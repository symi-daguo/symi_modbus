"""Tests for the panel protocols.

The byte sequences in these tests are the frames the panels of the supported
brands send and expect. They were taken from the vendor documentation and
from frames captured on a real bus.
"""
from __future__ import annotations

import pytest

from custom_components.symi_modbus.const import LED_FRAME_SET
from custom_components.symi_modbus.panels import clowire, lf, symi


def _hex(data: bytes) -> str:
    """Return the bytes as a readable hex string."""
    return data.hex(" ").upper()


class TestSymiProtocol:
    """The Symi protocol uses its own framed dialect."""

    def test_the_light_frame_has_the_documented_layout(self) -> None:
        """The frame is a report frame, the protocol document asks for that."""
        protocol = symi.SymiProtocol()
        frame = protocol.build_led_frame(0x02, 3, True)
        # The same frame the Node-RED implementation builds.
        assert _hex(frame) == "7E 02 04 0F 01 00 01 03 00 00 00 00 01 FD 7D"
        assert frame[0] == symi.FRAME_HEADER
        assert frame[-1] == symi.FRAME_TAIL
        assert frame[2] == symi.DATA_TYPE_REPORT

    def test_the_light_frame_can_be_a_set_frame(self) -> None:
        """Some panels only take a set frame, so it can be chosen."""
        protocol = symi.SymiProtocol(LED_FRAME_SET)
        frame = protocol.build_led_frame(0x02, 3, True)
        assert _hex(frame) == "7E 02 03 0F 01 00 01 03 00 00 00 00 01 A0 7D"
        assert frame[2] == symi.DATA_TYPE_SET

    def test_a_button_event_of_a_real_panel_is_parsed(self) -> None:
        """The frame a panel sends when a button is pressed is understood.

        The frame is the one the protocol document of the vendor shows for
        the third button of the panel with the address two.
        """
        protocol = symi.SymiProtocol()
        events = protocol.parse_frames(
            bytes.fromhex("7E 02 03 0F 01 00 01 03 00 00 00 00 01 A0 7D")
        )
        assert len(events) == 1
        assert events[0].panel_id == 0x02
        assert events[0].button == 3
        assert events[0].state is True
        assert events[0].device_addr == 0x01
        assert events[0].channel == 0x03

    def test_the_address_of_the_button_is_learned(self) -> None:
        """The light is written with the address the panel used."""
        protocol = symi.SymiProtocol()
        events = protocol.parse_frames(
            bytes.fromhex("7E 02 03 0F 01 00 01 03 00 00 00 00 01 A0 7D")
        )
        frame = protocol.build_led_frame(
            events[0].panel_id,
            events[0].button,
            True,
            events[0].device_addr,
            events[0].channel,
        )
        # Only the data type differs from the button event.
        assert frame[1] == 0x02
        assert frame[6] == 0x01
        assert frame[7] == 0x03

    def test_a_pressed_button_is_reported(self) -> None:
        """The frame of a button press is turned into a button event."""
        protocol = symi.SymiProtocol()
        frame = protocol.build_led_frame(0x05, 2, True)
        events = protocol.parse_frames(frame)
        assert len(events) == 1
        assert events[0].panel_id == 0x05
        assert events[0].button == 2
        assert events[0].state is True

    def test_the_backlight_channel_is_not_a_button(self) -> None:
        """Channel 0x0F is the backlight and is reported as button 15."""
        protocol = symi.SymiProtocol()
        body = bytearray(
            symi.SymiProtocol().build_led_frame(0x02, 0x0F, True)
        )
        body[7] = 0x0F
        body[13] = symi.calculate_crc8(bytes(body[:-2]))
        events = protocol.parse_frames(bytes(body))
        assert len(events) == 1
        assert events[0].button == 15

    def test_a_frame_split_over_two_reads_is_still_parsed(self) -> None:
        """A frame that arrives in pieces is kept until it is complete."""
        protocol = symi.SymiProtocol()
        frame = protocol.build_led_frame(0x03, 4, True)
        assert protocol.parse_frames(frame[:6]) == []
        events = protocol.parse_frames(frame[6:])
        assert len(events) == 1
        assert events[0].button == 4

    def test_two_frames_in_one_read_are_both_reported(self) -> None:
        """Two frames that arrive together are both parsed."""
        protocol = symi.SymiProtocol()
        data = protocol.build_led_frame(0x03, 1, True) + protocol.build_led_frame(
            0x03, 2, True
        )
        events = protocol.parse_frames(data)
        assert [event.button for event in events] == [1, 2]

    def test_a_wrong_checksum_is_accepted_for_a_button_event(self) -> None:
        """Panels of other vendors send button events with a broken checksum."""
        protocol = symi.SymiProtocol(LED_FRAME_SET)
        frame = bytearray(protocol.build_led_frame(0x02, 1, True))
        frame[13] ^= 0xFF
        assert protocol.parse_frames(bytes(frame))

    def test_a_wrong_checksum_drops_a_feedback_frame(self) -> None:
        """A frame that is not a button event has to pass the checksum."""
        protocol = symi.SymiProtocol()
        frame = bytearray(protocol.build_led_frame(0x02, 1, True))
        frame[12] ^= 0xFF
        assert protocol.parse_frames(bytes(frame)) == []

    def test_noise_between_two_frames_is_skipped(self) -> None:
        """Rubbish on the bus does not stop the parser."""
        protocol = symi.SymiProtocol()
        frame = protocol.build_led_frame(0x07, 6, True)
        events = protocol.parse_frames(b"\x00\x11\x22" + frame)
        assert len(events) == 1
        assert events[0].button == 6


class TestClowireProtocol:
    """The Clowire protocol is a Modbus variant with an extra frame tail."""

    def test_the_light_frames_match_the_vendor_examples(self) -> None:
        """The frames match the examples of the vendor documentation."""
        protocol = clowire.ClowireProtocol()
        assert (
            _hex(protocol.build_led_frame(0x02, 1, True))
            == "02 06 10 21 00 01 1C F3 AA"
        )
        assert (
            _hex(protocol.build_led_frame(0x02, 1, False))
            == "02 06 10 21 00 00 DD 33 AA"
        )
        assert (
            _hex(protocol._build_write(0x02, clowire.REG_BACKLIGHT, 0x0001))
            == "02 06 10 20 00 01 4D 33 AA"
        )

    def test_the_frame_tail_is_not_part_of_the_checksum(self) -> None:
        """The checksum covers the first six bytes only."""
        protocol = clowire.ClowireProtocol()
        frame = protocol.build_led_frame(0x02, 1, True)
        assert len(frame) == 9
        assert frame[-1] == clowire.FRAME_TAIL
        assert frame[-3:-1] == bytes(
            __import__(
                "custom_components.symi_modbus.frames", fromlist=["crc16_fn"]
            ).crc16_fn(frame[:6])
        )

    def test_a_button_press_is_reported(self) -> None:
        """The register address carries the number of the button."""
        protocol = clowire.ClowireProtocol()
        events = protocol.parse_frames(bytes.fromhex("02 20 10 11 00 80 D5 5B AA"))
        assert len(events) == 1
        assert events[0].panel_id == 0x02
        assert events[0].button == 1
        assert events[0].state is True

    def test_every_button_of_the_panel_is_found(self) -> None:
        """The eight buttons use the registers 0x1011 to 0x1018."""
        protocol = clowire.ClowireProtocol()
        for button in range(1, 9):
            register = clowire.REG_BUTTON_S1 + button - 1
            frame = protocol._build_write(0x02, register, 0x0080)
            # The button event uses the command code 0x20.
            frame = bytes([frame[0], clowire.CMD_BUTTON_EVENT]) + frame[2:]
            events = protocol.parse_frames(frame)
            assert events[0].button == button

    def test_a_long_press_carries_the_button(self) -> None:
        """A long press uses its own register with the button in the data."""
        protocol = clowire.ClowireProtocol()
        frame = protocol._build_write(0x02, clowire.REG_LONG_PRESS, 0x0180)
        frame = bytes([frame[0], clowire.CMD_BUTTON_EVENT]) + frame[2:]
        events = protocol.parse_frames(frame)
        assert len(events) == 1
        assert events[0].button == 1
        assert events[0].state is True

    def test_a_frame_split_over_two_reads_is_still_parsed(self) -> None:
        """A frame that arrives in pieces is kept until it is complete."""
        protocol = clowire.ClowireProtocol()
        frame = bytes.fromhex("02 20 10 11 00 80 D5 5B AA")
        assert protocol.parse_frames(frame[:4]) == []
        events = protocol.parse_frames(frame[4:])
        assert len(events) == 1

    def test_two_frames_in_one_read_are_both_reported(self) -> None:
        """Two frames that arrive together are both parsed."""
        protocol = clowire.ClowireProtocol()
        data = bytes.fromhex("02 20 10 11 00 80 D5 5B AA") + bytes.fromhex(
            "02 20 10 12 00 80 94 5A AA"
        )
        events = protocol.parse_frames(data)
        assert [event.button for event in events] == [1, 2]


class TestLfProtocol:
    """The LF protocol uses fixed eight byte frames without a tail."""

    def test_the_configuration_frames_match_the_vendor_examples(self) -> None:
        """The frames match the examples of the vendor documentation."""
        protocol = lf.LfProtocol()
        assert (
            _hex(protocol._build_write(0x02, lf.REG_LED_CONTROL, 0x0001))
            == "02 06 10 08 00 01 CD 3B"
        )
        assert (
            _hex(
                protocol._build_write(
                    0x02, lf.REG_PANEL_CONFIG, lf.CONFIG_RCU_ACTIVE
                )
            )
            == "02 06 10 03 00 06 FD 3B"
        )
        assert (
            _hex(protocol._build_write(0x02, lf.REG_SAVE_CONFIG, lf.SAVE_CONFIG_VALUE))
            == "02 06 10 0F 00 FE 3C BA"
        )

    def test_the_panel_is_put_into_host_controlled_mode(self) -> None:
        """The mode has to be set before the lights can be driven."""
        protocol = lf.LfProtocol()
        frames = protocol.prepare_frames([0x02])
        assert len(frames) == 2
        assert frames[0] == protocol._build_write(
            0x02, lf.REG_PANEL_CONFIG, lf.CONFIG_RCU_ACTIVE
        )
        assert frames[1] == protocol._build_write(
            0x02, lf.REG_SAVE_CONFIG, lf.SAVE_CONFIG_VALUE
        )

    def test_a_button_press_is_reported(self) -> None:
        """The mask in the frame carries the number of the button."""
        protocol = lf.LfProtocol()
        events = protocol.parse_frames(bytes.fromhex("01 03 00 02 01 01 24 5A"))
        assert len(events) == 1
        assert events[0].panel_id == 0x01
        assert events[0].button == 1
        assert events[0].state is True

    def test_a_frame_with_two_buttons_is_dropped(self) -> None:
        """A frame with more than one button in the mask is not used."""
        protocol = lf.LfProtocol()
        assert protocol.parse_frames(bytes.fromhex("01 03 00 02 01 03 84 5A")) == []

    def test_the_light_frame_carries_the_state_of_every_button(self) -> None:
        """The register holds the whole panel, so the mask is built up."""
        protocol = lf.LfProtocol()
        first = protocol.build_led_frame(0x02, 1, True)
        second = protocol.build_led_frame(0x02, 2, True)
        third = protocol.build_led_frame(0x02, 1, False)
        assert first == protocol._build_write(
            0x02, lf.REG_LED_CONTROL, 0x0001 | lf.LED_BACKLIGHT_ENABLE
        )
        assert second == protocol._build_write(
            0x02, lf.REG_LED_CONTROL, 0x0003 | lf.LED_BACKLIGHT_ENABLE
        )
        assert third == protocol._build_write(
            0x02, lf.REG_LED_CONTROL, 0x0002 | lf.LED_BACKLIGHT_ENABLE
        )

    def test_the_panels_keep_their_standby_light(self) -> None:
        """With no button lit the panel keeps its backlight."""
        protocol = lf.LfProtocol()
        protocol.build_led_frame(0x02, 1, True)
        frame = protocol.build_led_frame(0x02, 1, False)
        assert frame == protocol._build_write(
            0x02, lf.REG_LED_CONTROL, lf.LED_BACKLIGHT_ENABLE
        )

    def test_a_frame_split_over_two_reads_is_still_parsed(self) -> None:
        """A frame that arrives in pieces is kept until it is complete."""
        protocol = lf.LfProtocol()
        frame = bytes.fromhex("01 03 00 02 01 01 24 5A")
        assert protocol.parse_frames(frame[:5]) == []
        events = protocol.parse_frames(frame[5:])
        assert len(events) == 1

    def test_a_frame_with_a_broken_checksum_is_dropped(self) -> None:
        """A frame that does not add up is not used."""
        protocol = lf.LfProtocol()
        assert protocol.parse_frames(bytes.fromhex("01 03 00 02 01 01 24 5B")) == []


@pytest.mark.parametrize(
    ("brand", "expected"),
    [
        ("symi", "7E 02 04 0F 01 00 01 01 00 00 00 00 01 AF 7D"),
        ("clowire", "02 06 10 21 00 01 1C F3 AA"),
        ("lf", "02 06 10 08 01 01 CC AB"),
    ],
)
def test_every_brand_builds_a_light_frame(brand: str, expected: str) -> None:
    """Every brand drives the light of the first button the same way."""
    from custom_components.symi_modbus.panels import PROTOCOLS

    protocol = PROTOCOLS[brand]()
    assert _hex(protocol.build_led_frame(0x02, 1, True)) == expected
