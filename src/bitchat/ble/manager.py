"""High-level BLE manager coordinating discovery, connections, and transports."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from bitchat.ble.connection import BLEConnection
from bitchat.ble.scanner import BLEScanner
from bitchat.ble.transport import BLETransport
from bitchat.exceptions import BLEConnectionError
from bitchat.protocol.constants import SENDER_ID_SIZE

if TYPE_CHECKING:
    from collections.abc import Callable

    from bitchat.ble.models import DiscoveredPeer
    from bitchat.protocol.packet import BitchatPacket

logger = logging.getLogger(__name__)


class BLEManager:
    """Coordinates BLE discovery, multi-peer connections, and packet routing."""

    def __init__(
        self,
        sender_id: bytes,
        on_packet_received: Callable[[BitchatPacket, str], None] | None = None,
        on_peer_discovered: Callable[[DiscoveredPeer], None] | None = None,
        on_peer_connected: Callable[[str], None] | None = None,
        on_peer_disconnected: Callable[[str], None] | None = None,
        client_factory: Callable[..., Any] | None = None,
        scanner_factory: Callable[..., Any] | None = None,
    ) -> None:
        if len(sender_id) != SENDER_ID_SIZE:
            raise ValueError(
                f"sender_id must be {SENDER_ID_SIZE} bytes, got {len(sender_id)}"
            )

        self.sender_id = bytes(sender_id)
        self.on_packet_received = on_packet_received
        self.on_peer_discovered = on_peer_discovered
        self.on_peer_connected = on_peer_connected
        self.on_peer_disconnected = on_peer_disconnected
        self._client_factory = client_factory

        self.scanner = BLEScanner(
            on_peer_discovered=self._handle_peer_discovered,
            scanner_factory=scanner_factory,
        )
        self._transports: dict[str, BLETransport] = {}
        self._lock = asyncio.Lock()

    @property
    def discovered_peers(self) -> dict[str, DiscoveredPeer]:
        """Return all discovered peers from the scanner."""
        return self.scanner.discovered_peers

    @property
    def connected_peers(self) -> list[str]:
        """Return addresses of all currently ready connected peers."""
        return [
            addr
            for addr, transport in self._transports.items()
            if transport.connection.is_ready
        ]

    def _handle_peer_discovered(self, peer: DiscoveredPeer) -> None:
        """Forward peer discovery events to listeners."""
        if self.on_peer_discovered:
            try:
                self.on_peer_discovered(peer)
            except Exception as e:
                logger.warning("Error in on_peer_discovered callback: %s", e)

    def _handle_peer_disconnected(self, peer_address: str) -> None:
        """Handle peer disconnection and clean up local transport entry."""
        logger.info("Handling disconnect cleanup for %s", peer_address)
        self._transports.pop(peer_address, None)
        if self.on_peer_disconnected:
            try:
                self.on_peer_disconnected(peer_address)
            except Exception as e:
                logger.warning("Error in on_peer_disconnected callback: %s", e)

    def _handle_packet_received(
        self,
        packet: BitchatPacket,
        peer_address: str,
    ) -> None:
        """Forward incoming decoded packets to application listeners."""
        if self.on_packet_received:
            try:
                self.on_packet_received(packet, peer_address)
            except Exception as e:
                logger.error(
                    "Error in on_packet_received callback: %s", e, exc_info=True
                )

    async def start_discovery(self) -> None:
        """Start scanning for BitChat peers."""
        await self.scanner.start()

    async def stop_discovery(self) -> None:
        """Stop scanning for BitChat peers."""
        await self.scanner.stop()

    async def connect_peer(
        self, peer_address: str, timeout: float = 10.0
    ) -> BLETransport:
        """Establish a connection and transport to a specific BitChat peer."""
        async with self._lock:
            existing = self._transports.get(peer_address)
            if existing and existing.connection.is_ready:
                return existing

            connection = BLEConnection(
                peer_address=peer_address,
                disconnected_callback=self._handle_peer_disconnected,
                client_factory=self._client_factory,
                connect_timeout=timeout,
            )

            transport = BLETransport(
                connection=connection,
                sender_id=self.sender_id,
                on_packet_received=self._handle_packet_received,
            )

            self._transports[peer_address] = transport

        try:
            await transport.start()
            if self.on_peer_connected:
                try:
                    self.on_peer_connected(peer_address)
                except Exception as e:
                    logger.warning("Error in on_peer_connected callback: %s", e)
            return transport
        except Exception:
            async with self._lock:
                self._transports.pop(peer_address, None)
            raise

    async def disconnect_peer(self, peer_address: str) -> None:
        """Disconnect and remove a specific connected peer."""
        transport = self._transports.pop(peer_address, None)
        if transport:
            await transport.stop()

    async def send_to_peer(self, peer_address: str, packet: BitchatPacket) -> None:
        """Send a packet directly to a specific connected peer."""
        transport = self._transports.get(peer_address)
        if not transport or not transport.connection.is_ready:
            raise BLEConnectionError(
                f"Peer {peer_address} is not connected or not ready"
            )
        await transport.send_packet(packet)

    async def broadcast_packet(self, packet: BitchatPacket) -> None:
        """Broadcast a packet to all currently ready connected peers."""
        tasks = []
        for transport in list(self._transports.values()):
            if transport.connection.is_ready:
                tasks.append(transport.send_packet(packet))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, Exception):
                    logger.warning("Error broadcasting packet to peer: %s", res)

    async def shutdown(self) -> None:
        """Cleanly stop scanner and disconnect all peers."""
        await self.scanner.stop()
        transports = list(self._transports.values())
        self._transports.clear()
        stop_tasks = [t.stop() for t in transports]
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)
