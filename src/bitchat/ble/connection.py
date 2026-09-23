"""BLE connection lifecycle management."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from bleak import BleakClient

from bitchat.ble.gatt import GATTManager
from bitchat.ble.models import BLEConnectionState
from bitchat.exceptions import BLEConnectionError, BLEGATTError

if TYPE_CHECKING:
    from collections.abc import Callable

    from bleak.backends.characteristic import BleakGATTCharacteristic

logger = logging.getLogger(__name__)


class BLEConnection:
    """Manages connection lifecycle, GATT discovery, and notifications."""

    def __init__(
        self,
        peer_address: str,
        notification_callback: Callable[[bytes], None] | None = None,
        disconnected_callback: Callable[[str], None] | None = None,
        gatt_manager: GATTManager | None = None,
        client_factory: Callable[..., Any] | None = None,
        connect_timeout: float = 10.0,
    ) -> None:
        self.peer_address = peer_address
        self.notification_callback = notification_callback
        self.disconnected_callback = disconnected_callback
        self.gatt_manager = gatt_manager or GATTManager()
        self.connect_timeout = connect_timeout
        self._client_factory = client_factory or BleakClient

        self._state = BLEConnectionState.DISCONNECTED
        self._client: Any | None = None
        self._characteristic: BleakGATTCharacteristic | None = None
        self._is_subscribed: bool = False
        self._lock = asyncio.Lock()

    @property
    def state(self) -> BLEConnectionState:
        """Return the current connection lifecycle state."""
        return self._state

    @property
    def is_connected(self) -> bool:
        """Return True if the underlying client is connected."""
        return self._client is not None and bool(
            getattr(self._client, "is_connected", False)
        )

    @property
    def is_ready(self) -> bool:
        """Return True if connection is established and GATT is ready."""
        return self._state == BLEConnectionState.READY and self.is_connected

    def _on_disconnected(self, _client: Any) -> None:
        """Handle disconnection event triggered by Bleak."""
        logger.info("BLE peer disconnected: %s", self.peer_address)
        self._state = BLEConnectionState.DISCONNECTED
        self._characteristic = None
        self._is_subscribed = False

        if self.disconnected_callback:
            try:
                self.disconnected_callback(self.peer_address)
            except Exception as e:
                logger.warning("Error in disconnected_callback: %s", e)

    def _raw_notification_handler(
        self, _char: BleakGATTCharacteristic, data: bytearray | bytes
    ) -> None:
        """Process incoming raw notification data from the characteristic."""
        if self._state != BLEConnectionState.READY:
            logger.debug(
                "Ignored notification received while in state %s from %s",
                self._state,
                self.peer_address,
            )
            return

        raw_bytes = bytes(data)
        if self.notification_callback:
            try:
                self.notification_callback(raw_bytes)
            except Exception as e:
                logger.error(
                    "Unhandled exception in notification callback for %s: %s",
                    self.peer_address,
                    e,
                    exc_info=True,
                )

    async def connect(self) -> None:
        """Establish BLE connection, discover BitChat GATT, and subscribe."""
        async with self._lock:
            if self._state == BLEConnectionState.READY:
                return
            if self._state not in (
                BLEConnectionState.DISCONNECTED,
                BLEConnectionState.DISCONNECTING,
            ):
                raise BLEConnectionError(
                    f"Cannot connect to {self.peer_address}: "
                    f"already in state {self._state}"
                )

            self._state = BLEConnectionState.CONNECTING
            logger.info("Connecting to BLE peer: %s", self.peer_address)

            try:
                client = self._client_factory(
                    self.peer_address,
                    disconnected_callback=self._on_disconnected,
                )
                self._client = client
                connected = await client.connect(timeout=self.connect_timeout)
                if not connected:
                    raise BLEConnectionError(
                        f"Failed to connect to BLE peer: {self.peer_address}"
                    )

                self._state = BLEConnectionState.CONNECTED
                logger.info("Connected to %s; discovering GATT", self.peer_address)

                self._state = BLEConnectionState.DISCOVERING_GATT
                characteristic = await self.gatt_manager.discover(client)
                self._characteristic = characteristic

                self._state = BLEConnectionState.SUBSCRIBING
                logger.info("Subscribing to notifications on %s", self.peer_address)
                await client.start_notify(
                    characteristic, self._raw_notification_handler
                )
                self._is_subscribed = True

                self._state = BLEConnectionState.READY
                logger.info("BLE peer %s is ready for communication", self.peer_address)

            except Exception as e:
                logger.warning(
                    "Failed to establish connection to %s: %s",
                    self.peer_address,
                    e,
                )
                await self._cleanup()
                if isinstance(e, (BLEConnectionError, BLEGATTError)):
                    raise
                raise BLEConnectionError(
                    f"Connection failed for {self.peer_address}: {e}"
                ) from e

    async def _cleanup(self) -> None:
        """Internal cleanup on error or disconnect."""
        self._state = BLEConnectionState.DISCONNECTING
        if self._client is not None:
            if self._is_subscribed and self._characteristic is not None:
                try:
                    await self._client.stop_notify(self._characteristic)
                except Exception as e:
                    logger.debug("Error stopping notify during cleanup: %s", e)
                finally:
                    self._is_subscribed = False

            if getattr(self._client, "is_connected", False):
                try:
                    await self._client.disconnect()
                except Exception as e:
                    logger.debug("Error disconnecting client during cleanup: %s", e)

        self._client = None
        self._characteristic = None
        self._state = BLEConnectionState.DISCONNECTED

    async def disconnect(self) -> None:
        """Gracefully disconnect from the peer and clean up resources."""
        async with self._lock:
            if self._state == BLEConnectionState.DISCONNECTED:
                return
            logger.info("Disconnecting from BLE peer: %s", self.peer_address)
            await self._cleanup()

    async def write(self, data: bytes, response: bool = False) -> None:
        """Write raw bytes to the BitChat GATT characteristic."""
        if not self.is_ready or self._client is None or self._characteristic is None:
            raise BLEConnectionError(
                f"Cannot write to {self.peer_address}: "
                f"connection not ready (state={self._state})"
            )

        try:
            await self._client.write_gatt_char(
                self._characteristic, data, response=response
            )
        except Exception as e:
            raise BLEConnectionError(
                f"Failed to write data to {self.peer_address}: {e}"
            ) from e
