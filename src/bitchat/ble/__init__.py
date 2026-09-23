"""Bluetooth Low Energy (BLE) transport layer for BitChat."""

from bitchat.ble.connection import BLEConnection
from bitchat.ble.gatt import GATTManager
from bitchat.ble.manager import BLEManager
from bitchat.ble.models import BLEConnectionState, DiscoveredPeer
from bitchat.ble.scanner import BLEScanner
from bitchat.ble.transport import BLETransport
from bitchat.exceptions import (
    BLEConnectionError,
    BLEError,
    BLEGATTError,
    BLEScanError,
    BLETransportError,
)

__all__ = [
    "BLEConnection",
    "BLEConnectionError",
    "BLEConnectionState",
    "BLEError",
    "BLEGATTError",
    "BLEManager",
    "BLEScanError",
    "BLEScanner",
    "BLETransport",
    "BLETransportError",
    "DiscoveredPeer",
    "GATTManager",
]
