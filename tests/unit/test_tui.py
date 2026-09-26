"""Unit tests for the BitChat Textual TUI and autocomplete subsystem."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from tests.ble.mocks import MockBleakScanner, MockBLEServerBackend
from textual.widgets import Button, Input, RadioButton, RichLog, Static

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.manager import BLEManager
from bitchat.ble.models import DiscoveredPeer
from bitchat.ble.server import BLEServer
from bitchat.crypto.identity import LocalIdentity
from bitchat.storage.config import AppConfig, InMemoryStorage
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
    storage = InMemoryStorage()
    return SessionCoordinator(
        local_identity=identity,
        ble_manager=manager,
        ble_server=server,
        storage=storage,
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
async def test_tui_lan_status_uses_real_network_values_only(
    test_coordinator: SessionCoordinator,
) -> None:
    """LAN diagnostics must never default to localhost or synthetic loopback values."""
    app = BitChatApp(coordinator=test_coordinator)
    test_coordinator.active_transport_name = "lan"
    test_coordinator.ble_status = "scanning"
    test_coordinator.get_detailed_status = lambda: {
        "transport": "lan",
        "state": "scanning",
        "interface": "Wi-Fi",
        "ssid": "OfficeNet",
        "local_ip": "",
        "listening_port": 41235,
        "discovery": "Active",
        "discovered_peers_count": 0,
        "connected_peers_count": 0,
        "local_nickname": "Alice",
        "local_peer_id": "01" * 8,
    }

    async with app.run_test() as pilot:
        chat = app.query_one(ChatView)
        app._display_status_diagnostics(chat)
        await pilot.pause()
        rendered = "\n".join(str(line) for line in chat.rich_log.lines)
        assert "127.0.0.1" not in rendered
        assert "unavailable" in rendered.lower()
        assert "OfficeNet" in rendered


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


@pytest.mark.asyncio
async def test_tui_appearance_density_real_effect_and_history_rerender(
    test_coordinator: SessionCoordinator,
) -> None:
    """Toggling density updates CSS class, chat layout, and re-renders history."""
    storage = InMemoryStorage()
    app = BitChatApp(coordinator=test_coordinator, storage=storage)
    async with app.run_test(size=(120, 45)) as pilot:
        chat = app.query_one(ChatView)
        assert app.has_class("density-comfortable")
        assert chat.compact_mode is False

        # Add messages in comfortable mode
        chat.add_chat_message("Bob", "Hello comfortable world", is_encrypted=False)
        chat.add_system_message("Mesh routing initialized")
        await pilot.pause()

        # Open theme modal
        await pilot.press("f2")
        await pilot.pause()
        assert isinstance(app.screen, EditThemeModal)

        # Switch to Compact and apply
        await pilot.click("#rb-density-comp")
        await pilot.click("#btn-theme-apply")
        await pilot.pause()

        # Modal is closed, app root has density-compact class
        assert not isinstance(app.screen, EditThemeModal)
        assert app.has_class("density-compact")
        assert not app.has_class("density-comfortable")
        assert chat.compact_mode is True
        assert storage.load_config().density == "compact"

        rendered_lines = [str(line) for line in chat.rich_log.lines]
        log_content = " ".join(rendered_lines)
        assert "Hello comfortable world" in log_content

        # Switch back to Comfortable
        await pilot.press("f2")
        await pilot.pause()
        await pilot.click("#rb-density-comf")
        await pilot.click("#btn-theme-apply")
        await pilot.pause()

        assert app.has_class("density-comfortable")
        assert not app.has_class("density-compact")
        assert chat.compact_mode is False
        assert storage.load_config().density == "comfortable"


@pytest.mark.asyncio
async def test_tui_appearance_timestamps_real_toggle_and_rerender(
    test_coordinator: SessionCoordinator,
) -> None:
    """Disabling timestamps completely hides them from both past and future messages."""
    storage = InMemoryStorage()
    app = BitChatApp(coordinator=test_coordinator, storage=storage)
    async with app.run_test(size=(120, 45)) as pilot:
        chat = app.query_one(ChatView)
        assert chat.show_timestamps is True

        chat.add_chat_message("Charlie", "Test timestamp message", is_encrypted=False)
        await pilot.pause()

        # Open theme modal and select Hide Timestamps
        await pilot.press("f2")
        await pilot.pause()
        await pilot.click("#rb-ts-hide")
        await pilot.click("#btn-theme-apply")
        await pilot.pause()

        assert chat.show_timestamps is False
        assert storage.load_config().show_timestamps is False

        # Verify timestamp bullet is absent from re-rendered log
        rendered_lines = [str(line) for line in chat.rich_log.lines]
        for line in rendered_lines:
            if "Test timestamp message" in line:
                assert "•" not in line


@pytest.mark.asyncio
async def test_tui_appearance_accent_tone_propagation(
    test_coordinator: SessionCoordinator,
) -> None:
    """Selecting an accent tone propagates root CSS class and updates stored config."""
    storage = InMemoryStorage()
    app = BitChatApp(coordinator=test_coordinator, storage=storage)
    async with app.run_test(size=(120, 45)) as pilot:
        assert app.has_class("accent-blue")

        # Switch to Emerald
        await pilot.press("f2")
        await pilot.pause()
        await pilot.click("#rb-accent-emerald")
        await pilot.click("#btn-theme-apply")
        await pilot.pause()

        assert app.has_class("accent-emerald")
        assert not app.has_class("accent-blue")
        assert storage.load_config().accent == "emerald"

        # Switch to Purple
        await pilot.press("f2")
        await pilot.pause()
        await pilot.click("#rb-accent-purple")
        await pilot.click("#btn-theme-apply")
        await pilot.pause()

        assert app.has_class("accent-purple")
        assert not app.has_class("accent-emerald")
        assert storage.load_config().accent == "purple"


@pytest.mark.asyncio
async def test_tui_appearance_persistence_across_app_restarts(
    test_coordinator: SessionCoordinator,
) -> None:
    """Applied theme and appearance preferences survive application restart."""
    storage = InMemoryStorage()

    # Session 1: customize theme
    app1 = BitChatApp(coordinator=test_coordinator, storage=storage)
    async with app1.run_test(size=(120, 45)) as pilot:
        await pilot.press("f2")
        await pilot.pause()
        await pilot.click("#rb-density-comp")
        await pilot.click("#rb-ts-hide")
        await pilot.click("#rb-accent-cyan")
        await pilot.click("#btn-theme-apply")
        await pilot.pause()

    # Verify storage has all 3 updated settings
    cfg = storage.load_config()
    assert cfg.density == "compact"
    assert cfg.show_timestamps is False
    assert cfg.accent == "cyan"

    # Session 2: launch fresh BitChatApp with same storage
    app2 = BitChatApp(coordinator=test_coordinator, storage=storage)
    async with app2.run_test(size=(120, 45)) as pilot:
        chat = app2.query_one(ChatView)
        assert app2.current_density == "compact"
        assert app2.current_show_timestamps is False
        assert app2.current_accent == "cyan"
        assert app2.has_class("density-compact")
        assert app2.has_class("accent-cyan")
        assert chat.compact_mode is True
        assert chat.show_timestamps is False


@pytest.mark.asyncio
async def test_tui_appearance_discard_unapplied_changes_on_close(
    test_coordinator: SessionCoordinator,
) -> None:
    """Closing or pressing Escape discards unapplied edits without saving."""
    storage = InMemoryStorage(AppConfig(density="comfortable", accent="blue"))
    app = BitChatApp(coordinator=test_coordinator, storage=storage)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.press("f2")
        await pilot.pause()
        assert isinstance(app.screen, EditThemeModal)

        # Select different options but do NOT click Apply
        await pilot.click("#rb-density-comp")
        await pilot.click("#rb-accent-emerald")
        await pilot.click("#btn-theme-close")
        await pilot.pause()

        assert not isinstance(app.screen, EditThemeModal)
        assert app.has_class("density-comfortable")
        assert app.has_class("accent-blue")
        assert storage.load_config().density == "comfortable"
        assert storage.load_config().accent == "blue"


@pytest.mark.asyncio
async def test_tui_settings_modal_save_and_persistence(
    test_coordinator: SessionCoordinator,
) -> None:
    """Settings modal saves parameters, updates coordinator, and persists."""
    storage = InMemoryStorage()
    app = BitChatApp(coordinator=test_coordinator, storage=storage)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.press("f3")
        await pilot.pause()
        assert isinstance(app.screen, SettingsModal)

        settings_screen = app.screen
        settings_screen.query_one("#settings-input-nickname", Input).value = "Commander"
        settings_screen.query_one("#settings-input-hops", Input).value = "5"
        settings_screen.query_one("#settings-input-delay", Input).value = "50"

        await pilot.click("#btn-settings-save")
        await pilot.pause()

        assert not isinstance(app.screen, SettingsModal)
        assert test_coordinator.nickname == "Commander"
        assert test_coordinator.mesh_router.max_relay_ttl == 5
        assert test_coordinator.inter_fragment_delay == 0.05

        cfg = storage.load_config()
        assert cfg.nickname == "Commander"
        assert cfg.max_hops == 5
        assert cfg.inter_fragment_delay_ms == 50

        # Verify UI reflects new nickname
        header = app.query_one(HeaderWidget)
        sidebar = app.query_one(PeerSidebar)
        assert header.nickname == "Commander"
        assert sidebar.nickname == "Commander"


@pytest.mark.asyncio
async def test_phase10_keybinding_customization_and_authoritative_rebinding(
    test_coordinator: SessionCoordinator,
) -> None:
    """Keybinding re-assignment updates authoritative key dispatch and persists."""
    storage = InMemoryStorage()
    app = BitChatApp(coordinator=test_coordinator, storage=storage)
    async with app.run_test(size=(120, 45)) as pilot:
        # Initial: F1 opens help
        await pilot.press("f1")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)

        # Open settings to rebind Help to F4
        await pilot.press("f3")
        await pilot.pause()
        assert isinstance(app.screen, SettingsModal)
        settings_modal = app.screen
        settings_modal.query_one("#settings-kb-help", Input).value = "f4"
        await pilot.click("#btn-settings-save")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsModal)

        # Verification: F4 now opens help; F1 no longer opens help
        await pilot.press("f4")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()

        await pilot.press("f1")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)

        # Persistence verification: reload into fresh app instance
        cfg = storage.load_config()
        assert cfg.keybindings["help"] == "f4"

    fresh_app = BitChatApp(coordinator=test_coordinator, storage=storage)
    async with fresh_app.run_test(size=(120, 45)) as pilot:
        await pilot.press("f4")
        await pilot.pause()
        assert isinstance(fresh_app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()

        await pilot.press("f1")
        await pilot.pause()
        assert not isinstance(fresh_app.screen, HelpScreen)


@pytest.mark.asyncio
async def test_phase10_keybinding_conflict_detection_and_validation(
    test_coordinator: SessionCoordinator,
) -> None:
    """Duplicate keys or empty key inputs are caught and block saving."""
    storage = InMemoryStorage()
    app = BitChatApp(coordinator=test_coordinator, storage=storage)
    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.press("f3")
        await pilot.pause()
        assert isinstance(app.screen, SettingsModal)
        settings_modal = app.screen

        # Test duplicate key conflict: assign f2 to help (edit_theme already has f2)
        settings_modal.query_one("#settings-kb-help", Input).value = "f2"
        await pilot.click("#btn-settings-save")
        await pilot.pause()
        assert isinstance(app.screen, SettingsModal)
        hint = settings_modal.query_one("#settings-hint", Static)
        assert "conflict" in str(hint.render()).lower()

        # Test empty key input
        settings_modal.query_one("#settings-kb-help", Input).value = ""
        await pilot.click("#btn-settings-save")
        await pilot.pause()
        assert isinstance(app.screen, SettingsModal)
        assert "cannot be empty" in str(hint.render()).lower()

        # Test restore defaults
        await pilot.click("#btn-settings-restore-defaults")
        await pilot.pause()
        assert settings_modal.query_one("#settings-kb-help", Input).value == "f1"
        assert settings_modal.query_one("#settings-kb-settings", Input).value == "f3"


@pytest.mark.asyncio
async def test_phase10_modal_no_duplicate_stacking_and_toggle(
    test_coordinator: SessionCoordinator,
) -> None:
    """Pressing active modal key toggles off; opening another modal pops previous."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test(size=(120, 45)) as pilot:
        # F1 opens HelpScreen
        await pilot.press("f1")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)

        # F1 again toggles HelpScreen off
        await pilot.press("f1")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)

        # F2 opens EditThemeModal
        await pilot.press("f2")
        await pilot.pause()
        assert isinstance(app.screen, EditThemeModal)

        # Pressing F3 on EditThemeModal replaces it with SettingsModal without stacking
        await pilot.press("f3")
        await pilot.pause()
        assert isinstance(app.screen, SettingsModal)
        # Stack should only have root and SettingsModal (len == 2)
        assert len(app._screen_stack) == 2

        # BLE Error modal does not duplicate
        app._on_coordinator_ble_error("BLE Hardware Disconnected")
        await pilot.pause()
        assert isinstance(app.screen, BLEErrorModal)
        app._on_coordinator_ble_error("BLE Repeated Failure")
        await pilot.pause()
        ble_modals = [s for s in app._screen_stack if isinstance(s, BLEErrorModal)]
        assert len(ble_modals) == 1


@pytest.mark.asyncio
async def test_phase10_direct_messaging_and_context_switching(
    test_coordinator: SessionCoordinator,
) -> None:
    """@peer syntax handles both conversation switching and direct messaging."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test(size=(120, 45)) as pilot:
        inp = app.query_one(MessageInput)

        # 1. @Bob context switch
        inp.value = "@Bob"
        await inp.action_submit()
        await pilot.pause()
        assert app.active_context == "@Bob"
        chat = app.query_one(ChatView)
        assert any(
            "Switched conversation context to @Bob" in m.text
            for m in chat._message_history
        )

        # 2. @Alice hello direct message
        test_coordinator.peer_nicknames["cafebabe12345678"] = "Alice"
        inp.value = "@Alice How are you?"
        await inp.action_submit()
        await pilot.pause()
        assert any("to Alice" in m.text for m in chat._message_history)

        # 3. Return to #public
        inp.value = "/public"
        await inp.action_submit()
        await pilot.pause()
        assert app.active_context == "#public"


@pytest.mark.asyncio
async def test_phase10_connect_command_peer_resolution_and_discovery(
    test_coordinator: SessionCoordinator,
) -> None:
    """/connect without args shows peers; with peer name resolves to address."""
    # Add a mock discovered peer to ble_manager scanner
    test_coordinator.ble_manager.scanner._discovered_peers["11:22:33:44:55:66"] = (
        DiscoveredPeer(
            address="11:22:33:44:55:66",
            name="BitChat-Remote",
            rssi=-65,
        )
    )
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test(size=(120, 45)) as pilot:
        inp = app.query_one(MessageInput)
        chat = app.query_one(ChatView)

        # /connect without args lists discovered peers
        inp.value = "/connect"
        await inp.action_submit()
        await pilot.pause()
        assert any("11:22:33:44:55:66" in m.text for m in chat._message_history)
        assert any("BitChat-Remote" in m.text for m in chat._message_history)

        # /connect BitChat-Remote resolves name to address
        inp.value = "/connect BitChat-Remote"
        await inp.action_submit()
        await pilot.pause()
        assert any(
            "Connecting to peer at 11:22:33:44:55:66 (BitChat-Remote)" in m.text
            for m in chat._message_history
        )


@pytest.mark.asyncio
async def test_phase11_settings_transport_selection_and_switch(
    test_coordinator: SessionCoordinator,
) -> None:
    """Settings modal transport selection switches coordinator transport
    and updates sidebar.
    """
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test(size=(120, 45)) as pilot:
        sidebar = app.query_one(PeerSidebar)
        assert "BLE Mesh" in sidebar.border_title
        assert test_coordinator.active_transport_name == "bluetooth"

        # 1. Open settings modal
        await pilot.press("f3")
        await pilot.pause()
        assert isinstance(app.screen, SettingsModal)
        settings_modal = app.screen

        # Select LAN transport
        lan_radio = settings_modal.query_one("#radio-transport-lan", RadioButton)
        lan_radio.value = True
        await pilot.click("#btn-settings-save")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsModal)

        # Verify switched to LAN
        assert test_coordinator.active_transport_name == "lan"
        assert "LAN / Wi-Fi" in sidebar.border_title

        # 2. Switch back to bluetooth via command line
        inp = app.query_one(MessageInput)
        inp.value = "/transport bluetooth"
        await inp.action_submit()
        await pilot.pause()

        assert test_coordinator.active_transport_name == "bluetooth"
        assert "BLE Mesh" in sidebar.border_title
