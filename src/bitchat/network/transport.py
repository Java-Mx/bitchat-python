"""LAN/Wi-Fi transport implementation using UDP discovery and framed TCP."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from bitchat.network.adapter import NetworkAdapterManager
from bitchat.network.connection import LANConnection
from bitchat.network.discovery import LANDiscovery
from bitchat.network.server import LANServer
from bitchat.transport.base import (
    BaseTransport,
    TransportState,
    TransportType,
)

if TYPE_CHECKING:
    from bitchat.network.models import NetworkInfo
    from bitchat.protocol.packet import BitchatPacket

logger = logging.getLogger(__name__)


class LANTransport(BaseTransport):
    """Orchestrates local network discovery, TCP listening,
    and framed message transport.
    """

    def __init__(
        self,
        local_peer_id: str,
        local_nickname: str = "Anonymous",
        tcp_port: int = 41235,
        discovery_port: int = 41234,
        adapter_manager: NetworkAdapterManager | None = None,
    ) -> None:
        super().__init__()
        self.local_peer_id = local_peer_id
        self.local_nickname = local_nickname
        self.tcp_port = tcp_port
        self.discovery_port = discovery_port

        self.adapter_manager = adapter_manager or NetworkAdapterManager(
            on_network_changed=self._handle_network_changed
        )
        self.server = LANServer(
            port=tcp_port,
            on_connection_accepted=self._handle_inbound_connection,
        )
        self.discovery = LANDiscovery(
            local_peer_id=local_peer_id,
            local_nickname=local_nickname,
            listening_port=tcp_port,
            discovery_port=discovery_port,
            on_peer_discovered=self._handle_peer_discovered,
        )

        self._connections: dict[str, LANConnection] = {}
        self._is_running: bool = False
        self._state: TransportState = TransportState.OFFLINE
        self._error_message: str | None = None
        self._lock = asyncio.Lock()
        self._background_tasks: set[asyncio.Task[Any]] = set()

    @property
    def transport_type(self) -> TransportType:
        return TransportType.LAN

    @property
    def state(self) -> TransportState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def connected_peers(self) -> list[str]:
        return [addr for addr, conn in self._connections.items() if conn.is_ready]

    @property
    def discovered_peers(self) -> dict[str, Any]:
        return self.discovery.discovered_peers

    def _set_state(self, new_state: TransportState) -> None:
        if self._state != new_state:
            self._state = new_state
            if self.on_state_changed:
                with contextlib.suppress(Exception):
                    self.on_state_changed(new_state)

    def _handle_peer_discovered(self, peer: Any) -> None:
        if self._state == TransportState.SCANNING:
            self._set_state(TransportState.PEER_FOUND)
        if self.on_peer_discovered:
            self.on_peer_discovered(peer)

    def _spawn_task(self, coro: Any) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def _handle_inbound_connection(self, connection: LANConnection) -> None:
        """Wire up callbacks for an inbound TCP peer connection
        accepted by LANServer.
        """
        connection.on_packet_received = self._handle_packet_received
        connection.on_disconnected = self._handle_peer_disconnected

        self._connections[connection.peer_address] = connection
        self._set_state(TransportState.CONNECTED)
        if self.on_peer_connected:
            self.on_peer_connected(connection.peer_address)

    def _handle_peer_disconnected(self, peer_address: str) -> None:
        """Handle peer disconnection from either inbound or outbound socket."""
        self._connections.pop(peer_address, None)
        if not self.connected_peers:
            self._set_state(
                TransportState.SCANNING
                if self.discovery.is_running
                else TransportState.READY
            )
        if self.on_peer_disconnected:
            self.on_peer_disconnected(peer_address)

    def _handle_packet_received(self, packet: BitchatPacket, peer_address: str) -> None:
        if self.on_packet_received:
            self.on_packet_received(packet, peer_address)

    def _handle_network_changed(self, info: NetworkInfo) -> None:
        """Handle host network adapter changes (Wi-Fi disconnect/reconnect,
        IP change).
        """
        logger.info(
            "LANTransport network change: status=%s, interface=%s, ip=%s",
            info.status,
            info.interface,
            info.local_ip,
        )
        self.discovery.ssid = info.ssid
        if not info.is_connected:
            self._set_state(TransportState.UNAVAILABLE)
            self._error_message = "Local network is disconnected."
            if self.on_error:
                self.on_error(self._error_message)
        else:
            if self._state in (TransportState.UNAVAILABLE, TransportState.ERROR):
                self._set_state(TransportState.READY)
                # Restart discovery beacon
                self._spawn_task(self.discovery.send_broadcast_now())

    async def start(self) -> None:
        """Start network adapter monitoring, TCP server, and discovery beacon."""
        if self._is_running:
            return

        self._is_running = True
        self._set_state(TransportState.CHECKING)
        self._error_message = None

        # 1. Inspect network environment
        info = self.adapter_manager.refresh()
        self.discovery.ssid = info.ssid

        # 2. Start TCP server
        try:
            await self.server.start()
            self.discovery.update_listening_port(self.server.bound_port)
        except Exception as e:
            logger.warning("Could not start LAN TCP server: %s", e)
            self._set_state(TransportState.ERROR)
            self._error_message = f"LAN server failed: {e}"
            if self.on_error:
                self.on_error(self._error_message)
            raise RuntimeError(self._error_message) from e

        # 3. Start discovery
        try:
            await self.discovery.start()
            self._set_state(TransportState.SCANNING)
        except Exception as e:
            logger.warning("Could not start LAN discovery: %s", e)
            self._set_state(TransportState.ERROR)
            self._error_message = f"LAN discovery failed: {e}"
            if self.on_error:
                self.on_error(self._error_message)
            raise RuntimeError(self._error_message) from e

        # 4. Start network adapter monitor
        await self.adapter_manager.start_monitoring(
            listening_port=self.server.bound_port, discovery_active=True
        )

    async def stop(self) -> None:
        """Cleanly stop discovery, TCP server, and disconnect all peers."""
        if not self._is_running:
            return

        self._is_running = False
        self._set_state(TransportState.OFFLINE)
        self._error_message = None

        await self.adapter_manager.stop_monitoring()
        await self.discovery.stop()
        await self.server.stop()

        for task in list(self._background_tasks):
            task.cancel()
        self._background_tasks.clear()

        async with self._lock:
            conns = list(self._connections.values())
            self._connections.clear()

        for conn in conns:
            with contextlib.suppress(Exception):
                await conn.close()

    async def start_discovery(self) -> None:
        await self.discovery.start()
        self._set_state(TransportState.SCANNING)

    async def stop_discovery(self) -> None:
        await self.discovery.stop()
        if self._state in (TransportState.SCANNING, TransportState.PEER_FOUND):
            self._set_state(TransportState.READY)

    async def connect_peer(self, address: str, timeout: float = 10.0) -> LANConnection:
        """Connect to peer at 'ip:port' or return existing connection."""
        self._set_state(TransportState.CONNECTING)

        async with self._lock:
            existing = self._connections.get(address)
            if existing and existing.is_ready:
                self._set_state(TransportState.CONNECTED)
                return existing

            conn = LANConnection(
                peer_address=address,
                on_packet_received=self._handle_packet_received,
                on_disconnected=self._handle_peer_disconnected,
                connect_timeout=timeout,
            )
            self._connections[address] = conn

        try:
            await conn.connect()
            self._set_state(TransportState.CONNECTED)
            if self.on_peer_connected:
                self.on_peer_connected(address)
            return conn
        except Exception:
            async with self._lock:
                self._connections.pop(address, None)
            self._set_state(
                TransportState.SCANNING
                if self.discovery.is_running
                else TransportState.READY
            )
            raise

    async def disconnect_peer(self, address: str) -> None:
        async with self._lock:
            conn = self._connections.pop(address, None)
        if conn:
            await conn.close()
        if not self.connected_peers:
            self._set_state(
                TransportState.SCANNING
                if self.discovery.is_running
                else TransportState.READY
            )

    async def send_to_peer(self, address: str, packet: BitchatPacket) -> None:
        conn = self._connections.get(address)
        if not conn or not conn.is_ready:
            # Auto-connect if discovered
            conn = await self.connect_peer(address)
        await conn.send_packet(packet)

    async def broadcast_packet(
        self, packet: BitchatPacket, exclude_address: str | None = None
    ) -> None:
        tasks = []
        for addr, conn in list(self._connections.items()):
            if (exclude_address is None or addr != exclude_address) and conn.is_ready:
                tasks.append(conn.send_packet(packet))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def update_identity(self, peer_id_hex: str, nickname: str) -> None:
        self.local_peer_id = peer_id_hex
        self.local_nickname = nickname
        self.discovery.update_identity(peer_id_hex, nickname)

    def resolve_peer_id_to_address(self, target: str) -> str | None:
        clean = target.strip().lstrip("@").lower()

        # 1. Direct IP:port check
        if ":" in clean:
            parts = clean.split(":")
            if len(parts) == 2 and parts[1].isdigit():
                return clean

        # 2. Check discovered peers by peer ID prefix or nickname
        for addr, peer in self.discovery.discovered_peers.items():
            if peer.peer_id and (
                peer.peer_id.lower() == clean or peer.peer_id.lower().startswith(clean)
            ):
                return addr
            if peer.nickname and (
                peer.nickname.lower() == clean or clean in peer.nickname.lower()
            ):
                return addr

        return None

    def get_telemetry(self) -> dict[str, Any]:
        info = self.adapter_manager.current_info
        return {
            "transport": "lan",
            "state": self._state.value,
            "status": info.status,
            "interface": info.interface,
            "ssid": info.ssid,
            "local_ip": info.local_ip,
            "listening_address": f"0.0.0.0:{self.server.bound_port}",
            "listening_port": self.server.bound_port,
            "discovery": "Active" if self.discovery.is_running else "Stopped",
            "discovered_peers_count": len(self.discovered_peers),
            "connected_peers_count": len(self.connected_peers),
            "connected_peers": self.connected_peers,
            "discovered_peers": self.discovered_peers,
            "error_message": self._error_message,
        }
