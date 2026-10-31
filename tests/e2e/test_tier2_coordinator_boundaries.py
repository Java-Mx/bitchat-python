"""Tier 2: Boundary & Corner Cases — Peer Lifecycle & Session Coordinator Boundaries."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bitchat.app.session_coordinator import _decode_chat_payload
from bitchat.crypto.noise import NoiseSessionState

if TYPE_CHECKING:
    from tests.e2e.conftest import E2ENode


@pytest.mark.asyncio
async def test_coordinator_stop_idempotent(node_factory) -> None:
    """Validate calling stop() multiple times in sequence is safe and idempotent."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    await alice.start()
    assert alice.coordinator.is_running

    # First stop
    await alice.stop()
    assert not alice.coordinator.is_running
    assert alice.coordinator.ble_status == "offline"

    # Repeated stop should be completely benign
    await alice.stop()
    await alice.stop()
    assert not alice.coordinator.is_running


@pytest.mark.asyncio
async def test_coordinator_go_offline_idempotent(node_factory) -> None:
    """Validate go_offline transitions coordinator to offline state and is idempotent."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    await alice.start()
    assert alice.coordinator.is_running

    await alice.coordinator.go_offline()
    assert alice.coordinator.offline_mode is True
    assert not alice.coordinator.is_running
    assert alice.coordinator.ble_status == "offline"

    # Second go_offline call
    await alice.coordinator.go_offline()
    assert alice.coordinator.offline_mode is True


@pytest.mark.asyncio
async def test_coordinator_discard_failed_session(node_factory) -> None:
    """Validate coordinator safely purges sessions that transition to FAILED state."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    bob: E2ENode = node_factory("Bob", "BB:01")

    bob_id = bob.identity.peer_id_hex
    session = alice.coordinator.get_or_create_session(bob_id)
    assert alice.coordinator.get_session(bob_id) is not None

    # Enqueue a pending message
    alice.coordinator._pending_messages[bob_id] = ["Hello Bob"]

    # Session in non-failed state should not be discarded
    alice.coordinator._discard_failed_session(bob_id, session)
    assert alice.coordinator.get_session(bob_id) is not None
    assert bob_id in alice.coordinator._pending_messages

    # Transition to FAILED state
    session._state = NoiseSessionState.FAILED
    alice.coordinator._discard_failed_session(bob_id, session)

    assert alice.coordinator.get_session(bob_id) is None
    assert bob_id not in alice.coordinator._pending_messages


@pytest.mark.asyncio
async def test_coordinator_send_direct_message_before_start(node_factory) -> None:
    """Validate direct messages sent before coordinator starts queue in pending messages."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    bob: E2ENode = node_factory("Bob", "BB:01")

    # Coordinator is stopped/unstarted
    assert not alice.coordinator.is_running

    bob_id = bob.identity.peer_id_hex
    await alice.coordinator.send_direct_message(bob_id, "Deferred offline hello")

    # The message must be preserved in pending queue
    pending = alice.coordinator._pending_messages.get(bob_id)
    assert pending is not None
    assert "Deferred offline hello" in pending


def test_coordinator_decode_chat_payload_fallback() -> None:
    """Validate UTF-8 decoding fallback for invalid or binary bytes."""
    # Invalid UTF-8 sequence
    bad_bytes = b"\xff\xfe\xfd\x80\x81"
    decoded = _decode_chat_payload(bad_bytes)
    assert isinstance(decoded, str)
    # Should contain unicode replacement character
    assert "\ufffd" in decoded

    # Empty payload
    assert _decode_chat_payload(b"") == ""

    # Normal UTF-8 payload
    assert _decode_chat_payload(b"hello mesh") == "hello mesh"


@pytest.mark.asyncio
async def test_coordinator_unknown_transport_switch_fails(node_factory) -> None:
    """Validate switching to an unrecognized transport fails safely without state changes."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    await alice.start()

    orig_transport_name = alice.coordinator.active_transport_name
    orig_identity = alice.coordinator.local_identity.peer_id_hex

    success, msg = await alice.coordinator.switch_transport("quantum_telepathy")
    assert not success
    assert "Unknown transport" in msg

    # Identity and active transport should remain intact
    assert alice.coordinator.active_transport_name == orig_transport_name
    assert alice.coordinator.local_identity.peer_id_hex == orig_identity

    await alice.stop()
