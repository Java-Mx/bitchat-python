"""Comprehensive unit tests for BitChat M6 screens and UI/UX reconstruction."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from tests.ble.mocks import (
    MockBleakClient,
    MockBleakScanner,
    MockBLEServerBackend,
)
from textual.widgets import Button, Collapsible, DataTable, Input, Static

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.manager import BLEManager
from bitchat.ble.models import DiscoveredPeer
from bitchat.ble.server import BLEServer
from bitchat.crypto.identity import LocalIdentity
from bitchat.network.models import NetworkInfo, NetworkInterfaceInfo
from bitchat.platform.capabilities import (
    BluetoothCapabilities,
    ConfiguredTransports,
    LanCapabilities,
    SystemCapabilities,
    SystemReport,
    detect_network_info,
    format_configure_report,
)
from bitchat.storage.config import InMemoryStorage
from bitchat.transport.bluetooth import BluetoothTransport
from bitchat.tui.app import BitChatApp
from bitchat.tui.screens.ble_error import BLEErrorModal
from bitchat.tui.screens.commands import CommandsScreen
from bitchat.tui.screens.connection import ConnectionModal
from bitchat.tui.screens.edit_theme import EditThemeModal
from bitchat.tui.screens.home import HomeScreen
from bitchat.tui.screens.peer_info import PeerInfoModal
from bitchat.tui.screens.peers import PeersScreen
from bitchat.tui.screens.settings import (
    SaveStatusIndicator,
    SettingsScreen,
    UnsavedChangesModal,
)
from bitchat.tui.screens.telemetry import TelemetryScreen
from bitchat.tui.widgets.message_input import MessageInput
from bitchat.tui.widgets.status_bar import StatusBar


@pytest.fixture
def mock_coordinator() -> SessionCoordinator:
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
        nickname="Alice",
    )
    return coord


@pytest.mark.asyncio
async def test_home_screen_navigation_and_wordmark(
    mock_coordinator: SessionCoordinator,
) -> None:
    """HomeScreen renders geometric wordmark and handles arrow key navigation."""
    app = BitChatApp(coordinator=mock_coordinator, initial_screen="home")
    async with app.run_test() as pilot:
        assert isinstance(app.screen, HomeScreen)
        home = app.screen

        # Wordmark check
        wm = home.query_one("#home-wordmark", Static)
        assert "BITCHAT" not in str(wm.render())  # Block art, not plain text
        assert "█▀▀▄" in str(wm.render())

        # Initial selection is Connect (index 0)
        assert home.selected_index == 0
        connect_item = home.query_one("#nav-item-connect", Static)
        assert "> Connect" in str(connect_item.render())
        assert "selected" in connect_item.classes

        # Navigate down to Peers (index 1)
        await pilot.press("down")
        await pilot.pause()
        assert home.selected_index == 1
        peers_item = home.query_one("#nav-item-peers", Static)
        assert "> Peers" in str(peers_item.render())

        # Navigate down to Settings (index 2)
        await pilot.press("down")
        await pilot.pause()
        assert home.selected_index == 2

        # Navigate up back to Peers
        await pilot.press("up")
        await pilot.pause()
        assert home.selected_index == 1

        # Direct number selection: '1' for Connect
        await pilot.press("1")
        await pilot.pause()
        assert isinstance(app.screen, ConnectionModal)
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.asyncio
async def test_connection_modal_offline_mode(
    mock_coordinator: SessionCoordinator,
) -> None:
    """ConnectionModal supports arrow navigation and offline mode transition."""
    app = BitChatApp(coordinator=mock_coordinator, initial_screen="home")
    async with app.run_test() as pilot:
        assert isinstance(app.screen, HomeScreen)

        # Press enter on Connect to open ConnectionModal
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ConnectionModal)
        modal = app.screen

        # Navigate to Offline Mode (index 2)
        await pilot.press("down")
        await pilot.press("down")
        await pilot.pause()
        assert modal.selected_index == 2

        # Enter offline mode
        await pilot.press("enter")
        await pilot.pause()

        # Modal dismissed and transition into main app (chat) completed
        assert not isinstance(app.screen, ConnectionModal)
        assert not isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_connection_modal_ble_init(mock_coordinator: SessionCoordinator) -> None:
    """ConnectionModal attempts real BLE transport startup and handles errors."""
    app = BitChatApp(coordinator=mock_coordinator, initial_screen="home")
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ConnectionModal)

        # Press 1 for BLE
        with patch.object(
            mock_coordinator, "switch_transport", new_callable=AsyncMock
        ) as mock_switch:
            mock_switch.return_value = (True, "Switched")
            await pilot.press("1")
            await pilot.pause()
            assert not isinstance(app.screen, ConnectionModal)


@pytest.mark.asyncio
async def test_home_screen_open_peers_and_commands(
    mock_coordinator: SessionCoordinator,
) -> None:
    """Dedicated Peers and Commands screens open and dismiss via Esc."""
    app = BitChatApp(coordinator=mock_coordinator, initial_screen="home")
    async with app.run_test() as pilot:
        # Open Peers via 'p'
        await pilot.press("p")
        await pilot.pause()
        assert isinstance(app.screen, PeersScreen)
        peers_screen = app.screen
        table = peers_screen.query_one("#peers-table", DataTable)
        assert len(table.columns) == 6

        # Return via escape
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)

        # Open Commands via 'd'
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, CommandsScreen)
        commands_screen = app.screen
        cmd_table = commands_screen.query_one("#commands-table", DataTable)
        assert len(cmd_table.rows) > 10

        # Return via escape
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_home_screen_retry_ble(mock_coordinator: SessionCoordinator) -> None:
    """Pressing 'r' on HomeScreen invokes coordinator.retry_ble() and shows loading state."""
    app = BitChatApp(coordinator=mock_coordinator, initial_screen="home")
    async with app.run_test() as pilot:
        home = app.screen
        assert isinstance(home, HomeScreen)

        with patch.object(
            mock_coordinator, "retry_ble", new_callable=AsyncMock
        ) as mock_retry:
            await pilot.press("r")
            await pilot.pause()
            assert mock_retry.called


@pytest.mark.asyncio
async def test_settings_screen_save_indicator_and_unsaved_modal(
    mock_coordinator: SessionCoordinator,
) -> None:
    """SettingsScreen dedicated save indicator transitions from saved to unsaved, prompting modal on escape."""
    app = BitChatApp(coordinator=mock_coordinator, initial_screen="chat")
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.press("f3")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)
        settings = app.screen

        # Initial mount: indicator is saved
        indicator = settings.query_one(SaveStatusIndicator)
        assert "ALL CHANGES SAVED" in str(indicator.render())
        assert not settings.has_unsaved_changes

        # Switch to appearance category
        await pilot.click("#btn-cat-appearance")
        await pilot.pause()
        assert settings.active_category == "appearance"

        # Switch back to general and modify nickname
        await pilot.click("#btn-cat-general")
        await pilot.pause()
        nick_input = settings.query_one("#settings-input-nickname", Input)
        nick_input.value = "NewNick"
        await pilot.pause()

        # Indicator transitions to unsaved
        assert settings.has_unsaved_changes
        assert "UNSAVED CHANGES" in str(indicator.render())

        # Pressing escape prompts UnsavedChangesModal
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, UnsavedChangesModal)

        # Click stay and edit
        await pilot.click("#btn-unsaved-stay")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)

        # Press escape again and click discard
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, UnsavedChangesModal)
        await pilot.click("#btn-unsaved-discard")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsScreen)


@pytest.mark.asyncio
async def test_peers_screen_self_filtering(
    mock_coordinator: SessionCoordinator,
) -> None:
    """PeersScreen strictly filters out the local node from discovery and connection tables."""
    # Inject local node identity as a discovered peer on the scanner
    local_pid = mock_coordinator.local_identity.peer_id_hex
    peer_self = DiscoveredPeer(
        address="AA:BB:CC:DD:EE:FF",
        name="Alice",
        rssi=-50,
        peer_id=local_pid,
        nickname="Alice",
    )
    peer_bob = DiscoveredPeer(
        address="11:22:33:44:55:66",
        name="Bob",
        rssi=-60,
        peer_id="bob-peer-id-12345",
        nickname="Bob",
    )
    mock_coordinator.ble_manager.scanner._discovered_peers = {
        "AA:BB:CC:DD:EE:FF": peer_self,
        "11:22:33:44:55:66": peer_bob,
    }

    app = BitChatApp(coordinator=mock_coordinator, initial_screen="chat")
    async with app.run_test() as pilot:
        app.action_open_peers()
        await pilot.pause()
        assert isinstance(app.screen, PeersScreen)
        peers_screen = app.screen
        table = peers_screen.query_one("#peers-table", DataTable)

        # The local node (Alice) must NOT appear in the table; only Bob should appear
        row_names = [table.get_row_at(i)[0] for i in range(len(table.rows))]
        assert "Bob" in row_names
        assert "Alice" not in row_names


@pytest.mark.asyncio
async def test_configure_command_dispatches_to_settings(
    mock_coordinator: SessionCoordinator,
) -> None:
    """Typing /configure [category] opens SettingsScreen directly to that category."""
    app = BitChatApp(coordinator=mock_coordinator, initial_screen="chat")
    async with app.run_test(size=(120, 45)) as pilot:
        inp = app.query_one(MessageInput)
        inp.value = "/configure bluetooth"
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)
        assert app.screen.active_category == "bluetooth"


@pytest.mark.parametrize("terminal_size", [(120, 45), (80, 24)])
@pytest.mark.asyncio
async def test_settings_dialog_is_centered_at_multiple_terminal_sizes(
    mock_coordinator: SessionCoordinator,
    terminal_size: tuple[int, int],
) -> None:
    """The modal stays centered within both normal and compact viewports."""
    app = BitChatApp(coordinator=mock_coordinator, initial_screen="chat")
    async with app.run_test(size=terminal_size) as pilot:
        app.action_open_settings()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        dialog = screen.query_one("#settings-dialog")
        viewport = app.size
        assert abs((dialog.region.x * 2 + dialog.region.width) - viewport.width) <= 1
        assert abs((dialog.region.y * 2 + dialog.region.height) - viewport.height) <= 1
        assert screen.query_one("#settings-category-nav").region.x < (
            screen.query_one("#settings-form").region.x
        )
        assert screen.query_one("#btn-cat-general", Button).styles.text_align == "left"
        action_buttons = list(screen.query("#settings-actions-left Button"))
        assert len({button.size.width for button in action_buttons}) == 1


@pytest.mark.asyncio
async def test_peers_footer_input_and_buttons_fit_wide_and_narrow_terminals(
    mock_coordinator: SessionCoordinator,
) -> None:
    """Peer entry remains visible and action buttons balance at both widths."""
    for terminal_size in ((160, 40), (80, 24)):
        app = BitChatApp(coordinator=mock_coordinator, initial_screen="home")
        async with app.run_test(size=terminal_size) as pilot:
            peers = PeersScreen()
            app.push_screen(peers)
            await pilot.pause()

            footer = peers.query_one("#peers-action-bar")
            peer_input = peers.query_one("#peer-connect-input", Input)
            grid = peers.query_one("#peers-footer-buttons")
            buttons = list(peers.query("#peers-footer-buttons Button"))
            assert len(buttons) == 5
            assert peer_input.region.height == 3
            assert "Enter peer address or ID" in str(peer_input.placeholder)
            assert peer_input.region.y >= footer.region.y
            assert peer_input.region.bottom <= footer.region.bottom
            col1_col2 = [b for b in buttons if b.id != "btn-peers-back"]
            col3 = [b for b in buttons if b.id == "btn-peers-back"]
            assert len({b.size.width for b in col1_col2}) == 1
            assert col3[0].size.width == col1_col2[0].size.width
            assert all(button.region.right <= app.size.width for button in buttons)

            if terminal_size[0] < 120:
                assert footer.has_class("compact-footer")
                assert peer_input.region.width > 50
                assert peer_input.region.bottom <= grid.region.y
            else:
                assert not footer.has_class("compact-footer")
                assert peer_input.region.width >= 24
                assert peer_input.region.width > 50
                assert peer_input.region.right <= grid.region.x

            peer_input.focus()
            await pilot.press("p", "e", "e", "r")
            assert peer_input.value == "peer"
            assert peer_input.has_focus

            if terminal_size[0] >= 120:
                await pilot.resize_terminal(80, 24)
                await pilot.pause()
                assert footer.has_class("compact-footer")
                col1_col2_narrow = [b for b in buttons if b.id != "btn-peers-back"]
                col3_narrow = [b for b in buttons if b.id == "btn-peers-back"]
                assert len({b.size.width for b in col1_col2_narrow}) == 1
                assert col3_narrow[0].size.width == col1_col2_narrow[0].size.width

                await pilot.resize_terminal(160, 40)
                await pilot.pause()
                assert not footer.has_class("compact-footer")
                assert peer_input.region.width >= 24
                assert peer_input.region.width > 50
                assert peer_input.has_focus


@pytest.mark.asyncio
async def test_dialog_footer_groups_use_equal_width_centered_buttons(
    mock_coordinator: SessionCoordinator,
) -> None:
    """Two- and three-action modal footers use compact 1:1/equal grids."""
    app = BitChatApp(coordinator=mock_coordinator, initial_screen="home")
    dialog_cases = [
        (EditThemeModal(), "#edit-theme-actions", "#edit-theme-footer-buttons"),
        (
            PeerInfoModal("Peer", "peer-id"),
            "#peer-info-actions",
            "#peer-info-footer-buttons",
        ),
        (
            UnsavedChangesModal(),
            "#unsaved-actions",
            "#unsaved-footer-buttons",
        ),
        (
            BLEErrorModal(
                "GATT failed",
                bluetooth_available=True,
                central_active=True,
                peripheral_failure=True,
                lan_available=True,
            ),
            "#ble-error-actions",
            "#ble-error-buttons",
        ),
    ]
    async with app.run_test(size=(120, 40)) as pilot:
        for dialog, actions_selector, grid_selector in dialog_cases:
            app.push_screen(dialog)
            await pilot.pause()
            actions = dialog.query_one(actions_selector)
            grid = dialog.query_one(grid_selector)
            buttons = list(grid.query(Button))
            assert len(buttons) in (2, 3)
            assert len({button.size.width for button in buttons}) == 1
            assert all(button.size.height == 1 for button in buttons)
            assert all(button.styles.text_align == "center" for button in buttons)
            if isinstance(dialog, BLEErrorModal) and len(buttons) == 3:
                lan_button = dialog.query_one("#btn-ble-lan", Button)
                assert lan_button.size.width >= len("Continue Wi-Fi/LAN") + 2
                assert "Continue Wi-Fi/LAN" in str(lan_button.render())
            assert (
                abs(
                    2 * actions.region.x
                    + actions.region.width
                    - (2 * grid.region.x + grid.region.width)
                )
                <= 1
            )
            app.pop_screen()
            await pilot.pause()


@pytest.mark.asyncio
async def test_footer_groups_use_equal_width_button_grids(
    mock_coordinator: SessionCoordinator,
) -> None:
    """Visible footer buttons use equal-width, single-row shared styling."""
    app = BitChatApp(coordinator=mock_coordinator, initial_screen="home")
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(CommandsScreen())
        await pilot.pause()
        commands = app.screen
        assert isinstance(commands, CommandsScreen)
        command_bar = commands.query_one("#commands-action-bar")
        command_buttons = list(commands.query("#commands-action-bar Button"))
        assert len(command_buttons) == 2
        assert all(button.has_class("action-btn") for button in command_buttons)

        command_sizes = [
            (button.size.width, button.size.height) for button in command_buttons
        ]
        assert all(height == 1 for _, height in command_sizes)
        assert all(width < command_bar.size.width for width, _ in command_sizes)
        assert command_sizes[0][0] == command_sizes[1][0]
        command_grid = commands.query_one("#commands-footer-buttons")
        assert command_grid.region.right <= command_bar.region.right
        assert command_bar.region.right - command_grid.region.right <= 2

        status_buttons = list(app.query_one(StatusBar).query(Button))
        status_grid = app.query_one("#status-actions-grid")
        assert len(status_buttons) == 6
        assert all(button.size.height == 1 for button in status_buttons)
        assert all(
            button.size.width < status_grid.size.width for button in status_buttons
        )
        assert len({button.size.width for button in status_buttons}) == 1

        app.push_screen(TelemetryScreen())
        await pilot.pause()
        telemetry = app.screen
        assert isinstance(telemetry, TelemetryScreen)
        telemetry_bar = telemetry.query_one("#telemetry-action-bar")
        telemetry_buttons = list(telemetry.query("#telemetry-action-bar Button"))
        assert len(telemetry_buttons) == 4
        telemetry_sizes = [
            (button.size.width, button.size.height) for button in telemetry_buttons
        ]
        assert all(height == 1 for _, height in telemetry_sizes)
        assert all(width < telemetry_bar.size.width for width, _ in telemetry_sizes)
        assert len({width for width, _ in telemetry_sizes}) == 1
        telemetry_grid = telemetry.query_one("#telemetry-footer-buttons")
        assert telemetry_bar.region.right - telemetry_grid.region.right <= 2

        # The selected state remains a visible, functional Textual focus state.
        telemetry_buttons[0].focus()
        await pilot.pause()
        assert telemetry.focused is telemetry_buttons[0]


@pytest.mark.asyncio
async def test_telemetry_warning_label_has_monochrome_spacing(
    mock_coordinator: SessionCoordinator,
) -> None:
    """Warning rendering separates the plain-text symbol from its label."""
    app = BitChatApp(coordinator=mock_coordinator, initial_screen="home")
    async with app.run_test(size=(100, 30)) as pilot:
        mock_coordinator.ble_error_message = "GATT advertising failed"
        bluetooth = mock_coordinator._transports["bluetooth"]
        assert isinstance(bluetooth, BluetoothTransport)
        bluetooth._peripheral_error_message = "GATT advertising failed"
        telemetry = TelemetryScreen()
        app.push_screen(telemetry)
        await pilot.pause()
        telemetry.refresh_status()

        rendered = str(telemetry.query_one("#telem-ble-error", Static).render())
        assert "[!] Last BLE Diagnostic:" in rendered
        summary = str(telemetry.query_one("#telem-diagnostic-summary", Static).render())
        assert "Bluetooth peripheral unavailable" in summary
        assert "still scan" in summary
        assert "GATT advertising failed" in rendered


@pytest.mark.asyncio
async def test_telemetry_screen_navigation_and_sections(
    mock_coordinator: SessionCoordinator,
) -> None:
    """HomeScreen menu opens TelemetryScreen presenting Bluetooth, LAN, Identity, and App."""
    app = BitChatApp(coordinator=mock_coordinator, initial_screen="home")
    async with app.run_test() as pilot:
        assert isinstance(app.screen, HomeScreen)

        # Press 't' to open TelemetryScreen
        await pilot.press("t")
        await pilot.pause()
        assert isinstance(app.screen, TelemetryScreen)
        telem = app.screen

        # Verify all 4 sections are present
        assert telem.query_one("#card-telemetry-ble") is not None
        assert telem.query_one("#card-telemetry-lan") is not None
        assert telem.query_one("#card-telemetry-ident") is not None
        assert telem.query_one("#card-telemetry-app") is not None
        assert telem.query_one("#telem-summary-network-connection") is not None
        assert telem.query_one("#telem-summary-lan") is not None
        assert telem.query_one("#details-telemetry-ble", Collapsible).collapsed

        # Verify refresh and buttons
        await pilot.click("#btn-telem-refresh")
        await pilot.pause()

        # Return via escape
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_telemetry_shows_configure_network_details_without_expanding(
    mock_coordinator: SessionCoordinator,
) -> None:
    snapshot = NetworkInfo(
        status="Connected",
        interface="Wi-Fi",
        ssid="Example Wi-Fi",
        interface_name="wlan0",
        interface_state="Up",
        ipv4_addresses=("192.0.2.10",),
        ipv6_addresses=("2001:db8::10",),
        subnet_prefixes=(24, 64),
        default_gateway="192.0.2.1",
        dns_servers=("192.0.2.53",),
        default_route_interface="wlan0",
        connection_name="Example profile",
        interface_description="Wireless Adapter",
        interface_id="wlan0-guid",
        signal_strength_percent=82,
        interfaces=(
            NetworkInterfaceInfo(
                name="wlan0",
                description="Wireless Adapter",
                kind="Wi-Fi",
                operational_state="Up",
                ipv4_addresses=("192.0.2.10",),
                ipv6_addresses=("2001:db8::10",),
                subnet_prefixes=(24, 64),
                gateways=("192.0.2.1",),
                dns_servers=("192.0.2.53",),
                ssid="Example Wi-Fi",
                connection_name="Example profile",
                interface_id="wlan0-guid",
                signal_strength_percent=82,
                default_route=True,
            ),
            NetworkInterfaceInfo(
                name="vboxnet0",
                description="VirtualBox Host-Only Ethernet Adapter",
                kind="Ethernet",
                operational_state="Up",
                ipv4_addresses=("198.51.100.1",),
            ),
        ),
    )
    app = BitChatApp(coordinator=mock_coordinator, initial_screen="home")
    with patch(
        "bitchat.tui.screens.telemetry.get_network_info_snapshot",
        new=AsyncMock(return_value=snapshot),
    ):
        async with app.run_test(size=(110, 40)) as pilot:
            telemetry = TelemetryScreen()
            app.push_screen(telemetry)
            await pilot.pause()
            telemetry._network_info = snapshot
            telemetry.refresh_status()

            assert telemetry.query_one(
                "#details-telemetry-network", Collapsible
            ).collapsed
            expected = {
                "#telem-os-status": "Connected",
                "#telem-os-connection": "Example profile",
                "#telem-os-type": "Wi-Fi",
                "#telem-os-interface": "wlan0",
                "#telem-os-adapter": "Wireless Adapter",
                "#telem-os-profile": "Example profile",
                "#telem-os-ssid": "Example Wi-Fi",
                "#telem-os-ipv4": "192.0.2.10",
                "#telem-os-ipv6": "2001:db8::10",
                "#telem-os-subnet": "24, 64",
                "#telem-os-gateway": "192.0.2.1",
                "#telem-os-dns": "192.0.2.53",
                "#telem-os-signal": "82%",
                "#telem-os-other-interfaces": ("vboxnet0 (Ethernet, Up): 198.51.100.1"),
            }
            for selector, value in expected.items():
                widget = telemetry.query_one(selector, Static)
                assert value in str(widget.render())
                assert widget.display
            assert telemetry.query_one("#telem-os-status", Static).display

            report = SystemReport(
                system=SystemCapabilities(
                    "Windows", "Windows 11", "x86_64", "CPython 3.12"
                ),
                bluetooth=BluetoothCapabilities(
                    "Available", "Available", "Available", "Available", "n/a", "Granted"
                ),
                network=detect_network_info(snapshot),
                lan=LanCapabilities("Available", "Available"),
                configuration=ConfiguredTransports(
                    "Enabled", "Enabled", "Enabled", "System ready.", "lan"
                ),
                network_snapshot=snapshot,
            )
            configure_output = format_configure_report(report)
            for value in (
                "Example profile",
                "Wi-Fi",
                "wlan0",
                "Wireless Adapter",
                "wlan0-guid",
                "Example Wi-Fi",
                "192.0.2.10",
                "2001:db8::10",
                "24, 64",
                "192.0.2.1",
                "192.0.2.53",
                "82%",
                "vboxnet0 (Ethernet, Up): 198.51.100.1",
            ):
                assert value in configure_output
