"""The codes of a panel are kept with the entity."""
from __future__ import annotations

from custom_components.symi_modbus.switch import (
    _codes_from_options,
    _options_with_codes,
)


def test_the_codes_are_kept_under_the_domain_of_the_integration() -> None:
    """The codes live in the options of the entity, under the domain."""
    options = _options_with_codes({}, {"on": 17, "off": 16})

    assert options == {"on_code": 17, "off_code": 16}


def test_the_other_options_are_left_alone() -> None:
    """The options of another part of the entity are not touched."""
    options = _options_with_codes(
        {"conversation": {"should_expose": True}}, {"on": 17, "off": 16}
    )

    assert options == {"on_code": 17, "off_code": 16}


def test_the_codes_are_read_back() -> None:
    """The codes that were kept are read back."""
    options = _options_with_codes({}, {"on": 17, "off": 16})
    stored = {"symi_modbus": options}

    assert _codes_from_options(stored) == {"on": 17, "off": 16}


def test_an_entity_without_codes_has_none() -> None:
    """An entity that never learned a code has none."""
    assert _codes_from_options({}) == {}
    assert _codes_from_options({"conversation": {"should_expose": True}}) == {}


def test_a_code_that_was_not_learned_is_not_written() -> None:
    """A code that was not learned is not kept as a zero.

    The zero is a code a panel uses for the state that is off. Writing it for
    the state that is on would drive the light with the wrong code.
    """
    options = _options_with_codes({}, {"off": 0})

    assert options == {"off_code": 0}


def test_a_code_that_was_wrong_is_dropped() -> None:
    """The codes that were learned before are replaced by the ones now."""
    options = _options_with_codes({"on_code": 0, "off_code": 0}, {"on": 1})

    assert options == {"on_code": 1}
