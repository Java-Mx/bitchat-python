"""Terminal-native ConnectionModal providing transport selection before chat."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any, ClassVar

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult
    from textual.binding import BindingType

logger = logging.getLogger(__name__)

CONN_OPTIONS: list[tuple[str, str, str]] = [
    (
        "ble",
        "1. Bluetooth Low Energy (BLE)",
        "Direct peer-to-peer mesh using WinRT (Windows) or BlueZ (Linux)",
    ),
    (
        "lan",
        "2. Local Area Network (LAN / Wi-Fi)",
        "Subnet peer discovery via UDP broadcast and TCP transport",
    ),
    (
        "offline",
        "3. Offline Mode (Local Only)",
        "Local state only without radio transmissions",
    ),
    ("back", "4. Back to Dashboard", "Return to the BitChat dashboard"),
]


class ConnectionModal(ModalScreen[str | None]):
    """Modal dialog for terminal-native connection workflow before chat."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "nav_up", "Navigate Up", priority=True),
        Binding("k", "nav_up", "Navigate Up", priority=True),
        Binding("down", "nav_down", "Navigate Down", priority=True),
        Binding("j", "nav_down", "Navigate Down", priority=True),
        Binding("enter", "nav_select", "Select Option", priority=True),
        Binding("1", "select_ble", "Bluetooth", priority=True),
        Binding("2", "select_lan", "LAN", priority=True),
        Binding("3", "select_offline", "Offline", priority=True),
        Binding("4", "cancel", "Back", priority=True),
        Binding("escape", "cancel", "Back", priority=True),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.selected_index: int = 0
        self._is_connecting: bool = False

    def compose(self) -> ComposeResult:
        with Vertical(id="connection-dialog"):
            with Vertical(id="conn-header"):
                yield Label(
                    "[bold #58a6ff]Select Connection Transport[/bold #58a6ff]",
                    id="conn-title",
                )
                yield Label(
                    "[dim #8b949e]Establish mesh connection before entering chat"
                    "[/dim #8b949e]",
                    id="conn-subtitle",
                )

            # Terminal-native text menu (NO cards, NO button backgrounds)
            with Vertical(id="conn-options-list"):
                for key, _, _ in CONN_OPTIONS:
                    yield Static(id=f"conn-item-{key}", classes="conn-menu-item")

            with Vertical(id="conn-status-panel"):
                yield Static(
                    "[dim #6e7681]↑/↓ or 1-4 to select • Enter to connect • "
                    "Esc to return[/dim #6e7681]",
                    id="conn-status-text",
                )

            # Hidden compatibility buttons for automation and test clicks
            with Horizontal(id="conn-hidden-compat"):
                yield Button("BLE", id="btn-conn-ble")
                yield Button("LAN", id="btn-conn-lan")
                yield Button("Offline", id="btn-conn-offline")
                yield Button("Cancel", id="btn-conn-cancel")

    def on_mount(self) -> None:
        self._render_options()

    def _render_options(self) -> None:
        """Update options with moving '>' selection indicator."""
        for i, (key, label, desc) in enumerate(CONN_OPTIONS):
            with contextlib.suppress(Exception):
                item = self.query_one(f"#conn-item-{key}", Static)
                if i == self.selected_index:
                    item.update(
                        f"[bold #58a6ff]> {label}[/bold #58a6ff]\n"
                        f"    [dim #8b949e]{desc}[/dim #8b949e]"
                    )
                    item.add_class("selected")
                else:
                    item.update(
                        f"  [#e6edf3]{label}[/#e6edf3]\n"
                        f"    [dim #6e7681]{desc}[/dim #6e7681]"
                    )
                    item.remove_class("selected")

    def on_click(self, event: events.Click) -> None:
        """Allow clicking directly on any transport row."""
        if self._is_connecting:
            return
        widget = event.widget
        if widget is not None and widget.id and widget.id.startswith("conn-item-"):
            target_key = widget.id.removeprefix("conn-item-")
            for idx, (key, _, _) in enumerate(CONN_OPTIONS):
                if key == target_key:
                    self.selected_index = idx
                    self._render_options()
                    self._activate_option(idx)
                    return

    def action_nav_up(self) -> None:
        if self._is_connecting:
            return
        self.selected_index = (self.selected_index - 1) % len(CONN_OPTIONS)
        self._render_options()

    def action_nav_down(self) -> None:
        if self._is_connecting:
            return
        self.selected_index = (self.selected_index + 1) % len(CONN_OPTIONS)
        self._render_options()

    def action_nav_select(self) -> None:
        if self._is_connecting:
            return
        self._activate_option(self.selected_index)

    def _activate_option(self, index: int) -> None:
        match index:
            case 0:
                self.action_select_ble()
            case 1:
                self.action_select_lan()
            case 2:
                self.action_select_offline()
            case 3:
                self.action_cancel()

    def _set_busy(self, message: str) -> None:
        """Display live initialization feedback."""
        self._is_connecting = True
        with contextlib.suppress(Exception):
            self.query_one("#conn-status-text", Static).update(
                f"[bold #d29922]⌁ {message}[/bold #d29922]"
            )

    def _set_error(self, error_msg: str) -> None:
        """Display genuine initialization failure without fabricating readiness."""
        self._is_connecting = False
        with contextlib.suppress(Exception):
            self.query_one("#conn-status-text", Static).update(
                f"[bold #f85149]✕ {error_msg}[/bold #f85149]"
            )

    def action_select_ble(self) -> None:
        """Initialize platform Bluetooth / BLE transport."""
        if self._is_connecting:
            return

        self.selected_index = 0
        self._render_options()

        coord = getattr(self.app, "coordinator", None)
        if coord is None:
            self.dismiss("chat")
            return

        self._set_busy("Initializing Bluetooth adapter and WinRT/BlueZ GATT...")

        async def _init_ble() -> None:
            try:
                if coord.active_transport_name != "bluetooth":
                    success, msg = await coord.switch_transport("bluetooth")
                elif not coord.is_running:
                    await coord.start()
                    success = coord.is_running
                    msg = coord.ble_error_message or "Started"
                else:
                    success = True
                    msg = "Already active"

                telem = (
                    coord.active_transport.get_telemetry()
                    if hasattr(coord.active_transport, "get_telemetry")
                    else {}
                )
                peripheral_err = telem.get("peripheral_error")

                if success and not peripheral_err:
                    app_config = getattr(self.app, "config", None)
                    storage = getattr(self.app, "storage", None)
                    if app_config is not None:
                        app_config.transport = "bluetooth"
                        if storage is not None and hasattr(storage, "save_config"):
                            with contextlib.suppress(Exception):
                                storage.save_config(app_config)
                    refresh = getattr(self.app, "_refresh_peer_lists", None)
                    if callable(refresh):
                        refresh()
                    self.dismiss("chat")
                else:
                    self._is_connecting = False
                    self.dismiss(None)
                    err = (
                        peripheral_err
                        or coord.ble_error_message
                        or msg
                        or "Bluetooth adapter unavailable"
                    )
                    if hasattr(self.app, "post_message"):
                        if peripheral_err:
                            from bitchat.tui.app import BleWarningReported

                            self.app.post_message(BleWarningReported(err))
                        else:
                            from bitchat.tui.app import BleErrorReported

                            self.app.post_message(BleErrorReported(err))
            except Exception as e:
                logger.warning("BLE initialization failed: %s", e)
                self._is_connecting = False
                self.dismiss(None)
                if hasattr(self.app, "post_message"):
                    from bitchat.tui.app import BleErrorReported

                    self.app.post_message(BleErrorReported(str(e)))

        spawn = getattr(self.app, "_spawn_task", None)
        if callable(spawn):
            spawn(_init_ble())

    def action_select_lan(self) -> None:
        """Initialize Local Area Network / Wi-Fi transport."""
        if self._is_connecting:
            return

        self.selected_index = 1
        self._render_options()

        coord = getattr(self.app, "coordinator", None)
        if coord is None:
            self.dismiss("chat")
            return

        self._set_busy("Initializing LAN discovery and network listener...")

        async def _init_lan() -> None:
            try:
                if coord.active_transport_name != "lan":
                    success, msg = await coord.switch_transport("lan")
                elif not coord.is_running:
                    await coord.start()
                    success = coord.is_running
                    msg = coord.ble_error_message or "Started"
                else:
                    success = True
                    msg = "Already active"

                if success:
                    app_config = getattr(self.app, "config", None)
                    storage = getattr(self.app, "storage", None)
                    if app_config is not None:
                        app_config.transport = "lan"
                        if storage is not None and hasattr(storage, "save_config"):
                            with contextlib.suppress(Exception):
                                storage.save_config(app_config)
                    refresh = getattr(self.app, "_refresh_peer_lists", None)
                    if callable(refresh):
                        refresh()
                    self.dismiss("chat")
                else:
                    self._is_connecting = False
                    self.dismiss(None)
                    err = coord.lan_error_message or msg or "Local network unavailable"
                    if hasattr(self.app, "post_message"):
                        from bitchat.tui.app import LanErrorReported

                        self.app.post_message(LanErrorReported(err))
            except Exception as e:
                logger.warning("LAN initialization failed: %s", e)
                self._is_connecting = False
                self.dismiss(None)
                if hasattr(self.app, "post_message"):
                    from bitchat.tui.app import LanErrorReported

                    self.app.post_message(LanErrorReported(str(e)))

        spawn = getattr(self.app, "_spawn_task", None)
        if callable(spawn):
            spawn(_init_lan())

    def action_select_offline(self) -> None:
        """Enter genuine offline mode without activating radios."""
        if self._is_connecting:
            return

        self.selected_index = 2
        self._render_options()
        self._set_busy("Entering Offline Mode...")

        async def _init_offline() -> None:
            try:
                coord = getattr(self.app, "coordinator", None)
                if coord is not None:
                    if hasattr(coord, "switch_transport"):
                        await coord.switch_transport("offline")
                    elif hasattr(coord, "go_offline"):
                        await coord.go_offline()

                app_config = getattr(self.app, "config", None)
                storage = getattr(self.app, "storage", None)
                if app_config is not None:
                    app_config.transport = "offline"
                    if storage is not None and hasattr(storage, "save_config"):
                        with contextlib.suppress(Exception):
                            storage.save_config(app_config)

                refresh = getattr(self.app, "_refresh_peer_lists", None)
                if callable(refresh):
                    refresh()

                self.dismiss("chat")
            except Exception as e:
                logger.warning("Failed entering offline mode: %s", e)
                self._is_connecting = False
                self.dismiss("chat")

        spawn = getattr(self.app, "_spawn_task", None)
        if callable(spawn):
            spawn(_init_offline())
        else:
            self.dismiss("chat")

    def action_cancel(self) -> None:
        """Dismiss connection modal and return to dashboard."""
        if self._is_connecting:
            return
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle compatibility buttons."""
        match event.button.id:
            case "btn-conn-ble":
                self.action_select_ble()
            case "btn-conn-lan":
                self.action_select_lan()
            case "btn-conn-offline":
                self.action_select_offline()
            case "btn-conn-cancel":
                self.action_cancel()
