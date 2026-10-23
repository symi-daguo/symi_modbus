"""The codes a panel uses for the state it reports."""
from __future__ import annotations

from custom_components.symi_modbus.const import LED_FRAME_SET
from custom_components.symi_modbus.panels.base import ButtonEvent
from custom_components.symi_modbus.panels.symi import SymiProtocol


def _press(code: int) -> ButtonEvent:
    """Return the event of a button press that carries the code."""
    return ButtonEvent(
        panel_id=1,
        button=1,
        state=code != 0,
        device_addr=1,
        channel=1,
        code=code,
        is_state=False,
    )


def test_the_code_of_a_button_event_is_kept() -> None:
    """The code the panel sent is kept as it is."""
    # A button press is a set frame.
    protocol = SymiProtocol(LED_FRAME_SET)
    # A panel that uses a code of its own for the state it reports.
    frame = protocol.build_led_frame(0x01, 0x01, True, 0x01, 0x01, code=0x11)
    events = protocol.parse_frames(frame)
    assert len(events) == 1
    assert events[0].code == 0x11
    # A set frame is the press of a button, not a state report.
    assert events[0].is_state is False


def test_a_state_report_is_told_apart_from_a_press() -> None:
    """A status frame reports the state, a set frame is a press."""
    protocol = SymiProtocol()
    press = protocol.parse_frames(
        SymiProtocol(LED_FRAME_SET).build_led_frame(0x01, 0x01, True, 0x01, 0x01)
    )[0]
    report = protocol.parse_frames(
        protocol.build_led_frame(0x01, 0x01, True, 0x01, 0x01).replace(
            b"\x03", b"\x05", 1
        )
    )[0]
    assert press.is_state is False
    assert report.is_state is True


def test_the_light_is_driven_with_the_code_of_the_panel() -> None:
    """The code that was learned is the code that goes on the bus."""
    protocol = SymiProtocol()
    frame = protocol.build_led_frame(0x01, 0x01, False, 0x01, 0x01, code=0x10)
    # The code sits in the operation information, the twelfth byte.
    assert frame[12] == 0x10
    assert frame[2] == 0x04


def test_the_code_of_a_panel_is_learned_from_its_frames() -> None:
    """Two presses of a button teach the panel both of its codes."""
    protocol = SymiProtocol()
    events = []
    presses = SymiProtocol(LED_FRAME_SET)
    for code in (0x11, 0x10):
        events.append(
            protocol.parse_frames(
                presses.build_led_frame(0x01, 0x01, True, 0x01, 0x01, code=code)
            )[0]
        )

    codes: dict[str, int] = {}
    is_on = False
    for event in events:
        is_on = not is_on
        codes["on" if is_on else "off"] = event.code

    assert codes == {"on": 0x11, "off": 0x10}
