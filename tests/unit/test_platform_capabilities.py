"""Unit tests for platform capability detection and /configure command."""

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    import pytest

from bitchat.app.application import Application
from bitchat.commands.parser import CommandParser, CommandType
from bitchat.network.models import NetworkInfo
from bitchat.platform.capabilities import (
    BluetoothCapabilities,
    ConfiguredTransports,
    LanCapabilities,
    NetworkCapabilities,
    SystemCapabilities,
    SystemReport,
    _platform_kind_from_system,
    configure_viable_transports,
    detect_network_info,
    detect_system_capabilities,
    detect_system_info,
    format_configure_report,
)
from bitchat.platform.detection import PlatformKind


def test_command_parser_configure() -> None:
    """CommandParser properly recognizes /configure and configure."""
    parser = CommandParser()

    cmd1 = parser.parse("/configure")
    assert cmd1.command_type == CommandType.CONFIGURE
    assert cmd1.error_message is None

    cmd2 = parser.parse("configure")
    assert cmd2.command_type == CommandType.CONFIGURE

    cmd3 = parser.parse("  /configure  --verbose  ")
    assert cmd3.command_type == CommandType.CONFIGURE
    assert cmd3.args == ["--verbose"]

    cmd4 = parser.parse("/diagnostics")
    assert cmd4.command_type == CommandType.CONFIGURE

    cmd5 = parser.parse("diagnostics")
    assert cmd5.command_type == CommandType.CONFIGURE


def test_detect_system_info() -> None:
    """detect_system_info retrieves valid OS, distro, arch, and runtime."""
    sys_info = detect_system_info()
    assert isinstance(sys_info.os_name, str) and len(sys_info.os_name) > 0
    assert isinstance(sys_info.distribution, str) and len(sys_info.distribution) > 0
    assert isinstance(sys_info.architecture, str) and len(sys_info.architecture) > 0
    assert isinstance(sys_info.runtime, str) and "Python" in sys_info.runtime


def test_configure_viable_transports_both_available() -> None:
    """On Windows where peripheral backend is implemented, BLE (Central + Peripheral)
    and LAN available enables both and fallback.
    """
    system = SystemCapabilities("Windows", "Windows 11", "x86_64", "CPython 3.12")
    bt = BluetoothCapabilities(
        adapter="hci0 (Intel)",
        ble_central="Available",
        ble_peripheral="Available",
        gatt_capability="Available",
        bluez="Not applicable (WinRT)",
        permissions="Granted",
    )
    net = NetworkCapabilities(
        wifi="Connected (HomeWifi)",
        ethernet="Available (eth0)",
        ipv4="192.168.1.100",
        ipv6="2001:db8::1",
    )
    lan = LanCapabilities(
        udp_discovery="Available (Port 24024)",
        tcp_transport="Available (Port 24025)",
    )

    cfg = configure_viable_transports(system, bt, net, lan)
    assert cfg.ble == "Enabled (Central + Peripheral)"
    assert cfg.lan == "Enabled"
    assert cfg.fallback == "Enabled"
    assert cfg.recommended_transport == "bluetooth"
    assert "System ready." in cfg.status


def test_configure_viable_transports_linux_central_and_peripheral() -> None:
    """On Linux where peripheral backend is implemented in BitChat,
    configure_viable_transports accurately reports Central + Peripheral
    when the adapter and BlueZ daemon report peripheral Available.
    """
    system = SystemCapabilities("Linux", "Ubuntu 24.04", "x86_64", "CPython 3.12")
    bt = BluetoothCapabilities(
        adapter="hci0 (Intel)",
        ble_central="Available",
        ble_peripheral="Available",
        gatt_capability="Available",
        bluez="Available",
        permissions="Granted",
    )
    net = NetworkCapabilities(
        wifi="Connected (HomeWifi)",
        ethernet="Available (eth0)",
        ipv4="192.168.1.100",
        ipv6="2001:db8::1",
    )
    lan = LanCapabilities(
        udp_discovery="Available (Port 24024)",
        tcp_transport="Available (Port 24025)",
    )

    cfg = configure_viable_transports(system, bt, net, lan)
    assert cfg.ble == "Enabled (Central + Peripheral)"
    assert cfg.lan == "Enabled"
    assert cfg.fallback == "Enabled"
    assert cfg.recommended_transport == "bluetooth"
    assert "System ready." in cfg.status


def test_configure_viable_transports_central_only() -> None:
    """BLE Central available but Peripheral unavailable configures Central-only mode."""
    system = SystemCapabilities("Linux", "Debian 12", "x86_64", "CPython 3.12")
    bt = BluetoothCapabilities(
        adapter="hci0",
        ble_central="Available",
        ble_peripheral="Unsupported",
        gatt_capability="Unsupported",
        bluez="Available",
        permissions="Granted",
    )
    net = NetworkCapabilities(
        wifi="Not detected",
        ethernet="Connected (eth0)",
        ipv4="10.0.0.5",
        ipv6="Not detected",
    )
    lan = LanCapabilities(
        udp_discovery="Available (Port 24024)",
        tcp_transport="Available (Port 24025)",
    )

    cfg = configure_viable_transports(system, bt, net, lan)
    assert cfg.ble == "Enabled (Central Mode only)"
    assert cfg.lan == "Enabled"
    assert cfg.fallback == "Enabled"


def test_configure_viable_transports_no_bluetooth() -> None:
    """Unavailable Bluetooth configures LAN-only mode."""
    system = SystemCapabilities("Linux", "Fedora 40", "x86_64", "CPython 3.12")
    bt = BluetoothCapabilities(
        adapter="Not detected",
        ble_central="Not detected",
        ble_peripheral="Not detected",
        gatt_capability="Not detected",
        bluez="Not running",
        permissions="Unknown",
    )
    net = NetworkCapabilities(
        wifi="Connected (OfficeNet)",
        ethernet="Disconnected",
        ipv4="192.168.0.20",
        ipv6="Not detected",
    )
    lan = LanCapabilities(
        udp_discovery="Available (Port 24024)",
        tcp_transport="Available (Port 24025)",
    )

    cfg = configure_viable_transports(system, bt, net, lan)
    assert cfg.ble == "Unavailable"
    assert cfg.lan == "Enabled"
    assert cfg.fallback == "Disabled (LAN only)"
    assert cfg.recommended_transport == "lan"


def test_configure_viable_transports_no_lan() -> None:
    """Unavailable LAN configures BLE-only mode (on Windows with peripheral)."""
    system = SystemCapabilities("Windows", "Windows 11", "x86_64", "CPython 3.12")
    bt = BluetoothCapabilities(
        adapter="hci0",
        ble_central="Available",
        ble_peripheral="Available",
        gatt_capability="Available",
        bluez="Not applicable (WinRT)",
        permissions="Granted",
    )
    net = NetworkCapabilities(
        wifi="Not detected",
        ethernet="Not detected",
        ipv4="Not detected",
        ipv6="Not detected",
    )
    lan = LanCapabilities(
        udp_discovery="Failed (No network)",
        tcp_transport="Failed (No network)",
    )

    cfg = configure_viable_transports(system, bt, net, lan)
    assert cfg.ble == "Enabled (Central + Peripheral)"
    assert cfg.lan == "Unavailable"
    assert cfg.fallback == "Disabled (BLE only)"
    assert cfg.recommended_transport == "bluetooth"
    assert "System ready (BLE only)." in cfg.status


def test_configure_viable_transports_linux_no_lan() -> None:
    """On Linux without LAN, Central-only BLE is selected with BLE-only fallback."""
    system = SystemCapabilities("Linux", "Ubuntu 24.04", "x86_64", "CPython 3.12")
    bt = BluetoothCapabilities(
        adapter="hci0",
        ble_central="Available",
        ble_peripheral="Available",
        gatt_capability="Available",
        bluez="Available",
        permissions="Granted",
    )
    net = NetworkCapabilities(
        wifi="Not detected",
        ethernet="Not detected",
        ipv4="Not detected",
        ipv6="Not detected",
    )
    lan = LanCapabilities(
        udp_discovery="Failed (No network)",
        tcp_transport="Failed (No network)",
    )

    cfg = configure_viable_transports(system, bt, net, lan)
    assert cfg.ble == "Enabled (Central + Peripheral)"
    assert cfg.lan == "Unavailable"
    assert cfg.fallback == "Disabled (BLE only)"
    assert cfg.recommended_transport == "bluetooth"
    assert "System ready (BLE only)." in cfg.status


def test_configure_viable_transports_linux_no_lan_hardware_unsupported() -> None:
    """On Linux without LAN and unsupported peripheral hardware,
    Central-only BLE is selected.
    """
    system = SystemCapabilities("Linux", "Ubuntu 24.04", "x86_64", "CPython 3.12")
    bt = BluetoothCapabilities(
        adapter="hci0",
        ble_central="Available",
        ble_peripheral="Unsupported",
        gatt_capability="Unsupported",
        bluez="Available",
        permissions="Granted",
    )
    net = NetworkCapabilities(
        wifi="Not detected",
        ethernet="Not detected",
        ipv4="Not detected",
        ipv6="Not detected",
    )
    lan = LanCapabilities(
        udp_discovery="Failed (No network)",
        tcp_transport="Failed (No network)",
    )

    cfg = configure_viable_transports(system, bt, net, lan)
    assert cfg.ble == "Enabled (Central Mode only)"
    assert cfg.lan == "Unavailable"
    assert cfg.fallback == "Disabled (BLE only)"
    assert cfg.recommended_transport == "bluetooth"
    assert "System ready (BLE only)." in cfg.status


def test_configure_viable_transports_explicit_peripheral_override() -> None:
    """Explicit peripheral_supported parameter overrides platform backend defaults."""
    system = SystemCapabilities("Linux", "Ubuntu 24.04", "x86_64", "CPython 3.12")
    bt = BluetoothCapabilities(
        adapter="hci0",
        ble_central="Available",
        ble_peripheral="Available",
        gatt_capability="Available",
        bluez="Available",
        permissions="Granted",
    )
    net = NetworkCapabilities(
        wifi="Connected",
        ethernet="Not detected",
        ipv4="192.168.1.5",
        ipv6="Not detected",
    )
    lan = LanCapabilities("Available (Port 24024)", "Available (Port 24025)")

    # When custom peripheral backend is injected on Linux
    cfg_with_custom = configure_viable_transports(
        system, bt, net, lan, peripheral_supported=True
    )
    assert cfg_with_custom.ble == "Enabled (Central + Peripheral)"

    # When peripheral is disabled on Windows
    win_sys = SystemCapabilities("Windows", "Windows 11", "x86_64", "CPython 3.12")
    cfg_win_disabled = configure_viable_transports(
        win_sys, bt, net, lan, peripheral_supported=False
    )
    assert cfg_win_disabled.ble == "Enabled (Central Mode only)"


def test_bluetooth_capabilities_is_peripheral_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BluetoothCapabilities.is_peripheral_supported checks backend implementation."""
    import sys

    bt_avail = BluetoothCapabilities(
        adapter="hci0",
        ble_central="Available",
        ble_peripheral="Available",
        gatt_capability="Available",
        bluez="Available",
        permissions="Granted",
    )
    assert bt_avail.is_peripheral_available is True

    # On Linux: peripheral backend implemented
    monkeypatch.setattr(sys, "platform", "linux")
    assert bt_avail.is_peripheral_supported is True

    # On Windows: peripheral backend implemented
    monkeypatch.setattr(sys, "platform", "win32")
    assert bt_avail.is_peripheral_supported is True

    # On other platforms: peripheral backend not implemented
    monkeypatch.setattr(sys, "platform", "darwin")
    assert bt_avail.is_peripheral_supported is False

    # When peripheral is Unsupported on adapter: False on all platforms
    bt_unsupported = BluetoothCapabilities(
        adapter="hci0",
        ble_central="Available",
        ble_peripheral="Unsupported",
        gatt_capability="Unsupported",
        bluez="Available",
        permissions="Granted",
    )
    assert bt_unsupported.is_peripheral_supported is False
    monkeypatch.setattr(sys, "platform", "linux")
    assert bt_unsupported.is_peripheral_supported is False
    monkeypatch.setattr(sys, "platform", "win32")
    assert bt_unsupported.is_peripheral_supported is False


def test_bluetooth_capabilities_is_peripheral_supported_for() -> None:
    """BluetoothCapabilities.is_peripheral_supported_for checks platform explicitly."""
    bt_avail = BluetoothCapabilities(
        adapter="hci0",
        ble_central="Available",
        ble_peripheral="Available",
        gatt_capability="Available",
        bluez="Available",
        permissions="Granted",
    )
    assert bt_avail.is_peripheral_supported_for(PlatformKind.WINDOWS) is True
    assert bt_avail.is_peripheral_supported_for(PlatformKind.LINUX) is True
    assert bt_avail.is_peripheral_supported_for(PlatformKind.OTHER) is False

    bt_unsupported = BluetoothCapabilities(
        adapter="hci0",
        ble_central="Available",
        ble_peripheral="Unsupported",
        gatt_capability="Unsupported",
        bluez="Available",
        permissions="Granted",
    )
    assert bt_unsupported.is_peripheral_supported_for(PlatformKind.WINDOWS) is False
    assert bt_unsupported.is_peripheral_supported_for(PlatformKind.LINUX) is False


def test_platform_kind_from_system_resolution() -> None:
    """_platform_kind_from_system correctly resolves OS families from distro names."""
    assert (
        _platform_kind_from_system(
            SystemCapabilities("Linux", "Ubuntu 24.04", "x86_64", "Python")
        )
        is PlatformKind.LINUX
    )
    assert (
        _platform_kind_from_system(
            SystemCapabilities("Ubuntu", "Ubuntu 24.04", "x86_64", "Python")
        )
        is PlatformKind.LINUX
    )
    assert (
        _platform_kind_from_system(
            SystemCapabilities("Debian GNU/Linux", "Debian 12", "x86_64", "Python")
        )
        is PlatformKind.LINUX
    )
    assert (
        _platform_kind_from_system(
            SystemCapabilities("Arch Linux", "Rolling", "x86_64", "Python")
        )
        is PlatformKind.LINUX
    )
    assert (
        _platform_kind_from_system(
            SystemCapabilities("Windows", "Windows 11", "x86_64", "Python")
        )
        is PlatformKind.WINDOWS
    )
    assert (
        _platform_kind_from_system(
            SystemCapabilities("Win32", "Windows 10", "x86_64", "Python")
        )
        is PlatformKind.WINDOWS
    )
    assert (
        _platform_kind_from_system(
            SystemCapabilities("Darwin", "macOS 14", "arm64", "Python")
        )
        is PlatformKind.OTHER
    )
    assert _platform_kind_from_system(None) in (
        PlatformKind.LINUX,
        PlatformKind.WINDOWS,
        PlatformKind.OTHER,
    )


def test_configure_viable_transports_linux_distros() -> None:
    """Linux distributions with peripheral-capable hardware evaluate to Central only."""
    bt = BluetoothCapabilities(
        adapter="hci0 (Intel)",
        ble_central="Available",
        ble_peripheral="Available",
        gatt_capability="Available",
        bluez="Available",
        permissions="Granted",
    )
    net = NetworkCapabilities(
        wifi="Connected",
        ethernet="Not detected",
        ipv4="192.168.1.10",
        ipv6="Not detected",
    )
    lan = LanCapabilities("Available (Port 24024)", "Available (Port 24025)")

    for distro in ("Ubuntu", "Debian", "Arch Linux", "Fedora"):
        sys_cap = SystemCapabilities(distro, f"{distro} LTS", "x86_64", "CPython 3.12")
        cfg = configure_viable_transports(sys_cap, bt, net, lan)
        assert cfg.ble == "Enabled (Central + Peripheral)"
        assert cfg.lan == "Enabled"

    bt_unsupported = BluetoothCapabilities(
        adapter="hci0 (Intel)",
        ble_central="Available",
        ble_peripheral="Unsupported",
        gatt_capability="Unsupported",
        bluez="Available",
        permissions="Granted",
    )
    for distro in ("Ubuntu", "Debian", "Arch Linux", "Fedora"):
        sys_cap = SystemCapabilities(distro, f"{distro} LTS", "x86_64", "CPython 3.12")
        cfg = configure_viable_transports(sys_cap, bt_unsupported, net, lan)
        assert cfg.ble == "Enabled (Central Mode only)"
        assert cfg.lan == "Enabled"


def test_configure_viable_transports_permission_denied() -> None:
    """Permission denied conditions are properly classified."""
    system = SystemCapabilities("Linux", "Ubuntu 24.04", "x86_64", "CPython 3.12")
    bt = BluetoothCapabilities(
        adapter="hci0",
        ble_central="Permission denied",
        ble_peripheral="Permission denied",
        gatt_capability="Permission denied",
        bluez="Permission denied",
        permissions="Permission denied",
    )
    net = NetworkCapabilities(
        wifi="Available (wlan0)",
        ethernet="Available (eth0)",
        ipv4="192.168.1.5",
        ipv6="Not detected",
    )
    lan = LanCapabilities(
        udp_discovery="Permission denied",
        tcp_transport="Permission denied",
    )

    cfg = configure_viable_transports(system, bt, net, lan)
    assert cfg.ble == "Permission denied"
    assert cfg.lan == "Unavailable"
    assert cfg.recommended_transport == "offline"
    assert "Offline" in cfg.status


def test_configure_viable_transports_completely_offline() -> None:
    """Neither Bluetooth nor LAN available yields offline mode."""
    system = SystemCapabilities("Linux", "Arch Linux", "x86_64", "CPython 3.12")
    bt = BluetoothCapabilities(
        adapter="Not detected",
        ble_central="Not detected",
        ble_peripheral="Not detected",
        gatt_capability="Not detected",
        bluez="Not running",
        permissions="Unknown",
    )
    net = NetworkCapabilities(
        wifi="Not detected",
        ethernet="Not detected",
        ipv4="Not detected",
        ipv6="Not detected",
    )
    lan = LanCapabilities(
        udp_discovery="Failed (unreachable)",
        tcp_transport="Failed (unreachable)",
    )

    cfg = configure_viable_transports(system, bt, net, lan)
    assert cfg.ble == "Unavailable"
    assert cfg.lan == "Unavailable"
    assert cfg.fallback == "Disabled"
    assert cfg.recommended_transport == "offline"
    assert "Offline: No networking transports available." in cfg.status


def test_format_configure_report() -> None:
    """format_configure_report formats all required sections and diagnostic badges."""
    report = SystemReport(
        system=SystemCapabilities(
            "Linux", "Ubuntu 24.04 LTS", "x86_64", "CPython 3.12"
        ),
        bluetooth=BluetoothCapabilities(
            adapter="hci0 (Intel Bluetooth)",
            ble_central="Available",
            ble_peripheral="Available",
            gatt_capability="Available",
            bluez="Available",
            permissions="Granted",
        ),
        network=NetworkCapabilities(
            wifi="Connected (HomeWifi)",
            ethernet="Not detected",
            ipv4="192.168.1.100",
            ipv6="2001:db8::1",
        ),
        lan=LanCapabilities(
            udp_discovery="Available (Port 24024)",
            tcp_transport="Available (Port 24025)",
        ),
        configuration=ConfiguredTransports(
            ble="Enabled",
            lan="Enabled",
            fallback="Enabled",
            status="System ready.",
            recommended_transport="bluetooth",
        ),
    )

    formatted = format_configure_report(report)
    assert "BitChat Configuration" in formatted
    assert "System" in formatted
    assert "✓ Linux" in formatted
    assert "✓ Ubuntu 24.04 LTS" in formatted
    assert "✓ x86_64" in formatted
    assert "Bluetooth" in formatted
    assert "✓ hci0 (Intel Bluetooth)" in formatted
    assert "Network" in formatted
    assert "✓ Connected (HomeWifi)" in formatted
    assert "✕ Not detected" in formatted
    assert "LAN" in formatted
    assert "Configuration" in formatted
    assert "System ready." in formatted


def test_configure_network_summary_uses_shared_snapshot() -> None:
    snapshot = NetworkInfo(
        status="Connected",
        interface="Wi-Fi",
        ssid="Example Wi-Fi",
        local_ip="192.0.2.10",
        interface_name="Wi-Fi",
        interface_description="Wireless Adapter",
        ipv4_addresses=("192.0.2.10",),
        ipv6_addresses=("2001:db8::10",),
        subnet_prefixes=(24, 64),
        default_gateway="192.0.2.1",
        dns_servers=("192.0.2.53",),
        connection_name="Example Wi-Fi",
        collected_at=100.0,
        provider_backend="mock Windows provider",
    )
    expected_network = detect_network_info(snapshot)
    with (
        patch(
            "bitchat.platform.capabilities.detect_system_info",
            return_value=SystemCapabilities(
                "Windows", "Windows 11", "x86_64", "CPython 3.14"
            ),
        ),
        patch(
            "bitchat.platform.capabilities.detect_bluetooth_info",
            new=AsyncMock(
                return_value=BluetoothCapabilities(
                    "Available",
                    "Available",
                    "Unsupported",
                    "Unsupported",
                    "Not applicable",
                    "Granted",
                )
            ),
        ),
        patch(
            "bitchat.platform.capabilities.get_network_info_snapshot",
            new=AsyncMock(return_value=snapshot),
        ),
        patch(
            "bitchat.platform.capabilities.detect_lan_capabilities",
            return_value=LanCapabilities("Available", "Available"),
        ),
    ):
        report = asyncio.run(detect_system_capabilities())

    formatted = format_configure_report(report)
    assert report.network_snapshot is snapshot
    assert report.network == expected_network
    assert "Example Wi-Fi" in formatted
    assert "Wi-Fi" in formatted
    assert "192.0.2.10" in formatted
    assert "2001:db8::10" in formatted
    assert "192.0.2.1" in formatted
    assert "192.0.2.53" in formatted


def test_application_cli_configure_dispatch() -> None:
    """Application CLI dispatches /configure and outputs formatted report."""
    stdout_buf = io.StringIO()
    app = Application(stdout=stdout_buf)
    cmd = CommandParser().parse("/configure")

    should_continue = app.dispatch(cmd)
    assert should_continue is True
    output = stdout_buf.getvalue()
    assert "BitChat Configuration" in output
    assert "System" in output
    assert "Bluetooth" in output
    assert "Network" in output
    assert "LAN" in output
    assert "Configuration" in output
