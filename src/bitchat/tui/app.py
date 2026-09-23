"""Professional Textual terminal user interface for BitChat."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical

from bitchat.commands.parser import (
    COMMAND_REGISTRY,
    CommandParser,
    CommandType,
    get_command_suggestions,
)
from bitchat.tui.screens.ble_error import BLEErrorModal
from bitchat.tui.screens.edit_theme import EditThemeModal
from bitchat.tui.screens.help import HelpScreen
from bitchat.tui.screens.peer_info import PeerInfoModal
from bitchat.tui.screens.settings import SettingsModal
from bitchat.tui.theme import TCSS_STYLES
from bitchat.tui.widgets.autocomplete import AutocompletePalette
from bitchat.tui.widgets.chat_view import ChatView
from bitchat.tui.widgets.header import HeaderWidget
from bitchat.tui.widgets.message_input import MessageInput
from bitchat.tui.widgets.sidebar import PeerSidebar
from bitchat.tui.widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from textual.widgets import Input

    from bitchat.app.session_coordinator import SessionCoordinator


class BitChatApp(App[None]):
    """Modern terminal user interface for the BitChat mesh client."""

    TITLE = "BitChat"
    SUB_TITLE = "Bluetooth Low Energy Mesh Chat"
    CSS_PATH = "styles/app.tcss"
    CSS = TCSS_STYLES

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+l", "clear_log", "Clear", show=False, priority=True),
        Binding("f1", "show_help", "Help", show=False, priority=True),
        Binding("?", "show_help", "Help", show=False, priority=True),
        Binding("f2", "open_edit_theme", "Edit", show=False, priority=True),
        Binding("f3", "open_settings", "Settings", show=False, priority=True),
        Binding("pageup", "scroll_chat_up", "Scroll Up", show=False, priority=True),
        Binding(
            "pagedown", "scroll_chat_down", "Scroll Down", show=False, priority=True
        ),
    ]

    def __init__(
        self,
        coordinator: SessionCoordinator | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.coordinator = coordinator
        self.parser = CommandParser()
        self._background_tasks: set[asyncio.Task[Any]] = set()

        self.active_context: str = "#public"
        self.current_density: str = "comfortable"
        self.current_show_timestamps: bool = True
        self.current_accent: str = "blue"

        # Connect coordinator event hooks if present
        if self.coordinator is not None:
            self.coordinator.on_message_received = self._on_coordinator_message
            self.coordinator.on_peer_status_changed = self._on_coordinator_peer_status
            self.coordinator.on_handshake_completed = self._on_coordinator_handshake
            self.coordinator.on_ble_error = self._on_coordinator_ble_error

    def _spawn_task(self, coro: Any) -> asyncio.Task[Any]:
        """Spawn background task and keep reference until completed."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def compose(self) -> ComposeResult:
        nick = self.coordinator.nickname if self.coordinator else "Anonymous"
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
        msg_input = self.query_one(MessageInput)
        palette = self.query_one(AutocompletePalette)
        msg_input.autocomplete_palette = palette
        msg_input.focus()

        chat = self.query_one(ChatView)
        chat.add_system_message(
            "Welcome to BitChat. Type / for commands, @<peer> for direct messages, "
            "/help for help."
        )

        if self.coordinator:
            self._spawn_task(self.coordinator.start())
            self._refresh_peer_lists()

    def _refresh_peer_lists(self) -> None:
        """Refresh sidebar and header with latest peer states and truthful telemetry."""
        if not self.coordinator:
            return

        sidebar = self.query_one(PeerSidebar)
        header = self.query_one(HeaderWidget)
        status_bar = self.query_one(StatusBar)

        connected_addrs = self.coordinator.ble_manager.connected_peers
        header.peer_count = len(connected_addrs)

        conn_display: dict[str, str] = {}
        for addr in connected_addrs:
            pid = self.coordinator.address_to_peer_id.get(addr, "")
            nick = self.coordinator.peer_nicknames.get(pid, pid[:8] if pid else addr)
            session = self.coordinator.get_or_create_session(pid) if pid else None
            sec_tag = "🔒" if session and session.is_established else ""
            conn_display[addr] = f"{nick} {sec_tag} ({addr})"

        sidebar.set_connected_peers(conn_display)
        sidebar.set_discovered_peers(self.coordinator.ble_manager.discovered_peers)

        # Truthful Bluetooth state reporting
        if connected_addrs:
            status_bar.mesh_status = (
                f"● Connected ({len(connected_addrs)} peers) • Local Mesh"
            )
        elif self.coordinator.ble_status == "scanning":
            status_bar.mesh_status = "◌ Mesh Initializing"
        elif self.coordinator.ble_status in ("unavailable", "disabled", "error"):
            status_bar.mesh_status = "✕ BLE Offline"
        else:
            status_bar.mesh_status = "● BitChat Ready • Local Mesh"

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
                for addr in self.coordinator.ble_manager.connected_peers:
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

    def _on_coordinator_ble_error(self, err_msg: str) -> None:
        """Handle Bluetooth hardware or scan failure from coordinator."""

        def _do_error() -> None:
            chat = self.query_one(ChatView)
            chat.add_error_message(f"Bluetooth Error: {err_msg}")
            self._refresh_peer_lists()
            self.push_screen(BLEErrorModal(error_message=err_msg))

        self._dispatch_ui(_do_error)

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
            chat.add_system_message(f"Peer {peer}: {status}")
            self._refresh_peer_lists()

        self._dispatch_ui(_do_update)

    def _on_coordinator_handshake(self, peer_id: str, fingerprint: str) -> None:
        """Handle successful Noise XX handshake."""
        short_fp = fingerprint[:16] + "..." if len(fingerprint) > 16 else fingerprint

        def _do_notify() -> None:
            chat = self.query_one(ChatView)
            chat.add_security_event(
                f"Noise XX session established with {peer_id[:8]} (FP: {short_fp})"
            )
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

        session = (
            self.coordinator.get_or_create_session(resolved_pid)
            if resolved_pid
            else None
        )
        fp = (
            session.remote_fingerprint if session and session.remote_fingerprint else ""
        )
        is_enc = session.is_established if session else False
        is_conn = bool(
            address and address in self.coordinator.ble_manager.connected_peers
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
                self.action_focus_peers()
            case "commands":
                self.action_open_commands()
            case "help":
                self.action_show_help()
            case "quit":
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

    def on_settings_modal_settings_saved(
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
            self.query_one(PeerSidebar).update_identity(event.nickname)
            self.query_one(HeaderWidget).nickname = event.nickname
        chat = self.query_one(ChatView)
        chat.add_system_message(
            f"Settings updated: nickname='{event.nickname}', "
            f"max_hops={event.max_hops}, delay={event.inter_fragment_delay_ms}ms"
        )

    def on_edit_theme_modal_theme_applied(
        self, event: EditThemeModal.ThemeApplied
    ) -> None:
        """Handle applied appearance changes."""
        self.current_density = event.density
        self.current_show_timestamps = event.show_timestamps
        self.current_accent = event.accent_name
        chat = self.query_one(ChatView)
        chat.compact_mode = event.density == "compact"
        chat.show_timestamps = event.show_timestamps
        chat.add_system_message(
            f"Theme applied: density={event.density}, "
            f"timestamps={event.show_timestamps}, accent={event.accent_name}"
        )

    def on_ble_error_modal_retry_requested(
        self, event: BLEErrorModal.RetryRequested
    ) -> None:
        """Handle retry request from BLE error dialog."""
        self._spawn_task(self._handle_ble_retry())

    async def _handle_ble_retry(self) -> None:
        """Attempt to re-initialize BLE services and notify user."""
        chat = self.query_one(ChatView)
        chat.add_system_message("Retrying Bluetooth initialization...")
        if self.coordinator:
            success = await self.coordinator.retry_ble()
            if success:
                chat.add_system_message(
                    "Bluetooth reconnected successfully. BLE Mesh Active."
                )
                self._refresh_peer_lists()
            else:
                chat.add_error_message(
                    "Bluetooth retry failed. Remaining in offline mode."
                )
                self._refresh_peer_lists()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Dynamically evaluate input and manage autocomplete suggestions."""
        val = event.value
        palette = self.query_one(AutocompletePalette)

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
                for addr, peer in self.coordinator.ble_manager.discovered_peers.items():
                    name = peer.name or addr
                    if (
                        not query
                        or name.lower().startswith(query)
                        or query in name.lower()
                    ):
                        peer_items.append((f"@{name} ", f"{addr} ({peer.rssi} dBm)"))
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
                for addr, peer in self.coordinator.ble_manager.discovered_peers.items():
                    name = peer.name or "Unknown"
                    if (
                        not query
                        or query.lower() in addr.lower()
                        or query.lower() in name.lower()
                    ):
                        addr_items.append(
                            (f"/connect {addr}", f"{name} ({peer.rssi} dBm)")
                        )
            palette.show_suggestions(addr_items, title="Discovered BLE Peers")
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Process submitted chat line or slash command."""
        text = event.value.strip()
        msg_input = self.query_one(MessageInput)
        palette = self.query_one(AutocompletePalette)
        palette.hide()

        if not text:
            return

        msg_input.record_history(text)
        msg_input.value = ""

        chat = self.query_one(ChatView)
        cmd = self.parser.parse(text)

        match cmd.command_type:
            case CommandType.HELP:
                self.push_screen(HelpScreen())

            case CommandType.SETTINGS:
                self.action_open_settings()

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

            case CommandType.STATUS:
                self._display_status_diagnostics(chat)

            case CommandType.CLEAR:
                chat.clear_log()

            case CommandType.EXIT:
                self.exit()

            case CommandType.CONNECT:
                if cmd.error_message:
                    chat.add_error_message(cmd.error_message)
                    return
                target = cmd.args[0]
                chat.add_system_message(f"Connecting to peer at {target}...")
                if self.coordinator:
                    self._spawn_task(self.coordinator.ble_manager.connect_peer(target))

            case CommandType.DISCONNECT:
                if not self.coordinator:
                    return
                if cmd.args:
                    target = cmd.args[0]
                    chat.add_system_message(f"Disconnecting from {target}...")
                    self._spawn_task(
                        self.coordinator.ble_manager.disconnect_peer(target)
                    )
                else:
                    chat.add_system_message("Disconnecting all peers...")
                    self._spawn_task(self.coordinator.ble_manager.shutdown())

            case CommandType.SCAN:
                chat.add_system_message("Starting BLE discovery scan...")
                if self.coordinator:
                    self._spawn_task(self.coordinator.ble_manager.start_discovery())

            case CommandType.ONLINE:
                if not self.coordinator:
                    return
                connected = self.coordinator.ble_manager.connected_peers
                chat.add_system_message(f"Connected peers ({len(connected)}):")
                for addr in connected:
                    pid = self.coordinator.address_to_peer_id.get(addr, "unknown")
                    nick = self.coordinator.peer_nicknames.get(pid, "unknown")
                    chat.add_system_message(
                        f"  • {addr} (Peer: {pid[:8]}, Nick: {nick})"
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
                chat.add_system_message(f"Nickname changed to '{new_name}'")

            case CommandType.DM:
                if cmd.error_message:
                    chat.add_error_message(cmd.error_message)
                    return
                target_peer = cmd.args[0]
                dm_text = cmd.args[1]
                chat.add_chat_message(
                    self.coordinator.nickname if self.coordinator else "You",
                    f"(to {target_peer}): {dm_text}",
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
                        self.coordinator.send_direct_message(resolved_pid, dm_text)
                    )

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

            case CommandType.UNKNOWN:
                if text.startswith("/"):
                    chat.add_error_message(cmd.error_message or "Unknown command")
                else:
                    # Check active conversation context
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
                            self._spawn_task(
                                self.coordinator.send_broadcast_message(text)
                            )

    def _display_status_diagnostics(self, chat: ChatView) -> None:
        """Display operational diagnostics in chat."""
        if not self.coordinator:
            chat.add_system_message(
                "BitChat Diagnostics: Coordinator not attached (offline)."
            )
            return

        ble_stat = self.coordinator.ble_status.upper()
        conn_count = len(self.coordinator.ble_manager.connected_peers)
        disc_count = len(self.coordinator.ble_manager.discovered_peers)
        nick = self.coordinator.nickname
        pid = self.coordinator.local_identity.peer_id_hex[:16]
        fp = self.coordinator.local_identity.fingerprint[:16]

        chat.add_system_message("══════════ BitChat Operational Status ══════════")
        chat.add_system_message(f"Local Node:   {nick} [ID: {pid}... FP: {fp}...]")
        chat.add_system_message(
            f"BLE Adapter:  {ble_stat}  │  Active Context: {self.active_context}"
        )
        chat.add_system_message(
            f"Connections:  {conn_count} connected  │  {disc_count} discovered nearby"
        )
        max_hops = getattr(self.coordinator.mesh_router, "max_relay_ttl", 3)
        chat.add_system_message(f"Mesh Relay:   Active (Max {max_hops} hops)")
        chat.add_system_message("════════════════════════════════════════════════")

    def action_clear_log(self) -> None:
        """Action handler to clear the log."""
        self.query_one(ChatView).clear_log()

    def action_show_help(self) -> None:
        """Action handler to display the help screen."""
        self.push_screen(HelpScreen())

    def action_open_settings(self) -> None:
        """Action handler to open settings modal."""
        nick = self.coordinator.nickname if self.coordinator else "Anonymous"
        hops = (
            getattr(self.coordinator.mesh_router, "max_relay_ttl", 3)
            if self.coordinator
            else 3
        )
        delay = int(
            (self.coordinator.inter_fragment_delay if self.coordinator else 0.02) * 1000
        )
        self.push_screen(
            SettingsModal(
                current_nickname=nick,
                current_max_hops=hops,
                current_delay_ms=delay,
            )
        )

    def action_open_edit_theme(self) -> None:
        """Action handler to open theme customization modal."""
        self.push_screen(
            EditThemeModal(
                current_density=self.current_density,
                current_show_timestamps=self.current_show_timestamps,
                current_accent=self.current_accent,
            )
        )

    def action_focus_peers(self) -> None:
        """Focus the sidebar peer list."""
        self.query_one(PeerSidebar).focus()

    def action_open_commands(self) -> None:
        """Open command autocomplete palette by populating prompt."""
        msg_input = self.query_one(MessageInput)
        msg_input.value = "/"
        msg_input.focus()
        msg_input.cursor_position = 1

    def action_scroll_chat_up(self) -> None:
        """Action handler to scroll chat view up one page."""
        self.query_one(ChatView).page_up()

    def action_scroll_chat_down(self) -> None:
        """Action handler to scroll chat view down one page."""
        self.query_one(ChatView).page_down()

    async def action_quit(self) -> None:
        """Clean shutdown handler."""
        if self.coordinator:
            await self.coordinator.stop()
        self.exit()
