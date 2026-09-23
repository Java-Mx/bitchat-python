"""Session coordinator managing Noise sessions, BLE routing, and dispatch."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from bitchat.crypto.noise import NoiseRole, NoiseSessionState
from bitchat.crypto.sessions import NoiseSession
from bitchat.exceptions import PacketDecodingError
from bitchat.mesh.router import MeshRouter
from bitchat.protocol.constants import MessageType
from bitchat.protocol.decoder import decode_packet
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.fragmentation import (
    fragment_encoded_packet,
    should_fragment,
)
from bitchat.protocol.packet import BitchatPacket
from bitchat.protocol.reassembly import FragmentReassembler

if TYPE_CHECKING:
    from collections.abc import Callable

    from bitchat.ble.manager import BLEManager
    from bitchat.ble.models import DiscoveredPeer
    from bitchat.ble.server import BLEServer
    from bitchat.crypto.identity import LocalIdentity
    from bitchat.storage.config import StorageInterface

logger = logging.getLogger(__name__)


def _decode_chat_payload(payload_bytes: bytes) -> str:
    """Decode chat payload from bytes, handling raw UTF-8 or inner type prefix."""
    try:
        return payload_bytes.decode("utf-8")
    except UnicodeDecodeError:
        if len(payload_bytes) > 1 and payload_bytes[0] == MessageType.Message:
            try:
                return payload_bytes[1:].decode("utf-8")
            except UnicodeDecodeError:
                pass
        return payload_bytes.decode("utf-8", errors="replace")


class SessionCoordinator:
    """Manages active Noise sessions, peer tables, and message routing over BLE."""

    def __init__(
        self,
        local_identity: LocalIdentity,
        ble_manager: BLEManager,
        ble_server: BLEServer,
        storage: StorageInterface | None = None,
        nickname: str = "Anonymous",
        on_message_received: Callable[[str, str, bool], None] | None = None,
        on_peer_status_changed: Callable[[str, str], None] | None = None,
        on_handshake_completed: Callable[[str, str], None] | None = None,
        inter_fragment_delay: float = 0.02,
        mesh_router: MeshRouter | None = None,
    ) -> None:
        self.local_identity = local_identity
        self.ble_manager = ble_manager
        self.ble_server = ble_server
        self.storage = storage
        self.nickname = nickname
        self.inter_fragment_delay = inter_fragment_delay
        self.mesh_router = mesh_router or MeshRouter(
            local_peer_id=self.local_identity.peer_id
        )

        self.on_message_received = on_message_received
        self.on_peer_status_changed = on_peer_status_changed
        self.on_handshake_completed = on_handshake_completed

        self._sessions: dict[str, NoiseSession] = {}
        self._pending_messages: dict[str, list[str]] = {}
        self.peer_addresses: dict[str, str] = {}
        self.address_to_peer_id: dict[str, str] = {}
        self.peer_nicknames: dict[str, str] = {}
        self._announced_peers: set[str] = set()
        self._background_tasks: set[asyncio.Task[Any]] = set()

        self.server_reassembler = FragmentReassembler()
        self._is_running: bool = False

    def _spawn_task(self, coro: Any) -> asyncio.Task[Any]:
        """Spawn background task and keep a reference until completion."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    @property
    def is_running(self) -> bool:
        """Return True if the coordinator is active."""
        return self._is_running

    def get_or_create_session(self, remote_peer_id_hex: str) -> NoiseSession:
        """Get existing NoiseSession or initialize a new one for remote peer."""
        session = self._sessions.get(remote_peer_id_hex)
        if session is None:
            session = NoiseSession(self.local_identity, remote_peer_id_hex)
            self._sessions[remote_peer_id_hex] = session
        return session

    async def start(self) -> None:
        """Initialize BLE server, callbacks, and start peer discovery."""
        if self._is_running:
            return

        self._is_running = True

        # Hook server callbacks
        self.ble_server.on_data_received = self._handle_server_data_received

        # Hook manager callbacks
        self.ble_manager.on_packet_received = self._handle_incoming_packet
        self.ble_manager.on_peer_discovered = self._handle_peer_discovered
        self.ble_manager.on_peer_connected = self._handle_peer_connected
        self.ble_manager.on_peer_disconnected = self._handle_peer_disconnected

        # Start server and discovery
        await self.ble_server.start()
        try:
            await self.ble_manager.start_discovery()
        except Exception as e:
            logger.warning("Could not start BLE discovery: %s", e)

        # Broadcast announce
        await self.send_announce()

    async def stop(self) -> None:
        """Shutdown coordinator, close sessions, and stop BLE services."""
        if not self._is_running:
            return

        self._is_running = False

        for session in self._sessions.values():
            session.close()
        self._sessions.clear()
        self._pending_messages.clear()
        self._announced_peers.clear()

        await self.ble_manager.shutdown()
        await self.ble_server.stop()

    def set_nickname(self, nickname: str) -> None:
        """Update local nickname."""
        self.nickname = nickname

    async def send_announce(self, nickname: str | None = None) -> None:
        """Broadcast an Announce packet to notify peers of our presence."""
        nick = nickname or self.nickname
        packet = BitchatPacket.create(
            message_type=MessageType.Announce,
            sender_id=self.local_identity.peer_id,
            payload=nick.encode("utf-8"),
        )
        await self._broadcast_packet(packet)

    async def send_broadcast_message(self, text: str) -> None:
        """Send an unencrypted public message to all connected peers."""
        packet = BitchatPacket.create(
            message_type=MessageType.Message,
            sender_id=self.local_identity.peer_id,
            payload=text.encode("utf-8"),
        )
        await self._broadcast_packet(packet)

    async def send_direct_message(self, target_peer_id_hex: str, text: str) -> None:
        """Send an encrypted message to a peer, establishing Noise XX if needed."""
        session = self.get_or_create_session(target_peer_id_hex)

        if not session.is_established:
            self._pending_messages.setdefault(target_peer_id_hex, []).append(text)
            if session.state == NoiseSessionState.UNINITIALIZED:
                if session.role == NoiseRole.INITIATOR:
                    init_payload = session.start_handshake()
                    if init_payload is not None:
                        packet = BitchatPacket.create(
                            message_type=MessageType.NoiseHandshakeInit,
                            sender_id=self.local_identity.peer_id,
                            recipient_id=bytes.fromhex(target_peer_id_hex),
                            payload=init_payload,
                        )
                        await self._send_packet(target_peer_id_hex, packet)
                else:
                    req_packet = BitchatPacket.create(
                        message_type=MessageType.HandshakeRequest,
                        sender_id=self.local_identity.peer_id,
                        recipient_id=bytes.fromhex(target_peer_id_hex),
                        payload=b"",
                    )
                    await self._send_packet(target_peer_id_hex, req_packet)
            return

        # Session is established: encrypt and transmit
        ciphertext = session.encrypt(text.encode("utf-8"))
        packet = BitchatPacket.create(
            message_type=MessageType.NoiseEncrypted,
            sender_id=self.local_identity.peer_id,
            recipient_id=bytes.fromhex(target_peer_id_hex),
            payload=ciphertext,
        )
        await self._send_packet(target_peer_id_hex, packet)

    async def _send_packet(
        self, target_peer_id_hex: str | None, packet: BitchatPacket
    ) -> None:
        """Transmit packet via direct central transport or peripheral notification."""
        self.mesh_router.deduplicator.record(packet)

        target_addr = (
            self.peer_addresses.get(target_peer_id_hex) if target_peer_id_hex else None
        )
        if target_addr and target_addr in self.ble_manager.connected_peers:
            await self.ble_manager.send_to_peer(target_addr, packet)
            return

        if self.ble_manager.connected_peers:
            await self.ble_manager.broadcast_packet(packet)

        if self.ble_server.is_advertising:
            encoded = encode_packet(packet, add_padding=True)
            if should_fragment(encoded):
                fragments = fragment_encoded_packet(
                    encoded,
                    sender_id=self.local_identity.peer_id,
                    original_message_type=packet.message_type,
                )
                for i, frag in enumerate(fragments):
                    frag_bytes = encode_packet(frag, add_padding=True)
                    await self.ble_server.send_notification(frag_bytes)
                    if i < len(fragments) - 1:
                        await asyncio.sleep(self.inter_fragment_delay)
            else:
                await self.ble_server.send_notification(encoded)

    async def _broadcast_packet(
        self, packet: BitchatPacket, exclude_peer: str | None = None
    ) -> None:
        """Broadcast packet over central connections and peripheral notifications."""
        self.mesh_router.deduplicator.record(packet)

        tasks: list[Any] = []
        if self.ble_manager.connected_peers:
            tasks.append(
                self.ble_manager.broadcast_packet(packet, exclude_address=exclude_peer)
            )

        if self.ble_server.is_advertising and exclude_peer != "server":
            encoded = encode_packet(packet, add_padding=True)
            if should_fragment(encoded):
                fragments = fragment_encoded_packet(
                    encoded,
                    sender_id=self.local_identity.peer_id,
                    original_message_type=packet.message_type,
                )

                async def _send_frags() -> None:
                    for i, frag in enumerate(fragments):
                        frag_bytes = encode_packet(frag, add_padding=True)
                        await self.ble_server.send_notification(frag_bytes)
                        if i < len(fragments) - 1:
                            await asyncio.sleep(self.inter_fragment_delay)

                tasks.append(_send_frags())
            else:
                tasks.append(self.ble_server.send_notification(encoded))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _handle_server_data_received(self, raw_bytes: bytes, client_id: str) -> None:
        """Process incoming raw bytes from GATT server write."""
        try:
            packet = decode_packet(raw_bytes)
        except PacketDecodingError as e:
            logger.warning(
                "Dropped malformed packet from server client %s: %s", client_id, e
            )
            return

        if packet.message_type in (
            MessageType.FragmentStart,
            MessageType.FragmentContinue,
            MessageType.FragmentEnd,
        ):
            reassembled_wire = self.server_reassembler.add_fragment_packet(packet)
            if reassembled_wire is not None:
                try:
                    full_packet = decode_packet(reassembled_wire)
                    self._handle_incoming_packet(full_packet, client_id)
                except PacketDecodingError as e:
                    logger.warning("Failed decoding reassembled server packet: %s", e)
        else:
            self._handle_incoming_packet(packet, client_id)

    def _handle_incoming_packet(
        self, packet: BitchatPacket, peer_address: str | None = None
    ) -> None:
        """Route decoded incoming packet to mesh router and asynchronous processing."""
        decision = self.mesh_router.evaluate_incoming(
            packet, ingress_source=peer_address
        )

        if decision.should_process_locally:
            self._spawn_task(self._process_packet_async(packet, peer_address))

        if decision.packet_to_relay is not None:
            self._spawn_task(
                self._relay_packet_async(
                    decision.packet_to_relay,
                    decision.target_peer_id_hex,
                    decision.exclude_ingress,
                )
            )
        elif decision.target_peer_id_hex and not decision.should_process_locally:
            # Store-and-forward for offline destination
            self.mesh_router.store_forward_queue.enqueue(
                decision.target_peer_id_hex, packet
            )

    async def _relay_packet_async(
        self,
        packet: BitchatPacket,
        target_peer_id_hex: str | None = None,
        exclude_ingress: str | None = None,
    ) -> None:
        """Relay packet across mesh with collision-mitigation jitter."""
        jitter = self.mesh_router.get_relay_jitter()
        await asyncio.sleep(jitter)

        if target_peer_id_hex:
            target_addr = self.peer_addresses.get(target_peer_id_hex)
            if (
                target_addr
                and target_addr in self.ble_manager.connected_peers
                and target_addr != exclude_ingress
            ):
                try:
                    await self.ble_manager.send_to_peer(target_addr, packet)
                    return
                except Exception as e:
                    logger.warning("Failed relaying packet to %s: %s", target_addr, e)

            # Target is not a direct neighbor: broadcast relay across mesh or store
            if target_peer_id_hex not in self.peer_addresses:
                await self._broadcast_packet(packet, exclude_peer=exclude_ingress)
            else:
                self.mesh_router.store_forward_queue.enqueue(target_peer_id_hex, packet)
        else:
            await self._broadcast_packet(packet, exclude_peer=exclude_ingress)

    async def _process_packet_async(
        self, packet: BitchatPacket, peer_address: str | None = None
    ) -> None:
        """Handle incoming packet state transitions, crypto, and callbacks."""
        sender_hex = packet.sender_id.hex()
        if peer_address:
            self.peer_addresses[sender_hex] = peer_address
            self.address_to_peer_id[peer_address] = sender_hex

        match packet.message_type:
            case MessageType.Announce:
                nickname = packet.payload.decode("utf-8", errors="replace").strip()
                self.peer_nicknames[sender_hex] = nickname
                if self.on_peer_status_changed:
                    self.on_peer_status_changed(sender_hex, f"Online ({nickname})")

                if self.mesh_router.store_forward_queue.has_pending(sender_hex):
                    pending_pkts = (
                        self.mesh_router.store_forward_queue.dequeue_for_peer(
                            sender_hex
                        )
                    )
                    for pending in pending_pkts:
                        self._spawn_task(self._send_packet(sender_hex, pending))

            case MessageType.Message:
                text = _decode_chat_payload(packet.payload)
                if self.on_message_received:
                    self.on_message_received(sender_hex, text, False)

            case MessageType.HandshakeRequest:
                session = self.get_or_create_session(sender_hex)
                if (
                    session.role == NoiseRole.INITIATOR
                    and session.state == NoiseSessionState.UNINITIALIZED
                ):
                    init_payload = session.start_handshake()
                    if init_payload is not None:
                        resp_pkt = BitchatPacket.create(
                            message_type=MessageType.NoiseHandshakeInit,
                            sender_id=self.local_identity.peer_id,
                            recipient_id=packet.sender_id,
                            payload=init_payload,
                        )
                        await self._send_packet(sender_hex, resp_pkt)

            case MessageType.NoiseHandshakeInit:
                session = self.get_or_create_session(sender_hex)
                try:
                    resp_payload = session.process_handshake_message(packet.payload)
                except Exception as e:
                    logger.warning(
                        "NoiseHandshakeInit failed from %s: %s", sender_hex, e
                    )
                    return

                if resp_payload is not None:
                    resp_pkt = BitchatPacket.create(
                        message_type=MessageType.NoiseHandshakeResp,
                        sender_id=self.local_identity.peer_id,
                        recipient_id=packet.sender_id,
                        payload=resp_payload,
                    )
                    await self._send_packet(sender_hex, resp_pkt)

                if session.is_established:
                    self._on_handshake_established(sender_hex, session)

            case MessageType.NoiseHandshakeResp:
                session = self._sessions.get(sender_hex)
                if session is None:
                    logger.warning(
                        "Unexpected NoiseHandshakeResp from unknown %s", sender_hex
                    )
                    return

                try:
                    resp_payload = session.process_handshake_message(packet.payload)
                except Exception as e:
                    logger.warning(
                        "NoiseHandshakeResp failed from %s: %s", sender_hex, e
                    )
                    return

                if resp_payload is not None:
                    resp_pkt = BitchatPacket.create(
                        message_type=MessageType.NoiseHandshakeResp,
                        sender_id=self.local_identity.peer_id,
                        recipient_id=packet.sender_id,
                        payload=resp_payload,
                    )
                    await self._send_packet(sender_hex, resp_pkt)

                if session.is_established:
                    self._on_handshake_established(sender_hex, session)

            case MessageType.NoiseEncrypted:
                session = self._sessions.get(sender_hex)
                if session is None or not session.is_established:
                    logger.warning(
                        "Received NoiseEncrypted without established session from %s",
                        sender_hex,
                    )
                    return

                try:
                    plaintext = session.decrypt(packet.payload)
                except Exception as e:
                    logger.warning("Decryption error from %s: %s", sender_hex, e)
                    return

                text = _decode_chat_payload(plaintext)
                if self.on_message_received:
                    self.on_message_received(sender_hex, text, True)

            case _:
                logger.debug("Unhandled packet type: %s", packet.message_type)

    def _on_handshake_established(
        self, remote_peer_id_hex: str, session: NoiseSession
    ) -> None:
        """Trigger completion callback and flush queued messages."""
        fingerprint = session.remote_fingerprint or ""
        if self.on_handshake_completed:
            self.on_handshake_completed(remote_peer_id_hex, fingerprint)

        pending = self._pending_messages.pop(remote_peer_id_hex, [])
        for text in pending:
            self._spawn_task(self.send_direct_message(remote_peer_id_hex, text))

    def _handle_peer_discovered(self, peer: DiscoveredPeer) -> None:
        """Callback when scanner detects a BitChat BLE peer."""
        if self.on_peer_status_changed:
            name = peer.name or "Unknown"
            self.on_peer_status_changed(
                peer.address, f"Discovered: {name} ({peer.rssi} dBm)"
            )

    def _handle_peer_connected(self, peer_address: str) -> None:
        """Callback when a central connection to peer is established."""
        if self.on_peer_status_changed:
            self.on_peer_status_changed(peer_address, "Connected")
        self._spawn_task(self.send_announce())

        peer_id = self.address_to_peer_id.get(peer_address)
        if peer_id and self.mesh_router.store_forward_queue.has_pending(peer_id):
            pending_pkts = self.mesh_router.store_forward_queue.dequeue_for_peer(
                peer_id
            )
            for pending in pending_pkts:
                self._spawn_task(self.ble_manager.send_to_peer(peer_address, pending))

    def _handle_peer_disconnected(self, peer_address: str) -> None:
        """Callback when peer disconnects."""
        peer_id = self.address_to_peer_id.pop(peer_address, None)
        if peer_id:
            self.peer_addresses.pop(peer_id, None)
        if self.on_peer_status_changed:
            self.on_peer_status_changed(peer_address, "Disconnected")
