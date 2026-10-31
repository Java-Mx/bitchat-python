"""Adversarial stress and edge-case suite for Milestone 5:
Empirical Challenger 2 verification of lifecycle concurrency, unmounted widget DOM queries,
SensitiveDataFilter secret redaction, and multithreaded logging rotation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

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
    SensitiveDataFilter,
)
from bitchat.storage.config import InMemoryStorage
from bitchat.tui.screens.peer_info import PeerInfoModal
from bitchat.tui.screens.settings import SettingsModal
from bitchat.tui.widgets.autocomplete import AutocompletePalette
from bitchat.tui.widgets.chat_view import ChatView
from bitchat.tui.widgets.header import HeaderWidget as Header
from bitchat.tui.widgets.sidebar import PeerSidebar as Sidebar
from bitchat.tui.widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from pathlib import Path


def create_mock_coordinator(
    identity: LocalIdentity, nickname: str = "TestNode"
) -> SessionCoordinator:
    server = BLEServer(backend=MockBLEServerBackend())
    manager = BLEManager(
        sender_id=identity.peer_id,
        scanner_factory=lambda **kw: MockBleakScanner(
            kw["detection_callback"], kw["service_uuids"]
        ),
        client_factory=lambda address, **kw: MockBleakClient(address=address, **kw),
    )
    return SessionCoordinator(
        local_identity=identity,
        ble_manager=manager,
        ble_server=server,
        storage=InMemoryStorage(),
        nickname=nickname,
    )


# ============================================================================
# 1. Lifecycle & Shutdown Concurrency Stress
# ============================================================================


@pytest.mark.asyncio
async def test_coordinator_stop_concurrent_stress() -> None:
    """Stress test: 50 concurrent calls to SessionCoordinator.stop() must exit cleanly."""
    ident = LocalIdentity.generate()
    coord = create_mock_coordinator(ident, "StressNode")
    await coord.start()
    assert coord.is_running is True

    # Spawn 10 active background workers
    for i in range(10):

        async def worker_loop(idx: int) -> None:
            while True:
                await asyncio.sleep(0.01)

        coord._spawn_task(worker_loop(i))

    assert len(coord._background_tasks) >= 10

    # Trigger 50 concurrent stop() calls
    results = await asyncio.gather(
        *(coord.stop() for _ in range(50)), return_exceptions=True
    )

    for r in results:
        assert not isinstance(r, Exception), f"Concurrent stop raised: {r}"

    assert coord.is_running is False
    assert len(coord._background_tasks) == 0


@pytest.mark.asyncio
async def test_coordinator_stop_from_inside_running_task() -> None:
    """Invoking stop() from inside an active coordinator background task must not deadlock or self-cancel."""
    ident = LocalIdentity.generate()
    coord = create_mock_coordinator(ident, "SelfStopNode")
    await coord.start()

    stop_completed = False

    async def stopper_task() -> None:
        nonlocal stop_completed
        await asyncio.sleep(0.05)
        await coord.stop()
        stop_completed = True

    # Also spawn sibling tasks that should be cancelled
    sibling_cancelled = False

    async def sibling_task() -> None:
        nonlocal sibling_cancelled
        try:
            await asyncio.sleep(60.0)
        except asyncio.CancelledError:
            sibling_cancelled = True
            raise

    coord._spawn_task(sibling_task())
    stopper = coord._spawn_task(stopper_task())

    # Wait for the stopper task with a timeout to guard against deadlock
    await asyncio.wait_for(stopper, timeout=3.0)

    assert stop_completed is True
    assert sibling_cancelled is True
    assert coord.is_running is False
    assert len(coord._background_tasks) == 0


@pytest.mark.asyncio
async def test_coordinator_stop_during_active_message_transfer() -> None:
    """Abruptly stopping coordinator during high-frequency message loop must exit cleanly within 2s."""
    ident_alice = LocalIdentity.generate()
    ident_bob = LocalIdentity.generate()

    alice = create_mock_coordinator(ident_alice, "Alice")
    bob = create_mock_coordinator(ident_bob, "Bob")

    await alice.start()
    await bob.start()

    stop_traffic = asyncio.Event()

    async def traffic_generator() -> None:
        while not stop_traffic.is_set():
            try:
                # Dispatch send attempts
                await alice.send_broadcast_message("Flood test message")
                await asyncio.sleep(0.001)
            except Exception:
                break

    alice._spawn_task(traffic_generator())
    await asyncio.sleep(0.05)  # Let traffic run briefly

    # Abruptly stop both nodes
    stop_traffic.set()
    await asyncio.wait_for(
        asyncio.gather(alice.stop(), bob.stop()),
        timeout=2.0,
    )

    assert alice.is_running is False
    assert bob.is_running is False
    assert len(alice._background_tasks) == 0
    assert len(bob._background_tasks) == 0


# ============================================================================
# 2. Textual DOM Queries on Unmounted / Missing Widgets
# ============================================================================


def test_unmounted_widget_dom_queries_safely_handle_no_matches() -> None:
    """Calling DOM query methods on unmounted/detached widgets must catch NoMatches without crashing."""
    # 1. StatusBar unmounted
    status_bar = StatusBar()
    # Direct watchers calling query_one
    status_bar.watch_mesh_status("Mesh online")
    status_bar.watch_mesh_status("Offline")
    status_bar.watch_security_status("encrypted")
    status_bar.watch_security_status("clear")
    status_bar.watch_target_status("general")
    status_bar.watch_target_status("@Alice")

    # 2. Header unmounted
    header = Header()
    header.watch_status_text("Scanning...")
    header.watch_peer_count(5)
    header.watch_nickname("Bob")
    header.watch_peer_id_hex("0123456789abcdef")
    header.watch_fingerprint("DEAD:BEEF")

    # 3. Sidebar unmounted
    sidebar = Sidebar()
    sidebar.update_identity(nickname="Charlie", peer_id_hex="abcdef0123456789")
    sidebar.set_connected_peers({})
    sidebar.set_discovered_peers({})

    # 4. ChatView unmounted
    chat_view = ChatView()
    chat_view.re_render_all()

    # 5. AutocompletePalette unmounted
    autocomplete = AutocompletePalette()
    # selected_index getter/setter query #autocomplete-option-list
    idx = autocomplete.selected_index
    assert idx == 0
    autocomplete.selected_index = 2
    autocomplete.hide()

    # 6. SettingsModal unmounted
    settings_modal = SettingsModal()
    settings_modal._restore_defaults()
    settings_modal._save_settings()

    # 7. PeerInfoModal unmounted
    peer_info_modal = PeerInfoModal(
        nickname="Eve",
        peer_id_hex="deadbeef01234567",
        address="192.168.1.100",
        fingerprint="DEAD:BEEF",
    )
    peer_info_modal._copy_fingerprint()


# ============================================================================
# 3. SensitiveDataFilter Edge Cases & Comprehensive Redaction
# ============================================================================


def test_sensitive_data_filter_edge_cases() -> None:
    """SensitiveDataFilter must redact various token formats, nested JSON, tracebacks, and preserve peer IDs."""
    filt = SensitiveDataFilter()

    # 1. Bearer tokens with base64url characters
    bearer_token = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisSig-123_456"
    assert "Bearer [REDACTED]" in filt.redact(f"Header: {bearer_token}")
    assert "doNotLeakThisSig" not in filt.redact(f"Header: {bearer_token}")

    # 2. JSON blobs with embedded private keys and seeds
    json_blob = json.dumps(
        {
            "node": "Node1",
            "private_key": "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899",
            "seed": "super_secret_recovery_seed_phrase",
            "session_token": "tok_xyz_9999",
            "safe_id": "0123456789abcdef",
        },
        indent=2,
    )
    redacted_json = filt.redact(json_blob)
    assert (
        "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899"
        not in redacted_json
    )
    assert "super_secret_recovery_seed_phrase" not in redacted_json
    assert "tok_xyz_9999" not in redacted_json
    # Safe 16-hex ID preserved
    assert "0123456789abcdef" in redacted_json

    # 3. Tuple and dict args formatting
    record_tuple = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname="test.py",
        lineno=1,
        msg="Authentication failed: user=%s, api_key=%s, token=%s",
        args=("admin", "ak_live_abcdef123456", "session_abc"),
        exc_info=None,
    )
    assert filt.filter(record_tuple) is True
    assert "ak_live_abcdef123456" not in str(record_tuple.msg)
    assert "[REDACTED]" in str(record_tuple.msg)
    assert record_tuple.args is None

    # 4. Multiline tracebacks with secret in exception message
    raw_tb = """Traceback (most recent call last):
  File "bitchat/crypto/noise.py", line 42, in initiate
    raise CryptoError("Handshake static_key=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef is invalid")
CryptoError: Handshake static_key=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef is invalid
"""
    redacted_tb = filt.redact(raw_tb)
    assert (
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        not in redacted_tb
    )
    assert "[REDACTED]" in redacted_tb

    # 5. Hex key boundary tests
    # 63 characters (must NOT be treated as 64-char key)
    hex_63 = "a" * 63
    assert filt.redact(hex_63) == hex_63

    # 64 characters (MUST be redacted)
    hex_64 = "a" * 64
    assert filt.redact(hex_64) == "[REDACTED]"

    # 65 characters (must NOT be treated as 64-char key due to word boundary \b)
    hex_65 = "a" * 65
    assert filt.redact(hex_65) == hex_65

    # Safe natural language sentence containing "token"
    natural_text = "Alice spent 1 token at the arcade."
    # The word token alone without separator is preserved
    assert filt.redact(natural_text) == natural_text


# ============================================================================
# 4. RotatingFileHandler Multithreaded Concurrency Stress
# ============================================================================


def test_rotating_file_handler_multithreaded_stress(tmp_path: Path) -> None:
    """Concurrent logging across 10 threads triggering multiple file rotations must not corrupt or deadlock."""
    log_dir = tmp_path / "concurrent_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / DEFAULT_LOG_FILE_NAME

    # Small maxBytes (20 KB) to trigger frequent rotations under moderate volume
    small_max_bytes = 20 * 1024
    backup_count = 3

    handler = RotatingFileHandler(
        log_file,
        maxBytes=small_max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s [%(threadName)s] %(message)s"))
    handler.addFilter(SensitiveDataFilter())

    stress_logger = logging.getLogger("bitchat.stress.concurrency")
    stress_logger.setLevel(logging.INFO)
    stress_logger.addHandler(handler)

    num_threads = 8
    messages_per_thread = 500
    errors: list[Exception] = []

    def thread_worker(thread_idx: int) -> None:
        try:
            for m_idx in range(messages_per_thread):
                # Include secrets to verify thread-safe filter redaction during rotation
                secret = f"thread_{thread_idx}_msg_{m_idx}_" + ("f" * 64)
                stress_logger.info(
                    "Worker thread %d message %d: secret_key=%s",
                    thread_idx,
                    m_idx,
                    secret,
                )
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=thread_worker, args=(i,), name=f"StressThread-{i}")
        for i in range(num_threads)
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    handler.close()
    stress_logger.removeHandler(handler)

    assert len(errors) == 0, f"Thread logging errors: {errors}"

    # Verify log files exist and no leaked 64-char secrets
    log_files = list(log_dir.glob("bitchat.log*"))
    assert len(log_files) >= 1
    for f in log_files:
        content = f.read_text(encoding="utf-8", errors="replace")
        assert "f" * 64 not in content, f"Secret leaked in log file {f.name}"
        assert "[REDACTED]" in content
