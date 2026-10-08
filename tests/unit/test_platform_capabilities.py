"""Unit tests for platform capability detection and /configure command."""

from __future__ import annotations

import io

from bitchat.app.application import Application
from bitchat.commands.parser import CommandParser, CommandType
from bitchat.platform.capabilities import (
    BluetoothCapabilities,
    ConfiguredTransports,
    LanCapabilities,
    NetworkCapabilities,
    SystemCapabilities,
    SystemReport,
    configure_viable_transports,
    detect_system_info,
    format_configure_report,
)


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


def test_detect_system_info() -> None:
    """detect_system_info retrieves valid OS, distro, arch, and runtime."""
    sys_info = detect_system_info()
    assert isinstance(sys_info.os_name, str) and len(sys_info.os_name) > 0
    assert isinstance(sys_info.distribution, str) and len(sys_info.distribution) > 0
    assert isinstance(sys_info.architecture, str) and len(sys_info.architecture) > 0
    assert isinstance(sys_info.runtime, str) and "Python" in sys_info.runtime


def test_configure_viable_transports_both_available() -> None:
    """Both BLE (Central + Peripheral) and LAN available enables both and fallback."""
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
    """Unavailable LAN configures BLE-only mode."""
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
