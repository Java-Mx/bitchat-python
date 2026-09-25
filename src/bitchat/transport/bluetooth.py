"""Bluetooth Low Energy transport adapter implementing BaseTransport."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from bitchat.ble.models import BLEState
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.fragmentation import fragment_encoded_packet, should_fragment
from bitchat.transport.base import (
    BaseTransport,
    TransportState,
    TransportType,
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

    def _set_state(self, new_state: TransportState) -> None:
        if self._state != new_state:
            self._state = new_state
            if self.on_state_changed:
                with contextlib.suppress(Exception):
                    self.on_state_changed(new_state)

    def _handle_manager_packet(self, packet: BitchatPacket, peer_address: str) -> None:
        if self.on_packet_received:
            self.on_packet_received(packet, peer_address)

    def _handle_server_data(self, data: bytes, client_address: str = "") -> None:
        # Pass server received data to listener if handled externally or reassembled
        pass

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
        if not info.is_enabled:
            st = (
                TransportState.DISABLED
                if info.radio_state in ("off", "disabled")
                else TransportState.UNAVAILABLE
            )
            self._set_state(st)
            self._error_message = f"Bluetooth adapter is {info.radio_state}."
            if self.on_error:
                self.on_error(self._error_message)
        else:
            if self._state in (TransportState.DISABLED, TransportState.UNAVAILABLE):
                self._set_state(TransportState.READY)

    async def start(self) -> None:
        """Start adapter checks, GATT server, and BLE scanner."""
        if self._is_running:
            return

        self._is_running = True
        self._set_state(TransportState.CHECKING)
        self._error_message = None

        try:
            is_mock = getattr(self.ble_server, "_custom_backend", None) is not None
            if not is_mock:
                adapter_info = await self.ble_manager.adapter_manager.check_adapter()
                if not adapter_info.is_available:
                    self._set_state(TransportState.UNAVAILABLE)
                    self._error_message = "Bluetooth hardware adapter is not detected."
                    if self.on_error:
                        self.on_error(self._error_message)
                    raise RuntimeError(self._error_message)

                if not adapter_info.is_enabled:
                    self._set_state(TransportState.DISABLED)
                    self._error_message = (
                        "Bluetooth radio is turned off. "
                        "Please enable Bluetooth in system settings."
                    )
                    if self.on_error:
                        self.on_error(self._error_message)
                    await self.ble_manager.adapter_manager.start_monitoring(
                        self._handle_adapter_state_changed
                    )
                    raise RuntimeError(self._error_message)

                await self.ble_manager.adapter_manager.start_monitoring(
                    self._handle_adapter_state_changed
                )

            try:
                await self.ble_server.start()
            except Exception as e:
                logger.warning("Could not start BLE server: %s", e)
                self._set_state(TransportState.UNAVAILABLE)
                self._error_message = f"GATT server failed: {e}"
                if self.on_error:
                    self.on_error(self._error_message)
                raise RuntimeError(self._error_message) from e

            try:
                await self.ble_manager.start_discovery()
                self._set_state(TransportState.SCANNING)
            except Exception as e:
                logger.warning("Could not start BLE discovery: %s", e)
                self._set_state(TransportState.UNAVAILABLE)
                self._error_message = f"Bluetooth scan failed: {e}"
                if self.on_error:
                    self.on_error(self._error_message)
                raise RuntimeError(self._error_message) from e
        except Exception:
            self._is_running = False
            raise

    async def stop(self) -> None:
        """Stop BLE server, discovery scanner, and disconnect all peers."""
        if not self._is_running:
            return

        self._is_running = False
        self._set_state(TransportState.OFFLINE)
        self._error_message = None

        with contextlib.suppress(Exception):
            await self.ble_manager.shutdown()
        with contextlib.suppress(Exception):
            await self.ble_server.stop()

    async def start_discovery(self) -> None:
        await self.ble_manager.start_discovery()
        self._set_state(TransportState.SCANNING)

    async def stop_discovery(self) -> None:
        await self.ble_manager.stop_discovery()
        if self._state in (TransportState.SCANNING, TransportState.PEER_FOUND):
            self._set_state(TransportState.READY)

    async def connect_peer(self, address: str, timeout: float = 10.0) -> Any:
        self._set_state(TransportState.CONNECTING)
        try:
            transport = await self.ble_manager.connect_peer(address, timeout=timeout)
            self._set_state(TransportState.CONNECTED)
            return transport
        except Exception:
            self._set_state(
                TransportState.SCANNING
                if self.ble_manager.scanner.is_scanning
                else TransportState.READY
            )
            raise

    async def disconnect_peer(self, address: str) -> None:
        await self.ble_manager.disconnect_peer(address)

    async def send_to_peer(self, address: str, packet: BitchatPacket) -> None:
        if self.ble_manager:
            await self.ble_manager.send_to_peer(address, packet)

    async def broadcast_packet(
        self, packet: BitchatPacket, exclude_address: str | None = None
    ) -> None:
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
                    frag_bytes = encode_packet(frag, add_padding=True)
                    await self.ble_server.send_notification(frag_bytes)
                    if i < len(fragments) - 1:
                        await asyncio.sleep(self.inter_fragment_delay)
            else:
                await self.ble_server.send_notification(encoded)

    def update_identity(self, peer_id_hex: str, nickname: str) -> None:
        if self.ble_server:
            self.ble_server.update_identity(peer_id_hex, nickname)

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
                "gatt_server_status": "Stopped",
                "scanner_status": "Stopped",
                "discovered_peers_count": 0,
                "connected_peers_count": 0,
                "connected_peers": [],
                "discovered_peers": {},
                "error_message": self._error_message,
            }

        adapter = self.ble_manager.adapter_manager.current_info
        server_telem = self.ble_server.get_telemetry()
        return {
            "transport": "bluetooth",
            "state": self._state.value,
            "adapter_available": adapter.is_available,
            "adapter_state": "On"
            if adapter.is_enabled
            else (
                "Off" if adapter.radio_state in ("off", "disabled") else "Unavailable"
            ),
            "radio_state": adapter.radio_state,
            "gatt_server_status": "Advertising"
            if server_telem.get("is_advertising")
            else "Stopped",
            "scanner_status": "Active"
            if self.ble_manager.scanner.is_scanning
            else "Stopped",
            "discovered_peers_count": len(self.discovered_peers),
            "connected_peers_count": len(self.connected_peers),
            "connected_peers": self.connected_peers,
            "discovered_peers": self.discovered_peers,
            "error_message": self._error_message,
        }
