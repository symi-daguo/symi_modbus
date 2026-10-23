"""The panel bus: one serial line that the panels of a brand share."""
from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from collections.abc import Callable
from time import monotonic

from homeassistant.core import HomeAssistant

from .base import ButtonEvent, PanelProtocol

try:
    # Home Assistant 2026.7 deprecated pyserial-asyncio in favour of
    # pyserial-asyncio-fast, which offers the same API.
    import serial_asyncio_fast as serial_asyncio
except ImportError:  # pragma: no cover - fallback for older installs
    import serial_asyncio

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 5
READ_CHUNK = 256
# The panels ask for at least fifty milliseconds between two commands.
SERIAL_POST_WRITE_DELAY = 0.05
RECONNECT_DELAY = 5

# A bus that does not work is opened again and again, so the message about it
# is written once a minute at most.
ERROR_LOG_INTERVAL = 60

# A bus echoes the frames we send. Those echoes carry the same address and
# state as the frame we sent, so they are recognised and dropped instead of
# being reported as a button press.
ECHO_WINDOW = 0.15

# Upper bound of the send queue. A burst of indicator updates must not let
# the queue grow without limit.
MAX_QUEUE = 500

# How many chunks of the line are kept for the diagnostics. The customer can
# look at the raw data of the bus there, without the log filling up.
RECENT_CHUNKS = 40

# The line is shared with the panels. Nothing is written while a panel may
# still be sending, otherwise both are damaged.
LINE_QUIET = 0.05


def serial_port_holders(
    port: str, exclude: set[tuple[str, str]] | None = None
) -> int:
    """Return how many programs hold the serial port open.

    A serial port can be opened by more than one program, the bytes are then
    split between them and nobody receives all of them. The handles in
    ``exclude`` are not counted, they belong to the caller itself.
    """
    target = str(port)
    exclude = exclude or set()
    count = 0
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        fd_dir = f"/proc/{pid}/fd"
        try:
            handles = os.listdir(fd_dir)
        except OSError:
            continue
        for handle in handles:
            try:
                if os.readlink(f"{fd_dir}/{handle}") != target:
                    continue
            except OSError:
                continue
            if (pid, handle) in exclude:
                continue
            count += 1
            break
    return count


class PanelConnection:
    """A serial line that talks to the panels of one brand.

    The connection reads the bus in the background and hands every button
    event to the callback. Frames that are sent are queued and written one
    after the other, so a burst of indicator updates keeps its order.
    """

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        port: str,
        protocol: PanelProtocol,
        on_event: Callable[[ButtonEvent], None],
        baudrate: int = 9600,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: int = 1,
        on_state: Callable[[bool], None] | None = None,
    ) -> None:
        """Initialize the panel bus."""
        self._hass = hass
        self._port = port
        self._protocol = protocol
        self._on_event = on_event
        self._on_state = on_state
        self._baudrate = baudrate
        self._bytesize = bytesize
        self._parity = parity
        self._stopbits = stopbits

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._open_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._queue: deque[tuple[bytes, tuple[int, int, bool] | None]] = deque()
        self._queue_event = asyncio.Event()
        # The echoes of the frames we sent: panel, channel, code, time.
        self._echoes: list[tuple[int, int, int, float]] = []
        # When the last data arrived, so the line can be left alone.
        self._last_received_at: float | None = None
        self._seen_data = False
        self._tasks: list[asyncio.Task] = []
        self._last_error_at = 0.0
        # The last chunks of the line, for the diagnostics.
        self._recent: deque[str] = deque(maxlen=RECENT_CHUNKS)

    @property
    def is_connected(self) -> bool:
        """Return True when the serial port is open."""
        return self._writer is not None and not self._writer.is_closing()

    async def async_start(self) -> None:
        """Open the bus and start reading from it."""
        self._tasks.append(asyncio.create_task(self._async_read_loop()))
        self._tasks.append(asyncio.create_task(self._async_write_loop()))

    async def async_stop(self) -> None:
        """Stop the bus and close the serial port."""
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        await self._async_close()

    async def _async_close(self) -> None:
        """Close the serial port."""
        writer, self._writer, self._reader = self._writer, None, None
        if writer is None:
            return
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Closing the panel bus failed", exc_info=True)
        if self._on_state is not None:
            self._on_state(False)

    async def _async_open(self) -> None:
        """Open the serial port."""
        from ..connection import serial_bytesize, serial_parity, serial_stopbits

        try:
            self._reader, self._writer = await asyncio.wait_for(
                serial_asyncio.open_serial_connection(
                    url=str(self._port),
                    baudrate=self._baudrate,
                    bytesize=serial_bytesize(self._bytesize),
                    parity=serial_parity(self._parity),
                    stopbits=serial_stopbits(self._stopbits),
                ),
                CONNECT_TIMEOUT,
            )
        except Exception as err:  # noqa: BLE001
            self._log_error("cannot be opened", err)
            raise
        _LOGGER.debug("Panel bus %s opened", self._port)
        # Reading the open files of the other programs is a blocking call, so
        # it belongs in the executor.
        own = self.own_handle()
        holders = await self._hass.async_add_executor_job(
            serial_port_holders, str(self._port), own
        )
        if holders > 0:
            _LOGGER.error(
                "The serial port %s is also open by %s other programs, the bytes"
                " are split between them and the panels cannot be read reliably",
                self._port,
                holders,
            )
            if self._on_state is not None:
                self._on_state(False)
            return
        if self._on_state is not None:
            self._on_state(True)

    def recent_traffic(self) -> list[str]:
        """Return the last chunks of the line.

        The chunks are kept for the diagnostics, so the raw data of the bus can
        be looked at without filling the log.
        """
        return list(self._recent)

    def _remember(self, direction: str, data: bytes) -> None:
        """Keep a chunk of the line for the diagnostics."""
        self._recent.append(f"{direction} {data.hex(' ').upper()}")

    def _log_error(self, message: str, err: Exception) -> None:
        """Tell in the log that the bus does not work.

        The bus is opened again and again, so the message is written once a
        minute at most.
        """
        now = monotonic()
        if now - self._last_error_at < ERROR_LOG_INTERVAL:
            return
        self._last_error_at = now
        _LOGGER.warning("The panel bus %s %s: %s", self._port, message, err)

    def own_handle(self) -> set[tuple[str, str]]:
        """Return the handle of this connection, so it can be left out."""
        if self._writer is None:
            return set()
        transport = self._writer.transport
        serial_port = transport.get_extra_info("serial")
        fileno = getattr(serial_port, "fileno", lambda: None)()
        if fileno is None:
            return set()
        return {(str(os.getpid()), str(fileno))}

    async def _async_read_loop(self) -> None:
        """Read the bus and report the button events."""
        while True:
            try:
                async with self._open_lock:
                    if not self.is_connected:
                        await self._async_open()
                assert self._reader is not None
                chunk = await self._reader.read(READ_CHUNK)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                if self.is_connected:
                    # The port was open and stopped working, the reason is
                    # worth knowing.
                    self._log_error("stopped reading", err)
                await self._async_close()
                await asyncio.sleep(RECONNECT_DELAY)
                continue

            if not chunk:
                await self._async_close()
                await asyncio.sleep(RECONNECT_DELAY)
                continue

            self._handle_chunk(chunk)

    def _handle_chunk(self, chunk: bytes) -> None:
        """Parse the received bytes and report the button events."""
        self._last_received_at = monotonic()
        self._remember("<", chunk)
        if not self._seen_data:
            self._seen_data = True
            _LOGGER.info(
                "Panel bus %s received its first data: %s",
                self._port,
                chunk[:64].hex(" ").upper(),
            )
        _LOGGER.debug(
            "Panel bus %s received %s byte(s): %s",
            self._port,
            len(chunk),
            chunk[:64].hex(" ").upper(),
        )
        for event in self._protocol.parse_frames(chunk):
            if self._is_echo(event):
                continue
            self._on_event(event)

    def _is_echo(self, event: ButtonEvent) -> bool:
        """Return True when the event is the echo of a frame we sent.

        The echo carries the channel and the code of the frame that was sent,
        so those are compared. The state is not used, a panel can use a code of
        its own for the state and then the state of the echo does not tell
        which frame it belongs to.
        """
        now = monotonic()
        self._echoes = [echo for echo in self._echoes if now - echo[3] < ECHO_WINDOW]
        for index, (panel_id, channel, code, sent_at) in enumerate(self._echoes):
            if (
                panel_id == event.panel_id
                and channel == event.button
                and code == event.code
                and now - sent_at < ECHO_WINDOW
            ):
                del self._echoes[index]
                return True
        return False

    async def async_write_led(
        self,
        panel_id: int,
        button: int,
        state: bool,
        device_addr: int = 1,
        channel: int | None = None,
        code: int | None = None,
    ) -> None:
        """Queue the frame that drives the indicator light of a button."""
        frame = self._protocol.build_led_frame(
            panel_id, button, state, device_addr, channel, code
        )
        # The echo of the frame carries the channel and the code that were sent,
        # so the echo is told apart by them. Comparing the state would not work
        # for a panel that uses a code of its own for the state.
        used_channel = button if channel is None else channel
        used_code = (1 if state else 0) if code is None else code
        await self._async_enqueue(frame, (panel_id, used_channel, used_code))

    async def async_write_raw(self, frame: bytes) -> None:
        """Queue a frame that is not a button update."""
        await self._async_enqueue(frame, None)

    async def _async_enqueue(
        self, frame: bytes, echo: tuple[int, int, int] | None
    ) -> None:
        """Put a frame into the send queue."""
        async with self._write_lock:
            if len(self._queue) >= MAX_QUEUE:
                # The queue is full, the oldest update is the least important.
                self._queue.popleft()
            self._queue.append((frame, echo))
        self._queue_event.set()

    async def _async_wait_for_quiet(self) -> None:
        """Wait until the line is quiet.

        The panels share the line with us. When a panel sends its report while
        a frame of ours goes out, both are damaged and the panel does not get
        the frame, so nothing is written while the line is still busy.
        """
        if self._last_received_at is None:
            return
        quiet = LINE_QUIET - (monotonic() - self._last_received_at)
        if quiet > 0:
            await asyncio.sleep(quiet)

    async def _async_write_loop(self) -> None:
        """Write the queued frames one after the other."""
        while True:
            await self._queue_event.wait()
            async with self._write_lock:
                if not self._queue:
                    self._queue_event.clear()
                    continue
                frame, echo = self._queue.popleft()

            try:
                async with self._open_lock:
                    if not self.is_connected:
                        await self._async_open()
                assert self._writer is not None
                await self._async_wait_for_quiet()
                self._writer.write(frame)
                await self._writer.drain()
                self._remember(">", frame)
                if echo is not None:
                    self._echoes.append((*echo, monotonic()))
                    _LOGGER.debug(
                        "Panel bus %s: the light of panel %s channel %s is set "
                        "with the code %s",
                        self._port,
                        echo[0],
                        echo[1],
                        echo[2],
                    )
                _LOGGER.debug(
                    "Panel bus %s: sent %s", self._port, frame.hex(" ").upper()
                )
                await asyncio.sleep(SERIAL_POST_WRITE_DELAY)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Panel bus %s write failed: %s", self._port, err)
                await self._async_close()

            if not self._queue:
                self._queue_event.clear()
