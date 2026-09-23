"""Bottom status bar widget displaying active state and keybinding hints."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

if TYPE_CHECKING:
    from textual.app import ComposeResult


class StatusBar(Widget):
    """Bottom status bar providing real-time status and keyboard shortcut hints."""

    status_message: reactive[str] = reactive("● Secure • BLE Mesh Active")
    hint_message: reactive[str] = reactive(
        "Enter Send   ↑↓ History   Tab Complete   Esc Clear   / Commands   Ctrl+C Quit"
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(id="status-bar", **kwargs)

    def compose(self) -> ComposeResult:
        yield Label(self.status_message, id="status-left")
        yield Label(self.hint_message, id="status-right")

    def watch_status_message(self, new_val: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#status-left", Label).update(new_val)

    def watch_hint_message(self, new_val: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#status-right", Label).update(new_val)
