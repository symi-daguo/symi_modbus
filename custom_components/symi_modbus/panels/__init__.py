"""Panel protocols for the supported brands."""
from __future__ import annotations

from typing import Any

from .base import ButtonEvent, PanelProtocol
from .clowire import ClowireProtocol
from .lf import LfProtocol
from .symi import SymiProtocol

PROTOCOLS: dict[str, type[PanelProtocol]] = {
    SymiProtocol.brand: SymiProtocol,
    ClowireProtocol.brand: ClowireProtocol,
    LfProtocol.brand: LfProtocol,
}


def panel_keys(brand: str, buttons: Any = None) -> int:
    """Return the number of keys of a panel bus.

    The protocol of the brand knows how many keys its panels have, so the
    number is taken from there and never more than that.
    """
    keys = PROTOCOLS.get(str(brand), PanelProtocol).default_buttons
    if buttons is None:
        return keys
    return max(1, min(int(buttons), keys))


__all__ = ["PROTOCOLS", "ButtonEvent", "PanelProtocol", "panel_keys"]
