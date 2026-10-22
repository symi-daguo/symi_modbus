"""Panel protocols for the supported brands."""
from __future__ import annotations

from .base import ButtonEvent, PanelProtocol
from .clowire import ClowireProtocol
from .lf import LfProtocol
from .symi import SymiProtocol

PROTOCOLS: dict[str, type[PanelProtocol]] = {
    SymiProtocol.brand: SymiProtocol,
    ClowireProtocol.brand: ClowireProtocol,
    LfProtocol.brand: LfProtocol,
}

__all__ = ["PROTOCOLS", "ButtonEvent", "PanelProtocol"]
