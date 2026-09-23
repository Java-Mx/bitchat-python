"""Bluetooth error recovery and hardware diagnosis modal dialog."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.binding import BindingType


class BLEErrorModal(ModalScreen[None]):
    """Modal dialog displayed when Bluetooth adapter is missing, disabled, or fails."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "dismiss_modal", "Close"),
        ("q", "dismiss_modal", "Close"),
    ]

    class RetryRequested(Message):
        """Emitted when user requests a retry of Bluetooth services."""

    def __init__(
        self, error_message: str = "Bluetooth adapter not found or disabled.", **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.error_message = error_message

    def compose(self) -> ComposeResult:
        with Vertical(id="ble-error-dialog"):
            yield Label(
                "[bold #f85149]! Bluetooth Hardware Error[/bold #f85149]",
                id="ble-error-title",
            )

            with Vertical(id="ble-error-content"):
                yield Static(
                    "[bold #e6edf3]Could not initialize Bluetooth Low Energy "
                    "transport.[/bold #e6edf3]\n\n"
                    f"[#f85149]Details:[/#f85149] [dim #e6edf3]{self.error_message}"
                    "[/dim #e6edf3]\n\n"
                    "[dim #8b949e]Possible solutions:\n"
                    "  1. Ensure your PC's Bluetooth adapter is enabled in settings.\n"
                    "  2. On Linux, ensure BlueZ is active\n"
                    "     (`systemctl status bluetooth`).\n"
                    "  3. On Windows, ensure Bluetooth is toggled ON in Settings.\n"
                    "  4. Click 'Retry Adapter' after turning Bluetooth on."
                    "[/dim #8b949e]\n\n"
                    "[bold #58a6ff]BitChat is operating safely in Offline / Local Mode."
                    "[/bold #58a6ff]",
                    classes="ble-error-text",
                )

            with Horizontal(id="ble-error-actions"):
                yield Button("Retry Adapter", id="btn-ble-retry", classes="action-btn")
                yield Button(
                    "Continue Offline", id="btn-ble-close", classes="action-btn"
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-ble-close":
            self.dismiss()
        elif event.button.id == "btn-ble-retry":
            self.post_message(self.RetryRequested())
            self.dismiss()

    def action_dismiss_modal(self) -> None:
        self.dismiss()
