"""Unit tests for the BitChat Textual TUI."""

from __future__ import annotations

import pytest
from tests.ble.mocks import MockBleakScanner, MockBLEServerBackend
from textual.widgets import Input, RichLog, Static

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.manager import BLEManager
from bitchat.ble.server import BLEServer
from bitchat.crypto.identity import LocalIdentity
from bitchat.tui.app import BitChatApp


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
async def test_tui_mount_and_welcome(test_coordinator: SessionCoordinator) -> None:
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        log = app.query_one("#chat-log", RichLog)
        assert log is not None

        ident_box = app.query_one("#identity-box", Static)
        assert ident_box is not None
        assert "Alice" in str(ident_box.render())

        await pilot.pause()


@pytest.mark.asyncio
async def test_tui_send_chat_message(test_coordinator: SessionCoordinator) -> None:
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        inp = app.query_one("#chat-input", Input)
        inp.focus()
        inp.value = "Hello world from TUI!"
        await pilot.press("enter")
        await pilot.pause()

        # Input should be cleared after submit
        assert inp.value == ""


@pytest.mark.asyncio
async def test_tui_help_and_clear_command(test_coordinator: SessionCoordinator) -> None:
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        inp = app.query_one("#chat-input", Input)
        inp.focus()

        inp.value = "/help"
        await pilot.press("enter")
        await pilot.pause()

        inp.value = "/clear"
        await pilot.press("enter")
        await pilot.pause()

        log = app.query_one("#chat-log", RichLog)
        assert len(log.lines) == 0


@pytest.mark.asyncio
async def test_tui_inbound_message_display(
    test_coordinator: SessionCoordinator,
) -> None:
    app = BitChatApp(coordinator=test_coordinator)
    async with app.run_test() as pilot:
        # Simulate inbound coordinator message
        app._on_coordinator_message(
            "deadbeef12345678", "Encrypted secret message", True
        )
        await pilot.pause()

        log = app.query_one("#chat-log", RichLog)
        assert any("Encrypted secret message" in str(line) for line in log.lines)
