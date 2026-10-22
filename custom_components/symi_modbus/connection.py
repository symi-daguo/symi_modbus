"""Modbus transport: persistent connections with reconnect for serial and TCP."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import serial

try:
    # Home Assistant 2026.7 deprecated pyserial-asyncio in favour of
    # pyserial-asyncio-fast, which offers the same API.
    import serial_asyncio_fast as serial_asyncio
except ImportError:  # pragma: no cover - fallback for older installs
    import serial_asyncio

from .const import FRAME_MBAP
from .frames import decode_response, expected_response_length

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 5
READ_TIMEOUT = 2
SERIAL_POST_WRITE_DELAY = 0.02
MAX_FRAME_SIZE = 260


def _serial_bytesize(value: int) -> int:
    """Map a configured data-bit count to the pyserial constant."""
    return {
        5: serial.FIVEBITS,
        6: serial.SIXBITS,
        7: serial.SEVENBITS,
        8: serial.EIGHTBITS,
    }.get(int(value), serial.EIGHTBITS)


def _serial_parity(value: str) -> int:
    """Map a configured parity letter to the pyserial constant."""
    normalized = (value or "N").strip().upper()
    if normalized in ("N", "NONE"):
        return serial.PARITY_NONE
    if normalized == "E":
        return serial.PARITY_EVEN
    if normalized == "O":
        return serial.PARITY_ODD
    return serial.PARITY_NONE


def _serial_stopbits(value: int) -> float:
    """Map a configured stop-bit count to the pyserial constant."""
    return serial.STOPBITS_TWO if int(value) == 2 else serial.STOPBITS_ONE


class ModbusConnection:
    """A single persistent Modbus connection (serial or TCP).

    The connection stays open between requests and is reopened on demand after
    a failure, so a device that reboots or a link that drops recovers without
    restarting Home Assistant.
    """

    def __init__(
        self,
        *,
        connection_type: str,
        host: str | None = None,
        port: int | str = 502,
        baudrate: int = 9600,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: int = 1,
        frame: str = FRAME_MBAP,
    ) -> None:
        """Initialize the connection parameters."""
        self._type = connection_type
        self._host = host
        self._port = port
        self._baudrate = baudrate
        self._bytesize = bytesize
        self._parity = parity
        self._stopbits = stopbits
        self._frame = frame

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()
        self._buffer = bytearray()

    @property
    def frame(self) -> str:
        """Return the frame format used by this connection."""
        return self._frame

    @property
    def is_connected(self) -> bool:
        """Return True when the transport is currently open."""
        return self._writer is not None and not self._writer.is_closing()

    async def async_close(self) -> None:
        """Close the transport and drop any buffered data."""
        writer, self._writer, self._reader = self._writer, None, None
        self._buffer.clear()
        if writer is None:
            return
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Closing Modbus connection failed", exc_info=True)

    async def _async_open(self) -> None:
        """Open the underlying transport."""
        if self._type == "tcp":
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, int(self._port)), CONNECT_TIMEOUT
            )
            _LOGGER.debug("Modbus TCP connected to %s:%s", self._host, self._port)
            return

        _LOGGER.debug(
            "Opening serial %s at %s %s%s%s (serial_asyncio from %s)",
            self._port,
            self._baudrate,
            self._bytesize,
            self._parity,
            self._stopbits,
            serial_asyncio.__file__,
        )
        self._reader, self._writer = await asyncio.wait_for(
            serial_asyncio.open_serial_connection(
                url=str(self._port),
                baudrate=self._baudrate,
                bytesize=_serial_bytesize(self._bytesize),
                parity=_serial_parity(self._parity),
                stopbits=_serial_stopbits(self._stopbits),
            ),
            CONNECT_TIMEOUT,
        )
        _LOGGER.debug("Serial %s opened", self._port)
        transport = self._writer.transport
        serial_port = transport.get_extra_info("serial")
        fileno = getattr(serial_port, "fileno", lambda: None)()
        target = ""
        if fileno is not None:
            try:
                target = os.readlink(f"/proc/self/fd/{fileno}")
            except OSError:
                target = "unknown"
        _LOGGER.debug(
            "Serial fd=%s -> %s (name=%s)",
            fileno,
            target,
            getattr(serial_port, "name", "?"),
        )

    async def async_request(self, payload: bytes, function: int) -> bytes | None:
        """Send a request and return the decoded response payload.

        Returns None when the device did not answer or answered with a frame
        that could not be decoded.
        """
        async with self._lock:
            if not self.is_connected:
                try:
                    await self._async_open()
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Modbus connect failed: %s", err)
                    return None

            try:
                assert self._writer is not None
                assert self._reader is not None
                self._writer.write(payload)
                await self._writer.drain()
                _LOGGER.debug("Sent %s byte(s): %s", len(payload), payload.hex(' '))

                if self._type == "serial":
                    await asyncio.sleep(SERIAL_POST_WRITE_DELAY)

                frame = await self._async_read_frame(function)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug(
                    "Modbus request failed: %s: %r",
                    type(err).__name__,
                    str(err),
                    exc_info=True,
                )
                await self.async_close()
                return None

            if frame is None:
                # A timeout or a closed peer leaves the transport in an unknown
                # state. Drop it so the next request starts on a fresh
                # connection instead of reusing a half open one.
                await self.async_close()
                return None

            decoded = decode_response(frame, self._frame)
            if decoded is None:
                _LOGGER.debug("Modbus response could not be decoded")
                await self.async_close()
                return None

            _, response_function, response_payload = decoded
            if response_function & 0x80:
                _LOGGER.debug(
                    "Modbus exception response: function %s, code %s",
                    response_function,
                    response_payload[0] if response_payload else "?",
                )
                return None
            if response_function != function:
                _LOGGER.debug(
                    "Modbus response function mismatch: expected %s, got %s",
                    function,
                    response_function,
                )
                await self.async_close()
                return None
            return response_payload

    async def _async_read_frame(self, function: int) -> bytes | None:
        """Read exactly one complete response frame from the transport.

        Bytes that belong to the next frame stay in the buffer, so a partial
        or coalesced TCP read does not corrupt the stream.
        """
        assert self._reader is not None

        while len(self._buffer) < MAX_FRAME_SIZE:
            try:
                chunk = await asyncio.wait_for(
                    self._reader.read(MAX_FRAME_SIZE), READ_TIMEOUT
                )
            except asyncio.TimeoutError:
                _LOGGER.debug(
                    "Read timed out after %ss, %s byte(s) buffered",
                    READ_TIMEOUT,
                    len(self._buffer),
                )
                return None
            if not chunk:
                # Peer closed the connection.
                _LOGGER.debug("Peer closed the connection")
                return None
            _LOGGER.debug("Read %s byte(s): %s", len(chunk), chunk.hex(" "))
            self._buffer.extend(chunk)

            expected = expected_response_length(bytes(self._buffer), self._frame, function)
            if expected is None or len(self._buffer) < expected:
                continue

            frame = bytes(self._buffer[:expected])
            del self._buffer[:expected]
            return frame

        return None
