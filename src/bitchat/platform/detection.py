"""Centralized operating-system detection and BLE backend probing.

Three questions are deliberately kept separate here and elsewhere:

1. *Which operating system is this?* (:func:`detect_platform`)
2. *Does BitChat have a usable BLE backend for it?* (:func:`probe_ble_backend`)
3. *Is Bluetooth hardware present and powered?* — answered at runtime by
   :class:`bitchat.ble.adapter.BLEAdapterManager`, never by this module.

Knowing the OS (1) never implies that Bluetooth works (2, 3). Operating-system
detection uses only :data:`sys.platform`, read at call time so tests can mock it.
This module must stay free of imports from the rest of ``bitchat`` so that any
layer (BLE, network, TUI helpers) can depend on it without import cycles, and it
never imports a platform-specific package: backend availability is probed with
:mod:`importlib` without executing foreign-platform code.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from enum import StrEnum


class PlatformKind(StrEnum):
    """Operating-system families BitChat distinguishes."""

    WINDOWS = "windows"
    LINUX = "linux"
    OTHER = "other"


def detect_platform() -> PlatformKind:
    """Return the current operating-system family from :data:`sys.platform`."""
    platform_id = sys.platform
    if platform_id == "win32":
        return PlatformKind.WINDOWS
    if platform_id.startswith("linux"):
        return PlatformKind.LINUX
    return PlatformKind.OTHER


def is_windows() -> bool:
    """Return True when running on Windows."""
    return detect_platform() is PlatformKind.WINDOWS


def is_linux() -> bool:
    """Return True when running on Linux."""
    return detect_platform() is PlatformKind.LINUX


def is_supported_platform(kind: PlatformKind | None = None) -> bool:
    """Return True for operating systems with a first-class BLE backend."""
    return (kind or detect_platform()) in (PlatformKind.WINDOWS, PlatformKind.LINUX)


def peripheral_backend_implemented(kind: PlatformKind | None = None) -> bool:
    """Return True if BitChat implements the BLE peripheral (GATT server) role.

    Only the Windows WinRT backend currently hosts a GATT server. On Linux the
    BlueZ GATT server is not implemented, so BitChat runs central-only there
    regardless of what the adapter hardware supports.
    """
    return (kind or detect_platform()) is PlatformKind.WINDOWS


# Python modules each platform's BLE backend needs at runtime. These are declared
# with environment markers by ``bleak`` itself (``dbus-fast`` on Linux, ``winrt-*``
# on Windows), so a normal install already provides them.
_BACKEND_NAME: dict[PlatformKind, str] = {
    PlatformKind.WINDOWS: "WinRT",
    PlatformKind.LINUX: "BlueZ (D-Bus)",
    PlatformKind.OTHER: "bleak",
}
_BACKEND_MODULES: dict[PlatformKind, tuple[str, ...]] = {
    PlatformKind.WINDOWS: (
        "bleak",
        "winrt.windows.devices.bluetooth",
        "winrt.windows.devices.bluetooth.genericattributeprofile",
        "winrt.windows.devices.bluetooth.advertisement",
        "winrt.windows.devices.radios",
        "winrt.windows.storage.streams",
    ),
    PlatformKind.LINUX: ("bleak", "dbus_fast"),
    PlatformKind.OTHER: ("bleak",),
}


@dataclass(frozen=True)
class BleBackendStatus:
    """Whether the platform's BLE Python backend can be used at all."""

    platform: PlatformKind
    name: str
    available: bool
    missing_modules: tuple[str, ...] = ()

    @property
    def reason(self) -> str | None:
        """Human-readable explanation when the backend is unavailable."""
        if self.available:
            return None
        modules = ", ".join(self.missing_modules)
        return (
            f"{self.name} BLE backend unavailable: missing Python module(s) {modules}"
        )


def _module_available(name: str) -> bool:
    """Return True if ``name`` is importable, without importing it if avoidable."""
    if name in sys.modules:
        # A ``None`` entry is the documented way to block an import.
        return sys.modules[name] is not None
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def probe_ble_backend(kind: PlatformKind | None = None) -> BleBackendStatus:
    """Check that the Python BLE backend for ``kind`` (default: this OS) is present.

    This says nothing about Bluetooth hardware, radio state, or permissions.
    """
    kind = kind or detect_platform()
    missing = tuple(
        module for module in _BACKEND_MODULES[kind] if not _module_available(module)
    )
    return BleBackendStatus(
        platform=kind,
        name=_BACKEND_NAME[kind],
        available=not missing,
        missing_modules=missing,
    )
