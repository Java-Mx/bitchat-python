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

    can_focus = True

    nickname: reactive[str] = reactive("Anonymous")
    peer_id_hex: reactive[str] = reactive("")
    fingerprint: reactive[str] = reactive("")
    active_transport: reactive[str] = reactive("bluetooth")

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

    def watch_active_transport(self, new_val: str) -> None:
        self.border_title = (
            "Peers (LAN / Wi-Fi)" if new_val == "lan" else "Peers (BLE Mesh)"
        )

    def on_mount(self) -> None:
        self.border_title = (
            "Peers (LAN / Wi-Fi)"
            if self.active_transport == "lan"
            else "Peers (BLE Mesh)"
        )

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

    def set_discovered_peers(
        self,
        peers: dict[str, Any],
        is_scanning: bool = True,
        is_offline: bool = False,
        transport: str = "bluetooth",
    ) -> None:
        """Update discovered peers list."""
        self._discovered_peers = {}
        for addr, p in peers.items():
            if getattr(p, "transport", "bluetooth") == "lan":
                nick = (
                    getattr(p, "nickname", None)
                    or getattr(p, "name", None)
                    or "Unknown"
                )
                self._discovered_peers[addr] = f"{nick} ({getattr(p, 'ip', addr)})"
            else:
                p_name = getattr(p, "name", None) or "Unknown"
                rssi_str = getattr(p, "rssi", "")
                self._discovered_peers[addr] = f"{p_name} ({rssi_str} dBm)"

        with contextlib.suppress(Exception):
            view = self.query_one("#discovered-peers-list", ListView)
            view.clear()
            if is_offline:
                unavail = (
                    "LAN / Wi-Fi Unavailable"
                    if transport == "lan"
                    else "Bluetooth Unavailable"
                )
                view.append(ListItem(Label(f"[dim red]{unavail}[/dim red]")))
            elif not self._discovered_peers:
                if is_scanning:
                    scanning_msg = (
                        "Searching local network for peers..."
                        if transport == "lan"
                        else "Scanning for BitChat peers..."
                    )
                    view.append(ListItem(Label(f"[dim]{scanning_msg}[/dim]")))
                else:
                    no_peers_msg = (
                        "No BitChat peers on local network"
                        if transport == "lan"
                        else "No BitChat peers discovered"
                    )
                    view.append(ListItem(Label(f"[dim]{no_peers_msg}[/dim]")))
            else:
                for addr, p in peers.items():
                    is_lan = (
                        getattr(p, "transport", "bluetooth") == "lan"
                        or transport == "lan"
                    )
                    p_id = getattr(p, "peer_id", None)
                    p_name = getattr(p, "nickname", None) or getattr(p, "name", None)
                    name = p_name or (f"Peer {p_id[:8]}" if p_id else "BitChat Node")
                    color = get_peer_color(name)
                    id_line = (
                        f"  [dim #8b949e]ID: {p_id[:12]}[/dim #8b949e]\n"
                        if p_id
                        else ""
                    )
                    if is_lan:
                        ip_val = getattr(p, "ip", "")
                        port_val = getattr(p, "port", "")
                        ip_port = (
                            f"{ip_val}:{port_val}" if ip_val and port_val else addr
                        )
                        ssid = getattr(p, "ssid", None)
                        net_str = f"Network: {ssid} • " if ssid else ""
                        item = PeerListItem(
                            Label(
                                f"[{color}]○ {name}[/{color}]\n"
                                f"{id_line}"
                                f"  [dim #8b949e]{net_str}{ip_port}[/dim #8b949e]"
                            ),
                            peer_address=addr,
                            peer_name=name,
                        )
                    else:
                        rssi_val = getattr(p, "rssi", None)
                        rssi_str = (
                            f"{rssi_val} dBm" if rssi_val is not None else "Nearby"
                        )
                        item = PeerListItem(
                            Label(
                                f"[{color}]○ {name}[/{color}]\n"
                                f"{id_line}"
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
