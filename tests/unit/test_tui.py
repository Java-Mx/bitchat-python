"""Unit tests for the BitChat Textual TUI and autocomplete subsystem."""

from __future__ import annotations

import pytest
from tests.ble.mocks import MockBleakScanner, MockBLEServerBackend
from textual.widgets import RichLog, Static

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.manager import BLEManager
from bitchat.ble.models import DiscoveredPeer
from bitchat.ble.server import BLEServer
from bitchat.crypto.identity import LocalIdentity
from bitchat.tui.app import BitChatApp
from bitchat.tui.screens.help import HelpScreen
from bitchat.tui.widgets.autocomplete import AutocompletePalette
from bitchat.tui.widgets.header import HeaderWidget
from bitchat.tui.widgets.message_input import MessageInput
from bitchat.tui.widgets.sidebar import PeerSidebar
from bitchat.tui.widgets.status_bar import StatusBar


@pytest.fixture
def test_coordinator() -> SessionCoordinator:
    identity = LocalIdentity.generate()
    server = BLEServer(backend=MockBLEServerBackend())
    manager = BLEManager(
        sender_id=identity.peer_id,
        scanner_factory=lambda **kw: MockBleakScanner(
            kw["detection_callback"], kw["service_uuids"]
        ),
    )
    return SessionCoordinator(
        local_identity=identity,
        ble_manager=manager,
        ble_server=server,
        nickname="Alice",
    )


@pytest.mark.asyncio
async def test_tui_mount_and_widgets(test_coordinator: SessionCoordinator) -> None:
    """All modern TUI widgets (Header, Sidebar, Chat, Input, StatusBar)
    mount cleanly.
    """
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        assert app.query_one(HeaderWidget) is not None
        assert app.query_one(PeerSidebar) is not None
        assert app.query_one(MessageInput) is not None
        assert app.query_one(AutocompletePalette) is not None
        assert app.query_one(StatusBar) is not None

        ident_box = app.query_one("#identity-box", Static)
        assert ident_box is not None
        assert "Alice" in str(ident_box.render())

        log = app.query_one("#chat-log", RichLog)
        assert log is not None
        assert any("Welcome to BitChat" in str(line) for line in log.lines)

        await pilot.pause()


@pytest.mark.asyncio
async def test_tui_send_chat_message(test_coordinator: SessionCoordinator) -> None:
    """Sending a plain message appends it to chat and clears the input field."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        inp = app.query_one(MessageInput)
        inp.focus()
        inp.value = "Hello world from modern TUI!"
        await pilot.press("enter")
        await pilot.pause()

        assert inp.value == ""
        log = app.query_one("#chat-log", RichLog)
        assert any("Hello world from modern TUI!" in str(line) for line in log.lines)


@pytest.mark.asyncio
async def test_tui_autocomplete_popup_trigger_and_filtering(
    test_coordinator: SessionCoordinator,
) -> None:
    """Typing '/' displays suggestions; typing '/co' filters to /connect."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        inp = app.query_one(MessageInput)
        palette = app.query_one(AutocompletePalette)

        # Initially hidden
        assert palette.is_visible is False

        # Type '/'
        inp.value = "/"
        await pilot.pause()
        assert palette.is_visible is True
        assert len(palette._suggestions) >= 10

        # Type '/co'
        inp.value = "/co"
        await pilot.pause()
        assert palette.is_visible is True
        assert len(palette._suggestions) == 1
        assert palette._suggestions[0][0] == "/connect"

        # Press tab to complete
        await pilot.press("tab")
        await pilot.pause()
        assert inp.value == "/connect "
        assert palette.is_visible is False


@pytest.mark.asyncio
async def test_tui_autocomplete_escape_dismissal(
    test_coordinator: SessionCoordinator,
) -> None:
    """Pressing Escape closes the open autocomplete palette."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        inp = app.query_one(MessageInput)
        palette = app.query_one(AutocompletePalette)

        inp.value = "/"
        await pilot.pause()
        assert palette.is_visible is True

        await pilot.press("escape")
        await pilot.pause()
        assert palette.is_visible is False


@pytest.mark.asyncio
async def test_tui_autocomplete_arrow_navigation(
    test_coordinator: SessionCoordinator,
) -> None:
    """Up and Down arrow keys navigate autocomplete suggestions."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        inp = app.query_one(MessageInput)
        palette = app.query_one(AutocompletePalette)

        inp.value = "/"
        await pilot.pause()
        assert palette.is_visible is True
        assert palette.selected_index == 0

        # Down arrow
        await pilot.press("down")
        await pilot.pause()
        assert palette.selected_index == 1

        # Up arrow
        await pilot.press("up")
        await pilot.pause()
        assert palette.selected_index == 0


@pytest.mark.asyncio
async def test_tui_help_screen_and_clear_command(
    test_coordinator: SessionCoordinator,
) -> None:
    """/help pushes HelpScreen modal; /clear clears the chat log."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        inp = app.query_one(MessageInput)
        inp.value = "/help"
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, HelpScreen)

        # Dismiss modal
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)

        # Test /clear
        inp.value = "/clear"
        await pilot.press("enter")
        await pilot.pause()

        log = app.query_one("#chat-log", RichLog)
        assert len(log.lines) == 0


@pytest.mark.asyncio
async def test_tui_inbound_message_display(
    test_coordinator: SessionCoordinator,
) -> None:
    """Inbound messages from coordinator render in chat with proper badges."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        # Simulate inbound message
        app._on_coordinator_message(
            "deadbeef12345678", "Encrypted secret message", True
        )
        await pilot.pause()

        log = app.query_one("#chat-log", RichLog)
        assert any("Encrypted secret message" in str(line) for line in log.lines)
        assert any("DM" in str(line) for line in log.lines)


@pytest.mark.asyncio
async def test_tui_peer_discovery_and_status_update(
    test_coordinator: SessionCoordinator,
) -> None:
    """Discovered BLE peers and connection status update header, sidebar,
    and status bar.
    """
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        sidebar = app.query_one(PeerSidebar)
        header = app.query_one(HeaderWidget)

        # Simulate discovered peer
        peer = DiscoveredPeer(
            address="11:22:33:44:55:66",
            name="Bob-Node",
            rssi=-65,
            service_uuids=(),
        )
        test_coordinator.ble_manager.scanner._discovered_peers[peer.address] = peer
        app._refresh_peer_lists()
        await pilot.pause()

        assert "11:22:33:44:55:66" in sidebar._discovered_peers
        assert header.peer_count == 0

        # Simulate connected peer
        from unittest.mock import MagicMock

        mock_transport = MagicMock()
        mock_transport.connection.is_ready = True
        test_coordinator.ble_manager._transports["11:22:33:44:55:66"] = mock_transport
        # Set mock peer addresses
        test_coordinator.peer_addresses["deadbeef87654321"] = "11:22:33:44:55:66"
        test_coordinator.address_to_peer_id["11:22:33:44:55:66"] = "deadbeef87654321"
        test_coordinator.peer_nicknames["deadbeef87654321"] = "Bob"
        app._on_coordinator_peer_status("11:22:33:44:55:66", "Connected")
        await pilot.pause()

        log = app.query_one("#chat-log", RichLog)
        assert any("Connected" in str(line) for line in log.lines)
