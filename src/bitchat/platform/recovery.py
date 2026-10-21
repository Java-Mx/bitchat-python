"""Operating-system specific Bluetooth recovery guidance.

The TUI shows this text but never decides *which* text applies: the platform layer
does, so widgets contain no OS branching. Linux guidance avoids assuming a
particular distribution, desktop environment, or init system.
"""

from __future__ import annotations

from bitchat.platform.detection import PlatformKind, detect_platform

_WINDOWS_HINTS: tuple[str, ...] = (
    "Ensure Bluetooth is toggled ON in Windows Settings.",
    "Make sure the Bluetooth adapter is enabled in Device Manager.",
    "Click 'Retry Adapter' after turning Bluetooth on.",
)
_LINUX_HINTS: tuple[str, ...] = (
    "Ensure a Bluetooth adapter is present and not blocked "
    "(e.g. `rfkill list`, `bluetoothctl power on`).",
    "Ensure the BlueZ daemon (bluetoothd) is running; on systemd-based "
    "distributions: `systemctl status bluetooth`.",
    "Ensure your user may access BlueZ over D-Bus (distribution policy varies).",
    "Click 'Retry Adapter' after fixing the problem.",
)
_GENERIC_HINTS: tuple[str, ...] = (
    "Ensure a Bluetooth adapter is present and enabled.",
    "Click 'Retry Adapter' after turning Bluetooth on.",
)

_WINDOWS_GATT_HINT = (
    "Windows can abort GATT advertising even when the Bluetooth radio is on."
)
_LINUX_GATT_HINT = (
    "BlueZ could not register or advertise the BitChat GATT service. "
    "Check that bluetoothd is healthy."
)
_GENERIC_GATT_HINT = "The BLE GATT service could not be initialized."


def bluetooth_recovery_hints(kind: PlatformKind | None = None) -> tuple[str, ...]:
    """Return remediation steps for a missing or disabled Bluetooth adapter."""
    kind = kind or detect_platform()
    if kind is PlatformKind.WINDOWS:
        return _WINDOWS_HINTS
    if kind is PlatformKind.LINUX:
        return _LINUX_HINTS
    return _GENERIC_HINTS


def gatt_failure_hint(kind: PlatformKind | None = None) -> str:
    """Return the OS-specific explanation for a GATT/advertising failure."""
    kind = kind or detect_platform()
    if kind is PlatformKind.WINDOWS:
        return _WINDOWS_GATT_HINT
    if kind is PlatformKind.LINUX:
        return _LINUX_GATT_HINT
    return _GENERIC_GATT_HINT
