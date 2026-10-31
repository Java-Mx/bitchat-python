"""LAN/Wi-Fi transport implementation using UDP discovery and framed TCP."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from bitchat.network.adapter import NetworkAdapterManager, is_local_ip
from bitchat.network.connection import LANConnection
from bitchat.network.discovery import LANDiscovery
from bitchat.network.server import MAX_CONCURRENT_CONNECTIONS, LANServer
from bitchat.transport.base import (
    BaseTransport,
    TransportState,
    TransportType,
    format_connection_failure,
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
        max_connections: int = MAX_CONCURRENT_CONNECTIONS,
    ) -> None:
        super().__init__()
        self.local_peer_id = local_peer_id
        self.local_nickname = local_nickname
        self.tcp_port = tcp_port
        self.discovery_port = discovery_port
        self.max_connections = max_connections

        self.adapter_manager = adapter_manager or NetworkAdapterManager(
            on_network_changed=self._handle_network_changed
        )
        self.server = LANServer(
            port=tcp_port,
            on_connection_accepted=self._handle_inbound_connection,
            max_connections=max_connections,
        )
        self.discovery = LANDiscovery(
            local_peer_id=local_peer_id,
            local_nickname=local_nickname,
            listening_port=tcp_port,
            discovery_port=discovery_port,
            on_peer_discovered=self._handle_peer_discovered,
        )

        self._connections: dict[str, LANConnection] = {}
        self._peer_connections: dict[str, LANConnection] = {}
        self._address_to_peer_key: dict[str, str] = {}
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
        seen_conns: set[LANConnection] = set()
        peers: list[str] = []
        for addr, conn in self._connections.items():
            if conn.is_ready and conn not in seen_conns:
                seen_conns.add(conn)
                peers.append(addr)
        return peers

    @property
    def discovered_peers(self) -> dict[str, Any]:
        return self.discovery.discovered_peers

    @property
    def is_scanning(self) -> bool:
        return self.discovery.is_running and self.discovery.is_listening

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

    def _get_peer_key(self, address: str, peer_id: str | None = None) -> str:
        """Resolve a canonical peer key for deduplication."""
        if peer_id:
            return f"peer:{peer_id.lower()}"

        disc_peer = self.discovery.discovered_peers.get(address)
        if disc_peer and disc_peer.peer_id:
            return f"peer:{disc_peer.peer_id.lower()}"

        ip = address.split(":", 1)[0] if ":" in address else address
        if not ip.startswith("127."):
            for p in self.discovery.discovered_peers.values():
                if p.ip == ip and p.peer_id:
                    return f"peer:{p.peer_id.lower()}"
            return f"ip:{ip}"

        return f"addr:{address}"

    def _get_remote_id(self, peer_key: str, address: str) -> str:
        """Return remote peer ID if available, otherwise remote address."""
        if peer_key.startswith("peer:"):
            return peer_key[5:]
        return address

    def _should_keep_outbound(self, remote_id: str, remote_addr: str) -> bool:
        """Deterministically determine whether local node keeps outbound connection.

        The peer with lexicographically lower peer ID acts as initiator
        (keeps outbound).
        """
        local_id = self.local_peer_id.lower() if self.local_peer_id else ""
        if local_id and remote_id and local_id != remote_id:
            return local_id < remote_id.lower()
        local_port = self.server.bound_port
        local_ip = self.adapter_manager.current_info.local_ip or "0.0.0.0"
        local_endpoint = f"{local_ip}:{local_port}"
        return local_endpoint < remote_addr

    def _find_existing_connection(self, address: str) -> LANConnection | None:
        """Find an existing active connection to the peer specified by address."""
        conn = self._connections.get(address)
        if conn and conn.is_ready:
            return conn

        peer_key = self._get_peer_key(address)
        conn = self._peer_connections.get(peer_key)
        if conn and conn.is_ready:
            return conn

        ip = address.split(":", 1)[0] if ":" in address else address
        if not ip.startswith("127."):
            for c in list(self._connections.values()):
                if not c.is_ready:
                    continue
                c_ip = (
                    c.peer_address.split(":", 1)[0]
                    if ":" in c.peer_address
                    else c.peer_address
                )
                if c_ip == ip:
                    return c

        return None

    def _remove_connection_references(self, conn: LANConnection) -> None:
        """Remove all mapping references to a connection."""
        to_remove = [k for k, v in self._connections.items() if v is conn]
        for k in to_remove:
            self._connections.pop(k, None)
            self._address_to_peer_key.pop(k, None)
        peer_keys_to_remove = [
            k for k, v in self._peer_connections.items() if v is conn
        ]
        for k in peer_keys_to_remove:
            self._peer_connections.pop(k, None)

    def _handle_inbound_connection(self, connection: LANConnection) -> None:
        """Wire up callbacks for an inbound TCP peer connection
        accepted by LANServer with deduplication against concurrent connections.
        """
        if len(self._connections) >= self.max_connections:
            self._spawn_task(connection.close())
            return

        peer_key = self._get_peer_key(connection.peer_address)
        existing = self._find_existing_connection(connection.peer_address)
        if existing and existing.is_ready and existing is not connection:
            if existing.is_inbound:
                logger.info(
                    "Dropping duplicate inbound connection from %s",
                    connection.peer_address,
                )
                self._spawn_task(connection.close())
                return
            else:
                remote_id = self._get_remote_id(peer_key, connection.peer_address)
                if self._should_keep_outbound(remote_id, connection.peer_address):
                    logger.info(
                        "Deduplicating connection to %s: keeping outbound, "
                        "dropping inbound %s",
                        existing.peer_address,
                        connection.peer_address,
                    )
                    self._spawn_task(connection.close())
                    return
                else:
                    logger.info(
                        "Deduplicating connection to %s: keeping inbound %s, "
                        "dropping outbound",
                        existing.peer_address,
                        connection.peer_address,
                    )
                    self._spawn_task(existing.close())
                    self._remove_connection_references(existing)

        connection.on_packet_received = self._handle_packet_received
        server_disconnected = connection.on_disconnected

        def handle_disconnected(peer_address: str) -> None:
            try:
                if server_disconnected:
                    server_disconnected(peer_address)
            finally:
                self._handle_peer_disconnected(peer_address)

        connection.on_disconnected = handle_disconnected

        self._connections[connection.peer_address] = connection
        self._peer_connections[peer_key] = connection
        self._address_to_peer_key[connection.peer_address] = peer_key

        self._set_state(TransportState.CONNECTED)
        if self.on_peer_connected:
            self.on_peer_connected(connection.peer_address)

    def is_inbound_connection(self, peer_address: str) -> bool:
        """Return whether an active connection was accepted by this listener."""
        connection = self._connections.get(peer_address)
        return connection is not None and connection.is_inbound

    def _handle_peer_disconnected(self, peer_address: str) -> None:
        """Handle peer disconnection from either inbound or outbound socket."""
        conn = self._connections.get(peer_address)
        if conn:
            self._remove_connection_references(conn)
        else:
            self._connections.pop(peer_address, None)
            self._address_to_peer_key.pop(peer_address, None)

        if not self.connected_peers:
            self._set_state(
                TransportState.SCANNING
                if self.discovery.is_running
                else TransportState.READY
            )
        if self.on_peer_disconnected:
            self.on_peer_disconnected(peer_address)

    def _handle_packet_received(self, packet: BitchatPacket, peer_address: str) -> None:
        sender_id_hex = packet.sender_id.hex()
        conn = self._connections.get(peer_address)
        if conn:
            conn.peer_id = sender_id_hex
        peer_key = f"peer:{sender_id_hex.lower()}"
        self._address_to_peer_key[peer_address] = peer_key

        existing = self._peer_connections.get(peer_key)
        if (
            existing
            and existing is not conn
            and existing.is_ready
            and conn
            and conn.is_ready
        ):
            if self._should_keep_outbound(sender_id_hex, peer_address):
                to_keep = existing if not existing.is_inbound else conn
                to_drop = conn if not existing.is_inbound else existing
            else:
                to_keep = existing if existing.is_inbound else conn
                to_drop = conn if existing.is_inbound else existing

            if to_drop is not to_keep:
                logger.info(
                    "Packet-driven deduplication for peer %s: keeping %s, dropping %s",
                    sender_id_hex,
                    to_keep.peer_address,
                    to_drop.peer_address,
                )
                self._spawn_task(to_drop.close())
                self._remove_connection_references(to_drop)
                self._peer_connections[peer_key] = to_keep
        elif conn and conn.is_ready:
            self._peer_connections[peer_key] = conn

        if self.on_packet_received:
            self.on_packet_received(packet, peer_address)

    def _handle_network_changed(self, info: NetworkInfo) -> None:
        """Handle host network adapter changes (Wi-Fi disconnect/reconnect,
        IP change).
        """
        if not self._is_running and self._state == TransportState.OFFLINE:
            return

        logger.info(
            "LANTransport network change: status=%s, interface=%s, ip=%s",
            info.status,
            info.interface,
            info.local_ip,
        )
        self.discovery.ssid = (
            info.ssid if info.ssid and info.ssid.lower() != "unavailable" else ""
        )
        if not info.is_connected:
            self._set_state(TransportState.UNAVAILABLE)
            self._error_message = "Local network is disconnected."
            if self.on_error:
                self.on_error(self._error_message)
            self._spawn_task(self._pause_lan_services())
        else:
            if self._state in (TransportState.UNAVAILABLE, TransportState.ERROR):
                self._spawn_task(self._resume_lan_services())
            elif self.on_state_changed:
                with contextlib.suppress(Exception):
                    self.on_state_changed(self._state)

    def is_available(self) -> bool:
        """Return True if host network interface is connected with usable IP."""
        return self.adapter_manager.current_info.is_connected

    async def _pause_lan_services(self) -> None:
        """Stop discovery and listening when the host network is gone."""
        with contextlib.suppress(Exception):
            await self.discovery.stop()
        with contextlib.suppress(Exception):
            await self.server.stop()

    async def _resume_lan_services(self) -> None:
        """Restart LAN sockets after the host network returns."""
        try:
            if not self.server.is_listening:
                await self.server.start()
                self.discovery.update_listening_port(self.server.bound_port)
            if not self.discovery.is_running:
                await self.discovery.start()
            self._is_running = True
            self._error_message = None
            self._set_state(TransportState.SCANNING)
        except Exception as e:
            self._set_state(TransportState.ERROR)
            self._error_message = f"LAN recovery failed: {e}"
            if self.on_error:
                self.on_error(self._error_message)

    async def _release_partial_start(self) -> None:
        """Stop services a failed ``start()`` may already have brought up."""
        for label, stop in (
            ("discovery", self.discovery.stop),
            ("TCP server", self.server.stop),
        ):
            try:
                await stop()
            except Exception as e:
                logger.warning(
                    "Failed releasing LAN %s after failed start: %s", label, e
                )

    async def start(self) -> None:
        """Start network adapter monitoring, TCP server, and discovery beacon."""
        async with self._lock:
            if self._is_running:
                return

            self._is_running = True
            self._set_state(TransportState.CHECKING)
            self._error_message = None

            # 1. Inspect network environment
            info = self.adapter_manager.refresh()
            self.discovery.ssid = (
                info.ssid if info.ssid and info.ssid.lower() != "unavailable" else ""
            )

            if not info.is_connected:
                await self.adapter_manager.start_monitoring(
                    listening_port=0, discovery_active=False
                )
                self._is_running = False
                self._set_state(TransportState.UNAVAILABLE)
                self._error_message = "Local network is disconnected."
                if self.on_error:
                    self.on_error(self._error_message)
                raise RuntimeError(self._error_message)

            # 2. Start TCP server
            try:
                await self.server.start()
                self.discovery.update_listening_port(self.server.bound_port)
            except Exception as e:
                self._is_running = False
                logger.warning("Could not start LAN TCP server: %s", e)
                await self._release_partial_start()
                self._set_state(TransportState.ERROR)
                self._error_message = f"LAN server failed: {e}"
                if self.on_error:
                    self.on_error(self._error_message)
                raise RuntimeError(self._error_message) from e

            # 3. Start discovery
            try:
                await self.discovery.start()
            except Exception as e:
                self._is_running = False
                logger.warning("Could not start LAN discovery: %s", e)
                await self._release_partial_start()
                self._set_state(TransportState.ERROR)
                self._error_message = f"LAN discovery failed: {e}"
                if self.on_error:
                    self.on_error(self._error_message)
                raise RuntimeError(self._error_message) from e

            # 4. Start network adapter monitor
            await self.adapter_manager.start_monitoring(
                listening_port=self.server.bound_port, discovery_active=True
            )
            self._set_state(TransportState.SCANNING)

    async def stop(self) -> None:
        """Cleanly stop discovery, TCP server, and disconnect all peers."""
        async with self._lock:
            self._is_running = False
            self._set_state(TransportState.OFFLINE)
            self._error_message = None

            bg_tasks = list(self._background_tasks)
            for task in bg_tasks:
                task.cancel()
            if bg_tasks:
                await asyncio.gather(*bg_tasks, return_exceptions=True)
            self._background_tasks.clear()

            await self.adapter_manager.stop_monitoring()
            await self.discovery.stop()
            await self.server.stop()

            conns = list(set(self._connections.values()))
            self._connections.clear()
            self._peer_connections.clear()
            self._address_to_peer_key.clear()

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
        # Reject self-connection to local listening endpoint
        try:
            parts = address.split(":", 1)
            target_ip = parts[0].strip()
            target_port = int(parts[1]) if len(parts) > 1 else self.server.bound_port
            if (
                self.server.bound_port
                and target_port == self.server.bound_port
                and is_local_ip(target_ip)
            ):
                logger.debug(
                    "Self-connection rejected: target %s is local endpoint",
                    address,
                )
                raise ValueError(
                    f"Cannot connect to local listening endpoint: {address}"
                )
        except ValueError:
            raise
        except Exception:
            pass

        if self._state in (
            TransportState.UNAVAILABLE,
            TransportState.DISABLED,
            TransportState.OFFLINE,
            TransportState.ERROR,
        ):
            raise RuntimeError("Connection failed: transport unavailable")

        self._set_state(TransportState.CONNECTING)

        # Reuse existing connection if one is already active to this peer
        existing = self._find_existing_connection(address)
        if existing and existing.is_ready:
            self._set_state(TransportState.CONNECTED)
            async with self._lock:
                self._connections[address] = existing
                peer_key = self._get_peer_key(address)
                self._peer_connections[peer_key] = existing
                self._address_to_peer_key[address] = peer_key
            logger.debug(
                "Reusing existing connection %s for target %s",
                existing.peer_address,
                address,
            )
            return existing

        async with self._lock:
            existing = self._connections.get(address)
            if existing and existing.is_ready:
                self._set_state(TransportState.CONNECTED)
                return existing
            if len(self._connections) >= self.max_connections:
                self._set_state(
                    TransportState.CONNECTED
                    if self._connections
                    else TransportState.READY
                )
                raise RuntimeError("Maximum LAN connection limit reached")

            conn = LANConnection(
                peer_address=address,
                on_packet_received=self._handle_packet_received,
                on_disconnected=self._handle_peer_disconnected,
                connect_timeout=timeout,
            )
            self._connections[address] = conn
            peer_key = self._get_peer_key(address)
            self._peer_connections[peer_key] = conn
            self._address_to_peer_key[address] = peer_key

        try:
            await conn.connect()
            self._set_state(TransportState.CONNECTED)
            if self.on_peer_connected:
                self.on_peer_connected(address)
            return conn
        except Exception as e:
            async with self._lock:
                self._remove_connection_references(conn)
            self._set_state(
                TransportState.SCANNING
                if self.discovery.is_running
                else TransportState.READY
            )
            raise RuntimeError(format_connection_failure(e)) from e

    async def disconnect_peer(self, address: str) -> None:
        async with self._lock:
            conn = self._connections.get(address)
            if conn:
                self._remove_connection_references(conn)
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
        sent_connections: set[LANConnection] = set()
        sent_peer_keys: set[str] = set()
        for addr, conn in list(self._connections.items()):
            if not conn.is_ready or conn in sent_connections:
                continue
            if exclude_address is not None and (
                addr == exclude_address
                or getattr(conn, "peer_address", "") == exclude_address
            ):
                continue

            peer_key = self._address_to_peer_key.get(addr) or self._get_peer_key(
                conn.peer_address
            )
            if peer_key in sent_peer_keys:
                continue

            sent_peer_keys.add(peer_key)
            sent_connections.add(conn)
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
        network_ok = info.is_connected
        return {
            "transport": "lan",
            "state": self._state.value,
            "status": info.status,
            "interface": info.interface,
            "ssid": info.ssid if info.ssid else "unavailable",
            "local_ip": info.local_ip if info.local_ip else "unavailable",
            "listening_address": f"0.0.0.0:{self.server.bound_port}",
            "listening_port": self.server.bound_port,
            "discovery": "Active"
            if (self.discovery.is_running and network_ok)
            else "Stopped",
            "listening": "Active"
            if (self.server.is_listening and network_ok)
            else "Stopped",
            "discovered_peers_count": len(self.discovered_peers),
            "connected_peers_count": len(self.connected_peers),
            "connected_peers": self.connected_peers,
            "discovered_peers": self.discovered_peers,
            "error_message": self._error_message,
        }
