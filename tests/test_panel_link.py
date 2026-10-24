"""The panel link, from the bytes on the bus to the frame for the light.

The frame that is fed into the parser is the one the protocol document of the
vendor shows for the third button of the panel with the address two.
"""
from __future__ import annotations

from custom_components.symi_modbus.panels.symi import SymiProtocol

# The frame of the vendor document: panel two, button three, switched on.
PRESS_FRAME = bytes.fromhex("7E 02 03 0F 01 00 01 03 00 00 00 00 01 A0 7D")


def test_a_button_press_of_a_real_panel_is_parsed() -> None:
    """The frame a panel sends when a button is pressed is understood."""
    protocol = SymiProtocol()
    events = protocol.parse_frames(PRESS_FRAME)

    assert len(events) == 1
    event = events[0]
    assert event.panel_id == 0x02
    assert event.button == 3
    assert event.state is True
    assert event.device_addr == 0x01
    assert event.channel == 0x03


def test_the_light_is_written_with_the_address_of_the_button() -> None:
    """The answer carries the very address fields of the button event.

    The protocol document asks for that, a frame with another address is
    ignored by the panel and the light stays dark.
    """
    protocol = SymiProtocol()
    event = protocol.parse_frames(PRESS_FRAME)[0]

    answer = protocol.build_led_frame(
        event.panel_id, event.button, True, event.device_addr, event.channel
    )

    assert answer[0:2] == PRESS_FRAME[0:2]
    assert answer[2] == 0x03  # a set frame, the protocol document asks for it
    assert answer[6] == PRESS_FRAME[6]  # the device address
    assert answer[7] == PRESS_FRAME[7]  # the channel
    assert answer[12] == 0x01  # the state


def test_every_button_keeps_its_own_address() -> None:
    """Every button of a panel can use its own device address and channel."""
    protocol = SymiProtocol()
    first = protocol.parse_frames(PRESS_FRAME)[0]
    second = protocol.parse_frames(
        bytes.fromhex("7E 02 03 0F 01 00 02 05 00 00 00 00 01 5B 7D")
    )[0]

    assert (first.button, first.device_addr, first.channel) == (3, 0x01, 0x03)
    assert (second.button, second.device_addr, second.channel) == (5, 0x02, 0x05)

    frame = protocol.build_led_frame(
        second.panel_id, second.button, True, second.device_addr, second.channel
    )
    assert frame[6] == 0x02
    assert frame[7] == 0x05


def test_the_set_frame_is_the_one_of_the_node_red_implementation() -> None:
    """The set frame is the frame the original node writes."""
    from custom_components.symi_modbus.const import LED_FRAME_SET

    protocol = SymiProtocol(LED_FRAME_SET)
    frame = protocol.build_led_frame(0x02, 1, True, 0x01, 0x01)
    assert frame.hex(" ").upper() == "7E 02 03 0F 01 00 01 01 00 00 00 00 01 F2 7D"
