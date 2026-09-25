"""High-level BLE manager coordinating discovery, connections, and transports."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from bitchat.ble.adapter import AdapterInfo, BLEAdapterManager
from bitchat.ble.connection import BLEConnection
from bitchat.ble.models import BLEState, DiscoveredPeer
from bitchat.ble.scanner import BLEScanner
from bitchat.ble.transport import BLETransport
from bitchat.exceptions import BLEConnectionError
from bitchat.protocol.constants import SENDER_ID_SIZE

if TYPE_CHECKING:
    from collections.abc import Callable

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
        on_adapter_state_changed: Callable[[AdapterInfo], None] | None = None,
        client_factory: Callable[..., Any] | None = None,
        scanner_factory: Callable[..., Any] | None = None,
        adapter_manager: BLEAdapterManager | None = None,
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
        self.on_adapter_state_changed = on_adapter_state_changed
        self._client_factory = client_factory

        self.adapter_manager = adapter_manager or BLEAdapterManager(
            on_state_changed=self._handle_adapter_state_changed
        )
        self.scanner = BLEScanner(
            on_peer_discovered=self._handle_peer_discovered,
            scanner_factory=scanner_factory,
        )
        self._transports: dict[str, BLETransport] = {}
        self._state: BLEState = BLEState.OFFLINE
        self._lock = asyncio.Lock()
        self._background_tasks: set[asyncio.Task[Any]] = set()

    @property
    def state(self) -> BLEState:
        """Return the current high-level BLE subsystem state."""
        return self._state

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

    def prune_stale_peers(self, max_age: float = 30.0) -> list[str]:
        """Prune discovered peers that haven't been seen recently."""
        return self.scanner.prune_stale_peers(max_age=max_age)

    def resolve_peer_id_to_address(self, peer_id_or_prefix: str) -> str | None:
        """Resolve a known peer ID or prefix to a discovered BLE MAC address."""
        clean = peer_id_or_prefix.strip().lower().lstrip("@")
        for addr, peer in self.discovered_peers.items():
            if peer.peer_id and (
                peer.peer_id.lower() == clean or peer.peer_id.lower().startswith(clean)
            ):
                return addr
            if peer.name and (peer.name.lower() == clean or clean in peer.name.lower()):
                return addr
        return None

    def get_telemetry(self) -> dict[str, Any]:
        """Return truthful telemetry dictionary for diagnostics."""
        adapter = self.adapter_manager.current_info
        return {
            "adapter_available": adapter.is_available,
            "adapter_enabled": adapter.is_enabled,
            "radio_state": adapter.radio_state,
            "scanner_active": self.scanner.is_scanning,
            "ble_state": self._state,
            "discovered_peers_count": len(self.discovered_peers),
            "connected_peers_count": len(self.connected_peers),
        }

    def _handle_adapter_state_changed(self, info: AdapterInfo) -> None:
        """React to hardware Bluetooth radio state changes."""
        logger.info(
            "BLEManager notified of adapter state change: %s (enabled=%s)",
            info.radio_state,
            info.is_enabled,
        )
        if not info.is_enabled:
            self._state = (
                BLEState.BLUETOOTH_DISABLED
                if info.radio_state in ("off", "disabled")
                else BLEState.BLUETOOTH_UNAVAILABLE
            )
            # Reconcile state: disconnect peers on adapter power loss
            reconcile_task = asyncio.create_task(self._reconcile_offline_state())
            self._background_tasks.add(reconcile_task)
            reconcile_task.add_done_callback(self._background_tasks.discard)
        else:
            if self._state in (
                BLEState.BLUETOOTH_DISABLED,
                BLEState.BLUETOOTH_UNAVAILABLE,
                BLEState.OFFLINE,
            ):
                self._state = BLEState.READY

        if self.on_adapter_state_changed:
            try:
                self.on_adapter_state_changed(info)
            except Exception as e:
                logger.warning("Error in on_adapter_state_changed callback: %s", e)

    async def _reconcile_offline_state(self) -> None:
        """Clean up active connections and scanner when Bluetooth goes offline."""
        logger.warning("Reconciling BLE state after adapter loss")
        with contextlib.suppress(Exception):
            await self.scanner.stop()
        transports = list(self._transports.values())
        self._transports.clear()
        for t in transports:
            with contextlib.suppress(Exception):
                await t.stop()

    def _handle_peer_discovered(self, peer: DiscoveredPeer) -> None:
        """Forward peer discovery events to listeners."""
        if self._state == BLEState.SCANNING:
            self._state = BLEState.PEER_FOUND
        if self.on_peer_discovered:
            try:
                self.on_peer_discovered(peer)
            except Exception as e:
                logger.warning("Error in on_peer_discovered callback: %s", e)

    def _handle_peer_disconnected(self, peer_address: str) -> None:
        """Handle peer disconnection and clean up local transport entry."""
        logger.info("Handling disconnect cleanup for %s", peer_address)
        self._transports.pop(peer_address, None)
        if not self._transports and self._state == BLEState.CONNECTED:
            self._state = BLEState.READY

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
        self._state = BLEState.SCANNING
        try:
            await self.scanner.start()
        except Exception:
            self._state = BLEState.ERROR
            raise

    async def stop_discovery(self) -> None:
        """Stop scanning for BitChat peers."""
        await self.scanner.stop()
        if self._state in (BLEState.SCANNING, BLEState.PEER_FOUND):
            self._state = BLEState.READY

    async def connect_peer(
        self, peer_address: str, timeout: float = 10.0
    ) -> BLETransport:
        """Establish a connection and transport to a specific BitChat peer."""
        prev_state = self._state
        self._state = BLEState.CONNECTING
        async with self._lock:
            existing = self._transports.get(peer_address)
            if existing and existing.connection.is_ready:
                self._state = BLEState.CONNECTED
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
            self._state = BLEState.CONNECTED
            if self.on_peer_connected:
                try:
                    self.on_peer_connected(peer_address)
                except Exception as e:
                    logger.warning("Error in on_peer_connected callback: %s", e)
            return transport
        except Exception:
            self._state = prev_state
            async with self._lock:
                self._transports.pop(peer_address, None)
            raise

    async def disconnect_peer(self, peer_address: str) -> None:
        """Disconnect and remove a specific connected peer."""
        transport = self._transports.pop(peer_address, None)
        if transport:
            await transport.stop()
        if not self._transports and self._state == BLEState.CONNECTED:
            self._state = BLEState.READY

    async def send_to_peer(self, peer_address: str, packet: BitchatPacket) -> None:
        """Send a packet directly to a specific connected peer."""
        transport = self._transports.get(peer_address)
        if not transport or not transport.connection.is_ready:
            raise BLEConnectionError(
                f"Peer {peer_address} is not connected or not ready"
            )
        await transport.send_packet(packet)

    async def broadcast_packet(
        self, packet: BitchatPacket, exclude_address: str | None = None
    ) -> None:
        """Broadcast a packet to all currently ready connected peers,
        optionally excluding one.
        """
        tasks = []
        for addr, transport in list(self._transports.items()):
            if (
                exclude_address is None or addr != exclude_address
            ) and transport.connection.is_ready:
                tasks.append(transport.send_packet(packet))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, Exception):
                    logger.warning("Error broadcasting packet to peer: %s", res)

    async def shutdown(self) -> None:
        """Cleanly stop adapter monitoring, scanner, and disconnect all peers."""
        for t in list(self._background_tasks):
            t.cancel()
        self._background_tasks.clear()
        await self.adapter_manager.stop_monitoring()
        await self.scanner.stop()
        transports = list(self._transports.values())
        self._transports.clear()
        stop_tasks = [t.stop() for t in transports]
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)
        self._state = BLEState.OFFLINE
