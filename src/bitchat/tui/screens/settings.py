"""Settings and node configuration modal screen."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from bitchat.storage.config import DEFAULT_KEYBINDINGS

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult
    from textual.binding import BindingType

KEYBINDING_LABELS: dict[str, str] = {
    "help": "Help",
    "edit_theme": "Edit Theme",
    "settings": "Settings",
    "clear_chat": "Clear Chat",
    "quit": "Quit",
    "scroll_up": "Scroll Up",
    "scroll_down": "Scroll Down",
}


class SettingsModal(ModalScreen[None]):
    """Modal screen for adjusting node parameters, identity, and key bindings."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss_modal", "Cancel", priority=True),
        Binding("f3", "dismiss_modal", "Cancel", priority=True),
    ]

    def on_key(self, event: events.Key) -> None:
        """Handle global function keys inside modal to toggle or switch."""
        get_action = getattr(self.app, "get_action_for_key", None)
        if callable(get_action):
            action = get_action(event.key)
            if action == "settings":
                event.prevent_default()
                event.stop()
                self.dismiss()
            elif action in ("help", "edit_theme") and not (
                self.focused and isinstance(self.focused, Input)
            ):
                event.prevent_default()
                event.stop()
                self.dismiss()
                trigger = getattr(self.app, "trigger_action", None)
                if callable(trigger):
                    trigger(action)

    class SettingsSaved(Message):
        """Emitted when user saves modified settings."""

        def __init__(
            self,
            nickname: str,
            max_hops: int,
            inter_fragment_delay_ms: int,
            keybindings: dict[str, str] | None = None,
        ) -> None:
            super().__init__()
            self.nickname = nickname
            self.max_hops = max_hops
            self.inter_fragment_delay_ms = inter_fragment_delay_ms
            self.keybindings = keybindings or DEFAULT_KEYBINDINGS.copy()

    def __init__(
        self,
        current_nickname: str = "Anonymous",
        current_max_hops: int = 3,
        current_delay_ms: int = 20,
        current_keybindings: dict[str, str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.current_nickname = current_nickname
        self.current_max_hops = current_max_hops
        self.current_delay_ms = current_delay_ms
        self.current_keybindings = (
            current_keybindings.copy()
            if current_keybindings
            else DEFAULT_KEYBINDINGS.copy()
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-dialog"):
            yield Label(
                "[bold #58a6ff]BitChat Settings & Configuration[/bold #58a6ff]",
                id="settings-title",
            )

            with Vertical(id="settings-form"):
                yield Label("Node Parameters:", classes="settings-field-label")
                yield Label("Local Nickname:")
                yield Input(
                    value=self.current_nickname,
                    placeholder="Enter nickname...",
                    id="settings-input-nickname",
                )

                yield Label("Max Mesh Relay Hops (TTL 1-7):")
                yield Input(
                    value=str(self.current_max_hops),
                    placeholder="3",
                    id="settings-input-hops",
                )

                yield Label("Inter-Fragment Delay (ms, 5-500):")
                yield Input(
                    value=str(self.current_delay_ms),
                    placeholder="20",
                    id="settings-input-delay",
                )

                yield Label(
                    "Key Bindings (Action Shortcuts):", classes="settings-field-label"
                )
                for action, label in KEYBINDING_LABELS.items():
                    val = self.current_keybindings.get(
                        action, DEFAULT_KEYBINDINGS.get(action, "")
                    )
                    with Horizontal(classes="settings-kb-row"):
                        yield Label(f"{label}:", classes="settings-kb-label")
                        yield Input(
                            value=val,
                            id=f"settings-kb-{action}",
                            classes="settings-kb-input",
                        )

                yield Static(
                    "[dim #57606a]Keys can be standard (f1-f12, pageup) or "
                    "combinations (ctrl+l, ctrl+q). "
                    "Each action must have a unique key.[/dim #57606a]",
                    id="settings-hint",
                )

            with Horizontal(id="settings-actions"):
                yield Button(
                    "Restore Defaults",
                    id="btn-settings-restore-defaults",
                    classes="action-btn",
                )
                yield Button(
                    "Save Changes", id="btn-settings-save", classes="action-btn"
                )
                yield Button(
                    "Cancel (Esc)", id="btn-settings-cancel", classes="action-btn"
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-settings-cancel":
            self.dismiss()
        elif event.button.id == "btn-settings-restore-defaults":
            self._restore_defaults()
        elif event.button.id == "btn-settings-save":
            self._save_settings()

    def _restore_defaults(self) -> None:
        """Reset all keybinding input fields to factory defaults."""
        for action, default_key in DEFAULT_KEYBINDINGS.items():
            inp = self.query_one(f"#settings-kb-{action}", Input)
            inp.value = default_key
        hint = self.query_one("#settings-hint", Static)
        hint.update(
            "[bold #58a6ff]Keybindings restored to defaults. "
            "Click 'Save Changes' to apply.[/bold #58a6ff]"
        )

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

        # Validate keybindings
        keybindings: dict[str, str] = {}
        assigned_keys: dict[str, str] = {}  # key -> action label
        hint = self.query_one("#settings-hint", Static)

        for action, label in KEYBINDING_LABELS.items():
            inp = self.query_one(f"#settings-kb-{action}", Input)
            raw_key = inp.value.strip().lower()
            if not raw_key:
                hint.update(
                    f"[bold #f85149]Error: Key for '{label}' "
                    "cannot be empty.[/bold #f85149]"
                )
                inp.focus()
                return

            if raw_key in assigned_keys:
                conflict_label = assigned_keys[raw_key]
                hint.update(
                    f"[bold #f85149]Key conflict: '{raw_key}' is assigned to both "
                    f"'{conflict_label}' and '{label}'.[/bold #f85149]"
                )
                inp.focus()
                return

            assigned_keys[raw_key] = label
            keybindings[action] = raw_key

        msg = self.SettingsSaved(nick, hops, delay, keybindings)
        self.app.post_message(msg)
        self.post_message(msg)
        self.dismiss()

    def action_dismiss_modal(self) -> None:
        self.dismiss()
