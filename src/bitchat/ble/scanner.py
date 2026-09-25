"""BLE scanner for discovering BitChat peers."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
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
    """Asynchronous BLE scanner strictly filtered for BitChat peripherals."""

    def __init__(
        self,
        service_uuid: str = BITCHAT_SERVICE_UUID,
        on_peer_discovered: Callable[[DiscoveredPeer], None] | None = None,
        on_peer_expired: Callable[[str], None] | None = None,
        scanner_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.service_uuid = service_uuid.lower()
        self.on_peer_discovered = on_peer_discovered
        self.on_peer_expired = on_peer_expired
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

    def prune_stale_peers(self, max_age: float = 30.0) -> list[str]:
        """Prune peers that have not been seen within max_age seconds."""
        now = time.time()
        stale_addrs = [
            addr
            for addr, peer in self._discovered_peers.items()
            if (now - peer.last_seen) > max_age
        ]
        for addr in stale_addrs:
            self._discovered_peers.pop(addr, None)
            logger.info("Pruned stale discovered peer: %s", addr)
            if self.on_peer_expired:
                try:
                    self.on_peer_expired(addr)
                except Exception as e:
                    logger.warning("Error in on_peer_expired callback: %s", e)
        return stale_addrs

    def _detection_callback(
        self, device: BLEDevice, advertisement_data: AdvertisementData
    ) -> None:
        """Handle incoming BLE advertisement detection with strict BitChat filtering."""
        adv_uuids = [str(u).lower() for u in (advertisement_data.service_uuids or [])]
        norm_target = self.service_uuid.lower().replace("-", "")

        is_bitchat = False
        extracted_peer_id: str | None = None
        extracted_nick: str | None = None

        # 1. Match BitChat service UUID in service_uuids
        for u in adv_uuids:
            if u.replace("-", "") == norm_target:
                is_bitchat = True
                break

        # 2. Match BitChat service UUID in service_data keys
        svc_data = getattr(advertisement_data, "service_data", None)
        if not is_bitchat and svc_data:
            for s_uuid, s_payload in svc_data.items():
                if str(s_uuid).lower().replace("-", "") == norm_target:
                    is_bitchat = True
                    if len(s_payload) >= 6:
                        extracted_peer_id = bytes(s_payload[:8]).hex()
                    break

        # 3. Match BitChat manufacturer signature in manufacturer_data
        mfg_data = getattr(advertisement_data, "manufacturer_data", None)
        if not is_bitchat and mfg_data:
            for company_id, m_payload in mfg_data.items():
                if company_id in (0xFFFF, 0x0000):
                    raw = bytes(m_payload)
                    srv_bytes = uuid.UUID(self.service_uuid).bytes
                    if raw.startswith(b"BC" + srv_bytes):
                        is_bitchat = True
                        rest = raw[18:]
                        if rest:
                            parts = rest.decode("utf-8", errors="ignore").split("|", 1)
                            extracted_peer_id = parts[0]
                            if len(parts) > 1:
                                extracted_nick = parts[1]
                        break

        # Strict filtering: ignore all non-BitChat devices!
        if not is_bitchat:
            return

        addr = device.address
        name = (
            extracted_nick
            or advertisement_data.local_name
            or getattr(device, "name", None)
            or "BitChat Node"
        )
        rssi = (
            advertisement_data.rssi
            if advertisement_data.rssi is not None
            else getattr(device, "rssi", -100) or -100
        )

        # Safe diagnostic logging (Section 8 & 21: no secrets/keys)
        logger.info(
            "Discovered BitChat peer: %s (name=%s, rssi=%d dBm, peer_id=%s)",
            addr,
            name,
            rssi,
            extracted_peer_id,
        )

        peer = DiscoveredPeer(
            address=addr,
            name=name,
            rssi=rssi,
            service_uuids=tuple(adv_uuids) if adv_uuids else (self.service_uuid,),
            last_seen=time.time(),
            peer_id=extracted_peer_id,
            nickname=extracted_nick,
        )

        self._discovered_peers[addr] = peer

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
                if self._scanner_factory is BleakScanner:
                    # BleakScanner without native service_uuids filter so
                    # WinRT does not drop manufacturer-only packets
                    scanner = BleakScanner(
                        detection_callback=self._detection_callback,
                    )
                else:
                    try:
                        scanner = self._scanner_factory(
                            detection_callback=self._detection_callback,
                            service_uuids=[self.service_uuid],
                        )
                    except TypeError:
                        scanner = self._scanner_factory(
                            detection_callback=self._detection_callback,
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
