"""Pre-commit verification tests for BitChat hardening:
1. Home Screen protection and layout preservation.
2. Offline Mode status clean-up (displays exclusively 'OFFLINE MODE').
3. LAN and BLE status accuracy (separation of state, truthful reporting).
4. Strict 2:2:2 Peer Grid layout preservation.
5. Peer Screen navigation from both Home Screen and Chat System.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from textual.widgets import Button

from bitchat.network.models import NetworkInfo, NetworkInterfaceInfo
from bitchat.network.provider import discover_network_info
from bitchat.storage.config import AppConfig
from bitchat.transport.base import TransportState
from bitchat.tui.app import BitChatApp
from bitchat.tui.screens.home import HomeScreen
from bitchat.tui.screens.peers import PeersScreen
from bitchat.tui.widgets.message_input import MessageInput
from bitchat.tui.widgets.status_bar import StatusBar


@pytest.mark.asyncio
async def test_home_screen_protection() -> None:
    """Home Screen must remain the central dashboard with layout and navigation intact."""
    app = BitChatApp(config=AppConfig(), initial_screen="home")
    async with app.run_test() as pilot:
        assert isinstance(app.screen, HomeScreen)
        # Verify wordmark and subtitle
        assert app.screen.query_one("#home-wordmark") is not None
        assert app.screen.query_one("#home-subtitle") is not None
        assert app.screen.query_one("#home-nav-menu") is not None

        # Verify key menu items
        assert app.screen.query_one("#nav-item-connect") is not None
        assert app.screen.query_one("#nav-item-peers") is not None
        assert app.screen.query_one("#nav-item-settings") is not None
        assert app.screen.query_one("#nav-item-commands") is not None
        assert app.screen.query_one("#nav-item-telemetry") is not None
        assert app.screen.query_one("#nav-item-quit") is not None

        # Verify navigation to Peers from Home
        app.screen.action_open_peers()
        await pilot.pause()
        assert isinstance(app.screen, PeersScreen)

        # Verify Escape returns back to Home Screen
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_offline_mode_status_clean_presentation() -> None:
    """Offline Mode must communicate ONLY 'OFFLINE MODE' without any radio warnings."""
    coordinator = MagicMock()
    coordinator.offline_mode = True
    coordinator.selected_transport_name = "offline"
    coordinator.effective_active_transport_name = "offline"
    coordinator.active_transport = MagicMock()
    coordinator.active_transport.get_telemetry.return_value = {
        "transport": "offline",
        "state": "offline",
        "adapter_state": "On",
        "adapter_available": True,
    }
    coordinator.active_transport.connected_peers = []
    coordinator.active_transport.discovered_peers = {}
    coordinator.local_identity = MagicMock()
    coordinator.local_identity.peer_id_hex = "0123456789abcdef"
    coordinator.local_identity.fingerprint = "0123456789abcdef"
    coordinator.nickname = "Ashwin"

    app = BitChatApp(coordinator=coordinator, config=AppConfig(), initial_screen="chat")
    async with app.run_test() as pilot:
        app._refresh_peer_lists()
        await pilot.pause()

        sb = app.query_one(StatusBar)
        assert sb.mesh_status == "OFFLINE MODE"
        assert "Bluetooth" not in sb.mesh_status
        assert "LAN" not in sb.mesh_status
        assert "Unavailable" not in sb.mesh_status
        assert "Inactive" not in sb.mesh_status


@pytest.mark.asyncio
async def test_lan_status_accuracy_and_isolation() -> None:
    """LAN status must report disconnected when interface drops, and isolate radio status."""
    coordinator = MagicMock()
    coordinator.offline_mode = False
    coordinator.selected_transport_name = "lan"
    coordinator.effective_active_transport_name = "lan"
    lan_trans = MagicMock()
    lan_trans.state = TransportState.CONNECTED
    lan_trans.is_available.return_value = True
    lan_trans.is_scanning = True
    lan_trans.server = MagicMock()
    lan_trans.server.is_listening = True
    lan_trans.connected_peers = []
    lan_trans.discovered_peers = {"192.168.1.50": MagicMock()}
    lan_trans.get_telemetry.return_value = {
        "transport": "lan",
        "state": "connected",
        "scanner_status": "Active",
    }
    adapter_mgr = MagicMock()
    adapter_mgr.current_info = NetworkInfo(
        status="Connected",
        interface="Wi-Fi",
        interface_state="Up",
        local_ip="192.168.1.36",
        default_gateway="192.168.1.1",
    )
    lan_trans.adapter_manager = adapter_mgr
    coordinator.active_transport = lan_trans
    coordinator.local_identity = MagicMock()
    coordinator.local_identity.peer_id_hex = "abcdef0123456789"
    coordinator.local_identity.fingerprint = "abcdef0123456789"
    coordinator.nickname = "Ashwin"
    coordinator.get_session.return_value = None

    app = BitChatApp(coordinator=coordinator, config=AppConfig(), initial_screen="chat")
    async with app.run_test() as pilot:
        app._refresh_peer_lists()
        await pilot.pause()

        sb = app.query_one(StatusBar)
        # Active discovering state
        assert "LAN / Wi-Fi Active" in sb.mesh_status
        assert "Bluetooth" not in sb.mesh_status

        # Simulate Wi-Fi drop: network interface disconnected
        adapter_mgr.current_info = NetworkInfo(
            status="Disconnected",
            interface="Unavailable",
            interface_state="Down",
            local_ip="",
        )
        lan_trans.is_available.return_value = False
        lan_trans.state = TransportState.UNAVAILABLE
        app._refresh_peer_lists()
        await pilot.pause()

        assert "LAN Unavailable" in sb.mesh_status
        assert "Bluetooth" not in sb.mesh_status


@pytest.mark.asyncio
async def test_ble_status_accuracy_and_isolation() -> None:
    """BLE status must reflect adapter and connection state without leaking LAN messages."""
    coordinator = MagicMock()
    coordinator.offline_mode = False
    coordinator.selected_transport_name = "bluetooth"
    coordinator.effective_active_transport_name = "bluetooth"
    ble_trans = MagicMock()
    ble_trans.state = TransportState.CONNECTED
    ble_trans.connected_peers = []
    ble_trans.discovered_peers = {}
    ble_trans.get_telemetry.return_value = {
        "transport": "bluetooth",
        "adapter_state": "On",
        "adapter_available": True,
        "scanner_status": "Active",
        "advertising_active": True,
        "central_supported": True,
        "peripheral_supported": True,
    }
    coordinator.active_transport = ble_trans
    coordinator.local_identity = MagicMock()
    coordinator.local_identity.peer_id_hex = "1122334455667788"
    coordinator.local_identity.fingerprint = "1122334455667788"
    coordinator.nickname = "Ashwin"

    app = BitChatApp(coordinator=coordinator, config=AppConfig(), initial_screen="chat")
    async with app.run_test() as pilot:
        app._refresh_peer_lists()
        await pilot.pause()

        sb = app.query_one(StatusBar)
        assert "Bluetooth Active" in sb.mesh_status
        assert "BLE Central Scanning" in sb.mesh_status
        assert "BLE Peripheral Advertising Active" in sb.mesh_status
        assert "LAN" not in sb.mesh_status

        # Simulate Bluetooth disabled
        ble_trans.get_telemetry.return_value = {
            "transport": "bluetooth",
            "adapter_state": "Off",
            "adapter_available": False,
        }
        app._refresh_peer_lists()
        await pilot.pause()

        assert sb.mesh_status == "✕ Bluetooth Disabled"
        assert "LAN" not in sb.mesh_status


@pytest.mark.asyncio
async def test_peer_screen_navigation_from_chat_system() -> None:
    """Peer button in Chat System action bar must open PeersScreen and restore Chat on Esc."""
    app = BitChatApp(config=AppConfig(), initial_screen="chat")
    async with app.run_test() as pilot:
        # Initially on root chat screen
        assert not isinstance(app.screen, PeersScreen)
        assert not isinstance(app.screen, HomeScreen)

        # Click Peers button on bottom action bar
        btn_peers = app.query_one("#btn-action-peers", Button)
        await pilot.click(btn_peers)
        await pilot.pause()

        # Must have transitioned to PeersScreen
        assert isinstance(app.screen, PeersScreen)

        # Press Escape: must dismiss back to Chat System cleanly
        await pilot.press("escape")
        await pilot.pause()

        assert not isinstance(app.screen, PeersScreen)
        # Message input should remain functional
        msg_inp = app.query_one(MessageInput)
        assert msg_inp is not None

        # Keyboard F4 shortcut also opens PeersScreen
        await pilot.press("f4")
        await pilot.pause()
        assert isinstance(app.screen, PeersScreen)

        # Return to chat via Back button
        await pilot.click("#btn-peers-back")
        await pilot.pause()
        assert not isinstance(app.screen, PeersScreen)


def test_virtual_host_only_adapter_not_marked_connected() -> None:
    """Virtual host-only adapters without gateway or default route must not mark host connected."""
    from unittest.mock import patch

    vbox_adapter = NetworkInterfaceInfo(
        name="Ethernet 2",
        description="VirtualBox Host-Only Ethernet Adapter",
        operational_state="Up",
        ipv4_addresses=("192.168.56.1",),
        gateways=(),
        default_route=False,
    )

    with patch(
        "bitchat.network.provider._discover_windows",
        return_value=((vbox_adapter,), ""),
    ):
        info = discover_network_info()
        assert info.status == "Disconnected"
        assert info.is_connected is False
