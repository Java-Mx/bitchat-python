"""BLE scanner for discovering BitChat peers."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from bleak import BleakScanner

from bitchat.ble.models import DiscoveredPeer
from bitchat.exceptions import BLEScanError
from bitchat.protocol.constants import BITCHAT_SERVICE_UUID

if TYPE_CHECKING:
    from collections.abc import Callable

    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData

logger = logging.getLogger(__name__)


class BLEScanner:
    """Asynchronous BLE scanner filtered for BitChat peripherals."""

    def __init__(
        self,
        service_uuid: str = BITCHAT_SERVICE_UUID,
        on_peer_discovered: Callable[[DiscoveredPeer], None] | None = None,
        scanner_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.service_uuid = service_uuid.lower()
        self.on_peer_discovered = on_peer_discovered
        self._scanner_factory = scanner_factory or BleakScanner
        self._scanner: Any | None = None
        self._discovered_peers: dict[str, DiscoveredPeer] = {}
        self._is_scanning: bool = False
        self._lock = asyncio.Lock()

    @property
    def is_scanning(self) -> bool:
        """Return True if scanning is currently active."""
        return self._is_scanning

    @property
    def discovered_peers(self) -> dict[str, DiscoveredPeer]:
        """Return a copy of all discovered BitChat peers."""
        return self._discovered_peers.copy()

    def clear(self) -> None:
        """Clear discovered peer cache."""
        self._discovered_peers.clear()

    def _detection_callback(
        self, device: BLEDevice, advertisement_data: AdvertisementData
    ) -> None:
        """Handle incoming BLE advertisement detection."""
        adv_uuids = [str(u).lower() for u in (advertisement_data.service_uuids or [])]

        # Match BitChat service UUID
        if adv_uuids and self.service_uuid not in adv_uuids:
            return

        addr = device.address
        name = advertisement_data.local_name or device.name
        rssi = advertisement_data.rssi or getattr(device, "rssi", -100) or -100

        peer = DiscoveredPeer(
            address=addr,
            name=name,
            rssi=rssi,
            service_uuids=tuple(adv_uuids),
            last_seen=time.time(),
        )

        self._discovered_peers[addr] = peer
        logger.debug("Discovered BitChat peer: %s (name=%s, rssi=%d)", addr, name, rssi)

        if self.on_peer_discovered:
            try:
                self.on_peer_discovered(peer)
            except Exception as e:
                logger.warning("Error in on_peer_discovered callback: %s", e)

    async def start(self) -> None:
        """Start asynchronous BLE scanning."""
        async with self._lock:
            if self._is_scanning:
                return

            try:
                scanner = self._scanner_factory(
                    detection_callback=self._detection_callback,
                    service_uuids=[self.service_uuid],
                )
                self._scanner = scanner
                await scanner.start()
                self._is_scanning = True
                logger.info("BLE scanning started for service %s", self.service_uuid)
            except Exception as e:
                self._is_scanning = False
                self._scanner = None
                raise BLEScanError(f"Failed to start BLE scanner: {e}") from e

    async def stop(self) -> None:
        """Stop asynchronous BLE scanning."""
        async with self._lock:
            if not self._is_scanning or self._scanner is None:
                self._is_scanning = False
                return

            try:
                await self._scanner.stop()
            except Exception as e:
                logger.warning("Error while stopping BLE scanner: %s", e)
            finally:
                self._is_scanning = False
                self._scanner = None
                logger.info("BLE scanning stopped")

    async def scan(self, timeout: float = 5.0) -> list[DiscoveredPeer]:
        """Perform a bounded scan for the specified duration and return results."""
        await self.start()
        try:
            await asyncio.sleep(timeout)
        finally:
            await self.stop()
        return list(self._discovered_peers.values())
