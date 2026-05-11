"""Symi Modbus integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from time import monotonic
from typing import Callable, List, Optional

import serial
import serial_asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_DELAY,
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_TYPE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_PARITY,
    CONF_SERIAL,
    CONF_STOPBITS,
    CONF_TCP,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_DELAY_MS,
)
from .crc16 import crc16_fn

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 5
READ_TIMEOUT = 2
SERIAL_POST_WRITE_DELAY = 0.02
CRC_WARN_INTERVAL = 60.0


def _serial_bytesize(value: int) -> int:
    return {
        5: serial.FIVEBITS,
        6: serial.SIXBITS,
        7: serial.SEVENBITS,
        8: serial.EIGHTBITS,
    }.get(int(value), serial.EIGHTBITS)


def _serial_parity(value: str) -> int:
    v = (value or "N").strip().upper()
    if v in ("N", "NONE"):
        return serial.PARITY_NONE
    if v == "E":
        return serial.PARITY_EVEN
    if v == "O":
        return serial.PARITY_ODD
    return serial.PARITY_NONE


def _serial_stopbits(value: int) -> float:
    return serial.STOPBITS_TWO if int(value) == 2 else serial.STOPBITS_ONE


class ModbusHub:
    """Async Modbus RTU over TCP or serial (one hub per config entry)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the Modbus hub."""
        self._hass = hass
        self._entry = entry
        self._config = entry.data
        self._name = self._config[CONF_NAME]
        self._type = self._config[CONF_TYPE]
        self._lock = asyncio.Lock()
        self._callbacks: List[Callable] = []
        self._availability_callbacks: List[Callable[[bool], None]] = []
        self._scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL,
            self._config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        self._delay = self._config.get(CONF_DELAY, DEFAULT_DELAY_MS)
        self._slave_data: dict = {}
        self._slaves_to_poll: dict = {}
        self._unsub_poll = None
        self._in_error = False
        self._comm_ok = True
        self._crc_last_log: dict[str, float] = {}
        self._ascii_warned = False

        if self._type == CONF_TCP:
            self._host = self._config[CONF_HOST]
            self._port = int(self._config.get(CONF_PORT, 502))
        elif self._type == CONF_SERIAL:
            self._port = self._config[CONF_PORT]
            self._baudrate = int(self._config.get(CONF_BAUDRATE, 9600))
            self._bytesize = int(self._config.get(CONF_BYTESIZE, 8))
            self._parity = str(self._config.get(CONF_PARITY, "N"))
            self._stopbits = int(self._config.get(CONF_STOPBITS, 1))
            self._rtu = self._config.get(CONF_METHOD, "rtu") == "rtu"

    @property
    def name(self) -> str:
        """Return the name of this hub."""
        return self._name

    @property
    def connection_type(self) -> str:
        """Return connection type key (tcp / serial)."""
        return self._type

    def add_callback(self, callback_func: Callable) -> None:
        """Register a state callback function."""
        self._callbacks.append(callback_func)

    def remove_callback(self, callback_func: Callable) -> None:
        """Remove a state callback registered earlier."""
        try:
            self._callbacks.remove(callback_func)
        except ValueError:
            pass

    def add_availability_callback(self, callback_func: Callable[[bool], None]) -> None:
        """Register callback for transport availability (True = link up)."""
        self._availability_callbacks.append(callback_func)

    def remove_availability_callback(self, callback_func: Callable[[bool], None]) -> None:
        """Remove an availability callback registered earlier."""
        try:
            self._availability_callbacks.remove(callback_func)
        except ValueError:
            pass

    def _notify_availability(self, available: bool) -> None:
        if self._comm_ok == available:
            return
        self._comm_ok = available
        for cb in self._availability_callbacks:
            try:
                cb(available)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Availability callback failed")

    def _log_error(self, error_text: str, error_state: bool = True) -> None:
        """Log error transitions without repeating the same message every poll."""
        if self._in_error != error_state:
            if error_state:
                _LOGGER.error("%s (%s)", error_text, self._name)
            else:
                _LOGGER.info("%s (%s)", error_text, self._name)
            self._in_error = error_state

    def _throttled_crc_warning(self, key: str, message: str) -> None:
        now = monotonic()
        last = self._crc_last_log.get(key, 0.0)
        if now - last >= CRC_WARN_INTERVAL:
            self._crc_last_log[key] = now
            _LOGGER.warning("%s (%s)", message, self._name)

    async def _async_close_writer(self, writer: Optional[asyncio.StreamWriter]) -> None:
        if writer is None:
            return
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass

    async def async_setup(self) -> bool:
        """Set up the modbus hub."""
        _LOGGER.debug("Setting up Modbus hub %s (%s)", self._name, self._type)

        if self._type == CONF_SERIAL and not self._rtu and not self._ascii_warned:
            _LOGGER.warning(
                "Serial method is not RTU; ASCII framing is not implemented - using RTU frames (%s)",
                self._name,
            )
            self._ascii_warned = True

        self._unsub_poll = async_track_time_interval(
            self._hass,
            self.async_poll_slaves,
            timedelta(seconds=self._scan_interval),
        )
        return True

    async def async_send(self, data: list[int]) -> Optional[bytes]:
        """Send a Modbus RTU frame and read the response."""
        writer: Optional[asyncio.StreamWriter] = None
        payload = bytes(data)

        try:
            if self._type == CONF_TCP:
                coro = asyncio.open_connection(self._host, self._port)
                reader, writer = await asyncio.wait_for(coro, CONNECT_TIMEOUT)
            elif self._type == CONF_SERIAL:
                reader, writer = await asyncio.wait_for(
                    serial_asyncio.open_serial_connection(
                        url=self._port,
                        baudrate=self._baudrate,
                        bytesize=_serial_bytesize(self._bytesize),
                        parity=_serial_parity(self._parity),
                        stopbits=_serial_stopbits(self._stopbits),
                    ),
                    CONNECT_TIMEOUT,
                )
            else:
                self._log_error(f"Unsupported connection type: {self._type}")
                self._notify_availability(False)
                return None

            writer.write(payload)
            await writer.drain()

            if self._type == CONF_SERIAL:
                await asyncio.sleep(SERIAL_POST_WRITE_DELAY)

            buf = await asyncio.wait_for(reader.read(256), READ_TIMEOUT)
            if len(buf) > 2:
                self._log_error("Connection restored", error_state=False)
                self._notify_availability(True)
                return buf

            self._log_error("Received insufficient data from device")
            self._notify_availability(False)
            return None

        except TimeoutError:
            self._log_error("Response timed out")
            self._notify_availability(False)
            return None
        except Exception as err:  # noqa: BLE001
            self._log_error(f"{self._type.upper()} communication failed: {err}")
            self._notify_availability(False)
            return None
        finally:
            await self._async_close_writer(writer)

    def register_slaves_to_poll(self, slave: int, addresses: list[int]) -> None:
        """Register slave unit and coil addresses to poll."""
        if slave not in self._slaves_to_poll:
            self._slaves_to_poll[slave] = {"addresses": []}

        for address in addresses:
            if address not in self._slaves_to_poll[slave]["addresses"]:
                self._slaves_to_poll[slave]["addresses"].append(address)

        self._slaves_to_poll[slave]["start"] = min(self._slaves_to_poll[slave]["addresses"])
        max_addr = max(self._slaves_to_poll[slave]["addresses"])
        self._slaves_to_poll[slave]["count"] = (
            max_addr - self._slaves_to_poll[slave]["start"] + 1
        )

        _LOGGER.debug(
            "Registered polling for slave %s, addresses: %s",
            slave,
            self._slaves_to_poll[slave]["addresses"],
        )

    async def async_req_state(self, slave: int) -> Optional[bytes]:
        """Request coil states from a slave."""
        start = self._slaves_to_poll[slave]["start"]
        count = self._slaves_to_poll[slave]["count"]

        data = [slave, 1, 0, start, 0, count]
        for crc in crc16_fn(data):
            data.append(crc)

        async with self._lock:
            return await self.async_send(data)

    def handle_state(self, data: bytes) -> bool:
        """Process state data from response."""
        if len(data) < 3 or data[1] != 1:
            return False

        slave = data[0]
        if slave not in self._slaves_to_poll:
            return False

        states: dict[int, bool] = {}
        start = self._slaves_to_poll[slave]["start"]
        for i in range(data[2]):
            bits = data[i + 3]
            for j in range(8):
                addr = start + j + i * 8
                states[addr] = bool(bits >> j & 0x01)

        self._slave_data[slave] = states

        for callback_func in self._callbacks:
            callback_func(states, slave)

        return True

    def check_crc(self, data: bytes) -> bool:
        """Check CRC of response data."""
        if len(data) < 3:
            return False
        crc = crc16_fn(data[:-2])
        return (data[-2] == crc[0]) & (data[-1] == crc[1])

    async def async_poll_slaves(self, now: Optional[object] = None) -> None:
        """Poll all registered slaves."""
        for slave in self._slaves_to_poll:
            response = await self.async_req_state(slave)

            if response is None:
                continue

            if not self.check_crc(response):
                self._throttled_crc_warning(
                    f"slave-{slave}",
                    f"CRC check failed for slave {slave}",
                )
                continue

            self.handle_state(response[:-2])

            if self._delay > 0:
                await asyncio.sleep(self._delay / 1000)

    async def write_coil(self, slave: int, address: int, value: bool) -> bool:
        """Write to a coil."""
        data = [slave, 5, 0, address, 0, 0]
        if value:
            data[4] = 0xFF

        for crc in crc16_fn(data):
            data.append(crc)

        async with self._lock:
            response = await self.async_send(data)
            if response is None:
                return False

            if not self.check_crc(response):
                self._throttled_crc_warning("write", "CRC check failed for write response")
                return False

            if slave in self._slave_data and address in self._slave_data[slave]:
                self._slave_data[slave][address] = value

            return True

    async def async_stop(self, event: Optional[object] = None) -> None:
        """Stop the hub."""
        if self._unsub_poll is not None:
            self._unsub_poll()
            self._unsub_poll = None
