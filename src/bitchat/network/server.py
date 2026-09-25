"""TCP listener accepting incoming LAN peer connections."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from bitchat.network.connection import LANConnection

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

DEFAULT_LAN_PORT: int = 41235
MAX_CONCURRENT_CONNECTIONS: int = 32


class LANServer:
    """Manages the local inbound TCP server socket for BitChat LAN peers."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = DEFAULT_LAN_PORT,
        on_connection_accepted: Callable[[LANConnection], None] | None = None,
        max_connections: int = MAX_CONCURRENT_CONNECTIONS,
    ) -> None:
        self.host = host
        self.port = port
        self.on_connection_accepted = on_connection_accepted
        self.max_connections = max_connections

        self._server: asyncio.Server | None = None
        self._bound_port: int = 0
        self._is_listening: bool = False
        self._connections: dict[str, LANConnection] = {}
        self._lock = asyncio.Lock()

    @property
    def is_listening(self) -> bool:
        return self._is_listening

    @property
    def bound_port(self) -> int:
        return self._bound_port

    async def start(self) -> None:
        """Bind TCP socket and begin listening for incoming peer streams."""
        if self._is_listening:
            return

        try:
            self._server = await asyncio.start_server(
                self._handle_client,
                host=self.host,
                port=self.port,
            )
        except OSError:
            # Fallback to an ephemeral port if default port is in use
            logger.info("Port %d in use, binding to ephemeral port...", self.port)
            self._server = await asyncio.start_server(
                self._handle_client,
                host=self.host,
                port=0,
            )

        sockets = self._server.sockets
        if sockets:
            self._bound_port = sockets[0].getsockname()[1]
        self._is_listening = True
        logger.info("LAN server listening on %s:%d", self.host, self._bound_port)

    async def stop(self) -> None:
        """Stop listening and close all accepted incoming connections."""
        if not self._is_listening:
            return

        self._is_listening = False
        if self._server:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None

        async with self._lock:
            conns = list(self._connections.values())
            self._connections.clear()

        for conn in conns:
            with contextlib.suppress(Exception):
                await conn.close()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Process incoming client socket connection."""
        remote_addr = writer.get_extra_info("peername")
        if not remote_addr:
            writer.close()
            return

        host, port = remote_addr[0], remote_addr[1]
        peer_addr = f"{host}:{port}"

        async with self._lock:
            if len(self._connections) >= self.max_connections:
                logger.warning(
                    "Rejecting connection from %s: max connection limit (%d) reached",
                    peer_addr,
                    self.max_connections,
                )
                writer.close()
                with contextlib.suppress(Exception):
                    await writer.wait_closed()
                return

            conn = LANConnection(
                peer_address=peer_addr,
                reader=reader,
                writer=writer,
                on_disconnected=self._handle_client_disconnected,
            )
            self._connections[peer_addr] = conn

        logger.info("Accepted incoming LAN connection from %s", peer_addr)
        conn.start_reading()

        if self.on_connection_accepted:
            try:
                self.on_connection_accepted(conn)
            except Exception as e:
                logger.warning("Error in on_connection_accepted callback: %s", e)

    def _handle_client_disconnected(self, peer_address: str) -> None:
        """Remove disconnected client from active tracking."""
        self._connections.pop(peer_address, None)
