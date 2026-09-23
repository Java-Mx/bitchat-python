"""Tests for GATT discovery and validation."""

import pytest
from tests.ble.mocks import (
    MockBleakCharacteristic,
    MockBleakClient,
    MockBleakService,
)

from bitchat.ble.gatt import GATTManager
from bitchat.exceptions import BLEGATTError
from bitchat.protocol.constants import (
    BITCHAT_CHARACTERISTIC_UUID,
    BITCHAT_SERVICE_UUID,
)


@pytest.mark.asyncio
async def test_gatt_discover_success():
    service = MockBleakService(
        uuid=BITCHAT_SERVICE_UUID.lower(),
        characteristics=[
            MockBleakCharacteristic(uuid=BITCHAT_CHARACTERISTIC_UUID.lower())
        ],
    )
    client = MockBleakClient(address="11:22:33:44:55:66", services=[service])
    await client.connect()

    manager = GATTManager()
    char = await manager.discover(client)
    assert char.uuid.lower() == BITCHAT_CHARACTERISTIC_UUID.lower()


@pytest.mark.asyncio
async def test_gatt_case_insensitive_matching():
    # Service in UPPERCASE, Characteristic in UPPERCASE
    service = MockBleakService(
        uuid=BITCHAT_SERVICE_UUID.upper(),
        characteristics=[
            MockBleakCharacteristic(uuid=BITCHAT_CHARACTERISTIC_UUID.upper())
        ],
    )
    client = MockBleakClient(address="11:22:33:44:55:66", services=[service])
    await client.connect()

    manager = GATTManager()
    char = await manager.discover(client)
    assert char.uuid.lower() == BITCHAT_CHARACTERISTIC_UUID.lower()


@pytest.mark.asyncio
async def test_gatt_missing_service():
    unrelated_service = MockBleakService(
        uuid="0000180f-0000-1000-8000-00805f9b34fb",
        characteristics=[
            MockBleakCharacteristic(uuid="00002a19-0000-1000-8000-00805f9b34fb")
        ],
    )
    client = MockBleakClient(address="11:22:33:44:55:66", services=[unrelated_service])
    await client.connect()

    manager = GATTManager()
    with pytest.raises(BLEGATTError, match="BitChat service"):
        await manager.discover(client)


@pytest.mark.asyncio
async def test_gatt_missing_characteristic():
    service = MockBleakService(
        uuid=BITCHAT_SERVICE_UUID.lower(),
        characteristics=[
            MockBleakCharacteristic(uuid="00002a19-0000-1000-8000-00805f9b34fb")
        ],
    )
    client = MockBleakClient(address="11:22:33:44:55:66", services=[service])
    await client.connect()

    manager = GATTManager()
    with pytest.raises(BLEGATTError, match="BitChat characteristic"):
        await manager.discover(client)


@pytest.mark.asyncio
async def test_gatt_disconnected_client():
    client = MockBleakClient(address="11:22:33:44:55:66")
    manager = GATTManager()
    with pytest.raises(BLEGATTError, match="disconnected"):
        await manager.discover(client)
