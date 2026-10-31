"""Comprehensive unit tests for Milestone 5:
- Structured task lifecycle & cancellation in SessionCoordinator and BitChatApp
- TUI clean shutdown & on_unmount
- Diagnostic rotating file logging, SensitiveDataFilter, and console tearing prevention
"""

from __future__ import annotations

import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from tests.ble.mocks import (
    MockBleakClient,
    MockBleakScanner,
    MockBLEServerBackend,
)

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.manager import BLEManager
from bitchat.ble.server import BLEServer
from bitchat.crypto.identity import LocalIdentity
from bitchat.logging import (
    DEFAULT_BACKUP_COUNT,
    DEFAULT_LOG_FILE_NAME,
    DEFAULT_MAX_BYTES,
    SensitiveDataFilter,
    disable_console_logging,
    setup_logging,
)
from bitchat.storage.config import InMemoryStorage
from bitchat.tui.app import BitChatApp


@pytest.fixture
def mock_identity() -> LocalIdentity:
    return LocalIdentity.generate()


@pytest.fixture
def lifecycle_coordinator(mock_identity: LocalIdentity) -> SessionCoordinator:
    server = BLEServer(backend=MockBLEServerBackend())
    manager = BLEManager(
        sender_id=mock_identity.peer_id,
        scanner_factory=lambda **kw: MockBleakScanner(
            kw["detection_callback"], kw["service_uuids"]
        ),
        client_factory=lambda address, **kw: MockBleakClient(address=address, **kw),
    )
    coord = SessionCoordinator(
        local_identity=mock_identity,
        ble_manager=manager,
        ble_server=server,
        storage=InMemoryStorage(),
        nickname="AliceNode",
    )
    return coord


# ============================================================================
# 1. Structured Task Lifecycle & Coordinator Shutdown
# ============================================================================


@pytest.mark.asyncio
async def test_coordinator_stop_structured_task_cancellation(
    lifecycle_coordinator: SessionCoordinator,
) -> None:
    """SessionCoordinator.stop() explicitly cancels and gathers all background tasks."""
    coord = lifecycle_coordinator
    await coord.start()
    assert coord.is_running is True

    # Spawn long-running background tasks
    task_cancelled = False

    async def dummy_bg_task() -> None:
        nonlocal task_cancelled
        try:
            await asyncio.sleep(60.0)
        except asyncio.CancelledError:
            task_cancelled = True
            raise

    bg_task = coord._spawn_task(dummy_bg_task())
    assert bg_task in coord._background_tasks
    assert not bg_task.done()
    await asyncio.sleep(0)  # Allow background task to begin execution

    # Trigger prune task loop
    coord._start_prune_task()
    assert coord._prune_task is not None
    assert not coord._prune_task.done()

    # Call stop
    await coord.stop()

    assert coord.is_running is False
    assert task_cancelled is True
    assert bg_task.done()
    assert len(coord._background_tasks) == 0
    assert coord._prune_task is None
    assert len(coord._handshake_timeout_tasks) == 0
    assert coord.ble_status == "offline"

    # Active transport stopped
    assert coord.active_transport.on_packet_received is None


@pytest.mark.asyncio
async def test_coordinator_stop_is_idempotent(
    lifecycle_coordinator: SessionCoordinator,
) -> None:
    """Calling SessionCoordinator.stop() multiple times completes safely."""
    coord = lifecycle_coordinator
    await coord.start()
    await coord.stop()
    # Second stop should be a clean no-op without errors
    await coord.stop()
    assert coord.is_running is False
    assert len(coord._background_tasks) == 0


# ============================================================================
# 2. TUI Clean Shutdown & on_unmount
# ============================================================================


@pytest.mark.asyncio
async def test_tui_app_action_quit_cancels_background_tasks(
    lifecycle_coordinator: SessionCoordinator,
) -> None:
    """BitChatApp.action_quit() cancels background tasks and stops coordinator."""
    coord = lifecycle_coordinator
    with patch.object(coord, "stop", new_callable=AsyncMock) as mock_stop:
        app = BitChatApp(coordinator=coord, storage=InMemoryStorage())

        bg_cancelled = False

        async def long_bg_job() -> None:
            nonlocal bg_cancelled
            try:
                await asyncio.sleep(60.0)
            except asyncio.CancelledError:
                bg_cancelled = True
                raise

        t = app._spawn_task(long_bg_job())
        assert t in app._background_tasks
        await asyncio.sleep(0)  # Allow background task to begin execution

        await app.action_quit()

        assert bg_cancelled is True
        assert t.done()
        assert len(app._background_tasks) == 0
        mock_stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_tui_app_on_unmount_guarantees_cleanup(
    lifecycle_coordinator: SessionCoordinator,
) -> None:
    """BitChatApp.on_unmount() guarantees coordinator shutdown on exit."""
    coord = lifecycle_coordinator
    with patch.object(coord, "stop", new_callable=AsyncMock) as mock_stop:
        app = BitChatApp(coordinator=coord, storage=InMemoryStorage())

        # Simulate terminal unmount directly
        await app.on_unmount()
        mock_stop.assert_awaited_once()

        # Second unmount call should be idempotent
        await app.on_unmount()
        assert mock_stop.await_count == 1


# ============================================================================
# 3. Diagnostic Rotating File Logging
# ============================================================================


def test_setup_logging_configures_rotating_file_handler(tmp_path: Path) -> None:
    """setup_logging creates bitchat.log with 10MB rotation and 5 backups."""
    log_dir = tmp_path / "logs"
    setup_logging(log_dir=log_dir, level=logging.DEBUG)

    log_file = log_dir / DEFAULT_LOG_FILE_NAME
    assert log_file.exists() or log_dir.exists()

    root = logging.getLogger()
    target_path = str(log_file.resolve())
    rotating_handlers = [
        h
        for h in root.handlers
        if isinstance(h, RotatingFileHandler)
        and str(Path(h.baseFilename).resolve()) == target_path
    ]
    assert len(rotating_handlers) == 1

    handler = rotating_handlers[0]
    assert handler.maxBytes == DEFAULT_MAX_BYTES
    assert handler.backupCount == DEFAULT_BACKUP_COUNT
    assert handler.level == logging.DEBUG

    # Test writing log output
    test_logger = logging.getLogger("bitchat.test")
    test_logger.info("BitChat diagnostic logging active")
    handler.flush()

    content = log_file.read_text(encoding="utf-8")
    assert "BitChat diagnostic logging active" in content


def test_setup_logging_avoids_duplicate_handlers(tmp_path: Path) -> None:
    """Multiple setup_logging calls for the same file replace handlers."""
    log_dir = tmp_path / "logs_dup"
    setup_logging(log_dir=log_dir, level=logging.INFO)
    setup_logging(log_dir=log_dir, level=logging.DEBUG)

    root = logging.getLogger()
    target_path = str((log_dir / DEFAULT_LOG_FILE_NAME).resolve())
    matching = [
        h
        for h in root.handlers
        if isinstance(h, RotatingFileHandler)
        and str(Path(h.baseFilename).resolve()) == target_path
    ]
    assert len(matching) == 1
    assert matching[0].level == logging.DEBUG


# ============================================================================
# 4. Sensitive Data Filter & Redaction
# ============================================================================


def test_sensitive_data_filter_redacts_private_keys_and_secrets() -> None:
    """SensitiveDataFilter replaces 32-byte hex keys and credentials with [REDACTED]."""
    filt = SensitiveDataFilter()

    # 1. 32-byte hex string (64 characters)
    hex_key = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    raw_msg = f"Generated key pair with private_key={hex_key}"
    redacted = filt.redact(raw_msg)
    assert hex_key not in redacted
    assert "[REDACTED]" in redacted

    # 2. Key-value secrets
    assert "session_token=[REDACTED]" in filt.redact("session_token=secret_tok_98765")
    assert "password: [REDACTED]" in filt.redact("password: my_super_secret_password")
    assert "api_key=[REDACTED]" in filt.redact("api_key='abc123xyz456'")

    # 3. Bearer authorization tokens
    bearer_msg = "Authorization: Bearer my_jwt_token.1234.5678"
    assert "Bearer [REDACTED]" in filt.redact(bearer_msg)

    # 4. Safe values must NOT be redacted:
    # 8-byte peer_id (16 hex chars)
    peer_id = "deadbeef12345678"
    assert filt.redact(f"Peer {peer_id} joined") == f"Peer {peer_id} joined"
    # Normal chat text
    chat_text = "Hello world! BitChat is a secure mesh chat."
    assert filt.redact(chat_text) == chat_text


def test_sensitive_data_filter_log_record_integration() -> None:
    """SensitiveDataFilter redacts formatted LogRecords, args, and tracebacks."""
    filt = SensitiveDataFilter()
    secret_key = "a" * 64

    # Record with args
    record = logging.LogRecord(
        name="bitchat.crypto",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Session initialized with static secret: %s",
        args=(secret_key,),
        exc_info=None,
    )
    assert filt.filter(record) is True
    assert secret_key not in str(record.msg)
    assert "[REDACTED]" in str(record.msg)
    assert record.args is None

    # Record with exception traceback
    try:
        raise ValueError(f"Handshake failed with secret_key={secret_key}")
    except ValueError:
        exc_info = sys.exc_info()

    err_record = logging.LogRecord(
        name="bitchat.crypto",
        level=logging.ERROR,
        pathname=__file__,
        lineno=20,
        msg="Handshake error occurred",
        args=(),
        exc_info=exc_info,
    )
    assert filt.filter(err_record) is True
    assert err_record.exc_text is not None
    assert secret_key not in err_record.exc_text
    assert "[REDACTED]" in err_record.exc_text


# ============================================================================
# 5. Console Tearing Prevention in TUI Mode
# ============================================================================


def test_disable_console_logging_removes_stream_handlers() -> None:
    """disable_console_logging removes stdout/stderr stream handlers."""
    root = logging.getLogger()
    bitchat_logger = logging.getLogger("bitchat")

    stdout_handler = logging.StreamHandler(sys.stdout)
    stderr_handler = logging.StreamHandler(sys.stderr)
    root.addHandler(stdout_handler)
    bitchat_logger.addHandler(stderr_handler)

    assert stdout_handler in root.handlers
    assert stderr_handler in bitchat_logger.handlers

    disable_console_logging()

    assert stdout_handler not in root.handlers
    assert stderr_handler not in bitchat_logger.handlers
