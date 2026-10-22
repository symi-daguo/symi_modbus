"""End-to-end tests for the Modbus hub against a simulated device."""
from __future__ import annotations

import asyncio

import pytest

from custom_components.symi_modbus import connection as connection_module
from custom_components.symi_modbus.const import (
    CONF_COIL_COUNT,
    CONF_FRAME,
    CONF_HOST,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    CONF_SLAVES,
    CONF_TCP,
    CONF_PORT,
    CONF_TYPE,
    DEFAULT_SCAN_INTERVAL,
    FRAME_RTU,
)
from custom_components.symi_modbus.connection import ModbusConnection
from custom_components.symi_modbus.frames import (
    FUNCTION_READ_COILS,
    FUNCTION_WRITE_MULTIPLE_COILS,
    FUNCTION_WRITE_SINGLE_COIL,
    build_read_request,
    crc16_fn,
    decode_response,
    expected_request_length,
)
from custom_components.symi_modbus.modbus import ModbusHub


class FakeConfigEntry:
    """Minimal stand-in for a Home Assistant config entry."""

    def __init__(self, data: dict, options: dict | None = None) -> None:
        """Store the entry data."""
        self.data = data
        self.options = options or {}


class FakeHass:
    """Minimal stand-in for the Home Assistant core object."""

    def __init__(self) -> None:
        """Prepare the event bookkeeping used by the poll scheduler."""
        self.timers: list = []
        self.loop = asyncio.get_event_loop()

    def async_create_timer(self, *args, **kwargs):  # pragma: no cover - unused
        """Not used in these tests."""
        raise NotImplementedError

    async def async_add_executor_job(self, func, *args):
        """Run a blocking function inline."""
        return func(*args)


class FakeDevice:
    """A Modbus device that answers reads and accepts writes."""

    def __init__(self, slaves: dict[int, int]) -> None:
        """Prepare the coil state of every slave."""
        self.slaves = slaves
        self.coils: dict[int, dict[int, bool]] = {
            slave: {index: False for index in range(count)} for slave, count in slaves.items()
        }
        self.writes: list[tuple[int, int, bool]] = []
        self.requests = 0
        self.frame = FRAME_RTU
        # When muted the device receives requests but never answers.
        self.mute = False

    def handle(self, data: bytes) -> bytes | None:
        """Answer one RTU request."""
        self.requests += 1
        if self.mute:
            return None
        if len(data) < 2:
            return None
        slave = data[0]
        function = data[1]
        if slave not in self.coils:
            return None

        if function == FUNCTION_READ_COILS:
            address = (data[2] << 8) | data[3]
            count = (data[4] << 8) | data[5]
            bits = bytearray((count + 7) // 8)
            for index in range(count):
                coil = address + index
                if self.coils[slave].get(coil):
                    bits[index // 8] |= 1 << (index % 8)
            payload = bytes([slave, function, len(bits)]) + bytes(bits)
            return payload + bytes(crc16_fn(payload))

        if function == FUNCTION_WRITE_SINGLE_COIL:
            address = (data[2] << 8) | data[3]
            value = data[4] == 0xFF
            self.coils[slave][address] = value
            self.writes.append((slave, address, value))
            payload = bytes(data[:6])
            return payload + bytes(crc16_fn(payload))

        if function == FUNCTION_WRITE_MULTIPLE_COILS:
            address = (data[2] << 8) | data[3]
            count = (data[4] << 8) | data[5]
            byte_count = data[6]
            packed = data[7 : 7 + byte_count]
            for index in range(count):
                byte_index = index // 8
                if byte_index >= len(packed):
                    break
                if packed[byte_index] >> (index % 8) & 1:
                    self.coils[slave][address + index] = True
                    self.writes.append((slave, address + index, True))
                else:
                    self.coils[slave][address + index] = False
                    self.writes.append((slave, address + index, False))
            payload = bytes([slave, function]) + bytes(data[2:6])
            return payload + bytes(crc16_fn(payload))

        return None


async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, device: FakeDevice) -> None:
    """Serve RTU requests on one open TCP connection."""
    buffer = bytearray()
    try:
        while True:
            chunk = await reader.read(256)
            if not chunk:
                return
            buffer.extend(chunk)
            expected = expected_request_length(bytes(buffer), device.frame)
            if expected is None or len(buffer) < expected:
                continue
            request = bytes(buffer[:expected])
            del buffer[:expected]
            response = device.handle(request)
            if response is None:
                continue
            writer.write(response)
            await writer.drain()
    except (asyncio.CancelledError, ConnectionResetError):
        return
    finally:
        writer.close()


async def _start_server(device: FakeDevice) -> asyncio.AbstractServer:
    """Start a TCP server that answers like the fake device."""

    async def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _handle_client(reader, writer, device)

    return await asyncio.start_server(on_connect, host="127.0.0.1", port=0)


@pytest.mark.asyncio
async def test_hub_polls_every_slave() -> None:
    """Every slave of the master is polled and its states are published."""
    device = FakeDevice({10: 8, 11: 8})
    server = await _start_server(device)
    port = server.sockets[0].getsockname()[1]

    entry = FakeConfigEntry(
        {
            CONF_TYPE: CONF_TCP,
            CONF_NAME: "test",
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            CONF_COIL_COUNT: 8,
            CONF_SLAVES: {"10": {"start": 0, "count": 8}, "11": {"start": 0, "count": 8}},
            CONF_HOST: "127.0.0.1",
            CONF_PORT: port,
            CONF_FRAME: FRAME_RTU,
        }
    )
    hub = ModbusHub(FakeHass(), entry)
    await hub.async_setup()
    hub.register_slaves(entry.data[CONF_SLAVES])

    try:
        await hub.async_poll_slaves()
        assert device.requests == 2
        assert set(hub._slave_data) == {10, 11}

        await hub.write_coil(10, 3, True)
        assert device.writes[-1] == (10, 3, True)
    finally:
        await hub.async_stop()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_hub_survives_a_failing_slave() -> None:
    """One silent slave does not stop the other slaves from updating."""
    device = FakeDevice({10: 4})
    server = await _start_server(device)
    port = server.sockets[0].getsockname()[1]

    entry = FakeConfigEntry(
        {
            CONF_TYPE: CONF_TCP,
            CONF_NAME: "test",
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            CONF_COIL_COUNT: 4,
            CONF_SLAVES: {"10": {"start": 0, "count": 4}, "99": {"start": 0, "count": 4}},
            CONF_HOST: "127.0.0.1",
            CONF_PORT: port,
            CONF_FRAME: FRAME_RTU,
        }
    )
    hub = ModbusHub(FakeHass(), entry)
    await hub.async_setup()
    hub.register_slaves(entry.data[CONF_SLAVES])

    try:
        await hub.async_poll_slaves()
        # The responding slave still produced state.
        assert 10 in hub._slave_data
    finally:
        await hub.async_stop()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_hub_reconnects_after_the_link_drops(monkeypatch: pytest.MonkeyPatch) -> None:
    """The hub reconnects on its own after the link was lost."""
    # Shorten the read timeout so the test does not wait for the real one.
    monkeypatch.setattr(connection_module, "READ_TIMEOUT", 0.2)

    device = FakeDevice({10: 4})
    # The device stops answering without dropping the connection.
    device.mute = True
    server = await _start_server(device)
    port = server.sockets[0].getsockname()[1]

    entry = FakeConfigEntry(
        {
            CONF_TYPE: CONF_TCP,
            CONF_NAME: "test",
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            CONF_COIL_COUNT: 4,
            CONF_SLAVES: {"10": {"start": 0, "count": 4}},
            CONF_HOST: "127.0.0.1",
            CONF_PORT: port,
            CONF_FRAME: FRAME_RTU,
        }
    )
    hub = ModbusHub(FakeHass(), entry)
    await hub.async_setup()
    hub.register_slaves(entry.data[CONF_SLAVES])

    availability: list[bool] = []
    hub.add_availability_callback(availability.append)

    try:
        # The device is muted, so the first poll times out.
        await hub.async_poll_slaves()
        assert hub._slave_data == {}
        assert availability == [False]

        # The device answers again on the same connection.
        device.mute = False
        await hub.async_poll_slaves()
        assert 10 in hub._slave_data
        assert availability == [False, True]

        # The hub keeps the connection open between polls.
        assert hub._connection.is_connected
    finally:
        await hub.async_stop()
        server.close()


@pytest.mark.asyncio
async def test_hub_rebuilds_a_dropped_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connection that was dropped is rebuilt on the next request."""
    monkeypatch.setattr(connection_module, "READ_TIMEOUT", 0.2)

    device = FakeDevice({10: 4})
    server = await _start_server(device)
    port = server.sockets[0].getsockname()[1]

    entry = FakeConfigEntry(
        {
            CONF_TYPE: CONF_TCP,
            CONF_NAME: "test",
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            CONF_COIL_COUNT: 4,
            CONF_SLAVES: {"10": {"start": 0, "count": 4}},
            CONF_HOST: "127.0.0.1",
            CONF_PORT: port,
            CONF_FRAME: FRAME_RTU,
        }
    )
    hub = ModbusHub(FakeHass(), entry)
    await hub.async_setup()
    hub.register_slaves(entry.data[CONF_SLAVES])

    try:
        await hub.async_poll_slaves()
        assert 10 in hub._slave_data
        assert hub._connection.is_connected

        # The peer goes away; the hub notices on the next request.
        await hub._connection.async_close()
        assert not hub._connection.is_connected

        await hub.async_poll_slaves()
        assert 10 in hub._slave_data
        # The connection was opened again.
        assert hub._connection.is_connected
    finally:
        await hub.async_stop()
        server.close()


@pytest.mark.asyncio
async def test_a_timeout_drops_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """A request that times out must not reuse the half open connection.

    A device that reboots leaves the socket open on our side while the peer is
    gone. Reusing that socket would block the integration forever, so a failed
    request has to close the transport.
    """
    monkeypatch.setattr(connection_module, "READ_TIMEOUT", 0.2)

    device = FakeDevice({10: 4})
    device.mute = True
    server = await _start_server(device)
    port = server.sockets[0].getsockname()[1]

    connection = ModbusConnection(
        connection_type="tcp", host="127.0.0.1", port=port, frame=FRAME_RTU
    )
    request = build_read_request(10, FUNCTION_READ_COILS, 0, 4, FRAME_RTU)

    try:
        assert await connection.async_request(request, FUNCTION_READ_COILS) is None
        # The transport was closed instead of being kept for the next request.
        assert not connection.is_connected
    finally:
        await connection.async_close()
        server.close()
