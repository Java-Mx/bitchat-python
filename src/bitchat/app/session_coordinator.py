"""Session coordinator managing Noise sessions, transport routing, and dispatch."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from time import perf_counter
from typing import TYPE_CHECKING, Any

from bitchat.crypto.noise import NoiseRole, NoiseSessionState
from bitchat.crypto.sessions import NoiseSession
from bitchat.exceptions import (
    FragmentLimitExceededError,
    InvalidFragmentError,
    PacketDecodingError,
)
from bitchat.logging import log_transport_diagnostic
from bitchat.mesh.router import MeshRouter
from bitchat.network.transport import LANTransport
from bitchat.protocol.constants import MessageType
from bitchat.protocol.decoder import decode_packet
from bitchat.protocol.packet import BitchatPacket
from bitchat.protocol.reassembly import FragmentReassembler
from bitchat.transport.base import (
    BaseTransport,
    OfflineTransport,
    TransportError,
    TransportState,
    TransportType,
    TransportWarning,
    normalize_transport_name,
)
from bitchat.transport.bluetooth import BluetoothTransport

if TYPE_CHECKING:
    from collections.abc import Callable

    from bitchat.ble.manager import BLEManager
    from bitchat.ble.server import BLEServer
    from bitchat.crypto.identity import LocalIdentity
    from bitchat.mesh.dedup import PacketDeduplicator
    from bitchat.mesh.store_forward import StoreAndForwardQueue
    from bitchat.storage.config import StorageInterface


logger = logging.getLogger(__name__)
NOISE_HANDSHAKE_TIMEOUT_SECONDS: float = 10.0
TRANSPORT_RETRY_TIMEOUT_SECONDS: float = 30.0
MAX_TTL: int = 7
MAX_MESSAGE_SIZE: int = 32_768
MAX_PENDING_HANDSHAKES: int = 64
PERIODIC_PRUNE_INTERVAL_SECONDS: float = 30.0


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
        lan_tcp_port: int = 41235,
        lan_discovery_port: int = 41234,
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
        self.on_ble_error: Callable[[TransportError], None] | None = None
        self.on_ble_warning: Callable[[TransportWarning], None] | None = None
        self.on_lan_error: Callable[[TransportError], None] | None = None
        self.ble_status: str = "offline"
        self.lan_status: str = "offline"
        self.ble_error_message: str | None = None
        self.lan_error_message: str | None = None
        self.transport_errors: dict[TransportType, TransportError] = {}
        self.transport_diagnostics: dict[
            TransportType, list[TransportError | TransportWarning]
        ] = {}
        self._transport_generation = 0
        self.offline_mode: bool = False
        self._starting_transport: BaseTransport | None = None
        # Last error already delivered through the transport's on_error hook, so
        # start() does not report the same failure to the UI a second time.
        self._notified_error: str | None = None

        self._sessions: dict[str, NoiseSession] = {}
        self._pending_messages: dict[str, list[str]] = {}
        self.peer_addresses: dict[str, str] = {}
        self.address_to_peer_id: dict[str, str] = {}
        self.peer_nicknames: dict[str, str] = {}
        self._announced_peers: set[str] = set()
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._handshake_timeout_tasks: dict[str, asyncio.Task[Any]] = {}
        self._retry_lock = asyncio.Lock()
        self.last_transport_switch_metrics: dict[str, Any] = {}
        self._transport_state_committed_at: float | None = None

        self.server_reassembler = FragmentReassembler()
        self.fragment_reassembler = self.server_reassembler
        self._prune_task: asyncio.Task[Any] | None = None
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

        self._transports["offline"] = OfflineTransport()

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
                    tcp_port=lan_tcp_port,
                    discovery_port=lan_discovery_port,
                )

            if sel == "auto":
                bt_avail = self._transports["bluetooth"].is_available()
                sel = "bluetooth" if bt_avail else "lan"

            if sel == "lan":
                self.active_transport = self._transports["lan"]
                self.active_transport_name = "lan"
            elif sel == "offline":
                self.offline_mode = True
                self.active_transport = self._transports["offline"]
                self.active_transport_name = "offline"
                self.ble_status = "offline"
            else:
                self.active_transport = self._transports["bluetooth"]
                self.active_transport_name = "bluetooth"

        self.selected_transport_name = self.active_transport_name
        self.last_successful_transport_name: str | None = None
        self._wire_transport_callbacks(self.active_transport)

    def _wire_transport_callbacks(self, transport: BaseTransport) -> None:
        """Attach session coordinator packet and state handlers to a transport."""
        generation = self._transport_generation
        transport.on_packet_received = self._handle_incoming_packet
        transport.on_peer_discovered = self._handle_peer_discovered
        transport.on_peer_connected = self._handle_peer_connected
        transport.on_peer_disconnected = self._handle_peer_disconnected
        transport.on_state_changed = lambda state: self._handle_transport_state_changed(
            transport, state, generation
        )
        transport.on_error = lambda event: self._handle_transport_error(
            transport, event, generation
        )
        transport.on_warning = lambda event: self._handle_transport_warning(
            transport, event, generation
        )

    def _handle_transport_state_changed(
        self,
        transport: BaseTransport,
        state: TransportState,
        generation: int,
    ) -> None:
        if (
            generation != self._transport_generation
            or transport is not self.active_transport
        ):
            return
        if transport.transport_type == TransportType.BLUETOOTH:
            self.ble_status = state.value
        elif transport.transport_type == TransportType.LAN:
            self.lan_status = state.value
        if self.on_peer_status_changed:
            self.on_peer_status_changed("mesh", state.value)

    def _handle_transport_error(
        self,
        transport: BaseTransport,
        event: TransportError,
        generation: int,
    ) -> None:
        if (
            generation != self._transport_generation
            or (
                transport is not self.active_transport
                and transport is not self._starting_transport
            )
            or event.transport != transport.transport_type
        ):
            return
        self.transport_errors[event.transport] = event
        self._record_transport_diagnostic(event)
        self._notified_error = event.message
        if transport is self._starting_transport:
            return
        if event.transport == TransportType.LAN:
            self.lan_error_message = event.message
            if self.on_lan_error:
                self.on_lan_error(event)
        else:
            self.ble_error_message = event.message
            if self.on_ble_error:
                self.on_ble_error(event)

    def _handle_transport_warning(
        self,
        transport: BaseTransport,
        event: TransportWarning,
        generation: int,
    ) -> None:
        if (
            generation != self._transport_generation
            or (
                transport is not self.active_transport
                and transport is not self._starting_transport
            )
            or event.transport != TransportType.BLUETOOTH
        ):
            return
        self._record_transport_diagnostic(event)
        if self.on_ble_warning:
            self.on_ble_warning(event)

    def _spawn_task(self, coro: Any) -> asyncio.Task[Any]:
        """Spawn background task and keep a reference until completion."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)

        def _task_done(completed: asyncio.Task[Any]) -> None:
            self._background_tasks.discard(completed)
            if completed.cancelled():
                return
            error = completed.exception()
            if error is not None:
                logger.error(
                    "Coordinator background task failed",
                    exc_info=(type(error), error, error.__traceback__),
                )

        task.add_done_callback(_task_done)
        return task

    @property
    def transport_generation(self) -> int:
        """Return the generation used to reject callbacks from retired operations."""
        return self._transport_generation

    @property
    def packet_deduplicator(self) -> PacketDeduplicator:
        """Return the packet deduplicator instance."""
        return self.mesh_router.deduplicator

    @property
    def store_forward(self) -> StoreAndForwardQueue:
        """Return the store-and-forward queue instance."""
        return self.mesh_router.store_forward_queue

    def prune_caches(self) -> None:
        """Prune stale fragment assemblies, dedup entries, and stored packets."""
        try:
            self.fragment_reassembler.prune_stale()
        except Exception as e:
            logger.warning("Error pruning fragment reassembler: %s", e)
        try:
            self.packet_deduplicator.prune_expired()
        except Exception as e:
            logger.warning("Error pruning packet deduplicator: %s", e)
        try:
            self.store_forward.prune_expired()
        except Exception as e:
            logger.warning("Error pruning store-and-forward queue: %s", e)
        try:
            self.mesh_router.prune_routes()
            self.mesh_router.prune_rate_limiter()
        except Exception as e:
            logger.warning("Error pruning mesh router: %s", e)

    def _start_prune_task(self) -> None:
        """Start the periodic background prune task if not already running."""
        if self._prune_task is None or self._prune_task.done():
            self._prune_task = self._spawn_task(self._periodic_prune_loop())

    async def _periodic_prune_loop(
        self, interval_seconds: float = PERIODIC_PRUNE_INTERVAL_SECONDS
    ) -> None:
        """Periodically prune expired cache entries and queues in the background."""
        try:
            while self._is_running:
                await asyncio.sleep(interval_seconds)
                self.prune_caches()
        except asyncio.CancelledError:
            pass

    def _schedule_handshake_timeout(self, peer_id: str, session: NoiseSession) -> None:
        if peer_id in self._handshake_timeout_tasks:
            return

        async def expire_handshake() -> None:
            try:
                await asyncio.sleep(NOISE_HANDSHAKE_TIMEOUT_SECONDS)
                if (
                    self._sessions.get(peer_id) is session
                    and session.state == NoiseSessionState.HANDSHAKING
                ):
                    logger.warning("Noise handshake with %s timed out", peer_id)
                    session._state = NoiseSessionState.FAILED
                    self._discard_failed_session(peer_id, session)
            finally:
                if self._handshake_timeout_tasks.get(peer_id) is asyncio.current_task():
                    self._handshake_timeout_tasks.pop(peer_id, None)

        self._handshake_timeout_tasks[peer_id] = self._spawn_task(expire_handshake())

    def _cancel_handshake_timeout(self, peer_id: str) -> None:
        task = self._handshake_timeout_tasks.pop(peer_id, None)
        if task is not None:
            task.cancel()

    async def _cancel_handshake_timeouts(self) -> None:
        tasks = list(self._handshake_timeout_tasks.values())
        self._handshake_timeout_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def expire_handshake(self, peer_id: str) -> None:
        """Expire a pending handshake for peer_id (marks FAILED and discards)."""
        session = self._sessions.get(peer_id)
        if session is not None:
            session._state = NoiseSessionState.FAILED
            self._discard_failed_session(peer_id, session, force=True)

    def _discard_failed_session(
        self, peer_id: str, session: NoiseSession, force: bool = False
    ) -> None:
        """Discard a failed or timed-out session cleanly from active sessions."""
        if not force and session.state != NoiseSessionState.FAILED:
            return
        self._cancel_handshake_timeout(peer_id)
        orig_state = session.state
        session.close()
        if orig_state == NoiseSessionState.FAILED:
            session._state = NoiseSessionState.FAILED
        if self._sessions.get(peer_id) is session:
            self._sessions.pop(peer_id, None)
        self._pending_messages.pop(peer_id, None)

    MAX_PENDING_HANDSHAKES: int = MAX_PENDING_HANDSHAKES

    @property
    def pending_handshakes_count(self) -> int:
        """Return the number of sessions currently in HANDSHAKING state."""
        return sum(
            1
            for s in self._sessions.values()
            if s.state == NoiseSessionState.HANDSHAKING
        )

    def _is_nickname_spoofed(self, peer_id_hex: str, nickname: str) -> bool:
        """Check if an announced nickname is an unauthenticated spoof attempt.

        A nickname is considered spoofed if:
        1. It is empty or whitespace.
        2. It matches the local user's nickname (case-insensitive).
        3. It matches the nickname of another peer currently known in peer_nicknames.
        """
        if not nickname or not nickname.strip():
            return True
        clean_nick = nickname.strip().lower()
        clean_pid = peer_id_hex.strip().lower()

        # Cannot claim the local user's nickname
        if self.nickname and clean_nick == self.nickname.strip().lower():
            return True

        # Cannot claim another known peer's nickname
        for pid, nick in self.peer_nicknames.items():
            if pid.lower() != clean_pid and nick.strip().lower() == clean_nick:
                return True

        return False

    @property
    def is_running(self) -> bool:
        """Return True if the coordinator is active."""
        return self._is_running

    def is_transport_starting(self, transport_name: str) -> bool:
        """Return whether the named transport is in its initialization stage."""
        return (
            self._starting_transport is not None
            and self._starting_transport.transport_type.value == transport_name
        )

    @property
    def effective_active_transport_name(self) -> str:
        """Return the transport that is actually running, or offline."""
        if (
            self.offline_mode
            or not self._is_running
            or not self.active_transport.is_running
            or self.active_transport.state
            in (
                TransportState.UNAVAILABLE,
                TransportState.DISABLED,
                TransportState.ERROR,
                TransportState.OFFLINE,
                TransportState.CHECKING,
            )
            or (
                self.active_transport_name == "bluetooth"
                and self.ble_status in ("unavailable", "disabled", "error", "offline")
            )
            or (
                self.active_transport_name == "lan"
                and (
                    not self.is_lan_available()
                    or self.active_transport.state
                    in (
                        TransportState.UNAVAILABLE,
                        TransportState.DISABLED,
                        TransportState.ERROR,
                        TransportState.OFFLINE,
                    )
                )
            )
        ):
            return "offline"
        return self.active_transport_name

    def get_or_create_session(self, remote_peer_id_hex: str) -> NoiseSession:
        """Get existing NoiseSession or initialize a new one for remote peer."""
        clean_remote = remote_peer_id_hex.strip().lower()
        if clean_remote == self.local_identity.peer_id_hex.lower():
            err_msg = (
                f"Cannot establish Noise session with self "
                f"(peer_id={remote_peer_id_hex})"
            )
            raise ValueError(err_msg)
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
        telem["selected_transport"] = self.selected_transport_name
        telem["active_transport"] = self.effective_active_transport_name
        telem["last_successful_transport"] = self.last_successful_transport_name
        telem["transport_switch_in_progress"] = self._retry_lock.locked()
        telem["transport_switch_metrics"] = dict(self.last_transport_switch_metrics)
        telem["transport_errors"] = {
            transport.value: {
                "operation": error.operation,
                "operation_id": error.operation_id,
                "stage": error.stage,
                "occurred_at": error.occurred_at,
                "message": error.message,
                "original_error": error.original_error,
                "native_error_code": error.native_error_code,
                "hresult": error.hresult,
            }
            for transport, error in self.transport_errors.items()
        }
        telem["transport_diagnostics"] = {
            transport.value: [
                {
                    "operation": event.operation,
                    "operation_id": event.operation_id,
                    "stage": event.stage,
                    "occurred_at": event.occurred_at,
                    "message": event.message,
                    "original_error": event.original_error,
                    "native_error_code": event.native_error_code,
                    "hresult": event.hresult,
                    "kind": "error" if isinstance(event, TransportError) else "warning",
                }
                for event in history
            ]
            for transport, history in self.transport_diagnostics.items()
        }
        return telem

    def _record_transport_diagnostic(
        self, event: TransportError | TransportWarning
    ) -> None:
        """Retain a bounded per-transport history independent of active mode."""
        history = self.transport_diagnostics.setdefault(event.transport, [])
        if history and history[-1].operation_id == event.operation_id:
            return
        history.append(event)
        if len(history) > 100:
            del history[:-100]

    def record_transport_indicator_update(self) -> None:
        """Record elapsed time from state commit until the UI refreshes status."""
        if not self.last_transport_switch_metrics:
            return
        if self._transport_state_committed_at is not None:
            self.last_transport_switch_metrics["indicator_update_seconds"] = max(
                0.0, perf_counter() - self._transport_state_committed_at
            )

    def _record_transport_switch_metrics(
        self,
        *,
        started_at: float,
        previous: str,
        target: str,
        cleanup_seconds: float,
        initialization_seconds: float,
        state_commit_seconds: float,
        state_committed_at: float,
        discovery_ready_at: float | None,
        result: str,
    ) -> None:
        self._transport_state_committed_at = state_committed_at
        self.last_transport_switch_metrics = {
            "previous_transport": previous,
            "requested_transport": target,
            "active_transport": self.effective_active_transport_name,
            "cleanup_seconds": cleanup_seconds,
            "initialization_seconds": initialization_seconds,
            "state_commit_seconds": state_commit_seconds,
            "total_seconds": max(0.0, perf_counter() - started_at),
            "indicator_update_seconds": None,
            "discovery_ready_seconds": (
                max(0.0, discovery_ready_at - started_at)
                if discovery_ready_at is not None
                else None
            ),
            "result": result,
        }

    @staticmethod
    def _discovery_is_operational(transport: BaseTransport) -> bool:
        """Check runtime discovery endpoints without inferring from selection."""
        telemetry = transport.get_telemetry()
        if transport.transport_type == TransportType.BLUETOOTH:
            return telemetry.get("scanner_status") == "Active" or bool(
                telemetry.get("advertising_active")
            )
        return bool(
            telemetry.get("discovery_listening")
            and telemetry.get("discovery_broadcasting")
        )

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
        error_to_notify: str | None = None
        async with self._retry_lock:
            if self._is_running:
                return
            if self.offline_mode or self.active_transport_name == "offline":
                # The user chose to continue offline: only an explicit retry or
                # transport switch may start networking again.
                logger.info("Ignoring start(): offline mode is active")
                return

            self._is_running = True
            if self.active_transport_name == "bluetooth":
                self.ble_status = "checking"
                self.ble_error_message = None
            else:
                self.lan_status = "checking"
                self.lan_error_message = None
            self._notified_error = None

            if self.ble_server:
                self.ble_server.on_data_received = self._handle_server_data_received

            self.active_transport.update_identity(
                self.local_identity.peer_id_hex, self.nickname
            )
            self._wire_transport_callbacks(self.active_transport)

            try:
                await self.active_transport.start()
                if not self._transport_is_operational():
                    failure = (
                        self.active_transport.get_telemetry().get("error_message")
                        or f"{self.active_transport_name} transport is not operational"
                    )
                    raise RuntimeError(str(failure))
                if self.active_transport_name == "bluetooth":
                    self.ble_status = self.active_transport.state.value
                elif self.active_transport_name == "lan":
                    self.lan_status = self.active_transport.state.value
                await self.send_announce()
                self._start_prune_task()
                self.selected_transport_name = self.active_transport_name
                self.last_successful_transport_name = self.active_transport_name
            except Exception as e:
                self._is_running = False
                logger.warning(
                    "Could not start active transport %s: %s",
                    self.active_transport_name,
                    e,
                )
                failed_state = self.active_transport.state
                await self._stop_transport_safely(
                    self.active_transport_name, self.active_transport
                )
                effective_state = self._preserve_failed_transport_state(
                    self.active_transport, failed_state, str(e)
                )
                if self.active_transport_name == "bluetooth":
                    self.ble_status = effective_state.value
                    self.ble_error_message = str(e)
                else:
                    self.lan_error_message = str(e)
                error_to_notify = str(e)

        if error_to_notify is not None and error_to_notify != self._notified_error:
            self.active_transport.report_error("start", error_to_notify)

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
        if self.active_transport_name == "bluetooth" and not isinstance(
            self.active_transport, BluetoothTransport
        ):
            return self.active_transport.is_running
        if self.active_transport_name == "lan" and not isinstance(
            self.active_transport, LANTransport
        ):
            return self.active_transport.is_running
        telem = self.active_transport.get_telemetry()
        if self.active_transport_name == "bluetooth":
            if telem.get("adapter_state") != "On":
                if self._uses_injected_ble_backend():
                    return bool(
                        telem.get("scanner_status") == "Active"
                        or telem.get("advertising_active")
                    )
                return False
            return bool(
                (
                    telem.get("central_supported")
                    and telem.get("scanner_status") == "Active"
                )
                or (
                    telem.get("peripheral_supported")
                    and telem.get("advertising_active")
                )
            )
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

    def is_ble_available(self) -> bool:
        """Return True if Bluetooth transport is registered and available."""
        bt = self._transports.get("bluetooth")
        if bt is None:
            return False
        return bt.is_available()

    def is_lan_available(self) -> bool:
        """Return True if LAN transport is registered and network is usable."""
        lan = self._transports.get("lan")
        if lan is None:
            return False
        return lan.is_available()

    def _preserve_failed_transport_state(
        self,
        transport: BaseTransport,
        failed_state: TransportState,
        error_message: str,
    ) -> TransportState:
        """Restore failure state and error message after _stop_transport_safely."""
        effective_state = (
            failed_state
            if failed_state
            in (
                TransportState.UNAVAILABLE,
                TransportState.DISABLED,
                TransportState.ERROR,
            )
            else TransportState.UNAVAILABLE
        )
        if hasattr(transport, "_state"):
            transport._state = effective_state  # type: ignore[attr-defined]
        if hasattr(transport, "_error_message"):
            transport._error_message = error_message  # type: ignore[attr-defined]
        return effective_state

    async def retry_active_transport(self) -> bool:
        """Re-initialize the active transport after failure. Success is operational.

        The attempt is bounded by ``TRANSPORT_RETRY_TIMEOUT_SECONDS`` and
        serialised by ``_retry_lock`` so repeated clicks cannot stack up
        concurrent restarts. Failed resources are released before returning.
        """
        async with self._retry_lock:
            if self.offline_mode or self.active_transport_name == "offline":
                logger.info("Ignoring retry: offline mode is active")
                return False
            self._transport_generation += 1
            self._wire_transport_callbacks(self.active_transport)
            if self.active_transport_name == "bluetooth":
                self.ble_status = "checking"
                self.ble_error_message = None
            else:
                self.lan_error_message = None
            await self._stop_transport_safely(
                self.active_transport_name, self.active_transport
            )
            try:
                await asyncio.wait_for(
                    self.active_transport.start(),
                    timeout=TRANSPORT_RETRY_TIMEOUT_SECONDS,
                )
                self._is_running = True
                if self.active_transport_name == "bluetooth":
                    self.ble_status = self.active_transport.state.value
                if not self._transport_is_operational():
                    failed_state = self.active_transport.state
                    failed_message = (
                        self.active_transport.get_telemetry().get("error_message")
                        or "Transport is not operational"
                    )
                    await self._stop_transport_safely(
                        self.active_transport_name, self.active_transport
                    )
                    effective_state = self._preserve_failed_transport_state(
                        self.active_transport, failed_state, str(failed_message)
                    )
                    self._is_running = False
                    if self.active_transport_name == "bluetooth":
                        self.ble_status = effective_state.value
                        self.ble_error_message = str(failed_message)
                    else:
                        self.lan_error_message = str(failed_message)
                    return False
                self.offline_mode = False
                await self.send_announce()
                self._start_prune_task()
                return True
            except TimeoutError:
                logger.warning(
                    "Retry of %s transport timed out after %.0fs",
                    self.active_transport_name,
                    TRANSPORT_RETRY_TIMEOUT_SECONDS,
                )
                err_msg = (
                    f"Retry timed out after {TRANSPORT_RETRY_TIMEOUT_SECONDS:.0f}s"
                )
                await self._stop_transport_safely(
                    self.active_transport_name, self.active_transport
                )
                self._preserve_failed_transport_state(
                    self.active_transport, TransportState.UNAVAILABLE, err_msg
                )
                self._is_running = False
                if self.active_transport_name == "bluetooth":
                    self.ble_status = "unavailable"
                    self.ble_error_message = err_msg
                else:
                    self.lan_error_message = err_msg
                return False
            except Exception as e:
                logger.warning("Retry active transport failed: %s", e)
                failed_state = self.active_transport.state
                await self._stop_transport_safely(
                    self.active_transport_name, self.active_transport
                )
                effective_state = self._preserve_failed_transport_state(
                    self.active_transport, failed_state, str(e)
                )
                self._is_running = False
                if self.active_transport_name == "bluetooth":
                    self.ble_status = effective_state.value
                    self.ble_error_message = str(e)
                else:
                    self.lan_error_message = str(e)
                return False

    async def retry_ble(self) -> bool:
        """Re-initialize the active Bluetooth transport after failure."""
        if self.offline_mode or self.active_transport_name == "offline":
            logger.info("Ignoring retry_ble: offline mode is active")
            return False
        if self.active_transport_name != "bluetooth":
            success, _ = await self.switch_transport("bluetooth")
            return success
        return await self.retry_active_transport()

    async def retry_ble_independent(self) -> bool:
        """Retry BLE without changing or stopping the selected non-BLE transport."""
        if self.offline_mode or self.active_transport_name == "offline":
            logger.info("Ignoring retry_ble_independent: offline mode is active")
            return False
        if self.active_transport_name == "bluetooth":
            return await self.retry_active_transport()

        retry_active_after_lock = False
        async with self._retry_lock:
            if self.active_transport_name == "bluetooth":
                retry_active_after_lock = True
            else:
                transport = self._transports.get("bluetooth")
                if transport is None:
                    return False

                previous_starting = self._starting_transport
                self._starting_transport = transport
                self._wire_transport_callbacks(transport)
                try:
                    if transport.is_running:
                        await self._stop_transport_safely("bluetooth", transport)
                    await asyncio.wait_for(
                        transport.start(),
                        timeout=TRANSPORT_RETRY_TIMEOUT_SECONDS,
                    )
                    return transport.is_running and transport.state not in {
                        TransportState.ERROR,
                        TransportState.UNAVAILABLE,
                        TransportState.DISABLED,
                        TransportState.OFFLINE,
                    }
                except TimeoutError:
                    logger.warning(
                        "Independent BLE retry timed out after %.0fs",
                        TRANSPORT_RETRY_TIMEOUT_SECONDS,
                    )
                    return False
                except Exception:
                    logger.exception("Independent BLE retry failed")
                    return False
                finally:
                    self._starting_transport = previous_starting

        if retry_active_after_lock:
            return await self.retry_active_transport()
        return False

    async def retry_lan(self) -> bool:
        """Re-initialize the active LAN transport after failure."""
        if self.offline_mode or self.active_transport_name == "offline":
            logger.info("Ignoring retry_lan: offline mode is active")
            return False
        if self.active_transport_name != "lan":
            success, _ = await self.switch_transport("lan")
            return success
        return await self.retry_active_transport()

    async def stop(self) -> None:
        """Shutdown coordinator, close sessions, and stop all transports."""
        self._is_running = False
        self.ble_status = "offline"
        self.ble_error_message = None

        if self._prune_task and not self._prune_task.done():
            self._prune_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._prune_task
        self._prune_task = None

        await self._cancel_handshake_timeouts()
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()
        self._pending_messages.clear()
        self._announced_peers.clear()

        # Cancel and cleanly cleanup any remaining background tasks
        current_t = asyncio.current_task()
        pending_bg = [
            t for t in self._background_tasks if not t.done() and t is not current_t
        ]
        for t in pending_bg:
            t.cancel()
        if pending_bg:
            await asyncio.gather(*pending_bg, return_exceptions=True)
        self._background_tasks.clear()

        for name, transport in list(self._transports.items()):
            self._detach_transport_callbacks(transport)
            await self._stop_transport_safely(name, transport)

    def _detach_transport_callbacks(self, transport: BaseTransport) -> None:
        """Stop a retired transport from delivering events to the coordinator."""
        transport.on_packet_received = None
        transport.on_peer_discovered = None
        transport.on_peer_connected = None
        transport.on_peer_disconnected = None
        transport.on_state_changed = None
        transport.on_error = None
        transport.on_warning = None

    async def _stop_transport_safely(self, name: str, transport: BaseTransport) -> None:
        """Stop a transport, logging (not propagating) shutdown failures."""
        try:
            await transport.stop()
        except Exception as e:
            logger.warning("Error stopping %s transport: %s", name, e)

    async def _reset_session_state(self) -> None:
        """Close Noise sessions and clear peer tables bound to a transport."""
        await self._cancel_handshake_timeouts()
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()
        self.peer_addresses.clear()
        self.address_to_peer_id.clear()
        self.peer_nicknames.clear()
        self._announced_peers.clear()
        for transport in self._transports.values():
            disc: Any = getattr(transport, "discovery", None)
            if disc is not None and hasattr(disc, "clear"):
                disc.clear()
            scn: Any = getattr(transport, "scanner", None)
            if scn is not None and hasattr(scn, "clear"):
                scn.clear()
            bm: Any = getattr(transport, "ble_manager", None)
            if bm is not None and hasattr(bm, "scanner"):
                bm.scanner.clear()
        self._pending_messages.clear()

    async def go_offline(self) -> None:
        """Deliberately disable all networking for this session.

        Stops every transport (including their adapter/network monitors, so
        nothing restarts in the background), closes sessions, and records that
        the user chose offline mode. The persisted identity is untouched.
        Idempotent and safe after partial initialization.
        """
        async with self._retry_lock:
            self._transport_generation += 1
            await self._go_offline_locked()

    async def _go_offline_locked(self) -> None:
        """Internal helper for go_offline assuming _retry_lock is already held."""
        self.offline_mode = True
        if self.selected_transport_name == "offline":
            self.active_transport_name = "offline"
            if "offline" in self._transports:
                self.active_transport = self._transports["offline"]

        if self._prune_task and not self._prune_task.done():
            self._prune_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._prune_task
        self._prune_task = None

        current_t = asyncio.current_task()
        pending_bg = [
            t for t in self._background_tasks if not t.done() and t is not current_t
        ]
        for t in pending_bg:
            t.cancel()
        if pending_bg:
            await asyncio.gather(*pending_bg, return_exceptions=True)
        self._background_tasks.clear()

        for name, transport in list(self._transports.items()):
            if hasattr(transport, "set_offline"):
                transport.set_offline(True)
            self._detach_transport_callbacks(transport)
            await self._stop_transport_safely(name, transport)

        await self._reset_session_state()
        self._is_running = False
        self.ble_status = "offline"
        self.lan_status = "offline"
        self.ble_error_message = None
        self.lan_error_message = None
        self.transport_errors.clear()

        if self.on_peer_status_changed:
            self.on_peer_status_changed("mesh", "offline")

    async def switch_transport(self, target_transport: str) -> tuple[bool, str]:
        """Switch between Bluetooth, LAN, and offline modes.

        Guarantees verified state transitions and invariant cryptographic identity.
        """
        switch_started_at = perf_counter()
        target = normalize_transport_name(target_transport)
        if target is None:
            return False, f"Unknown transport: {target_transport.strip()}"

        async with self._retry_lock:
            prev_name = self.active_transport_name
            current_id = self.local_identity.peer_id_hex

            if target == "offline":
                cleanup_started_at = perf_counter()
                self._transport_generation += 1
                self.selected_transport_name = "offline"
                self.active_transport_name = "offline"
                if "offline" in self._transports:
                    self.active_transport = self._transports["offline"]
                await self._go_offline_locked()
                state_committed_at = perf_counter()
                self._record_transport_switch_metrics(
                    started_at=switch_started_at,
                    previous=prev_name,
                    target=target,
                    cleanup_seconds=state_committed_at - cleanup_started_at,
                    initialization_seconds=0.0,
                    state_commit_seconds=0.0,
                    state_committed_at=state_committed_at,
                    discovery_ready_at=None,
                    result="success",
                )
                log_transport_diagnostic(
                    operation="transport_switch",
                    stage="switch_complete",
                    result="SUCCESS",
                    requested_transport="offline",
                    previous_transport=prev_name,
                    active_transport="offline",
                    details=(
                        "Transport switched to offline mode; local identity preserved."
                    ),
                )
                return (
                    True,
                    f"Switched transport to offline. Peer identity: {current_id[:12]}",
                )

            if (
                target == self.active_transport_name
                and self.active_transport.is_running
            ):
                self.selected_transport_name = target
                state_committed_at = perf_counter()
                self._record_transport_switch_metrics(
                    started_at=switch_started_at,
                    previous=prev_name,
                    target=target,
                    cleanup_seconds=0.0,
                    initialization_seconds=0.0,
                    state_commit_seconds=0.0,
                    state_committed_at=state_committed_at,
                    discovery_ready_at=(
                        state_committed_at
                        if self._discovery_is_operational(self.active_transport)
                        else None
                    ),
                    result="already_active",
                )
                return True, f"Already active on {target} transport."

            if target == "bluetooth" and "bluetooth" not in self._transports:
                # Validate before tearing anything down or rotating identity.
                return False, "Bluetooth transport not available"

            self._transport_generation += 1
            logger.info(
                "Switching transport: %s -> %s", self.active_transport_name, target
            )
            log_transport_diagnostic(
                operation="transport_switch",
                stage="init",
                result="STARTING",
                requested_transport=target,
                previous_transport=prev_name,
                details=f"Initiating switch from {prev_name} to {target}",
            )

            # 1. Stop old transport completely and detach it from the coordinator
            old_transport = self.active_transport
            old_was_running = old_transport.is_running
            cleanup_started_at = perf_counter()
            self._detach_transport_callbacks(old_transport)
            await self._stop_transport_safely(self.active_transport_name, old_transport)

            # 2-3. Close active Noise sessions, clear peer tables and pending messages
            await self._reset_session_state()

            # 4. Preserve stable persistent identity across transport interfaces
            for transport in self._transports.values():
                transport.update_identity(current_id, self.nickname)
            logger.info(
                "Transport switch (%s -> %s): preserved device identity %s",
                prev_name,
                target,
                current_id,
            )

            # 5. Prepare candidate transport
            if target == "lan":
                if "lan" not in self._transports:
                    self._transports["lan"] = LANTransport(
                        local_peer_id=current_id,
                        local_nickname=self.nickname,
                    )
                candidate_transport = self._transports["lan"]
            else:
                candidate_transport = self._transports["bluetooth"]

            if hasattr(candidate_transport, "set_offline"):
                candidate_transport.set_offline(False)
            candidate_error_before = candidate_transport.last_error
            self._wire_transport_callbacks(candidate_transport)

            # 6. Start candidate transport; update active_transport ONLY after success
            initialization_started_at = perf_counter()
            cleanup_seconds = initialization_started_at - cleanup_started_at
            initialization_seconds = 0.0
            discovery_ready_at: float | None = None
            state_commit_seconds = 0.0
            state_committed_at = perf_counter()
            try:
                self._starting_transport = candidate_transport
                try:
                    await candidate_transport.start()
                finally:
                    self._starting_transport = None
                if not candidate_transport.is_running or candidate_transport.state in (
                    TransportState.UNAVAILABLE,
                    TransportState.DISABLED,
                    TransportState.ERROR,
                    TransportState.OFFLINE,
                    TransportState.CHECKING,
                ):
                    failed_message = (
                        candidate_transport.get_telemetry().get("error_message")
                        or f"{target} transport is not operational"
                    )
                    raise RuntimeError(failed_message)

                initialization_seconds = perf_counter() - initialization_started_at
                if self._discovery_is_operational(candidate_transport):
                    discovery_ready_at = perf_counter()

                # SUCCESS! Update active transport state only after verification
                state_commit_started_at = perf_counter()
                self.active_transport = candidate_transport
                self.active_transport_name = target
                self.selected_transport_name = target
                self.last_successful_transport_name = target
                if target == "bluetooth":
                    self.ble_status = candidate_transport.state.value
                    self.ble_error_message = None
                else:
                    self.lan_status = candidate_transport.state.value
                    self.lan_error_message = None
                self.offline_mode = False
                self._is_running = True
                state_committed_at = perf_counter()
                state_commit_seconds = state_committed_at - state_commit_started_at
                await self.send_announce()
                self._start_prune_task()
                self._record_transport_switch_metrics(
                    started_at=switch_started_at,
                    previous=prev_name,
                    target=target,
                    cleanup_seconds=cleanup_seconds,
                    initialization_seconds=initialization_seconds,
                    state_commit_seconds=state_commit_seconds,
                    state_committed_at=state_committed_at,
                    discovery_ready_at=discovery_ready_at,
                    result="success",
                )

                log_transport_diagnostic(
                    operation="transport_switch",
                    stage="switch_complete",
                    result="SUCCESS",
                    requested_transport=target,
                    previous_transport=prev_name,
                    active_transport=target,
                    details=f"Transport switch to {target} succeeded.",
                )
                display_name = "LAN / Wi-Fi" if target == "lan" else "Bluetooth"
                return True, (
                    f"Switched transport to {display_name}. "
                    f"New secure chat session created. "
                    f"Peer identity: {current_id[:12]}"
                )
            except asyncio.CancelledError:
                initialization_seconds = perf_counter() - initialization_started_at
                if self.active_transport is candidate_transport:
                    self._record_transport_switch_metrics(
                        started_at=switch_started_at,
                        previous=prev_name,
                        target=target,
                        cleanup_seconds=cleanup_seconds,
                        initialization_seconds=initialization_seconds,
                        state_commit_seconds=state_commit_seconds,
                        state_committed_at=state_committed_at,
                        discovery_ready_at=discovery_ready_at,
                        result="cancelled_after_commit",
                    )
                    raise

                self._detach_transport_callbacks(candidate_transport)
                await self._stop_transport_safely(target, candidate_transport)
                self.active_transport = old_transport
                self.active_transport_name = prev_name
                self._transport_generation += 1
                self._wire_transport_callbacks(old_transport)
                rollback_succeeded = False
                if old_was_running:
                    try:
                        await asyncio.wait_for(
                            old_transport.start(),
                            timeout=TRANSPORT_RETRY_TIMEOUT_SECONDS,
                        )
                        rollback_succeeded = self._transport_is_operational()
                    except Exception:
                        logger.exception(
                            "Failed restoring %s after cancelled transport switch",
                            prev_name,
                        )
                self._is_running = rollback_succeeded
                self.offline_mode = old_was_running and not rollback_succeeded
                if rollback_succeeded:
                    self._start_prune_task()
                    with contextlib.suppress(Exception):
                        await self.send_announce()
                self._record_transport_switch_metrics(
                    started_at=switch_started_at,
                    previous=prev_name,
                    target=target,
                    cleanup_seconds=cleanup_seconds,
                    initialization_seconds=initialization_seconds,
                    state_commit_seconds=0.0,
                    state_committed_at=perf_counter(),
                    discovery_ready_at=None,
                    result="cancelled",
                )
                raise
            except Exception as e:
                initialization_seconds = perf_counter() - initialization_started_at
                logger.error("Failed starting %s transport: %s", target, e)
                # Cleanup candidate transport
                self._detach_transport_callbacks(candidate_transport)
                await self._stop_transport_safely(target, candidate_transport)
                failed_state = candidate_transport.state
                self._preserve_failed_transport_state(
                    candidate_transport, failed_state, str(e)
                )

                self.active_transport = old_transport
                self.active_transport_name = prev_name
                self._transport_generation += 1
                self._wire_transport_callbacks(self.active_transport)

                if target == "bluetooth":
                    self.ble_error_message = str(e)
                else:
                    self.lan_error_message = str(e)
                candidate_error = candidate_transport.last_error
                if candidate_error is None or candidate_error is candidate_error_before:
                    error_code = getattr(e, "winerror", None) or getattr(
                        e, "errno", None
                    )
                    candidate_error = candidate_transport.report_error(
                        "transport_switch",
                        str(e),
                        stage=str(
                            candidate_transport.get_telemetry().get("failed_stage")
                            or "transport_start"
                        ),
                        original_error=e,
                        native_error_code=error_code,
                        hresult=(
                            str(hresult_value)
                            if (hresult_value := getattr(e, "hresult", None))
                            is not None
                            else None
                        ),
                    )
                assert candidate_error is not None
                self.transport_errors[candidate_transport.transport_type] = (
                    candidate_error
                )
                self._record_transport_diagnostic(candidate_error)

                rollback_error: Exception | None = None
                rollback_succeeded = False
                if old_was_running:
                    try:
                        await asyncio.wait_for(
                            old_transport.start(),
                            timeout=TRANSPORT_RETRY_TIMEOUT_SECONDS,
                        )
                        if not old_transport.is_running or old_transport.state in (
                            TransportState.UNAVAILABLE,
                            TransportState.DISABLED,
                            TransportState.ERROR,
                            TransportState.OFFLINE,
                            TransportState.CHECKING,
                        ):
                            raise RuntimeError(f"{prev_name} transport did not recover")
                        rollback_succeeded = True
                    except Exception as rollback_exc:
                        rollback_error = rollback_exc
                        logger.error(
                            "Failed restoring %s transport after switch failure: %s",
                            prev_name,
                            rollback_exc,
                        )
                        await self._stop_transport_safely(prev_name, old_transport)
                        rollback_state = self._preserve_failed_transport_state(
                            old_transport, old_transport.state, str(rollback_exc)
                        )
                        if prev_name == "bluetooth":
                            self.ble_status = rollback_state.value
                            self.ble_error_message = str(rollback_exc)
                        else:
                            self.lan_error_message = str(rollback_exc)

                if prev_name == "offline":
                    self.active_transport = self._transports["offline"]
                    self.active_transport_name = "offline"
                    self.selected_transport_name = "offline"
                    self.offline_mode = True
                    self._is_running = False
                    self.ble_status = "offline"
                else:
                    self._is_running = rollback_succeeded
                    self.offline_mode = old_was_running and not rollback_succeeded
                if rollback_succeeded:
                    if prev_name == "bluetooth":
                        self.ble_status = old_transport.state.value
                        self.ble_error_message = None
                    else:
                        self.lan_error_message = None
                    try:
                        await self.send_announce()
                    except Exception:
                        logger.exception(
                            "Failed announcing after restoring %s transport",
                            prev_name,
                        )
                    self._start_prune_task()
                self._record_transport_switch_metrics(
                    started_at=switch_started_at,
                    previous=prev_name,
                    target=target,
                    cleanup_seconds=cleanup_seconds,
                    initialization_seconds=initialization_seconds,
                    state_commit_seconds=0.0,
                    state_committed_at=perf_counter(),
                    discovery_ready_at=None,
                    result="failed_rollback_succeeded"
                    if rollback_succeeded
                    else "failed",
                )

                log_transport_diagnostic(
                    operation="transport_switch",
                    stage="target_start",
                    result="FAILED",
                    requested_transport=target,
                    previous_transport=prev_name,
                    active_transport=self.active_transport_name,
                    cleanup_result=(
                        "candidate_released_previous_transport_restored"
                        if rollback_succeeded
                        else "candidate_released_rollback_failed"
                        if rollback_error
                        else "candidate_released_previous_transport_was_stopped"
                    ),
                    details=(
                        f"{e}; rollback failed: {rollback_error}"
                        if rollback_error
                        else str(e)
                    ),
                )
                rollback_message = (
                    f" {prev_name} transport restored."
                    if rollback_succeeded
                    else (
                        f" Failed to restore {prev_name} transport: {rollback_error}"
                        if rollback_error
                        else ""
                    )
                )
                return (
                    False,
                    f"Failed starting {target} transport: {e}.{rollback_message}",
                )

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
        if self.offline_mode or self.active_transport_name == "offline":
            logger.info("Cannot send broadcast message: offline mode is active")
            return
        encoded = text.encode("utf-8")
        if len(encoded) > MAX_MESSAGE_SIZE:
            msg = f"Message payload exceeds maximum size ({MAX_MESSAGE_SIZE} bytes)"
            raise ValueError(msg)
        packet = BitchatPacket.create(
            message_type=MessageType.Message,
            sender_id=self.local_identity.peer_id,
            payload=encoded,
        )
        await self._broadcast_packet(packet)

    async def send_direct_message(self, target_peer_id_hex: str, text: str) -> None:
        """Send an encrypted message to a peer, establishing Noise XX if needed."""
        if self.offline_mode or self.active_transport_name == "offline":
            logger.info("Cannot send direct message: offline mode is active")
            return
        encoded = text.encode("utf-8")
        if len(encoded) > MAX_MESSAGE_SIZE:
            msg = f"Message payload exceeds maximum size ({MAX_MESSAGE_SIZE} bytes)"
            raise ValueError(msg)
        session = self.get_or_create_session(target_peer_id_hex)

        if not session.is_established:
            self._pending_messages.setdefault(target_peer_id_hex, []).append(text)
            if session.state == NoiseSessionState.UNINITIALIZED:
                if session.role == NoiseRole.INITIATOR:
                    init_payload = session.start_handshake()
                    if init_payload is not None:
                        self._schedule_handshake_timeout(target_peer_id_hex, session)
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

    def _resolve_connected_peer_address(self, target_peer_id_hex: str) -> str | None:
        """Return an active connected transport address for target_peer_id_hex."""
        connected = set(self.active_transport.connected_peers)
        target_addr = self.peer_addresses.get(target_peer_id_hex)
        if target_addr and target_addr in connected:
            return target_addr
        target_lower = target_peer_id_hex.lower()
        for addr, pid in self.address_to_peer_id.items():
            if pid.lower() == target_lower and addr in connected:
                return addr
        if target_peer_id_hex in connected:
            return target_peer_id_hex
        return None

    async def _send_packet(
        self, target_peer_id_hex: str | None, packet: BitchatPacket
    ) -> None:
        """Transmit packet via direct transport connection or broadcast."""
        if self.offline_mode or self.active_transport_name == "offline":
            return
        self.mesh_router.deduplicator.record(packet)

        target_addr: str | None = None
        if target_peer_id_hex:
            target_addr = self._resolve_connected_peer_address(target_peer_id_hex)
            if not target_addr:
                next_hop = self.mesh_router.get_next_hop(target_peer_id_hex)
                if next_hop:
                    target_addr = self._resolve_connected_peer_address(next_hop)

        if target_addr:
            await self.active_transport.send_to_peer(target_addr, packet)
            return

        await self.active_transport.broadcast_packet(packet)

    async def _broadcast_packet(
        self, packet: BitchatPacket, exclude_peer: str | None = None
    ) -> None:
        """Broadcast packet across all active transport peers."""
        if self.offline_mode or self.active_transport_name == "offline":
            return
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
            try:
                reassembled_wire = self.server_reassembler.add_fragment_packet(packet)
            except (InvalidFragmentError, FragmentLimitExceededError) as e:
                logger.warning(
                    "Invalid or oversized fragment from server client %s: %s",
                    client_id,
                    e,
                )
                return
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
        if self.offline_mode or self.active_transport_name == "offline":
            return
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
            success = self.mesh_router.store_forward_queue.enqueue(
                decision.target_peer_id_hex, packet
            )
            if not success:
                logger.warning(
                    "Store-and-forward queue full; packet for %s dropped",
                    decision.target_peer_id_hex,
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

        if target_peer_id_hex is None:
            jitter = self.mesh_router.get_relay_jitter()
            try:
                await asyncio.sleep(jitter)
            except asyncio.CancelledError:
                return

        if not self._is_running:
            return

        try:
            if target_peer_id_hex:
                target_addr = self._resolve_connected_peer_address(target_peer_id_hex)
                if not target_addr:
                    next_hop = self.mesh_router.get_next_hop(target_peer_id_hex)
                    if next_hop:
                        target_addr = self._resolve_connected_peer_address(next_hop)

                if target_addr and target_addr != exclude_ingress:
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
                    success = self.mesh_router.store_forward_queue.enqueue(
                        target_peer_id_hex, packet
                    )
                    if not success:
                        logger.warning(
                            "Store-and-forward queue full; packet for %s dropped",
                            target_peer_id_hex,
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
        if sender_hex.lower() == self.local_identity.peer_id_hex.lower():
            logger.debug(
                "Ignoring packet looped back from local device identity %s", sender_hex
            )
            return
        is_direct_neighbor = peer_address is not None and (
            packet.sender_id.hex() == peer_address or packet.ttl >= MAX_TTL
        )
        if peer_address and is_direct_neighbor:
            self.address_to_peer_id[peer_address] = sender_hex
            is_inbound_lan = isinstance(
                self.active_transport, LANTransport
            ) and self.active_transport.is_inbound_connection(peer_address)
            if not is_inbound_lan:
                self.peer_addresses[sender_hex] = peer_address

        # Learn route to sender in mesh router
        if peer_address:
            next_hop = self.address_to_peer_id.get(peer_address, peer_address)
            hop_count = max(1, MAX_TTL - packet.ttl + 1) if packet.ttl <= MAX_TTL else 1
            self.mesh_router.add_route(
                destination=sender_hex,
                next_hop=next_hop,
                hop_count=hop_count,
            )

        match packet.message_type:
            case MessageType.Announce:
                nickname = packet.payload.decode("utf-8", errors="replace").strip()
                if self._is_nickname_spoofed(sender_hex, nickname):
                    logger.warning(
                        "Rejected spoofed nickname '%s' from %s", nickname, sender_hex
                    )
                else:
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
                existing_session = self._sessions.get(sender_hex)
                is_pending = (
                    existing_session is not None
                    and existing_session.state == NoiseSessionState.HANDSHAKING
                )
                if (
                    not is_pending
                    and self.pending_handshakes_count >= MAX_PENDING_HANDSHAKES
                ):
                    logger.warning(
                        "Rejecting HandshakeRequest from %s: "
                        "pending handshake limit (%d) reached",
                        sender_hex,
                        MAX_PENDING_HANDSHAKES,
                    )
                    return

                session = self.get_or_create_session(sender_hex)
                if (
                    session.role == NoiseRole.INITIATOR
                    and session.state == NoiseSessionState.UNINITIALIZED
                ):
                    init_payload = session.start_handshake()
                    if init_payload is not None:
                        self._schedule_handshake_timeout(sender_hex, session)
                        resp_pkt = BitchatPacket.create(
                            message_type=MessageType.NoiseHandshakeInit,
                            sender_id=self.local_identity.peer_id,
                            recipient_id=packet.sender_id,
                            payload=init_payload,
                        )
                        await self._send_packet(sender_hex, resp_pkt)

            case MessageType.NoiseHandshakeInit:
                existing_session = self._sessions.get(sender_hex)
                is_pending = (
                    existing_session is not None
                    and existing_session.state == NoiseSessionState.HANDSHAKING
                )
                if (
                    not is_pending
                    and self.pending_handshakes_count >= MAX_PENDING_HANDSHAKES
                ):
                    logger.warning(
                        "Rejecting NoiseHandshakeInit from %s: "
                        "pending handshake limit (%d) reached",
                        sender_hex,
                        MAX_PENDING_HANDSHAKES,
                    )
                    return

                session = self.get_or_create_session(sender_hex)
                try:
                    resp_payload = session.process_handshake_message(packet.payload)
                except Exception as e:
                    logger.warning(
                        "NoiseHandshakeInit failed from %s: %s", sender_hex, e
                    )
                    self._discard_failed_session(sender_hex, session)
                    return

                if session.state == NoiseSessionState.HANDSHAKING:
                    self._schedule_handshake_timeout(sender_hex, session)
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
                    self._discard_failed_session(sender_hex, session)
                    return

                if session.state == NoiseSessionState.HANDSHAKING:
                    self._schedule_handshake_timeout(sender_hex, session)
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
                if session is not None and not session.is_established:
                    for _ in range(25):
                        await asyncio.sleep(0.04)
                        if session.is_established:
                            break

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
        self._cancel_handshake_timeout(remote_peer_id_hex)
        fingerprint = session.remote_fingerprint or ""

        # Peer authentication & TOFU verification
        if self.storage is not None and fingerprint:
            try:
                config = self.storage.load_config()
                if not config.verify_contact(remote_peer_id_hex, fingerprint):
                    logger.error(
                        "TOFU verification failed for peer %s: fingerprint mismatch "
                        "(expected %s, got %s)",
                        remote_peer_id_hex,
                        config.get_contact_fingerprint(remote_peer_id_hex),
                        fingerprint,
                    )
                    session._state = NoiseSessionState.FAILED
                    self._discard_failed_session(remote_peer_id_hex, session)
                    return
                self.storage.save_config(config)
            except Exception as e:
                logger.warning("Error during TOFU contact verification: %s", e)

        if self.on_handshake_completed:
            self.on_handshake_completed(remote_peer_id_hex, fingerprint)

        pending = self._pending_messages.pop(remote_peer_id_hex, [])
        for text in pending:
            self._spawn_task(self.send_direct_message(remote_peer_id_hex, text))

    def _handle_peer_discovered(self, peer: Any) -> None:
        """Record a peer discovered by the active transport."""
        if self.offline_mode or self.active_transport_name == "offline":
            return
        clean_pid = peer.peer_id.lower() if getattr(peer, "peer_id", None) else ""
        if clean_pid and clean_pid == self.local_identity.peer_id_hex.lower():
            logger.debug(
                "Ignoring discovered peer matching local device identity %s", clean_pid
            )
            return
        name = getattr(peer, "name", None) or getattr(peer, "nickname", None)
        previous_nick = self.peer_nicknames.get(clean_pid) if clean_pid else None
        announce_key = clean_pid or peer.address.lower()
        already_announced = announce_key in self._announced_peers

        if clean_pid:
            previous_owner = self.address_to_peer_id.get(peer.address)
            if previous_owner and previous_owner != clean_pid:
                if self.peer_addresses.get(previous_owner) == peer.address:
                    self.peer_addresses.pop(previous_owner, None)
                    self.peer_nicknames.pop(previous_owner, None)
                self._announced_peers.discard(previous_owner)
            previous_address = self.peer_addresses.get(clean_pid)
            if (
                previous_address
                and previous_address != peer.address
                and previous_address not in self.active_transport.connected_peers
                and self.address_to_peer_id.get(previous_address) == clean_pid
            ):
                self.address_to_peer_id.pop(previous_address, None)
            self.peer_addresses[clean_pid] = peer.address
            self.address_to_peer_id[peer.address] = clean_pid
            if name:
                if self._is_nickname_spoofed(clean_pid, name):
                    logger.warning(
                        "Rejected spoofed discovery nickname '%s' from %s",
                        name,
                        clean_pid,
                    )
                else:
                    self.peer_nicknames[clean_pid] = name

        self._announced_peers.add(announce_key)

        if self.on_peer_status_changed:
            nick_changed = bool(
                clean_pid and name and previous_nick and previous_nick != name
            )
            if already_announced and not nick_changed:
                self.on_peer_status_changed("mesh", self.ble_status)
                return
            status = f"Discovered: {name or 'Unknown'}"
            rssi = getattr(peer, "rssi", None)
            if rssi is not None:
                status += f" ({rssi} dBm)"
            self.on_peer_status_changed(peer.address, status)

    def _handle_peer_connected(self, peer_address: str) -> None:
        """Callback when a central connection to peer is established."""
        if self.offline_mode or self.active_transport_name == "offline":
            return
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
        self._announced_peers.discard(peer_address.lower())
        peer_id = self.address_to_peer_id.pop(peer_address, None)
        if peer_id:
            if self.peer_addresses.get(peer_id) == peer_address:
                self.peer_addresses.pop(peer_id, None)

            # If the peer is still present in active_transport.discovered_peers,
            # restore its discovered address mapping so it remains addressable.
            still_discovered = False
            for disc_addr, disc_peer in self.active_transport.discovered_peers.items():
                disc_pid = getattr(disc_peer, "peer_id", None)
                if disc_pid and disc_pid.lower() == peer_id.lower():
                    still_discovered = True
                    self.peer_addresses.setdefault(peer_id, disc_addr)
                    self.address_to_peer_id.setdefault(disc_addr, peer_id)
                    break

            peer_still_connected = any(
                address in self.active_transport.connected_peers
                for address, mapped_peer_id in self.address_to_peer_id.items()
                if mapped_peer_id == peer_id
            )
            if not peer_still_connected:
                if not still_discovered:
                    self._announced_peers.discard(peer_id)
                self._cancel_handshake_timeout(peer_id)
                session = self._sessions.pop(peer_id, None)
                if session is not None:
                    session.close()
                self._pending_messages.pop(peer_id, None)
        if self.on_peer_status_changed:
            self.on_peer_status_changed(peer_address, "Disconnected")

    async def connect_peer(self, target: str, timeout: float = 10.0) -> Any:
        """Establish connection to a target peer ID, nickname, or address."""
        if self.offline_mode or self.active_transport_name == "offline":
            raise RuntimeError("Cannot connect to peer: offline mode is active")
        resolved = self.resolve_peer_address(target) or target
        return await self.active_transport.connect_peer(resolved, timeout=timeout)

    async def disconnect_peer(self, target: str) -> None:
        """Disconnect a specific peer by ID, nickname, or address."""
        resolved = self.resolve_peer_address(target) or target
        await self.active_transport.disconnect_peer(resolved)
