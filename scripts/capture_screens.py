"""Generate SVG screenshots for all BitChat screens covering all 23 core states and UI components."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest.mock import AsyncMock, MagicMock

from tests.ble.mocks import (
    MockBleakClient,
    MockBleakScanner,
    MockBLEServerBackend,
)
from textual.widgets import Input

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.manager import BLEManager
from bitchat.ble.models import DiscoveredPeer
from bitchat.ble.server import BLEServer
from bitchat.crypto.identity import LocalIdentity
from bitchat.network.transport import LANTransport
from bitchat.storage.config import InMemoryStorage
from bitchat.transport.base import TransportState
from bitchat.transport.bluetooth import BluetoothTransport
from bitchat.tui.app import BitChatApp
from bitchat.tui.screens.ble_error import BLEErrorModal
from bitchat.tui.screens.commands import CommandsScreen
from bitchat.tui.screens.edit_theme import EditThemeModal
from bitchat.tui.screens.home import HomeScreen
from bitchat.tui.screens.peers import PeersScreen
from bitchat.tui.screens.settings import SettingsScreen
from bitchat.tui.screens.telemetry import TelemetryScreen
from bitchat.tui.widgets.chat_view import ChatView


def make_mock_coord(nickname: str = "Alice") -> SessionCoordinator:
    identity = LocalIdentity.generate()
    server = BLEServer(backend=MockBLEServerBackend())
    manager = BLEManager(
        sender_id=identity.peer_id,
        scanner_factory=lambda **kw: MockBleakScanner(
            kw["detection_callback"], kw["service_uuids"]
        ),
        client_factory=lambda address, **kw: MockBleakClient(address=address, **kw),
    )
    storage = InMemoryStorage()
    coord = SessionCoordinator(
        local_identity=identity,
        ble_manager=manager,
        ble_server=server,
        storage=storage,
        nickname=nickname,
    )
    coord.start = AsyncMock()
    coord.stop = AsyncMock()
    return coord


async def capture_all() -> None:
    out_dir = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    coord = make_mock_coord("Alice")
    discovered_peers_map = {
        "11:22:33:44:55:66": DiscoveredPeer(
            address="11:22:33:44:55:66",
            name="Bob",
            rssi=-54,
            peer_id="bob-peer-id-12345",
            nickname="Bob",
        ),
        "AA:BB:CC:DD:EE:01": DiscoveredPeer(
            address="AA:BB:CC:DD:EE:01",
            name="Charlie",
            rssi=-68,
            peer_id="charlie-peer-id-67890",
            nickname="Charlie",
        ),
    }
    coord.ble_manager.scanner._discovered_peers = dict(discovered_peers_map)

    # -----------------------------------------------------------------------
    # Session A: Home screen, Modals, System telemetry, Diagnostics
    # -----------------------------------------------------------------------
    app = BitChatApp(coordinator=coord, initial_screen="home")
    async with app.run_test(size=(100, 34)) as pilot:
        await pilot.pause()

        # 01. Home Screen
        svg = app.export_screenshot()
        (out_dir / "01_home_screen.svg").write_text(svg, encoding="utf-8")
        (out_dir / "01_home_screen_connect_selected.svg").write_text(svg, encoding="utf-8")

        # 02. Connection Modal
        await pilot.press("c")
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "02_connection_modal.svg").write_text(svg, encoding="utf-8")
        (out_dir / "03_connection_menu.svg").write_text(svg, encoding="utf-8")
        await pilot.press("escape")
        await pilot.pause()

        # 03. BLE Warning Stage 1 (Acknowledgement Mode: single "Okay, I understand")
        modal_stage1 = BLEErrorModal(
            error_message="WinRT GATT service advertising aborted (status 3: Aborted). Windows stopped BLE advertising.",
            bluetooth_available=True,
            central_active=True,
            peripheral_failure=True,
            peripheral_supported=True,
            lan_available=True,
            failed_stage="advertising_start",
            error_code=3,
            error_source="winrt.GattServiceProviderAdvertisementStatus",
            acknowledgement_mode=True,
        )
        app.push_screen(modal_stage1)
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "03_ble_warning_stage1_ack.svg").write_text(svg, encoding="utf-8")
        await pilot.click("#btn-ble-ack")
        await pilot.pause()

        # 04. BLE Warning Stage 2 (Actionable: 3 choices: Retry Adapter, Continue Wi-Fi/LAN, Continue Offline)
        modal_stage2 = BLEErrorModal(
            error_message="BLE connection to peer could not be established. Peripheral mode remains limited.",
            bluetooth_available=True,
            central_active=True,
            peripheral_failure=True,
            peripheral_supported=True,
            lan_available=True,
            failed_stage="peripheral_init",
            error_code=3,
            error_source="winrt.GattServiceProviderAdvertisementStatus",
            acknowledgement_mode=False,
        )
        app.push_screen(modal_stage2)
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "04_ble_warning_stage2_actionable.svg").write_text(svg, encoding="utf-8")
        await pilot.press("escape")
        await pilot.pause()

        # 05. BLE Init Failure (Hardware Error / Radio Off)
        modal_hw_err = BLEErrorModal(
            error_message="Bluetooth adapter hardware not found or radio powered OFF.",
            bluetooth_available=False,
            central_active=False,
            peripheral_failure=True,
            peripheral_supported=False,
            lan_available=True,
            failed_stage="adapter_discovery",
            acknowledgement_mode=False,
        )
        app.push_screen(modal_hw_err)
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "05_ble_init_failure.svg").write_text(svg, encoding="utf-8")
        await pilot.press("escape")
        await pilot.pause()

        # 08. Peers Screen Empty
        coord.ble_manager.scanner._discovered_peers = {}
        peers_screen_empty = PeersScreen()
        app.push_screen(peers_screen_empty)
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "08_peers_screen_empty.svg").write_text(svg, encoding="utf-8")
        (out_dir / "peers_empty.svg").write_text(svg, encoding="utf-8")
        await pilot.press("escape")
        await pilot.pause()

        # 09. Peers Screen Discovered
        coord._is_running = True
        coord._transports["bluetooth"]._is_running = True
        coord._transports["bluetooth"]._state = TransportState.SCANNING
        coord._active_transport_name = "bluetooth"
        coord.ble_status = "scanning"
        coord.ble_manager.scanner._discovered_peers = dict(discovered_peers_map)
        peers_screen_disc = PeersScreen()
        app.push_screen(peers_screen_disc)
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "09_peers_screen_discovered.svg").write_text(svg, encoding="utf-8")
        (out_dir / "04_peers_screen.svg").write_text(svg, encoding="utf-8")
        (out_dir / "peers_discovered.svg").write_text(svg, encoding="utf-8")
        (out_dir / "peers_action_grid_normal.svg").write_text(svg, encoding="utf-8")
        (out_dir / "peers_bottom_bar_normal.svg").write_text(svg, encoding="utf-8")
        await pilot.press("escape")
        await pilot.pause()

        # Peers Screen Connected
        mock_sess = MagicMock()
        mock_sess.is_established = True
        mock_sess.remote_fingerprint = "4a8f9c1b2e3d5f6a7b8c9d0e1f2a3b4c5d6e7f80"
        coord._sessions["bob-peer-id-12345"] = mock_sess
        mock_conn = MagicMock()
        mock_conn.is_ready = True
        mock_trans = MagicMock()
        mock_trans.connection = mock_conn
        coord.ble_manager._transports["11:22:33:44:55:66"] = mock_trans
        coord.address_to_peer_id["11:22:33:44:55:66"] = "bob-peer-id-12345"
        coord.peer_nicknames["bob-peer-id-12345"] = "Bob"
        peers_screen_conn = PeersScreen()
        app.push_screen(peers_screen_conn)
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "peers_connected.svg").write_text(svg, encoding="utf-8")
        await pilot.press("escape")
        await pilot.pause()
        coord.ble_manager._transports.clear()
        coord._sessions.clear()

        # 21. Commands Help Screen
        cmd_screen = CommandsScreen()
        app.push_screen(cmd_screen)
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "21_commands_help.svg").write_text(svg, encoding="utf-8")
        (out_dir / "05_commands_screen.svg").write_text(svg, encoding="utf-8")
        await pilot.press("escape")
        await pilot.pause()

        # 22. System Telemetry Screen
        telem_screen = TelemetryScreen()
        app.push_screen(telem_screen)
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "22_telemetry_screen.svg").write_text(svg, encoding="utf-8")
        (out_dir / "03_telemetry_screen.svg").write_text(svg, encoding="utf-8")
        await pilot.press("escape")
        await pilot.pause()

        # Settings Screen Screens (11 through 20)
        settings_screen = SettingsScreen()
        app.push_screen(settings_screen)
        await pilot.pause()

        # 11. Settings General (Cat 0)
        svg = app.export_screenshot()
        (out_dir / "11_settings_general.svg").write_text(svg, encoding="utf-8")

        # 12. Settings Identity & Security (Cat 1) - Shows RadioSet and public identity
        settings_screen.switch_category("identity")
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "12_settings_identity_security.svg").write_text(svg, encoding="utf-8")

        # 13. Settings Bluetooth (Cat 2)
        settings_screen.switch_category("bluetooth")
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "13_settings_bluetooth.svg").write_text(svg, encoding="utf-8")

        # 14. Settings LAN (Cat 3)
        settings_screen.switch_category("network")
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "14_settings_lan.svg").write_text(svg, encoding="utf-8")

        # 15. Settings Notifications (Cat 4)
        settings_screen.switch_category("notifications")
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "15_settings_notifications.svg").write_text(svg, encoding="utf-8")

        # 16. Settings Appearance (Cat 5)
        settings_screen.switch_category("appearance")
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "16_settings_appearance.svg").write_text(svg, encoding="utf-8")

        # 17. Settings Startup (Cat 6)
        settings_screen.switch_category("startup")
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "17_settings_startup.svg").write_text(svg, encoding="utf-8")

        # 18. Settings Advanced (Cat 7)
        settings_screen.switch_category("advanced")
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "18_settings_advanced.svg").write_text(svg, encoding="utf-8")

        # 19. Settings Unsaved Changes (Cat 0 with modified field)
        settings_screen.switch_category("general")
        await pilot.pause()
        nick_input = settings_screen.query_one("#settings-input-nickname", Input)
        nick_input.value = "Alice_Modified"
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "19_settings_unsaved_changes.svg").write_text(svg, encoding="utf-8")
        (out_dir / "07_settings_screen_unsaved.svg").write_text(svg, encoding="utf-8")

        # 20. Settings Saved
        await pilot.click("#btn-settings-save")
        await pilot.pause()
        svg = app.export_screenshot()
        (out_dir / "20_settings_saved.svg").write_text(svg, encoding="utf-8")
        (out_dir / "06_settings_screen.svg").write_text(svg, encoding="utf-8")
        (out_dir / "06_settings_screen_saved.svg").write_text(svg, encoding="utf-8")
        await pilot.press("escape")
        await pilot.pause()

        # 23. Quit Screen State (HomeScreen with item 5 / Quit highlighted)
        if isinstance(app.screen, HomeScreen):
            app.screen.selected_index = 5
            app.screen._render_menu()
            await pilot.pause()
            svg = app.export_screenshot()
            (out_dir / "23_quit_modal.svg").write_text(svg, encoding="utf-8")

    # -----------------------------------------------------------------------
    # Session B: Chat Screen with LAN Active & Truthful Status
    # -----------------------------------------------------------------------
    # Configure coordinator with LAN active and Bluetooth available
    lan_trans = coord._transports["lan"]
    assert isinstance(lan_trans, LANTransport)
    lan_trans._state = TransportState.SCANNING
    coord._active_transport_name = "lan"

    bt_trans = coord._transports["bluetooth"]
    assert isinstance(bt_trans, BluetoothTransport)
    bt_trans._state = TransportState.READY

    app_chat_lan = BitChatApp(coordinator=coord, initial_screen="chat")
    async with app_chat_lan.run_test(size=(100, 34)) as pilot:
        await pilot.pause()
        app_chat_lan._refresh_peer_lists()
        await pilot.pause()

        chat = app_chat_lan.query_one(ChatView)
        chat.add_system_message("BitChat decentralized mesh active (LAN Wi-Fi transport).")
        chat.add_chat_message("Bob", "Hey Alice, LAN broadcast discovery connected us!", is_encrypted=True)
        chat.add_chat_message("Alice", "Everything is encrypted end-to-end with ChaCha20-Poly1305.", is_encrypted=True, is_self=True)
        await pilot.pause()

        # 06. LAN Active Chat (Status reports ● LAN / Wi-Fi Active • Bluetooth Available)
        svg = app_chat_lan.export_screenshot()
        (out_dir / "06_lan_active_chat.svg").write_text(svg, encoding="utf-8")

        # 10. General Chat Screen
        (out_dir / "10_chat_screen.svg").write_text(svg, encoding="utf-8")
        (out_dir / "08_chat_screen.svg").write_text(svg, encoding="utf-8")

    # -----------------------------------------------------------------------
    # Session C: Chat Screen with BLE Active
    # -----------------------------------------------------------------------
    bt_trans._state = TransportState.SCANNING
    coord._active_transport_name = "bluetooth"

    app_chat_ble = BitChatApp(coordinator=coord, initial_screen="chat")
    async with app_chat_ble.run_test(size=(100, 34)) as pilot:
        await pilot.pause()
        app_chat_ble._refresh_peer_lists()
        await pilot.pause()

        chat = app_chat_ble.query_one(ChatView)
        chat.add_system_message("BitChat decentralized mesh active (Bluetooth Low Energy transport).")
        chat.add_chat_message("Charlie", "Direct peer-to-peer BLE link established.", is_encrypted=True)
        await pilot.pause()

        # 07. BLE Active Chat
        svg = app_chat_ble.export_screenshot()
        (out_dir / "07_ble_active_chat.svg").write_text(svg, encoding="utf-8")

    # -----------------------------------------------------------------------
    # Session D: Theme Variations (Midnight Blue, Cyber Cyan, Terminal Emerald, Amethyst Purple)
    # -----------------------------------------------------------------------
    for theme_name, accent_key in [
        ("midnight_blue", "blue"),
        ("cyber_cyan", "cyan"),
        ("terminal_emerald", "emerald"),
        ("amethyst_purple", "purple"),
    ]:
        theme_coord = make_mock_coord(f"Alice_{accent_key}")
        theme_cfg = InMemoryStorage()
        theme_app = BitChatApp(coordinator=theme_coord, storage=theme_cfg, initial_screen="chat")
        theme_app.current_accent = accent_key
        async with theme_app.run_test(size=(100, 34)) as pilot:
            theme_app.remove_class("accent-blue")
            theme_app.add_class(f"accent-{accent_key}")
            await pilot.pause()

            # Chat theme capture
            chat = theme_app.query_one(ChatView)
            chat.add_system_message(f"Theme active: {theme_name.replace('_', ' ').title()}")
            chat.add_chat_message("Bob", f"Testing encrypted session under {theme_name} theme.", is_encrypted=True)
            chat.add_chat_message("Alice", "Theme tokens applied cleanly across all widgets.", is_encrypted=True, is_self=True)
            await pilot.pause()
            svg = theme_app.export_screenshot()
            (out_dir / f"theme_chat_{theme_name}.svg").write_text(svg, encoding="utf-8")

        # Peers theme capture in separate test app
        peers_coord = make_mock_coord(f"Alice_{accent_key}")
        peers_coord._is_running = True
        peers_coord._transports["bluetooth"]._is_running = True
        peers_coord._transports["bluetooth"]._state = TransportState.SCANNING
        peers_coord._active_transport_name = "bluetooth"
        peers_coord.ble_status = "scanning"
        peers_coord.ble_manager.scanner._discovered_peers = dict(discovered_peers_map)
        peers_app = BitChatApp(coordinator=peers_coord, initial_screen="chat")
        peers_app.current_accent = accent_key
        async with peers_app.run_test(size=(100, 34)) as pilot:
            peers_app.remove_class("accent-blue")
            peers_app.add_class(f"accent-{accent_key}")
            peers_screen = PeersScreen()
            peers_app.push_screen(peers_screen)
            await pilot.pause()
            svg = peers_app.export_screenshot()
            (out_dir / f"theme_peers_{theme_name}.svg").write_text(svg, encoding="utf-8")

        # Settings theme capture in separate test app
        settings_app = BitChatApp(coordinator=make_mock_coord(f"Alice_{accent_key}"), initial_screen="chat")
        settings_app.current_accent = accent_key
        async with settings_app.run_test(size=(100, 34)) as pilot:
            settings_app.remove_class("accent-blue")
            settings_app.add_class(f"accent-{accent_key}")
            settings_screen = SettingsScreen()
            settings_app.push_screen(settings_screen)
            await pilot.pause()
            svg = settings_app.export_screenshot()
            (out_dir / f"theme_settings_{theme_name}.svg").write_text(svg, encoding="utf-8")

    # -----------------------------------------------------------------------
    # Session E: Peers Narrow Terminal Width
    # -----------------------------------------------------------------------
    narrow_coord = make_mock_coord("Alice")
    narrow_coord._is_running = True
    narrow_coord._transports["bluetooth"]._is_running = True
    narrow_coord._transports["bluetooth"]._state = TransportState.SCANNING
    narrow_coord._active_transport_name = "bluetooth"
    narrow_coord.ble_status = "scanning"
    narrow_coord.ble_manager.scanner._discovered_peers = dict(discovered_peers_map)
    app_narrow = BitChatApp(coordinator=narrow_coord, initial_screen="chat")
    async with app_narrow.run_test(size=(75, 30)) as pilot_narrow:
        p_disc = PeersScreen()
        app_narrow.push_screen(p_disc)
        await pilot_narrow.pause()
        svg = app_narrow.export_screenshot()
        (out_dir / "peers_action_grid_narrow.svg").write_text(svg, encoding="utf-8")
        (out_dir / "peers_bottom_bar_narrow.svg").write_text(svg, encoding="utf-8")

    # -----------------------------------------------------------------------
    # Session F: Appearance & Theme Modal Variations and States
    # -----------------------------------------------------------------------
    for theme_name, accent_key in [
        ("midnight_blue", "blue"),
        ("cyber_cyan", "cyan"),
        ("terminal_emerald", "emerald"),
        ("amethyst_purple", "purple"),
    ]:
        theme_modal_app = BitChatApp(coordinator=make_mock_coord(f"Alice_{accent_key}"), initial_screen="chat")
        async with theme_modal_app.run_test(size=(100, 34)) as pilot_modal:
            for acc in ("blue", "cyan", "emerald", "purple"):
                theme_modal_app.remove_class(f"accent-{acc}")
            theme_modal_app.add_class(f"accent-{accent_key}")
            theme_modal_app.current_accent = accent_key
            modal = EditThemeModal(
                current_density="comfortable",
                current_show_timestamps=True,
                current_accent=accent_key,
            )
            theme_modal_app.push_screen(modal)
            await pilot_modal.pause()
            svg = theme_modal_app.export_screenshot()
            (out_dir / f"appearance_modal_{theme_name}.svg").write_text(svg, encoding="utf-8")
            if accent_key == "blue":
                (out_dir / "appearance_modal_centered_buttons.svg").write_text(svg, encoding="utf-8")
                (out_dir / "appearance_modal_centered_all_changes_saved.svg").write_text(svg, encoding="utf-8")

    # Unsaved changes, Reset, Apply, Cancel captures
    app_dirty = BitChatApp(coordinator=make_mock_coord("Alice"), initial_screen="chat")
    async with app_dirty.run_test(size=(100, 34)) as pilot_dirty:
        modal_dirty = EditThemeModal(
            current_density="comfortable",
            current_show_timestamps=True,
            current_accent="blue",
        )
        app_dirty.push_screen(modal_dirty)
        await pilot_dirty.pause()

        # Trigger dirty state by clicking compact density
        await pilot_dirty.click("#rb-density-comp")
        await pilot_dirty.pause()
        svg = app_dirty.export_screenshot()
        (out_dir / "appearance_modal_unsaved_changes.svg").write_text(svg, encoding="utf-8")

        # Reset to Default
        await pilot_dirty.click("#btn-theme-reset")
        await pilot_dirty.pause()
        svg = app_dirty.export_screenshot()
        (out_dir / "appearance_modal_after_reset.svg").write_text(svg, encoding="utf-8")

        # Apply changes
        await pilot_dirty.click("#btn-theme-apply")
        await pilot_dirty.pause()
        svg = app_dirty.export_screenshot()
        (out_dir / "appearance_modal_after_apply.svg").write_text(svg, encoding="utf-8")

        # Reopen and Cancel
        modal_cancel = EditThemeModal(
            current_density="comfortable",
            current_show_timestamps=True,
            current_accent="purple",
        )
        app_dirty.push_screen(modal_cancel)
        await pilot_dirty.pause()
        await pilot_dirty.click("#btn-theme-close")
        await pilot_dirty.pause()
        svg = app_dirty.export_screenshot()
        (out_dir / "appearance_modal_after_cancel.svg").write_text(svg, encoding="utf-8")

    # -----------------------------------------------------------------------
    # Session G: Multi-Resolution Screen Verification (1600x900, 1280x720, 1000x700, 800x600)
    # -----------------------------------------------------------------------
    resolutions = [
        ("1600x900", 160, 45),
        ("1280x720", 128, 36),
        ("1000x700", 100, 35),
        ("800x600", 80, 28),
    ]
    for res_name, cols, rows in resolutions:
        res_coord = make_mock_coord("Alice")
        res_coord._is_running = True
        res_coord._transports["bluetooth"]._is_running = True
        res_coord._transports["bluetooth"]._state = TransportState.SCANNING
        res_coord._active_transport_name = "bluetooth"
        res_coord.ble_status = "scanning"
        res_coord.ble_manager.scanner._discovered_peers = dict(discovered_peers_map)
        app_res_peers = BitChatApp(coordinator=res_coord, initial_screen="chat")
        async with app_res_peers.run_test(size=(cols, rows)) as pilot_res:
            peers_scr = PeersScreen()
            app_res_peers.push_screen(peers_scr)
            await pilot_res.pause()
            svg = app_res_peers.export_screenshot()
            (out_dir / f"peers_screen_{res_name}.svg").write_text(svg, encoding="utf-8")

        app_res_theme = BitChatApp(coordinator=make_mock_coord("Alice"), initial_screen="chat")
        async with app_res_theme.run_test(size=(cols, rows)) as pilot_res_theme:
            modal_res = EditThemeModal(
                current_density="comfortable",
                current_show_timestamps=True,
                current_accent="blue",
            )
            app_res_theme.push_screen(modal_res)
            await pilot_res_theme.pause()
            svg = app_res_theme.export_screenshot()
            (out_dir / f"appearance_modal_{res_name}.svg").write_text(svg, encoding="utf-8")

    print(f"All screen SVGs successfully captured into {out_dir.resolve()}")


if __name__ == "__main__":
    asyncio.run(capture_all())
