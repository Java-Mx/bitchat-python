"""IDE-style command autocomplete suggestion palette widget using OptionList."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from textual.message import Message
from textual.widget import Widget
from textual.widgets import OptionList
from textual.widgets.option_list import Option

if TYPE_CHECKING:
    from textual.app import ComposeResult


class AutocompletePalette(Widget):
    """Floating/docked suggestion popup menu for slash commands and arguments."""

    DEFAULT_CSS = """
    AutocompletePalette {
        height: auto;
        max-height: 8;
        background: #161b22;
        border: solid #58a6ff;
        padding: 0;
        display: none;
        margin-bottom: 0;
    }
    #autocomplete-option-list {
        height: auto;
        max-height: 8;
        background: #161b22;
        border: none;
        scrollbar-size-vertical: 1;
    }
    """

    class SuggestionAccepted(Message):
        """Emitted when user accepts a suggestion."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(self, **kwargs) -> None:
        super().__init__(id="autocomplete-popup", **kwargs)
        self._suggestions: list[tuple[str, str]] = []  # (value, description)

    def compose(self) -> ComposeResult:
        yield OptionList(id="autocomplete-option-list")

    @property
    def is_visible(self) -> bool:
        """Return True if the autocomplete popup is currently displayed."""
        return self.styles.display != "none" and len(self._suggestions) > 0

    @property
    def selected_index(self) -> int:
        """Return the currently highlighted option index."""
        try:
            ol = self.query_one("#autocomplete-option-list", OptionList)
            return ol.highlighted if ol.highlighted is not None else 0
        except Exception:
            return 0

    @selected_index.setter
    def selected_index(self, val: int) -> None:
        with contextlib.suppress(Exception):
            ol = self.query_one("#autocomplete-option-list", OptionList)
            ol.highlighted = val

    def show_suggestions(self, suggestions: list[tuple[str, str]]) -> None:
        """Display suggestion list and highlight first item."""
        self._suggestions = list(suggestions)
        ol = self.query_one("#autocomplete-option-list", OptionList)
        ol.clear_options()

        if not self._suggestions:
            self.styles.display = "none"
            return

        self.styles.display = "block"
        options = [
            Option(
                f"[bold #58a6ff]{val}[/bold #58a6ff]  [dim]{desc}[/dim]",
                id=f"opt-{i}",
            )
            for i, (val, desc) in enumerate(self._suggestions)
        ]
        ol.add_options(options)
        ol.highlighted = 0

    def hide(self) -> None:
        """Dismiss the autocomplete popup."""
        self.styles.display = "none"
        self._suggestions.clear()
        with contextlib.suppress(Exception):
            ol = self.query_one("#autocomplete-option-list", OptionList)
            ol.clear_options()

    def select_next(self) -> None:
        """Advance selection down."""
        if not self._suggestions:
            return
        ol = self.query_one("#autocomplete-option-list", OptionList)
        curr = ol.highlighted if ol.highlighted is not None else -1
        ol.highlighted = (curr + 1) % len(self._suggestions)

    def select_prev(self) -> None:
        """Move selection up."""
        if not self._suggestions:
            return
        ol = self.query_one("#autocomplete-option-list", OptionList)
        curr = ol.highlighted if ol.highlighted is not None else 0
        ol.highlighted = (curr - 1) % len(self._suggestions)

    def get_selected_value(self) -> str | None:
        """Return value of the currently selected suggestion."""
        if not self._suggestions:
            return None
        idx = self.selected_index
        if 0 <= idx < len(self._suggestions):
            return self._suggestions[idx][0]
        return None

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection via mouse or keyboard enter."""
        if 0 <= event.option_index < len(self._suggestions):
            val = self._suggestions[event.option_index][0]
            self.post_message(self.SuggestionAccepted(val))
