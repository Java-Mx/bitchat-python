"""TCP connection lifecycle, framing, read loop, and teardown."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from bitchat.exceptions import PacketDecodingError
from bitchat.network.framing import FramingError, StreamFramer, encode_frame
from bitchat.protocol.decoder import decode_packet
from bitchat.protocol.encoder import encode_packet

if TYPE_CHECKING:
    from collections.abc import Callable

    from bitchat.protocol.packet import BitchatPacket

logger = logging.getLogger(__name__)


class LANConnection:
    """Manages an active bi-directional TCP stream to a BitChat peer."""

    def __init__(
        self,
        peer_address: str,
        reader: asyncio.StreamReader | None = None,
        writer: asyncio.StreamWriter | None = None,
        on_packet_received: Callable[[BitchatPacket, str], None] | None = None,
        on_disconnected: Callable[[str], None] | None = None,
        connect_timeout: float = 10.0,
    ) -> None:
        self.peer_address = peer_address
        self.on_packet_received = on_packet_received
        self.on_disconnected = on_disconnected
        self.connect_timeout = connect_timeout

        self._reader: asyncio.StreamReader | None = reader
        self._writer: asyncio.StreamWriter | None = writer
        self._is_connected: bool = reader is not None and writer is not None
        self._is_ready: bool = self._is_connected
        self._read_task: asyncio.Task[Any] | None = None
        self._lock = asyncio.Lock()
        self._framer = StreamFramer()

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def is_ready(self) -> bool:
        return self._is_ready and self._is_connected

    async def connect(self) -> None:
        """Establish outbound TCP connection to target peer_address."""
        if self._is_connected:
            return

        try:
            host, port_str = self.peer_address.split(":", 1)
            port = int(port_str)
        except ValueError as err:
            raise ValueError(
                f"Invalid peer address format '{self.peer_address}' "
                "(expected host:port)"
            ) from err

        async with self._lock:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=self.connect_timeout,
                )
                self._reader = reader
                self._writer = writer
                self._is_connected = True
                self._is_ready = True
                self.start_reading()
                logger.info("Connected to LAN peer at %s", self.peer_address)
            except Exception as e:
                self._is_connected = False
                self._is_ready = False
                logger.debug(
                    "Failed connecting to LAN peer %s: %s", self.peer_address, e
                )
                raise

    def start_reading(self) -> None:
        """Launch background stream reader task."""
        if self._read_task is None or self._read_task.done():
            self._read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        """Continuous reading loop extracting framed packets."""
        logger.debug("Started TCP read loop for %s", self.peer_address)
        try:
            while self._is_connected and self._reader:
                chunk = await self._reader.read(4096)
                if not chunk:
                    # Clean EOF from remote peer
                    logger.info(
                        "Remote peer %s closed connection (EOF)", self.peer_address
                    )
                    break

                try:
                    payloads = self._framer.feed(chunk)
                except FramingError as e:
                    logger.warning(
                        "Framing error on %s: %s (terminating connection)",
                        self.peer_address,
                        e,
                    )
                    break

                for raw_packet in payloads:
                    try:
                        packet = decode_packet(raw_packet)
                        if self.on_packet_received:
                            self.on_packet_received(packet, self.peer_address)
                    except PacketDecodingError as e:
                        logger.warning(
                            "Packet decode error from %s: %s", self.peer_address, e
                        )
                    except Exception as e:
                        logger.error(
                            "Unhandled error processing packet from %s: %s",
                            self.peer_address,
                            e,
                            exc_info=True,
                        )
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError) as e:
            logger.info("Connection lost to %s: %s", self.peer_address, e)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(
                "Unexpected error in TCP read loop for %s: %s", self.peer_address, e
            )
        finally:
            await self.close()

    async def send_packet(self, packet: BitchatPacket) -> None:
        """Encode, frame, and transmit a BitChat packet over TCP."""
        if not self.is_ready or not self._writer:
            raise ConnectionError(
                f"Cannot send: peer {self.peer_address} is not connected"
            )

        async with self._lock:
            try:
                encoded = encode_packet(packet, add_padding=False)
                frame = encode_frame(encoded)
                self._writer.write(frame)
                await self._writer.drain()
            except Exception as e:
                logger.warning("Failed sending packet to %s: %s", self.peer_address, e)
                await self.close()
                raise

    async def close(self) -> None:
        """Cleanly close socket and cancel background tasks."""
        if not self._is_connected:
            return

        self._is_connected = False
        self._is_ready = False
        self._framer.clear()

        writer = self._writer
        self._writer = None
        self._reader = None

        if writer:
            with contextlib.suppress(Exception):
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), timeout=0.5)

        if self._read_task and asyncio.current_task() != self._read_task:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
            self._read_task = None

        if self.on_disconnected:
            try:
                self.on_disconnected(self.peer_address)
            except Exception as e:
                logger.warning("Error in on_disconnected callback: %s", e)
