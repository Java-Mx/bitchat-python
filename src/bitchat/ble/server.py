"""GATT Server and BLE advertiser for BitChat peripheral role."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import TYPE_CHECKING, Any

from bitchat.exceptions import BLEError
from bitchat.logging import log_transport_diagnostic
from bitchat.platform.detection import (
    is_linux,
    is_windows,
    peripheral_backend_implemented,
)
from bitchat.protocol.constants import (
    BITCHAT_CHARACTERISTIC_UUID,
    BITCHAT_SERVICE_UUID,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_ADVERTISEMENT_START_TIMEOUT_SECONDS = 5.0
_ADVERTISEMENT_POLL_INTERVAL_SECONDS = 0.05
_LEGACY_ADVERTISEMENT_MAX_BYTES = 31
_MANUFACTURER_AD_STRUCTURE_OVERHEAD = 4

WINRT_BLUETOOTH_ERROR_NAMES: dict[int, str] = {
    0: "Success",
    1: "RadioNotAvailable",
    2: "ResourceInUse",
    3: "DeviceNotConnected",
    4: "OtherError",
    5: "DisabledByPolicy",
    6: "NotSupported",
    7: "DisabledByUser",
    8: "ConsentRequired",
    9: "TransportNotSupported",
}

WINRT_GATT_ADV_STATUS_NAMES: dict[int, str] = {
    0: "Created",
    1: "Stopped",
    2: "Started",
    3: "Aborted",
    4: "StartedWithoutAllAdvertisementData",
}


def _extract_winrt_error_info(exc: Exception) -> tuple[int | None, str | None]:
    """Extract Win32 error code and formatted HRESULT from exception if available."""
    code = getattr(exc, "winerror", None) or getattr(exc, "hresult", None)
    if code is None:
        return None, None
    unsigned_code = code & 0xFFFFFFFF
    hresult_str = f"0x{unsigned_code:08X}"
    win32_code = code & 0xFFFF if (unsigned_code & 0xFFFF0000) == 0x80070000 else code
    return win32_code, hresult_str


def _manufacturer_advertisement_payload(service_uuid: str) -> bytes:
    return b"BC" + uuid.UUID(service_uuid).bytes


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
        linux_bus: Any | None = None,
    ) -> None:
        self.service_uuid = service_uuid.lower()
        self.characteristic_uuid = characteristic_uuid.lower()
        self.on_data_received = on_data_received
        self.on_client_subscribed = on_client_subscribed
        self.on_client_unsubscribed = on_client_unsubscribed
        self._custom_backend = backend
        self.peer_id = peer_id
        self.nickname = nickname
        self._linux_bus = linux_bus
        self._linux_backend: Any | None = None

        self._is_advertising: bool = False
        self._last_error: str | None = None
        self._failed_stage: str | None = None
        self._error_code: int | None = None
        self._hresult: str | None = None
        self._error_source: str | None = None
        self._provider: Any | None = None
        self._characteristic: Any | None = None
        self._publisher: Any | None = None
        self._write_token: Any | None = None
        self._subscribers_token: Any | None = None
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_advertising(self) -> bool:
        """Return True if the server is currently advertising."""
        return self._is_advertising

    @property
    def supports_peripheral(self) -> bool:
        """Return True if this process can host a GATT server on this platform.

        An injected backend is always honoured; otherwise only platforms with a
        native implementation (Windows WinRT and Linux BlueZ) can advertise.
        """
        return self._custom_backend is not None or peripheral_backend_implemented()

    def update_identity(self, peer_id: str, nickname: str) -> None:
        """Update identity advertised in BLE packets."""
        self.peer_id = peer_id
        self.nickname = nickname
        if self._linux_backend is not None:
            self._linux_backend.update_identity(peer_id, nickname)

    def get_telemetry(self) -> dict[str, Any]:
        """Return truthful telemetry about GATT server state."""
        linux = self._linux_backend
        has_provider = self._provider is not None or (
            linux is not None and linux.has_provider
        )
        has_publisher = self._publisher is not None or (
            linux is not None and linux.has_publisher
        )
        characteristic = self._characteristic or getattr(linux, "_characteristic", None)
        service_registered = has_provider
        advertisement_registered = has_publisher
        if self._custom_backend is not None:
            backend_name = type(self._custom_backend).__name__
        elif is_windows():
            backend_name = "Windows WinRT GATT"
        elif is_linux():
            backend_name = "Linux BlueZ (D-Bus)"
        else:
            backend_name = "Unsupported"
        return {
            "backend_name": backend_name,
            "server_active": self._is_advertising,
            "is_advertising": self._is_advertising,
            "service_uuid": self.service_uuid,
            "service_registered": service_registered,
            "characteristic_uuid": self.characteristic_uuid,
            "characteristic_registered": characteristic is not None,
            "notifications_supported": characteristic is not None,
            "subscribed_client_count": len(
                getattr(characteristic, "subscribed_clients", ()) or ()
            ),
            "has_provider": has_provider,
            "has_publisher": has_publisher,
            "advertisement_registered": advertisement_registered,
            "dbus_available": bool(getattr(linux, "_bus", None)) if linux else None,
            "adapter_path": getattr(linux, "_adapter_path", None),
            "last_error": self._last_error,
            "failed_stage": self._failed_stage,
            "error_code": self._error_code,
            "hresult": self._hresult,
            "error_source": self._error_source,
        }

    async def start(self) -> None:
        """Start the GATT server and advertise the BitChat service."""
        async with self._lock:
            if self._is_advertising:
                return

            self._loop = asyncio.get_running_loop()
            self._last_error = None
            self._failed_stage = None
            self._error_code = None
            self._hresult = None
            self._error_source = None

            if self._custom_backend is not None:
                try:
                    await self._custom_backend.start(self)
                except Exception as e:
                    with contextlib.suppress(Exception):
                        await self._custom_backend.stop()
                    self._last_error = str(e)
                    self._is_advertising = False
                    raise BLEError(f"Failed to start BLE server backend: {e}") from e
                self._is_advertising = True
                logger.info("BLEServer started using injected test backend")
                return

            if is_windows():
                await self._start_windows_server()
            elif is_linux():
                await self._start_linux_server()
            else:
                logger.info(
                    "Native BLE peripheral mode is only implemented on Windows "
                    "WinRT and Linux BlueZ. Running in central-only mode on this "
                    "platform."
                )
                self._is_advertising = False

    async def stop(self) -> None:
        """Stop advertising and clean up the GATT service."""
        async with self._lock:
            if not self._is_advertising:
                if is_windows() and (
                    self._provider is not None
                    or self._publisher is not None
                    or self._characteristic is not None
                ):
                    self._cleanup_windows_resources()
                if is_linux() and self._linux_backend is not None:
                    await self._cleanup_linux_resources()
                return

            if self._custom_backend is not None:
                await self._custom_backend.stop()
                self._is_advertising = False
                logger.info("BLEServer stopped using injected test backend")
                return

            if is_windows():
                self._cleanup_windows_resources()

            if is_linux():
                await self._cleanup_linux_resources()

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

        if is_windows() and self._characteristic is not None:
            try:
                from winrt.windows.storage.streams import (  # pyright: ignore[reportMissingImports]
                    DataWriter,
                )

                writer = DataWriter()
                writer.write_bytes(data)
                buf = writer.detach_buffer()
                await self._characteristic.notify_value_async(buf)
            except Exception as e:
                raise BLEError(f"Failed to notify BLE characteristic: {e}") from e
        elif is_linux() and self._linux_backend is not None:
            await self._linux_backend.send_notification(data, client_id)

    async def _start_windows_server(self) -> None:
        """Initialize Windows WinRT GATT provider and characteristic."""
        try:
            import winrt.windows.devices.bluetooth.advertisement as adv  # pyright: ignore[reportMissingImports]
            import winrt.windows.devices.bluetooth.genericattributeprofile as gatt  # pyright: ignore[reportMissingImports]
            from winrt.windows.storage.streams import (  # pyright: ignore[reportMissingImports]
                DataWriter,
            )

            srv_uuid = uuid.UUID(self.service_uuid)
            log_transport_diagnostic(
                operation="ble_server_start",
                stage="gatt_provider_create",
                result="STARTING",
                requested_transport="bluetooth",
                details=f"Creating WinRT GATT service provider for {self.service_uuid}",
            )
            res = await gatt.GattServiceProvider.create_async(srv_uuid)
            if res.error != 0 or res.service_provider is None:
                err_code = int(res.error) if hasattr(res, "error") else -1
                err_name = WINRT_BLUETOOTH_ERROR_NAMES.get(err_code, "UnknownError")
                self._failed_stage = "gatt_provider_create"
                self._error_code = err_code
                self._error_source = "winrt.GattServiceProvider.create_async"
                self._last_error = (
                    f"Failed to create GattServiceProvider: {err_name} "
                    f"(error {err_code})"
                )
                log_transport_diagnostic(
                    operation="ble_server_start",
                    stage="gatt_provider_create",
                    result="FAILED",
                    requested_transport="bluetooth",
                    error_code=err_code,
                    source="winrt.GattServiceProvider.create_async",
                    cleanup_result="windows_resources_released",
                    details=self._last_error,
                )
                raise BLEError(self._last_error)

            provider = res.service_provider
            self._provider = provider
            char_uuid = uuid.UUID(self.characteristic_uuid)
            char_params = gatt.GattLocalCharacteristicParameters()
            char_params.characteristic_properties = (
                gatt.GattCharacteristicProperties.WRITE_WITHOUT_RESPONSE
                | gatt.GattCharacteristicProperties.WRITE
                | gatt.GattCharacteristicProperties.NOTIFY
            )

            log_transport_diagnostic(
                operation="ble_server_start",
                stage="characteristic_create",
                result="STARTING",
                requested_transport="bluetooth",
                details=(
                    f"Creating WinRT GATT characteristic for {self.characteristic_uuid}"
                ),
            )
            c_res = await provider.service.create_characteristic_async(
                char_uuid, char_params
            )
            if c_res.error != 0 or c_res.characteristic is None:
                err_code = int(c_res.error) if hasattr(c_res, "error") else -1
                err_name = WINRT_BLUETOOTH_ERROR_NAMES.get(err_code, "UnknownError")
                self._failed_stage = "characteristic_create"
                self._error_code = err_code
                self._error_source = "winrt.GattLocalCharacteristicParameters"
                self._last_error = (
                    f"Failed to create GattLocalCharacteristic: {err_name} "
                    f"(error {err_code})"
                )
                log_transport_diagnostic(
                    operation="ble_server_start",
                    stage="characteristic_create",
                    result="FAILED",
                    requested_transport="bluetooth",
                    error_code=err_code,
                    source="winrt.GattLocalCharacteristicParameters",
                    cleanup_result="windows_resources_released",
                    details=self._last_error,
                )
                raise BLEError(self._last_error)

            char = c_res.characteristic
            self._characteristic = char
            self._write_token = char.add_write_requested(self._on_winrt_write_requested)
            self._subscribers_token = char.add_subscribed_clients_changed(
                self._on_winrt_subscribers_changed
            )

            advertising_params = gatt.GattServiceProviderAdvertisingParameters()
            advertising_params.is_connectable = True
            advertising_params.is_discoverable = True
            log_transport_diagnostic(
                operation="ble_server_start",
                stage="advertising_start",
                result="STARTING",
                requested_transport="bluetooth",
                details="Starting WinRT GATT service advertising",
            )
            provider.start_advertising_with_parameters(advertising_params)
            try:
                await self._wait_for_gatt_advertisement_status(provider)
            except BLEError:
                status_val = int(getattr(provider, "advertisement_status", 3))
                status_name = WINRT_GATT_ADV_STATUS_NAMES.get(status_val, "Unknown")
                self._failed_stage = "advertising_start"
                self._error_code = status_val
                self._error_source = "winrt.GattServiceProviderAdvertisementStatus"
                self._last_error = (
                    f"GATT service advertising failed with status "
                    f"{status_val} ({status_name})"
                )
                log_transport_diagnostic(
                    operation="ble_server_start",
                    stage="advertising_start",
                    result="ABORTED",
                    requested_transport="bluetooth",
                    error_code=status_val,
                    source="winrt.GattServiceProviderAdvertisementStatus",
                    cleanup_result="windows_resources_released",
                    details=self._last_error,
                )
                logger.warning(
                    "GATT service advertising failed (%s); "
                    "continuing without peripheral role",
                    self._last_error,
                )
                self._is_advertising = False
                self._cleanup_windows_resources()
                return

            # Broadcast companion manufacturer advertisement so nodes detect BitChat
            try:
                publisher = adv.BluetoothLEAdvertisementPublisher()
                m = adv.BluetoothLEManufacturerData()
                m.company_id = 0xFFFF
                writer = DataWriter()
                payload = _manufacturer_advertisement_payload(self.service_uuid)
                if len(payload) + _MANUFACTURER_AD_STRUCTURE_OVERHEAD > (
                    _LEGACY_ADVERTISEMENT_MAX_BYTES
                ):
                    raise BLEError("BitChat manufacturer advertisement is too large")
                writer.write_bytes(payload)
                m.data = writer.detach_buffer()
                publisher.advertisement.manufacturer_data.append(m)
                self._publisher = publisher
                publisher.start()
                await self._wait_for_advertisement_status(
                    publisher,
                    "status",
                    started_status=2,
                    failed_statuses=(3, 4, 5),
                    advertisement_type="BitChat discovery",
                )
                logger.info(
                    "WinRT BLE advertisement publisher started for BitChat (%s)",
                    self.service_uuid,
                )
            except Exception as pub_err:
                err_code, hresult = _extract_winrt_error_info(pub_err)
                self._failed_stage = "discovery_advertisement_start"
                self._error_code = err_code
                self._hresult = hresult
                self._error_source = "winrt.BluetoothLEAdvertisementPublisher"
                self._last_error = (
                    f"WinRT BitChat discovery advertisement failed: {pub_err}"
                )
                log_transport_diagnostic(
                    operation="ble_server_start",
                    stage="discovery_advertisement_start",
                    result="FAILED",
                    requested_transport="bluetooth",
                    error_code=err_code,
                    hresult=hresult,
                    source="winrt.BluetoothLEAdvertisementPublisher",
                    cleanup_result="windows_resources_released",
                    details=self._last_error,
                )
                raise BLEError(self._last_error) from pub_err

            self._is_advertising = True
            log_transport_diagnostic(
                operation="ble_server_start",
                stage="server_active",
                result="SUCCESS",
                requested_transport="bluetooth",
                active_transport="bluetooth",
                details=f"WinRT BLEServer active for {self.service_uuid}",
            )
            logger.info(
                "WinRT BLEServer active for BitChat service %s", self.service_uuid
            )
        except asyncio.CancelledError:
            self._cleanup_windows_resources()
            self._is_advertising = False
            raise
        except Exception as e:
            self._cleanup_windows_resources()
            self._is_advertising = False
            err_code, hresult = _extract_winrt_error_info(e)
            if self._error_code is None and err_code is not None:
                self._error_code = err_code
            if self._hresult is None and hresult is not None:
                self._hresult = hresult
            if self._failed_stage is None:
                self._failed_stage = "start_windows_server"
            if self._error_source is None:
                self._error_source = type(e).__name__
            self._last_error = str(e)
            log_transport_diagnostic(
                operation="ble_server_start",
                stage=self._failed_stage,
                result="FAILED",
                requested_transport="bluetooth",
                error_code=self._error_code,
                hresult=self._hresult,
                source=self._error_source,
                cleanup_result="windows_resources_released",
                details=str(e),
            )
            raise BLEError(f"Failed to start WinRT BLEServer: {e}") from e

        self._last_error = None

    @staticmethod
    async def _wait_for_advertisement_status(
        resource: Any,
        status_attribute: str,
        started_status: int,
        failed_statuses: tuple[int, ...],
        advertisement_type: str,
    ) -> None:
        """Wait for WinRT to report that an advertisement actually started."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _ADVERTISEMENT_START_TIMEOUT_SECONDS
        while True:
            status = int(getattr(resource, status_attribute))
            if status == started_status:
                return
            if status in failed_statuses:
                raise BLEError(
                    f"{advertisement_type} advertising failed with status {status}"
                )
            if loop.time() >= deadline:
                raise BLEError(
                    f"{advertisement_type} advertising did not start (status {status})"
                )
            await asyncio.sleep(_ADVERTISEMENT_POLL_INTERVAL_SECONDS)

    @staticmethod
    async def _wait_for_gatt_advertisement_status(provider: Any) -> bool:
        """Wait for GattServiceProvider advertisement to reach a terminal state.

        GattServiceProviderAdvertisementStatus enum values (WinRT):
          0 = Created   (initial / pre-start)
          1 = Stopped
          2 = Started                           -> full success
          3 = Aborted                           -> failure
          4 = StartedWithoutAllAdvertisementData -> partial success (acceptable)

        Returns True when fully started, True when partially started (logs warning),
        raises BLEError when aborted.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _ADVERTISEMENT_START_TIMEOUT_SECONDS
        while True:
            status = int(getattr(provider, "advertisement_status", 0))
            if status == 2:  # STARTED
                return True
            if status == 4:  # STARTED_WITHOUT_ALL_ADVERTISEMENT_DATA
                logger.warning(
                    "GATT service started without all advertisement data (status 4). "
                    "Some service metadata may not be broadcast. Continuing."
                )
                return True
            if status == 3:  # ABORTED
                raise BLEError(
                    "GATT service advertising failed with status 3 (Aborted)"
                )
            if loop.time() >= deadline:
                raise BLEError(
                    "GATT service advertising did not start within timeout "
                    f"(status {status})"
                )
            await asyncio.sleep(_ADVERTISEMENT_POLL_INTERVAL_SECONDS)

    def _cleanup_windows_resources(self) -> None:
        """Safely release Windows WinRT provider, publisher, and event handlers."""
        char = self._characteristic
        if char is not None:
            if self._write_token is not None:
                with contextlib.suppress(Exception):
                    char.remove_write_requested(self._write_token)
            if self._subscribers_token is not None:
                with contextlib.suppress(Exception):
                    char.remove_subscribed_clients_changed(self._subscribers_token)
        self._write_token = None
        self._subscribers_token = None

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
                import winrt.windows.devices.bluetooth.genericattributeprofile as gatt  # pyright: ignore[reportMissingImports]
                from winrt.windows.storage.streams import (  # pyright: ignore[reportMissingImports]
                    DataReader,
                )

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

    def _dispatch_data_received(self, data: bytes, client_id: str) -> None:
        if self.on_data_received is not None:
            self.on_data_received(data, client_id)

    def _dispatch_client_subscribed(self, client_id: str) -> None:
        if self.on_client_subscribed is not None:
            self.on_client_subscribed(client_id)

    def _dispatch_client_unsubscribed(self, client_id: str) -> None:
        if self.on_client_unsubscribed is not None:
            self.on_client_unsubscribed(client_id)

    def _on_advertising_state_changed(self, is_advertising: bool) -> None:
        self._is_advertising = is_advertising

    async def _start_linux_server(self) -> None:
        """Initialize Linux BlueZ GATT provider and LE advertisement."""
        log_transport_diagnostic(
            operation="ble_server_start",
            stage="bluez_gatt_server_start",
            result="STARTING",
            requested_transport="bluetooth",
            details=f"Starting Linux BlueZ GATT server for {self.service_uuid}",
        )
        try:
            from bitchat.ble.bluez import BlueZServerBackend

            backend = BlueZServerBackend(
                service_uuid=self.service_uuid,
                characteristic_uuid=self.characteristic_uuid,
                on_data_received=self._dispatch_data_received,
                on_client_subscribed=self._dispatch_client_subscribed,
                on_client_unsubscribed=self._dispatch_client_unsubscribed,
                on_advertising_state_changed=self._on_advertising_state_changed,
                bus=self._linux_bus,
                peer_id=self.peer_id,
                nickname=self.nickname,
            )
            self._linux_backend = backend
            await backend.start()
            self._is_advertising = True
            self._last_error = None
            log_transport_diagnostic(
                operation="ble_server_start",
                stage="bluez_gatt_server_start",
                result="SUCCESS",
                requested_transport="bluetooth",
                active_transport="bluetooth",
                details=f"Linux BlueZ BLEServer active for {self.service_uuid}",
            )
            logger.info(
                "Linux BlueZ BLEServer active for BitChat service %s", self.service_uuid
            )
        except asyncio.CancelledError:
            await self._cleanup_linux_resources()
            self._is_advertising = False
            raise
        except Exception as e:
            await self._cleanup_linux_resources()
            self._is_advertising = False
            self._last_error = str(e)
            self._failed_stage = "bluez_gatt_server_start"
            self._error_source = "BlueZServerBackend"
            log_transport_diagnostic(
                operation="ble_server_start",
                stage="bluez_gatt_server_start",
                result="FAILED",
                requested_transport="bluetooth",
                source="BlueZServerBackend",
                cleanup_result="linux_resources_released",
                details=str(e),
            )
            logger.warning(
                "Linux BlueZ GATT service advertising failed (%s); "
                "continuing without peripheral role",
                e,
            )

    async def _cleanup_linux_resources(self) -> None:
        """Safely release Linux BlueZ backend and D-Bus resources."""
        backend = self._linux_backend
        self._linux_backend = None
        if backend is not None:
            with contextlib.suppress(Exception):
                await backend.stop()
