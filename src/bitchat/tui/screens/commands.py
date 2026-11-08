"""CommandsScreen displaying available application commands, syntax, and shortcuts."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Label, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.binding import BindingType

# Extended reference list for commands and keyboard shortcuts
EXTENDED_COMMANDS: list[tuple[str, str, str, str]] = [
    (
        "/configure [category]",
        "System",
        "Run system diagnostics, or open a settings category",
        "/configure",
    ),
    (
        "/configure general",
        "System",
        "Open General configuration (nickname, identity)",
        "/configure general",
    ),
    (
        "/configure network",
        "System",
        "Open LAN / Wi-Fi network settings",
        "/configure network",
    ),
    (
        "/configure bluetooth",
        "System",
        "Open BLE mesh parameters & roles",
        "/configure bluetooth",
    ),
    (
        "/configure appearance",
        "System",
        "Open theme, density & accent settings",
        "/configure appearance",
    ),
    (
        "/connect <address>",
        "Network",
        "Connect to a peer BLE address or IP",
        "/connect 11:22:33:44:55:66",
    ),
    (
        "/disconnect [address]",
        "Network",
        "Disconnect from a peer or all peers",
        "/disconnect",
    ),
    ("/scan", "Network", "Scan for nearby BitChat BLE or LAN peers", "/scan"),
    ("/online / /peers", "Network", "List connected and discovered peers", "/online"),
    (
        "/dm <peer> <message>",
        "Chat",
        "Send encrypted Noise XX direct message",
        "/dm @Bob Hello!",
    ),
    ("/public", "Chat", "Switch active conversation context to #public", "/public"),
    (
        "/transport [medium]",
        "Network",
        "Switch active transport (bluetooth or lan)",
        "/transport lan",
    ),
    (
        "/name <nickname>",
        "Identity",
        "Set local nickname and announce to mesh",
        "/name Alice",
    ),
    (
        "/info <peer>",
        "Security",
        "Inspect peer cryptographic identity & fingerprint",
        "/info @Bob",
    ),
    ("/clear", "System", "Clear active chat history log", "/clear"),
    ("/help", "System", "Show this commands and navigation screen", "/help"),
    ("/exit", "System", "Exit BitChat safely", "/exit"),
]

KEYBOARD_SHORTCUTS: list[tuple[str, str, str]] = [
    ("F1 / ?", "Help / Commands", "Open available commands and shortcuts"),
    ("F2", "Theme & Appearance", "Open density, accent, and visual styling modal"),
    ("F3", "Settings", "Open application settings and configuration"),
    ("Ctrl+L", "Clear Chat", "Clear the current chat log history"),
    ("Ctrl+Q", "Quit", "Cleanly stop transport and exit BitChat"),
    ("PageUp", "Scroll Chat Up", "Scroll back through message history"),
    ("PageDown", "Scroll Chat Down", "Scroll forward towards recent messages"),
    ("Escape", "Back / Dismiss", "Close current modal or return to previous screen"),
]


class CommandsScreen(Screen[None]):
    """Dedicated screen presenting all application commands, syntax, and shortcuts."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss_screen", "Back", priority=True),
        Binding("q", "dismiss_screen", "Back", priority=True),
        Binding("f1", "dismiss_screen", "Back", priority=True),
        Binding("c", "open_chat", "Enter Chat", priority=True),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="commands-screen-container"):
            with Horizontal(id="commands-top-header"):
                yield Label(
                    "[bold #58a6ff]BitChat — Commands & Shortcuts Reference"
                    "[/bold #58a6ff]",
                    id="commands-title",
                )
                yield Static(
                    "[dim #8b949e]Complete command syntax, examples, and shortcuts"
                    "[/dim #8b949e]"
                )

            with Vertical(id="commands-tables-scroll"):
                yield Label(
                    "[bold #39c5cf]Slash Commands & Diagnostic Syntax[/bold #39c5cf]",
                    classes="table-section-title",
                )
                cmd_table = DataTable(id="commands-table")
                cmd_table.cursor_type = "row"
                cmd_table.zebra_stripes = True
                yield cmd_table

                yield Label(
                    "[bold #bc8cff]Global Keyboard Navigation Shortcuts[/bold #bc8cff]",
                    classes="table-section-title",
                )
                kb_table = DataTable(id="shortcuts-table")
                kb_table.cursor_type = "row"
                kb_table.zebra_stripes = True
                yield kb_table

            with (
                Horizontal(id="commands-action-bar"),
                Grid(
                    id="commands-footer-buttons",
                    classes="footer-action-grid",
                ),
            ):
                yield Button(
                    "Open Chat [C]",
                    id="btn-commands-chat",
                    variant="primary",
                    classes="action-btn",
                )
                yield Button(
                    "Back to Dashboard (Esc)",
                    id="btn-commands-back",
                    classes="action-btn",
                )

    def on_mount(self) -> None:
        """Populate commands and keyboard shortcut tables."""
        cmd_table = self.query_one("#commands-table", DataTable)
        cmd_table.add_columns("Command Syntax", "Category", "Description", "Example")

        for cmd, cat, desc, example in EXTENDED_COMMANDS:
            cmd_table.add_row(cmd, cat, desc, example)

        kb_table = self.query_one("#shortcuts-table", DataTable)
        kb_table.add_columns("Key Shortcut", "Action", "Description")

        for key, action, desc in KEYBOARD_SHORTCUTS:
            kb_table.add_row(key, action, desc)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-commands-back":
            self.action_dismiss_screen()
        elif event.button.id == "btn-commands-chat":
            self.action_open_chat()

    def action_open_chat(self) -> None:
        if hasattr(self.app, "action_open_chat"):
            self.app.action_open_chat()  # type: ignore[attr-defined]
        else:
            self.dismiss()

    def action_dismiss_screen(self) -> None:
        self.dismiss()
