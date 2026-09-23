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
from bitchat.tui.screens.help import HelpScreen
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
    CSS = TCSS_STYLES

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("ctrl+l", "clear_log", "Clear", show=False),
        Binding("f1", "show_help", "Help", show=False),
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

        # Connect coordinator event hooks if present
        if self.coordinator is not None:
            self.coordinator.on_message_received = self._on_coordinator_message
            self.coordinator.on_peer_status_changed = self._on_coordinator_peer_status
            self.coordinator.on_handshake_completed = self._on_coordinator_handshake

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
            "Welcome to BitChat. Type / for commands, /help for help."
        )

        if self.coordinator:
            self._spawn_task(self.coordinator.start())
            self._refresh_peer_lists()

    def _refresh_peer_lists(self) -> None:
        """Refresh sidebar and header with latest peer states."""
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

        if connected_addrs:
            status_bar.status_message = (
                f"● Connected | {len(connected_addrs)} peer(s) | BLE Mesh Ready"
            )
        else:
            status_bar.status_message = "○ Scanning for BitChat peers | Mesh Listening"

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

    def on_input_changed(self, event: Input.Changed) -> None:
        """Dynamically evaluate input and manage autocomplete suggestions."""
        val = event.value
        palette = self.query_one(AutocompletePalette)

        if not val.startswith("/"):
            palette.hide()
            return

        # Check if user is typing a command or arguments
        tokens = val.split(maxsplit=1)
        if len(tokens) == 1 and not val.endswith(" "):
            # Filtering command names (/c, /dm, etc.)
            suggestions = get_command_suggestions(tokens[0])
            items = [(s.name, s.description) for s in suggestions]
            palette.show_suggestions(items)
        elif len(tokens) >= 1 and val.startswith("/dm "):
            # Contextual peer argument completion
            query = tokens[1] if len(tokens) > 1 else ""
            peer_items: list[tuple[str, str]] = []
            if self.coordinator:
                for pid, nick in self.coordinator.peer_nicknames.items():
                    if (
                        not query
                        or query.lower() in nick.lower()
                        or query.lower() in pid.lower()
                    ):
                        peer_items.append((f"/dm {nick} ", f"Peer ID: {pid[:8]}..."))
            palette.show_suggestions(peer_items)
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
            palette.show_suggestions(addr_items)
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
                    # Check if selected is a command with arguments
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
                    f"[to {target_peer}]: {dm_text}",
                    is_encrypted=True,
                    is_self=True,
                )
                if self.coordinator:
                    # Resolve nickname to peer ID if nickname provided
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
                    # Plain broadcast message
                    chat.add_chat_message(
                        self.coordinator.nickname if self.coordinator else "You",
                        text,
                        is_encrypted=False,
                        is_self=True,
                    )
                    if self.coordinator:
                        self._spawn_task(self.coordinator.send_broadcast_message(text))

    def action_clear_log(self) -> None:
        """Action handler to clear the log."""
        self.query_one(ChatView).clear_log()

    def action_show_help(self) -> None:
        """Action handler to display the help screen."""
        self.push_screen(HelpScreen())

    async def action_quit(self) -> None:
        """Clean shutdown handler."""
        if self.coordinator:
            await self.coordinator.stop()
        self.exit()
