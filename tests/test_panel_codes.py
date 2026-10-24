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
from custom_components.symi_modbus.switch import (
    PanelButtonSwitch,
    _codes_from_options,
    _options_with_codes,
)


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
    state, is_new = button._press_state(_press(1))
    assert state is True
    assert is_new is False


def test_a_key_that_sends_the_same_code_again_flips_the_state() -> None:
    """A panel that sends the same code every time has a key that flips.

    The protocol has two kinds of keys. One kind tells the state of the light,
    the other kind sends the same code for every press and is a trigger. The
    frames show which kind a key is: the same code a second time means that
    the key is a trigger and the light of the button flips on every press.
    """
    button = _button()
    button._is_on = False
    button._last_code = 1

    state, is_new = button._press_state(_press(1))

    assert state is True
    assert button._is_toggle is True


def test_the_code_of_a_trigger_is_not_learned() -> None:
    """The code of a trigger is not the code of a state, so it is not learned."""
    button = _button()
    button._codes = {"on": 1, "off": 0}
    button._is_on = True
    button._last_code = 1

    button._press_state(_press(1))

    assert button._codes == {}


def test_a_key_that_toggles_keeps_flipping() -> None:
    """A key that was found to be a trigger flips on every press."""
    button = _button()
    button._is_on = False
    button._is_toggle = True
    button._last_code = 1

    state, is_new = button._press_state(_press(1))

    assert state is True
    assert is_new is False


def test_a_key_that_tells_the_state_follows_the_code() -> None:
    """A key that sends another code tells the state of the light."""
    button = _button()
    button._codes = {"on": 1, "off": 0}
    button._is_on = True
    button._last_code = 1

    state, is_new = button._press_state(_press(0))

    assert state is False
    assert button._is_toggle is False


def test_what_was_learned_about_the_key_is_kept() -> None:
    """The code of the last press and the kind of the key survive a restart."""
    options = _options_with_codes({}, {"on": 1}, 1, True)

    assert options == {"on_code": 1, "last_code": 1, "toggle": True}
    assert _codes_from_options({"symi_modbus": options}) == {"on": 1}


def test_a_press_with_an_unknown_code_is_read_the_way_the_brand_reads_it() -> None:
    """A code that is not known yet is read the way the brand of the panel reads it.

    The Symi panels put the state of the button in the frame, the code zero is
    the state that is off. The state of the entity is not used for it, it can
    be out of step because the relay wrote the light.
    """
    button = _button()
    button._codes = {"on": 1}
    button._is_on = True

    # The code zero is the state that is off, also when the entity says on.
    state, is_new = button._press_state(_press(0))
    assert state is False
    assert is_new is True

    button._is_on = False
    state, is_new = button._press_state(_press(7))
    assert state is True
    assert is_new is True


def test_a_press_of_a_brand_that_reports_no_state_toggles_the_light() -> None:
    """The LF panels do not tell which state the button goes to.

    The press then only says that the button was used, the light of the button
    is toggled and no code is learned.
    """
    button = _button()
    event = ButtonEvent(panel_id=1, button=1, state=True, is_toggle=True)

    button._is_on = False
    state, is_new = button._press_state(event)
    assert state is True
    assert is_new is False

    button._is_on = True
    state, is_new = button._press_state(event)
    assert state is False
    assert is_new is False


def test_a_code_that_was_set_by_hand_tells_the_state() -> None:
    """A code that was set by hand is the most certain one."""
    button = _button()
    button._codes = {}
    button._panels.manual_codes = lambda subentry_id: (17, 16)

    assert button._state_of(17) is True
    assert button._state_of(16) is False


def test_the_light_is_driven_with_the_code_of_the_panel() -> None:
    """The light is driven with the code the panel uses for that state."""
    button = _button()
    button._codes = {"on": 1, "off": 0}

    assert button._code_for(True) == 1
    assert button._code_for(False) == 0


def test_a_code_that_cannot_be_told_apart_is_not_used() -> None:
    """Two codes that are the same tell nothing, so the standard is used.

    The codes that were learned before were written as a zero for the state
    that was never learned. A zero is the code a panel uses for the state
    that is off, so the two codes could not be told apart and the light was
    driven with the zero even when it was to be turned on.
    """
    button = _button()
    button._codes = {"on": 0, "off": 0}

    assert button._code_for(True) == 1
    assert button._code_for(False) == 0


def test_a_state_whose_code_was_never_learned_uses_the_standard() -> None:
    """A state without a learned code is driven with the code of the protocol."""
    button = _button()
    button._codes = {"off": 0}

    assert button._code_for(True) == 1
    assert button._code_for(False) == 0


def test_two_codes_that_were_set_by_hand_are_not_used() -> None:
    """Two codes that are the same tell nothing, so neither of them is used."""
    button = _button()
    button._codes = {}
    button._panels.manual_codes = lambda subentry_id: (16, 16)

    assert button._state_of(16) is None


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
