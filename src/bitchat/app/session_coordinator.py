"""Session coordinator managing Noise sessions, transport routing, and dispatch."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from bitchat.crypto.identity import LocalIdentity
from bitchat.crypto.noise import NoiseRole, NoiseSessionState
from bitchat.crypto.sessions import NoiseSession
from bitchat.exceptions import PacketDecodingError
from bitchat.mesh.router import MeshRouter
from bitchat.network.transport import LANTransport
from bitchat.protocol.constants import MessageType
from bitchat.protocol.decoder import decode_packet
from bitchat.protocol.packet import BitchatPacket
from bitchat.protocol.reassembly import FragmentReassembler
from bitchat.transport.base import BaseTransport, TransportState
from bitchat.transport.bluetooth import BluetoothTransport

if TYPE_CHECKING:
    from collections.abc import Callable

    from bitchat.ble.manager import BLEManager
    from bitchat.ble.server import BLEServer
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
        ble_manager: BLEManager | None = None,
        ble_server: BLEServer | None = None,
        transport: BaseTransport | None = None,
        storage: StorageInterface | None = None,
        nickname: str = "Anonymous",
        on_message_received: Callable[[str, str, bool], None] | None = None,
        on_peer_status_changed: Callable[[str, str], None] | None = None,
        on_handshake_completed: Callable[[str, str], None] | None = None,
        inter_fragment_delay: float = 0.02,
        mesh_router: MeshRouter | None = None,
        initial_transport: str = "bluetooth",
    ) -> None:
        self.local_identity = local_identity
        self.storage = storage
        self.nickname = nickname
        self.inter_fragment_delay = inter_fragment_delay
        self.mesh_router = mesh_router or MeshRouter(
            local_peer_id=self.local_identity.peer_id
        )

        self.on_message_received = on_message_received
        self.on_peer_status_changed = on_peer_status_changed
        self.on_handshake_completed = on_handshake_completed
        self.on_ble_error: Callable[[str], None] | None = None
        self.ble_status: str = "offline"
        self.ble_error_message: str | None = None

        self._sessions: dict[str, NoiseSession] = {}
        self._pending_messages: dict[str, list[str]] = {}
        self.peer_addresses: dict[str, str] = {}
        self.address_to_peer_id: dict[str, str] = {}
        self.peer_nicknames: dict[str, str] = {}
        self._announced_peers: set[str] = set()
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._retry_lock = asyncio.Lock()

        self.server_reassembler = FragmentReassembler()
        self._is_running: bool = False

        # Registered transports dictionary
        self._transports: dict[str, BaseTransport] = {}
        self.ble_manager: Any = ble_manager
        self.ble_server: Any = ble_server

        if ble_manager is not None and ble_server is not None:
            bt_transport = BluetoothTransport(
                ble_manager=ble_manager,
                ble_server=ble_server,
                inter_fragment_delay=inter_fragment_delay,
            )
            self._transports["bluetooth"] = bt_transport

        if transport is not None:
            self._transports[transport.transport_type.value] = transport
            self.active_transport = transport
            self.active_transport_name = transport.transport_type.value
        else:
            sel = initial_transport.lower()
            if "bluetooth" not in self._transports:
                self._transports["bluetooth"] = BluetoothTransport(
                    ble_manager=ble_manager,  # type: ignore[arg-type]
                    ble_server=ble_server,  # type: ignore[arg-type]
                    inter_fragment_delay=inter_fragment_delay,
                )
            if "lan" not in self._transports:
                self._transports["lan"] = LANTransport(
                    local_peer_id=self.local_identity.peer_id_hex,
                    local_nickname=self.nickname,
                )

            if sel == "lan":
                self.active_transport = self._transports["lan"]
                self.active_transport_name = "lan"
            else:
                self.active_transport = self._transports["bluetooth"]
                self.active_transport_name = "bluetooth"

        self._wire_transport_callbacks(self.active_transport)

    def _wire_transport_callbacks(self, transport: BaseTransport) -> None:
        """Attach session coordinator packet and state handlers to a transport."""
        transport.on_packet_received = self._handle_incoming_packet
        transport.on_peer_discovered = self._handle_peer_discovered
        transport.on_peer_connected = self._handle_peer_connected
        transport.on_peer_disconnected = self._handle_peer_disconnected
        transport.on_state_changed = self._handle_transport_state_changed
        transport.on_error = self._handle_transport_error

    def _handle_transport_state_changed(self, state: TransportState) -> None:
        self.ble_status = state.value
        if self.on_peer_status_changed:
            self.on_peer_status_changed("mesh", state.value)

    def _handle_transport_error(self, err_msg: str) -> None:
        self.ble_error_message = err_msg
        if self.on_ble_error:
            self.on_ble_error(err_msg)

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

    def get_session(self, remote_peer_id_hex: str) -> NoiseSession | None:
        """Return an existing Noise session without creating one."""
        return self._sessions.get(remote_peer_id_hex)

    def get_detailed_status(self) -> dict[str, Any]:
        """Return truthful telemetry dictionary for diagnostics."""
        telem = self.active_transport.get_telemetry()
        telem["local_nickname"] = self.nickname
        telem["local_peer_id"] = self.local_identity.peer_id_hex
        telem["local_fingerprint"] = self.local_identity.fingerprint
        telem["active_transport"] = self.active_transport_name
        return telem

    def resolve_peer_address(self, target: str) -> str | None:
        """Resolve nickname, peer ID prefix, or device to a transport address."""
        clean = target.strip().lstrip("@").lower()

        # 1. Exact or prefix match in peer_addresses
        for pid, addr in self.peer_addresses.items():
            if pid.lower() == clean or pid.lower().startswith(clean):
                return addr

        # 2. Nickname match
        for pid, nick in self.peer_nicknames.items():
            if nick.lower() == clean and pid in self.peer_addresses:
                return self.peer_addresses[pid]

        # 3. Direct lookup in active transport
        direct_addr = self.active_transport.resolve_peer_id_to_address(target)
        if direct_addr:
            return direct_addr

        # 4. Discovered peer lookup in active transport
        for addr_key, peer in self.active_transport.discovered_peers.items():
            pid = getattr(peer, "peer_id", None)
            if pid and (pid.lower() == clean or pid.lower().startswith(clean)):
                return addr_key
            pname = getattr(peer, "name", None) or getattr(peer, "nickname", None)
            if pname and (pname.lower() == clean or clean in pname.lower()):
                return addr_key
            clean_addr = addr_key.lower().replace(":", "").replace("-", "")
            if addr_key.lower() == clean or clean_addr == clean.replace(
                ":", ""
            ).replace("-", ""):
                return addr_key

        # 5. Reverse lookup in address_to_peer_id
        for addr_str, pid in self.address_to_peer_id.items():
            if pid.lower() == clean or pid.lower().startswith(clean):
                return addr_str

        return None

    async def start(self) -> None:
        """Initialize active transport, callbacks, and start peer discovery."""
        if self._is_running:
            return

        self._is_running = True
        self.ble_status = "checking"
        self.ble_error_message = None

        if self.ble_server:
            self.ble_server.on_data_received = self._handle_server_data_received

        self.active_transport.update_identity(
            self.local_identity.peer_id_hex, self.nickname
        )
        self._wire_transport_callbacks(self.active_transport)

        try:
            await self.active_transport.start()
            self.ble_status = self.active_transport.state.value
            await self.send_announce()
        except Exception as e:
            self._is_running = False
            logger.warning(
                "Could not start active transport %s: %s",
                self.active_transport_name,
                e,
            )
            self.ble_status = "unavailable"
            self.ble_error_message = str(e)
            if self.on_ble_error:
                self.on_ble_error(self.ble_error_message)

    def _transport_is_operational(self) -> bool:
        """Return True only if the active transport is actually usable."""
        state = self.active_transport.state
        if state in (
            TransportState.UNAVAILABLE,
            TransportState.DISABLED,
            TransportState.ERROR,
            TransportState.OFFLINE,
            TransportState.CHECKING,
        ):
            return False
        telem = self.active_transport.get_telemetry()
        if self.active_transport_name == "bluetooth":
            if telem.get("adapter_state") != "On":
                if self._uses_injected_ble_backend():
                    return telem.get("scanner_status") == "Active"
                return False
            return telem.get("scanner_status") == "Active"
        if self.active_transport_name == "lan":
            return (
                telem.get("status") == "Connected"
                and telem.get("discovery") == "Active"
                and telem.get("listening") == "Active"
            )
        return True

    def _uses_injected_ble_backend(self) -> bool:
        ble = self._transports.get("bluetooth")
        if ble is None:
            return False
        checker = getattr(ble, "_uses_injected_test_backend", None)
        return bool(checker()) if callable(checker) else False

    async def retry_ble(self) -> bool:
        """Re-initialize the active transport after failure. Success is operational."""
        async with self._retry_lock:
            self.ble_status = "checking"
            self.ble_error_message = None
            with contextlib.suppress(Exception):
                await self.active_transport.stop()
            try:
                await self.active_transport.start()
                self._is_running = True
                self.ble_status = self.active_transport.state.value
                if not self._transport_is_operational():
                    self.ble_status = self.active_transport.state.value
                    self.ble_error_message = (
                        self.active_transport.get_telemetry().get("error_message")
                        or "Transport is not operational"
                    )
                    return False
                await self.send_announce()
                return True
            except Exception as e:
                logger.warning("Retry active transport failed: %s", e)
                self.ble_status = "unavailable"
                self.ble_error_message = str(e)
                if self.on_ble_error:
                    self.on_ble_error(self.ble_error_message)
                return False

    async def stop(self) -> None:
        """Shutdown coordinator, close sessions, and stop all transports."""
        self._is_running = False
        self.ble_status = "offline"
        self.ble_error_message = None

        for session in self._sessions.values():
            session.close()
        self._sessions.clear()
        self._pending_messages.clear()
        self._announced_peers.clear()

        for transport in self._transports.values():
            with contextlib.suppress(Exception):
                await transport.stop()

    async def switch_transport(self, target_transport: str) -> tuple[bool, str]:
        """Switch between Bluetooth and LAN with session teardown and fresh identity."""
        target = target_transport.lower().strip()
        if target not in ("bluetooth", "lan"):
            return False, f"Unknown transport: {target}"

        if target == self.active_transport_name and self.active_transport.is_running:
            return True, f"Already active on {target} transport."

        logger.info("Switching transport: %s -> %s", self.active_transport_name, target)

        # 1. Stop old transport completely
        await self.active_transport.stop()

        # 2. Close active Noise sessions
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()

        # 3. Clear active peer tables and pending messages
        self.peer_addresses.clear()
        self.address_to_peer_id.clear()
        self.peer_nicknames.clear()
        self._announced_peers.clear()
        self._pending_messages.clear()

        # 4. Generate fresh ephemeral transport identity
        old_id = self.local_identity.peer_id_hex
        self.local_identity = LocalIdentity.generate()
        new_id = self.local_identity.peer_id_hex
        self.mesh_router.local_peer_id = self.local_identity.peer_id
        logger.info(
            "Transport switch (%s -> %s): generated fresh identity %s (old: %s)",
            self.active_transport_name,
            target,
            new_id,
            old_id,
        )

        # 5. Switch active transport
        if target == "lan":
            if "lan" not in self._transports:
                self._transports["lan"] = LANTransport(
                    local_peer_id=new_id,
                    local_nickname=self.nickname,
                )
            else:
                self._transports["lan"].update_identity(new_id, self.nickname)
            self.active_transport = self._transports["lan"]
        else:
            if "bluetooth" not in self._transports:
                return False, "Bluetooth transport not available"
            self._transports["bluetooth"].update_identity(new_id, self.nickname)
            self.active_transport = self._transports["bluetooth"]

        self.active_transport_name = target
        self._wire_transport_callbacks(self.active_transport)

        # 6. Start new transport
        try:
            await self.active_transport.start()
            self.ble_status = self.active_transport.state.value
            await self.send_announce()
            display_name = "LAN / Wi-Fi" if target == "lan" else "Bluetooth"
            return True, (
                f"Switched transport to {display_name}. "
                f"New secure chat session created. "
                f"New peer identity: {new_id[:12]}"
            )
        except Exception as e:
            logger.error("Failed starting %s transport: %s", target, e)
            self.ble_status = "unavailable"
            self.ble_error_message = str(e)
            return False, f"Failed starting {target} transport: {e}"

    def set_nickname(self, nickname: str) -> None:
        """Update local nickname across active transports."""
        self.nickname = nickname
        for transport in self._transports.values():
            transport.update_identity(self.local_identity.peer_id_hex, self.nickname)

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
        """Transmit packet via direct transport connection or broadcast."""
        self.mesh_router.deduplicator.record(packet)

        target_addr = (
            self.peer_addresses.get(target_peer_id_hex) if target_peer_id_hex else None
        )
        if target_addr and target_addr in self.active_transport.connected_peers:
            await self.active_transport.send_to_peer(target_addr, packet)
            return

        await self.active_transport.broadcast_packet(packet)

    async def _broadcast_packet(
        self, packet: BitchatPacket, exclude_peer: str | None = None
    ) -> None:
        """Broadcast packet across all active transport peers."""
        self.mesh_router.deduplicator.record(packet)
        await self.active_transport.broadcast_packet(
            packet, exclude_address=exclude_peer
        )

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
        if not self._is_running:
            return

        jitter = self.mesh_router.get_relay_jitter()
        try:
            await asyncio.sleep(jitter)
        except asyncio.CancelledError:
            return

        if not self._is_running:
            return

        try:
            if target_peer_id_hex:
                target_addr = self.peer_addresses.get(target_peer_id_hex)
                if (
                    target_addr
                    and target_addr in self.active_transport.connected_peers
                    and target_addr != exclude_ingress
                ):
                    try:
                        await self.active_transport.send_to_peer(target_addr, packet)
                        return
                    except Exception as e:
                        logger.warning(
                            "Failed relaying packet to %s: %s", target_addr, e
                        )

                # Target is not a direct neighbor: broadcast relay across mesh or store
                if target_peer_id_hex not in self.peer_addresses:
                    await self._broadcast_packet(packet, exclude_peer=exclude_ingress)
                else:
                    self.mesh_router.store_forward_queue.enqueue(
                        target_peer_id_hex, packet
                    )
            else:
                await self._broadcast_packet(packet, exclude_peer=exclude_ingress)
        except Exception as e:
            logger.warning("Relaying failed safely: %s", e)

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

    def _handle_peer_discovered(self, peer: Any) -> None:
        """Callback when scanner detects a BitChat BLE peer."""
        if peer.peer_id:
            clean_pid = peer.peer_id.lower()
            self.peer_addresses[clean_pid] = peer.address
            self.address_to_peer_id[peer.address] = clean_pid
            if peer.nickname:
                self.peer_nicknames[clean_pid] = peer.nickname

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
                self._spawn_task(
                    self.active_transport.send_to_peer(peer_address, pending)
                )

    def _handle_peer_disconnected(self, peer_address: str) -> None:
        """Callback when peer disconnects."""
        peer_id = self.address_to_peer_id.pop(peer_address, None)
        if peer_id:
            self.peer_addresses.pop(peer_id, None)
        if self.on_peer_status_changed:
            self.on_peer_status_changed(peer_address, "Disconnected")

    async def connect_peer(self, target: str, timeout: float = 10.0) -> Any:
        """Establish connection to a target peer ID, nickname, or address."""
        resolved = self.resolve_peer_address(target) or target
        return await self.active_transport.connect_peer(resolved, timeout=timeout)

    async def disconnect_peer(self, target: str) -> None:
        """Disconnect a specific peer by ID, nickname, or address."""
        resolved = self.resolve_peer_address(target) or target
        await self.active_transport.disconnect_peer(resolved)
