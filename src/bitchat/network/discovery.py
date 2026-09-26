"""UDP multicast/broadcast peer discovery protocol with security bounds."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from bitchat.network.adapter import get_local_ip
from bitchat.network.models import DiscoveryPacket, LANDiscoveredPeer

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

DEFAULT_DISCOVERY_PORT: int = 41234
DEFAULT_BROADCAST_INTERVAL: float = 3.0
MAX_DISCOVERY_RATE_PER_IP: int = 10  # Packets per second per sender IP


class LANDiscovery:
    """Manages UDP broadcast announcement broadcasting and peer discovery."""

    def __init__(
        self,
        local_peer_id: str,
        local_nickname: str,
        listening_port: int,
        ssid: str = "",
        discovery_port: int = DEFAULT_DISCOVERY_PORT,
        broadcast_interval: float = DEFAULT_BROADCAST_INTERVAL,
        on_peer_discovered: Callable[[LANDiscoveredPeer], None] | None = None,
    ) -> None:
        self.local_peer_id = local_peer_id
        self.local_nickname = local_nickname
        self.listening_port = listening_port
        self.ssid = ssid
        self.discovery_port = discovery_port
        self.broadcast_interval = broadcast_interval
        self.on_peer_discovered = on_peer_discovered

        self._is_running: bool = False
        self._discovered_peers: dict[str, LANDiscoveredPeer] = {}
        self._rate_limiter: dict[str, list[float]] = defaultdict(list)
        self._broadcast_task: asyncio.Task[Any] | None = None
        self._listen_task: asyncio.Task[Any] | None = None
        self._listen_sock: socket.socket | None = None
        self._send_sock: socket.socket | None = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def is_listening(self) -> bool:
        return self._is_running and self._listen_sock is not None

    @property
    def discovered_peers(self) -> dict[str, LANDiscoveredPeer]:
        return self._discovered_peers.copy()

    def update_identity(self, peer_id: str, nickname: str, ssid: str = "") -> None:
        """Update identity advertised in outgoing beacons."""
        self.local_peer_id = peer_id
        self.local_nickname = nickname
        if ssid:
            self.ssid = ssid

    def update_listening_port(self, port: int) -> None:
        """Update TCP listening port announced to LAN peers."""
        self.listening_port = port

    async def start(self) -> None:
        """Initialize sockets and launch UDP listen and broadcast loops."""
        if self._is_running:
            return

        # 1. Setup send socket
        try:
            send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            send_sock.setblocking(False)
            self._send_sock = send_sock
        except Exception as e:
            logger.warning("Failed creating UDP discovery send socket: %s", e)

        # 2. Setup listen socket (required for real discovery)
        try:
            listen_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            listen_sock.setblocking(False)
            listen_sock.bind(("0.0.0.0", self.discovery_port))
            self._listen_sock = listen_sock
        except Exception as e:
            if self._send_sock:
                with contextlib.suppress(Exception):
                    self._send_sock.close()
                self._send_sock = None
            raise RuntimeError(
                f"Could not bind UDP discovery listen socket on port "
                f"{self.discovery_port}: {e}"
            ) from e

        self._is_running = True
        self._listen_task = asyncio.create_task(self._listen_loop())

        # 3. Launch periodic broadcaster
        self._broadcast_task = asyncio.create_task(self._broadcast_loop())
        # Immediate initial beacon
        await self.send_broadcast_now()

    async def stop(self) -> None:
        """Stop discovery loops and release sockets."""
        if not self._is_running:
            return

        self._is_running = False

        if self._broadcast_task:
            self._broadcast_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._broadcast_task
            self._broadcast_task = None

        if self._listen_task:
            self._listen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listen_task
            self._listen_task = None

        if self._listen_sock:
            with contextlib.suppress(Exception):
                self._listen_sock.close()
            self._listen_sock = None

        if self._send_sock:
            with contextlib.suppress(Exception):
                self._send_sock.close()
            self._send_sock = None

    async def send_broadcast_now(self) -> None:
        """Transmit an immediate discovery broadcast beacon."""
        if not self._send_sock or self.listening_port <= 0:
            return

        try:
            beacon = DiscoveryPacket(
                peer_id=self.local_peer_id,
                nickname=self.local_nickname,
                port=self.listening_port,
                ssid=self.ssid,
            )
            raw = beacon.to_bytes()
            loop = asyncio.get_running_loop()
            targets = ["255.255.255.255"]
            local_ip = get_local_ip()
            if local_ip and not local_ip.startswith("127."):
                parts = local_ip.split(".")
                if len(parts) == 4:
                    targets.append(f"{parts[0]}.{parts[1]}.{parts[2]}.255")
            for target_ip in dict.fromkeys(targets):
                with contextlib.suppress(Exception):
                    await loop.sock_sendto(
                        self._send_sock, raw, (target_ip, self.discovery_port)
                    )
        except Exception as e:
            logger.debug("Failed sending discovery broadcast: %s", e)

    async def _broadcast_loop(self) -> None:
        while self._is_running:
            try:
                await asyncio.sleep(self.broadcast_interval)
                if not self._is_running:
                    break
                await self.send_broadcast_now()
                self.prune_stale_peers()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Error in discovery broadcast loop: %s", e)

    async def _listen_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while self._is_running and self._listen_sock:
            try:
                data, addr = await loop.sock_recvfrom(self._listen_sock, 2048)
                self._process_incoming_packet(data, addr[0])
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._is_running:
                    logger.debug("Error in discovery listen loop: %s", e)
                    await asyncio.sleep(0.1)

    def _process_incoming_packet(
        self, data: bytes, sender_ip: str
    ) -> LANDiscoveredPeer | None:
        """Process incoming raw UDP bytes and register discovered peer if valid."""
        if self._is_rate_limited(sender_ip):
            return None

        packet = DiscoveryPacket.from_bytes(data)
        if packet is None:
            return None

        if packet.peer_id == self.local_peer_id:
            return None

        if sender_ip.startswith("127.") or sender_ip in ("localhost", "::1"):
            logger.debug("Ignoring loopback discovery packet from %s", sender_ip)
            return None

        endpoint = f"{sender_ip}:{packet.port}"
        peer = LANDiscoveredPeer(
            address=endpoint,
            ip=sender_ip,
            port=packet.port,
            peer_id=packet.peer_id,
            nickname=packet.nickname,
            ssid=packet.ssid,
            last_seen=time.time(),
        )
        self._discovered_peers[endpoint] = peer
        if self.on_peer_discovered:
            try:
                self.on_peer_discovered(peer)
            except Exception as e:
                logger.warning("Error in on_peer_discovered: %s", e)
        return peer

    def _is_rate_limited(self, ip: str, now: float | None = None) -> bool:
        current_time = time.time() if now is None else now
        timestamps = self._rate_limiter[ip]
        valid = [t for t in timestamps if current_time - t <= 1.0]
        self._rate_limiter[ip] = valid
        if len(valid) >= MAX_DISCOVERY_RATE_PER_IP:
            return True
        valid.append(current_time)
        return False

    def prune_stale_peers(self, max_age: float = 30.0) -> list[str]:
        """Prune peers not heard from within max_age seconds."""
        now = time.time()
        stale = [
            addr
            for addr, peer in self._discovered_peers.items()
            if peer.is_expired(ttl=max_age, now=now)
        ]
        for addr in stale:
            self._discovered_peers.pop(addr, None)
        return stale
