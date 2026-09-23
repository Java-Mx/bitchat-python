"""Peer sidebar widget displaying connected and discovered nodes."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from bitchat.ble.models import DiscoveredPeer


class PeerSidebar(Widget):
    """Sidebar displaying local identity card and real-time peer lists."""

    DEFAULT_CSS = """
    PeerSidebar {
        width: 32;
        min-width: 24;
        max-width: 38;
        background: #161b22;
        border-right: solid #30363d;
        padding: 0 1;
        layout: vertical;
    }
    """

    nickname: reactive[str] = reactive("Anonymous")
    peer_id_hex: reactive[str] = reactive("")
    fingerprint: reactive[str] = reactive("")

    def __init__(
        self,
        nickname: str = "Anonymous",
        peer_id_hex: str = "",
        fingerprint: str = "",
        **kwargs,
    ) -> None:
        super().__init__(id="sidebar", **kwargs)
        self.nickname = nickname
        self.peer_id_hex = peer_id_hex
        self.fingerprint = fingerprint
        self._connected_peers: dict[str, str] = {}  # addr -> label
        self._discovered_peers: dict[str, str] = {}  # addr -> label

    def compose(self) -> ComposeResult:
        with Vertical(id="identity-card"):
            yield Label("[bold #58a6ff]Identity[/bold #58a6ff]")
            yield Static(self._render_identity_card(), id="identity-box")

        yield Label(
            "[bold #3fb950]Connected Peers[/bold #3fb950]", classes="sidebar-title"
        )
        yield ListView(id="connected-peers-list", classes="peer-list-view")

        yield Label(
            "[bold #8b949e]Discovered (BLE)[/bold #8b949e]", classes="sidebar-title"
        )
        yield ListView(id="discovered-peers-list", classes="peer-list-view")

    def _render_identity_card(self) -> str:
        short_id = self.peer_id_hex[:12] if self.peer_id_hex else "N/A"
        short_fp = self.fingerprint[:16] + "..." if self.fingerprint else "N/A"
        return (
            f"[bold]{self.nickname}[/bold]\n"
            f"ID: [dim]{short_id}[/dim]\n"
            f"FP: [dim]{short_fp}[/dim]"
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
                    view.append(
                        ListItem(
                            Label(f"[#3fb950]●[/#3fb950] {label}"),
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
                view.append(ListItem(Label("[dim]Scanning...[/dim]")))
            else:
                for addr, label in self._discovered_peers.items():
                    view.append(
                        ListItem(
                            Label(f"[#8b949e]○[/#8b949e] {label}\n  [dim]{addr}[/dim]")
                        )
                    )
