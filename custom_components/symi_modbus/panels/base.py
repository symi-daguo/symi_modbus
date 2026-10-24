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

    channel: int = 0
    """Channel the panel used for this button, 0 when it is the button number."""

    code: int = 0
    """The code the panel sent in the frame.

    A panel can use a code of its own for the state it reports, so the code is
    kept as it is and matched against the state later.
    """

    is_state: bool = False
    """True when the frame reports the state, false when it is a key press."""

    is_toggle: bool = False
    """True when the press carries no state, the button toggles its light.

    Some brands do not tell in the frame which state the button goes to, the
    press then only says that the button was used.
    """

    is_state_code: bool = False
    """True when the code is the code of a state.

    A panel can report an action that is not a state, a double click for
    example. Such a code is not the code of a state, it is not learned and it
    is not written to the light.
    """


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
        self,
        panel_id: int,
        button: int,
        state: bool,
        device_addr: int = 1,
        channel: int | None = None,
        code: int | None = None,
    ) -> bytes:
        """Build the frame that turns the indicator light of a button on or off.

        The address of the button has to be the one the panel used in its
        button event, the panel ignores a frame with another address. The code
        is the one the panel uses for the state, a panel can use a code of its
        own.
        """

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
