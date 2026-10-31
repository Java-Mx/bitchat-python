"""Tier 1: Feature Coverage — Session Coordinator Application Lifecycle."""

from __future__ import annotations

import asyncio

import pytest
from tests.e2e.conftest import E2ENode, link_nodes, wait_until


@pytest.mark.asyncio
async def test_coordinator_start_stop_lifecycle(node_factory) -> None:
    """Validate coordinator transitions between running and stopped states cleanly."""
    alice: E2ENode = node_factory("Alice", "AA:01")

    assert not alice.coordinator.is_running
    await alice.start()
    assert alice.coordinator.is_running

    await alice.stop()
    assert not alice.coordinator.is_running


@pytest.mark.asyncio
async def test_coordinator_announcement_exchange(node_factory) -> None:
    """Validate announce packet broadcasts local nickname and populates remote peer table."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    bob: E2ENode = node_factory("Bob", "BB:01")

    await bob.start()
    await alice.start()
    await link_nodes(alice, bob)

    # Alice announces herself
    await alice.coordinator.send_announce("Alice")

    await wait_until(
        lambda: (
            bob.coordinator.peer_nicknames.get(alice.identity.peer_id_hex) == "Alice"
        ),
        timeout=2.0,
    )

    assert bob.coordinator.peer_nicknames[alice.identity.peer_id_hex] == "Alice"

    await alice.stop()
    await bob.stop()


@pytest.mark.asyncio
async def test_coordinator_unencrypted_broadcast_chat(node_factory) -> None:
    """Validate broadcast chat messages are delivered with encrypted=False."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    bob: E2ENode = node_factory("Bob", "BB:01")

    await bob.start()
    await alice.start()
    await link_nodes(alice, bob)

    chat_text = "Hello everyone on the mesh!"
    await alice.coordinator.send_broadcast_message(chat_text)

    await wait_until(
        lambda: any(m[1] == chat_text for m in bob.received_messages),
        timeout=2.0,
    )

    msg_record = next(m for m in bob.received_messages if m[1] == chat_text)
    assert msg_record[0] == alice.identity.peer_id_hex
    assert msg_record[1] == chat_text
    assert msg_record[2] is False  # unencrypted broadcast

    await alice.stop()
    await bob.stop()


@pytest.mark.asyncio
async def test_coordinator_encrypted_direct_message(node_factory) -> None:
    """Validate direct message triggers Noise XX handshake and delivers with encrypted=True."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    bob: E2ENode = node_factory("Bob", "BB:01")

    await bob.start()
    await alice.start()
    await link_nodes(alice, bob)

    # Exchange announcements first
    await alice.coordinator.send_announce("Alice")
    await bob.coordinator.send_announce("Bob")
    await asyncio.sleep(0.05)

    secret_text = "Private secret message for Bob only"
    await alice.coordinator.send_direct_message(bob.identity.peer_id_hex, secret_text)

    await wait_until(
        lambda: any(m[1] == secret_text for m in bob.received_messages),
        timeout=3.0,
    )

    msg_record = next(m for m in bob.received_messages if m[1] == secret_text)
    assert msg_record[1] == secret_text
    assert msg_record[2] is True  # encrypted!

    # Sessions established on both ends
    session_a = alice.coordinator.get_or_create_session(bob.identity.peer_id_hex)
    session_b = bob.coordinator.get_or_create_session(alice.identity.peer_id_hex)
    assert session_a.is_established
    assert session_b.is_established

    await alice.stop()
    await bob.stop()


@pytest.mark.asyncio
async def test_coordinator_nickname_update(node_factory) -> None:
    """Validate updating nickname via set_nickname propagates in subsequent announcements."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    bob: E2ENode = node_factory("Bob", "BB:01")

    await bob.start()
    await alice.start()
    await link_nodes(alice, bob)

    alice.coordinator.set_nickname("AliceV2")
    await alice.coordinator.send_announce()

    await wait_until(
        lambda: (
            bob.coordinator.peer_nicknames.get(alice.identity.peer_id_hex) == "AliceV2"
        ),
        timeout=2.0,
    )

    assert bob.coordinator.peer_nicknames[alice.identity.peer_id_hex] == "AliceV2"

    await alice.stop()
    await bob.stop()


@pytest.mark.asyncio
async def test_coordinator_transport_switch_preserves_device_identity(
    node_factory,
) -> None:
    """Validate switching transport preserves the persistent device identity."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    await alice.start()

    initial_id_hex = alice.coordinator.local_identity.peer_id_hex
    # Switch to LAN
    success, _msg = await alice.coordinator.switch_transport("lan")
    assert success is True

    new_id_hex = alice.coordinator.local_identity.peer_id_hex
    assert new_id_hex == initial_id_hex
    assert alice.coordinator.active_transport_name == "lan"

    await alice.stop()
