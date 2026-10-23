"""Clowire (克伦威尔) panel protocol.

The panels use a Modbus like layout with an extra frame tail:

    [address][command][register hi][register lo][data hi][data lo]
    [CRC lo][CRC hi][0xAA]

The checksum is the Modbus CRC-16 over the first six bytes and the frame tail
sits behind the checksum, it is not part of it.
"""
from __future__ import annotations

from ..const import LED_FRAME_REPORT
from ..frames import crc16_fn
from .base import ButtonEvent, PanelProtocol

FRAME_TAIL = 0xAA
BROADCAST_ADDR = 0xFF
DEFAULT_PANEL_ADDR = 0x02

CMD_READ = 0x03
CMD_WRITE = 0x06
CMD_BUTTON_EVENT = 0x20
CMD_BATCH_CONTROL = 0x25

REG_BUTTON_S1 = 0x1011
REG_BUTTON_S8 = 0x1018
REG_BACKLIGHT = 0x1020
REG_LED1 = 0x1021
REG_LED8 = 0x1028
REG_LONG_PRESS = 0x2050

# The length of a regular frame and of the batch frame.
FRAME_LENGTH = 9
BATCH_FRAME_LENGTH = 11


class ClowireProtocol(PanelProtocol):
    """Protocol of the Clowire panels."""

    brand = "clowire"
    default_buttons = 8

    def __init__(self, led_frame_type: str = LED_FRAME_REPORT) -> None:
        """Initialize the protocol."""
        self._buffer = bytearray()

    def build_led_frame(
        self,
        panel_id: int,
        button: int,
        state: bool,
        device_addr: int = 1,
        channel: int | None = None,
    ) -> bytes:
        """Build the frame that drives the indicator light of a button.

        Every button has its own register, 0x1021 is the first one.
        """
        register = REG_LED1 + (button - 1)
        return self._build_write(panel_id, register, 0x0001 if state else 0x0000)

    @staticmethod
    def _build_write(panel_id: int, register: int, value: int) -> bytes:
        """Build a write-single-register frame with the frame tail."""
        body = [
            panel_id & 0xFF,
            CMD_WRITE,
            (register >> 8) & 0xFF,
            register & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ]
        return bytes(body + crc16_fn(body) + [FRAME_TAIL])

    def parse_frames(self, data: bytes) -> list[ButtonEvent]:
        """Parse the received bytes into button events."""
        self._buffer.extend(data)
        events: list[ButtonEvent] = []

        while True:
            tail = self._buffer.find(FRAME_TAIL)
            if tail < 0:
                break
            if tail < FRAME_LENGTH - 1:
                # Not enough bytes in front of the tail for a frame.
                del self._buffer[: tail + 1]
                continue

            frame = self._take_frame(tail)
            if frame is None:
                del self._buffer[: tail + 1]
                continue
            event = self._parse_frame(frame)
            if event is not None:
                events.append(event)

        return events

    def _take_frame(self, tail: int) -> bytes | None:
        """Return the frame that ends at the given tail position."""
        for length in (FRAME_LENGTH, BATCH_FRAME_LENGTH):
            if tail < length - 1:
                continue
            frame = bytes(self._buffer[tail - (length - 1) : tail + 1])
            if self._is_valid_frame(frame):
                del self._buffer[: tail + 1]
                return frame
        return None

    @staticmethod
    def _is_valid_frame(frame: bytes) -> bool:
        """Return True when the frame may be used.

        Panels of different vendors disagree on the checksum, so the command
        codes that carry a button event are accepted even when the checksum
        does not match.
        """
        command = frame[1]
        if command in (CMD_BUTTON_EVENT, CMD_READ):
            return True
        expected = crc16_fn(frame[:-3])
        return frame[-3] == expected[0] and frame[-2] == expected[1]

    @staticmethod
    def _parse_frame(frame: bytes) -> ButtonEvent | None:
        """Turn one complete frame into a button event."""
        command = frame[1]
        register = (frame[2] << 8) | frame[3]

        if command not in (CMD_BUTTON_EVENT, CMD_READ):
            return None

        if REG_BUTTON_S1 <= register <= REG_BUTTON_S8:
            # A click on one of the eight buttons. The panels report the
            # button in the register address, the data holds the click type.
            return ButtonEvent(
                panel_id=frame[0],
                button=register - REG_BUTTON_S1 + 1,
                state=True,
            )

        if register == REG_LONG_PRESS:
            # A long press carries the button in the high data byte and the
            # press or release in the low data byte.
            button = frame[4]
            low = frame[5]
            if low == 0x80:
                return ButtonEvent(panel_id=frame[0], button=button, state=True)
            if low == 0xFE:
                return ButtonEvent(panel_id=frame[0], button=button, state=False)

        return None
