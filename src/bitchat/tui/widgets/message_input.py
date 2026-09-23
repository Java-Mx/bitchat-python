"""Message input widget with command history and autocomplete coordination."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.message import Message
from textual.widgets import Input

if TYPE_CHECKING:
    from textual import events

    from bitchat.tui.widgets.autocomplete import AutocompletePalette


class MessageInput(Input):
    """Input widget coordinating with autocomplete palette and command history."""

    DEFAULT_CSS = """
    MessageInput {
        height: 3;
        background: #161b22;
        border: solid #30363d;
        color: #e6edf3;
        padding: 0 1;
    }
    MessageInput:focus {
        border: solid #58a6ff;
    }
    """

    class AutocompleteAction(Message):
        """Action signal dispatched to autocomplete palette."""

        def __init__(self, action: str) -> None:  # "prev", "next", "accept", "dismiss"
            super().__init__()
            self.action = action

    def __init__(self, **kwargs) -> None:
        super().__init__(
            placeholder="Type a message or / for commands...",
            id="message-input",
            **kwargs,
        )
        self._history: list[str] = []
        self._history_index: int = -1
        self._temp_input: str = ""
        self.autocomplete_palette: AutocompletePalette | None = None

    def record_history(self, text: str) -> None:
        """Append sent command or message to history."""
        stripped = text.strip()
        if stripped and (not self._history or self._history[-1] != stripped):
            self._history.append(stripped)
        self._history_index = -1
        self._temp_input = ""

    def on_key(self, event: events.Key) -> None:
        """Intercept arrow keys and navigation when autocomplete is open or closed."""
        ac_active = (
            self.autocomplete_palette is not None
            and self.autocomplete_palette.is_visible
        )

        if event.key == "up":
            if ac_active:
                event.prevent_default()
                event.stop()
                self.post_message(self.AutocompleteAction("prev"))
            else:
                event.prevent_default()
                event.stop()
                self._navigate_history_prev()

        elif event.key == "down":
            if ac_active:
                event.prevent_default()
                event.stop()
                self.post_message(self.AutocompleteAction("next"))
            else:
                event.prevent_default()
                event.stop()
                self._navigate_history_next()

        elif event.key == "tab":
            if ac_active:
                event.prevent_default()
                event.stop()
                self.post_message(self.AutocompleteAction("accept"))

        elif event.key == "escape":
            if ac_active:
                event.prevent_default()
                event.stop()
                self.post_message(self.AutocompleteAction("dismiss"))
            else:
                self.value = ""

        elif event.key == "enter" and ac_active:
            # If autocomplete is showing, enter accepts selected suggestion
            event.prevent_default()
            event.stop()
            self.post_message(self.AutocompleteAction("accept"))

    def _navigate_history_prev(self) -> None:
        """Recall older history entry."""
        if not self._history:
            return
        if self._history_index == -1:
            self._temp_input = self.value
            self._history_index = len(self._history) - 1
        elif self._history_index > 0:
            self._history_index -= 1

        self.value = self._history[self._history_index]
        self.cursor_position = len(self.value)

    def _navigate_history_next(self) -> None:
        """Recall newer history entry."""
        if not self._history or self._history_index == -1:
            return

        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self.value = self._history[self._history_index]
        else:
            self._history_index = -1
            self.value = self._temp_input

        self.cursor_position = len(self.value)
