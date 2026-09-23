"""Unit tests for the BitChat Textual TUI and autocomplete subsystem."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from tests.ble.mocks import MockBleakScanner, MockBLEServerBackend
from textual.widgets import Button, RichLog, Static

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.manager import BLEManager
from bitchat.ble.models import DiscoveredPeer
from bitchat.ble.server import BLEServer
from bitchat.crypto.identity import LocalIdentity
from bitchat.tui.app import BitChatApp
from bitchat.tui.screens.ble_error import BLEErrorModal
from bitchat.tui.screens.edit_theme import EditThemeModal
from bitchat.tui.screens.help import HelpScreen
from bitchat.tui.screens.peer_info import PeerInfoModal
from bitchat.tui.screens.settings import SettingsModal
from bitchat.tui.widgets.autocomplete import AutocompletePalette
from bitchat.tui.widgets.chat_view import ChatView
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


def test_tui_deterministic_identity_colors() -> None:
    """Peer identity colors are deterministic and stable across calls."""
    from bitchat.tui.theme import (
        COLOR_SELF_IDENTITY,
        PEER_IDENTITY_COLORS,
        get_peer_color,
    )

    # Identical peer produces identical color
    color_alice_1 = get_peer_color("Alice")
    color_alice_2 = get_peer_color("Alice")
    assert color_alice_1 == color_alice_2
    assert color_alice_1 in PEER_IDENTITY_COLORS

    # Local user gets self identity color
    assert get_peer_color("You") == COLOR_SELF_IDENTITY
    assert get_peer_color("self") == COLOR_SELF_IDENTITY

    # Empty identifier handled gracefully
    assert get_peer_color("") != ""


@pytest.mark.asyncio
async def test_tui_contextual_dm_autocomplete(
    test_coordinator: SessionCoordinator,
) -> None:
    """Typing '/dm ' triggers contextual peer autocomplete list."""
    test_coordinator.peer_nicknames["deadbeef12345678"] = "Bob"
    test_coordinator.peer_nicknames["cafebabe87654321"] = "Charlie"

    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        inp = app.query_one(MessageInput)
        palette = app.query_one(AutocompletePalette)

        # Type '/dm '
        inp.value = "/dm "
        await pilot.pause()
        assert palette.is_visible is True
        assert palette.border_title == "Peers (Noise XX)"
        assert len(palette._suggestions) == 2

        # Filter by 'Bo'
        inp.value = "/dm Bo"
        await pilot.pause()
        assert palette.is_visible is True
        assert len(palette._suggestions) == 1
        assert palette._suggestions[0][0] == "/dm Bob "

        # Tab complete
        await pilot.press("tab")
        await pilot.pause()
        assert inp.value == "/dm Bob "
        assert palette.is_visible is False


@pytest.mark.asyncio
async def test_tui_contextual_connect_autocomplete(
    test_coordinator: SessionCoordinator,
) -> None:
    """Typing '/connect ' triggers contextual discovered BLE peers autocomplete."""
    peer = DiscoveredPeer(
        address="AA:BB:CC:DD:EE:FF",
        name="Nearby-Node",
        rssi=-70,
        service_uuids=(),
    )
    test_coordinator.ble_manager.scanner._discovered_peers[peer.address] = peer

    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        inp = app.query_one(MessageInput)
        palette = app.query_one(AutocompletePalette)

        # Type '/connect '
        inp.value = "/connect "
        await pilot.pause()
        assert palette.is_visible is True
        assert palette.border_title == "Discovered BLE Peers"
        assert len(palette._suggestions) == 1
        assert "AA:BB:CC:DD:EE:FF" in palette._suggestions[0][0]


@pytest.mark.asyncio
async def test_tui_chat_scroll_actions(test_coordinator: SessionCoordinator) -> None:
    """PageUp and PageDown scroll chat view without errors."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        chat = app.query_one(ChatView)
        for i in range(50):
            chat.add_chat_message("Alice", f"Message number {i}", False)
        await pilot.pause()

        # Scroll actions execute without error
        app.action_scroll_chat_up()
        await pilot.pause()
        app.action_scroll_chat_down()
        await pilot.pause()
        assert len(chat.rich_log.lines) >= 50


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "width,height",
    [
        (80, 24),
        (100, 30),
        (120, 40),
        (160, 50),
    ],
)
async def test_tui_responsive_terminal_sizes(
    test_coordinator: SessionCoordinator, width: int, height: int
) -> None:
    """TUI mounts and lays out cleanly across various terminal dimensions."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test(size=(width, height)) as pilot:
        assert app.query_one(HeaderWidget) is not None
        assert app.query_one(PeerSidebar) is not None
        assert app.query_one(ChatView) is not None
        assert app.query_one(MessageInput) is not None
        assert app.query_one(StatusBar) is not None
        await pilot.pause()


@pytest.mark.asyncio
async def test_tui_action_bar_button_triggers(
    test_coordinator: SessionCoordinator,
) -> None:
    """Action bar buttons trigger settings, edit theme, help, and commands."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        # 1. Edit Theme button
        btn_edit = app.query_one("#btn-action-edit")
        await pilot.click(btn_edit)
        await pilot.pause()
        assert isinstance(app.screen, EditThemeModal)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, EditThemeModal)

        # 2. Settings button
        btn_set = app.query_one("#btn-action-settings")
        await pilot.click(btn_set)
        await pilot.pause()
        assert isinstance(app.screen, SettingsModal)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsModal)

        # 3. Help button
        btn_help = app.query_one("#btn-action-help")
        await pilot.click(btn_help)
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()

        # 4. Commands button
        btn_cmd = app.query_one("#btn-action-commands")
        await pilot.click(btn_cmd)
        await pilot.pause()
        inp = app.query_one(MessageInput)
        assert inp.value == "/"


@pytest.mark.asyncio
async def test_tui_peer_info_modal_security_and_display(
    test_coordinator: SessionCoordinator,
) -> None:
    """PeerInfoModal displays full public fingerprint and peer ID, hiding secrets."""
    mock_pid = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    mock_fp = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"

    modal = PeerInfoModal(
        nickname="Charlie",
        peer_id_hex=mock_pid,
        fingerprint=mock_fp,
        address="12:34:56:78:90:AB",
        is_connected=True,
        is_encrypted=True,
    )

    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        app.push_screen(modal)
        await pilot.pause()

        assert isinstance(app.screen, PeerInfoModal)
        # Verify public metadata is displayed in full
        static_texts = " ".join(str(s.render()) for s in app.screen.query(Static))
        assert mock_pid in static_texts
        assert mock_fp in static_texts
        assert "Charlie" in static_texts
        assert "Noise XX" in static_texts

        # Verify NO secret key material is ever shown
        assert "private_key" not in static_texts
        assert "sk" not in static_texts
        assert test_coordinator.local_identity.x25519_private.hex() not in static_texts
        assert test_coordinator.local_identity.ed25519_private.hex() not in static_texts

        # Verify close button
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, PeerInfoModal)


@pytest.mark.asyncio
async def test_tui_context_switching_and_at_syntax(
    test_coordinator: SessionCoordinator,
) -> None:
    """User can switch conversation context between #public and @peer."""
    test_coordinator.peer_nicknames["deadbeef12345678"] = "Bob"

    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        inp = app.query_one(MessageInput)
        chat = app.query_one(ChatView)
        status_bar = app.query_one(StatusBar)

        # Initially #public
        assert app.active_context == "#public"
        assert "public" in chat.channel_name

        # 1. Switch context to @Bob
        app.switch_conversation_context("Bob")
        await pilot.pause()
        assert app.active_context == "@Bob"
        assert "@Bob" in chat.channel_name
        assert "@Bob" in status_bar.channel_message

        # 2. Sending message in @Bob context routes as DM
        inp.focus()
        inp.value = "Hey Bob from context mode"
        await pilot.press("enter")
        await pilot.pause()

        log = app.query_one("#chat-log", RichLog)
        assert any(
            "to @Bob" in str(line) and "Hey Bob from context mode" in str(line)
            for line in log.lines
        )

        # 3. Switch back via /public
        inp.focus()
        inp.value = "/public"
        await pilot.press("enter")
        await pilot.pause()
        assert app.active_context == "#public"

        # 4. Direct @peer message syntax
        inp.focus()
        inp.value = "@Bob Direct message via at syntax"
        await pilot.press("enter")
        await pilot.pause()
        assert any(
            "to Bob" in str(line) and "Direct message via at syntax" in str(line)
            for line in log.lines
        )


@pytest.mark.asyncio
async def test_tui_at_autocomplete_trigger(
    test_coordinator: SessionCoordinator,
) -> None:
    """Typing '@' triggers peer suggestions with deterministic identity colors."""
    test_coordinator.peer_nicknames["deadbeef12345678"] = "Alice"
    test_coordinator.peer_nicknames["cafebabe87654321"] = "Bob"

    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        inp = app.query_one(MessageInput)
        palette = app.query_one(AutocompletePalette)

        # Type '@'
        inp.value = "@"
        await pilot.pause()
        assert palette.is_visible is True
        assert palette.border_title == "Peers (@mention / DM)"
        assert len(palette._suggestions) == 2

        # Filter by '@b'
        inp.value = "@b"
        await pilot.pause()
        assert len(palette._suggestions) == 1
        assert palette._suggestions[0][0] == "@Bob "

        # Tab complete
        await pilot.press("tab")
        await pilot.pause()
        assert inp.value == "@Bob "
        assert palette.is_visible is False


@pytest.mark.asyncio
async def test_tui_ble_truthful_state_and_error_modal(
    test_coordinator: SessionCoordinator,
) -> None:
    """When BLE fails, truthful status is shown and BLEErrorModal is presented."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        status_bar = app.query_one(StatusBar)

        # Simulate BLE hardware failure
        test_coordinator.ble_status = "unavailable"
        app._refresh_peer_lists()
        await pilot.pause()

        assert "BLE Offline" in status_bar.status_message

        # Trigger BLE error callback
        app._on_coordinator_ble_error("Bluetooth adapter disabled by user")
        await pilot.pause()

        assert isinstance(app.screen, BLEErrorModal)
        assert app.screen.error_message == "Bluetooth adapter disabled by user"
        static_texts = " ".join(str(s.render()) for s in app.screen.query(Static))
        assert "Bluetooth adapter disabled by user" in static_texts

        # Dismiss modal
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, BLEErrorModal)


@pytest.mark.asyncio
async def test_tui_phase93_footer_2_2_2_structure_and_actions(
    test_coordinator: SessionCoordinator,
) -> None:
    """Action bar has 2:2:2 button layout and all 6 buttons perform actions."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        status_bar = app.query_one(StatusBar)
        buttons = status_bar.query(Button)
        assert len(buttons) == 6

        btn_ids = [b.id for b in buttons]
        assert "btn-action-edit" in btn_ids
        assert "btn-action-settings" in btn_ids
        assert "btn-action-peers" in btn_ids
        assert "btn-action-commands" in btn_ids
        assert "btn-action-help" in btn_ids
        assert "btn-action-quit" in btn_ids

        # 1. Edit button
        await pilot.click("#btn-action-edit")
        await pilot.pause()
        assert isinstance(app.screen, EditThemeModal)
        await pilot.press("escape")
        await pilot.pause()

        # 2. Settings button
        await pilot.click("#btn-action-settings")
        await pilot.pause()
        assert isinstance(app.screen, SettingsModal)
        await pilot.press("escape")
        await pilot.pause()

        # 3. Help button
        await pilot.click("#btn-action-help")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()

        # 4. Commands button
        await pilot.click("#btn-action-commands")
        await pilot.pause()
        inp = app.query_one(MessageInput)
        assert inp.value == "/"
        assert inp.has_focus is True

        # 5. Peers button
        await pilot.click("#btn-action-peers")
        await pilot.pause()
        sidebar = app.query_one(PeerSidebar)
        assert sidebar.has_focus is True


@pytest.mark.asyncio
async def test_tui_phase93_function_keys_with_input_focused(
    test_coordinator: SessionCoordinator,
) -> None:
    """F1, F2, F3 work reliably even while MessageInput has focus."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        inp = app.query_one(MessageInput)
        inp.focus()
        assert inp.has_focus is True

        # F2 -> EditThemeModal
        await pilot.press("f2")
        await pilot.pause()
        assert isinstance(app.screen, EditThemeModal)
        await pilot.press("escape")
        await pilot.pause()

        # F3 -> SettingsModal
        inp.focus()
        await pilot.press("f3")
        await pilot.pause()
        assert isinstance(app.screen, SettingsModal)
        await pilot.press("escape")
        await pilot.pause()

        # F1 -> HelpScreen
        inp.focus()
        await pilot.press("f1")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()


@pytest.mark.asyncio
async def test_tui_phase93_help_screen_centered_close(
    test_coordinator: SessionCoordinator,
) -> None:
    """Help screen has centered bottom close button and DataTable of commands."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        await pilot.press("f1")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)

        help_screen = app.screen
        close_btn = help_screen.query_one("#help-close-btn", Button)
        assert "Close" in str(close_btn.label)

        # Click close button dismisses modal
        await pilot.click("#help-close-btn")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)


@pytest.mark.asyncio
async def test_tui_phase93_target_status_offline_awareness(
    test_coordinator: SessionCoordinator,
) -> None:
    """Target status reflects #public, @peer, and @peer • Offline truthfully."""
    test_coordinator.peer_nicknames["0123456789abcdef"] = "Alice"
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        status_bar = app.query_one(StatusBar)

        # Initial context is #public
        assert status_bar.target_status == "Target: #public"

        # Switch to Alice (not connected yet)
        app.switch_conversation_context("@Alice")
        await pilot.pause()
        assert status_bar.target_status == "Target: @Alice • Offline"

        # Connect Alice
        mock_transport = MagicMock()
        mock_transport.connection.is_ready = True
        test_coordinator.ble_manager._transports["AA:BB:CC:DD:EE:FF"] = mock_transport
        test_coordinator.address_to_peer_id["AA:BB:CC:DD:EE:FF"] = "0123456789abcdef"
        app._refresh_peer_lists()
        await pilot.pause()
        assert status_bar.target_status == "Target: @Alice"

        # Disconnect Alice
        test_coordinator.ble_manager._transports.clear()
        app._refresh_peer_lists()
        await pilot.pause()
        assert status_bar.target_status == "Target: @Alice • Offline"

        # Switch back to public
        app.switch_conversation_context("#public")
        await pilot.pause()
        assert status_bar.target_status == "Target: #public"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "width,height",
    [(80, 24), (100, 30), (120, 40), (160, 50)],
)
async def test_tui_phase93_layout_alignment_responsive(
    test_coordinator: SessionCoordinator, width: int, height: int
) -> None:
    """ChatView and MessageInput share identical horizontal boundaries across sizes."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test(size=(width, height)):
        sidebar = app.query_one(PeerSidebar)
        chat = app.query_one(ChatView)
        inp = app.query_one(MessageInput)
        status = app.query_one(StatusBar)
        header = app.query_one(HeaderWidget)

        # Horizontal alignment: chat and input must have identical x and width
        assert chat.region.x == inp.region.x
        assert chat.region.width == inp.region.width
        assert chat.region.x == sidebar.region.width

        # Full width span
        assert status.region.x == 0
        assert status.region.width == width
        assert header.region.x == 0
        assert header.region.width == width

        # Vertical continuity: no gaps between sidebar and status bar
        assert sidebar.region.y + sidebar.region.height == status.region.y
