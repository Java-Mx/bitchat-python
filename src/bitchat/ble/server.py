"""GATT Server and BLE advertiser for BitChat peripheral role."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid
from typing import TYPE_CHECKING, Any

from bitchat.exceptions import BLEError
from bitchat.protocol.constants import (
    BITCHAT_CHARACTERISTIC_UUID,
    BITCHAT_SERVICE_UUID,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class BLEServer:
    """GATT Server hosting the BitChat service and characteristic."""

    def __init__(
        self,
        service_uuid: str = BITCHAT_SERVICE_UUID,
        characteristic_uuid: str = BITCHAT_CHARACTERISTIC_UUID,
        on_data_received: Callable[[bytes, str], None] | None = None,
        on_client_subscribed: Callable[[str], None] | None = None,
        on_client_unsubscribed: Callable[[str], None] | None = None,
        backend: Any | None = None,
        peer_id: str = "",
        nickname: str = "",
    ) -> None:
        self.service_uuid = service_uuid.lower()
        self.characteristic_uuid = characteristic_uuid.lower()
        self.on_data_received = on_data_received
        self.on_client_subscribed = on_client_subscribed
        self.on_client_unsubscribed = on_client_unsubscribed
        self._custom_backend = backend
        self.peer_id = peer_id
        self.nickname = nickname

        self._is_advertising: bool = False
        self._provider: Any | None = None
        self._characteristic: Any | None = None
        self._publisher: Any | None = None
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_advertising(self) -> bool:
        """Return True if the server is currently advertising."""
        return self._is_advertising

    def update_identity(self, peer_id: str, nickname: str) -> None:
        """Update identity advertised in BLE packets."""
        self.peer_id = peer_id
        self.nickname = nickname

    def get_telemetry(self) -> dict[str, Any]:
        """Return truthful telemetry about GATT server state."""
        return {
            "server_active": self._is_advertising,
            "is_advertising": self._is_advertising,
            "service_uuid": self.service_uuid,
            "characteristic_uuid": self.characteristic_uuid,
            "has_provider": self._provider is not None,
            "has_publisher": self._publisher is not None,
        }

    async def start(self) -> None:
        """Start the GATT server and advertise the BitChat service."""
        async with self._lock:
            if self._is_advertising:
                return

            self._loop = asyncio.get_running_loop()

            if self._custom_backend is not None:
                await self._custom_backend.start(self)
                self._is_advertising = True
                logger.info("BLEServer started using injected test backend")
                return

            if os.name == "nt":
                await self._start_windows_server()
            else:
                logger.warning(
                    "Native BLE peripheral mode currently only implemented on "
                    "Windows WinRT. Running in central-only mode on this platform."
                )
                self._is_advertising = False

    async def stop(self) -> None:
        """Stop advertising and clean up the GATT service."""
        async with self._lock:
            if not self._is_advertising:
                return

            if self._custom_backend is not None:
                await self._custom_backend.stop()
                self._is_advertising = False
                logger.info("BLEServer stopped using injected test backend")
                return

            if os.name == "nt":
                if self._publisher is not None:
                    with contextlib.suppress(Exception):
                        self._publisher.stop()
                    self._publisher = None

                if self._provider is not None:
                    with contextlib.suppress(Exception):
                        self._provider.stop_advertising()
                    self._provider = None
                    self._characteristic = None

            self._is_advertising = False
            logger.info("BLEServer stopped")

    async def send_notification(
        self, data: bytes, client_id: str | None = None
    ) -> None:
        """Send notification bytes to connected/subscribed client(s)."""
        if not self._is_advertising:
            raise BLEError("Cannot send notification: BLEServer is not active")

        if self._custom_backend is not None:
            await self._custom_backend.send_notification(data, client_id)
            return

        if os.name == "nt" and self._characteristic is not None:
            try:
                from winrt.windows.storage.streams import DataWriter

                writer = DataWriter()
                writer.write_bytes(data)
                buf = writer.detach_buffer()
                await self._characteristic.notify_value_async(buf)
            except Exception as e:
                raise BLEError(f"Failed to notify BLE characteristic: {e}") from e

    async def _start_windows_server(self) -> None:
        """Initialize Windows WinRT GATT provider and characteristic."""
        try:
            import winrt.windows.devices.bluetooth.advertisement as adv
            import winrt.windows.devices.bluetooth.genericattributeprofile as gatt
            from winrt.windows.storage.streams import DataWriter

            srv_uuid = uuid.UUID(self.service_uuid)
            res = await gatt.GattServiceProvider.create_async(srv_uuid)
            if res.error != 0 or res.service_provider is None:
                raise BLEError(
                    f"Failed to create GattServiceProvider: error {res.error}"
                )

            self._provider = res.service_provider
            char_uuid = uuid.UUID(self.characteristic_uuid)
            char_params = gatt.GattLocalCharacteristicParameters()
            char_params.characteristic_properties = (
                gatt.GattCharacteristicProperties.WRITE_WITHOUT_RESPONSE
                | gatt.GattCharacteristicProperties.WRITE
                | gatt.GattCharacteristicProperties.NOTIFY
            )

            c_res = await self._provider.service.create_characteristic_async(
                char_uuid, char_params
            )
            if c_res.error != 0 or c_res.characteristic is None:
                raise BLEError(
                    f"Failed to create GattLocalCharacteristic: error {c_res.error}"
                )

            char = c_res.characteristic
            char.add_write_requested(self._on_winrt_write_requested)
            char.add_subscribed_clients_changed(self._on_winrt_subscribers_changed)
            self._characteristic = char

            # Start GATT provider advertising
            with contextlib.suppress(Exception):
                self._provider.start_advertising()

            # Broadcast companion manufacturer advertisement so nodes detect BitChat
            try:
                publisher = adv.BluetoothLEAdvertisementPublisher()
                m = adv.BluetoothLEManufacturerData()
                m.company_id = 0xFFFF
                writer = DataWriter()
                # b'BC' + 16-byte UUID + peer_id + '|' + nickname
                payload = b"BC" + srv_uuid.bytes
                if self.peer_id:
                    pid_bytes = self.peer_id[:12].encode("utf-8")
                    nick_bytes = (self.nickname[:8] if self.nickname else "").encode(
                        "utf-8"
                    )
                    payload += pid_bytes + b"|" + nick_bytes
                writer.write_bytes(payload)
                m.data = writer.detach_buffer()
                publisher.advertisement.manufacturer_data.append(m)
                publisher.start()
                self._publisher = publisher
                logger.info(
                    "WinRT BLE advertisement publisher started for BitChat (%s)",
                    self.service_uuid,
                )
            except Exception as pub_err:
                logger.warning(
                    "WinRT advertisement publisher could not start: %s", pub_err
                )

            self._is_advertising = True
            logger.info(
                "WinRT BLEServer active for BitChat service %s", self.service_uuid
            )
        except Exception as e:
            self._cleanup_windows_resources()
            self._is_advertising = False
            raise BLEError(f"Failed to start WinRT BLEServer: {e}") from e

    def _cleanup_windows_resources(self) -> None:
        """Safely release Windows WinRT provider and publisher."""
        if self._publisher is not None:
            with contextlib.suppress(Exception):
                self._publisher.stop()
            self._publisher = None

        if self._provider is not None:
            with contextlib.suppress(Exception):
                self._provider.stop_advertising()
            self._provider = None
            self._characteristic = None

    def _on_winrt_write_requested(self, _char: Any, args: Any) -> None:
        """Callback for incoming write requests from WinRT."""
        import contextlib

        try:
            deferral = args.get_deferral()
        except Exception:
            deferral = None

        async def _process_write() -> None:
            try:
                import winrt.windows.devices.bluetooth.genericattributeprofile as gatt
                from winrt.windows.storage.streams import DataReader

                req = await args.get_request_async()
                if req is None or req.value is None:
                    return

                reader = DataReader.from_buffer(req.value)
                length = reader.unconsumed_buffer_length
                arr = bytearray(length)
                reader.read_bytes(arr)
                raw_bytes = bytes(arr)

                if req.option == gatt.GattWriteOption.WRITE_WITH_RESPONSE:
                    req.respond()

                client_id = "winrt_client"
                if self.on_data_received is not None:
                    self.on_data_received(raw_bytes, client_id)
            except Exception as e:
                logger.warning("Error processing incoming WinRT write: %s", e)
            finally:
                if deferral is not None:
                    with contextlib.suppress(Exception):
                        deferral.complete()

        if self._loop is not None and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(_process_write(), self._loop)

    def _on_winrt_subscribers_changed(self, char: Any, _args: Any) -> None:
        """Callback for subscriber client count changes."""
        try:
            subs = getattr(char, "subscribed_clients", None)
            count = len(subs) if subs is not None else 0
            logger.info("BLE subscriber count changed: %d", count)
            if count > 0 and self.on_client_subscribed:
                self.on_client_subscribed("client")
            elif count == 0 and self.on_client_unsubscribed:
                self.on_client_unsubscribed("client")
        except Exception as e:
            logger.debug("Error in subscribers_changed callback: %s", e)
