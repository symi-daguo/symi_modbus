"""Common types for the panel (wall switch) protocols."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ButtonEvent:
    """A button press reported by a panel on the bus."""

    panel_id: int
    """Address of the panel that sent the event (1-255)."""

    button: int
    """Number of the button, 1-8. 15 marks the backlight channel."""

    state: bool
    """True when the button reports "on", False when it reports "off"."""

    device_addr: int = 1
    """Logical device address of the panel, used to address the answer."""


class PanelProtocol(ABC):
    """Interface of a panel brand protocol.

    Every brand speaks its own dialect on the same RS-485 bus. The panel
    connection only needs to build the frame that drives the indicator light
    and to understand the frames the panels send.
    """

    brand: str
    """Key of the brand, used in the configuration."""

    default_buttons: int = 8
    """Number of buttons a panel of this brand has."""

    @abstractmethod
    def build_led_frame(
        self, panel_id: int, button: int, state: bool, device_addr: int = 1
    ) -> bytes:
        """Build the frame that turns the indicator light of a button on or off."""

    @abstractmethod
    def parse_frames(self, data: bytes) -> list[ButtonEvent]:
        """Parse the bytes received on the bus into button events.

        The data may hold more than one frame and may end in the middle of a
        frame, so the implementation keeps whatever it cannot use yet.
        """

    def prepare_frames(self, panel_ids: list[int]) -> list[bytes]:
        """Return the frames that have to be sent before the lights can be driven.

        Some brands need the panel to be put into a mode where the host owns
        the indicator lights. Those frames are sent once when the bus starts.
        """
        return []
