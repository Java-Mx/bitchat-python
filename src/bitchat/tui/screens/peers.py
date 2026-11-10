"""PeersScreen providing peer discovery, connection management, and status."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Input, Label, Static

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult
    from textual.binding import BindingType

logger = logging.getLogger(__name__)


class PeersScreen(Screen[None]):
    """Dedicated screen for discovering, inspecting, and connecting to peers."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss_screen", "Back", priority=True),
        Binding("r", "refresh_peers", "Refresh"),
        Binding("c", "handle_connect", "Connect"),
        Binding("d", "handle_disconnect", "Disconnect"),
        Binding("o", "open_chat", "Open Chat"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="peers-screen-container"):
            with Horizontal(id="peers-top-header"):
                yield Label(
                    "BitChat — Peer Management",
                    id="peers-title",
                )
                yield Static(id="peers-local-info")

            with Vertical(id="peers-table-container"):
                table = DataTable(id="peers-table")
                table.cursor_type = "row"
                table.zebra_stripes = True
                yield table

                with Vertical(id="peers-empty-container"):
                    yield Label(
                        "No BitChat peers discovered yet.",
                        id="peers-empty-title",
                    )
                    yield Label(
                        "Ensure radio/LAN is active and peers are nearby.\n"
                        "Press [Refresh] to scan or enter peer address below.",
                        id="peers-empty-subtitle",
                    )

            with Horizontal(id="peers-action-bar"):
                yield Input(
                    placeholder="Enter peer address or ID...",
                    id="peer-connect-input",
                )
                with Grid(
                    id="peers-footer-buttons",
                    classes="footer-action-grid",
                ):
                    # Row 1: Connect (2fr), Disconnect (2fr), Back (2fr)
                    yield Button(
                        "Connect",
                        id="btn-peers-connect",
                        classes="action-btn",
                    )
                    yield Button(
                        "Disconnect",
                        id="btn-peers-disconnect",
                        classes="action-btn",
                    )
                    yield Button(
                        "Back",
                        id="btn-peers-back",
                        classes="action-btn",
                    )
                    # Row 2: Refresh (2fr), Open Chat (2fr), Spacer (2fr)
                    yield Button(
                        "Refresh",
                        id="btn-peers-refresh",
                        classes="action-btn",
                    )
                    yield Button(
                        "Open Chat",
                        id="btn-peers-chat",
                        classes="action-btn",
                    )
                    yield Static(
                        "", id="peers-grid-spacer", classes="action-btn-spacer"
                    )

    def on_mount(self) -> None:
        """Setup table columns and size footer for the available terminal width."""
        table = self.query_one("#peers-table", DataTable)
        table.add_columns(
            "Peer Name",
            "Address / ID",
            "Transport",
            "Connection State",
            "Fingerprint",
            "Signal / Link",
        )
        self._update_footer_layout(self.size.width)
        self.refresh_peer_list()
        self._update_button_states()

    def on_resize(self, event: events.Resize) -> None:
        """Move the peer entry above the action grid when horizontal space is tight."""
        self._update_footer_layout(event.size.width)

    def _update_footer_layout(self, width: int) -> None:
        with contextlib.suppress(Exception):
            footer = self.query_one("#peers-action-bar")
            compact = width < 120
            footer.set_class(compact, "compact-footer")

    def refresh_peer_list(self) -> None:
        """Populate discovered and connected peers, strictly filtering self."""
        coord = getattr(self.app, "coordinator", None)
        local_pid = ""
        local_nick = "Anonymous"
        active_transport = "Unknown"

        if coord is not None:
            local_pid = coord.local_identity.peer_id_hex.lower()
            local_nick = coord.nickname
            active_transport = coord.effective_active_transport_name.upper()

        with contextlib.suppress(Exception):
            self.query_one("#peers-local-info", Static).update(
                f"[dim #8b949e]Local Node:[/dim #8b949e] "
                f"[bold #e6edf3]{local_nick}[/bold #e6edf3] "
                f"([dim #58a6ff]{local_pid[:8]}[/dim #58a6ff]) | "
                f"[dim #8b949e]Transport:[/dim #8b949e] "
                f"[bold #39c5cf]{active_transport}[/bold #39c5cf]"
            )

        try:
            table = self.query_one("#peers-table", DataTable)
        except Exception:
            return
        table.clear()

        if coord is None:
            with contextlib.suppress(Exception):
                self.query_one("#peers-empty-container").display = True
                table.display = False
            self._update_button_states()
            return

        active_transport_name = coord.effective_active_transport_name
        connected_peers = (
            set(coord.active_transport.connected_peers)
            if active_transport_name != "offline"
            else set()
        )
        discovered_peers = (
            coord.active_transport.discovered_peers
            if active_transport_name != "offline"
            else {}
        )
        authenticated_peers = getattr(self.app, "_authenticated_transport_peers", set())

        # Resolve known local addresses to prevent loopback self-peering
        local_addresses = {
            "127.0.0.1",
            "localhost",
            "::1",
            getattr(coord, "local_address", ""),
        }

        displayed_peers: set[str] = set()

        # 1. Connected / Authenticated peers
        for addr in connected_peers:
            if addr in local_addresses:
                continue

            pid = coord.address_to_peer_id.get(addr, "")
            if pid and pid.lower() == local_pid:
                # Prevent local device from appearing as its own peer
                continue

            nick = coord.peer_nicknames.get(pid, pid[:8] if pid else addr[:12])
            session = coord.get_session(pid) if pid else None
            fp = (
                session.remote_fingerprint[:16] + "..."
                if session and session.remote_fingerprint
                else "Pending"
            )
            is_auth = (pid in authenticated_peers) or (
                session.is_established if session else False
            )
            conn_state = (
                "[#3fb950]● Connected[/#3fb950]"
                if is_auth
                else "[#d29922]● Pending[/#d29922]"
            )
            trans_lbl = active_transport_name.upper()

            table.add_row(
                nick,
                addr,
                trans_lbl,
                conn_state,
                fp,
                "Strong",
            )
            displayed_peers.add(addr)
            if pid:
                displayed_peers.add(pid.lower())

        # 2. Discovered peers
        for addr_key, peer in discovered_peers.items():
            if addr_key in displayed_peers or addr_key in local_addresses:
                continue

            peer_pid = getattr(peer, "peer_id", "") or ""
            if peer_pid and peer_pid.lower() == local_pid:
                # Strictly prevent local device from appearing as its own peer
                continue

            name = (
                getattr(peer, "nickname", None)
                or getattr(peer, "name", None)
                or "Unknown"
            )
            if name.lower() == local_nick.lower():
                # Avoid self-nick spoof
                continue

            rssi = getattr(peer, "rssi", None)
            rssi_str = f"{rssi} dBm" if rssi is not None else "-"
            trans_lbl = active_transport_name.upper()

            table.add_row(
                name,
                addr_key,
                trans_lbl,
                "[dim #8b949e]Discovered[/dim #8b949e]",
                "-",
                rssi_str,
            )
            displayed_peers.add(addr_key)

        has_peers = len(displayed_peers) > 0
        with contextlib.suppress(Exception):
            empty_box = self.query_one("#peers-empty-container")
            table.display = has_peers
            empty_box.display = not has_peers

        self._update_button_states()

    def _update_button_states(self) -> None:
        """Update disabled state of peer action buttons based on current state."""
        try:
            table = self.query_one("#peers-table", DataTable)
            inp = self.query_one("#peer-connect-input", Input)
            has_input = bool(inp.value.strip())
            has_row = table.cursor_row is not None and table.row_count > 0

            coord = getattr(self.app, "coordinator", None)
            has_connected = False
            if coord is not None and coord.effective_active_transport_name != "offline":
                has_connected = bool(coord.active_transport.connected_peers)

            # Connect is enabled if input has text or a row in table is selected
            btn_connect = self.query_one("#btn-peers-connect", Button)
            btn_connect.disabled = not (has_input or has_row)

            # Disconnect is enabled if input has text or connected peers exist or row selected
            btn_disconnect = self.query_one("#btn-peers-disconnect", Button)
            btn_disconnect.disabled = not (has_input or has_connected or has_row)

            # Open Chat is enabled if row is selected or input has text
            btn_chat = self.query_one("#btn-peers-chat", Button)
            btn_chat.disabled = not (has_row or has_input)

            # Refresh and Back are always enabled
            self.query_one("#btn-peers-refresh", Button).disabled = False
            self.query_one("#btn-peers-back", Button).disabled = False
        except Exception as e:
            logger.debug("Failed updating peer button states: %s", e)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "peer-connect-input":
            self._update_button_states()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "peer-connect-input":
            self._handle_connect()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._update_button_states()
        self.action_open_chat()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._update_button_states()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button actions on PeersScreen."""
        match event.button.id:
            case "btn-peers-back":
                self.action_dismiss_screen()
            case "btn-peers-chat":
                self.action_open_chat()
            case "btn-peers-refresh":
                self.action_refresh_peers()
            case "btn-peers-connect":
                self._handle_connect()
            case "btn-peers-disconnect":
                self._handle_disconnect()

    def _get_target_peer(self) -> str:
        """Get the peer target from input box or selected row."""
        try:
            inp = self.query_one("#peer-connect-input", Input)
            target = inp.value.strip()
            if target:
                return target
            table = self.query_one("#peers-table", DataTable)
            if table.cursor_row is not None and table.row_count > 0:
                row = table.get_row_at(table.cursor_row)
                if (
                    row
                    and len(row) > 1
                    and str(row[1]) not in ("-", "Click [Refresh] to scan")
                ):
                    return str(row[1])
        except Exception:
            pass
        return ""

    def _handle_connect(self) -> None:
        """Connect to peer entered in input or selected in table."""
        inp = self.query_one("#peer-connect-input", Input)
        target = self._get_target_peer()
        inp.value = ""

        if target:
            coord = getattr(self.app, "coordinator", None)
            if coord is not None:
                spawn = getattr(self.app, "_spawn_task", None)
                if callable(spawn):

                    async def _conn() -> None:
                        try:
                            await coord.connect_peer(target, timeout=10.0)
                        except Exception as e:
                            logger.warning("Peer connect failed: %s", e)
                        finally:
                            self.refresh_peer_list()

                    spawn(_conn())

    def _handle_disconnect(self) -> None:
        """Disconnect selected or all peers."""
        inp = self.query_one("#peer-connect-input", Input)
        target = inp.value.strip()
        inp.value = ""

        coord = getattr(self.app, "coordinator", None)
        if coord is not None:
            spawn = getattr(self.app, "_spawn_task", None)
            if callable(spawn):

                async def _disc() -> None:
                    try:
                        if target:
                            await coord.disconnect_peer(target)
                        else:
                            # If row selected, disconnect that row
                            table = self.query_one("#peers-table", DataTable)
                            row_addr = ""
                            if table.cursor_row is not None and table.row_count > 0:
                                row = table.get_row_at(table.cursor_row)
                                if row and len(row) > 1:
                                    row_addr = str(row[1])
                            if (
                                row_addr
                                and row_addr in coord.active_transport.connected_peers
                            ):
                                await coord.disconnect_peer(row_addr)
                            else:
                                for addr in list(
                                    coord.active_transport.connected_peers
                                ):
                                    await coord.disconnect_peer(addr)
                    except Exception as e:
                        logger.warning("Peer disconnect error: %s", e)
                    finally:
                        self.refresh_peer_list()

                spawn(_disc())

    def action_connect(self) -> None:
        self._handle_connect()

    def action_disconnect(self) -> None:
        self._handle_disconnect()

    def action_refresh_peers(self) -> None:
        """Trigger active transport discovery and refresh peer table."""
        coord = getattr(self.app, "coordinator", None)
        if coord is not None:
            spawn = getattr(self.app, "_spawn_task", None)
            if callable(spawn):

                async def _scan() -> None:
                    try:
                        await coord.active_transport.start_discovery()
                    except Exception as e:
                        logger.warning("Peer scan error: %s", e)
                    finally:
                        self.refresh_peer_list()

                spawn(_scan())
        self.refresh_peer_list()

    def action_open_chat(self) -> None:
        """Transition into chat screen, opening selected peer's conversation if selected."""
        try:
            target_nick = ""
            table = self.query_one("#peers-table", DataTable)
            if table.cursor_row is not None and table.row_count > 0:
                row = table.get_row_at(table.cursor_row)
                if row and len(row) > 0:
                    raw_name = str(row[0])
                    if raw_name and raw_name != "Unknown":
                        target_nick = raw_name
            if not target_nick:
                inp_val = self.query_one("#peer-connect-input", Input).value.strip()
                if inp_val:
                    target_nick = inp_val

            if target_nick:
                switch_fn = getattr(self.app, "switch_conversation_context", None)
                if callable(switch_fn):
                    switch_fn(f"@{target_nick}")
        except Exception as e:
            logger.debug("Failed opening selected peer conversation: %s", e)

        open_chat = getattr(self.app, "action_open_chat", None)
        if callable(open_chat):
            open_chat()
        else:
            self.dismiss()

    def action_dismiss_screen(self) -> None:
        """Return to previous screen (Dashboard or Chat)."""
        self.dismiss()
