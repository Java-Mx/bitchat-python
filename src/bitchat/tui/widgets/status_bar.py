"""Interactive bottom action bar and operational telemetry widget."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Label

if TYPE_CHECKING:
    from textual.app import ComposeResult


class StatusBar(Widget):
    """Interactive bottom action bar providing click shortcuts and live telemetry."""

    status_message: reactive[str] = reactive("● Secure • BLE Mesh Active")
    channel_message: reactive[str] = reactive("Target: #public")
    hint_message: reactive[str] = reactive("Noise XX • Forward Secrecy")

    class ActionTriggered(Message):
        """Emitted when user activates an action bar command."""

        def __init__(self, action: str) -> None:
            super().__init__()
            self.action = action

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(id="status-bar", **kwargs)

    def compose(self) -> ComposeResult:
        with Horizontal(id="status-action-row"):
            yield Button("Edit (F2)", id="btn-action-edit", classes="action-btn")
            yield Button(
                "Settings (F3)", id="btn-action-settings", classes="action-btn"
            )
            yield Button("Peers", id="btn-action-peers", classes="action-btn")
            yield Button("Commands (/)", id="btn-action-commands", classes="action-btn")
            yield Button("Help (?)", id="btn-action-help", classes="action-btn")
            yield Button("Quit", id="btn-action-quit", classes="action-btn")

        with Horizontal(id="status-telemetry-row"):
            yield Label(self.status_message, id="status-left")
            yield Label(self.channel_message, id="status-center")
            yield Label(self.hint_message, id="status-right")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Forward action button clicks to parent application."""
        bid = event.button.id or ""
        match bid:
            case "btn-action-edit":
                self.post_message(self.ActionTriggered("edit"))
            case "btn-action-settings":
                self.post_message(self.ActionTriggered("settings"))
            case "btn-action-peers":
                self.post_message(self.ActionTriggered("peers"))
            case "btn-action-commands":
                self.post_message(self.ActionTriggered("commands"))
            case "btn-action-help":
                self.post_message(self.ActionTriggered("help"))
            case "btn-action-quit":
                self.post_message(self.ActionTriggered("quit"))

    def watch_status_message(self, new_val: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#status-left", Label).update(new_val)

    def watch_channel_message(self, new_val: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#status-center", Label).update(new_val)

    def watch_hint_message(self, new_val: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#status-right", Label).update(new_val)
