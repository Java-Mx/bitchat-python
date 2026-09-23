"""Peer sidebar widget displaying connected and discovered nodes."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static

from bitchat.tui.theme import get_peer_color

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult

    from bitchat.ble.models import DiscoveredPeer


class PeerListItem(ListItem):
    """Custom list item carrying peer address and name metadata."""

    def __init__(
        self,
        *children: Widget,
        peer_address: str = "",
        peer_name: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(*children, **kwargs)
        self.peer_address = peer_address
        self.peer_name = peer_name


class PeerSidebar(Widget):
    """Sidebar displaying local identity card and real-time peer lists."""

    nickname: reactive[str] = reactive("Anonymous")
    peer_id_hex: reactive[str] = reactive("")
    fingerprint: reactive[str] = reactive("")

    class PeerSelected(Message):
        """Emitted when user selects a peer to switch conversation context."""

        def __init__(self, peer_identifier: str, address: str = "") -> None:
            super().__init__()
            self.peer_identifier = peer_identifier
            self.address = address

    class PeerInfoRequested(Message):
        """Emitted when peer detailed security inspection is requested."""

        def __init__(self, peer_identifier: str, address: str = "") -> None:
            super().__init__()
            self.peer_identifier = peer_identifier
            self.address = address

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
        self._addr_to_name: dict[str, str] = {}

    def on_mount(self) -> None:
        self.border_title = "Peers (BLE Mesh)"

    def compose(self) -> ComposeResult:
        with Vertical(id="identity-card"):
            yield Label(
                "[bold #58a6ff]Local Node [#public][/bold #58a6ff]", id="identity-title"
            )
            yield Static(self._render_identity_card(), id="identity-box")

        yield Label(
            "Connected (Enter: Chat │ i: Info)", classes="sidebar-section-title"
        )
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
        self._addr_to_name.clear()
        with contextlib.suppress(Exception):
            view = self.query_one("#connected-peers-list", ListView)
            view.clear()
            if not self._connected_peers:
                view.append(ListItem(Label("[dim]No peers connected[/dim]")))
            else:
                for addr, label in self._connected_peers.items():
                    name = label.split(" (")[0].strip()
                    clean_name = name.replace("🔒", "").strip()
                    self._addr_to_name[addr] = clean_name
                    color = get_peer_color(clean_name)
                    item = PeerListItem(
                        Label(
                            f"[bold {color}]● {name}[/bold {color}]\n"
                            f"  [dim #8b949e]Secure • Connected[/dim #8b949e]"
                        ),
                        peer_address=addr,
                        peer_name=clean_name,
                    )
                    view.append(item)

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
                    item = PeerListItem(
                        Label(
                            f"[{color}]○ {name}[/{color}]\n"
                            f"  [dim #8b949e]{rssi_str} • {addr}[/dim #8b949e]"
                        ),
                        peer_address=addr,
                        peer_name=name,
                    )
                    view.append(item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle selection in connected peer list."""
        item = event.item
        addr = getattr(item, "peer_address", "")
        name = getattr(item, "peer_name", "")
        if event.list_view.id == "connected-peers-list":
            if addr and name:
                self.post_message(self.PeerSelected(name, addr))
        elif event.list_view.id == "discovered-peers-list" and addr:
            self.post_message(self.PeerInfoRequested(name or addr, addr))

    def on_key(self, event: events.Key) -> None:
        """Handle keypresses in the sidebar, such as 'i' for info."""
        if event.key == "i":
            with contextlib.suppress(Exception):
                for lv_id in ("#connected-peers-list", "#discovered-peers-list"):
                    view = self.query_one(lv_id, ListView)
                    if view.has_focus and view.highlighted_child:
                        item = view.highlighted_child
                        addr = getattr(item, "peer_address", "")
                        name = getattr(item, "peer_name", "")
                        if addr:
                            self.post_message(
                                self.PeerInfoRequested(name or addr, addr)
                            )
                            event.prevent_default()
                            event.stop()
                            break

    def on_click(self, event: events.Click) -> None:
        """Handle clicks on identity card to switch back to public channel."""
        with contextlib.suppress(Exception):
            card = self.query_one("#identity-card")
            if card.region.contains(event.screen_x, event.screen_y):
                self.post_message(self.PeerSelected("#public", ""))
