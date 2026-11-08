"""Bluetooth Low Energy transport adapter implementing BaseTransport."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from bitchat.ble.models import BLEState
from bitchat.exceptions import FragmentationError, PacketDecodingError
from bitchat.logging import log_transport_diagnostic
from bitchat.platform.detection import PlatformKind, detect_platform
from bitchat.protocol.constants import MessageType
from bitchat.protocol.decoder import decode_packet
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.fragmentation import fragment_encoded_packet, should_fragment
from bitchat.protocol.reassembly import FragmentReassembler
from bitchat.transport.base import (
    BaseTransport,
    TransportState,
    TransportType,
    format_connection_failure,
)

if TYPE_CHECKING:
    from bitchat.ble.adapter import AdapterInfo
    from bitchat.ble.manager import BLEManager
    from bitchat.ble.server import BLEServer
    from bitchat.protocol.packet import BitchatPacket

logger = logging.getLogger(__name__)

_BLE_STATE_MAP: dict[BLEState, TransportState] = {
    BLEState.OFFLINE: TransportState.OFFLINE,
    BLEState.CHECKING: TransportState.CHECKING,
    BLEState.READY: TransportState.READY,
    BLEState.SCANNING: TransportState.SCANNING,
    BLEState.PEER_FOUND: TransportState.PEER_FOUND,
    BLEState.CONNECTING: TransportState.CONNECTING,
    BLEState.CONNECTED: TransportState.CONNECTED,
    BLEState.ERROR: TransportState.ERROR,
    BLEState.BLUETOOTH_UNAVAILABLE: TransportState.UNAVAILABLE,
    BLEState.BLUETOOTH_DISABLED: TransportState.DISABLED,
}


class BluetoothTransport(BaseTransport):
    """Bridges existing BLEManager and BLEServer to the common
    BaseTransport interface.
    """

    def __init__(
        self,
        ble_manager: BLEManager,
        ble_server: BLEServer,
        inter_fragment_delay: float = 0.02,
    ) -> None:
        super().__init__()
        self.ble_manager = ble_manager
        self.ble_server = ble_server
        self.inter_fragment_delay = inter_fragment_delay
        self._is_running: bool = False
        self._state: TransportState = TransportState.OFFLINE
        self._error_message: str | None = None
        self._peripheral_error_message: str | None = None
        self._failed_stage: str | None = None
        self._error_code: int | None = None
        self._hresult: str | None = None
        self._error_source: str | None = None
        self._central_supported: bool = False
        self._peripheral_supported: bool = False
        self._advertisement_offload_supported: bool = False
        if self._uses_injected_test_backend():
            self._central_supported = True
            self._peripheral_supported = True
        elif self.ble_manager is not None and hasattr(
            self.ble_manager, "adapter_manager"
        ):
            mgr = self.ble_manager.adapter_manager
            adapter_info = getattr(mgr, "current_info", None)
            if adapter_info is not None:
                self._central_supported = bool(adapter_info.is_central_supported)
                self._peripheral_supported = bool(adapter_info.is_peripheral_supported)
                self._advertisement_offload_supported = bool(
                    adapter_info.is_advertisement_offload_supported
                )
        self._start_lock = asyncio.Lock()
        self._halt_task: asyncio.Task[Any] | None = None

        self.server_reassembler = FragmentReassembler()
        self._server_clients: set[str] = set()
        self.offline_mode: bool = False

        # Wire up internal callbacks
        if self.ble_manager is not None:
            self.ble_manager.on_packet_received = self._handle_manager_packet
            self.ble_manager.on_peer_discovered = self._handle_peer_discovered
            self.ble_manager.on_peer_connected = self._handle_peer_connected
            self.ble_manager.on_peer_disconnected = self._handle_peer_disconnected
            self.ble_manager.on_adapter_state_changed = (
                self._handle_adapter_state_changed
            )

        if self.ble_server is not None:
            self.ble_server.on_data_received = self._handle_server_data
            self.ble_server.on_client_subscribed = self._handle_server_client_subscribed
            self.ble_server.on_client_unsubscribed = (
                self._handle_server_client_unsubscribed
            )

    def set_offline(self, offline: bool) -> None:
        """Enforce strict offline mode invariant."""
        self.offline_mode = offline
        if offline:
            self._is_running = False
            self._set_state(TransportState.OFFLINE)

    @property
    def transport_type(self) -> TransportType:
        return TransportType.BLUETOOTH

    @property
    def state(self) -> TransportState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def connected_peers(self) -> list[str]:
        return self.ble_manager.connected_peers if self.ble_manager else []

    @property
    def discovered_peers(self) -> dict[str, Any]:
        return self.ble_manager.discovered_peers if self.ble_manager else {}

    @property
    def is_scanning(self) -> bool:
        if not self.ble_manager:
            return False
        return bool(self.ble_manager.scanner.is_scanning)

    def is_available(self) -> bool:
        """Return True if Bluetooth hardware is available on the system."""
        if not self.ble_manager or not self.ble_server:
            return False
        adapter = self.ble_manager.adapter_manager.current_info
        if adapter.is_available:
            return True
        if self._uses_injected_test_backend():
            if (
                getattr(self.ble_manager.adapter_manager, "_custom_backend", None)
                is not None
            ):
                return adapter.is_available
            return True
        return False

    def _set_state(self, new_state: TransportState) -> None:
        if self._state != new_state:
            self._state = new_state
            if self.on_state_changed:
                with contextlib.suppress(Exception):
                    self.on_state_changed(new_state)

    def _handle_manager_packet(self, packet: BitchatPacket, peer_address: str) -> None:
        if self.on_packet_received:
            self.on_packet_received(packet, peer_address)

    def _handle_server_client_subscribed(self, client_id: str) -> None:
        if client_id:
            self._server_clients.add(client_id)

    def _handle_server_client_unsubscribed(self, client_id: str) -> None:
        self._server_clients.discard(client_id)

    def _handle_server_data(self, data: bytes, client_address: str = "") -> None:
        if client_address:
            self._server_clients.add(client_address)

        try:
            packet = decode_packet(data)
        except PacketDecodingError as e:
            logger.warning(
                "Discarding malformed packet from server client %s: %s",
                client_address,
                e,
            )
            return

        if packet.message_type in (
            MessageType.FragmentStart,
            MessageType.FragmentContinue,
            MessageType.FragmentEnd,
        ):
            try:
                reassembled_wire = self.server_reassembler.add_fragment_packet(packet)
            except (FragmentationError, PacketDecodingError) as e:
                logger.warning(
                    "Error reassembling fragment from server client %s: %s",
                    client_address,
                    e,
                )
                return

            if reassembled_wire is not None:
                try:
                    full_packet = decode_packet(reassembled_wire)
                    if self.on_packet_received:
                        self.on_packet_received(full_packet, client_address)
                except PacketDecodingError as e:
                    logger.warning(
                        "Failed to decode reassembled packet from server client %s: %s",
                        client_address,
                        e,
                    )
        else:
            if self.on_packet_received:
                self.on_packet_received(packet, client_address)

    def _handle_peer_discovered(self, peer: Any) -> None:
        if self._state == TransportState.SCANNING:
            self._set_state(TransportState.PEER_FOUND)
        if self.on_peer_discovered:
            self.on_peer_discovered(peer)

    def _handle_peer_connected(self, address: str) -> None:
        self._set_state(TransportState.CONNECTED)
        if self.on_peer_connected:
            self.on_peer_connected(address)

    def _handle_peer_disconnected(self, address: str) -> None:
        if not self.ble_manager.connected_peers:
            self._set_state(
                TransportState.SCANNING
                if self.ble_manager.scanner.is_scanning
                else TransportState.READY
            )
        if self.on_peer_disconnected:
            self.on_peer_disconnected(address)

    def _handle_adapter_state_changed(self, info: AdapterInfo) -> None:
        if self.offline_mode:
            return
        if not info.is_enabled:
            st = (
                TransportState.DISABLED
                if info.radio_state in ("off", "disabled")
                else TransportState.UNAVAILABLE
            )
            self._set_state(st)
            if info.radio_state in ("off", "disabled"):
                self._error_message = "Bluetooth disabled"
            else:
                self._error_message = "Bluetooth unavailable"
            self._is_running = False
            self.report_error("adapter_state_change", self._error_message)
            self._schedule_halt()
        # Radio returning to on does not claim READY until retry restarts workers.

    def _schedule_halt(self) -> None:
        """Stop BLE workers after adapter loss without composing UI widgets."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._halt_task is not None and not self._halt_task.done():
            return
        self._halt_task = loop.create_task(self._halt_ble_workers())

    async def _halt_ble_workers(self) -> None:
        """Stop scanner, server, and peer links after Bluetooth failure."""
        with contextlib.suppress(Exception):
            await self.ble_manager.scanner.stop()
        if hasattr(self.ble_manager.scanner, "clear"):
            self.ble_manager.scanner.clear()
        transports = list(getattr(self.ble_manager, "_transports", {}).items())
        self.ble_manager._transports.clear()
        for addr, transport in transports:
            with contextlib.suppress(Exception):
                await transport.stop()
            if self.on_peer_disconnected:
                with contextlib.suppress(Exception):
                    self.on_peer_disconnected(addr)
        with contextlib.suppress(Exception):
            await self.ble_server.stop()

    def _uses_injected_test_backend(self) -> bool:
        """True only when tests explicitly inject BLE backends. Never auto-selected."""
        server_injected = getattr(self.ble_server, "_custom_backend", None) is not None
        adapter_mgr = getattr(self.ble_manager, "adapter_manager", None)
        adapter_injected = (
            getattr(adapter_mgr, "_custom_backend", None) is not None
            if adapter_mgr is not None
            else False
        )
        return server_injected or adapter_injected

    def _skip_host_adapter_probe(self) -> bool:
        """Keep legacy server-only test doubles independent from host hardware."""
        server_injected = getattr(self.ble_server, "_custom_backend", None) is not None
        adapter_mgr = getattr(self.ble_manager, "adapter_manager", None)
        adapter_injected = (
            getattr(adapter_mgr, "_custom_backend", None) is not None
            if adapter_mgr is not None
            else False
        )
        return server_injected and not adapter_injected

    async def start(self) -> None:
        """Start only the BLE roles supported by the current adapter."""
        async with self._start_lock:
            if self.offline_mode:
                raise RuntimeError(
                    "Cannot start Bluetooth transport: offline mode is active"
                )
            if self._is_running:
                return

            self._is_running = True
            self._set_state(TransportState.CHECKING)
            self._error_message = None
            self._peripheral_error_message = None
            self._failed_stage = None
            self._error_code = None
            self._hresult = None
            self._error_source = None
            adapter_info: AdapterInfo | None = None
            peripheral_start_error: BaseException | None = None

            log_transport_diagnostic(
                operation="ble_transport_start",
                stage="init",
                result="STARTING",
                requested_transport="bluetooth",
                details="Starting BLE transport initialization",
            )

            try:
                if not self._skip_host_adapter_probe():
                    log_transport_diagnostic(
                        operation="ble_transport_start",
                        stage="adapter_check",
                        result="STARTING",
                        requested_transport="bluetooth",
                        details="Probing Bluetooth host adapter",
                    )
                    adapter_info = (
                        await self.ble_manager.adapter_manager.check_adapter()
                    )
                    if not adapter_info.is_available:
                        self._set_state(TransportState.UNAVAILABLE)
                        self._error_message = "Bluetooth unavailable"
                        self._failed_stage = "adapter_check"
                        self._error_source = "adapter_manager"
                        log_transport_diagnostic(
                            operation="ble_transport_start",
                            stage="adapter_check",
                            result="FAILED",
                            requested_transport="bluetooth",
                            source="adapter_manager",
                            details=self._error_message,
                        )
                        self.report_error("adapter_check", self._error_message)
                        raise RuntimeError(self._error_message)

                    if not adapter_info.is_enabled:
                        self._set_state(TransportState.DISABLED)
                        self._error_message = "Bluetooth disabled"
                        self._failed_stage = "adapter_check"
                        self._error_source = "adapter_manager"
                        log_transport_diagnostic(
                            operation="ble_transport_start",
                            stage="adapter_check",
                            result="DISABLED",
                            requested_transport="bluetooth",
                            source="adapter_manager",
                            details=self._error_message,
                        )
                        self.report_error("adapter_check", self._error_message)
                        raise RuntimeError(self._error_message)

                    await self.ble_manager.adapter_manager.start_monitoring(
                        self._handle_adapter_state_changed,
                        refresh=False,
                    )

                self._central_supported = (
                    adapter_info.is_central_supported
                    if adapter_info is not None
                    else True
                )
                self._peripheral_supported = (
                    adapter_info.is_peripheral_supported
                    if adapter_info is not None
                    else True
                )
                backend_hosts_peripheral = bool(
                    getattr(self.ble_server, "supports_peripheral", True)
                )
                platform_limits_peripheral = (
                    self._peripheral_supported and not backend_hosts_peripheral
                )
                if platform_limits_peripheral:
                    # The adapter hardware can advertise but BitChat has no GATT
                    # server for this platform's backend. This is an expected
                    # limitation, not a startup failure: report central-only
                    # truthfully without raising a recovery warning.
                    self._peripheral_supported = False
                    logger.info(
                        "BLE peripheral role is not implemented for this "
                        "platform backend; running central-only"
                    )
                self._advertisement_offload_supported = (
                    adapter_info.is_advertisement_offload_supported
                    if adapter_info is not None
                    else False
                )

                if not self._central_supported and not self._peripheral_supported:
                    self._set_state(TransportState.ERROR)
                    self._error_message = (
                        "Bluetooth adapter supports neither BLE central nor "
                        "peripheral operation"
                    )
                    self._failed_stage = "capabilities_check"
                    self._error_source = "adapter_capabilities"
                    log_transport_diagnostic(
                        operation="ble_transport_start",
                        stage="capabilities_check",
                        result="FAILED",
                        requested_transport="bluetooth",
                        source="adapter_capabilities",
                        details=self._error_message,
                    )
                    self.report_error("capabilities_check", self._error_message)
                    raise RuntimeError(self._error_message)

                if self._peripheral_supported:
                    log_transport_diagnostic(
                        operation="ble_transport_start",
                        stage="peripheral_start",
                        result="STARTING",
                        requested_transport="bluetooth",
                        details="Starting BLE peripheral GATT server",
                    )
                    try:
                        await self.ble_server.start()
                    except Exception as e:
                        peripheral_start_error = e
                        self._peripheral_error_message = (
                            f"BLE peripheral advertising failed: {e}"
                        )
                        self._error_message = self._peripheral_error_message
                        server_telem = (
                            self.ble_server.get_telemetry()
                            if hasattr(self.ble_server, "get_telemetry")
                            else {}
                        )
                        self._failed_stage = (
                            server_telem.get("failed_stage") or "peripheral_start"
                        )
                        self._error_code = server_telem.get("error_code")
                        self._hresult = server_telem.get("hresult")
                        self._error_source = (
                            server_telem.get("error_source") or type(e).__name__
                        )
                        log_transport_diagnostic(
                            operation="ble_transport_start",
                            stage="peripheral_start",
                            result="FAILED",
                            requested_transport="bluetooth",
                            error_code=self._error_code,
                            hresult=self._hresult,
                            source=self._error_source,
                            cleanup_result="windows_resources_released",
                            details=self._peripheral_error_message,
                        )
                        logger.warning("%s", self._peripheral_error_message)
                    else:
                        if not self.ble_server.is_advertising:
                            server_telem = (
                                self.ble_server.get_telemetry()
                                if hasattr(self.ble_server, "get_telemetry")
                                else {}
                            )
                            server_err = server_telem.get("last_error")
                            if isinstance(server_err, str) and server_err:
                                self._peripheral_error_message = (
                                    f"BLE peripheral advertising failed: {server_err}"
                                )
                                self._error_message = self._peripheral_error_message
                                self._failed_stage = (
                                    server_telem.get("failed_stage")
                                    or "advertising_start"
                                )
                                self._error_code = server_telem.get("error_code")
                                self._hresult = server_telem.get("hresult")
                                self._error_source = (
                                    server_telem.get("error_source") or "ble_server"
                                )
                                log_transport_diagnostic(
                                    operation="ble_transport_start",
                                    stage="peripheral_start",
                                    result="ABORTED",
                                    requested_transport="bluetooth",
                                    error_code=self._error_code,
                                    hresult=self._hresult,
                                    source=self._error_source,
                                    cleanup_result="windows_resources_released",
                                    details=self._peripheral_error_message,
                                )
                                logger.warning("%s", self._peripheral_error_message)
                        else:
                            log_transport_diagnostic(
                                operation="ble_transport_start",
                                stage="peripheral_start",
                                result="SUCCESS",
                                requested_transport="bluetooth",
                                details="GATT server advertising active",
                            )
                elif not platform_limits_peripheral:
                    logger.info("BLE peripheral role is not supported by the adapter")

                if self._central_supported:
                    log_transport_diagnostic(
                        operation="ble_transport_start",
                        stage="central_scan_start",
                        result="STARTING",
                        requested_transport="bluetooth",
                        details="Starting BLE central scanner discovery",
                    )
                    try:
                        await self.ble_manager.start_discovery()
                        self._set_state(TransportState.SCANNING)
                        log_transport_diagnostic(
                            operation="ble_transport_start",
                            stage="central_scan_start",
                            result="SUCCESS",
                            requested_transport="bluetooth",
                            details="BLE central scanner active",
                        )
                    except Exception as e:
                        logger.warning("Could not start BLE discovery: %s", e)
                        scan_error = f"Bluetooth scan failed: {e}"
                        self._failed_stage = "central_scan_start"
                        self._error_source = "ble_manager.start_discovery"
                        if self.ble_server.is_advertising:
                            await self.ble_server.stop()
                        self._set_state(TransportState.ERROR)
                        self._error_message = scan_error
                        log_transport_diagnostic(
                            operation="ble_transport_start",
                            stage="central_scan_start",
                            result="FAILED",
                            requested_transport="bluetooth",
                            source="ble_manager.start_discovery",
                            cleanup_result="ble_server_stopped",
                            details=scan_error,
                        )
                        self.report_error("central_scan_start", self._error_message)
                        raise RuntimeError(self._error_message) from e

                if not self.ble_manager.scanner.is_scanning and (
                    not self.ble_server.is_advertising
                ):
                    self._set_state(TransportState.ERROR)
                    self._error_message = (
                        self._peripheral_error_message
                        or "No supported BLE role could be started"
                    )
                    self.report_error("role_start", self._error_message)
                    raise RuntimeError(self._error_message)

                if self._peripheral_error_message:
                    self.report_warning(
                        "peripheral_start",
                        self._peripheral_error_message,
                        stage=self._failed_stage or "peripheral_start",
                        original_error=peripheral_start_error,
                        native_error_code=self._error_code,
                        hresult=self._hresult,
                    )

                if not self._central_supported:
                    self._set_state(TransportState.READY)

                log_transport_diagnostic(
                    operation="ble_transport_start",
                    stage="start_complete",
                    result="SUCCESS",
                    requested_transport="bluetooth",
                    active_transport="bluetooth",
                    details=f"Transport state: {self._state.value}",
                )
            except BaseException:
                self._is_running = False
                if self.ble_manager is not None:
                    with contextlib.suppress(Exception):
                        await self.ble_manager.adapter_manager.stop_monitoring()
                    with contextlib.suppress(Exception):
                        await self.ble_manager.scanner.stop()
                if self.ble_server is not None:
                    with contextlib.suppress(Exception):
                        await self.ble_server.stop()
                raise

    async def stop(self) -> None:
        """Stop BLE server, discovery scanner, and disconnect all peers."""
        async with self._start_lock:
            self._is_running = False
            if self._halt_task is not None and not self._halt_task.done():
                self._halt_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._halt_task
            self._halt_task = None
            self._set_state(TransportState.OFFLINE)
            self._error_message = None

            with contextlib.suppress(Exception):
                await self.ble_manager.shutdown()
            with contextlib.suppress(Exception):
                await self.ble_server.stop()
            self.server_reassembler.clear()
            self._server_clients.clear()

    async def start_discovery(self) -> None:
        if self.offline_mode:
            raise RuntimeError("Cannot start BLE discovery: offline mode is active")
        if not self._central_supported:
            raise RuntimeError(
                "BLE discovery is unavailable because the adapter does not "
                "support the central role"
            )
        await self.ble_manager.start_discovery()
        self._set_state(TransportState.SCANNING)

    async def stop_discovery(self) -> None:
        await self.ble_manager.stop_discovery()
        if self._state in (TransportState.SCANNING, TransportState.PEER_FOUND):
            self._set_state(TransportState.READY)

    async def connect_peer(self, address: str, timeout: float = 10.0) -> Any:
        if self.offline_mode or self._state in (
            TransportState.UNAVAILABLE,
            TransportState.DISABLED,
            TransportState.OFFLINE,
            TransportState.ERROR,
        ):
            raise RuntimeError("Connection failed: transport unavailable")
        self._set_state(TransportState.CONNECTING)
        try:
            transport = await self.ble_manager.connect_peer(address, timeout=timeout)
            self._set_state(TransportState.CONNECTED)
            return transport
        except Exception as e:
            self._set_state(
                TransportState.SCANNING
                if self.ble_manager.scanner.is_scanning
                else TransportState.READY
            )
            raise RuntimeError(format_connection_failure(e)) from e

    async def disconnect_peer(self, address: str) -> None:
        await self.ble_manager.disconnect_peer(address)

    def _is_server_client(self, address: str) -> bool:
        if address in self._server_clients:
            return True
        if self.ble_server is not None:
            custom_backend = getattr(self.ble_server, "_custom_backend", None)
            if custom_backend is not None and hasattr(custom_backend, "clients"):
                for client in custom_backend.clients:
                    if getattr(client, "address", None) == address:
                        return True
            server_clients = getattr(self.ble_server, "connected_clients", None)
            if server_clients and address in server_clients:
                return True
        return False

    async def _send_server_notification(self, data: bytes, client_id: str) -> None:
        if not self.ble_server:
            return
        try:
            await self.ble_server.send_notification(data, client_id=client_id)
        except TypeError:
            send_fn: Any = self.ble_server.send_notification
            try:
                await send_fn(client_id, data)
            except TypeError:
                await self.ble_server.send_notification(data)

    async def send_to_peer(self, address: str, packet: BitchatPacket) -> None:
        if self.offline_mode:
            raise RuntimeError("Cannot transmit packet: offline mode is active")
        if (
            self._is_server_client(address)
            and self.ble_server
            and self.ble_server.is_advertising
        ):
            encoded = encode_packet(packet, add_padding=True)
            if should_fragment(encoded):
                fragments = fragment_encoded_packet(
                    encoded,
                    sender_id=packet.sender_id,
                    original_message_type=packet.message_type,
                )
                for i, frag in enumerate(fragments):
                    frag_bytes = encode_packet(frag, add_padding=False)
                    await self._send_server_notification(frag_bytes, address)
                    if i < len(fragments) - 1:
                        await asyncio.sleep(self.inter_fragment_delay)
            else:
                await self._send_server_notification(encoded, address)
            return

        if self.ble_manager:
            await self.ble_manager.send_to_peer(address, packet)

    async def broadcast_packet(
        self, packet: BitchatPacket, exclude_address: str | None = None
    ) -> None:
        if self.offline_mode:
            return
        if self.ble_manager and self.ble_manager.connected_peers:
            await self.ble_manager.broadcast_packet(
                packet, exclude_address=exclude_address
            )

        if self.ble_server and self.ble_server.is_advertising:
            encoded = encode_packet(packet, add_padding=True)
            if should_fragment(encoded):
                fragments = fragment_encoded_packet(
                    encoded,
                    sender_id=packet.sender_id,
                    original_message_type=packet.message_type,
                )
                for i, frag in enumerate(fragments):
                    frag_bytes = encode_packet(frag, add_padding=False)
                    await self.ble_server.send_notification(frag_bytes)
                    if i < len(fragments) - 1:
                        await asyncio.sleep(self.inter_fragment_delay)
            else:
                await self.ble_server.send_notification(encoded)

    def update_identity(self, peer_id_hex: str, nickname: str) -> None:
        if self.ble_server:
            self.ble_server.update_identity(peer_id_hex, nickname)
        if self.ble_manager:
            self.ble_manager.update_sender_id(bytes.fromhex(peer_id_hex))

    def resolve_peer_id_to_address(self, target: str) -> str | None:
        if self.ble_manager:
            return self.ble_manager.resolve_peer_id_to_address(target)
        return None

    def get_telemetry(self) -> dict[str, Any]:
        if not self.ble_manager or not self.ble_server:
            return {
                "transport": "bluetooth",
                "state": self._state.value,
                "adapter_available": False,
                "adapter_state": "Unavailable",
                "adapter_initialization": "Not checked",
                "central_supported": self._central_supported,
                "peripheral_supported": self._peripheral_supported,
                "advertisement_offload_supported": (
                    self._advertisement_offload_supported
                ),
                "advertising_active": False,
                "peripheral_error": self._peripheral_error_message,
                "gatt_server_status": "Stopped",
                "scanner_status": "Stopped",
                "discovered_peers_count": 0,
                "connected_peers_count": 0,
                "connected_peers": [],
                "discovered_peers": {},
                "error_message": self._error_message,
            }

        adapter = self.ble_manager.adapter_manager.current_info
        adapter_checked = bool(
            adapter.name or adapter.device_id or adapter.radio_state != "unavailable"
        )
        server_telem = self.ble_server.get_telemetry()
        platform = detect_platform()
        backend_name = {
            PlatformKind.WINDOWS: "Windows WinRT GATT",
            PlatformKind.LINUX: "Linux BlueZ (D-Bus)",
            PlatformKind.OTHER: "Bleak central only",
        }[platform]
        if self.ble_server._custom_backend is not None:
            backend_name = type(self.ble_server._custom_backend).__name__
        return {
            "transport": "bluetooth",
            "state": self._state.value,
            "adapter_available": adapter.is_available,
            "adapter_name": adapter.name or "Unknown",
            "adapter_id": adapter.device_id or "Unavailable",
            "adapter_initialization": (
                "Initialized"
                if adapter.is_available
                else "Unavailable"
                if adapter_checked
                else "Not checked"
            ),
            "backend_name": backend_name,
            "platform": platform.value,
            "permission_status": "Not exposed by this platform backend",
            "adapter_state": "On"
            if adapter.is_enabled
            else (
                "Off"
                if adapter.radio_state in ("off", "disabled")
                else "Unavailable"
                if adapter_checked
                else "Not checked"
            ),
            "radio_state": adapter.radio_state,
            "central_supported": self._central_supported,
            "peripheral_supported": self._peripheral_supported,
            "advertisement_offload_supported": (self._advertisement_offload_supported),
            "advertising_active": self.ble_server.is_advertising,
            "peripheral_error": self._peripheral_error_message,
            "gatt_server_status": self._gatt_server_status(server_telem),
            "scanner_status": "Active"
            if self.ble_manager.scanner.is_scanning
            else "Stopped",
            "scan_started_at": self.ble_manager.scanner.scan_started_at,
            "scan_duration_seconds": self.ble_manager.scanner.scan_duration_seconds,
            "last_successful_scan_at": self.ble_manager.scanner.last_successful_scan_at,
            "gatt": server_telem,
            "discovered_peers_count": len(self.discovered_peers),
            "connected_peers_count": len(self.connected_peers),
            "connected_peers": self.connected_peers,
            "discovered_peers": self.discovered_peers,
            "error_message": self._error_message,
            "failed_stage": self._failed_stage or server_telem.get("failed_stage"),
            "error_code": self._error_code
            if self._error_code is not None
            else server_telem.get("error_code"),
            "hresult": self._hresult or server_telem.get("hresult"),
            "error_source": self._error_source or server_telem.get("error_source"),
        }

    def _gatt_server_status(self, telemetry: dict[str, Any]) -> str:
        if telemetry.get("is_advertising"):
            return "Advertising"
        if not self._peripheral_supported:
            return "Unsupported"
        if self._peripheral_error_message:
            return "Failed"
        return "Stopped"
