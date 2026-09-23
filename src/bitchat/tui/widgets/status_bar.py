"""Interactive bottom action bar and operational telemetry widget."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from textual.containers import Grid, Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Label

if TYPE_CHECKING:
    from textual.app import ComposeResult


class StatusBar(Widget):
    """Interactive bottom action bar providing click shortcuts and live telemetry."""

    mesh_status: reactive[str] = reactive("● BitChat Ready • Local Mesh")
    security_status: reactive[str] = reactive("Noise XX • Forward Secrecy")
    target_status: reactive[str] = reactive("Target: #public")

    class ActionTriggered(Message):
        """Emitted when user activates an action bar command."""

        def __init__(self, action: str) -> None:
            super().__init__()
            self.action = action

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(id="status-bar", **kwargs)

    @property
    def status_message(self) -> str:
        """Backward-compatible alias for mesh_status."""
        return self.mesh_status

    @status_message.setter
    def status_message(self, val: str) -> None:
        self.mesh_status = val

    @property
    def channel_message(self) -> str:
        """Backward-compatible alias for target_status."""
        return self.target_status

    @channel_message.setter
    def channel_message(self, val: str) -> None:
        self.target_status = val

    @property
    def hint_message(self) -> str:
        """Backward-compatible alias for security_status."""
        return self.security_status

    @hint_message.setter
    def hint_message(self, val: str) -> None:
        self.security_status = val

    def compose(self) -> ComposeResult:
        with Horizontal(id="status-container"):
            with Vertical(id="status-telemetry-col"):
                yield Label(self.mesh_status, id="status-line-mesh")
                yield Label(self.security_status, id="status-line-crypto")
                yield Label(self.target_status, id="status-line-target")

            with Grid(id="status-actions-grid"):
                yield Button("Edit", id="btn-action-edit", classes="action-btn")
                yield Button("Settings", id="btn-action-settings", classes="action-btn")
                yield Button("Peers", id="btn-action-peers", classes="action-btn")
                yield Button("Commands", id="btn-action-commands", classes="action-btn")
                yield Button("Help", id="btn-action-help", classes="action-btn")
                yield Button("Quit", id="btn-action-quit", classes="action-btn")

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

    def watch_mesh_status(self, new_val: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#status-line-mesh", Label).update(new_val)

    def watch_security_status(self, new_val: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#status-line-crypto", Label).update(new_val)

    def watch_target_status(self, new_val: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#status-line-target", Label).update(new_val)
