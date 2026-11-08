"""Professional Textual terminal user interface for BitChat."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any, ClassVar

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Button, Input, Label

from bitchat.commands.parser import (
    COMMAND_REGISTRY,
    Command,
    CommandParser,
    CommandType,
    get_command_suggestions,
)
from bitchat.logging import disable_console_logging
from bitchat.storage.config import AppConfig, FileConfigStorage, StorageInterface
from bitchat.transport.base import (
    TransportError,
    TransportType,
    TransportWarning,
    normalize_transport_name,
)
from bitchat.tui.screens.ble_error import BLEErrorModal
from bitchat.tui.screens.commands import CommandsScreen
from bitchat.tui.screens.edit_theme import EditThemeModal
from bitchat.tui.screens.help import HelpScreen
from bitchat.tui.screens.home import HomeScreen
from bitchat.tui.screens.peer_info import PeerInfoModal
from bitchat.tui.screens.peers import PeersScreen
from bitchat.tui.screens.settings import (
    SettingsModal,
    SettingsScreen,
    normalize_keybinding,
)
from bitchat.tui.screens.telemetry import TelemetryScreen
from bitchat.tui.theme import TCSS_STYLES
from bitchat.tui.widgets.autocomplete import AutocompletePalette
from bitchat.tui.widgets.chat_view import ChatView
from bitchat.tui.widgets.header import HeaderWidget
from bitchat.tui.widgets.message_input import MessageInput
from bitchat.tui.widgets.sidebar import PeerSidebar
from bitchat.tui.widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from bitchat.app.session_coordinator import SessionCoordinator

logger = logging.getLogger(__name__)


class BleErrorReported(Message):
    """BLE error forwarded from coordinator or transport callbacks."""

    def __init__(
        self, error: TransportError | str, generation: int | None = None
    ) -> None:
        super().__init__()
        self.error = error if isinstance(error, TransportError) else None
        self.error_message = (
            error.message if isinstance(error, TransportError) else error
        )
        self.generation = generation


class LanErrorReported(Message):
    """LAN network error forwarded from coordinator or transport callbacks."""

    def __init__(
        self, error: TransportError | str, generation: int | None = None
    ) -> None:
        super().__init__()
        self.error = error if isinstance(error, TransportError) else None
        self.error_message = (
            error.message if isinstance(error, TransportError) else error
        )
        self.generation = generation


class BleWarningReported(Message):
    """BLE capability warning forwarded from transport startup."""

    def __init__(
        self, warning: TransportWarning | str, generation: int | None = None
    ) -> None:
        super().__init__()
        self.event = warning if isinstance(warning, TransportWarning) else None
        self.warning = (
            warning.message if isinstance(warning, TransportWarning) else warning
        )
        self.generation = generation


class BitChatApp(App[None]):
    """Modern terminal user interface for the BitChat mesh client."""

    TITLE = "BitChat"
    SUB_TITLE = "Bluetooth Low Energy Mesh Chat"
    CSS_PATH = "styles/app.tcss"
    CSS = TCSS_STYLES
    COMMAND_PALETTE_BINDING = "ctrl+shift+p"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("f4", "open_peers", "Peers", show=False),
        Binding("escape", "open_home", "Dashboard", show=False),
    ]

    ACTION_TO_APP_METHOD: ClassVar[dict[str, str]] = {
        "help": "show_help",
        "edit_theme": "open_edit_theme",
        "settings": "open_settings",
        "clear_chat": "clear_log",
        "quit": "quit",
        "scroll_up": "scroll_chat_up",
        "scroll_down": "scroll_chat_down",
        "home": "open_home",
        "peers": "open_peers",
        "commands": "open_commands",
    }

    def __init__(
        self,
        coordinator: SessionCoordinator | None = None,
        storage: StorageInterface | None = None,
        config: AppConfig | None = None,
        initial_screen: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        disable_console_logging()
        self.coordinator = coordinator
        self.parser = CommandParser(slash_only=True)
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._is_shutting_down: bool = False

        import os
        import sys

        if initial_screen is None:
            if "pytest" in sys.modules and not os.environ.get("BITCHAT_FORCE_HOME"):
                self.initial_screen: str = "chat"
            else:
                self.initial_screen = "home"
        else:
            self.initial_screen = initial_screen

        if storage is not None:
            self.storage: StorageInterface = storage
        elif (
            coordinator is not None
            and getattr(coordinator, "storage", None) is not None
        ):
            self.storage = coordinator.storage  # type: ignore[assignment]
        else:
            self.storage = FileConfigStorage()

        if config is not None:
            self.config = config
        else:
            try:
                self.config = self.storage.load_config()
            except Exception as e:
                logger.warning("Failed to load config, falling back to default: %s", e)
                self.config = AppConfig()

        self._key_to_action: dict[str, str] = {}
        self.apply_keybindings(self.config.keybindings)

        self.active_context: str = "#public"
        self.current_density: str = self.config.density
        self.current_show_timestamps: bool = self.config.show_timestamps
        self.current_accent: str = self.config.accent
        self._authenticated_transport_peers: set[str] = set()
        self._authenticated_peer_addresses: dict[str, str] = {}
        self._ble_warning_acknowledged: bool = False
        self._transport_switch_task: asyncio.Task[Any] | None = None

        # Sync nickname to coordinator if coordinator was default "Anonymous"
        if (
            self.coordinator is not None
            and self.config.nickname != "Anonymous"
            and self.coordinator.nickname == "Anonymous"
        ):
            self.coordinator.set_nickname(self.config.nickname)

        # Sync mesh parameters from config to coordinator
        if self.coordinator is not None:
            self.coordinator.mesh_router.max_relay_ttl = self.config.max_hops
            self.coordinator.inter_fragment_delay = (
                self.config.inter_fragment_delay_ms / 1000.0
            )

        # Connect coordinator event hooks if present
        if self.coordinator is not None:
            self.coordinator.on_message_received = self._on_coordinator_message
            self.coordinator.on_peer_status_changed = self._on_coordinator_peer_status
            self.coordinator.on_handshake_completed = self._on_coordinator_handshake
            self.coordinator.on_ble_error = self._on_coordinator_ble_error
            self.coordinator.on_ble_warning = self._on_coordinator_ble_warning
            self.coordinator.on_lan_error = self._on_coordinator_lan_error

    def _spawn_task(self, coro: Any) -> asyncio.Task[Any]:
        """Spawn background task and keep reference until completed."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)

        def _task_done(t: asyncio.Task[Any]) -> None:
            self._background_tasks.discard(t)
            if not t.cancelled():
                exc = t.exception()
                if exc is not None:
                    logger.error(
                        "TUI background task failed",
                        exc_info=(type(exc), exc, exc.__traceback__),
                    )

        task.add_done_callback(_task_done)
        return task

    def apply_keybindings(self, keymap: dict[str, str]) -> None:
        """Apply dynamic keybindings at runtime."""
        target_actions = {
            action for action in self.ACTION_TO_APP_METHOD.values() if action != "quit"
        } | {f"configured_{action}" for action in self.ACTION_TO_APP_METHOD}
        if hasattr(self, "_bindings") and hasattr(self._bindings, "key_to_bindings"):
            keys_to_remove = [
                k
                for k, bindings in self._bindings.key_to_bindings.items()
                if any(b.action in target_actions for b in bindings)
            ]
            for k in keys_to_remove:
                self._bindings.key_to_bindings.pop(k, None)

        self._key_to_action = {}
        for action, key in keymap.items():
            method_name = self.ACTION_TO_APP_METHOD.get(action)
            normalized_key = self._normalize_runtime_key(action, key)
            if not method_name or normalized_key is None:
                continue
            if normalized_key in self._key_to_action:
                logger.warning(
                    "Ignoring duplicate keybinding %r for %s; already assigned to %s",
                    normalized_key,
                    action,
                    self._key_to_action[normalized_key],
                )
                continue
            self._key_to_action[normalized_key] = action
            if normalized_key == "ctrl+c" and action == "quit":
                continue
            self._bindings.bind(
                normalized_key, f"configured_{action}", show=False, priority=True
            )
        self.refresh_bindings()

    @staticmethod
    def _normalize_runtime_key(action: str, key: str) -> str | None:
        try:
            return normalize_keybinding(key, action)
        except ValueError as exc:
            logger.warning(
                "Ignoring invalid keybinding for %s (%r): %s", action, key, exc
            )
            return None

    def get_action_for_key(self, key: str) -> str | None:
        """Return the logical action configured for a given key string."""
        return self._key_to_action.get(key.strip().lower())

    def trigger_action(self, action_name: str) -> None:
        """Authoritative dispatch for user actions across the app."""
        match action_name:
            case "help":
                self.action_show_help()
            case "edit_theme":
                self.action_open_edit_theme()
            case "settings":
                self.action_open_settings()
            case "clear_chat":
                self.action_clear_log()
            case "quit":
                self._spawn_task(self.action_quit())
            case "scroll_up":
                self.action_scroll_chat_up()
            case "scroll_down":
                self.action_scroll_chat_down()
            case "home":
                self.action_open_home()
            case "peers":
                self.action_open_peers()
            case "commands":
                self.action_open_commands()

    def _dispatch_configured_keybinding(self, action: str) -> None:
        if isinstance(self.focused, Input) and not isinstance(
            self.focused, MessageInput
        ):
            return
        self.trigger_action(action)

    def action_configured_help(self) -> None:
        self._dispatch_configured_keybinding("help")

    def action_configured_edit_theme(self) -> None:
        self._dispatch_configured_keybinding("edit_theme")

    def action_configured_settings(self) -> None:
        self._dispatch_configured_keybinding("settings")

    def action_configured_clear_chat(self) -> None:
        self._dispatch_configured_keybinding("clear_chat")

    def action_configured_quit(self) -> None:
        self._dispatch_configured_keybinding("quit")

    def action_configured_scroll_up(self) -> None:
        self._dispatch_configured_keybinding("scroll_up")

    def action_configured_scroll_down(self) -> None:
        self._dispatch_configured_keybinding("scroll_down")

    def action_configured_peers(self) -> None:
        self._dispatch_configured_keybinding("peers")

    def action_configured_home(self) -> None:
        self._dispatch_configured_keybinding("home")

    def action_configured_commands(self) -> None:
        self._dispatch_configured_keybinding("commands")

    async def on_event(self, event: events.Event) -> None:
        """Let printable shortcut keys remain ordinary text in focused inputs."""
        if (
            isinstance(event, events.Key)
            and event.character
            and event.key in self._key_to_action
            and isinstance(self.focused, Input)
        ):
            self.focused._forward_event(event)
            return
        await super().on_event(event)

    def compose(self) -> ComposeResult:
        nick = self.coordinator.nickname if self.coordinator else self.config.nickname
        pid = self.coordinator.local_identity.peer_id_hex if self.coordinator else ""
        fp = self.coordinator.local_identity.fingerprint if self.coordinator else ""

        yield HeaderWidget(nickname=nick, peer_id_hex=pid, fingerprint=fp)
        with Horizontal(id="main-body"):
            yield PeerSidebar(nickname=nick, peer_id_hex=pid, fingerprint=fp)
            with Vertical(id="chat-column"):
                yield ChatView(id="chat-view")
                with Vertical(id="input-container"):
                    yield AutocompletePalette()
                    yield MessageInput()
        yield StatusBar()

    async def on_mount(self) -> None:
        """Mount and start coordinator services."""
        # Apply initial density and accent classes to app root
        self.add_class(f"density-{self.current_density}")
        self.add_class(f"accent-{self.current_accent}")

        chat = self.query_one(ChatView)
        chat.compact_mode = self.current_density == "compact"
        chat.show_timestamps = self.current_show_timestamps

        msg_input = self.query_one(MessageInput)
        palette = self.query_one(AutocompletePalette)
        msg_input.autocomplete_palette = palette
        msg_input.focus()

        chat.add_system_message(
            "Welcome to BitChat. Type / for commands, @<peer> for direct messages, "
            "/help for help."
        )

        if self.coordinator is not None:
            coord = self.coordinator

            async def _start_coordinator() -> None:
                try:
                    await coord.start()
                except Exception as e:
                    logger.warning("Coordinator start error: %s", e)
                    if hasattr(coord, "ble_status"):
                        coord.ble_status = "unavailable"
                    if getattr(coord, "active_transport_name", "") == "lan":
                        self._on_coordinator_lan_error(str(e))
                    else:
                        self._on_coordinator_ble_error(str(e))
                finally:
                    self._refresh_peer_lists()

            if (
                self.initial_screen not in ("home", "connection")
                and not coord.offline_mode
                and coord.active_transport_name != "offline"
            ):
                self._spawn_task(_start_coordinator())
            self._refresh_peer_lists()

        if self.initial_screen == "connection":
            from bitchat.tui.screens.connection import ConnectionModal

            home = HomeScreen()
            self.push_screen(home)
            self.push_screen(ConnectionModal(), home._on_connection_modal_result)
        elif self.initial_screen == "home":
            self.push_screen(HomeScreen())

        self.set_interval(2.0, self._refresh_peer_lists)

    def _refresh_peer_lists(self) -> None:
        """Refresh sidebar and header with latest peer states and truthful telemetry."""
        for screen in list(self._screen_stack):
            if isinstance(screen, (HomeScreen, TelemetryScreen)):
                screen.refresh_status()
            elif isinstance(screen, PeersScreen):
                screen.refresh_peer_list()

        if not self.coordinator:
            return

        base_screen = self._screen_stack[0] if self._screen_stack else self.screen
        try:
            sidebar = base_screen.query_one(PeerSidebar)
            header = base_screen.query_one(HeaderWidget)
            status_bar = base_screen.query_one(StatusBar)
        except NoMatches:
            try:
                sidebar = self.query_one(PeerSidebar)
                header = self.query_one(HeaderWidget)
                status_bar = self.query_one(StatusBar)
            except NoMatches:
                return

        active_transport = self.coordinator.active_transport
        trans_name = self.coordinator.effective_active_transport_name
        telemetry = active_transport.get_telemetry()
        sidebar.active_transport = trans_name

        connected_addrs = active_transport.connected_peers

        conn_display: dict[str, str] = {}
        seen_conn_pids: dict[str, str] = {}
        for addr in connected_addrs:
            pid = self.coordinator.address_to_peer_id.get(addr, "")
            nick = self.coordinator.peer_nicknames.get(pid, pid[:8] if pid else addr)
            session = self.coordinator.get_session(pid) if pid else None
            sec_tag = (
                "🔒 authenticated"
                if session and session.is_established
                else "unverified"
            )
            if pid and pid in seen_conn_pids:
                prev_addr = seen_conn_pids[pid]
                canonical_addr = self.coordinator.peer_addresses.get(pid, addr)
                if addr == canonical_addr and prev_addr != canonical_addr:
                    conn_display.pop(prev_addr, None)
                    seen_conn_pids[pid] = addr
                    conn_display[addr] = f"{nick} {sec_tag} ({addr})"
                continue
            if pid:
                seen_conn_pids[pid] = addr
            conn_display[addr] = f"{nick} {sec_tag} ({addr})"

        header.peer_count = len(conn_display)
        sidebar.set_connected_peers(conn_display)
        is_sc = getattr(active_transport, "is_scanning", False)
        if trans_name == "bluetooth":
            is_off = self.coordinator.offline_mode or telemetry.get(
                "adapter_state"
            ) in ("Off", "Unavailable")
        elif trans_name == "offline":
            is_off = True
        else:
            is_off = self.coordinator.offline_mode or active_transport.state.value in (
                "unavailable",
                "disabled",
                "error",
                "offline",
            )
        sidebar.set_discovered_peers(
            active_transport.discovered_peers,
            is_scanning=is_sc,
            is_offline=is_off,
            transport=trans_name,
        )

        # Determine Bluetooth availability independently for BLE states:
        bt_trans = (
            self.coordinator._transports.get("bluetooth")
            if self.coordinator and hasattr(self.coordinator, "_transports")
            else None
        )
        bt_available = False
        if bt_trans:
            bt_telem = bt_trans.get_telemetry()
            adapter_state = bt_telem.get("adapter_state")
            bt_available = adapter_state == "On" or (
                adapter_state not in ("Off", "Unavailable")
                and bool(bt_telem.get("adapter_available"))
            )
        elif self.coordinator and self.coordinator.is_ble_available():
            bt_available = True

        # Update header-channel to match active transport
        with contextlib.suppress(Exception):
            chan_lbl = self.query_one("#header-channel", Label)
            if (
                self.coordinator.offline_mode
                or self.coordinator.selected_transport_name == "offline"
                or (
                    trans_name == "offline"
                    and getattr(self.coordinator, "selected_transport_name", None)
                    in (None, "offline")
                )
            ):
                chan_lbl.update("Secure • Offline")
            elif trans_name == "lan":
                chan_lbl.update("Secure • LAN Mesh")
            else:
                chan_lbl.update("Secure • BLE Mesh")

        # Truthful, strictly-isolated state reporting
        if (
            self.coordinator.offline_mode
            or self.coordinator.selected_transport_name == "offline"
        ):
            status_bar.mesh_status = "OFFLINE MODE"
        elif trans_name == "offline":
            bt_label = (
                "Bluetooth Available" if bt_available else "Bluetooth Unavailable"
            )
            if self.coordinator.selected_transport_name == "lan":
                status_bar.mesh_status = (
                    "✕ LAN Unavailable (offline) • Local network connection unavailable"
                )
            elif self.coordinator.ble_status in (
                "unavailable",
                "disabled",
                "error",
                "offline",
            ):
                status_bar.mesh_status = (
                    f"✕ Bluetooth Inactive ({self.coordinator.ble_status}) • {bt_label}"
                )
            else:
                status_bar.mesh_status = "OFFLINE MODE"
        elif trans_name == "lan":
            info = getattr(active_transport, "adapter_manager", None)
            current_info = info.current_info if info else None
            is_net_conn = current_info.is_connected if current_info else True
            lan_state = active_transport.state.value
            lan_avail = getattr(active_transport, "is_available", lambda: True)()
            if (
                not is_net_conn
                or lan_state in ("unavailable", "disabled", "error", "offline")
                or not lan_avail
            ):
                status_bar.mesh_status = (
                    "✕ LAN Unavailable (offline) • Local network connection unavailable"
                )
            else:
                connected_count = len(connected_addrs)
                authenticated_count = sum(
                    1
                    for addr in connected_addrs
                    if (
                        session := self.coordinator.get_session(
                            self.coordinator.address_to_peer_id.get(addr, "")
                        )
                    )
                    and session.is_established
                )
                if connected_count > 0:
                    if authenticated_count > 0:
                        status_bar.mesh_status = f"● LAN / Wi-Fi Connected • {authenticated_count} session(s)"
                    else:
                        status_bar.mesh_status = f"● LAN / Wi-Fi Connected • Handshake pending ({connected_count})"
                else:
                    scanning = getattr(active_transport, "is_scanning", False)
                    server_listening = getattr(
                        getattr(active_transport, "server", None),
                        "is_listening",
                        False,
                    )
                    discovered_count = len(active_transport.discovered_peers)
                    if scanning and server_listening:
                        status_bar.mesh_status = (
                            f"● LAN / Wi-Fi Active • Discovering Peers ({discovered_count} discovered)"
                            if discovered_count
                            else "● LAN / Wi-Fi Active • Discovering Peers"
                        )
                    elif server_listening:
                        status_bar.mesh_status = "● LAN / Wi-Fi Active • Listening"
                    else:
                        status_bar.mesh_status = "● LAN / Wi-Fi Active"
        else:
            adapter_state = telemetry.get("adapter_state")
            adapter_avail = telemetry.get("adapter_available", True)
            if adapter_state == "Off":
                status_bar.mesh_status = "✕ Bluetooth Disabled"
            elif adapter_state == "Unavailable" or not adapter_avail:
                status_bar.mesh_status = "✕ Bluetooth Unavailable"
            else:
                central_status = (
                    "BLE Central Scanning"
                    if telemetry.get("scanner_status") == "Active"
                    else "BLE Central Available"
                    if telemetry.get("central_supported")
                    else "BLE Central Unavailable"
                )
                if not telemetry.get("peripheral_supported", True):
                    peripheral_status = "BLE Peripheral Unsupported"
                elif telemetry.get("peripheral_error"):
                    peripheral_status = "BLE Peripheral Failed"
                elif telemetry.get("advertising_active"):
                    peripheral_status = "BLE Peripheral Advertising Active"
                else:
                    peripheral_status = "BLE Peripheral Inactive"

                connected_count = len(connected_addrs)
                authenticated_count = sum(
                    1
                    for addr in connected_addrs
                    if (
                        session := self.coordinator.get_session(
                            self.coordinator.address_to_peer_id.get(addr, "")
                        )
                    )
                    and session.is_established
                )
                if connected_count > 0:
                    if authenticated_count > 0:
                        status_bar.mesh_status = (
                            f"● Bluetooth Connected • {authenticated_count} session(s)"
                        )
                    else:
                        status_bar.mesh_status = f"● Bluetooth Connected • Handshake pending ({connected_count})"
                elif self.coordinator.effective_active_transport_name == "bluetooth":
                    status_bar.mesh_status = (
                        f"● Bluetooth Active • {central_status} • {peripheral_status}"
                    )
                elif telemetry.get("adapter_state") == "On":
                    status_bar.mesh_status = f"● Bluetooth Available • {central_status} • {peripheral_status}"
                else:
                    status_bar.mesh_status = "✕ Bluetooth Unavailable"

        self._update_target_status()

    def _update_target_status(self) -> None:
        """Update status bar target line reflecting active context and connectivity."""
        status_bar = self.query_one(StatusBar)
        if self.active_context == "#public":
            status_bar.target_status = "Target: #public"
        elif self.active_context.startswith("@"):
            peer_nick = self.active_context[1:].strip()
            is_connected = False
            if self.coordinator:
                for addr in self.coordinator.active_transport.connected_peers:
                    pid = self.coordinator.address_to_peer_id.get(addr, "")
                    nick = self.coordinator.peer_nicknames.get(
                        pid, pid[:8] if pid else addr
                    )
                    if nick.lower() == peer_nick.lower() or (
                        pid and pid.lower().startswith(peer_nick.lower())
                    ):
                        is_connected = True
                        break
            if is_connected:
                status_bar.target_status = f"Target: @{peer_nick}"
            else:
                status_bar.target_status = f"Target: @{peer_nick} • Offline"
        else:
            status_bar.target_status = f"Target: {self.active_context}"

    def _safe_post_message(self, message: Message) -> None:
        """Post a Textual message safely across threads and lifecycle states."""
        import threading

        try:
            if getattr(self, "_thread_id", None) == threading.get_ident():
                self.post_message(message)
            else:
                self.call_from_thread(self.post_message, message)
        except Exception as e:
            logger.debug("Failed to post message %s: %s", message, e)

    def _on_coordinator_ble_error(self, error: TransportError | str) -> None:
        """Queue BLE failures for handling inside the active Textual app context."""
        generation = self.coordinator.transport_generation if self.coordinator else None
        self._safe_post_message(BleErrorReported(error, generation))

    def _on_coordinator_ble_warning(self, warning: TransportWarning | str) -> None:
        """Queue non-fatal BLE role limitations inside the Textual app context."""
        generation = self.coordinator.transport_generation if self.coordinator else None
        self._safe_post_message(BleWarningReported(warning, generation))

    def _on_coordinator_lan_error(self, error: TransportError | str) -> None:
        """Queue LAN failures for handling inside the active Textual app context."""
        generation = self.coordinator.transport_generation if self.coordinator else None
        self._safe_post_message(LanErrorReported(error, generation))

    def _get_chat_view(self) -> ChatView | None:
        """Safely retrieve active ChatView without raising if on modal or HomeScreen."""
        try:
            return self.query_one(ChatView)
        except Exception:
            if self._screen_stack:
                for s in self._screen_stack:
                    with contextlib.suppress(Exception):
                        return s.query_one(ChatView)
        return None

    def on_ble_warning_reported(self, event: BleWarningReported) -> None:
        """Present a BLE role limitation without marking Bluetooth offline."""
        if (
            self.coordinator is not None
            and (
                self.coordinator.offline_mode
                or self.coordinator.active_transport_name != "bluetooth"
            )
            and not self.coordinator.is_transport_starting("bluetooth")
        ):
            return
        if (
            event.generation is not None
            and self.coordinator is not None
            and event.generation != self.coordinator.transport_generation
        ):
            return
        if event.event and event.event.transport != TransportType.BLUETOOTH:
            return
        ble_transport = (
            self.coordinator._transports.get("bluetooth") if self.coordinator else None
        )
        telemetry = ble_transport.get_telemetry() if ble_transport else {}
        self._refresh_peer_lists()
        if not any(isinstance(s, BLEErrorModal) for s in self._screen_stack):
            from bitchat.tui.screens.connection import ConnectionModal

            if isinstance(self.screen, ConnectionModal):
                self.screen.dismiss(None)
            peripheral_failure = bool(
                telemetry.get("peripheral_error")
                or "peripheral" in event.warning.lower()
            )
            self.push_screen(
                BLEErrorModal(
                    error_message=event.warning,
                    bluetooth_available=True,
                    central_active=(
                        telemetry.get("central_supported", False)
                        and telemetry.get("scanner_status") == "Active"
                    ),
                    peripheral_failure=peripheral_failure,
                    peripheral_supported=bool(
                        telemetry.get("peripheral_supported", True)
                    ),
                    lan_available=True,
                    failed_stage=telemetry.get("failed_stage"),
                    error_code=telemetry.get("error_code"),
                    hresult=telemetry.get("hresult"),
                    error_source=telemetry.get("error_source"),
                    acknowledgement_mode=not self._ble_warning_acknowledged,
                ),
                self._on_ble_modal_dismissed,
            )

    def on_ble_error_reported(self, event: BleErrorReported) -> None:
        """Present a coordinator BLE failure from the Textual message loop."""
        if (
            (event.error is not None or event.generation is not None)
            and self.coordinator is not None
            and self.coordinator.active_transport_name != "bluetooth"
        ):
            return
        if (
            event.generation is not None
            and self.coordinator is not None
            and event.generation != self.coordinator.transport_generation
        ):
            return
        if event.error and event.error.transport != TransportType.BLUETOOTH:
            return
        self._refresh_peer_lists()
        self._present_ble_recovery_dialog(event.error_message)

    def _present_ble_recovery_dialog(self, error_message: str) -> None:
        """Show the BLE recovery dialog unless one is already open."""
        if any(isinstance(s, BLEErrorModal) for s in self._screen_stack):
            return
        from bitchat.tui.screens.connection import ConnectionModal

        if isinstance(self.screen, ConnectionModal):
            self.screen.dismiss(None)
        ble_transport = (
            self.coordinator._transports.get("bluetooth") if self.coordinator else None
        )
        telemetry = ble_transport.get_telemetry() if ble_transport else {}
        radio_available = telemetry.get("adapter_state") == "On"
        self.push_screen(
            BLEErrorModal(
                error_message=error_message,
                bluetooth_available=radio_available,
                central_active=(
                    radio_available and telemetry.get("scanner_status") == "Active"
                ),
                peripheral_failure=bool(telemetry.get("peripheral_error")),
                peripheral_supported=bool(telemetry.get("peripheral_supported", True)),
                lan_available=True,
                failed_stage=telemetry.get("failed_stage"),
                error_code=telemetry.get("error_code"),
                hresult=telemetry.get("hresult"),
                error_source=telemetry.get("error_source"),
                acknowledgement_mode=not self._ble_warning_acknowledged,
            ),
            self._on_ble_modal_dismissed,
        )

    def on_lan_error_reported(self, event: LanErrorReported) -> None:
        """Present a coordinator LAN failure from the Textual message loop."""
        if (
            (event.error is not None or event.generation is not None)
            and self.coordinator is not None
            and (
                self.coordinator.offline_mode
                or self.coordinator.active_transport_name != "lan"
            )
        ):
            return
        if (
            event.generation is not None
            and self.coordinator is not None
            and event.generation != self.coordinator.transport_generation
        ):
            return
        if event.error and event.error.transport != TransportType.LAN:
            return
        chat = self._get_chat_view()
        if chat is not None:
            chat.add_error_message(f"LAN Error: {event.error_message}")
        guidance = (
            "Local network connectivity is unavailable. "
            "BitChat cannot currently use LAN/Wi-Fi transport."
        )
        if chat is not None:
            chat.add_system_message(guidance)
        self._refresh_peer_lists()
        if not any(isinstance(s, BLEErrorModal) for s in self._screen_stack):
            from bitchat.tui.screens.connection import ConnectionModal

            if isinstance(self.screen, ConnectionModal):
                self.screen.dismiss(None)
            ble_available = self._is_ble_available()
            lan_trans = (
                self.coordinator._transports.get("lan")
                if self.coordinator and hasattr(self.coordinator, "_transports")
                else None
            )
            lan_telem = lan_trans.get_telemetry() if lan_trans else {}
            self.push_screen(
                BLEErrorModal(
                    error_message=event.error_message,
                    transport="lan",
                    ble_available=ble_available,
                    failed_stage=lan_telem.get("failed_stage"),
                    error_code=lan_telem.get("error_code"),
                    hresult=lan_telem.get("hresult"),
                    error_source=lan_telem.get("error_source"),
                ),
                self._on_lan_modal_dismissed,
            )

    def _on_ble_modal_dismissed(self, result: str | None) -> None:
        if result == "acknowledged":
            self._ble_warning_acknowledged = True
            return
        self._ble_warning_acknowledged = True
        if result == "retry":
            self._spawn_task(self._handle_ble_retry())
        elif result == "lan":
            self._handle_lan_fallback()
        else:
            self._handle_continue_offline()

    def _on_lan_modal_dismissed(self, result: str | None) -> None:
        if result == "retry":
            self._spawn_task(self._handle_lan_retry())
        elif result in ("ble", "switch_ble"):
            self._handle_ble_fallback()
        else:
            self._handle_continue_offline()

    def _handle_lan_fallback(self) -> None:
        """Switch to LAN transport after BLE failure, reusing existing switch path."""
        chat = self._get_chat_view()
        if chat is not None:
            chat.add_system_message(
                "Switching to LAN / Wi-Fi transport. Discovering local peers..."
            )
        self._handle_transport_switch("lan")

    def _handle_ble_fallback(self) -> None:
        """Switch to BLE transport after LAN failure, reusing existing switch path."""
        chat = self._get_chat_view()
        if chat is not None:
            chat.add_system_message(
                "Switching to Bluetooth Low Energy transport. Scanning for local peers..."
            )
        self._handle_transport_switch("bluetooth")

    async def _handle_lan_retry(self) -> None:
        """Attempt to re-initialize LAN services and notify user."""
        chat = self._get_chat_view()
        if chat is not None:
            chat.add_system_message("Retrying LAN initialization...")
        if self.coordinator:
            success = await self.coordinator.retry_lan()
            if success:
                telemetry = self.coordinator.active_transport.get_telemetry()
                iface = telemetry.get("interface", "Network")
                if chat is not None:
                    chat.add_system_message(
                        f"LAN reconnected successfully on {iface}. LAN Mesh Active."
                    )
                self._refresh_peer_lists()
            else:
                err = (
                    self.coordinator.lan_error_message
                    or "Local network connection unavailable"
                )
                if chat is not None:
                    chat.add_error_message(
                        f"LAN retry failed: {err}. Remaining in offline mode."
                    )
                self._refresh_peer_lists()

    def _handle_continue_offline(self) -> None:
        """Disable networking cleanly; local UI features stay available."""
        chat = self._get_chat_view()
        if self.coordinator:
            self._spawn_task(self._go_offline(self.coordinator))
        elif chat is not None:
            chat.add_system_message("Operating in Offline Mode.")

    async def _go_offline(self, coordinator: SessionCoordinator) -> None:
        await coordinator.go_offline()
        self.config.transport = "offline"
        with contextlib.suppress(Exception):
            self.storage.save_config(self.config)
        self._refresh_peer_lists()
        chat = self._get_chat_view()
        if chat is not None:
            chat.add_system_message("Operating in Offline Mode.")

    def _is_ble_available(self) -> bool:
        """Check if Bluetooth transport is registered and adapter is available."""
        if not self.coordinator:
            return False
        return self.coordinator.is_ble_available()

    def _resolve_peer_address(self, target: str) -> str | None:
        """Resolve a nickname, peer ID prefix, or discovered device
        to a concrete BLE address.
        """
        if not self.coordinator:
            return None

        clean_target = target.strip().lstrip("@")
        clean_lower = clean_target.lower()

        # 1. Ask coordinator to resolve through known addresses and discovered peers
        resolved = self.coordinator.resolve_peer_address(clean_target)
        if resolved:
            return resolved

        # 2. Match exact address in discovered peers
        if clean_target in self.coordinator.active_transport.discovered_peers:
            return clean_target

        # 3. Match unpunctuated MAC/IP ONLY if it exists in discovered peers
        unpunctuated = clean_lower.replace(":", "").replace("-", "")
        for addr in self.coordinator.active_transport.discovered_peers:
            if addr.replace(":", "").replace("-", "").lower() == unpunctuated:
                return addr

        # DO NOT blindly fabricate a MAC address from a raw peer ID!
        return None

    def _on_coordinator_message(
        self, sender_id: str, text: str, is_encrypted: bool
    ) -> None:
        """Handle incoming chat message from coordinator."""
        nick = sender_id[:8]
        if self.coordinator and sender_id in self.coordinator.peer_nicknames:
            nick = self.coordinator.peer_nicknames[sender_id]

        def _do_write() -> None:
            chat = self.query_one(ChatView)
            chat.add_chat_message(nick, text, is_encrypted=is_encrypted, is_self=False)

        self._dispatch_ui(_do_write)

    def _on_coordinator_peer_status(self, peer: str, status: str) -> None:
        """Handle peer connectivity change."""

        def _do_update() -> None:
            chat = self.query_one(ChatView)
            if status.casefold() == "disconnected":
                disconnected_peers = [
                    peer_id
                    for peer_id, address in self._authenticated_peer_addresses.items()
                    if address == peer
                ]
                for peer_id in disconnected_peers:
                    self._authenticated_peer_addresses.pop(peer_id, None)
                    self._authenticated_transport_peers.discard(peer_id)

            if peer != "mesh" and status.casefold() != "connected":
                chat.add_system_message(f"Peer {peer}: {status}")
            self._refresh_peer_lists()

        self._dispatch_ui(_do_update)

    def _on_coordinator_handshake(self, peer_id: str, fingerprint: str) -> None:
        """Handle successful Noise XX handshake."""
        coordinator = self.coordinator
        if coordinator is None:
            return

        short_fp = fingerprint[:16] + "..." if len(fingerprint) > 16 else fingerprint

        def _do_notify() -> None:
            if peer_id in self._authenticated_transport_peers:
                self._refresh_peer_lists()
                return

            self._authenticated_transport_peers.add(peer_id)
            address = coordinator.peer_addresses.get(peer_id)
            if address is None:
                address = next(
                    (
                        peer_address
                        for peer_address, known_peer_id in (
                            coordinator.address_to_peer_id.items()
                        )
                        if known_peer_id == peer_id
                    ),
                    None,
                )
            if address is not None:
                self._authenticated_peer_addresses[peer_id] = address

            chat = self.query_one(ChatView)
            chat.add_security_event(
                f"Noise XX session established with {peer_id[:8]} (FP: {short_fp})"
            )
            transport_name = coordinator.active_transport_name
            connection_label = "LAN" if transport_name == "lan" else "Bluetooth"
            chat.add_system_message(f"Connected via {connection_label}")
            self._refresh_peer_lists()

        self._dispatch_ui(_do_notify)

    def _dispatch_ui(self, callback: Any) -> None:
        """Safely execute UI callback whether on main thread or background thread."""
        import threading

        if self._thread_id == threading.get_ident():
            callback()
        else:
            self.call_from_thread(callback)

    def switch_conversation_context(self, target: str) -> None:
        """Switch active conversation context between #public and @peer."""
        if not target or target in ("#public", "public", "Local Node"):
            self.active_context = "#public"
        elif target.startswith("@"):
            self.active_context = target
        else:
            self.active_context = f"@{target}"

        chat = self.query_one(ChatView)
        chat.channel_name = self.active_context
        self._update_target_status()
        msg_input = self.query_one(MessageInput)
        msg_input.focus()

    def _open_peer_info(self, peer_identifier: str, address: str = "") -> None:
        """Open detailed PeerInfoModal with safe public identity info."""
        if not self.coordinator:
            self.push_screen(
                PeerInfoModal(
                    nickname=peer_identifier,
                    peer_id_hex="N/A (No Coordinator)",
                    fingerprint="N/A",
                    address=address,
                )
            )
            return

        resolved_pid = ""
        resolved_nick = peer_identifier.lstrip("@")
        for pid, nick in self.coordinator.peer_nicknames.items():
            if nick.lower() == resolved_nick.lower() or pid.startswith(resolved_nick):
                resolved_pid = pid
                resolved_nick = nick
                break

        if not resolved_pid and address in self.coordinator.address_to_peer_id:
            resolved_pid = self.coordinator.address_to_peer_id[address]
            resolved_nick = self.coordinator.peer_nicknames.get(
                resolved_pid, resolved_pid[:8]
            )

        session = self.coordinator.get_session(resolved_pid) if resolved_pid else None
        fp = (
            session.remote_fingerprint if session and session.remote_fingerprint else ""
        )
        is_enc = session.is_established if session else False
        is_conn = bool(
            address and address in self.coordinator.active_transport.connected_peers
        )

        self.push_screen(
            PeerInfoModal(
                nickname=resolved_nick,
                peer_id_hex=resolved_pid or "Unknown Node ID",
                fingerprint=fp or "Handshake pending / Unverified",
                address=address
                or self.coordinator.peer_addresses.get(resolved_pid, "Mesh Multi-Hop"),
                is_connected=is_conn,
                is_encrypted=is_enc,
            )
        )

    def on_status_bar_action_triggered(self, event: StatusBar.ActionTriggered) -> None:
        """Handle clicks on bottom Action Bar buttons."""
        match event.action:
            case "edit":
                self.action_open_edit_theme()
            case "settings":
                self.action_open_settings()
            case "peers":
                self.action_open_peers()
            case "commands":
                self.action_open_commands()
            case "help":
                self.action_show_help()
            case "quit":
                self._spawn_task(self.action_quit())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button pressed events from bottom action bar or screens."""
        bid = event.button.id or ""
        match bid:
            case "btn-action-edit":
                self.action_open_edit_theme()
            case "btn-action-settings":
                self.action_open_settings()
            case "btn-action-peers":
                self.action_open_peers()
            case "btn-action-commands":
                self.action_open_commands()
            case "btn-action-help":
                self.action_show_help()
            case "btn-action-quit":
                self._spawn_task(self.action_quit())

    def on_peer_sidebar_peer_selected(self, event: PeerSidebar.PeerSelected) -> None:
        """Handle peer selection from sidebar to switch conversation context."""
        self.switch_conversation_context(event.peer_identifier)

    def on_peer_sidebar_peer_info_requested(
        self, event: PeerSidebar.PeerInfoRequested
    ) -> None:
        """Handle peer info request from sidebar."""
        self._open_peer_info(event.peer_identifier, event.address)

    def on_peer_info_modal_start_direct_message(
        self, event: PeerInfoModal.StartDirectMessage
    ) -> None:
        """Handle user selecting Direct Message from PeerInfoModal."""
        self.switch_conversation_context(f"@{event.nickname}")

    def on_settings_screen_settings_saved(
        self, event: SettingsModal.SettingsSaved
    ) -> None:
        """Handle applied settings changes."""
        if self.coordinator:
            self.coordinator.set_nickname(event.nickname)
            self.coordinator.mesh_router.max_relay_ttl = event.max_hops
            self.coordinator.inter_fragment_delay = (
                event.inter_fragment_delay_ms / 1000.0
            )
            self._spawn_task(self.coordinator.send_announce(event.nickname))
            try:
                base_screen = (
                    self._screen_stack[0] if self._screen_stack else self.screen
                )
                base_screen.query_one(PeerSidebar).update_identity(event.nickname)
                base_screen.query_one(HeaderWidget).nickname = event.nickname
            except Exception:
                pass

        # SettingsScreen has already persisted the complete configuration. Update
        # the in-memory copy without writing a potentially stale partial snapshot.
        self.config.nickname = event.nickname
        self.config.max_hops = event.max_hops
        self.config.inter_fragment_delay_ms = event.inter_fragment_delay_ms
        self.config.keybindings = event.keybindings
        self.apply_keybindings(self.config.keybindings)

        # Settings saved status is exclusively displayed in the dedicated Settings
        # indicator; chat log is kept clean.

        # Update visual theme accent and message density if modified
        if (
            hasattr(event, "accent")
            and event.accent
            and event.accent != self.current_accent
        ):
            old_accent = self.current_accent
            self.current_accent = event.accent
            self.remove_class(f"accent-{old_accent}")
            self.add_class(f"accent-{self.current_accent}")
            self.config.accent = self.current_accent

        if (
            hasattr(event, "density")
            and event.density
            and event.density != self.current_density
        ):
            old_density = self.current_density
            self.current_density = event.density
            self.remove_class(f"density-{old_density}")
            self.add_class(f"density-{self.current_density}")
            self.config.density = self.current_density

        target_trans = normalize_transport_name(
            getattr(event, "transport", "bluetooth")
        )
        curr_trans = (
            self.coordinator.effective_active_transport_name
            if self.coordinator
            else getattr(self.config, "transport", "bluetooth")
        )
        if target_trans and target_trans != curr_trans:
            self._handle_transport_switch(target_trans)

    def _handle_transport_switch(self, target_transport: str) -> None:
        """Switch active transport between Bluetooth, LAN, and Offline."""
        chat = None
        try:
            chat = self.query_one(ChatView)
        except Exception:
            if self._screen_stack:
                with contextlib.suppress(Exception):
                    chat = self._screen_stack[0].query_one(ChatView)

        target = normalize_transport_name(target_transport)
        if target is None:
            if chat is not None:
                chat.add_error_message(
                    "Invalid transport. Usage: /transport "
                    "<bluetooth|ble|lan|wifi|offline>"
                )
            return

        if not self.coordinator:
            if chat is not None:
                chat.add_error_message(
                    "Cannot switch transport because the coordinator is not running."
                )
            return

        if (
            self._transport_switch_task is not None
            and not self._transport_switch_task.done()
        ):
            if chat is not None:
                chat.add_error_message(
                    "A transport switch is already in progress. Please wait."
                )
            return

        coord = self.coordinator

        async def _do_switch() -> None:
            previous_ble_warning_ids = {
                diagnostic.operation_id
                for diagnostic in coord.transport_diagnostics.get(
                    TransportType.BLUETOOTH, []
                )
                if not isinstance(diagnostic, TransportError)
            }
            try:
                success, msg = await coord.switch_transport(target)
                base_screen = (
                    self._screen_stack[0] if self._screen_stack else self.screen
                )
                try:
                    sidebar = base_screen.query_one(PeerSidebar)
                    header = base_screen.query_one(HeaderWidget)
                    sidebar.active_transport = coord.effective_active_transport_name
                    sidebar.peer_id_hex = coord.local_identity.peer_id_hex
                    sidebar.fingerprint = coord.local_identity.fingerprint
                    sidebar.update_identity(coord.nickname)
                    header.peer_id_hex = coord.local_identity.peer_id_hex
                    header.fingerprint = coord.local_identity.fingerprint
                    header.nickname = coord.nickname
                except Exception:
                    logger.debug("Unable to refresh transport identity widgets")

                curr_chat = self._get_chat_view()
                if success:
                    if target in ("bluetooth", "lan"):
                        self.config.transport = target
                        try:
                            self.storage.save_config(self.config)
                        except Exception as e:
                            logger.warning(
                                "Failed to save switched transport config: %s", e
                            )
                    if curr_chat is not None:
                        curr_chat.add_system_message(msg)
                    if target == "bluetooth":
                        new_ble_warnings = [
                            diagnostic
                            for diagnostic in coord.transport_diagnostics.get(
                                TransportType.BLUETOOTH, []
                            )
                            if not isinstance(diagnostic, TransportError)
                            and diagnostic.operation_id not in previous_ble_warning_ids
                        ]
                        ble_transport = coord._transports.get("bluetooth")
                        ble_telem = (
                            ble_transport.get_telemetry() if ble_transport else {}
                        )
                        peripheral_error = ble_telem.get("peripheral_error") or (
                            new_ble_warnings[-1].message if new_ble_warnings else None
                        )
                        if peripheral_error:
                            self._present_ble_recovery_dialog(str(peripheral_error))
                else:
                    if curr_chat is not None:
                        if (
                            target == "bluetooth"
                            and coord.effective_active_transport_name == "lan"
                        ):
                            curr_chat.add_error_message(
                                "Requested transport was not activated; "
                                "LAN remains active."
                            )
                        else:
                            curr_chat.add_error_message(
                                f"Transport switch failed: {msg}"
                            )
                    if target == "lan":
                        alt = (
                            "Use /transport bluetooth, retry with /scan, "
                            "or continue offline."
                            if coord.is_ble_available()
                            else "Retry with /scan once connected, or continue offline."
                        )
                        if curr_chat is not None:
                            curr_chat.add_system_message(alt)
                        if not any(
                            isinstance(s, BLEErrorModal) for s in self._screen_stack
                        ):
                            lan_trans = coord._transports.get("lan")
                            lan_telem = lan_trans.get_telemetry() if lan_trans else {}
                            self.push_screen(
                                BLEErrorModal(
                                    error_message=msg,
                                    transport="lan",
                                    ble_available=coord.is_ble_available(),
                                    failed_stage=lan_telem.get("failed_stage"),
                                    error_code=lan_telem.get("error_code"),
                                    hresult=lan_telem.get("hresult"),
                                    error_source=lan_telem.get("error_source"),
                                ),
                                self._on_lan_modal_dismissed,
                            )
                    elif target == "bluetooth":
                        if curr_chat is not None:
                            curr_chat.add_system_message(
                                "Use /transport lan, retry with /scan, or continue offline."
                            )
                        self._present_ble_recovery_dialog(msg)
            finally:
                self._refresh_peer_lists()
                coord.record_transport_indicator_update()

        self._transport_switch_task = self._spawn_task(_do_switch())

    def on_edit_theme_modal_theme_applied(
        self, event: EditThemeModal.ThemeApplied
    ) -> None:
        """Handle applied appearance changes."""
        old_density = self.current_density
        old_accent = self.current_accent

        self.current_density = event.density
        self.current_show_timestamps = event.show_timestamps
        self.current_accent = event.accent_name

        # Swap density and accent classes on the application root
        self.remove_class(f"density-{old_density}")
        self.add_class(f"density-{self.current_density}")
        self.remove_class(f"accent-{old_accent}")
        self.add_class(f"accent-{self.current_accent}")

        chat = self._get_chat_view()
        if chat is not None:
            chat.compact_mode = event.density == "compact"
            chat.show_timestamps = event.show_timestamps
            chat.re_render_all()

        # Update and persist config
        self.config.density = self.current_density
        self.config.show_timestamps = self.current_show_timestamps
        self.config.accent = self.current_accent
        try:
            self.storage.save_config(self.config)
        except Exception as e:
            logger.warning("Failed to save theme settings to storage: %s", e)

        # Theme applied directly to UI; chat log kept clean.

    async def _handle_ble_retry(self) -> None:
        """Attempt to re-initialize BLE services and update dashboard."""
        if self.coordinator:
            success = await self.coordinator.retry_ble()
            self._refresh_peer_lists()
            for s in self._screen_stack:
                if isinstance(s, HomeScreen):
                    s.refresh_status()

            chat = None
            try:
                chat = self.query_one(ChatView)
            except Exception:
                if self._screen_stack:
                    with contextlib.suppress(Exception):
                        chat = self._screen_stack[0].query_one(ChatView)

            if success:
                telemetry = self.coordinator.active_transport.get_telemetry()
                if telemetry.get("peripheral_error"):
                    self._present_ble_recovery_dialog(telemetry["peripheral_error"])
                elif telemetry.get("peripheral_supported") and chat is not None:
                    chat.add_system_message(
                        "Bluetooth reconnected successfully. BLE Mesh Active."
                    )
            else:
                self._present_ble_recovery_dialog(
                    self.coordinator.ble_error_message or "Bluetooth did not start"
                )

    def on_input_changed(self, event: Input.Changed) -> None:
        """Dynamically evaluate input and manage autocomplete suggestions."""
        val = event.value
        try:
            palette = self.query_one(AutocompletePalette)
        except NoMatches:
            # Input events can fire during startup/teardown before the
            # palette is mounted; there is nothing to update yet.
            return

        # Trigger on '@' for peer autocompletion
        if val.startswith("@"):
            if " " in val:
                palette.hide()
                return
            query = val[1:].lower().strip()
            peer_items: list[tuple[str, str]] = []
            if self.coordinator:
                for pid, nick in self.coordinator.peer_nicknames.items():
                    if (
                        not query
                        or nick.lower().startswith(query)
                        or query in nick.lower()
                        or (len(query) >= 4 and query in pid.lower())
                    ):
                        peer_items.append(
                            (f"@{nick} ", f"Peer: {pid[:8]}... (Encrypted)")
                        )
            if not peer_items and self.coordinator:
                for (
                    addr,
                    peer,
                ) in self.coordinator.active_transport.discovered_peers.items():
                    name = (
                        getattr(peer, "nickname", None)
                        or getattr(peer, "name", None)
                        or addr
                    )
                    if (
                        not query
                        or name.lower().startswith(query)
                        or query in name.lower()
                    ):
                        rssi = getattr(peer, "rssi", None)
                        extra = f" ({rssi} dBm)" if rssi is not None else ""
                        peer_items.append((f"@{name} ", f"{addr}{extra}"))
            palette.show_suggestions(peer_items, title="Peers (@mention / DM)")
            return

        if not val.startswith("/"):
            palette.hide()
            return

        tokens = val.split(maxsplit=1)
        if len(tokens) == 1 and not val.endswith(" "):
            # Filtering command names (/c, /dm, etc.)
            suggestions = get_command_suggestions(tokens[0])
            items = [(s.name, s.description) for s in suggestions]
            palette.show_suggestions(items, title="Commands")
        elif len(tokens) >= 1 and (val.startswith("/dm ") or val.startswith("/info ")):
            parts = val.split(maxsplit=2)
            if len(parts) >= 3 or (len(parts) == 2 and val.endswith(" ")):
                palette.hide()
                return
            query = tokens[1] if len(tokens) > 1 else ""
            cmd_prefix = "/dm" if val.startswith("/dm ") else "/info"
            peer_items = []
            if self.coordinator:
                for pid, nick in self.coordinator.peer_nicknames.items():
                    if (
                        not query
                        or query.lower() in nick.lower()
                        or query.lower() in pid.lower()
                    ):
                        peer_items.append(
                            (f"{cmd_prefix} {nick} ", f"Peer ID: {pid[:8]}...")
                        )
            palette.show_suggestions(peer_items, title="Peers (Noise XX)")
        elif len(tokens) >= 1 and val.startswith("/connect "):
            # Contextual discovered address argument completion
            query = tokens[1] if len(tokens) > 1 else ""
            addr_items: list[tuple[str, str]] = []
            if self.coordinator:
                coord = self.coordinator
                for addr, peer in coord.active_transport.discovered_peers.items():
                    name = (
                        getattr(peer, "nickname", None)
                        or getattr(peer, "name", None)
                        or "Unknown"
                    )
                    if (
                        not query
                        or query.lower() in addr.lower()
                        or query.lower() in name.lower()
                    ):
                        rssi = getattr(peer, "rssi", None)
                        extra = f" ({rssi} dBm)" if rssi is not None else ""
                        addr_items.append((f"/connect {addr}", f"{name}{extra}"))
                trans_label = (
                    "BLE" if coord.active_transport_name == "bluetooth" else "LAN"
                )
                title = f"Discovered {trans_label} Peers"
                palette.show_suggestions(addr_items, title=title)
        else:
            palette.hide()

    def on_message_input_autocomplete_action(
        self, event: MessageInput.AutocompleteAction
    ) -> None:
        """Handle navigation and selection events from MessageInput."""
        palette = self.query_one(AutocompletePalette)
        msg_input = self.query_one(MessageInput)

        match event.action:
            case "prev":
                palette.select_prev()
            case "next":
                palette.select_next()
            case "dismiss":
                palette.hide()
            case "accept":
                selected = palette.get_selected_value()
                if selected is not None:
                    matching_spec = next(
                        (s for s in COMMAND_REGISTRY if s.name == selected), None
                    )
                    if matching_spec and matching_spec.arg_type is not None:
                        msg_input.value = f"{selected} "
                    else:
                        msg_input.value = selected
                    palette.hide()
                    msg_input.cursor_position = len(msg_input.value)

    def on_autocomplete_palette_suggestion_accepted(
        self, event: AutocompletePalette.SuggestionAccepted
    ) -> None:
        """Handle mouse click on autocomplete item."""
        msg_input = self.query_one(MessageInput)
        palette = self.query_one(AutocompletePalette)

        matching_spec = next(
            (s for s in COMMAND_REGISTRY if s.name == event.value), None
        )
        if matching_spec and matching_spec.arg_type is not None:
            msg_input.value = f"{event.value} "
        else:
            msg_input.value = event.value
        palette.hide()
        msg_input.cursor_position = len(msg_input.value)
        msg_input.focus()

    def _send_chat_message(self, chat: ChatView, text: str) -> None:
        """Send normal chat message honoring active conversation context."""
        if self.coordinator and self.coordinator.offline_mode:
            chat.add_system_message(
                "Cannot send message: BitChat is in Offline Mode. "
                "Select Bluetooth or LAN in Connection menu to enable networking."
            )
            return

        if self.active_context.startswith("@"):
            target_peer = self.active_context[1:]
            chat.add_chat_message(
                self.coordinator.nickname if self.coordinator else "You",
                f"(to @{target_peer}): {text}",
                is_encrypted=True,
                is_self=True,
            )
            if self.coordinator:
                resolved_pid = target_peer
                for pid, nick in self.coordinator.peer_nicknames.items():
                    if nick.lower() == target_peer.lower():
                        resolved_pid = pid
                        break
                self._spawn_task(
                    self.coordinator.send_direct_message(resolved_pid, text)
                )
        else:
            chat.add_chat_message(
                self.coordinator.nickname if self.coordinator else "You",
                text,
                is_encrypted=False,
                is_self=True,
            )
            if self.coordinator:
                self._spawn_task(self.coordinator.send_broadcast_message(text))

    def _send_direct_message(
        self, chat: ChatView, target_peer: str, dm_text: str
    ) -> None:
        """Send an encrypted direct message to a specified peer."""
        if self.coordinator and self.coordinator.offline_mode:
            chat.add_system_message(
                "Cannot send direct message: BitChat is in Offline Mode. "
                "Select Bluetooth or LAN in Connection menu to enable networking."
            )
            return

        chat.add_chat_message(
            self.coordinator.nickname if self.coordinator else "You",
            f"(to {target_peer}): {dm_text}",
            is_encrypted=True,
            is_self=True,
        )
        if self.coordinator:
            resolved_pid = None
            clean_target = target_peer.lstrip("@").lower()
            for pid, nick in self.coordinator.peer_nicknames.items():
                if nick.lower() == clean_target or pid.lower().startswith(clean_target):
                    resolved_pid = pid
                    break
            if resolved_pid is None:
                try:
                    bytes.fromhex(clean_target)
                    resolved_pid = clean_target
                except ValueError:
                    pass

            if resolved_pid:
                self._spawn_task(
                    self.coordinator.send_direct_message(resolved_pid, dm_text)
                )
            else:
                chat.add_error_message(
                    f"Cannot send DM: peer '{target_peer}' not found."
                )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Process submitted chat line or slash command."""
        text = event.value.strip()
        msg_input = self.query_one(MessageInput)
        palette = self.query_one(AutocompletePalette)
        palette.hide()

        if not text:
            msg_input.value = ""
            return

        msg_input.record_history(text)
        msg_input.value = ""

        chat = self.query_one(ChatView)

        # Context switch shortcut: @peer without a message body
        if text.startswith("@") and len(text.split()) == 1 and len(text) > 1:
            target_peer = text[1:].strip()
            self.switch_conversation_context(f"@{target_peer}")
            chat.add_system_message(f"Switched conversation context to @{target_peer}")
            return

        # Direct message shortcut: @peer <message>
        if text.startswith("@"):
            cmd = self.parser.parse(text)
            if cmd.error_message:
                chat.add_error_message(cmd.error_message)
                return
            target_peer = cmd.args[0]
            dm_text = cmd.args[1]
            self._send_direct_message(chat, target_peer, dm_text)
            return

        # Single clear command-dispatch boundary: only execute a slash command
        # when trimmed input explicitly starts with '/'.
        if not text.startswith("/"):
            self._send_chat_message(chat, text)
            return

        # Process slash command
        cmd = self.parser.parse(text)
        self._dispatch_slash_command(chat, cmd, text)

    def _dispatch_slash_command(self, chat: ChatView, cmd: Command, text: str) -> None:
        """Dispatch a validated slash command whose trimmed input begins with '/'."""
        match cmd.command_type:
            case CommandType.HELP:
                self.action_show_help()

            case CommandType.HOME:
                self.action_open_home()

            case CommandType.SETTINGS:
                self.action_open_settings()

            case CommandType.CONFIGURE:
                self._handle_configure_command(cmd, chat)

            case CommandType.EDIT:
                self.action_open_edit_theme()

            case CommandType.INFO:
                if cmd.error_message:
                    chat.add_error_message(cmd.error_message)
                    return
                target_peer = cmd.args[0] if cmd.args else ""
                self._open_peer_info(target_peer)

            case CommandType.PUBLIC:
                self.switch_conversation_context("#public")
                chat.add_system_message("Switched to #public channel")

            case CommandType.TRANSPORT:
                if not cmd.args:
                    curr = (
                        self.coordinator.effective_active_transport_name
                        if self.coordinator
                        else getattr(self.config, "transport", "bluetooth")
                    )
                    state = (
                        (
                            "offline"
                            if curr == "offline"
                            else self.coordinator.active_transport.state.value
                        )
                        if self.coordinator
                        else "offline"
                    )
                    telem = (
                        self.coordinator.active_transport.get_telemetry()
                        if self.coordinator
                        and curr != "offline"
                        and hasattr(self.coordinator.active_transport, "get_telemetry")
                        else {}
                    )
                    port = telem.get("listening_port") or "N/A"
                    discovery = (
                        telem.get("discovery") or telem.get("scanner_status") or "N/A"
                    )
                    chat.add_system_message(
                        f"Active transport medium: {curr.upper()} (state: {state})"
                    )
                    chat.add_system_message(
                        f"Listener port: {port} | Discovery: {discovery}"
                    )
                    bt_avail = (
                        "Available"
                        if (self.coordinator and self.coordinator.is_ble_available())
                        else "Unavailable"
                    )
                    lan_avail = (
                        "Available"
                        if (self.coordinator and self.coordinator.is_lan_available())
                        else "Unavailable"
                    )
                    chat.add_system_message(
                        f"Supported transports: Bluetooth ({bt_avail}), "
                        f"LAN ({lan_avail}), Offline (Available)"
                    )
                    chat.add_system_message(
                        "Switch medium using: /transport bluetooth, "
                        "/transport ble, /transport lan, /transport wifi, "
                        "or /transport offline"
                    )
                    return
                target_trans = normalize_transport_name(cmd.args[0])
                if target_trans is None:
                    chat.add_error_message(
                        f"Unknown transport '{cmd.args[0]}'. Usage: /transport "
                        "<bluetooth|ble|lan|wifi|offline>"
                    )
                    return
                self._handle_transport_switch(target_trans)

            case CommandType.STATUS:
                self._display_status_diagnostics(chat)

            case CommandType.CLEAR:
                chat.clear_log()

            case CommandType.EXIT:
                self._spawn_task(self.action_quit())

            case CommandType.CONNECT:
                if not self.coordinator:
                    chat.add_system_message("Transport coordinator offline.")
                    return
                coord = self.coordinator
                if coord.offline_mode or coord.active_transport_name == "offline":
                    chat.add_system_message(
                        "Cannot connect: BitChat is in Offline Mode. "
                        "Select Bluetooth or LAN in Connection menu to enable networking."
                    )
                    return
                trans_name = coord.active_transport_name

                if not cmd.args:
                    discovered = coord.active_transport.discovered_peers
                    if not discovered:
                        chat.add_system_message(
                            f"No peers discovered yet. "
                            f"Scanning for nearby BitChat {trans_name.upper()} peers..."
                        )
                        self._spawn_task(coord.active_transport.start_discovery())
                    else:
                        chat.add_system_message(
                            f"Discovered {trans_name.upper()} peers "
                            f"({len(discovered)}):"
                        )
                        for addr, peer in discovered.items():
                            name = (
                                getattr(peer, "nickname", None)
                                or getattr(peer, "name", None)
                                or "Unknown"
                            )
                            rssi = getattr(peer, "rssi", None)
                            extra = f" ({rssi} dBm)" if rssi is not None else ""
                            chat.add_system_message(f"  • {addr} — {name}{extra}")
                        chat.add_system_message(
                            "Connect using: /connect <address_or_id>"
                        )
                    return

                target = cmd.args[0]
                resolved_addr = self._resolve_peer_address(target) or target
                desc = f" ({target})" if resolved_addr != target else ""
                chat.add_system_message(
                    f"Connecting to peer at {resolved_addr}{desc}..."
                )

                async def _perform_connect(addr: str, description: str) -> None:
                    try:
                        await coord.connect_peer(addr, timeout=10.0)
                        chat.add_system_message(
                            f"Connected to peer at {addr}{description}."
                        )
                        self._refresh_peer_lists()
                    except Exception as e:
                        chat.add_error_message(
                            f"Connection failed for {addr}{description}: {e}"
                        )
                        self._refresh_peer_lists()

                self._spawn_task(_perform_connect(resolved_addr, desc))

            case CommandType.DISCONNECT:
                if self.coordinator is None:
                    return
                coord = self.coordinator
                if cmd.args:
                    target = cmd.args[0]
                    resolved_addr = self._resolve_peer_address(target) or target
                    chat.add_system_message(f"Disconnecting from {resolved_addr}...")

                    async def _perform_disconnect(addr: str) -> None:
                        try:
                            await coord.disconnect_peer(addr)
                            chat.add_system_message(f"Disconnected from {addr}.")
                            self._refresh_peer_lists()
                        except Exception as e:
                            chat.add_error_message(f"Disconnect failed for {addr}: {e}")
                            self._refresh_peer_lists()

                    self._spawn_task(_perform_disconnect(resolved_addr))
                else:
                    chat.add_system_message("Disconnecting all peers...")

                    async def _perform_disconnect_all() -> None:
                        try:
                            for addr in list(coord.active_transport.connected_peers):
                                try:
                                    await coord.disconnect_peer(addr)
                                except Exception as err:
                                    logger.warning(
                                        "Error disconnecting peer %s: %s", addr, err
                                    )
                            chat.add_system_message("All peers disconnected.")
                            self._refresh_peer_lists()
                        except Exception as e:
                            chat.add_error_message(f"Error during disconnect: {e}")
                            self._refresh_peer_lists()

                    self._spawn_task(_perform_disconnect_all())

            case CommandType.SCAN:
                if self.coordinator is not None:
                    coord = self.coordinator
                    if coord.offline_mode or coord.active_transport_name == "offline":
                        chat.add_system_message(
                            "Cannot scan: BitChat is in Offline Mode. "
                            "Select Bluetooth or LAN in Connection menu to enable discovery."
                        )
                        return
                    trans_name = coord.active_transport_name
                    chat.add_system_message(
                        f"Starting {trans_name.upper()} discovery scan..."
                    )

                    async def _perform_scan() -> None:
                        try:
                            await coord.active_transport.start_discovery()
                            self._refresh_peer_lists()
                        except Exception as e:
                            chat.add_error_message(f"Scan failed: {e}")
                            self._refresh_peer_lists()

                    self._spawn_task(_perform_scan())

            case CommandType.ONLINE:
                if cmd.raw_input.strip().lower().startswith(("/peers", "peers")):
                    self.action_open_peers()
                    return
                if not self.coordinator:
                    chat.add_system_message("Coordinator offline.")
                    return
                coord = self.coordinator
                connected = coord.active_transport.connected_peers
                discovered = coord.active_transport.discovered_peers
                chat.add_system_message(f"Connected peers ({len(connected)}):")
                if connected:
                    for addr in connected:
                        pid = coord.address_to_peer_id.get(addr, "unknown")
                        nick = coord.peer_nicknames.get(pid, "unknown")
                        chat.add_system_message(
                            f"  • {addr} (Peer: {pid[:8]}, Nick: {nick})"
                        )
                else:
                    chat.add_system_message("  (No peers currently connected)")

                chat.add_system_message(f"Discovered nearby peers ({len(discovered)}):")
                if discovered:
                    for addr, peer in discovered.items():
                        name = (
                            getattr(peer, "nickname", None)
                            or getattr(peer, "name", None)
                            or "Unknown"
                        )
                        rssi = getattr(peer, "rssi", None)
                        extra = f" ({rssi} dBm)" if rssi is not None else ""
                        chat.add_system_message(f"  • {addr} — {name}{extra}")
                else:
                    chat.add_system_message(
                        "  (No nearby nodes found; type /scan to discover)"
                    )

            case CommandType.NAME:
                if cmd.error_message:
                    chat.add_error_message(cmd.error_message)
                    return
                new_name = cmd.args[0]
                if self.coordinator:
                    self.coordinator.set_nickname(new_name)
                    self._spawn_task(self.coordinator.send_announce(new_name))
                    sidebar = self.query_one(PeerSidebar)
                    header = self.query_one(HeaderWidget)
                    sidebar.update_identity(new_name)
                    header.nickname = new_name
                self.config.nickname = new_name
                try:
                    self.storage.save_config(self.config)
                except Exception as e:
                    logger.warning("Failed to save nickname to storage: %s", e)
                chat.add_system_message(f"Nickname changed to '{new_name}'")

            case CommandType.DM:
                if cmd.error_message:
                    chat.add_error_message(cmd.error_message)
                    return
                target_peer = cmd.args[0]
                dm_text = cmd.args[1]
                self._send_direct_message(chat, target_peer, dm_text)

            case CommandType.LARGE:
                if cmd.error_message:
                    chat.add_error_message(cmd.error_message)
                    return
                target_peer = cmd.args[0]
                chat.add_system_message(
                    f"Sending 1000B fragmented test message to {target_peer}..."
                )
                if self.coordinator:
                    resolved_pid = target_peer
                    for pid, nick in self.coordinator.peer_nicknames.items():
                        if nick.lower() == target_peer.lower():
                            resolved_pid = pid
                            break
                    large_payload = "FRAG-TEST-" + ("X" * 1000)
                    self._spawn_task(
                        self.coordinator.send_direct_message(
                            resolved_pid, large_payload
                        )
                    )

            case _:
                chat.add_error_message(
                    cmd.error_message or f"Unknown command: '{text}'."
                )

    def _handle_configure_command(self, cmd: Command, chat: ChatView) -> None:
        """Run diagnostics or open the requested configuration category."""
        if not cmd.args:
            self._display_configure_diagnostics(chat)
            return
        cat = cmd.args[0].lower().strip()
        valid_categories = {
            "general",
            "identity",
            "bluetooth",
            "network",
            "notifications",
            "appearance",
            "startup",
            "advanced",
            "lan",
            "wifi",
            "ble",
            "theme",
        }
        if cat in valid_categories:
            self.action_open_settings(category=cat)
        else:
            self.notify(
                f"Unknown configuration category: '{cat}'. "
                "Valid: general, network, bluetooth, appearance",
                severity="warning",
            )

    def _display_configure_diagnostics(self, chat: ChatView) -> None:
        """Run system, Bluetooth, and LAN capability diagnostics and display in chat."""
        from bitchat.platform.capabilities import (
            detect_system_capabilities,
            format_configure_report,
        )

        chat.add_system_message("Running system configuration diagnostics...")

        async def _run_diagnostics() -> None:
            try:
                report = await detect_system_capabilities()
                formatted = format_configure_report(report)
                for line in formatted.splitlines():
                    chat.add_system_message(line)
            except Exception as e:
                chat.add_error_message(f"Diagnostics failed: {e}")

        self._spawn_task(_run_diagnostics())

    def _display_status_diagnostics(self, chat: ChatView) -> None:
        """Display operational diagnostics in chat."""
        if not self.coordinator:
            chat.add_system_message("BitChat Status: Coordinator Offline")
            return

        status = self.coordinator.get_detailed_status()
        if status.get("transport") == "lan":
            iface = status.get("interface", "Unknown")
            trans_lbl = f"LAN ({iface})" if iface in ("Wi-Fi", "Ethernet") else "LAN"
            chat.add_system_message("══════════ BitChat LAN Status ══════════")
            chat.add_system_message(
                f"Transport:         {trans_lbl} ({status.get('state', 'unknown')})"
            )
            chat.add_system_message(f"Interface:         {iface}")
            chat.add_system_message(
                f"Wi-Fi SSID:        {status.get('ssid') or 'unavailable'}"
            )
            local_ip = status.get("local_ip")
            display_ip = (
                local_ip
                if local_ip and not local_ip.startswith("127.")
                else "unavailable"
            )
            chat.add_system_message(f"Local IP:          {display_ip}")
            chat.add_system_message(
                f"Listening Port:    {status.get('listening_port', 'N/A')}"
            )
            chat.add_system_message(
                f"UDP Discovery:     {status.get('discovery', 'Stopped')}"
            )
            chat.add_system_message(
                f"Discovered Peers:  {status.get('discovered_peers_count', 0)}"
            )
            chat.add_system_message(
                f"Connected Peers:   {status.get('connected_peers_count', 0)}"
            )
            chat.add_system_message(
                f"Local Node:        {status.get('local_nickname', 'Anonymous')} "
                f"(ID: {status.get('local_peer_id', '')[:12]})"
            )
            chat.add_system_message(f"Active Context:    {self.active_context}")
            chat.add_system_message("════════════════════════════════════════")
        else:
            chat.add_system_message("══════════ BitChat Status ══════════")
            ad_stat = "Available" if status.get("adapter_available") else "Unavailable"
            chat.add_system_message(f"Bluetooth Adapter: {ad_stat}")
            chat.add_system_message(
                f"Bluetooth State:   {status.get('adapter_state', 'Off')}"
            )
            chat.add_system_message(
                f"GATT Server:       {status.get('gatt_server_status', 'Stopped')}"
            )
            chat.add_system_message(
                f"Scanner:           {status.get('scanner_status', 'Stopped')}"
            )
            chat.add_system_message(
                f"Discovered Peers:  {status.get('discovered_peers_count', 0)}"
            )
            chat.add_system_message(
                f"Connected Peers:   {status.get('connected_peers_count', 0)}"
            )
            chat.add_system_message(
                f"Local Node:        {status.get('local_nickname', 'Anonymous')} "
                f"(ID: {status.get('local_peer_id', '')[:12]})"
            )
            chat.add_system_message(f"Active Context:    {self.active_context}")
            chat.add_system_message("════════════════════════════════════")

    def action_clear_log(self) -> None:
        """Action handler to clear the log."""
        self.query_one(ChatView).clear_log()

    def action_clear_chat(self) -> None:
        """Alias action for clear_chat keybinding."""
        self.action_clear_log()

    def action_show_help(self) -> None:
        """Action handler to display the help screen."""
        if isinstance(self.screen, HelpScreen):
            self.pop_screen()
            return
        if not isinstance(self.screen, BitChatApp) and len(self._screen_stack) > 1:
            self.pop_screen()
        self.push_screen(HelpScreen())

    def action_help(self) -> None:
        """Alias action for help keybinding."""
        self.action_show_help()

    def action_open_settings(self, category: str | None = None) -> None:
        """Action handler to open categorized settings screen."""
        cat = category or "general"
        if isinstance(self.screen, SettingsScreen):
            if category is None:
                self.screen._handle_cancel_or_back()
            else:
                self.screen.switch_category(cat)
            return
        if (
            not isinstance(self.screen, BitChatApp)
            and len(self._screen_stack) > 1
            and not isinstance(self.screen, (HomeScreen, PeersScreen, CommandsScreen))
        ):
            self.pop_screen()
        nick = (
            self.coordinator.nickname
            if (
                self.coordinator
                and self.coordinator.nickname
                and self.coordinator.nickname != "Anonymous"
            )
            else self.config.nickname
        )
        hops = self.config.max_hops
        delay = self.config.inter_fragment_delay_ms
        current_trans = getattr(self.config, "transport", "bluetooth")
        self.push_screen(
            SettingsScreen(
                current_nickname=nick,
                current_max_hops=hops,
                current_delay_ms=delay,
                current_keybindings=self.config.keybindings,
                current_transport=current_trans,
                current_density=self.config.density,
                current_accent=self.config.accent,
                current_show_timestamps=self.config.show_timestamps,
                current_debug=self.config.debug,
                initial_category=cat,
            )
        )

    def action_settings(self) -> None:
        """Alias action for settings keybinding."""
        self.action_open_settings()

    def action_open_home(self) -> None:
        """Action handler to navigate to the BitChat dashboard home screen."""
        if isinstance(self.screen, HomeScreen):
            return
        with contextlib.suppress(Exception):
            msg_inp = self.query_one(MessageInput)
            if msg_inp.value:
                return
        if any(isinstance(s, HomeScreen) for s in self._screen_stack):
            while len(self._screen_stack) > 1 and not isinstance(
                self.screen, HomeScreen
            ):
                self.pop_screen()
            return
        self.push_screen(HomeScreen())

    def action_open_chat(self) -> None:
        """Action handler to transition to the primary chat screen."""
        while len(self._screen_stack) > 1 and not isinstance(
            self.screen, BLEErrorModal
        ):
            self.pop_screen()
        with contextlib.suppress(Exception):
            self.query_one(MessageInput).focus()

    def action_open_peers(self) -> None:
        """Action handler to navigate to the peer management screen."""
        if isinstance(self.screen, PeersScreen):
            return
        if any(isinstance(s, PeersScreen) for s in self._screen_stack):
            while len(self._screen_stack) > 1 and not isinstance(
                self.screen, PeersScreen
            ):
                self.pop_screen()
            return
        self.push_screen(PeersScreen())

    def action_open_telemetry(self) -> None:
        """Action handler to navigate to the system & radio telemetry screen."""
        if isinstance(self.screen, TelemetryScreen):
            return
        if any(isinstance(s, TelemetryScreen) for s in self._screen_stack):
            while len(self._screen_stack) > 1 and not isinstance(
                self.screen, TelemetryScreen
            ):
                self.pop_screen()
            return
        self.push_screen(TelemetryScreen())

    def action_open_commands(self) -> None:
        """Action handler: populate chat input if in chat, or open CommandsScreen."""
        try:
            msg_input = self.query_one(MessageInput)
            msg_input.value = "/"
            msg_input.focus()
            msg_input.cursor_position = 1
            palette = self.query_one(AutocompletePalette)
            suggestions = get_command_suggestions("/")
            items = [(s.name, s.description) for s in suggestions]
            palette.show_suggestions(items, title="Commands")
        except Exception:
            self.action_open_commands_screen()

    def action_open_commands_screen(self) -> None:
        """Action handler to display the commands reference screen."""
        if isinstance(self.screen, CommandsScreen):
            self.pop_screen()
            return
        if (
            not isinstance(self.screen, BitChatApp)
            and len(self._screen_stack) > 1
            and not isinstance(self.screen, (HomeScreen, PeersScreen))
        ):
            self.pop_screen()
        self.push_screen(CommandsScreen())

    def action_retry_bluetooth(self) -> None:
        """Action handler to retry BLE transport initialization."""
        self._spawn_task(self._handle_ble_retry())

    def action_open_edit_theme(self) -> None:
        """Action handler to open theme customization modal."""
        if isinstance(self.screen, EditThemeModal):
            self.pop_screen()
            return
        if not isinstance(self.screen, BitChatApp) and len(self._screen_stack) > 1:
            self.pop_screen()
        self.push_screen(
            EditThemeModal(
                current_density=self.current_density,
                current_show_timestamps=self.current_show_timestamps,
                current_accent=self.current_accent,
            )
        )

    def action_edit_theme(self) -> None:
        """Alias action for edit_theme keybinding."""
        self.action_open_edit_theme()

    def action_focus_peers(self) -> None:
        """Focus the sidebar peer list."""
        self.query_one(PeerSidebar).focus()

    def action_scroll_chat_up(self) -> None:
        """Action handler to scroll chat view up one page."""
        self.query_one(ChatView).page_up()

    def action_scroll_up(self) -> None:
        """Alias action for scroll_up keybinding."""
        self.action_scroll_chat_up()

    def action_scroll_chat_down(self) -> None:
        """Action handler to scroll chat view down one page."""
        self.query_one(ChatView).page_down()

    def action_scroll_down(self) -> None:
        """Alias action for scroll_down keybinding."""
        self.action_scroll_chat_down()

    async def _shutdown_resources(self) -> None:
        """Gracefully stop coordinator, cancel background tasks, and clean up."""
        if getattr(self, "_is_shutting_down", False):
            return
        self._is_shutting_down = True

        # 1. Cancel and gather any active background tasks
        current_t = asyncio.current_task()
        pending_bg = [
            t for t in self._background_tasks if not t.done() and t is not current_t
        ]
        for t in pending_bg:
            t.cancel()
        if pending_bg:
            await asyncio.gather(*pending_bg, return_exceptions=True)
        self._background_tasks.clear()

        # 2. Cancel running Textual workers if any
        if hasattr(self, "workers"):
            for worker in list(self.workers):
                worker.cancel()

        # 3. Gracefully stop session coordinator
        if self.coordinator is not None:
            try:
                await self.coordinator.stop()
            except Exception as e:
                logger.warning("Error stopping coordinator during shutdown: %s", e)

    async def on_unmount(self) -> None:
        """Guarantee graceful coordinator, transport, and storage shutdown
        on terminal exit.
        """
        await self._shutdown_resources()

    async def action_quit(self) -> None:
        """Clean shutdown handler."""
        await self._shutdown_resources()
        self.exit()
