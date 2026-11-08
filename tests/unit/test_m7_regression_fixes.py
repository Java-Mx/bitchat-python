"""Regression tests for UI text wrapping, Peers navigation, network states, and themes."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Label, ListItem, ListView

from bitchat.crypto.identity import LocalIdentity
from bitchat.network.models import NetworkInfo, NetworkInterfaceInfo
from bitchat.network.provider import discover_network_info
from bitchat.storage.config import AppConfig, FileConfigStorage
from bitchat.tui.app import BitChatApp
from bitchat.tui.screens.chat import ChatScreen
from bitchat.tui.screens.edit_theme import EditThemeModal
from bitchat.tui.screens.peers import PeersScreen
from bitchat.tui.widgets.sidebar import PeerSidebar
from bitchat.tui.widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_peer_sidebar_scanning_text_wrapping() -> None:
    """Verify that scanning and no-peers messages contain clean line breaks and wrap in the sidebar."""

    class TestSidebarApp(App[None]):
        def compose(self) -> ComposeResult:
            yield PeerSidebar(
                nickname="TestNode",
                peer_id_hex="abcdef123456",
                fingerprint="0123456789abcdef",
            )

    app = TestSidebarApp()
    async with app.run_test() as pilot:
        sidebar = app.query_one(PeerSidebar)
        # 1. LAN scanning message
        sidebar.set_discovered_peers(
            {}, is_scanning=True, is_offline=False, transport="lan"
        )
        await pilot.pause()
        view = sidebar.query_one("#discovered-peers-list", ListView)
        assert len(view.children) == 1
        item = view.children[0]
        assert isinstance(item, ListItem)
        label = item.query_one(Label)
        # Ensure it has line break so it fits comfortably within narrow sidebars
        rendered_str = str(label.render())
        assert "\n" in rendered_str
        assert "Searching local network" in rendered_str
        assert "for peers..." in rendered_str

        # 2. LAN no peers message
        sidebar.set_discovered_peers(
            {}, is_scanning=False, is_offline=False, transport="lan"
        )
        await pilot.pause()
        view = sidebar.query_one("#discovered-peers-list", ListView)
        label = view.children[0].query_one(Label)
        rendered_str = str(label.render())
        assert "\n" in rendered_str
        assert "No BitChat peers" in rendered_str


@pytest.mark.asyncio
async def test_chat_screen_peers_button_opens_peers_screen(tmp_path: Path) -> None:
    """Verify clicking the Peers button in chat interface's status bar opens PeersScreen."""
    storage = FileConfigStorage(
        config_path=tmp_path / "config.json", identity_path=tmp_path / "identity.json"
    )
    coord = MagicMock()
    coord.nickname = "Alice"
    coord.local_identity = LocalIdentity.generate()
    coord.selected_transport_name = "bluetooth"
    coord.effective_active_transport_name = "bluetooth"
    coord.ble_status = "active"
    coord.offline_mode = False
    coord.mesh_router = MagicMock()
    coord.active_transport = MagicMock()
    coord.active_transport.state.value = "scanning"
    coord.active_transport.connected_peers = []
    coord.active_transport.discovered_peers = {}
    coord.active_transport.is_scanning = True
    coord.address_to_peer_id = {}
    coord.peer_nicknames = {}

    app = BitChatApp(coordinator=coord, storage=storage, initial_screen="chat")
    async with app.run_test() as pilot:
        await pilot.pause()

        # 1. Trigger peers action from default chat interface: opens PeersScreen
        status_bar = app.query_one(StatusBar)
        status_bar.on_button_pressed(MagicMock(button=MagicMock(id="btn-action-peers")))
        await pilot.pause()
        assert isinstance(app.screen, PeersScreen)
        app.screen.action_dismiss_screen()
        await pilot.pause()
        assert not isinstance(app.screen, PeersScreen)

        # Opening peers screen directly pushes PeersScreen
        app.action_open_peers()
        await pilot.pause()
        assert isinstance(app.screen, PeersScreen)

        # Clicking back returns to previous screen
        app.screen.action_dismiss_screen()
        await pilot.pause()
        assert not isinstance(app.screen, PeersScreen)

        # 2. Push ChatScreen explicitly and verify action_open_peers opens PeersScreen
        app.push_screen(ChatScreen())
        await pilot.pause()
        assert isinstance(app.screen, ChatScreen)

        app.screen.action_open_peers()
        await pilot.pause()
        assert isinstance(app.screen, PeersScreen)


def test_network_state_eight_distinct_states() -> None:
    """Verify all 8 network states are distinguished on NetworkInfo."""
    # 1. Fully connected state
    iface = NetworkInterfaceInfo(
        name="Wi-Fi",
        kind="Wi-Fi",
        operational_state="Up",
        ipv4_addresses=("192.168.1.100",),
        ssid="OfficeNet",
    )
    info = NetworkInfo(
        status="Connected",
        interface="Wi-Fi",
        interface_name="Wi-Fi",
        interface_state="Up",
        local_ip="192.168.1.100",
        ipv4_addresses=("192.168.1.100",),
        listening_port=41235,
        discovery_active=True,
        interfaces=(iface,),
    )
    assert info.is_detected is True
    assert info.is_configured is True
    assert info.is_administratively_enabled is True
    assert info.is_operational is True
    assert info.is_ip_assigned is True
    assert info.is_discovery_active is True
    assert info.is_listener_bound is True
    assert info.is_connected is True

    # 2. Wi-Fi disabled / no IP
    disabled_iface = NetworkInterfaceInfo(
        name="Wi-Fi",
        kind="Wi-Fi",
        operational_state="Disabled",
    )
    disconnected_info = NetworkInfo(
        status="Disconnected",
        interface="Unavailable",
        interface_name="Wi-Fi",
        interface_state="Disabled",
        local_ip="",
        interfaces=(disabled_iface,),
    )
    assert disconnected_info.is_detected is True
    assert disconnected_info.is_administratively_enabled is False
    assert disconnected_info.is_operational is False
    assert disconnected_info.is_ip_assigned is False
    assert disconnected_info.is_connected is False


def test_discover_network_info_ignores_down_default_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify discover_network_info does not select an interface whose operational status is Down."""
    eth_down = NetworkInterfaceInfo(
        name="Ethernet",
        kind="Ethernet",
        operational_state="Down",
        ipv4_addresses=("10.0.0.5",),
        default_route=True,
    )
    wifi_up = NetworkInterfaceInfo(
        name="Wi-Fi",
        kind="Wi-Fi",
        operational_state="Up",
        ipv4_addresses=("192.168.1.50",),
        ssid="MyNetwork",
    )

    monkeypatch.setattr(
        "bitchat.network.provider._discover_windows",
        lambda: ((eth_down, wifi_up), "Ethernet"),
    )
    monkeypatch.setattr("sys.platform", "win32")

    info = discover_network_info()
    # It must select the operational Wi-Fi interface, not the down Ethernet
    assert info.interface_name == "Wi-Fi"
    assert info.status == "Connected"
    assert info.local_ip == "192.168.1.50"
    assert info.ssid == "MyNetwork"


@pytest.mark.asyncio
async def test_theme_and_accent_switching_persistence(tmp_path: Path) -> None:
    """Verify that applying theme changes updates application CSS classes and persists to storage."""
    storage = FileConfigStorage(
        config_path=tmp_path / "config.json", identity_path=tmp_path / "identity.json"
    )
    storage.save_config(
        AppConfig(density="comfortable", accent="blue", show_timestamps=True)
    )
    from unittest.mock import AsyncMock

    coord = MagicMock()
    coord.nickname = "Alice"
    coord.local_identity = LocalIdentity.generate()
    coord.start = AsyncMock()
    coord.effective_active_transport_name = "offline"
    app = BitChatApp(coordinator=coord, storage=storage, initial_screen="chat")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "density-comfortable" in app.classes
        assert "accent-blue" in app.classes

        # Apply Emerald + Compact
        app.on_edit_theme_modal_theme_applied(
            EditThemeModal.ThemeApplied(
                density="compact", show_timestamps=False, accent_name="emerald"
            )
        )
        await pilot.pause()

        assert "density-compact" in app.classes
        assert "accent-emerald" in app.classes
        assert app.config.density == "compact"
        assert app.config.accent == "emerald"
        assert app.config.show_timestamps is False

        # Verify saved to storage
        loaded_cfg = storage.load_config()
        assert loaded_cfg.density == "compact"
        assert loaded_cfg.accent == "emerald"
        assert loaded_cfg.show_timestamps is False
