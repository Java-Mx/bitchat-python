"""Peer sidebar widget displaying connected and discovered nodes."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static

from bitchat.tui.theme import get_peer_color

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from bitchat.ble.models import DiscoveredPeer


class PeerSidebar(Widget):
    """Sidebar displaying local identity card and real-time peer lists."""

    nickname: reactive[str] = reactive("Anonymous")
    peer_id_hex: reactive[str] = reactive("")
    fingerprint: reactive[str] = reactive("")

    def __init__(
        self,
        nickname: str = "Anonymous",
        peer_id_hex: str = "",
        fingerprint: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(id="sidebar", **kwargs)
        self.nickname = nickname
        self.peer_id_hex = peer_id_hex
        self.fingerprint = fingerprint
        self._connected_peers: dict[str, str] = {}  # addr -> label
        self._discovered_peers: dict[str, str] = {}  # addr -> label

    def on_mount(self) -> None:
        self.border_title = "Peers [BLE Mesh]"

    def compose(self) -> ComposeResult:
        with Vertical(id="identity-card"):
            yield Label("[bold #58a6ff]Local Node[/bold #58a6ff]", id="identity-title")
            yield Static(self._render_identity_card(), id="identity-box")

        yield Label("Connected", classes="sidebar-section-title")
        yield ListView(id="connected-peers-list", classes="peer-list-view")

        yield Label("Discovered (Nearby)", classes="sidebar-section-title")
        yield ListView(id="discovered-peers-list", classes="peer-list-view")

    def _render_identity_card(self) -> str:
        short_id = self.peer_id_hex[:12] if self.peer_id_hex else "N/A"
        short_fp = self.fingerprint[:16] + "..." if self.fingerprint else "N/A"
        self_color = get_peer_color(self.nickname)
        return (
            f"[bold {self_color}]{self.nickname}[/bold {self_color}]\n"
            f"[dim]ID:[/dim]  [dim #8b949e]{short_id}[/dim #8b949e]\n"
            f"[dim]FP:[/dim]  [dim #8b949e]{short_fp}[/dim #8b949e]"
        )

    def update_identity(
        self, nickname: str, peer_id_hex: str = "", fingerprint: str = ""
    ) -> None:
        """Update identity card values."""
        self.nickname = nickname
        if peer_id_hex:
            self.peer_id_hex = peer_id_hex
        if fingerprint:
            self.fingerprint = fingerprint
        with contextlib.suppress(Exception):
            box = self.query_one("#identity-box", Static)
            box.update(self._render_identity_card())

    def set_connected_peers(self, peers: dict[str, str]) -> None:
        """Update connected peers list (mapping address -> display string)."""
        self._connected_peers = dict(peers)
        with contextlib.suppress(Exception):
            view = self.query_one("#connected-peers-list", ListView)
            view.clear()
            if not self._connected_peers:
                view.append(ListItem(Label("[dim]No peers connected[/dim]")))
            else:
                for addr, label in self._connected_peers.items():
                    item_id = f"peer-{addr.replace(':', '_')}"
                    name = label.split(" (")[0]
                    color = get_peer_color(name)
                    view.append(
                        ListItem(
                            Label(
                                f"[bold {color}]● {name}[/bold {color}]\n"
                                f"  [dim #8b949e]Secure • Connected[/dim #8b949e]"
                            ),
                            id=item_id,
                        )
                    )

    def set_discovered_peers(self, peers: dict[str, DiscoveredPeer]) -> None:
        """Update discovered peers list."""
        self._discovered_peers = {
            addr: f"{p.name or 'Unknown'} ({p.rssi} dBm)" for addr, p in peers.items()
        }
        with contextlib.suppress(Exception):
            view = self.query_one("#discovered-peers-list", ListView)
            view.clear()
            if not self._discovered_peers:
                view.append(ListItem(Label("[dim]Scanning for nodes...[/dim]")))
            else:
                for addr, p in peers.items():
                    name = p.name or "BitChat Node"
                    color = get_peer_color(name)
                    rssi_str = f"{p.rssi} dBm" if p.rssi is not None else "Nearby"
                    view.append(
                        ListItem(
                            Label(
                                f"[{color}]○ {name}[/{color}]\n"
                                f"  [dim #8b949e]{rssi_str} • {addr}[/dim #8b949e]"
                            )
                        )
                    )
