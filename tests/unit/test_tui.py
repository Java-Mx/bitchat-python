"""Unit tests for the BitChat Textual TUI and autocomplete subsystem."""

from __future__ import annotations

import asyncio
import contextvars
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tests.ble.mocks import MockBleakScanner, MockBLEServerBackend
from textual.command import CommandPalette
from textual.widgets import Button, Input, Label, RadioButton, RichLog, Static

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.adapter import AdapterInfo, BLEAdapterManager
from bitchat.ble.manager import BLEManager
from bitchat.ble.models import DiscoveredPeer
from bitchat.ble.server import BLEServer
from bitchat.crypto.identity import LocalIdentity
from bitchat.network.models import NetworkInfo
from bitchat.network.transport import LANTransport
from bitchat.storage.config import (
    DEFAULT_KEYBINDINGS,
    AppConfig,
    InMemoryStorage,
)
from bitchat.transport.base import TransportState
from bitchat.tui.app import BitChatApp
from bitchat.tui.screens.ble_error import (
    BLEErrorModal,
    LANErrorModal,
    TransportErrorModal,
)
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
        assert any("Welcome to BitChat" in line.text for line in log.lines)

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
        rendered = " ".join(" ".join(line.text for line in log.lines).split())
        assert "Hello world from modern TUI!" in rendered


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
        rendered = " ".join(" ".join(line.text for line in log.lines).split())
        assert "Encrypted secret message" in rendered
        assert "DM" in rendered


@pytest.mark.asyncio
async def test_chat_messages_render_metadata_and_text_on_one_aligned_row(
    test_coordinator: SessionCoordinator,
) -> None:
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test(size=(120, 40)) as pilot:
        chat = app.query_one(ChatView)
        chat.clear_log()
        chat.add_chat_message("Alice", "short outgoing", False, is_self=True)
        chat.add_chat_message("PeerB", "short incoming", False)
        chat.add_chat_message("PeerC", "private incoming", True)
        chat.add_chat_message("Alice", "private outgoing", True, is_self=True)
        await pilot.pause()

        lines = [line.text.rstrip() for line in chat.rich_log.lines]
        assert len(lines) == 7
        assert lines[0].lstrip().startswith("You [Public] • ")
        assert ": short outgoing" in lines[0]
        assert lines[0].startswith(" ")
        assert not lines[1].strip()
        assert lines[2].startswith("PeerB [Public] • ")
        assert ": short incoming" in lines[2]
        assert not lines[3].strip()
        assert lines[4].startswith("PeerC [🔒 DM] • ")
        assert ": private incoming" in lines[4]
        assert not lines[5].strip()
        assert lines[6].lstrip().startswith("You [🔒 DM] • ")
        assert ": private outgoing" in lines[6]


@pytest.mark.asyncio
async def test_chat_spacing_is_between_records_not_multiline_lines(
    test_coordinator: SessionCoordinator,
) -> None:
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test(size=(120, 40)) as pilot:
        chat = app.query_one(ChatView)
        chat.clear_log()
        chat.add_chat_message("PeerB", "first line\nsecond line", False)
        chat.add_chat_message("Alice", "outgoing", False, is_self=True)
        await pilot.pause()

        lines = [line.text.rstrip() for line in chat.rich_log.lines]
        assert len(lines) == 4
        assert lines[0].startswith("PeerB [Public] • ")
        assert lines[0].endswith(": first line")
        assert lines[1].lstrip() == "second line"
        assert lines[2].strip() == ""
        assert lines[3].lstrip().startswith("You [Public] • ")


@pytest.mark.asyncio
async def test_chat_messages_have_a_visible_richlog_row_gap(
    test_coordinator: SessionCoordinator,
) -> None:
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test(size=(120, 40)) as pilot:
        chat = app.query_one(ChatView)
        chat.clear_log()
        chat.add_chat_message("Alice", "Hello", False, is_self=True)
        chat.add_chat_message("Alice", "World", False, is_self=True)
        await pilot.pause()

        log = chat.rich_log
        rows = [line.text.rstrip() for line in log.lines]
        hello_row = next(i for i, row in enumerate(rows) if ": Hello" in row)
        world_row = next(i for i, row in enumerate(rows) if ": World" in row)

        assert world_row - hello_row == 2
        assert not rows[hello_row + 1].strip()
        assert log.virtual_size.height > world_row


@pytest.mark.asyncio
async def test_chat_long_and_multiline_messages_wrap_with_hanging_alignment(
    test_coordinator: SessionCoordinator,
) -> None:
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test(size=(110, 36)) as pilot:
        chat = app.query_one(ChatView)
        log = chat.rich_log
        width = max(1, log.scrollable_content_region.width - 1)
        chat.clear_log()

        long_text = (
            "this is a very long message that should wrap safely without "
            "horizontal overflow " * 4
        )
        chat.add_chat_message("Alice", long_text, False, is_self=True)
        await pilot.pause()
        outgoing_lines = [line.text.rstrip() for line in log.lines]
        assert len(outgoing_lines) > 1
        assert outgoing_lines[0].lstrip().startswith("You [Public] • ")
        assert ": this is a very long message" in outgoing_lines[0]
        assert all(line.cell_length <= width for line in log.lines)
        assert all(line.startswith(" ") for line in outgoing_lines[1:])
        assert "horizontal overflow" in "".join(outgoing_lines)

        chat.clear_log()
        chat.add_chat_message("PeerB", long_text, False)
        await pilot.pause()
        incoming_lines = [line.text.rstrip() for line in log.lines]
        assert len(incoming_lines) > 1
        assert incoming_lines[0].startswith("PeerB [Public] • ")
        assert ": this is a very long message" in incoming_lines[0]
        assert all(line.cell_length <= width for line in log.lines)
        assert all(line.startswith(" ") for line in incoming_lines[1:])
        assert "horizontal overflow" in "".join(incoming_lines)

        chat.clear_log()
        chat.add_chat_message(
            "Alice", "first line\nsecond line\nthird line", True, is_self=True
        )
        await pilot.pause()
        outgoing_multiline = [line.text.rstrip() for line in log.lines]
        assert len(outgoing_multiline) == 3
        assert outgoing_multiline[0].lstrip().endswith(": first line")
        assert outgoing_multiline[1].lstrip() == "second line"
        assert outgoing_multiline[2].lstrip() == "third line"
        assert all(line.startswith(" ") for line in outgoing_multiline[1:])

        chat.clear_log()
        chat.add_chat_message("PeerB", "first line\nsecond line", False)
        await pilot.pause()
        incoming_multiline = [line.text.rstrip() for line in log.lines]
        assert len(incoming_multiline) == 2
        assert incoming_multiline[0].startswith("PeerB [Public] • ")
        assert incoming_multiline[0].endswith(": first line")
        assert incoming_multiline[1].lstrip() == "second line"
        assert incoming_multiline[1].startswith(" ")


@pytest.mark.asyncio
async def test_chat_margins_wrap_and_resize_with_conversation_width(
    test_coordinator: SessionCoordinator,
) -> None:
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test(size=(110, 36)) as pilot:
        chat = app.query_one(ChatView)
        log = chat.rich_log
        chat.clear_log()
        assert log.content_region.x >= log.region.x + 1
        assert log.region.right - log.content_region.right >= 1
        assert log.region.right - log.scrollable_content_region.right >= 2

        message = "Long content that must wrap inside the padded conversation " * 4
        chat.add_chat_message("PeerB", message, False)
        chat.add_chat_message("Alice", message, False, is_self=True)
        await pilot.pause()

        width = max(1, log.scrollable_content_region.width - 1)
        assert all(line.cell_length <= width for line in log.lines)
        incoming_lines = [line for line in log.lines if "PeerB [Public]" in line.text]
        outgoing_lines = [line for line in log.lines if "You [Public]" in line.text]
        assert incoming_lines and outgoing_lines
        assert incoming_lines[0].text.startswith("PeerB [Public]")
        assert outgoing_lines[0].text.lstrip().startswith("You [Public]")
        assert outgoing_lines[0].cell_length == width
        assert outgoing_lines[0].cell_length < log.scrollable_content_region.width

        await pilot.resize_terminal(85, 36)
        await pilot.pause()
        resized_width = max(1, log.scrollable_content_region.width - 1)
        assert resized_width < width
        assert all(line.cell_length <= resized_width for line in log.lines)
        assert "Long content" in "".join(line.text for line in log.lines)


@pytest.mark.asyncio
async def test_chat_scrolls_after_many_single_row_messages(
    test_coordinator: SessionCoordinator,
) -> None:
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test(size=(100, 24)) as pilot:
        chat = app.query_one(ChatView)
        chat.clear_log()
        for index in range(60):
            chat.add_chat_message("PeerB", f"message {index}", False)
        await pilot.pause()

        log = chat.rich_log
        bottom = log.scroll_y
        assert bottom > 0
        await pilot.press("pageup")
        await pilot.pause()
        assert log.scroll_y < bottom
        chat.add_chat_message("PeerB", "arrived while manually scrolling", False)
        await pilot.pause()
        assert log.scroll_y == log.max_scroll_y
        assert any(
            "arrived while manually scrolling" in line.text for line in log.lines
        )
        await pilot.press("pagedown")
        await pilot.pause()
        assert log.scroll_y == log.max_scroll_y


@pytest.mark.asyncio
async def test_chat_narrow_width_keeps_long_sender_metadata_and_message(
    test_coordinator: SessionCoordinator,
) -> None:
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test(size=(80, 30)) as pilot:
        chat = app.query_one(ChatView)
        log = chat.rich_log
        width = max(1, log.scrollable_content_region.width - 1)
        chat.clear_log()
        sender = "A" * 32
        chat.add_chat_message(sender, "visible message body", False)
        await pilot.pause()

        rendered = " ".join(" ".join(line.text for line in log.lines).split())
        assert sender in rendered
        assert "[Public]" in rendered
        assert "visible message body" in rendered
        assert all(line.cell_length <= width for line in log.lines)


@pytest.mark.asyncio
async def test_ctrl_p_uses_configured_action_and_preserves_palette_access(
    test_coordinator: SessionCoordinator,
) -> None:
    keybindings = DEFAULT_KEYBINDINGS.copy()
    keybindings["help"] = "ctrl+p"
    app = BitChatApp(
        coordinator=test_coordinator,
        config=AppConfig(keybindings=keybindings),
    )
    async with app.run_test(size=(120, 40)) as pilot:
        ctrl_p_bindings = app._bindings.key_to_bindings["ctrl+p"]
        assert [binding.action for binding in ctrl_p_bindings] == ["show_help"]
        default_screen = app.screen

        message_input = app.query_one(MessageInput)
        message_input.focus()
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        help_screen = app.screen
        assert help_screen.is_active
        assert help_screen in app.screen_stack
        assert len(app.screen_stack) == 2
        assert not isinstance(app.screen, CommandPalette)

        await pilot.press("ctrl+p")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)
        assert app.screen is default_screen
        assert default_screen.is_active
        assert help_screen not in app.screen_stack
        assert len(app.screen_stack) == 1
        assert not isinstance(app.screen, CommandPalette)

        with patch.object(help_screen, "dismiss", wraps=help_screen.dismiss) as dismiss:
            help_screen.action_dismiss_modal()
            dismiss.assert_not_called()

            await pilot.press("ctrl+p")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            assert app.screen is not help_screen
            assert dismiss.call_count == 0

        await pilot.press("ctrl+p")
        await pilot.pause()
        assert app.screen is default_screen

        for _ in range(3):
            await pilot.press("ctrl+p")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            assert app.screen.is_active
            await pilot.press("ctrl+p")
            await pilot.pause()
            assert app.screen is default_screen

        sidebar = app.query_one(PeerSidebar)
        sidebar.focus()
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        assert not isinstance(app.screen, CommandPalette)

        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("ctrl+shift+p")
        await pilot.pause()
        assert isinstance(app.screen, CommandPalette)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, CommandPalette)

        message_input = app.query_one(MessageInput)
        message_input.focus()
        message_input.value = "/"
        await pilot.pause()
        assert app.query_one(AutocompletePalette).is_visible

        message_input.value = ""
        await pilot.press("f3")
        await pilot.pause()
        assert isinstance(app.screen, SettingsModal)
        settings_input = app.screen.query_one("#settings-kb-help", Input)
        settings_input.focus()
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, SettingsModal)

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsModal)

        app.query_one(ChatView).add_chat_message("PeerB", "clear me", False)
        await pilot.pause()
        await pilot.press("ctrl+l")
        await pilot.pause()
        assert not app.query_one(ChatView)._message_history


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
        assert not any("Connected" in line.text for line in log.lines)


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
async def test_opening_peer_info_does_not_create_noise_session(
    test_coordinator: SessionCoordinator,
) -> None:
    peer_id = LocalIdentity.generate().peer_id_hex
    test_coordinator.peer_nicknames[peer_id] = "Bob"
    app = BitChatApp(coordinator=test_coordinator)

    async with app.run_test():
        app._open_peer_info("Bob")
        assert test_coordinator.get_session(peer_id) is None


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
        rendered = " ".join(" ".join(line.text for line in log.lines).split())
        assert "to @Bob" in rendered and "Hey Bob from context mode" in rendered

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
        rendered = " ".join(" ".join(line.text for line in log.lines).split())
        assert "to Bob" in rendered and "Direct message via at syntax" in rendered


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
async def test_ble_error_from_real_coordinator_uses_active_textual_lifecycle(
    test_coordinator: SessionCoordinator,
) -> None:
    def failing_scanner_factory(detection_callback, service_uuids):
        scanner = MockBleakScanner(detection_callback, service_uuids)
        scanner.should_fail_start = True
        return scanner

    test_coordinator.ble_manager.scanner._scanner_factory = failing_scanner_factory
    app = BitChatApp(coordinator=test_coordinator)

    async with app.run_test() as pilot:
        await pilot.pause()

        assert isinstance(app.screen, BLEErrorModal)
        assert app.screen.is_mounted
        assert app.screen.app is app
        assert app.screen.error_message == (
            "Bluetooth scan failed: Failed to start BLE scanner: "
            "Bluetooth adapter offline"
        )
        error_content = app.screen.query_one(".ble-error-text", Static)
        error_title = app.screen.query_one("#ble-error-title", Static)
        assert "Bluetooth Hardware Error" in str(error_title.render())
        assert "Bluetooth adapter offline" in str(error_content.render())

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, BLEErrorModal)
        assert app.is_running

        await pilot.press("f1")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()

        second_error = "A second BLE failure without an active app context"

        async def report_without_textual_context() -> None:
            test_coordinator._handle_transport_error(second_error)

        callback_task = contextvars.Context().run(
            asyncio.create_task, report_without_textual_context()
        )
        await callback_task
        await pilot.pause()

        assert isinstance(app.screen, BLEErrorModal)
        assert app.screen.is_mounted
        assert app.screen.app is app
        assert app.screen.error_message == second_error
        error_content = app.screen.query_one(".ble-error-text", Static)
        assert second_error in str(error_content.render())

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, BLEErrorModal)
        assert app.is_running

        third_error = "A third BLE failure from a worker thread"
        await asyncio.to_thread(test_coordinator._handle_transport_error, third_error)
        await pilot.pause()

        assert isinstance(app.screen, BLEErrorModal)
        assert app.screen.is_mounted
        assert app.screen.app is app
        assert app.screen.error_message == third_error
        error_content = app.screen.query_one(".ble-error-text", Static)
        assert third_error in str(error_content.render())

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, BLEErrorModal)
        assert app.is_running


@pytest.mark.asyncio
async def test_gatt_failure_keeps_bluetooth_central_mode_visible(
    test_coordinator: SessionCoordinator,
) -> None:
    class AdapterBackend:
        async def check_adapter(self) -> AdapterInfo:
            return AdapterInfo(
                is_available=True,
                radio_state="on",
                is_central_supported=True,
                is_peripheral_supported=True,
                device_id="test-adapter",
                name="Test Bluetooth",
            )

    test_coordinator.ble_manager.adapter_manager = BLEAdapterManager(
        custom_backend=AdapterBackend()
    )
    server_backend = test_coordinator.ble_server._custom_backend
    server_backend.start_errors.append(
        RuntimeError("GATT service advertising failed with status 3")
    )
    app = BitChatApp(coordinator=test_coordinator)

    async with app.run_test(size=(120, 45)) as pilot:
        await pilot.pause()

        assert isinstance(app.screen, BLEErrorModal)
        title = app.screen.query_one("#ble-error-title", Static)
        content = app.screen.query_one(".ble-error-text", Static)
        telemetry = test_coordinator.active_transport.get_telemetry()
        assert "BLE Peripheral Mode Warning" in str(title.render())
        assert "radio is ON" in str(content.render())
        assert "central scanning remains active" in str(content.render())
        assert telemetry["scanner_status"] == "Active"
        assert telemetry["adapter_state"] == "On"
        assert telemetry["scanner_status"] == "Active"
        assert telemetry["advertising_active"] is False

        status = app.query_one(StatusBar).status_message
        assert "Bluetooth Available" in status
        assert "BLE Central Mode" in status
        assert "Peripheral Advertising Failed" in status
        rendered = "\n".join(
            line.text for line in app.query_one("#chat-log", RichLog).lines
        )
        assert "BLE central scanning is active" in rendered
        assert "status 3" in rendered

        retry_button = app.screen.query_one("#btn-ble-retry", Button)
        clicked = await pilot.click("#btn-ble-retry")
        await pilot.pause(1)
        assert clicked, retry_button.region
        assert not isinstance(app.screen, BLEErrorModal), (
            server_backend.start_attempts,
            test_coordinator.active_transport.get_telemetry(),
            [type(screen).__name__ for screen in app._screen_stack],
        )
        assert server_backend.start_attempts == 2
        assert telemetry["advertising_active"] is False
        assert test_coordinator.active_transport.get_telemetry()["advertising_active"]


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
        rendered = "\n".join(line.text for line in chat.rich_log.lines)
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

        rendered_lines = [line.text for line in chat.rich_log.lines]
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
        rendered_lines = [line.text for line in chat.rich_log.lines]
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


# ---------------------------------------------------------------------------
# BLE → LAN fallback modal tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ble_error_modal_shows_lan_button_when_lan_available() -> None:
    """BLEErrorModal renders 'Continue with LAN' when lan_available=True."""
    modal = BLEErrorModal(
        error_message="GATT failed",
        bluetooth_available=True,
        peripheral_failure=True,
        lan_available=True,
    )
    app = BitChatApp()
    async with app.run_test() as pilot:
        await app.push_screen(modal)
        await pilot.pause()
        assert isinstance(app.screen, BLEErrorModal)
        buttons = {b.id for b in app.screen.query(Button)}
        assert "btn-ble-lan" in buttons
        assert "btn-ble-retry" in buttons
        assert "btn-ble-close" in buttons


@pytest.mark.asyncio
async def test_ble_error_modal_hides_lan_button_when_lan_unavailable() -> None:
    """BLEErrorModal omits 'Continue with LAN' when lan_available=False."""
    modal = BLEErrorModal(
        error_message="GATT failed",
        bluetooth_available=True,
        peripheral_failure=True,
        lan_available=False,
    )
    app = BitChatApp()
    async with app.run_test() as pilot:
        await app.push_screen(modal)
        await pilot.pause()
        buttons = {b.id for b in app.screen.query(Button)}
        assert "btn-ble-lan" not in buttons
        assert "btn-ble-retry" in buttons
        assert "btn-ble-close" in buttons


@pytest.mark.asyncio
async def test_ble_warning_modal_includes_lan_button(
    test_coordinator: SessionCoordinator,
) -> None:
    """BLE peripheral warning modal always includes the LAN fallback button."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        app._on_coordinator_ble_warning("GATT advertising failed with status 3")
        await pilot.pause()

        assert isinstance(app.screen, BLEErrorModal)
        buttons = {b.id for b in app.screen.query(Button)}
        assert "btn-ble-lan" in buttons, (
            "LAN button must be present when BLE peripheral fails"
        )
        assert "btn-ble-retry" in buttons
        assert "btn-ble-close" in buttons
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, BLEErrorModal)


@pytest.mark.asyncio
async def test_continue_with_lan_switches_transport(
    test_coordinator: SessionCoordinator,
) -> None:
    """'Continue with LAN' dismisses the modal and switches to LAN transport."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test(size=(120, 45)) as pilot:
        app._on_coordinator_ble_warning("GATT advertising failed with status 3")
        await pilot.pause()

        assert isinstance(app.screen, BLEErrorModal)
        assert test_coordinator.active_transport_name == "bluetooth"

        await pilot.click("#btn-ble-lan")
        await pilot.pause(1)

        # Modal must be gone
        assert not isinstance(app.screen, BLEErrorModal)
        # Transport must have switched to LAN
        assert test_coordinator.active_transport_name == "lan"
        # BLE was NOT faked as successful
        assert not test_coordinator.active_transport.get_telemetry().get(
            "advertising_active"
        )


@pytest.mark.asyncio
async def test_continue_offline_does_not_start_lan(
    test_coordinator: SessionCoordinator,
) -> None:
    """'Continue Offline' dismisses the modal without starting LAN."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        app._on_coordinator_ble_warning("GATT advertising failed with status 3")
        await pilot.pause()

        assert isinstance(app.screen, BLEErrorModal)
        await pilot.click("#btn-ble-close")
        await pilot.pause()

        assert not isinstance(app.screen, BLEErrorModal)
        # Transport remains bluetooth (no switch happened)
        assert test_coordinator.active_transport_name == "bluetooth"


@pytest.mark.asyncio
async def test_retry_adapter_still_works_after_modal_changes(
    test_coordinator: SessionCoordinator,
) -> None:
    """'Retry Adapter' still retries BLE; transport must stay bluetooth."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        app._on_coordinator_ble_warning("GATT advertising failed with status 3")
        await pilot.pause()

        assert isinstance(app.screen, BLEErrorModal)
        await pilot.click("#btn-ble-retry")
        await pilot.pause(1)

        assert not isinstance(app.screen, BLEErrorModal)
        # Transport stays bluetooth (retry, not LAN)
        assert test_coordinator.active_transport_name == "bluetooth"


@pytest.mark.asyncio
async def test_no_connected_via_lan_before_peer_connection(
    test_coordinator: SessionCoordinator,
) -> None:
    """Status bar must not show 'Connected via LAN' until a real peer connects."""
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test(size=(120, 45)) as pilot:
        app._on_coordinator_ble_warning("GATT failed")
        await pilot.pause()
        assert isinstance(app.screen, BLEErrorModal)

        await pilot.click("#btn-ble-lan")
        await pilot.pause(1)

        assert not isinstance(app.screen, BLEErrorModal)
        assert test_coordinator.active_transport_name == "lan"

        # Gather all chat lines
        chat_lines = "\n".join(
            line.text for line in app.query_one("#chat-log", RichLog).lines
        )
        # "Connected via LAN" must NOT appear without a real peer handshake
        assert "Connected via LAN" not in chat_lines

        # Status bar must reflect LAN state, not a fake BLE success
        status = app.query_one(StatusBar).status_message
        assert "BLE Central" not in status or "LAN" in status


@pytest.mark.asyncio
async def test_lan_fallback_handler_calls_transport_switch(
    test_coordinator: SessionCoordinator,
) -> None:
    """_handle_lan_fallback() routes through _handle_transport_switch('lan')."""
    app = BitChatApp(coordinator=test_coordinator)
    calls: list[str] = []
    original = app._handle_transport_switch

    def _spy(target: str) -> None:
        calls.append(target)
        original(target)

    app._handle_transport_switch = _spy  # type: ignore[assignment]

    async with app.run_test() as pilot:
        app._handle_lan_fallback()
        await pilot.pause(1)

    assert "lan" in calls, "LAN fallback must invoke _handle_transport_switch('lan')"


# =============================================================================
# LAN / Network-Loss Recovery UX and Truthful Status Tests
# =============================================================================


@pytest.mark.asyncio
async def test_lan_wifi_drops_ethernet_remains_no_modal() -> None:
    """Wi-Fi drops while Ethernet is connected -> LAN remains usable,
    NO recovery modal, and status bar reflects 'LAN (Ethernet)'.
    """
    wifi_info = NetworkInfo(
        status="Connected",
        interface="Wi-Fi",
        ssid="OfficeWiFi",
        local_ip="192.168.1.50",
    )
    with patch("bitchat.network.adapter.detect_network_info", return_value=wifi_info):
        identity = LocalIdentity.generate()
        server = BLEServer(backend=MockBLEServerBackend())
        manager = BLEManager(
            sender_id=identity.peer_id,
            scanner_factory=lambda **kw: MockBleakScanner(
                kw["detection_callback"], kw["service_uuids"]
            ),
        )
        coord = SessionCoordinator(
            local_identity=identity,
            ble_manager=manager,
            ble_server=server,
            storage=InMemoryStorage(),
            nickname="Alice",
            initial_transport="lan",
        )
        app = BitChatApp(coordinator=coord)
        async with app.run_test(size=(120, 45)) as pilot:
            await pilot.pause()
            # Verify initial Wi-Fi status
            status = app.query_one(StatusBar).status_message
            assert "LAN (Wi-Fi)" in status

            # Transition: Wi-Fi lost, Ethernet remains
            eth_info = NetworkInfo(
                status="Connected",
                interface="Ethernet",
                ssid="unavailable",
                local_ip="192.168.1.100",
            )
            lan_trans = coord.active_transport
            assert isinstance(lan_trans, LANTransport)
            lan_trans.adapter_manager._current_info = eth_info
            lan_trans._handle_network_changed(eth_info)
            await pilot.pause()

            # No recovery modal must appear
            assert not any(isinstance(s, BLEErrorModal) for s in app._screen_stack)
            # Status bar must reflect Ethernet
            new_status = app.query_one(StatusBar).status_message
            assert "LAN (Ethernet)" in new_status
            assert lan_trans.state != TransportState.UNAVAILABLE


@pytest.mark.asyncio
async def test_lan_all_interfaces_disconnect_triggers_recovery_modal() -> None:
    """When all LAN interfaces disconnect, LAN enters UNAVAILABLE,
    recovery modal is requested, and truthful offline status is displayed.
    """
    wifi_info = NetworkInfo(
        status="Connected",
        interface="Wi-Fi",
        ssid="OfficeWiFi",
        local_ip="192.168.1.50",
    )
    with patch("bitchat.network.adapter.detect_network_info", return_value=wifi_info):
        identity = LocalIdentity.generate()
        server = BLEServer(backend=MockBLEServerBackend())
        manager = BLEManager(
            sender_id=identity.peer_id,
            scanner_factory=lambda **kw: MockBleakScanner(
                kw["detection_callback"], kw["service_uuids"]
            ),
        )
        coord = SessionCoordinator(
            local_identity=identity,
            ble_manager=manager,
            ble_server=server,
            storage=InMemoryStorage(),
            nickname="Alice",
            initial_transport="lan",
        )
        app = BitChatApp(coordinator=coord)
        async with app.run_test(size=(120, 45)) as pilot:
            await pilot.pause()

            lan_trans = coord.active_transport
            assert isinstance(lan_trans, LANTransport)

            # All interfaces disconnect
            disc_info = NetworkInfo(
                status="Disconnected",
                interface="Unavailable",
                ssid="unavailable",
                local_ip="",
            )
            lan_trans.adapter_manager._current_info = disc_info
            lan_trans._handle_network_changed(disc_info)
            await pilot.pause()

            # LAN transport must be UNAVAILABLE
            assert lan_trans.state == TransportState.UNAVAILABLE
            # Modal must be presented
            assert isinstance(app.screen, BLEErrorModal)
            assert app.screen.transport == "lan"
            # Title & guidance check
            title_text = str(app.screen.query_one("#ble-error-title", Label).render())
            assert "LAN / Network Connection Lost" in title_text
            content_text = str(app.screen.query_one(".ble-error-text", Static).render())
            assert "Local network connectivity is unavailable" in content_text
            # Status bar must reflect truthful offline status
            status = app.query_one(StatusBar).status_message
            expected_status = (
                "LAN (offline) • Reason: Local network connection unavailable"
            )
            assert expected_status in status


@pytest.mark.asyncio
async def test_lan_recovery_switch_to_ble_when_ble_available() -> None:
    """'Switch to BLE' button switches transport to BLE without claiming connected."""
    modal = BLEErrorModal(
        error_message="Local network is disconnected.",
        transport="lan",
        ble_available=True,
    )
    identity = LocalIdentity.generate()
    server = BLEServer(backend=MockBLEServerBackend())
    manager = BLEManager(
        sender_id=identity.peer_id,
        scanner_factory=lambda **kw: MockBleakScanner(
            kw["detection_callback"], kw["service_uuids"]
        ),
    )
    wifi_info = NetworkInfo(
        status="Connected",
        interface="Wi-Fi",
        ssid="OfficeWiFi",
        local_ip="192.168.1.50",
    )
    with patch("bitchat.network.adapter.detect_network_info", return_value=wifi_info):
        coord = SessionCoordinator(
            local_identity=identity,
            ble_manager=manager,
            ble_server=server,
            storage=InMemoryStorage(),
            nickname="Alice",
            initial_transport="lan",
        )
        app = BitChatApp(coordinator=coord)
        async with app.run_test(size=(120, 45)) as pilot:
            await pilot.pause()
            await app.push_screen(modal, app._on_lan_modal_dismissed)
            await pilot.pause()

            assert isinstance(app.screen, BLEErrorModal)
            buttons = {b.id for b in app.screen.query(Button)}
            assert "btn-lan-ble" in buttons

            await pilot.click("#btn-lan-ble")
            await pilot.pause(1)

            # Modal is dismissed
            assert not isinstance(app.screen, BLEErrorModal)
            # Transport switched to bluetooth
            assert coord.active_transport_name == "bluetooth"

            # Truthful status: must NOT falsely claim "Connected via BLE"
            # or peer connected
            chat_lines = "\n".join(
                line.text for line in app.query_one("#chat-log", RichLog).lines
            )
            assert "Connected via BLE" not in chat_lines
            assert "Connected via Bluetooth" not in chat_lines
            status = app.query_one(StatusBar).status_message
            assert "Connected (" not in status


@pytest.mark.asyncio
async def test_lan_recovery_modal_omits_ble_button_when_ble_unavailable() -> None:
    """When BLE is unavailable, recovery modal omits 'Switch to BLE' button."""
    modal = BLEErrorModal(
        error_message="Local network is disconnected.",
        transport="lan",
        ble_available=False,
    )
    app = BitChatApp()
    async with app.run_test(size=(120, 45)) as pilot:
        await app.push_screen(modal)
        await pilot.pause()

        assert isinstance(app.screen, BLEErrorModal)
        buttons = {b.id for b in app.screen.query(Button)}
        assert "btn-lan-ble" not in buttons
        assert "btn-lan-retry" in buttons
        assert "btn-lan-close" in buttons


@pytest.mark.asyncio
async def test_lan_retry_success_reconnects_lan() -> None:
    """'Retry LAN' succeeds when network returns and updates truthful status."""
    identity = LocalIdentity.generate()
    server = BLEServer(backend=MockBLEServerBackend())
    manager = BLEManager(
        sender_id=identity.peer_id,
        scanner_factory=lambda **kw: MockBleakScanner(
            kw["detection_callback"], kw["service_uuids"]
        ),
    )
    wifi_info = NetworkInfo(
        status="Connected",
        interface="Wi-Fi",
        ssid="OfficeWiFi",
        local_ip="192.168.1.50",
    )
    with patch("bitchat.network.adapter.detect_network_info", return_value=wifi_info):
        coord = SessionCoordinator(
            local_identity=identity,
            ble_manager=manager,
            ble_server=server,
            storage=InMemoryStorage(),
            nickname="Alice",
            initial_transport="lan",
        )
        app = BitChatApp(coordinator=coord)
        async with app.run_test(size=(120, 45)) as pilot:
            await pilot.pause()
            modal = BLEErrorModal(
                error_message="Local network is disconnected.",
                transport="lan",
                ble_available=False,
            )
            await app.push_screen(modal, app._on_lan_modal_dismissed)
            await pilot.pause()

            with patch.object(coord, "retry_lan", new=AsyncMock(return_value=True)):
                await pilot.click("#btn-lan-retry")
                await pilot.pause(1)

            assert not isinstance(app.screen, BLEErrorModal)
            chat_lines = "\n".join(
                line.text for line in app.query_one("#chat-log", RichLog).lines
            )
            assert "LAN reconnected successfully" in chat_lines


@pytest.mark.asyncio
async def test_lan_retry_failure_remains_offline() -> None:
    """'Retry LAN' handles failure gracefully and remains in offline mode."""
    identity = LocalIdentity.generate()
    server = BLEServer(backend=MockBLEServerBackend())
    manager = BLEManager(
        sender_id=identity.peer_id,
        scanner_factory=lambda **kw: MockBleakScanner(
            kw["detection_callback"], kw["service_uuids"]
        ),
    )
    wifi_info = NetworkInfo(
        status="Connected",
        interface="Wi-Fi",
        ssid="OfficeWiFi",
        local_ip="192.168.1.50",
    )
    with patch("bitchat.network.adapter.detect_network_info", return_value=wifi_info):
        coord = SessionCoordinator(
            local_identity=identity,
            ble_manager=manager,
            ble_server=server,
            storage=InMemoryStorage(),
            nickname="Alice",
            initial_transport="lan",
        )
        app = BitChatApp(coordinator=coord)
        async with app.run_test(size=(120, 45)) as pilot:
            await pilot.pause()
            modal = BLEErrorModal(
                error_message="Local network is disconnected.",
                transport="lan",
                ble_available=False,
            )
            await app.push_screen(modal, app._on_lan_modal_dismissed)
            await pilot.pause()

            with patch.object(coord, "retry_lan", new=AsyncMock(return_value=False)):
                await pilot.click("#btn-lan-retry")
                await pilot.pause(1)

            chat_lines = " ".join(
                " ".join(
                    line.text for line in app.query_one("#chat-log", RichLog).lines
                ).split()
            )
            assert "LAN retry failed" in chat_lines
            assert "Remaining in offline mode" in chat_lines


@pytest.mark.asyncio
async def test_lan_continue_offline_pauses_services_and_enters_offline_mode() -> None:
    """'Continue Offline' pauses LAN services and enters offline mode cleanly."""
    identity = LocalIdentity.generate()
    server = BLEServer(backend=MockBLEServerBackend())
    manager = BLEManager(
        sender_id=identity.peer_id,
        scanner_factory=lambda **kw: MockBleakScanner(
            kw["detection_callback"], kw["service_uuids"]
        ),
    )
    wifi_info = NetworkInfo(
        status="Connected",
        interface="Wi-Fi",
        ssid="OfficeWiFi",
        local_ip="192.168.1.50",
    )
    with patch("bitchat.network.adapter.detect_network_info", return_value=wifi_info):
        coord = SessionCoordinator(
            local_identity=identity,
            ble_manager=manager,
            ble_server=server,
            storage=InMemoryStorage(),
            nickname="Alice",
            initial_transport="lan",
        )
        app = BitChatApp(coordinator=coord)
        async with app.run_test(size=(120, 45)) as pilot:
            await pilot.pause()
            modal = BLEErrorModal(
                error_message="Local network is disconnected.",
                transport="lan",
                ble_available=False,
            )
            await app.push_screen(modal, app._on_lan_modal_dismissed)
            await pilot.pause()

            assert isinstance(app.screen, BLEErrorModal)
            await pilot.click("#btn-lan-close")
            await pilot.pause(1)

            assert not isinstance(app.screen, BLEErrorModal)
            assert coord.ble_status == "offline"

            chat_lines = "\n".join(
                line.text for line in app.query_one("#chat-log", RichLog).lines
            )
            assert "Operating in Offline Mode." in chat_lines

            status = app.query_one(StatusBar).status_message
            assert (
                "LAN (offline) • Reason: Local network connection unavailable" in status
            )


@pytest.mark.asyncio
async def test_lan_network_recovery_resumes_services_and_updates_status() -> None:
    """When network reconnects after failure, LAN resumes services and status
    becomes truthful.
    """
    wifi_info = NetworkInfo(
        status="Connected",
        interface="Wi-Fi",
        ssid="OfficeWiFi",
        local_ip="192.168.1.50",
    )
    with patch("bitchat.network.adapter.detect_network_info", return_value=wifi_info):
        identity = LocalIdentity.generate()
        server = BLEServer(backend=MockBLEServerBackend())
        manager = BLEManager(
            sender_id=identity.peer_id,
            scanner_factory=lambda **kw: MockBleakScanner(
                kw["detection_callback"], kw["service_uuids"]
            ),
        )
        coord = SessionCoordinator(
            local_identity=identity,
            ble_manager=manager,
            ble_server=server,
            storage=InMemoryStorage(),
            nickname="Alice",
            initial_transport="lan",
        )
        app = BitChatApp(coordinator=coord)
        async with app.run_test(size=(120, 45)) as pilot:
            await pilot.pause()
            lan_trans = coord.active_transport
            assert isinstance(lan_trans, LANTransport)

            # Disconnect all
            disc_info = NetworkInfo(
                status="Disconnected",
                interface="Unavailable",
                ssid="unavailable",
                local_ip="",
            )
            lan_trans.adapter_manager._current_info = disc_info
            lan_trans._handle_network_changed(disc_info)
            await pilot.pause()
            assert lan_trans.state == TransportState.UNAVAILABLE

            # Network recovers
            recov_info = NetworkInfo(
                status="Connected",
                interface="Wi-Fi",
                ssid="OfficeWiFi",
                local_ip="192.168.1.50",
            )
            lan_trans.adapter_manager._current_info = recov_info
            lan_trans._handle_network_changed(recov_info)
            await pilot.pause(1)

            assert lan_trans.state in (TransportState.SCANNING, TransportState.READY)
            status = app.query_one(StatusBar).status_message
            assert "LAN (Wi-Fi)" in status


@pytest.mark.asyncio
async def test_lan_textual_lifecycle_safety_from_background_thread() -> None:
    """Errors dispatched from a background thread do not raise NoActiveAppError."""
    app = BitChatApp()
    async with app.run_test(size=(120, 45)) as pilot:
        error_raised = False

        def _bg_error() -> None:
            nonlocal error_raised
            try:
                app._on_coordinator_lan_error("Background monitor error")
            except Exception:
                error_raised = True

        await asyncio.to_thread(_bg_error)
        await pilot.pause(1)
        assert not error_raised
        assert isinstance(app.screen, BLEErrorModal)
        assert app.screen.transport == "lan"


def test_modal_aliases_and_ble_regression() -> None:
    """Modal aliases match BLEErrorModal, and BLE modal retains standard buttons."""
    assert LANErrorModal is BLEErrorModal
    assert TransportErrorModal is BLEErrorModal

    ble_modal = BLEErrorModal(
        error_message="Bluetooth adapter disabled",
        transport="bluetooth",
        bluetooth_available=False,
    )
    assert ble_modal.transport == "bluetooth"
