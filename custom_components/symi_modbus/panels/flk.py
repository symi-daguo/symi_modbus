"""FLK (弗雷克) panel protocol.

The K7x wall panels speak Modbus RTU on RS-485, 9600 8N1. A key press is
reported by the panel itself with a write-single-register frame::

    [addr][0x06][reg hi][reg lo][data hi][data lo][CRC lo][CRC hi]

The register is 0x0033..0x003A for the buttons 1..8, the high data byte
holds the panel type (0x06 for the eight key panel, register 0x0040) and
the low byte the kind of press: 1..3 are single to triple click, 4 is a
long press down, 5 a long press release.

The indicator lights are a bit mask in register 0x0032, one bit per light.
There is no way to write a single light on its own, so the mask of a panel
is kept and written again on every change. The panel flashes the light of
a pressed key and then waits for the host to answer with the whole mask.

The address of a panel is set by its DIP switches and is the first byte of
every frame. There is no command that changes it.
"""
from __future__ import annotations

import logging

from ..const import DEFAULT_LED_FRAME_TYPE
from ..frames import crc16_fn
from .base import ButtonEvent, PanelProtocol

_LOGGER = logging.getLogger(__name__)

CMD_WRITE_SINGLE_REGISTER = 0x06

REG_INDICATOR = 0x0032
REG_BUTTON_FIRST = 0x0033
REG_BUTTON_LAST = 0x003A

FRAME_LENGTH = 8

# The panel type of the eight key panel (register 0x0040). Reports carry it
# in the high data byte, so it is learned and answered with the same value.
DEFAULT_PANEL_TYPE = 0x06

# A press in the default "click count" mode of register 0x004B. Code 0x05
# ends a long press that already reported 0x04, so it is left out: one
# physical press must not flip the light twice. The "button state" mode
# (0x004B = 1, codes 0x00/0x01) is not supported, the codes cannot be told
# apart from a click.
PRESS_CODES = frozenset({0x01, 0x02, 0x03, 0x04})


class FlkProtocol(PanelProtocol):
    """Protocol of the FLK (弗雷克) K7x panels."""

    brand = "flk"
    default_buttons = 8

    def __init__(self, led_frame_type: str = DEFAULT_LED_FRAME_TYPE) -> None:
        """Initialize the stream buffer and the state of the panels."""
        self._buffer = bytearray()
        # The bus manager passes the frame type to every brand. FLK has one
        # frame for the lights, the value is kept for a common constructor.
        self._led_frame_type = led_frame_type
        # The panel type learned from the reports, one per panel address.
        self._panel_types: dict[int, int] = {}
        # The last indicator mask written to a panel.
        self._masks: dict[int, int] = {}

    def build_led_frame(
        self,
        panel_id: int,
        button: int,
        state: bool,
        device_addr: int = 1,
        channel: int | None = None,
        code: int | None = None,
    ) -> bytes:
        """Build the frame that writes the indicator mask of a panel.

        The register holds all eight lights at once, so the states of the
        other buttons are sent along. The high data byte repeats the panel
        type the panel used in its last button report.
        """
        mask = self._masks.get(panel_id, 0)
        bit = 1 << ((button - 1) & 0x07)
        if state:
            mask |= bit
        else:
            mask &= ~bit & 0xFF
        self._masks[panel_id] = mask
        panel_type = self._panel_types.get(panel_id, DEFAULT_PANEL_TYPE)
        return self._build_write(
            panel_id, REG_INDICATOR, (panel_type << 8) | mask
        )

    @staticmethod
    def _build_write(panel_id: int, register: int, value: int) -> bytes:
        """Build a write-single-register frame."""
        body = [
            panel_id & 0xFF,
            CMD_WRITE_SINGLE_REGISTER,
            (register >> 8) & 0xFF,
            register & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ]
        return bytes(body + crc16_fn(body))

    def parse_frames(self, data: bytes) -> list[ButtonEvent]:
        """Parse the received bytes into button events.

        Every frame is eight bytes long and has no header or tail, so the
        checksum and the register are what a broken byte stream is aligned
        on. Bytes that may still start a frame are kept for the next chunk.
        """
        self._buffer.extend(data)
        events: list[ButtonEvent] = []

        offset = 0
        while offset + FRAME_LENGTH <= len(self._buffer):
            frame = bytes(self._buffer[offset : offset + FRAME_LENGTH])
            event = self._parse_frame(frame)
            if event is None:
                offset += 1
                continue
            events.append(event)
            offset += FRAME_LENGTH

        remaining = len(self._buffer) - offset
        keep = min(remaining, FRAME_LENGTH - 1)
        del self._buffer[: len(self._buffer) - keep]
        return events

    def _parse_frame(self, frame: bytes) -> ButtonEvent | None:
        """Turn one eight byte frame into a button event."""
        if frame[1] != CMD_WRITE_SINGLE_REGISTER:
            return None
        register = (frame[2] << 8) | frame[3]
        if not REG_BUTTON_FIRST <= register <= REG_BUTTON_LAST:
            # A read, a write to the lights or an answer of the host.
            return None
        expected = crc16_fn(frame[:-2])
        if frame[-2] != expected[0] or frame[-1] != expected[1]:
            return None

        code = frame[5]
        if code not in PRESS_CODES:
            _LOGGER.debug(
                "FLK panel %s reported the press code 0x%02X, it is not a press",
                frame[0],
                code,
            )
            return None

        panel_id = frame[0]
        button = register - REG_BUTTON_FIRST + 1
        self._panel_types[panel_id] = frame[4]
        return ButtonEvent(
            panel_id=panel_id,
            button=button,
            state=True,
            # The frame says which key was used, not which state the light
            # goes to. The light of the button is toggled.
            device_addr=panel_id,
            channel=button,
            code=code,
            is_toggle=True,
        )
