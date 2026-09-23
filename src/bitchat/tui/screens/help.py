"""Help modal screen for the BitChat TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Label

from bitchat.commands.parser import COMMAND_REGISTRY

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.binding import BindingType


class HelpScreen(ModalScreen[None]):
    """Modal screen displaying all available slash commands and keyboard shortcuts."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "dismiss_modal", "Close"),
        ("q", "dismiss_modal", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label(
                "[bold #58a6ff]BitChat Commands & Navigation[/bold #58a6ff]",
                id="help-title",
            )
            table = DataTable(id="help-table")
            table.cursor_type = "row"
            table.zebra_stripes = True
            yield table
            yield Button("Close (Esc)", id="help-close-btn")

    def on_mount(self) -> None:
        table = self.query_one("#help-table", DataTable)
        table.add_columns("Command", "Category", "Description")
        for spec in COMMAND_REGISTRY:
            table.add_row(spec.usage, spec.category, spec.description)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "help-close-btn":
            self.dismiss()

    def action_dismiss_modal(self) -> None:
        self.dismiss()
