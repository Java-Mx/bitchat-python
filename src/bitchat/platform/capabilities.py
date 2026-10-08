"""System capability discovery, hardware diagnostics, and transport viability."""

from __future__ import annotations

import contextlib
import errno
import logging
import platform
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bitchat.network.adapter import get_local_ip, get_wifi_ssid_and_state

logger = logging.getLogger(__name__)

DEFAULT_UDP_PORT = 24024
DEFAULT_TCP_PORT = 24025


@dataclass(frozen=True)
class SystemCapabilities:
    """Operating system and runtime environment capabilities."""

    os_name: str
    distribution: str
    architecture: str
    runtime: str


@dataclass(frozen=True)
class BluetoothCapabilities:
    """Bluetooth hardware, BlueZ, and BLE role capabilities."""

    adapter: str
    ble_central: str
    ble_peripheral: str
    gatt_capability: str
    bluez: str
    permissions: str

    @property
    def is_central_available(self) -> bool:
        return "Available" in self.ble_central

    @property
    def is_peripheral_available(self) -> bool:
        return "Available" in self.ble_peripheral


@dataclass(frozen=True)
class NetworkCapabilities:
    """Host network interfaces and address configuration."""

    wifi: str
    ethernet: str
    ipv4: str
    ipv6: str


@dataclass(frozen=True)
class LanCapabilities:
    """Local Area Network socket binding and discovery capabilities."""

    udp_discovery: str
    tcp_transport: str


@dataclass(frozen=True)
class ConfiguredTransports:
    """Evaluated transport configuration and operational mode."""

    ble: str
    lan: str
    fallback: str
    status: str
    recommended_transport: str


@dataclass(frozen=True)
class SystemReport:
    """Comprehensive system diagnostics report."""

    system: SystemCapabilities
    bluetooth: BluetoothCapabilities
    network: NetworkCapabilities
    lan: LanCapabilities
    configuration: ConfiguredTransports


# ---------------------------------------------------------------------------
# Hardware & Environment Detection Helpers
# ---------------------------------------------------------------------------


def detect_system_info() -> SystemCapabilities:
    """Detect operating system, distribution name, architecture, and runtime."""
    os_name = platform.system()
    arch = platform.machine() or "unknown"
    distro = "Unknown"

    if os_name == "Linux":
        # 1. freedesktop_os_release (Python 3.10+)
        if hasattr(platform, "freedesktop_os_release"):
            with contextlib.suppress(OSError, AttributeError):
                info = platform.freedesktop_os_release()
                distro = info.get("PRETTY_NAME") or info.get("NAME", "Linux")

        # 2. Fallback: parse /etc/os-release or /usr/lib/os-release
        if distro == "Unknown":
            for release_path in (
                Path("/etc/os-release"),
                Path("/usr/lib/os-release"),
            ):
                if release_path.is_file():
                    with contextlib.suppress(Exception):
                        content = release_path.read_text(encoding="utf-8")
                        m = re.search(
                            r'^(?:PRETTY_NAME|NAME)="?([^"\n]+)"?',
                            content,
                            re.MULTILINE,
                        )
                        if m:
                            distro = m.group(1).strip()
                            break

        if distro == "Unknown":
            distro = "Linux (generic)"

    elif os_name == "Windows":
        distro = f"Windows {platform.release()}"
    elif os_name == "Darwin":
        mac_ver = platform.mac_ver()[0]
        distro = f"macOS {mac_ver}" if mac_ver else "macOS"
    else:
        distro = platform.platform()

    is_frozen = getattr(sys, "frozen", False)
    frozen_tag = " (standalone)" if is_frozen else ""
    py_ver = (
        f"{platform.python_implementation()} {platform.python_version()}{frozen_tag}"
    )

    return SystemCapabilities(
        os_name=os_name,
        distribution=distro,
        architecture=arch,
        runtime=py_ver,
    )


async def detect_bluetooth_info() -> BluetoothCapabilities:
    """Detect Bluetooth adapter, BlueZ, BLE roles, and permissions."""
    os_name = platform.system()

    if os_name == "Linux":
        return await _detect_linux_bluetooth()
    elif os_name == "Windows":
        return await _detect_windows_bluetooth()
    else:
        return _detect_generic_bluetooth()


async def _detect_linux_bluetooth() -> BluetoothCapabilities:
    """Query Linux BlueZ and D-Bus interfaces for Bluetooth state."""
    adapter_name = "Not detected"
    ble_central = "Not detected"
    ble_peripheral = "Not detected"
    gatt_cap = "Not detected"
    bluez_state = "Not detected"
    permissions = "Unknown"

    # 1. Check sysfs for bluetooth devices (/sys/class/bluetooth/hci*)
    hci_dirs: list[Path] = []
    sysfs_bt = Path("/sys/class/bluetooth")
    if sysfs_bt.is_dir():
        with contextlib.suppress(Exception):
            hci_dirs = sorted(sysfs_bt.glob("hci*"))

    has_hardware = bool(hci_dirs)
    if has_hardware:
        primary_hci = hci_dirs[0].name
        adapter_name = primary_hci

    # 2. Check D-Bus system bus for org.bluez
    try:
        from dbus_fast import (  # pyright: ignore[reportMissingImports]
            BusType,
            Message,
            MessageType,
        )
        from dbus_fast.aio import MessageBus  # pyright: ignore[reportMissingImports]

        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        try:
            # Query NameOwner for org.bluez
            reply = await bus.call(
                Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="GetNameOwner",
                    signature="s",
                    body=["org.bluez"],
                )
            )
            if reply.message_type == MessageType.METHOD_RETURN:
                bluez_state = "Available"
                permissions = "Granted"

                # Query managed objects for adapter capabilities
                obj_reply = await bus.call(
                    Message(
                        destination="org.bluez",
                        path="/",
                        interface="org.freedesktop.DBus.ObjectManager",
                        member="GetManagedObjects",
                    )
                )
                if (
                    obj_reply.message_type == MessageType.METHOD_RETURN
                    and obj_reply.body
                ):
                    managed = obj_reply.body[0]

                    def _extract(props: dict[str, Any], key: str, default: Any) -> Any:
                        val = props.get(key)
                        if val is None:
                            return default
                        return getattr(val, "value", val)

                    # Look for adapter objects
                    for path, ifaces in managed.items():
                        if "org.bluez.Adapter1" in ifaces:
                            props = ifaces["org.bluez.Adapter1"]
                            alias = str(_extract(props, "Alias", ""))
                            name = str(_extract(props, "Name", ""))
                            adapter_name = alias or name or str(path).split("/")[-1]
                            powered = bool(_extract(props, "Powered", True))

                            if not powered:
                                ble_central = "Disabled (Radio Off)"
                                ble_peripheral = "Disabled (Radio Off)"
                                gatt_cap = "Disabled (Radio Off)"
                            else:
                                ble_central = "Available"
                                if "org.bluez.LEAdvertisingManager1" in ifaces:
                                    ble_peripheral = "Available"
                                else:
                                    ble_peripheral = "Unsupported"

                                if "org.bluez.GattManager1" in ifaces:
                                    gatt_cap = "Available"
                                else:
                                    gatt_cap = "Unsupported"
                            break
            else:
                bluez_state = "Not running"
        finally:
            with contextlib.suppress(Exception):
                bus.disconnect()

    except PermissionError:
        bluez_state = "Permission denied"
        permissions = "Permission denied"
    except Exception as e:
        logger.debug("D-Bus check for BlueZ failed: %s", e)
        if "org.freedesktop.DBus.Error.AccessDenied" in str(e):
            bluez_state = "Permission denied"
            permissions = "Permission denied"
        elif "org.freedesktop.DBus.Error.ServiceUnknown" in str(e):
            bluez_state = "Not running"
        else:
            bluez_state = "Not running"

    # Fallback if D-Bus inspection didn't resolve capabilities
    if has_hardware and ble_central == "Not detected":
        adapter_name = hci_dirs[0].name
        if bluez_state == "Available":
            ble_central = "Available"
            ble_peripheral = "Unsupported"
            gatt_cap = "Unsupported"
            permissions = "Granted"
        elif bluez_state == "Permission denied":
            ble_central = "Permission denied"
            ble_peripheral = "Permission denied"
            gatt_cap = "Permission denied"
        else:
            ble_central = "Unavailable (BlueZ not running)"
            ble_peripheral = "Unavailable (BlueZ not running)"
            gatt_cap = "Unavailable (BlueZ not running)"

    return BluetoothCapabilities(
        adapter=adapter_name,
        ble_central=ble_central,
        ble_peripheral=ble_peripheral,
        gatt_capability=gatt_cap,
        bluez=bluez_state,
        permissions=permissions,
    )


async def _detect_windows_bluetooth() -> BluetoothCapabilities:
    """Query Windows WinRT adapter information."""
    try:
        from winrt.windows.devices.bluetooth import BluetoothAdapter
        from winrt.windows.devices.radios import RadioState

        adapter = await BluetoothAdapter.get_default_async()
        if adapter is None:
            return BluetoothCapabilities(
                adapter="Not detected",
                ble_central="Not detected",
                ble_peripheral="Not detected",
                gatt_capability="Not detected",
                bluez="Not applicable (WinRT)",
                permissions="Granted",
            )

        radio = await adapter.get_radio_async()
        radio_name = (
            getattr(radio, "name", "Windows Bluetooth")
            if radio
            else "Windows Bluetooth"
        )
        is_on = radio is not None and getattr(radio, "state", None) == RadioState.ON

        is_central = bool(getattr(adapter, "is_central_role_supported", False))
        is_periph = bool(getattr(adapter, "is_peripheral_role_supported", False))

        if not is_on:
            central_str = "Disabled (Radio Off)"
            periph_str = "Disabled (Radio Off)"
            gatt_str = "Disabled (Radio Off)"
        else:
            central_str = "Available" if is_central else "Unsupported"
            periph_str = "Available" if is_periph else "Unsupported"
            gatt_str = "Available" if is_periph else "Unsupported"

        return BluetoothCapabilities(
            adapter=radio_name,
            ble_central=central_str,
            ble_peripheral=periph_str,
            gatt_capability=gatt_str,
            bluez="Not applicable (WinRT)",
            permissions="Granted",
        )
    except Exception as e:
        logger.debug("Windows Bluetooth check failed: %s", e)
        return BluetoothCapabilities(
            adapter="Not detected",
            ble_central="Not detected",
            ble_peripheral="Not detected",
            gatt_capability="Not detected",
            bluez="Not applicable (WinRT)",
            permissions="Granted",
        )


def _detect_generic_bluetooth() -> BluetoothCapabilities:
    """Generic fallback Bluetooth detection for other platforms."""
    return BluetoothCapabilities(
        adapter="Generic BLE Adapter",
        ble_central="Available",
        ble_peripheral="Unsupported",
        gatt_capability="Unsupported",
        bluez="Not applicable",
        permissions="Granted",
    )


def detect_network_info() -> NetworkCapabilities:
    """Detect Wi-Fi, Ethernet, IPv4, and IPv6 networking capabilities."""
    os_name = platform.system()
    ipv4 = get_local_ip() or "Not detected"
    ipv6 = _detect_ipv6_address()

    wifi_status = "Not detected"
    eth_status = "Not detected"

    if os_name == "Linux":
        wifi_status, eth_status = _detect_linux_interfaces()
    elif os_name == "Windows":
        ssid, wifi_state = get_wifi_ssid_and_state()
        if wifi_state == "connected" and ssid:
            wifi_status = f"Connected ({ssid})"
            eth_status = "Available"
        elif ipv4 != "Not detected":
            wifi_status = "Disconnected"
            eth_status = "Connected"
        else:
            wifi_status = "Disconnected"
            eth_status = "Disconnected"
    else:
        if ipv4 != "Not detected":
            eth_status = "Connected"
            wifi_status = "Available"

    return NetworkCapabilities(
        wifi=wifi_status,
        ethernet=eth_status,
        ipv4=ipv4,
        ipv6=ipv6,
    )


def _detect_linux_interfaces() -> tuple[str, str]:
    """Scan /sys/class/net on Linux for Wi-Fi and Ethernet status."""
    wifi_str = "Not detected"
    eth_str = "Not detected"
    net_path = Path("/sys/class/net")

    if not net_path.is_dir():
        return wifi_str, eth_str

    for iface_dir in net_path.iterdir():
        name = iface_dir.name
        if name in ("lo",) or name.startswith(("docker", "veth", "br-", "virbr")):
            continue

        operstate = "unknown"
        oper_file = iface_dir / "operstate"
        if oper_file.is_file():
            with contextlib.suppress(Exception):
                operstate = oper_file.read_text(encoding="utf-8").strip()

        # Check Wi-Fi
        if (iface_dir / "wireless").is_dir():
            ssid = _detect_linux_wifi_ssid(name)
            if operstate == "up":
                if ssid:
                    wifi_str = f"Connected ({ssid})"
                elif not wifi_str.startswith("Connected"):
                    wifi_str = f"Available ({name})"
            elif wifi_str == "Not detected":
                wifi_str = f"Available ({name}, {operstate})"

        # Check Ethernet: type 1 is ARPHRD_ETHER
        type_file = iface_dir / "type"
        if type_file.is_file() and not (iface_dir / "wireless").is_dir():
            with contextlib.suppress(Exception):
                if type_file.read_text(encoding="utf-8").strip() == "1":
                    if operstate == "up":
                        eth_str = f"Connected ({name})"
                    elif eth_str == "Not detected":
                        eth_str = f"Available ({name}, {operstate})"

    return wifi_str, eth_str


def _detect_linux_wifi_ssid(iface: str) -> str | None:
    """Attempt detection of active Wi-Fi SSID on Linux."""
    # 1. nmcli
    if shutil.which("nmcli"):
        with contextlib.suppress(Exception):
            res = subprocess.run(
                ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
            for line in res.stdout.splitlines():
                if line.startswith("yes:"):
                    return line.split(":", 1)[1].strip()

    # 2. iwgetid
    if shutil.which("iwgetid"):
        with contextlib.suppress(Exception):
            res = subprocess.run(
                ["iwgetid", iface, "-r"],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()

    return None


def _detect_ipv6_address() -> str:
    """Test IPv6 connectivity and return active address or status."""
    if not socket.has_ipv6:
        return "Disabled"

    # Route probe to public IPv6 DNS
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as s:
            s.connect(("2001:4860:4860::8888", 80))
            addr = s.getsockname()[0]
            if addr and not addr.startswith("::1"):
                return addr
    except Exception:
        pass

    # Hostname probe
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET6):
            cand = info[4][0]
            if isinstance(cand, str) and not cand.startswith("::1"):
                return cand
    except Exception:
        pass

    return "Not detected"


def detect_lan_capabilities(
    udp_port: int = DEFAULT_UDP_PORT,
    tcp_port: int = DEFAULT_TCP_PORT,
) -> LanCapabilities:
    """Validate UDP broadcast binding and TCP transport listening."""
    udp_status = "Available"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", udp_port))
            udp_status = f"Available (Port {udp_port})"
    except PermissionError:
        udp_status = "Permission denied"
    except OSError as e:
        if getattr(e, "errno", None) in (errno.EADDRINUSE, 10048):
            udp_status = f"Active (Port {udp_port})"
        else:
            udp_status = f"Failed ({e})"

    tcp_status = "Available"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", tcp_port))
            tcp_status = f"Available (Port {tcp_port})"
    except PermissionError:
        tcp_status = "Permission denied"
    except OSError as e:
        if getattr(e, "errno", None) in (errno.EADDRINUSE, 10048):
            tcp_status = f"Active (Port {tcp_port})"
        else:
            tcp_status = f"Failed ({e})"

    return LanCapabilities(
        udp_discovery=udp_status,
        tcp_transport=tcp_status,
    )


def configure_viable_transports(
    system: SystemCapabilities,
    bluetooth: BluetoothCapabilities,
    network: NetworkCapabilities,
    lan: LanCapabilities,
) -> ConfiguredTransports:
    """Evaluate detected capabilities and select viable transports (Section 10)."""
    # Evaluate BLE viability
    ble_adapter_ok = bluetooth.adapter != "Not detected"
    ble_central_ok = bluetooth.is_central_available
    ble_periph_ok = bluetooth.is_peripheral_available
    ble_perm_ok = bluetooth.permissions != "Permission denied"

    ble_viable = ble_adapter_ok and ble_central_ok and ble_perm_ok

    if ble_viable and ble_periph_ok:
        ble_mode = "Enabled (Central + Peripheral)"
    elif ble_viable:
        ble_mode = "Enabled (Central Mode only)"
    elif "Disabled" in bluetooth.ble_central:
        ble_mode = "Disabled (Radio Off)"
    elif bluetooth.permissions == "Permission denied":
        ble_mode = "Permission denied"
    else:
        ble_mode = "Unavailable"

    # Evaluate LAN viability
    lan_has_ip = network.ipv4 != "Not detected"
    lan_udp_ok = (
        "Permission denied" not in lan.udp_discovery
        and not lan.udp_discovery.startswith("Failed")
    )
    lan_tcp_ok = (
        "Permission denied" not in lan.tcp_transport
        and not lan.tcp_transport.startswith("Failed")
    )
    lan_viable = lan_has_ip and lan_udp_ok and lan_tcp_ok

    lan_mode = "Enabled" if lan_viable else "Unavailable"

    # Fallback and operational status determination
    if ble_viable and lan_viable:
        fallback = "Enabled"
        rec_trans = "bluetooth"
        status = "System ready."
    elif ble_viable:
        fallback = "Disabled (BLE only)"
        rec_trans = "bluetooth"
        status = "System ready (BLE only)."
    elif lan_viable:
        fallback = "Disabled (LAN only)"
        rec_trans = "lan"
        status = "System ready (LAN only)."
    else:
        fallback = "Disabled"
        rec_trans = "offline"
        status = "Offline: No networking transports available."

    return ConfiguredTransports(
        ble=ble_mode,
        lan=lan_mode,
        fallback=fallback,
        status=status,
        recommended_transport=rec_trans,
    )


async def detect_system_capabilities() -> SystemReport:
    """Run full system, Bluetooth, and LAN diagnostic detection."""
    system = detect_system_info()
    bluetooth = await detect_bluetooth_info()
    network = detect_network_info()
    lan = detect_lan_capabilities()
    config = configure_viable_transports(system, bluetooth, network, lan)

    return SystemReport(
        system=system,
        bluetooth=bluetooth,
        network=network,
        lan=lan,
        configuration=config,
    )


def format_configure_report(report: SystemReport) -> str:
    """Format diagnostic report matching production /configure CLI/TUI standard."""
    can_unicode = True
    try:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        "✓ ✕ ─".encode(encoding)
    except Exception:
        can_unicode = False

    check_sym = "✓" if can_unicode else "[+]"
    cross_sym = "✕" if can_unicode else "[-]"
    divider = "──────────────────────" if can_unicode else "----------------------"

    def _badge(val: str) -> str:
        # Determine checkmark vs cross/warning icon
        lower = val.lower()
        if (
            any(
                x in lower
                for x in (
                    "available",
                    "enabled",
                    "connected",
                    "granted",
                    "active",
                    "ready",
                    "linux",
                    "windows",
                    "macos",
                )
            )
            and "not" not in lower
        ):
            return f"{check_sym} {val}"
        elif any(
            x in lower
            for x in (
                "unsupported",
                "disabled",
                "permission denied",
                "failed",
                "not detected",
                "unavailable",
                "offline",
            )
        ):
            return f"{cross_sym} {val}"
        return f"{check_sym} {val}"

    sys_sec = report.system
    bt_sec = report.bluetooth
    net_sec = report.network
    lan_sec = report.lan
    cfg_sec = report.configuration

    lines = [
        "BitChat Configuration",
        divider,
        "",
        "System",
        f"  OS                 {_badge(sys_sec.os_name)}",
        f"  Distribution       {_badge(sys_sec.distribution)}",
        f"  Architecture       {_badge(sys_sec.architecture)}",
        f"  Runtime            {_badge(sys_sec.runtime)}",
        "",
        "Bluetooth",
        f"  Adapter            {_badge(bt_sec.adapter)}",
        f"  BLE Central        {_badge(bt_sec.ble_central)}",
        f"  BLE Peripheral     {_badge(bt_sec.ble_peripheral)}",
        f"  GATT               {_badge(bt_sec.gatt_capability)}",
        f"  BlueZ              {_badge(bt_sec.bluez)}",
        f"  Permissions        {_badge(bt_sec.permissions)}",
        "",
        "Network",
        f"  Wi-Fi              {_badge(net_sec.wifi)}",
        f"  Ethernet           {_badge(net_sec.ethernet)}",
        f"  IPv4               {_badge(net_sec.ipv4)}",
        f"  IPv6               {_badge(net_sec.ipv6)}",
        "",
        "LAN",
        f"  UDP Discovery      {_badge(lan_sec.udp_discovery)}",
        f"  TCP Transport      {_badge(lan_sec.tcp_transport)}",
        "",
        "Configuration",
        f"  BLE                {_badge(cfg_sec.ble)}",
        f"  LAN                {_badge(cfg_sec.lan)}",
        f"  Fallback           {_badge(cfg_sec.fallback)}",
        "",
        f"{cfg_sec.status}",
    ]

    return "\n".join(lines)
