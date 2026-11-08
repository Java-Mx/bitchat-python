from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.containers import Grid, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Label

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from textual.app import ComposeResult


class StatusBar(Widget):
    """Interactive bottom action bar providing click shortcuts and live telemetry."""

    mesh_status: reactive[str] = reactive("◌ Initializing Mesh...")
    security_status: reactive[str] = reactive("Noise XX • Forward Secrecy")
    target_status: reactive[str] = reactive("Target: #public")

    class ActionTriggered(Message):
        """Emitted when user activates an action bar command."""

        def __init__(self, action: str) -> None:
            super().__init__()
            self.action = action

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(id="status-bar", **kwargs)

    @staticmethod
    def _is_offline_status(status: str) -> bool:
        """Classify the active transport, not optional hardware details."""
        status = status.lstrip()
        return (
            status.startswith(("✕", "○ Offline", "OFFLINE MODE"))
            or "OFFLINE" in status.upper()
        )

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
                mesh_lbl = Label(self.mesh_status, id="status-line-mesh")
                if self._is_offline_status(self.mesh_status):
                    mesh_lbl.add_class("status-offline")
                yield mesh_lbl
                yield Label(self.security_status, id="status-line-crypto")
                yield Label(self.target_status, id="status-line-target")

            with Grid(
                id="status-actions-grid",
                classes="footer-action-grid",
            ):
                yield Button("Edit", id="btn-action-edit", classes="action-btn")
                yield Button("Settings", id="btn-action-settings", classes="action-btn")
                yield Button("Peers", id="btn-action-peers", classes="action-btn")
                yield Button("Commands", id="btn-action-commands", classes="action-btn")
                yield Button("Help", id="btn-action-help", classes="action-btn")
                yield Button("Quit", id="btn-action-quit", classes="action-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Forward action button clicks to parent application."""
        bid = event.button.id or ""
        app: Any = self.app
        match bid:
            case "btn-action-edit":
                self.post_message(self.ActionTriggered("edit"))
                if hasattr(app, "action_open_edit_theme"):
                    app.action_open_edit_theme()
            case "btn-action-settings":
                self.post_message(self.ActionTriggered("settings"))
                if hasattr(app, "action_open_settings"):
                    app.action_open_settings()
            case "btn-action-peers":
                self.post_message(self.ActionTriggered("peers"))
                if hasattr(app, "action_open_peers"):
                    app.action_open_peers()
            case "btn-action-commands":
                self.post_message(self.ActionTriggered("commands"))
                if hasattr(app, "action_open_commands"):
                    app.action_open_commands()
            case "btn-action-help":
                self.post_message(self.ActionTriggered("help"))
                if hasattr(app, "action_show_help"):
                    app.action_show_help()
            case "btn-action-quit":
                self.post_message(self.ActionTriggered("quit"))
                if hasattr(app, "action_quit") and hasattr(app, "_spawn_task"):
                    app._spawn_task(app.action_quit())

    def watch_mesh_status(self, new_val: str) -> None:
        try:
            lbl = self.query_one("#status-line-mesh", Label)
            lbl.update(new_val)
            if self._is_offline_status(new_val):
                lbl.add_class("status-offline")
            else:
                lbl.remove_class("status-offline")
        except NoMatches:
            pass
        except Exception as e:
            logger.debug("Failed updating mesh status line: %s", e)

    def watch_security_status(self, new_val: str) -> None:
        try:
            self.query_one("#status-line-crypto", Label).update(new_val)
        except NoMatches:
            pass
        except Exception as e:
            logger.debug("Failed updating security status line: %s", e)

    def watch_target_status(self, new_val: str) -> None:
        try:
            self.query_one("#status-line-target", Label).update(new_val)
        except NoMatches:
            pass
        except Exception as e:
            logger.debug("Failed updating target status line: %s", e)
