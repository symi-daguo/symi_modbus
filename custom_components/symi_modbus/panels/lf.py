"""LF (拉斐) panel protocol.

The panels report a button press with a fixed eight byte frame:

    [address][0x03][0x00][0x02][absolute key][button mask][CRC lo][CRC hi]

There is no frame tail, so the frames are cut by their fixed length. The
indicator lights are a bit mask in register 0x1008 that is written as a
whole, so the state of the other buttons has to be sent along.
"""
from __future__ import annotations

from ..const import LED_FRAME_REPORT
from ..frames import crc16_fn
from .base import ButtonEvent, PanelProtocol

CMD_READ = 0x03
CMD_WRITE = 0x06

REG_PANEL_ADDR = 0x1000
REG_PANEL_CONFIG = 0x1003
REG_LED_CONTROL = 0x1008
REG_SAVE_CONFIG = 0x100F

DEFAULT_PANEL_ADDR = 0x02

ACTIVE_FRAME_LENGTH = 8

# The host has to own the indicator lights and the panels have to report the
# button presses on their own.
CONFIG_RCU_ACTIVE = 0x0006

# Bit 8 enables the indicator lights of the panels with a dimmable backlight.
LED_BACKLIGHT_ENABLE = 0x0100

# The value that stores the configuration in the panel.
SAVE_CONFIG_VALUE = 0x00FE


class LfProtocol(PanelProtocol):
    """Protocol of the LF panels."""

    brand = "lf"
    default_buttons = 8

    def __init__(self, led_frame_type: str = LED_FRAME_REPORT) -> None:
        """Initialize the stream buffer and the known indicator light states."""
        self._buffer = bytearray()
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
        """Build the frame that drives the indicator light of a button.

        The register holds the state of all eight buttons of the panel, so the
        mask is built from the states that are known so far.
        """
        mask = self._masks.get(panel_id, 0)
        if state:
            mask |= 1 << (button - 1)
        else:
            mask &= ~(1 << (button - 1)) & 0xFF
        self._masks[panel_id] = mask

        # With no button lit the panel keeps its standby backlight, otherwise
        # the backlight bit has to be set for the lights to show up at all.
        value = (mask | LED_BACKLIGHT_ENABLE) if mask else LED_BACKLIGHT_ENABLE
        return self._build_write(panel_id, REG_LED_CONTROL, value)

    def prepare_frames(self, panel_ids: list[int]) -> list[bytes]:
        """Return the frames that put the panels into host controlled mode.

        Without that mode the panels keep the lights for themselves and ignore
        what the host writes.
        """
        frames: list[bytes] = []
        for panel_id in panel_ids:
            frames.append(
                self._build_write(panel_id, REG_PANEL_CONFIG, CONFIG_RCU_ACTIVE)
            )
            frames.append(
                self._build_write(panel_id, REG_SAVE_CONFIG, SAVE_CONFIG_VALUE)
            )
        return frames

    @staticmethod
    def _build_write(panel_id: int, register: int, value: int) -> bytes:
        """Build a write-single-register frame."""
        body = [
            panel_id & 0xFF,
            CMD_WRITE,
            (register >> 8) & 0xFF,
            register & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ]
        return bytes(body + crc16_fn(body))

    def parse_frames(self, data: bytes) -> list[ButtonEvent]:
        """Parse the received bytes into button events."""
        self._buffer.extend(data)
        events: list[ButtonEvent] = []

        offset = 0
        while offset + ACTIVE_FRAME_LENGTH <= len(self._buffer):
            frame = bytes(self._buffer[offset : offset + ACTIVE_FRAME_LENGTH])
            if self._is_active_frame(frame):
                button = self._mask_to_button(frame[5])
                if button is not None:
                    events.append(
                        ButtonEvent(panel_id=frame[0], button=button, state=True)
                    )
                offset += ACTIVE_FRAME_LENGTH
            else:
                offset += 1

        # Keep the bytes that may still be the start of a frame.
        remaining = len(self._buffer) - offset
        keep = min(remaining, ACTIVE_FRAME_LENGTH - 1)
        del self._buffer[: len(self._buffer) - keep]

        return events

    @staticmethod
    def _is_active_frame(frame: bytes) -> bool:
        """Return True when the frame is a button press of a panel."""
        if frame[1] != CMD_READ or frame[2] != 0x00 or frame[3] != 0x02:
            return False
        expected = crc16_fn(frame[:-2])
        return frame[-2] == expected[0] and frame[-1] == expected[1]

    @staticmethod
    def _mask_to_button(mask: int) -> int | None:
        """Return the button number of a single bit mask."""
        if mask == 0 or mask & (mask - 1):
            # No button or more than one button in the same frame.
            return None
        return mask.bit_length()
