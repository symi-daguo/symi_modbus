"""Symi (亖米) panel protocol.

The panels speak a light weight framed protocol on RS-485:

    [0x7E][addr][type][len][device type][brand][device][channel]
    [room][room type][room id][op code][op info...][CRC8][0x7D]

The CRC is a CRC-8 with polynomial 0x07 over everything except the CRC byte
and the frame tail.
"""
from __future__ import annotations

import logging

from ..const import LED_FRAME_REPORT, LED_FRAME_SET
from .base import ButtonEvent, PanelProtocol

_LOGGER = logging.getLogger(__name__)

FRAME_HEADER = 0x7E
FRAME_TAIL = 0x7D

DATA_TYPE_SET = 0x03
DATA_TYPE_REPORT = 0x04
DATA_TYPE_STATUS = 0x05

DEVICE_TYPE_LIGHT = 0x01
DEVICE_TYPE_SCENE = 0x07

LIGHT_OP_SINGLE = 0x00
LIGHT_OP_MULTI = 0x05

MIN_FRAME_LEN = 15
MAX_FRAME_LEN = 64

# The channel of the backlight, it is not a regular button.
BACKLIGHT_BUTTON = 15


def calculate_crc8(body: bytes) -> int:
    """Return the CRC-8 (polynomial 0x07) of the frame body."""
    crc = 0
    for byte in body:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


class SymiProtocol(PanelProtocol):
    """Protocol of the Symi panels."""

    brand = "symi"
    default_buttons = 8

    def __init__(self, led_frame_type: str = LED_FRAME_REPORT) -> None:
        """Initialize the stream buffer and the kind of feedback frame."""
        self._buffer = bytearray()
        self._led_frame_type = led_frame_type
        # The addresses of the panels on the line. A frame that was damaged on
        # the line carries the address of another panel, and that is how it is
        # told apart from a frame of a panel with a broken checksum.
        self.known_addresses: set[int] = set()

    def _fits_another_panel(self, frame: bytes) -> bool:
        """Return whether the checksum of the frame fits another panel.

        Two panels that report at the same time, or a panel that reports while
        a frame of ours goes out, damage each other on the line. The address
        byte of the damaged frame then belongs to the other panel, and so does
        its checksum. Such a frame must not be taken for a button of this
        panel.
        """
        body = bytearray(frame[:-2])
        for address in self.known_addresses:
            body[1] = address
            if calculate_crc8(bytes(body)) == frame[-2]:
                return True
        return False

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

        The protocol document asks for a report frame, the address fields have
        to be the ones the panel used in its button event, otherwise the
        panel ignores the frame and the light stays dark.
        """
        data_type = (
            DATA_TYPE_SET if self._led_frame_type == LED_FRAME_SET else DATA_TYPE_REPORT
        )
        body = bytes(
            [
                FRAME_HEADER,
                panel_id & 0xFF,
                data_type,
                0x0F,
                DEVICE_TYPE_LIGHT,
                0x00,
                device_addr & 0xFF,
                (button if channel is None else channel) & 0xFF,
                0x00,
                0x00,
                0x00,
                LIGHT_OP_SINGLE,
                (0x01 if state else 0x00) if code is None else code & 0xFF,
            ]
        )
        return body + bytes([calculate_crc8(body), FRAME_TAIL])

    def parse_frames(self, data: bytes) -> list[ButtonEvent]:
        """Parse the received bytes into button events."""
        self._buffer.extend(data)
        events: list[ButtonEvent] = []

        while self._buffer:
            start = self._buffer.find(FRAME_HEADER)
            if start < 0:
                # No frame start in sight, the noise cannot become a frame.
                self._buffer.clear()
                break
            if start > 0:
                del self._buffer[:start]
            if len(self._buffer) < 4:
                break

            data_len = self._buffer[3]
            if data_len < MIN_FRAME_LEN or data_len > MAX_FRAME_LEN:
                # Impossible length, resynchronize on the next header.
                del self._buffer[0]
                continue
            if len(self._buffer) < data_len:
                # The frame is not complete yet.
                break

            frame = bytes(self._buffer[:data_len])
            del self._buffer[:data_len]
            events.extend(self._parse_frame(frame))

        return events

    def _parse_frame(self, frame: bytes) -> list[ButtonEvent]:
        """Turn one complete frame into button events."""
        if frame[-1] != FRAME_TAIL:
            return []

        data_type = frame[2]
        device_type = frame[4]
        op_code = frame[11] if len(frame) > 11 else 0

        # Panels of different vendors disagree on the checksum, so a button
        # event is accepted even when the checksum does not match. A frame
        # whose checksum fits another panel on the line was damaged on the
        # line, and it belongs to that panel.
        lenient = (
            data_type in (DATA_TYPE_SET, DATA_TYPE_STATUS)
            and device_type in (DEVICE_TYPE_LIGHT, DEVICE_TYPE_SCENE)
            and op_code == LIGHT_OP_SINGLE
        )
        if frame[-2] != calculate_crc8(frame[:-2]):
            if not lenient or self._fits_another_panel(frame):
                _LOGGER.debug(
                    "The frame %s of panel %s was dropped, its checksum does "
                    "not fit",
                    frame.hex(" ").upper(),
                    frame[1],
                )
                return []

        panel_id = frame[1]
        device_addr = frame[6]
        channel = frame[7]
        op_info = frame[12:-2]

        if device_type not in (DEVICE_TYPE_LIGHT, DEVICE_TYPE_SCENE):
            return []
        if data_type not in (DATA_TYPE_SET, DATA_TYPE_REPORT, DATA_TYPE_STATUS):
            return []

        if op_code == LIGHT_OP_SINGLE:
            if not op_info:
                return []
            button = BACKLIGHT_BUTTON if channel == BACKLIGHT_BUTTON else channel
            return [
                ButtonEvent(
                    panel_id=panel_id,
                    button=button,
                    state=op_info[0] != 0,
                    device_addr=device_addr,
                    channel=channel,
                    code=op_info[0],
                    # A set frame is the press of a button, the other frames
                    # report the state of the panel.
                    is_state=data_type != DATA_TYPE_SET,
                )
            ]

        if op_code == LIGHT_OP_MULTI and len(op_info) >= 2:
            # A bit mask of the eight buttons of the panel.
            states = op_info[1]
            return [
                ButtonEvent(
                    panel_id=panel_id,
                    button=bit + 1,
                    state=bool(states & (1 << bit)),
                    device_addr=device_addr,
                )
                for bit in range(8)
                if states & (1 << bit)
            ]

        return []
