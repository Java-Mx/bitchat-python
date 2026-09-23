"""Tests for BLE scanner behavior."""

import pytest
from tests.ble.mocks import MockBleakScanner

from bitchat.ble.scanner import BLEScanner
from bitchat.exceptions import BLEScanError
from bitchat.protocol.constants import BITCHAT_SERVICE_UUID


@pytest.mark.asyncio
async def test_scanner_start_stop():
    mock_scanner: MockBleakScanner | None = None

    def scanner_factory(detection_callback, service_uuids):
        nonlocal mock_scanner
        mock_scanner = MockBleakScanner(detection_callback, service_uuids)
        return mock_scanner

    scanner = BLEScanner(scanner_factory=scanner_factory)
    assert not scanner.is_scanning

    await scanner.start()
    assert scanner.is_scanning
    assert mock_scanner is not None
    assert mock_scanner.is_started
    assert mock_scanner.service_uuids == [BITCHAT_SERVICE_UUID.lower()]

    await scanner.stop()
    assert not scanner.is_scanning
    assert not mock_scanner.is_started


@pytest.mark.asyncio
async def test_scanner_filters_service_uuid():
    mock_scanner: MockBleakScanner | None = None
    discovered = []

    def scanner_factory(detection_callback, service_uuids):
        nonlocal mock_scanner
        mock_scanner = MockBleakScanner(detection_callback, service_uuids)
        return mock_scanner

    scanner = BLEScanner(
        on_peer_discovered=discovered.append,
        scanner_factory=scanner_factory,
    )
    await scanner.start()
    assert mock_scanner is not None

    # Emit BitChat peripheral
    mock_scanner.emit_device(
        address="11:22:33:44:55:66",
        name="BitChat-Alice",
        service_uuids=[BITCHAT_SERVICE_UUID.lower()],
        rssi=-50,
    )
    # Emit unrelated peripheral
    mock_scanner.emit_device(
        address="99:88:77:66:55:44",
        name="Unrelated-Beacon",
        service_uuids=["0000180f-0000-1000-8000-00805f9b34fb"],
        rssi=-70,
    )

    peers = scanner.discovered_peers
    assert "11:22:33:44:55:66" in peers
    assert "99:88:77:66:55:44" not in peers
    assert len(discovered) == 1
    assert discovered[0].address == "11:22:33:44:55:66"
    assert discovered[0].name == "BitChat-Alice"
    assert discovered[0].rssi == -50

    await scanner.stop()


@pytest.mark.asyncio
async def test_scanner_deduplication():
    mock_scanner: MockBleakScanner | None = None

    def scanner_factory(detection_callback, service_uuids):
        nonlocal mock_scanner
        mock_scanner = MockBleakScanner(detection_callback, service_uuids)
        return mock_scanner

    scanner = BLEScanner(scanner_factory=scanner_factory)
    await scanner.start()
    assert mock_scanner is not None

    mock_scanner.emit_device(address="AA:BB:CC:DD:EE:FF", rssi=-60)
    assert len(scanner.discovered_peers) == 1
    assert scanner.discovered_peers["AA:BB:CC:DD:EE:FF"].rssi == -60

    # Second advertisement with updated RSSI
    mock_scanner.emit_device(address="AA:BB:CC:DD:EE:FF", rssi=-45)
    assert len(scanner.discovered_peers) == 1
    assert scanner.discovered_peers["AA:BB:CC:DD:EE:FF"].rssi == -45

    await scanner.stop()


@pytest.mark.asyncio
async def test_scanner_start_failure():
    def failing_factory(detection_callback, service_uuids):
        m = MockBleakScanner(detection_callback, service_uuids)
        m.should_fail_start = True
        return m

    scanner = BLEScanner(scanner_factory=failing_factory)
    with pytest.raises(BLEScanError, match="Failed to start BLE scanner"):
        await scanner.start()

    assert not scanner.is_scanning


@pytest.mark.asyncio
async def test_scanner_bounded_scan():
    def scanner_factory(detection_callback, service_uuids):
        m = MockBleakScanner(detection_callback, service_uuids)
        # Emit a device immediately upon creation
        m.emit_device(address="AA:00:11:22:33:44")
        return m

    scanner = BLEScanner(scanner_factory=scanner_factory)
    results = await scanner.scan(timeout=0.01)
    assert len(results) == 1
    assert results[0].address == "AA:00:11:22:33:44"
    assert not scanner.is_scanning
