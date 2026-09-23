"""Textual TUI for BitChat."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Static,
)

from bitchat.commands.parser import CommandParser, CommandType

if TYPE_CHECKING:
    from bitchat.app.session_coordinator import SessionCoordinator


class BitChatApp(App[None]):
    """Terminal User Interface for BitChat."""

    TITLE = "BitChat"
    SUB_TITLE = "Bluetooth Low Energy Mesh Chat"

    CSS = """
    Screen {
        layout: vertical;
    }
    #main-container {
        height: 1fr;
        layout: horizontal;
    }
    #sidebar {
        width: 32;
        border-right: solid $primary;
        padding: 1;
        background: $panel;
    }
    #peer-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    #identity-box {
        margin-bottom: 1;
        padding: 1;
        border: round $primary;
        height: auto;
    }
    #chat-container {
        width: 1fr;
        height: 1fr;
        layout: vertical;
        padding: 0 1;
    }
    #chat-log {
        height: 1fr;
        border: solid $accent;
        background: $surface;
    }
    #chat-input {
        dock: bottom;
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_log", "Clear", show=True),
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

    def _spawn_task(self, coro: Any) -> asyncio.Task[Any]:
        """Spawn background task and keep reference until completed."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-container"):
            with Vertical(id="sidebar"):
                yield Static(id="identity-box")
                yield Label("Peers", id="peer-title")
                yield ListView(id="peer-list")
            with Vertical(id="chat-container"):
                yield RichLog(id="chat-log", wrap=True, highlight=True, markup=True)
                yield Input(
                    placeholder="Type a message or /command (/help for guide)...",
                    id="chat-input",
                )
        yield Footer()

    async def on_mount(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.write("[bold cyan]Welcome to BitChat![/bold cyan]")
        log.write(
            "Commands: [bold]/connect <addr>[/bold], [bold]/scan[/bold], "
            "[bold]/online[/bold], [bold]/name <nick>[/bold], "
            "[bold]/dm <peer> <msg>[/bold], [bold]/large <peer>[/bold], "
            "[bold]/clear[/bold], [bold]/help[/bold]"
        )

        self._update_identity_display()

        if self.coordinator is not None:
            self.coordinator.on_message_received = self._on_coordinator_message
            self.coordinator.on_peer_status_changed = self._on_coordinator_status
            self.coordinator.on_handshake_completed = self._on_coordinator_handshake
            self._spawn_task(self._start_coordinator())

    async def _start_coordinator(self) -> None:
        if self.coordinator is not None and not self.coordinator.is_running:
            await self.coordinator.start()
            self._update_identity_display()
            self._update_peer_list()

    def _update_identity_display(self) -> None:
        box = self.query_one("#identity-box", Static)
        if self.coordinator is not None:
            ident = self.coordinator.local_identity
            nick = self.coordinator.nickname
            short_id = ident.peer_id_hex[:8]
            short_fp = ident.fingerprint[:12] + "..."
            box.update(
                f"[bold]{nick}[/bold]\n"
                f"ID: [cyan]{short_id}[/cyan]\n"
                f"FP: [dim]{short_fp}[/dim]"
            )
        else:
            box.update("[dim]Offline (No coordinator)[/dim]")

    def _update_peer_list(self) -> None:
        peer_list = self.query_one("#peer-list", ListView)
        peer_list.clear()

        if self.coordinator is None:
            return

        connected = self.coordinator.ble_manager.connected_peers
        for addr in connected:
            pid = self.coordinator.address_to_peer_id.get(addr, "unknown")
            nick = self.coordinator.peer_nicknames.get(pid, pid[:8])
            peer_list.append(ListItem(Label(f"● {nick} ({addr})")))

        discovered = self.coordinator.ble_manager.discovered_peers
        for addr, peer in discovered.items():
            if addr not in connected:
                name = peer.name or "Peer"
                peer_list.append(ListItem(Label(f"○ {name} ({addr})")))

    def _on_coordinator_message(
        self, sender_id: str, text: str, is_encrypted: bool
    ) -> None:
        log = self.query_one("#chat-log", RichLog)
        nick = sender_id[:8]
        if self.coordinator and sender_id in self.coordinator.peer_nicknames:
            nick = self.coordinator.peer_nicknames[sender_id]

        if is_encrypted:
            log.write(f"[bold green]🔒 [DM] <{nick}>:[/bold green] {text}")
        else:
            log.write(f"[bold cyan][Public] <{nick}>:[/bold cyan] {text}")

    def _on_coordinator_status(self, peer: str, status: str) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.write(f"[dim yellow][Peer {peer}]: {status}[/dim yellow]")
        self._update_peer_list()

    def _on_coordinator_handshake(self, peer_id: str, fingerprint: str) -> None:
        log = self.query_one("#chat-log", RichLog)
        short_fp = fingerprint[:16] + "..." if len(fingerprint) > 16 else fingerprint
        log.write(
            f"[bold magenta]🔐 Secure Noise XX session established with "
            f"{peer_id[:8]} (FP: {short_fp})[/bold magenta]"
        )

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        event.input.value = ""
        if not value:
            return

        log = self.query_one("#chat-log", RichLog)

        if not value.startswith("/"):
            # Public broadcast message
            log.write(f"[bold white][You]:[/bold white] {value}")
            if self.coordinator:
                await self.coordinator.send_broadcast_message(value)
            return

        command = self.parser.parse(value)
        match command.command_type:
            case CommandType.HELP:
                log.write("[bold cyan]Available Commands:[/bold cyan]")
                log.write("  /connect <addr>        - Connect to a peer BLE address")
                log.write("  /disconnect [addr]     - Disconnect from peer or all")
                log.write("  /scan                  - Show discovered peers")
                log.write("  /online                - List active peers")
                log.write("  /name <nick>           - Change nickname and broadcast")
                log.write("  /dm <peer_id> <msg>    - Send encrypted Noise message")
                log.write(
                    "  /large <peer_id>       - Send 1000B fragmented test message"
                )
                log.write("  /clear                 - Clear chat log")
                log.write("  /exit                  - Quit BitChat")

            case CommandType.CONNECT:
                if command.error_message:
                    log.write(f"[red]{command.error_message}[/red]")
                elif self.coordinator:
                    target = command.args[0]
                    log.write(f"[yellow]Connecting to {target}...[/yellow]")
                    self._spawn_task(self.coordinator.ble_manager.connect_peer(target))

            case CommandType.DISCONNECT:
                if self.coordinator:
                    if command.args:
                        target = command.args[0]
                        log.write(f"[yellow]Disconnecting from {target}...[/yellow]")
                        self._spawn_task(
                            self.coordinator.ble_manager.disconnect_peer(target)
                        )
                    else:
                        log.write("[yellow]Disconnecting all peers...[/yellow]")
                        self._spawn_task(self.coordinator.ble_manager.shutdown())

            case CommandType.SCAN:
                if self.coordinator:
                    discovered = self.coordinator.ble_manager.discovered_peers
                    log.write(f"[cyan]Discovered {len(discovered)} peer(s):[/cyan]")
                    for addr, peer in discovered.items():
                        name = peer.name or "Unknown"
                        log.write(f"  • {addr} ({name}, {peer.rssi} dBm)")
                    self._update_peer_list()

            case CommandType.ONLINE:
                if self.coordinator:
                    connected = self.coordinator.ble_manager.connected_peers
                    log.write(f"[cyan]Connected peers ({len(connected)}):[/cyan]")
                    for addr in connected:
                        pid = self.coordinator.address_to_peer_id.get(addr, "unknown")
                        nick = self.coordinator.peer_nicknames.get(pid, pid[:8])
                        log.write(f"  • {addr} (Peer ID: {pid}, Nick: {nick})")
                    self._update_peer_list()

            case CommandType.NAME:
                if command.error_message:
                    log.write(f"[red]{command.error_message}[/red]")
                elif self.coordinator:
                    new_nick = command.args[0]
                    self.coordinator.set_nickname(new_nick)
                    log.write(
                        f"[green]Nickname set to '{new_nick}'. "
                        "Broadcasting announce...[/green]"
                    )
                    await self.coordinator.send_announce(new_nick)
                    self._update_identity_display()

            case CommandType.DM:
                if command.error_message:
                    log.write(f"[red]{command.error_message}[/red]")
                elif self.coordinator:
                    target_peer = command.args[0]
                    msg = command.args[1]
                    log.write(
                        f"[bold green]🔒 [You -> {target_peer[:8]}]:[/bold green] {msg}"
                    )
                    await self.coordinator.send_direct_message(target_peer, msg)

            case CommandType.LARGE:
                if command.error_message:
                    log.write(f"[red]{command.error_message}[/red]")
                elif self.coordinator:
                    target_peer = command.args[0]
                    payload = "FRAG-TEST-" + ("X" * 1000)
                    log.write(
                        f"[yellow]Sending 1000B fragmented message to "
                        f"{target_peer[:8]}...[/yellow]"
                    )
                    await self.coordinator.send_direct_message(target_peer, payload)

            case CommandType.CLEAR:
                self.action_clear_log()

            case CommandType.EXIT:
                self.exit()

            case _:
                log.write(
                    f"[red]Unknown command: '{value}'. Type /help for commands.[/red]"
                )

    def action_clear_log(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.clear()

    async def action_quit(self) -> None:
        if self.coordinator:
            await self.coordinator.stop()
        self.exit()
