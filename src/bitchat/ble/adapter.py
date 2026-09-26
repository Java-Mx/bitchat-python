"""Platform-agnostic Bluetooth adapter detection and radio state monitoring."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdapterInfo:
    """Represents the current state and capabilities of the local Bluetooth adapter."""

    is_available: bool = False
    radio_state: str = "unavailable"  # "on", "off", "disabled", "unavailable"
    is_peripheral_supported: bool = False
    is_central_supported: bool = False
    is_advertising_supported: bool = False
    device_id: str = ""
    name: str = ""

    @property
    def is_enabled(self) -> bool:
        """Return True if the adapter is available and radio is powered on."""
        return self.is_available and self.radio_state == "on"


class BLEAdapterManager:
    """Coordinates Bluetooth adapter detection and radio state monitoring."""

    def __init__(
        self,
        on_state_changed: Callable[[AdapterInfo], None] | None = None,
        custom_backend: Any | None = None,
    ) -> None:
        # custom_backend is test-only injection. Production startup never sets this.
        self.on_state_changed = on_state_changed
        self._custom_backend = custom_backend
        self._current_info = AdapterInfo()
        self._is_monitoring: bool = False
        self._monitor_task: asyncio.Task[None] | None = None
        self._winrt_radio: Any | None = None
        self._winrt_token: Any | None = None
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def current_info(self) -> AdapterInfo:
        """Return cached adapter state information."""
        return self._current_info

    async def check_adapter(self) -> AdapterInfo:
        """Perform an immediate hardware adapter detection check."""
        if self._custom_backend is not None:
            info = await self._custom_backend.check_adapter()
            self._current_info = info
            return info

        if os.name == "nt":
            info = await self._check_windows_adapter()
        else:
            info = await self._check_generic_adapter()

        self._current_info = info
        return info

    async def start_monitoring(
        self, callback: Callable[[AdapterInfo], None] | None = None
    ) -> None:
        """Begin event-driven and periodic monitoring of adapter radio state."""
        async with self._lock:
            if callback is not None:
                self.on_state_changed = callback

            if self._is_monitoring:
                return

            self._loop = asyncio.get_running_loop()
            self._is_monitoring = True

            # Initial check
            await self.check_adapter()

            # Start event listener on Windows
            if os.name == "nt" and self._custom_backend is None:
                await self._setup_windows_listener()

            # Gentle background verification loop (checks every 4 seconds)
            self._monitor_task = asyncio.create_task(self._poll_loop())

    async def stop_monitoring(self) -> None:
        """Stop adapter monitoring and clean up listeners."""
        async with self._lock:
            if not self._is_monitoring:
                return

            self._is_monitoring = False
            if self._monitor_task is not None:
                self._monitor_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._monitor_task
                self._monitor_task = None

            if self._winrt_radio is not None and self._winrt_token is not None:
                with contextlib.suppress(Exception):
                    self._winrt_radio.remove_state_changed(self._winrt_token)
                self._winrt_radio = None
                self._winrt_token = None

    async def _check_windows_adapter(self) -> AdapterInfo:
        """Query Windows WinRT for default BluetoothAdapter and radio state."""
        try:
            from winrt.windows.devices.bluetooth import BluetoothAdapter
            from winrt.windows.devices.radios import RadioState

            adapter = await BluetoothAdapter.get_default_async()
            if adapter is None:
                return AdapterInfo(
                    is_available=False,
                    radio_state="unavailable",
                    name="No Bluetooth Adapter",
                )

            radio = await adapter.get_radio_async()
            state_str = "unknown"
            if radio is not None:
                state_map = {
                    RadioState.ON: "on",
                    RadioState.OFF: "off",
                    RadioState.DISABLED: "disabled",
                    RadioState.UNKNOWN: "unknown",
                }
                state_str = state_map.get(radio.state, "unknown")
            else:
                state_str = "unavailable"

            is_periph = bool(getattr(adapter, "is_peripheral_role_supported", False))
            is_central = bool(getattr(adapter, "is_central_role_supported", True))
            is_adv = bool(getattr(adapter, "is_advertisement_offload_supported", False))

            device_id = str(getattr(adapter, "device_id", ""))
            radio_name = str(getattr(radio, "name", "Bluetooth Adapter"))

            return AdapterInfo(
                is_available=True,
                radio_state=state_str,
                is_peripheral_supported=is_periph,
                is_central_supported=is_central,
                is_advertising_supported=is_adv,
                device_id=device_id,
                name=radio_name,
            )
        except Exception as e:
            logger.warning("Windows WinRT Bluetooth check failed: %s", e)
            return AdapterInfo(
                is_available=False,
                radio_state="unavailable",
                name=f"Error: {e}",
            )

    async def _check_generic_adapter(self) -> AdapterInfo:
        """Generic fallback adapter check for non-Windows platforms."""
        try:
            from bleak import BleakScanner

            # Try a zero-duration scanner instantiation
            _ = BleakScanner()
            return AdapterInfo(
                is_available=True,
                radio_state="on",
                is_peripheral_supported=False,
                is_central_supported=True,
                name="Generic BLE Adapter",
            )
        except Exception as e:
            logger.debug("Generic adapter check failed: %s", e)
            return AdapterInfo(
                is_available=False,
                radio_state="unavailable",
                name=f"Generic Error: {e}",
            )

    async def _setup_windows_listener(self) -> None:
        """Register native WinRT Radio.state_changed callback."""
        try:
            from winrt.windows.devices.bluetooth import BluetoothAdapter

            adapter = await BluetoothAdapter.get_default_async()
            if adapter is None:
                return

            radio = await adapter.get_radio_async()
            if radio is None:
                return

            def _on_radio_state_changed(_sender: Any, _args: Any) -> None:
                if self._loop is not None and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._handle_radio_event(), self._loop
                    )

            self._winrt_radio = radio
            self._winrt_token = radio.add_state_changed(_on_radio_state_changed)
            logger.debug("WinRT radio state_changed listener installed")
        except Exception as e:
            logger.warning("Could not setup WinRT radio state listener: %s", e)

    async def _handle_radio_event(self) -> None:
        """Process native radio state change event."""
        prev = self._current_info
        new_info = await self.check_adapter()
        if (
            new_info.is_available != prev.is_available
            or new_info.radio_state != prev.radio_state
        ):
            logger.info(
                "Bluetooth radio state transition: %s -> %s",
                prev.radio_state,
                new_info.radio_state,
            )
            self._notify_listeners(new_info)

    def _notify_listeners(self, info: AdapterInfo) -> None:
        """Trigger registered callback with updated adapter info."""
        if self.on_state_changed is not None:
            try:
                self.on_state_changed(info)
            except Exception as e:
                logger.error("Error in on_state_changed callback: %s", e)

    async def _poll_loop(self) -> None:
        """Periodic verification loop to ensure state consistency."""
        while self._is_monitoring:
            try:
                await asyncio.sleep(4.0)
                if not self._is_monitoring:
                    break
                prev = self._current_info
                new_info = await self.check_adapter()
                if (
                    new_info.is_available != prev.is_available
                    or new_info.radio_state != prev.radio_state
                ):
                    logger.info(
                        "Periodic check detected radio state change: %s -> %s",
                        prev.radio_state,
                        new_info.radio_state,
                    )
                    self._notify_listeners(new_info)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Error in adapter poll loop: %s", e)
