"""Application controller managing lifecycle, command dispatch, and BLE coordination."""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, Any, TextIO

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.commands.parser import Command, CommandParser, CommandType
from bitchat.crypto.identity import LocalIdentity
from bitchat.exceptions import ApplicationError, ConfigurationError
from bitchat.storage.config import AppConfig, FileConfigStorage, StorageInterface

if TYPE_CHECKING:
    from bitchat.ble.manager import BLEManager
    from bitchat.ble.server import BLEServer


class Application:
    """Core application controller managing lifecycle and command dispatch."""

    def __init__(
        self,
        storage: StorageInterface | None = None,
        command_parser: CommandParser | None = None,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        coordinator: SessionCoordinator | None = None,
        local_identity: LocalIdentity | None = None,
        ble_manager: BLEManager | None = None,
        ble_server: BLEServer | None = None,
        enable_ble: bool = False,
    ) -> None:
        self.storage: StorageInterface = storage or FileConfigStorage()
        self.command_parser: CommandParser = command_parser or CommandParser()
        self.stdin: TextIO = stdin or sys.stdin
        self.stdout: TextIO = stdout or sys.stdout
        self.is_running: bool = False
        self.is_chat_initialized: bool = False
        self.config: AppConfig | None = None
        self.enable_ble: bool = enable_ble or (coordinator is not None)

        self.local_identity: LocalIdentity | None = local_identity
        self.ble_manager: BLEManager | None = ble_manager
        self.ble_server: BLEServer | None = ble_server
        self.coordinator: SessionCoordinator | None = coordinator

    def _run_async(self, coro: Any) -> Any:
        """Execute coroutine in existing or fresh event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        else:
            return loop.create_task(coro)

    def startup(self) -> None:
        """Initialize configuration and start the application lifecycle."""
        if self.is_running:
            raise ApplicationError("Application is already running.")
        try:
            self.config = self.storage.load_config()
        except ConfigurationError as e:
            self.stdout.write(f"Warning: Failed to load configuration: {e}\n")
            self.config = AppConfig()

        self.is_running = True
        self.stdout.write("BitChat\n")
        self.stdout.write(
            "No chat session initialized. Available commands: "
            "initialize chat, help, exit\n"
        )
        self.stdout.flush()

    def shutdown(self) -> None:
        """Perform clean application shutdown."""
        if not self.is_running:
            return
        self.is_running = False

        if self.coordinator is not None and self.coordinator.is_running:
            self._run_async(self.coordinator.stop())

        self.storage.close()
        self.stdout.write("Goodbye!\n")
        self.stdout.flush()

    def dispatch(self, command: Command) -> bool:
        """Dispatch a parsed command.

        Returns True if the application should continue running, or False to exit.
        """
        match command.command_type:
            case CommandType.INITIALIZE_CHAT:
                return self._handle_initialize_chat(command)
            case CommandType.HELP:
                return self._handle_help(command)
            case CommandType.EXIT:
                return self._handle_exit(command)
            case CommandType.CONNECT:
                return self._handle_connect(command)
            case CommandType.DISCONNECT:
                return self._handle_disconnect(command)
            case CommandType.SCAN:
                return self._handle_scan(command)
            case CommandType.ONLINE:
                return self._handle_online(command)
            case CommandType.NAME:
                return self._handle_name(command)
            case CommandType.DM:
                return self._handle_dm(command)
            case CommandType.LARGE:
                return self._handle_large(command)
            case CommandType.CLEAR:
                return self._handle_clear(command)
            case CommandType.SETTINGS:
                return self._handle_settings(command)
            case CommandType.EDIT:
                return self._handle_edit(command)
            case CommandType.STATUS:
                return self._handle_status(command)
            case CommandType.INFO:
                return self._handle_info(command)
            case CommandType.PUBLIC:
                return self._handle_public(command)
            case CommandType.UNKNOWN:
                return self._handle_unknown(command)
            case _:
                return True

    def _ensure_coordinator(self) -> SessionCoordinator:
        """Lazily initialize identity, BLE components, and SessionCoordinator."""
        if self.coordinator is not None:
            return self.coordinator

        if self.local_identity is None:
            loaded_identity = self.storage.load_identity()
            if loaded_identity is not None:
                self.local_identity = loaded_identity
            else:
                self.local_identity = LocalIdentity.generate()
                self.storage.save_identity(self.local_identity)

        if self.ble_server is None:
            from bitchat.ble.server import BLEServer

            self.ble_server = BLEServer()

        if self.ble_manager is None:
            from bitchat.ble.manager import BLEManager

            self.ble_manager = BLEManager(sender_id=self.local_identity.peer_id)

        nick = self.config.nickname if self.config else "Anonymous"

        self.coordinator = SessionCoordinator(
            local_identity=self.local_identity,
            ble_manager=self.ble_manager,
            ble_server=self.ble_server,
            storage=self.storage,
            nickname=nick,
            on_message_received=self._on_message_received,
            on_peer_status_changed=self._on_peer_status_changed,
            on_handshake_completed=self._on_handshake_completed,
        )
        return self.coordinator

    def _on_message_received(
        self, sender_id: str, text: str, is_encrypted: bool
    ) -> None:
        nick = sender_id[:8]
        if self.coordinator and sender_id in self.coordinator.peer_nicknames:
            nick = self.coordinator.peer_nicknames[sender_id]
        tag = "[🔒 DM]" if is_encrypted else "[Public]"
        self.stdout.write(f"\n{tag} <{nick}>: {text}\n> ")
        self.stdout.flush()

    def _on_peer_status_changed(self, peer: str, status: str) -> None:
        self.stdout.write(f"\n[Peer {peer}]: {status}\n> ")
        self.stdout.flush()

    def _on_handshake_completed(self, peer_id: str, fingerprint: str) -> None:
        short_fp = fingerprint[:16] + "..." if len(fingerprint) > 16 else fingerprint
        self.stdout.write(
            f"\n[Security] Noise XX session established with {peer_id} "
            f"(Fingerprint: {short_fp})\n> "
        )
        self.stdout.flush()

    def _handle_initialize_chat(self, command: Command) -> bool:
        self.is_chat_initialized = True
        if self.enable_ble:
            coord = self._ensure_coordinator()
            self._run_async(coord.start())

        self.stdout.write("Chat initialized.\n")
        if self.enable_ble and self.local_identity:
            self.stdout.write(
                f"Local Peer ID: {self.local_identity.peer_id_hex} "
                f"(Fingerprint: {self.local_identity.fingerprint[:16]}...)\n"
            )
        self.stdout.flush()
        return True

    def _handle_connect(self, command: Command) -> bool:
        if not self.is_chat_initialized:
            self._handle_initialize_chat(command)

        if command.error_message:
            self.stdout.write(f"{command.error_message}\n")
            self.stdout.flush()
            return True

        target_address = command.args[0]
        self.stdout.write(f"Connecting to peer at {target_address}...\n")
        self.stdout.flush()

        coord = self._ensure_coordinator()
        self._run_async(coord.ble_manager.connect_peer(target_address))
        return True

    def _handle_disconnect(self, command: Command) -> bool:
        if not self.coordinator:
            self.stdout.write("Chat session not initialized.\n")
            self.stdout.flush()
            return True

        if command.args:
            target = command.args[0]
            self.stdout.write(f"Disconnecting from {target}...\n")
            self._run_async(self.coordinator.ble_manager.disconnect_peer(target))
        else:
            self.stdout.write("Disconnecting all peers...\n")
            self._run_async(self.coordinator.ble_manager.shutdown())
        self.stdout.flush()
        return True

    def _handle_scan(self, command: Command) -> bool:
        if not self.is_chat_initialized:
            self._handle_initialize_chat(command)

        coord = self._ensure_coordinator()
        discovered = coord.ble_manager.discovered_peers
        self.stdout.write(f"Discovered {len(discovered)} BitChat peer(s):\n")
        for addr, peer in discovered.items():
            name = peer.name or "Unknown"
            self.stdout.write(f"  - {addr} ({name}, {peer.rssi} dBm)\n")
        self.stdout.flush()
        return True

    def _handle_online(self, command: Command) -> bool:
        if not self.coordinator:
            self.stdout.write("Chat session not initialized.\n")
            self.stdout.flush()
            return True

        connected = self.coordinator.ble_manager.connected_peers
        self.stdout.write(f"Connected peers ({len(connected)}):\n")
        for addr in connected:
            peer_id = self.coordinator.address_to_peer_id.get(addr, "unknown")
            nick = self.coordinator.peer_nicknames.get(peer_id, "unknown")
            self.stdout.write(f"  - {addr} (Peer ID: {peer_id}, Nick: {nick})\n")

        known = self.coordinator.peer_nicknames
        if known:
            self.stdout.write("Known BitChat peers:\n")
            for pid, nick in known.items():
                self.stdout.write(f"  - {pid}: {nick}\n")
        self.stdout.flush()
        return True

    def _handle_name(self, command: Command) -> bool:
        if command.error_message:
            self.stdout.write(f"{command.error_message}\n")
            self.stdout.flush()
            return True

        new_name = command.args[0]
        if self.config:
            self.config.nickname = new_name
            try:
                self.storage.save_config(self.config)
            except Exception as e:
                self.stdout.write(f"Warning: Failed to save config: {e}\n")

        if self.coordinator:
            self.coordinator.set_nickname(new_name)
            self._run_async(self.coordinator.send_announce(new_name))

        self.stdout.write(f"Nickname set to: {new_name}\n")
        self.stdout.flush()
        return True

    def _handle_dm(self, command: Command) -> bool:
        if not self.is_chat_initialized:
            self._handle_initialize_chat(command)

        if command.error_message:
            self.stdout.write(f"{command.error_message}\n")
            self.stdout.flush()
            return True

        target_peer = command.args[0]
        message = command.args[1]
        coord = self._ensure_coordinator()

        self.stdout.write(f"[You -> {target_peer}]: {message}\n")
        self.stdout.flush()
        self._run_async(coord.send_direct_message(target_peer, message))
        return True

    def _handle_large(self, command: Command) -> bool:
        if not self.is_chat_initialized:
            self._handle_initialize_chat(command)

        if command.error_message:
            self.stdout.write(f"{command.error_message}\n")
            self.stdout.flush()
            return True

        target_peer = command.args[0]
        coord = self._ensure_coordinator()

        large_payload = "FRAG-TEST-" + ("X" * 1000)
        self.stdout.write(
            f"Sending 1000-byte test message to {target_peer} "
            f"(verifying fragmentation & reassembly)...\n"
        )
        self.stdout.flush()
        self._run_async(coord.send_direct_message(target_peer, large_payload))
        return True

    def _handle_clear(self, command: Command) -> bool:
        self.stdout.write("\033[H\033[2J")
        self.stdout.flush()
        return True

    def _handle_help(self, command: Command) -> bool:
        self.stdout.write("Available commands:\n")
        self.stdout.write("  initialize chat           - Initialize a chat session\n")
        self.stdout.write(
            "  /connect <address>        - Connect to a peer BLE address\n"
        )
        self.stdout.write("  /disconnect [address]     - Disconnect from peer or all\n")
        self.stdout.write("  /scan                     - Show discovered BLE peers\n")
        self.stdout.write(
            "  /online                   - List connected and known peers\n"
        )
        self.stdout.write(
            "  /name <nickname>          - Set local nickname and announce\n"
        )
        self.stdout.write(
            "  /dm <peer_id> <message>   - Send encrypted direct message\n"
        )
        self.stdout.write(
            "  /large <peer_id>          - Send 1000B fragmented test message\n"
        )
        self.stdout.write("  /clear                    - Clear terminal screen\n")
        self.stdout.write("  help                      - Show this help message\n")
        self.stdout.write("  exit                      - Exit the application\n")
        self.stdout.flush()
        return True

    def _handle_exit(self, command: Command) -> bool:
        return False

    def _handle_unknown(self, command: Command) -> bool:
        if self.is_chat_initialized and not command.raw_input.strip().startswith("/"):
            text = command.raw_input.strip()
            coord = self._ensure_coordinator()
            self.stdout.write(f"[You]: {text}\n")
            self.stdout.flush()
            self._run_async(coord.send_broadcast_message(text))
            return True

        msg = command.error_message or f"Unknown command: '{command.raw_input}'"
        self.stdout.write(f"{msg}\n")
        self.stdout.flush()
        return True

    def _handle_settings(self, command: Command) -> bool:
        nick = self.config.nickname if self.config else "Anonymous"
        self.stdout.write(f"BitChat Configuration:\n  Nickname: {nick}\n")
        self.stdout.flush()
        return True

    def _handle_edit(self, command: Command) -> bool:
        self.stdout.write("Appearance editor is only available in TUI mode.\n")
        self.stdout.flush()
        return True

    def _handle_status(self, command: Command) -> bool:
        if not self.coordinator:
            self.stdout.write("BitChat Status: Offline (Session not initialized)\n")
        else:
            status = self.coordinator.ble_status
            self.stdout.write(f"BitChat Status: {status}\n")
        self.stdout.flush()
        return True

    def _handle_info(self, command: Command) -> bool:
        if self.local_identity:
            self.stdout.write(
                f"Local Identity:\n"
                f"  Peer ID: {self.local_identity.peer_id_hex}\n"
                f"  Fingerprint: {self.local_identity.fingerprint}\n"
            )
        else:
            self.stdout.write("Identity not initialized.\n")
        self.stdout.flush()
        return True

    def _handle_public(self, command: Command) -> bool:
        self.stdout.write("Current context: #public\n")
        self.stdout.flush()
        return True

    def run(self) -> int:
        """Run the complete application lifecycle.

        startup -> command loop -> command dispatch -> shutdown.
        Returns exit code 0 on normal exit.
        """
        self.startup()
        try:
            while self.is_running:
                self.stdout.write("> ")
                self.stdout.flush()
                try:
                    line = self.stdin.readline()
                except (KeyboardInterrupt, EOFError):
                    break
                if not line:  # EOF encountered
                    break
                command = self.command_parser.parse(line)
                should_continue = self.dispatch(command)
                if not should_continue:
                    break
        finally:
            self.shutdown()
        return 0
