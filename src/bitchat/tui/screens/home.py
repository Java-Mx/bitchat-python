"""Terminal-native BitChat Home Screen & Central Dashboard."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, ClassVar

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Label, Static

from bitchat import __version__
from bitchat.tui.screens.commands import CommandsScreen
from bitchat.tui.screens.connection import ConnectionModal
from bitchat.tui.screens.peers import PeersScreen
from bitchat.tui.screens.settings import SettingsScreen
from bitchat.tui.screens.telemetry import TelemetryScreen

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult
    from textual.binding import BindingType

# Distinctive, centered geometric ASCII/Unicode block typography wordmark
WORDMARK = (
    "█▀▀▄  ▀█▀  ▀█▀  ▄▀▀▄  █  █  ▄▀▀▄  ▀█▀\n"
    "█▀▀▄   █    █   █     █▀▀█  █▄▄█   █ \n"
    "█▄▄▀  ▄█▄   █   ▀▄▄▀  █  █  █  █   █ "
)

NAV_ITEMS: list[tuple[str, str]] = [
    ("connect", "Connect"),
    ("peers", "Peers"),
    ("settings", "Settings"),
    ("commands", "Commands"),
    ("telemetry", "System Telemetry"),
    ("quit", "Quit"),
]


class HomeScreen(Screen[None]):
    """Central dashboard screen providing terminal-native keyboard navigation."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "nav_up", "Navigate Up", priority=True),
        Binding("k", "nav_up", "Navigate Up", priority=True),
        Binding("down", "nav_down", "Navigate Down", priority=True),
        Binding("j", "nav_down", "Navigate Down", priority=True),
        Binding("enter", "nav_select", "Select Entry", priority=True),
        Binding("1", "select_0", "Connect", priority=True),
        Binding("2", "select_1", "Peers", priority=True),
        Binding("3", "select_2", "Settings", priority=True),
        Binding("4", "select_3", "Commands", priority=True),
        Binding("5", "select_4", "System Telemetry", priority=True),
        Binding("6", "select_5", "Quit", priority=True),
        Binding("c", "open_connect", "Connect", priority=True),
        Binding("p", "open_peers", "Peers", priority=True),
        Binding("s", "open_settings", "Settings", priority=True),
        Binding("d", "open_commands", "Commands", priority=True),
        Binding("question_mark", "open_commands", "Commands", priority=True),
        Binding("t", "open_telemetry", "Telemetry", priority=True),
        Binding("r", "retry_ble", "Retry Bluetooth", priority=True),
        Binding("q", "quit_app", "Quit", priority=True),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.selected_index: int = 0

    def compose(self) -> ComposeResult:
        with (
            Vertical(id="home-screen-container"),
            Vertical(id="home-dashboard"),
        ):
            # Centered geometric block typography wordmark & subtitle
            with Vertical(id="home-banner"):
                yield Static(WORDMARK, id="home-wordmark")
                yield Label(
                    f"[dim #8b949e]Encrypted Peer-to-Peer Mesh • "
                    f"Decentralized • v{__version__}[/dim #8b949e]",
                    id="home-subtitle",
                )

            # Terminal-native interactive text menu (NO cards, NO button backgrounds)
            with Vertical(id="home-nav-menu"):
                for key, _ in NAV_ITEMS:
                    yield Static(id=f"nav-item-{key}", classes="menu-item")

            # Subtle keyboard shortcut hint
            yield Label(
                "[dim #8b949e]↑ / ↓ Navigate     Enter Select     [Q] Quit[/dim #8b949e]",
                id="home-nav-hint",
            )

            # Hidden buttons for backward compatibility with automation and tests
            with Horizontal(id="home-hidden-compat"):
                yield Button("Connect", id="btn-home-connect")
                yield Button("Peers", id="btn-home-peers")
                yield Button("Settings", id="btn-home-settings")
                yield Button("Commands", id="btn-home-commands")
                yield Button("System Telemetry", id="btn-home-telemetry")
                yield Button("Chat", id="btn-home-chat")
                yield Button("Quit", id="btn-home-quit")
                yield Button("Retry BLE", id="btn-home-retry-ble")

    def on_mount(self) -> None:
        """Render initial menu selection."""
        self._render_menu()

    def refresh_status(self) -> None:
        """Subsystem status update hook for app events."""
        pass

    def _render_menu(self) -> None:
        """Update terminal text menu rows with moving '>' selection indicator."""
        for i, (key, label) in enumerate(NAV_ITEMS):
            with contextlib.suppress(Exception):
                item = self.query_one(f"#nav-item-{key}", Static)
                if i == self.selected_index:
                    item.update(f"[bold #58a6ff]> {label}[/bold #58a6ff]")
                    item.add_class("selected")
                else:
                    item.update(f"  [#e6edf3]{label}[/#e6edf3]")
                    item.remove_class("selected")

    def on_click(self, event: events.Click) -> None:
        """Allow clicking directly on any menu item."""
        widget = event.widget
        if widget is not None and widget.id and widget.id.startswith("nav-item-"):
            target_key = widget.id.removeprefix("nav-item-")
            for idx, (key, _) in enumerate(NAV_ITEMS):
                if key == target_key:
                    self.selected_index = idx
                    self._render_menu()
                    self._activate_selected()
                    return

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle compatibility buttons."""
        bid = event.button.id or ""
        match bid:
            case "btn-home-connect":
                self.action_open_connect()
            case "btn-home-peers":
                self.action_open_peers()
            case "btn-home-settings":
                self.action_open_settings()
            case "btn-home-commands":
                self.action_open_commands()
            case "btn-home-telemetry":
                self.action_open_telemetry()
            case "btn-home-chat":
                self.action_open_chat()
            case "btn-home-quit":
                self.action_quit_app()
            case "btn-home-retry-ble":
                self.action_retry_ble()

    def action_retry_ble(self) -> None:
        """Retry BLE transport initialization."""
        fn = getattr(self.app, "action_retry_bluetooth", None)
        if callable(fn):
            fn()

    def action_nav_up(self) -> None:
        """Select previous item in the text menu."""
        self.selected_index = (self.selected_index - 1) % len(NAV_ITEMS)
        self._render_menu()

    def action_nav_down(self) -> None:
        """Select next item in the text menu."""
        self.selected_index = (self.selected_index + 1) % len(NAV_ITEMS)
        self._render_menu()

    def action_nav_select(self) -> None:
        """Activate the currently selected navigation entry."""
        self._activate_selected()

    def action_select_0(self) -> None:
        self.selected_index = 0
        self._render_menu()
        self.action_open_connect()

    def action_select_1(self) -> None:
        self.selected_index = 1
        self._render_menu()
        self.action_open_peers()

    def action_select_2(self) -> None:
        self.selected_index = 2
        self._render_menu()
        self.action_open_settings()

    def action_select_3(self) -> None:
        self.selected_index = 3
        self._render_menu()
        self.action_open_commands()

    def action_select_4(self) -> None:
        self.selected_index = 4
        self._render_menu()
        self.action_open_telemetry()

    def action_select_5(self) -> None:
        self.selected_index = 5
        self._render_menu()
        self.action_quit_app()

    def _activate_selected(self) -> None:
        match self.selected_index:
            case 0:
                self.action_open_connect()
            case 1:
                self.action_open_peers()
            case 2:
                self.action_open_settings()
            case 3:
                self.action_open_commands()
            case 4:
                self.action_open_telemetry()
            case 5:
                self.action_quit_app()

    def _on_connection_modal_result(self, res: str | None) -> None:
        """Handle ConnectionModal result, transitioning into chat if selected."""
        if res == "chat":
            self.action_open_chat()

    def action_open_connect(self) -> None:
        """Present connection transport selection dialog."""
        self.app.push_screen(ConnectionModal(), self._on_connection_modal_result)

    def action_open_peers(self) -> None:
        """Open peer discovery and inspection screen."""
        self.app.push_screen(PeersScreen())

    def action_open_settings(self) -> None:
        """Open settings and configuration screen."""
        fn = getattr(self.app, "action_open_settings", None)
        if callable(fn):
            fn()
        else:
            self.app.push_screen(SettingsScreen())

    def action_open_commands(self) -> None:
        """Open command reference screen."""
        self.app.push_screen(CommandsScreen())

    def action_open_telemetry(self) -> None:
        """Open dedicated system & radio telemetry screen."""
        self.app.push_screen(TelemetryScreen())

    def action_open_chat(self) -> None:
        """Transition into chat screen."""
        fn = getattr(self.app, "action_open_chat", None)
        if callable(fn):
            fn()
        elif len(self.app._screen_stack) > 1:
            self.app.pop_screen()

    def action_quit_app(self) -> None:
        """Cleanly exit application."""
        self.app.exit()
