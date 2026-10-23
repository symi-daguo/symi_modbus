"""The codes a panel uses for the state it reports."""
from __future__ import annotations

from custom_components.symi_modbus.const import LED_FRAME_SET
from custom_components.symi_modbus.panels.base import ButtonEvent
from custom_components.symi_modbus.panels.symi import (
    SymiProtocol,
    calculate_crc8,
)


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


from collections import deque
from time import monotonic

from custom_components.symi_modbus.panels.base import ButtonEvent
from custom_components.symi_modbus.panels.connection import PanelConnection
from custom_components.symi_modbus.panels.symi import SymiProtocol
from custom_components.symi_modbus.switch import PanelButtonSwitch


class FakeManager:
    """A manager that only knows whether the bus is up."""

    def is_connected(self, subentry_id: str) -> bool:
        """Return that the bus is up."""
        return True

    def manual_codes(self, subentry_id: str) -> tuple[int | None, int | None]:
        """Return that no code was set by hand."""
        return (None, None)

    async def async_set_button(self, *args, **kwargs) -> None:
        """Do nothing."""


def _button() -> PanelButtonSwitch:
    """Return a button of a panel."""
    return PanelButtonSwitch(FakeManager(), "bus", 1, 1, "symi", "unique")


def _connection() -> PanelConnection:
    """Return a connection with one echo on it."""
    connection = PanelConnection.__new__(PanelConnection)
    connection._echoes = [(1, 1, 16, monotonic())]
    connection._recent = deque(maxlen=4)
    return connection


def test_a_press_with_a_known_code_keeps_the_state() -> None:
    """A press whose code is known tells the state, the button does not flip."""
    button = _button()
    button._codes = {"on": 1, "off": 0}
    button._is_on = True

    # The code of the press is the code of the "on" state, so the button goes on
    # even though it was on already.
    state, is_new = button._press_state(1)
    assert state is True
    assert is_new is False


def test_a_press_with_an_unknown_code_flips_the_state() -> None:
    """A press with a code the panel uses first time is a toggle."""
    button = _button()
    button._codes = {"on": 1}
    button._is_on = True

    state, is_new = button._press_state(7)
    assert state is False
    assert is_new is True


def test_the_code_zero_can_be_learned() -> None:
    """A panel that reports the state with the code zero is understood."""
    button = _button()
    button._codes = {"on": 1, "off": 0}

    assert button._state_of(0) is False
    assert button._state_of(1) is True


def test_codes_that_cannot_be_told_apart_are_not_used() -> None:
    """Two codes that are the same tell nothing, so neither of them is used."""
    button = _button()
    button._codes = {"on": 1, "off": 1}

    assert button._state_of(1) is None


def test_the_echo_is_told_apart_by_the_code() -> None:
    """The echo of a frame is recognised by the code it carries.

    A panel can use a code of its own for the state. The echo of a frame that
    was sent with that code must still be recognised, otherwise the frame of
    the integration is taken for a press of a button.
    """
    connection = _connection()

    echo = ButtonEvent(
        panel_id=1, button=1, state=True, device_addr=1, channel=1, code=16
    )
    assert connection._is_echo(echo) is True


def test_a_press_of_the_panel_is_not_an_echo() -> None:
    """A press of the panel is not the echo of a frame."""
    connection = _connection()

    press = ButtonEvent(
        panel_id=1, button=1, state=True, device_addr=1, channel=1, code=17
    )
    assert connection._is_echo(press) is False


def test_the_echo_of_another_panel_is_not_an_echo() -> None:
    """The echo of another panel is not the echo of this frame."""
    connection = _connection()

    echo = ButtonEvent(
        panel_id=2, button=1, state=True, device_addr=1, channel=1, code=16
    )
    assert connection._is_echo(echo) is False


def test_the_frame_carries_the_code_that_was_asked_for() -> None:
    """The frame of the light carries the code of the panel."""
    frame = SymiProtocol().build_led_frame(1, 1, False, 1, 1, code=16)

    # The code sits in the operation information, the twelfth byte.
    assert frame[12] == 16


def test_a_frame_that_was_damaged_on_the_line_is_dropped() -> None:
    """A frame that carries the address of another panel is dropped.

    Two panels that report at the same time, or a panel that reports while a
    frame of ours goes out, damage each other on the line. The address byte of
    the damaged frame then belongs to the other panel, and so does its
    checksum.
    """
    protocol = SymiProtocol()
    protocol.known_addresses = {1, 2}

    # The frame of panel 2, with the address of panel 1 written over it.
    good = protocol.build_led_frame(0x02, 1, True)
    damaged = bytearray(good)
    damaged[1] = 0x01

    assert protocol.parse_frames(bytes(damaged)) == []


def test_a_panel_with_a_broken_checksum_is_still_understood() -> None:
    """A panel that sends frames with a broken checksum is still understood."""
    protocol = SymiProtocol()
    protocol.known_addresses = {1, 2}

    # A button event of panel 1 with a checksum that fits no other panel.
    body = bytearray(
        bytes.fromhex("7E 01 03 0F 01 00 01 01 00 00 00 00 01")
    )
    taken = set()
    for address in (1, 2):
        body[1] = address
        taken.add(calculate_crc8(bytes(body)))
    wrong = next(value for value in range(256) if value not in taken)
    body[1] = 0x01
    frame = bytes(body) + bytes([wrong, 0x7D])

    events = protocol.parse_frames(frame)
    assert len(events) == 1
    assert events[0].panel_id == 1
