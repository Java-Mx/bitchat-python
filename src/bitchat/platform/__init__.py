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

__all__ = [
    "BluetoothCapabilities",
    "ConfiguredTransports",
    "LanCapabilities",
    "NetworkCapabilities",
    "SystemCapabilities",
    "SystemReport",
    "configure_viable_transports",
    "detect_system_capabilities",
    "format_configure_report",
]
