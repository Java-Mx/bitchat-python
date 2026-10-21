"""Platform detection, capabilities, and system configuration."""

from bitchat.platform.capabilities import (
    BluetoothCapabilities,
    ConfiguredTransports,
    LanCapabilities,
    NetworkCapabilities,
    SystemCapabilities,
    SystemReport,
    configure_viable_transports,
    detect_system_capabilities,
    format_configure_report,
)
from bitchat.platform.detection import (
    PlatformKind,
    detect_platform,
    is_linux,
    is_windows,
)

__all__ = [
    "BluetoothCapabilities",
    "ConfiguredTransports",
    "LanCapabilities",
    "NetworkCapabilities",
    "PlatformKind",
    "SystemCapabilities",
    "SystemReport",
    "configure_viable_transports",
    "detect_platform",
    "detect_system_capabilities",
    "format_configure_report",
    "is_linux",
    "is_windows",
]
