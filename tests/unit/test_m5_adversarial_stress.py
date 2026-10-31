"""Adversarial stress-testing suite for Milestone 5:
Empirically verifies:
1. Lifecycle & Cancellation under nested, hanging, self-calling, and failing tasks
2. TUI Teardown idempotency, concurrent calls, and worker cancellation
3. Logging & SensitiveDataFilter redaction under diverse secret patterns, tracebacks, args, and safe peer ID preservation
4. Log rotation with high-throughput byte generation (>10MB) verifying 5-backup bound
5. Console handler suppression in TUI mode
6. Packaging tests and Windows Installer 2.0 preservation
"""

from __future__ import annotations

import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
    DEFAULT_LOG_FILE_NAME,
    DEFAULT_MAX_BYTES,
    SensitiveDataFilter,
    disable_console_logging,
    setup_logging,
)
from bitchat.storage.config import InMemoryStorage
from bitchat.tui.app import BitChatApp


@pytest.fixture
def test_identity() -> LocalIdentity:
    return LocalIdentity.generate()


@pytest.fixture
def coordinator_instance(test_identity: LocalIdentity) -> SessionCoordinator:
    server = BLEServer(backend=MockBLEServerBackend())
    manager = BLEManager(
        sender_id=test_identity.peer_id,
        scanner_factory=lambda **kw: MockBleakScanner(
            kw["detection_callback"], kw["service_uuids"]
        ),
        client_factory=lambda address, **kw: MockBleakClient(address=address, **kw),
    )
    coord = SessionCoordinator(
        local_identity=test_identity,
        ble_manager=manager,
        ble_server=server,
        storage=InMemoryStorage(),
        nickname="StressAlice",
    )
    return coord


# ============================================================================
# Area 1: Lifecycle & Cancellation Stress Testing
# ============================================================================


@pytest.mark.asyncio
async def test_coordinator_stop_with_nested_and_spawning_tasks(
    coordinator_instance: SessionCoordinator,
) -> None:
    """Stress test: Tasks spawning other background tasks while coordinator is running,
    ensuring stop() cancels all tasks without hanging.
    """
    coord = coordinator_instance
    await coord.start()

    nested_cancelled = []

    async def child_task(idx: int) -> None:
        try:
            await asyncio.sleep(60.0)
        except asyncio.CancelledError:
            nested_cancelled.append(f"child_{idx}")
            raise

    async def parent_task(idx: int) -> None:
        # Spawn children via coord
        for c in range(3):
            coord._spawn_task(child_task(idx * 10 + c))
        try:
            await asyncio.sleep(60.0)
        except asyncio.CancelledError:
            nested_cancelled.append(f"parent_{idx}")
            raise

    # Spawn multiple parent tasks
    for p in range(5):
        coord._spawn_task(parent_task(p))

    # Yield control to let tasks start and spawn children
    await asyncio.sleep(0.01)

    # 5 parents + 15 children = 20 tasks
    assert len(coord._background_tasks) >= 20

    # Execute stop
    await coord.stop()

    assert coord.is_running is False
    assert len(coord._background_tasks) == 0
    # All 5 parents and 15 children received cancellation
    assert len(nested_cancelled) >= 20


@pytest.mark.asyncio
async def test_coordinator_stop_with_hanging_and_failing_tasks(
    coordinator_instance: SessionCoordinator,
) -> None:
    """Stress test: Background tasks that delay on CancelledError or raise exceptions."""
    coord = coordinator_instance
    await coord.start()

    task_results = []

    async def slow_cleanup_task() -> None:
        try:
            await asyncio.sleep(60.0)
        except asyncio.CancelledError:
            # Short sleep during cancellation cleanup
            await asyncio.sleep(0.02)
            task_results.append("slow_cancelled")
            raise

    async def failing_task() -> None:
        try:
            await asyncio.sleep(60.0)
        except asyncio.CancelledError:
            task_results.append("failing_cancelled")
            raise RuntimeError("Task failed during cancellation") from None

    coord._spawn_task(slow_cleanup_task())
    coord._spawn_task(failing_task())
    await asyncio.sleep(0.01)

    # Stop should gather with return_exceptions=True and not raise RuntimeError
    await coord.stop()

    assert "slow_cancelled" in task_results
    assert "failing_cancelled" in task_results
    assert len(coord._background_tasks) == 0
    assert coord.is_running is False


@pytest.mark.asyncio
async def test_coordinator_stop_from_within_background_task(
    coordinator_instance: SessionCoordinator,
) -> None:
    """Stress test: Calling coord.stop() from inside an active background task
    must avoid self-cancellation deadlock.
    """
    coord = coordinator_instance
    await coord.start()

    stop_completed = False

    async def stopping_task() -> None:
        nonlocal stop_completed
        await coord.stop()
        stop_completed = True

    t = coord._spawn_task(stopping_task())
    await t

    assert stop_completed is True
    assert coord.is_running is False
    assert len(coord._background_tasks) == 0


@pytest.mark.asyncio
async def test_coordinator_stop_burst_concurrency(
    coordinator_instance: SessionCoordinator,
) -> None:
    """Stress test: 100 concurrent tasks cancelled simultaneously."""
    coord = coordinator_instance
    await coord.start()

    cancelled_count = 0

    async def worker(i: int) -> None:
        nonlocal cancelled_count
        try:
            await asyncio.sleep(100.0)
        except asyncio.CancelledError:
            cancelled_count += 1
            raise

    for i in range(100):
        coord._spawn_task(worker(i))

    await asyncio.sleep(0.01)
    assert len(coord._background_tasks) >= 100

    await coord.stop()

    assert cancelled_count == 100
    assert len(coord._background_tasks) == 0


# ============================================================================
# Area 2: TUI Teardown & Worker Cancellation Stress Testing
# ============================================================================


@pytest.mark.asyncio
async def test_tui_shutdown_resources_concurrency_and_idempotency(
    coordinator_instance: SessionCoordinator,
) -> None:
    """Stress test: Concurrent calls to _shutdown_resources() execute safely
    without race conditions or duplicate coordinator stops.
    """
    coord = coordinator_instance
    with patch.object(coord, "stop", new_callable=AsyncMock) as mock_stop:
        app = BitChatApp(coordinator=coord, storage=InMemoryStorage())

        async def bg() -> None:
            await asyncio.sleep(60.0)

        app._spawn_task(bg())
        await asyncio.sleep(0.01)

        # Launch 10 concurrent shutdown calls
        await asyncio.gather(*[app._shutdown_resources() for _ in range(10)])

        assert app._is_shutting_down is True
        assert len(app._background_tasks) == 0
        assert mock_stop.await_count == 1


@pytest.mark.asyncio
async def test_tui_shutdown_cancels_textual_workers(
    coordinator_instance: SessionCoordinator,
) -> None:
    """Verify that _shutdown_resources explicitly cancels all Textual workers."""
    coord = coordinator_instance
    with patch.object(coord, "stop", new_callable=AsyncMock):
        app = BitChatApp(coordinator=coord, storage=InMemoryStorage())

        from unittest.mock import PropertyMock

        from textual.app import App

        mock_worker1 = MagicMock()
        mock_worker2 = MagicMock()
        with patch.object(
            App, "workers", new_callable=PropertyMock
        ) as mock_workers_prop:
            mock_workers_prop.return_value = [mock_worker1, mock_worker2]

            await app._shutdown_resources()

            mock_worker1.cancel.assert_called_once()
            mock_worker2.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_tui_shutdown_survives_coordinator_stop_exception(
    coordinator_instance: SessionCoordinator,
) -> None:
    """Verify that an exception in coordinator.stop() is caught and logged,
    not crashing the UI shutdown process.
    """
    coord = coordinator_instance
    with patch.object(coord, "stop", side_effect=RuntimeError("Coord stop failed")):
        app = BitChatApp(coordinator=coord, storage=InMemoryStorage())
        # Should not raise
        await app._shutdown_resources()
        assert app._is_shutting_down is True


@pytest.mark.asyncio
async def test_tui_shutdown_from_inside_app_background_task(
    coordinator_instance: SessionCoordinator,
) -> None:
    """Verify that calling _shutdown_resources from inside an app background task
    does not deadlock on self-cancellation.
    """
    coord = coordinator_instance
    with patch.object(coord, "stop", new_callable=AsyncMock):
        app = BitChatApp(coordinator=coord, storage=InMemoryStorage())

        shutdown_done = False

        async def self_terminating_task() -> None:
            nonlocal shutdown_done
            await app._shutdown_resources()
            shutdown_done = True

        t = app._spawn_task(self_terminating_task())
        await t

        assert shutdown_done is True
        assert app._is_shutting_down is True
        assert len(app._background_tasks) == 0


# ============================================================================
# Area 3: Logging & SensitiveDataFilter Redaction Stress Testing
# ============================================================================


def test_sensitive_data_filter_comprehensive_secret_patterns() -> None:
    """Stress test: Inject diverse private keys, tokens, seeds, auth headers,
    and verify redaction while ensuring normal messages and peer IDs are intact.
    """
    filt = SensitiveDataFilter()

    # 1. 64-char hex private keys (lowercase, uppercase, mixed)
    key_lower = "a" * 64
    key_upper = "F" * 64
    key_mixed = "0123456789abcdefABCDEF0123456789abcdefABCDEF0123456789abcdefABCD"
    assert filt.redact(f"key1={key_lower}") == "key1=[REDACTED]"
    assert filt.redact(f"key2={key_upper}") == "key2=[REDACTED]"
    assert filt.redact(f"key3={key_mixed}") == "key3=[REDACTED]"

    # 2. Key-value secrets with varied delimiters and quotes
    assert filt.redact("private_key: 'secret123'") == "private_key: [REDACTED]"
    assert filt.redact('priv-key = "secret_val"') == "priv-key = [REDACTED]"
    assert filt.redact("seed: 9876543210") == "seed: [REDACTED]"
    assert filt.redact("session-token: abc-xyz-123") == "session-token: [REDACTED]"
    assert filt.redact("auth_token=super_secret") == "auth_token=[REDACTED]"
    assert filt.redact("api-key: my_api_key_456") == "api-key: [REDACTED]"
    assert filt.redact("password: complex#password!") == "password: [REDACTED]"

    # 3. Bearer tokens with complex characters
    bearer_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
    assert (
        filt.redact(f"Authorization: Bearer {bearer_token}")
        == "Authorization: Bearer [REDACTED]"
    )

    # 4. Safe values must NOT be redacted
    # 16-hex peer ID
    assert filt.redact("peer_id: 0123456789abcdef") == "peer_id: 0123456789abcdef"
    # 8-char short peer ID prefix
    assert filt.redact("Peer deadbeef online") == "Peer deadbeef online"
    # 63-hex and 65-hex non-key hex strings
    hex_63 = "c" * 63
    hex_65 = "d" * 65
    assert filt.redact(f"data={hex_63}") == f"data={hex_63}"
    assert filt.redact(f"data={hex_65}") == f"data={hex_65}"

    # 5. Normal chat messages containing numbers and symbols
    chat_msg = "Hey, meet me at 12:30 at 192.168.1.50 with 100% certainty!"
    assert filt.redact(chat_msg) == chat_msg


def test_sensitive_data_filter_traceback_and_exception_chains() -> None:
    """Stress test: Exception traceback and chained exceptions containing secrets."""
    filt = SensitiveDataFilter()
    secret_key = "e" * 64

    try:
        try:
            raise ValueError(f"Inner error with secret={secret_key}")
        except ValueError as inner:
            raise RuntimeError(f"Outer error wrapping: {secret_key}") from inner
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="bitchat.crypto",
        level=logging.ERROR,
        pathname=__file__,
        lineno=100,
        msg="Critical failure: %s",
        args=(secret_key,),
        exc_info=exc_info,
    )

    filt.filter(record)

    # Both message and exc_text should have secrets redacted
    assert secret_key not in str(record.msg)
    assert "[REDACTED]" in str(record.msg)
    assert record.exc_text is not None
    assert secret_key not in record.exc_text
    assert "[REDACTED]" in record.exc_text


# ============================================================================
# Area 4: Log Rotation Stress Testing (>10MB Data Volume)
# ============================================================================


def test_log_rotation_with_high_volume_throughput(tmp_path: Path) -> None:
    """Stress test: Write >10MB of data to verify clean rotation and max 5 backups."""
    log_dir = tmp_path / "stress_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / DEFAULT_LOG_FILE_NAME

    # Create handler with smaller maxBytes (100KB) to test multiple rotations rapidly,
    # or test with larger chunks.
    # We will test both: rapid multi-rotation (verifying 5 backups bound),
    # AND verify the production DEFAULT_MAX_BYTES setting.
    test_max_bytes = 100 * 1024  # 100 KB
    backup_count = 5

    handler = RotatingFileHandler(
        log_file,
        maxBytes=test_max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)
    filt = SensitiveDataFilter()
    handler.addFilter(filt)

    stress_logger = logging.getLogger("bitchat.stress_rotation")
    stress_logger.setLevel(logging.INFO)
    stress_logger.addHandler(handler)

    try:
        # Write 1MB of data in 1KB chunks (will cause ~10 rotations, exceeding 5 backups)
        chunk = "X" * 1024
        for _ in range(1000):
            stress_logger.info(chunk)
        handler.flush()

        # Check existing log files
        log_files = sorted(log_dir.glob("bitchat.log*"))
        # Base log + up to 5 backups = maximum 6 files
        assert len(log_files) <= backup_count + 1
        assert (log_dir / DEFAULT_LOG_FILE_NAME).exists()
        # Verify backups up to .5 exist
        for i in range(1, backup_count + 1):
            assert (log_dir / f"{DEFAULT_LOG_FILE_NAME}.{i}").exists()
        # Backup .6 must NOT exist (backupCount=5)
        assert not (log_dir / f"{DEFAULT_LOG_FILE_NAME}.6").exists()
    finally:
        handler.close()
        stress_logger.removeHandler(handler)


def test_actual_10mb_log_rotation_with_default_configuration(tmp_path: Path) -> None:
    """Empirical test: Write >10MB (>11MB) of log data to verify bitchat.log rotates
    cleanly under default production parameters.
    """
    log_dir = tmp_path / "ten_mb_logs"
    setup_logging(log_dir=log_dir, level=logging.INFO)

    log_file = log_dir / DEFAULT_LOG_FILE_NAME
    logger_inst = logging.getLogger("bitchat.ten_mb")

    # Generate 11 MB of log data using 100KB chunks (110 iterations = 11 MB)
    large_chunk = "A" * (100 * 1024)
    for _ in range(115):
        logger_inst.info(large_chunk)

    root = logging.getLogger()
    for h in root.handlers:
        h.flush()

    assert log_file.exists()
    backup_1 = log_dir / f"{DEFAULT_LOG_FILE_NAME}.1"
    assert backup_1.exists(), "Expected bitchat.log.1 after exceeding 10MB"
    # Rollover occurs when next record would exceed maxBytes, so backup is near maxBytes
    assert backup_1.stat().st_size > 9.9 * 1024 * 1024
    assert backup_1.stat().st_size <= DEFAULT_MAX_BYTES
    assert log_file.stat().st_size > 0


def test_setup_logging_defaults_and_production_capacity(tmp_path: Path) -> None:
    """Verify setup_logging configures exact production 10MB capacity and 5 backups."""
    log_dir = tmp_path / "prod_logs"
    setup_logging(log_dir=log_dir, level=logging.DEBUG)

    root = logging.getLogger()
    handlers = [
        h
        for h in root.handlers
        if isinstance(h, RotatingFileHandler)
        and Path(h.baseFilename).parent == log_dir.resolve()
    ]
    assert len(handlers) == 1
    h = handlers[0]
    assert h.maxBytes == 10 * 1024 * 1024  # 10 MB
    assert h.backupCount == 5


# ============================================================================
# Area 5: Console Suppression in TUI Mode
# ============================================================================


def test_console_suppression_in_tui_mode_and_init(tmp_path: Path) -> None:
    """Verify console handlers are stripped when tui_mode=True and during BitChatApp init."""
    root = logging.getLogger()
    bitchat_logger = logging.getLogger("bitchat")

    # Add stream handlers to both
    sh1 = logging.StreamHandler(sys.stdout)
    sh2 = logging.StreamHandler(sys.stderr)
    root.addHandler(sh1)
    bitchat_logger.addHandler(sh2)

    assert sh1 in root.handlers
    assert sh2 in bitchat_logger.handlers

    # Call disable_console_logging
    disable_console_logging()

    assert sh1 not in root.handlers
    assert sh2 not in bitchat_logger.handlers

    # Add again and test setup_logging with tui_mode=True
    sh3 = logging.StreamHandler(sys.stdout)
    root.addHandler(sh3)
    setup_logging(log_dir=tmp_path / "tui_logs", tui_mode=True)
    assert sh3 not in root.handlers


# ============================================================================
# Area 6: Packaging Tests & Windows Installer 2.0 Intactness
# ============================================================================


def test_windows_installer_critical_files_exist_and_non_empty() -> None:
    """Empirically verify all Windows Installer 2.0 files exist and are intact."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    expected_paths = [
        repo_root / "packaging" / "windows" / "bitchat.iss",
        repo_root / "packaging" / "windows" / "build.py",
        repo_root / "packaging" / "windows" / "assets.py",
        repo_root / "packaging" / "windows" / "download_page.py",
        repo_root / "packaging" / "windows" / "version_info.txt",
        repo_root / "packaging" / "windows" / "assets" / "bitchat.ico",
        repo_root / "src" / "bitchat" / "platform" / "startup.py",
        repo_root / "src" / "bitchat" / "__main__.py",
        repo_root / "TERMS_OF_USE.md",
        repo_root / "PRIVACY_POLICY.md",
        repo_root / "docs" / "DOWNLOAD.md",
        repo_root
        / "manifests"
        / "j"
        / "Java-Mx"
        / "BitChat"
        / "0.2.0"
        / "Java-Mx.BitChat.installer.yaml",
        repo_root / ".github" / "workflows" / "release.yml",
        repo_root / "tests" / "unit" / "test_packaging_windows.py",
    ]

    for p in expected_paths:
        assert p.exists(), f"Preserved file missing: {p}"
        assert p.stat().st_size > 0, f"Preserved file is empty: {p}"
