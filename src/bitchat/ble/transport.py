"""BLE transport integrating packet encoding, fragmentation, and pacing."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from bitchat.exceptions import (
    BLETransportError,
    FragmentationError,
    PacketDecodingError,
)
from bitchat.protocol.constants import (
    SENDER_ID_SIZE,
    MessageType,
)
from bitchat.protocol.decoder import decode_packet
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.fragmentation import fragment_encoded_packet, should_fragment
from bitchat.protocol.reassembly import FragmentReassembler

if TYPE_CHECKING:
    from collections.abc import Callable

    from bitchat.ble.connection import BLEConnection
    from bitchat.protocol.packet import BitchatPacket

logger = logging.getLogger(__name__)

_DEFAULT_INTER_FRAGMENT_DELAY_SECONDS: float = (
    0.02  # 20ms matching Swift/Rust reference
)
_DEFAULT_QUEUE_MAX_SIZE: int = 100


class BLETransport:
    """Manages raw byte transmission, 20ms fragment pacing, and reception."""

    def __init__(
        self,
        connection: BLEConnection,
        sender_id: bytes,
        on_packet_received: Callable[[BitchatPacket, str], None] | None = None,
        queue_max_size: int = _DEFAULT_QUEUE_MAX_SIZE,
        inter_fragment_delay: float = _DEFAULT_INTER_FRAGMENT_DELAY_SECONDS,
        reassembler: FragmentReassembler | None = None,
    ) -> None:
        if len(sender_id) != SENDER_ID_SIZE:
            raise ValueError(
                f"sender_id must be {SENDER_ID_SIZE} bytes, got {len(sender_id)}"
            )

        self.connection = connection
        self.sender_id = bytes(sender_id)
        self.on_packet_received = on_packet_received
        self.inter_fragment_delay = inter_fragment_delay
        self.reassembler = reassembler or FragmentReassembler()

        self._receive_queue: asyncio.Queue[bytes] = asyncio.Queue(
            maxsize=queue_max_size
        )
        self._worker_task: asyncio.Task[None] | None = None
        self._is_running: bool = False

        # Hook notification callback into the connection
        self.connection.notification_callback = self._handle_incoming_notification

    @property
    def is_running(self) -> bool:
        """Return True if the transport reception worker is running."""
        return self._is_running

    def _handle_incoming_notification(self, raw_bytes: bytes) -> None:
        """Enqueue incoming untrusted notification bytes without blocking Bleak."""
        try:
            self._receive_queue.put_nowait(raw_bytes)
        except asyncio.QueueFull:
            logger.warning(
                "Receive queue full for peer %s; dropping packet",
                self.connection.peer_address,
            )

    async def _receive_worker(self) -> None:
        """Background task draining receive queue, decoding, and reassembly."""
        logger.debug("Receive worker started for peer %s", self.connection.peer_address)
        while self._is_running:
            try:
                raw_bytes = await self._receive_queue.get()
                self._process_raw_bytes(raw_bytes)
                self._receive_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "Unexpected error in receive worker for %s: %s",
                    self.connection.peer_address,
                    e,
                    exc_info=True,
                )
        logger.debug("Receive worker stopped for peer %s", self.connection.peer_address)

    def _process_raw_bytes(self, raw_bytes: bytes) -> None:
        """Decode incoming bytes and route through reassembly if fragmented."""
        try:
            packet = decode_packet(raw_bytes)
        except PacketDecodingError as e:
            logger.warning(
                "Discarding malformed packet from %s: %s",
                self.connection.peer_address,
                e,
            )
            return

        if packet.message_type in (
            MessageType.FragmentStart,
            MessageType.FragmentContinue,
            MessageType.FragmentEnd,
        ):
            try:
                reassembled_wire = self.reassembler.add_fragment_packet(packet)
            except (FragmentationError, PacketDecodingError) as e:
                logger.warning(
                    "Error reassembling fragment from %s: %s",
                    self.connection.peer_address,
                    e,
                )
                return

            if reassembled_wire is not None:
                try:
                    full_packet = decode_packet(reassembled_wire)
                    self._dispatch_packet(full_packet)
                except PacketDecodingError as e:
                    logger.warning(
                        "Failed to decode reassembled packet from %s: %s",
                        self.connection.peer_address,
                        e,
                    )
        else:
            self._dispatch_packet(packet)

    def _dispatch_packet(self, packet: BitchatPacket) -> None:
        """Deliver validated packet to the registered callback."""
        if self.on_packet_received:
            try:
                self.on_packet_received(packet, self.connection.peer_address)
            except Exception as e:
                logger.error(
                    "Unhandled exception in on_packet_received for %s: %s",
                    self.connection.peer_address,
                    e,
                    exc_info=True,
                )

    async def start(self) -> None:
        """Start the transport layer and connect to the remote peer."""
        if self._is_running:
            return

        self._is_running = True
        self._worker_task = asyncio.create_task(self._receive_worker())

        try:
            await self.connection.connect()
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        """Stop the transport worker and disconnect the peer."""
        self._is_running = False

        if self._worker_task is not None:
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
            self._worker_task = None

        await self.connection.disconnect()

    async def send_packet(
        self, packet: BitchatPacket, add_padding: bool = True
    ) -> None:
        """Serialize and transmit a packet, fragmenting and pacing if needed."""
        if not self.connection.is_ready:
            raise BLETransportError(
                f"Cannot send packet: peer {self.connection.peer_address} is not ready"
            )

        encoded = encode_packet(packet, add_padding=add_padding)

        if not should_fragment(encoded):
            await self.connection.write(encoded, response=False)
            return

        # Large packet: slice and send with 20ms pacing
        fragments = fragment_encoded_packet(
            encoded,
            sender_id=self.sender_id,
            original_message_type=packet.message_type,
        )

        logger.debug(
            "Transmitting %d fragments for packet size %d bytes to %s",
            len(fragments),
            len(encoded),
            self.connection.peer_address,
        )

        for i, frag_pkt in enumerate(fragments):
            frag_bytes = encode_packet(frag_pkt, add_padding=True)
            await self.connection.write(frag_bytes, response=False)
            if i < len(fragments) - 1:
                await asyncio.sleep(self.inter_fragment_delay)

    async def send_bytes(self, raw_bytes: bytes) -> None:
        """Transmit raw bytes directly to the characteristic."""
        if not self.connection.is_ready:
            raise BLETransportError(
                f"Cannot send bytes: peer {self.connection.peer_address} is not ready"
            )
        await self.connection.write(raw_bytes, response=False)
