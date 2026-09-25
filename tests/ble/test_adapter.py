"""Tests for BLE adapter manager, radio monitoring, and truthful state transitions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bitchat.ble.adapter import AdapterInfo, BLEAdapterManager
from bitchat.ble.models import DiscoveredPeer
from bitchat.ble.scanner import BLEScanner
from bitchat.protocol.constants import BITCHAT_SERVICE_UUID


@pytest.mark.asyncio
async def test_adapter_info_properties() -> None:
    """Verify AdapterInfo properties and enabled flag."""
    info_on = AdapterInfo(
        is_available=True,
        radio_state="on",
        is_peripheral_supported=True,
        is_central_supported=True,
        device_id="adapter_1",
        name="Test Radio",
    )
    assert info_on.is_available is True
    assert info_on.is_enabled is True
    assert info_on.radio_state == "on"

    info_off = AdapterInfo(is_available=True, radio_state="off")
    assert info_off.is_available is True
    assert info_off.is_enabled is False

    info_unavail = AdapterInfo(is_available=False, radio_state="unavailable")
    assert info_unavail.is_available is False
    assert info_unavail.is_enabled is False


@pytest.mark.asyncio
async def test_adapter_manager_custom_backend() -> None:
    """Verify custom backend delegation in BLEAdapterManager."""
    mock_backend = MagicMock()
    mock_backend.check_adapter = AsyncMock(
        return_value=AdapterInfo(
            is_available=True,
            radio_state="on",
            is_peripheral_supported=True,
            is_central_supported=True,
        )
    )

    mgr = BLEAdapterManager(custom_backend=mock_backend)
    info = await mgr.check_adapter()

    assert info.is_available is True
    assert info.is_enabled is True
    mock_backend.check_adapter.assert_awaited_once()


@pytest.mark.asyncio
async def test_adapter_manager_state_transition_notification() -> None:
    """Verify callbacks fire when radio state changes."""
    notifications: list[AdapterInfo] = []

    state_sequence = [
        AdapterInfo(is_available=True, radio_state="on"),
        AdapterInfo(is_available=True, radio_state="off"),
        AdapterInfo(is_available=True, radio_state="on"),
    ]
    idx = 0

    class MockBackend:
        async def check_adapter(self) -> AdapterInfo:
            nonlocal idx
            res = state_sequence[min(idx, len(state_sequence) - 1)]
            idx += 1
            return res

    mgr = BLEAdapterManager(
        on_state_changed=notifications.append,
        custom_backend=MockBackend(),
    )

    await mgr.check_adapter()
    assert mgr.current_info.radio_state == "on"

    # Advance state to "off"
    info2 = await mgr.check_adapter()
    assert info2.radio_state == "off"
    mgr._notify_listeners(info2)

    assert len(notifications) == 1
    assert notifications[0].radio_state == "off"

    # Advance state back to "on"
    info3 = await mgr.check_adapter()
    assert info3.radio_state == "on"
    mgr._notify_listeners(info3)

    assert len(notifications) == 2
    assert notifications[1].radio_state == "on"


@pytest.mark.asyncio
async def test_scanner_strict_filtering_non_bitchat() -> None:
    """Verify scanner strictly rejects packets lacking BitChat UUID or signature."""
    scanner = BLEScanner()

    mock_device = MagicMock()
    mock_device.address = "11:22:33:44:55:66"
    mock_device.name = "Random-Device"
    mock_device.rssi = -60

    # 1. Unrelated service UUID -> Rejected
    adv1 = MagicMock()
    adv1.service_uuids = ["00001800-0000-1000-8000-00805f9b34fb"]
    adv1.service_data = {}
    adv1.manufacturer_data = {}
    adv1.local_name = "Random-Device"
    adv1.rssi = -60

    scanner._detection_callback(mock_device, adv1)
    assert "11:22:33:44:55:66" not in scanner.discovered_peers

    # 2. Empty service UUID and empty manufacturer data -> Rejected
    adv2 = MagicMock()
    adv2.service_uuids = []
    adv2.service_data = {}
    adv2.manufacturer_data = {}
    adv2.local_name = "Random-Headphones"
    adv2.rssi = -50

    scanner._detection_callback(mock_device, adv2)
    assert "11:22:33:44:55:66" not in scanner.discovered_peers

    # 3. BitChat service UUID present -> Accepted!
    adv3 = MagicMock()
    adv3.service_uuids = [BITCHAT_SERVICE_UUID.lower()]
    adv3.service_data = {}
    adv3.manufacturer_data = {}
    adv3.local_name = "BitChat-Peer"
    adv3.rssi = -45

    scanner._detection_callback(mock_device, adv3)
    assert "11:22:33:44:55:66" in scanner.discovered_peers
    assert scanner.discovered_peers["11:22:33:44:55:66"].name == "BitChat-Peer"


@pytest.mark.asyncio
async def test_scanner_prune_stale_peers() -> None:
    """Verify stale discovered peers are cleanly removed after TTL."""
    scanner = BLEScanner()

    peer_fresh = DiscoveredPeer(
        address="AA:01",
        name="Fresh",
        rssi=-50,
        last_seen=100.0,
    )
    peer_stale = DiscoveredPeer(
        address="BB:02",
        name="Stale",
        rssi=-80,
        last_seen=20.0,
    )

    scanner._discovered_peers["AA:01"] = peer_fresh
    scanner._discovered_peers["BB:02"] = peer_stale

    expired: list[str] = []
    scanner.on_peer_expired = expired.append

    # Prune with current time 110.0 and max_age 30.0 (anything older than 80.0 is stale)
    import time

    orig_time = time.time
    try:
        time.time = lambda: 110.0
        pruned = scanner.prune_stale_peers(max_age=30.0)
        assert "BB:02" in pruned
        assert "AA:01" not in pruned
        assert "BB:02" not in scanner.discovered_peers
        assert "AA:01" in scanner.discovered_peers
        assert "BB:02" in expired
    finally:
        time.time = orig_time
