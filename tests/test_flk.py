"""Tests for the FLK (弗雷克) panel protocol.

The frames in these tests are the ones a K7x panel sends and expects. They
were taken from the vendor register table and from frames captured on a real
bus.
"""
from __future__ import annotations

import pytest

from custom_components.symi_modbus.panels import flk


def test_a_button_event_of_a_real_panel_is_parsed() -> None:
    """The frame a panel sends for the first key is understood."""
    protocol = flk.FlkProtocol()
    events = protocol.parse_frames(bytes.fromhex("01 06 00 33 06 01 BB A5"))

    assert len(events) == 1
    assert events[0].panel_id == 1
    assert events[0].button == 1
    assert events[0].state is True
    assert events[0].is_toggle is True


def test_every_key_has_its_own_register() -> None:
    """The register of a key is 0x0033 for the first and 0x003A for the last."""
    protocol = flk.FlkProtocol()
    frame = flk.FlkProtocol._build_write(3, 0x003A, 0x0601)
    events = protocol.parse_frames(frame)

    assert len(events) == 1
    assert events[0].panel_id == 3
    assert events[0].button == 8


def test_a_frame_that_arrives_in_two_chunks_is_parsed() -> None:
    """A frame of the bus can be split over two reads."""
    protocol = flk.FlkProtocol()
    frame = bytes.fromhex("01 06 00 33 06 01 BB A5")

    assert protocol.parse_frames(frame[:3]) == []
    events = protocol.parse_frames(frame[3:])

    assert len(events) == 1
    assert events[0].button == 1


def test_bytes_before_a_frame_are_skipped() -> None:
    """A broken byte at the start is resynchronised on the checksum."""
    protocol = flk.FlkProtocol()
    events = protocol.parse_frames(bytes.fromhex("FF FF 01 06 00 33 06 01 BB A5"))

    assert len(events) == 1
    assert events[0].panel_id == 1


def test_a_write_to_the_lights_is_not_a_press() -> None:
    """The frame that writes the lights is not a button event."""
    protocol = flk.FlkProtocol()

    assert protocol.parse_frames(bytes.fromhex("01 06 00 32 06 01 EA 65")) == []


def test_the_release_of_a_long_press_is_not_a_press() -> None:
    """Code 0x05 ends a long press that already reported 0x04."""
    protocol = flk.FlkProtocol()
    frame = flk.FlkProtocol._build_write(1, 0x0033, 0x0605)

    assert protocol.parse_frames(frame) == []


def test_a_frame_with_a_broken_checksum_is_dropped() -> None:
    """A frame that does not add up is not used."""
    protocol = flk.FlkProtocol()

    assert protocol.parse_frames(bytes.fromhex("01 06 00 33 06 01 BB A6")) == []


def test_the_light_is_written_as_a_mask_of_the_panel() -> None:
    """The register of the lights holds all eight lights at once."""
    protocol = flk.FlkProtocol()

    assert (
        protocol.build_led_frame(1, 1, True).hex(" ").upper()
        == "01 06 00 32 06 01 EA 65"
    )


def test_the_mask_keeps_the_other_lights() -> None:
    """Writing one light again does not switch the other lights off."""
    protocol = flk.FlkProtocol()
    protocol.build_led_frame(1, 1, True)
    frame = protocol.build_led_frame(1, 2, True)

    # Light 1 and 2 are on, the panel type is 0x06.
    assert frame.hex(" ").upper().startswith("01 06 00 32 06 03")


@pytest.mark.parametrize(
    ("brand", "expected"),
    [
        ("flk", "01 06 00 32 06 01 EA 65"),
    ],
)
def test_the_light_frame_of_the_brand(brand: str, expected: str) -> None:
    """Every brand builds the light frame of the first button."""
    from custom_components.symi_modbus.panels import PROTOCOLS

    protocol = PROTOCOLS[brand]()

    assert protocol.build_led_frame(1, 1, True).hex(" ").upper() == expected
