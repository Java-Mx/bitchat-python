"""Settings and node configuration modal screen."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.binding import BindingType


class SettingsModal(ModalScreen[None]):
    """Modal screen for adjusting node parameters, identity, and mesh routing."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "dismiss_modal", "Cancel"),
    ]

    class SettingsSaved(Message):
        """Emitted when user saves modified settings."""

        def __init__(
            self, nickname: str, max_hops: int, inter_fragment_delay_ms: int
        ) -> None:
            super().__init__()
            self.nickname = nickname
            self.max_hops = max_hops
            self.inter_fragment_delay_ms = inter_fragment_delay_ms

    def __init__(
        self,
        current_nickname: str = "Anonymous",
        current_max_hops: int = 3,
        current_delay_ms: int = 20,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.current_nickname = current_nickname
        self.current_max_hops = current_max_hops
        self.current_delay_ms = current_delay_ms

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-dialog"):
            yield Label(
                "[bold #58a6ff]BitChat Node Configuration[/bold #58a6ff]",
                id="settings-title",
            )

            with Vertical(id="settings-form"):
                yield Label("Local Nickname:", classes="settings-field-label")
                yield Input(
                    value=self.current_nickname,
                    placeholder="Enter nickname...",
                    id="settings-input-nickname",
                )

                yield Label(
                    "Max Mesh Relay Hops (TTL 1-7):", classes="settings-field-label"
                )
                yield Input(
                    value=str(self.current_max_hops),
                    placeholder="3",
                    id="settings-input-hops",
                )

                yield Label(
                    "Inter-Fragment Transmission Delay (ms):",
                    classes="settings-field-label",
                )
                yield Input(
                    value=str(self.current_delay_ms),
                    placeholder="20",
                    id="settings-input-delay",
                )

                yield Static(
                    "[dim #57606a]Changes take effect immediately upon saving. "
                    "Nickname changes announce to all peers.[/dim #57606a]",
                    id="settings-hint",
                )

            with Horizontal(id="settings-actions"):
                yield Button(
                    "Save Changes", id="btn-settings-save", classes="action-btn"
                )
                yield Button(
                    "Cancel (Esc)", id="btn-settings-cancel", classes="action-btn"
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-settings-cancel":
            self.dismiss()
        elif event.button.id == "btn-settings-save":
            self._save_settings()

    def _save_settings(self) -> None:
        nick_input = self.query_one("#settings-input-nickname", Input).value.strip()
        hops_input = self.query_one("#settings-input-hops", Input).value.strip()
        delay_input = self.query_one("#settings-input-delay", Input).value.strip()

        nick = nick_input or self.current_nickname
        try:
            hops = max(1, min(7, int(hops_input)))
        except ValueError:
            hops = self.current_max_hops

        try:
            delay = max(5, min(500, int(delay_input)))
        except ValueError:
            delay = self.current_delay_ms

        self.post_message(self.SettingsSaved(nick, hops, delay))
        self.dismiss()

    def action_dismiss_modal(self) -> None:
        self.dismiss()
