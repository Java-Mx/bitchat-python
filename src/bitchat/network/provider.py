"""Cross-platform, read-only operating-system network interface discovery.

The provider intentionally gathers no wireless credentials. Platform commands are
bounded, invoked without a shell, and return only interface, route, address, and
resolver metadata.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from bitchat.network.models import NetworkInfo, NetworkInterfaceInfo

logger = logging.getLogger(__name__)


def discover_network_info() -> NetworkInfo:
    """Return the best available system-network snapshot without requiring root."""
    collection_errors: tuple[str, ...] = ()
    try:
        if sys.platform == "win32":
            interfaces, route_name = _discover_windows()
        elif sys.platform.startswith("linux"):
            interfaces, route_name = _discover_linux()
        else:
            interfaces, route_name = _discover_fallback()
    except Exception as exc:
        logger.debug("Operating-system network discovery failed: %s", exc)
        interfaces, route_name = (), ""
        collection_errors = (f"Interface discovery failed: {exc}",)

    # 1. Prefer default route interface ONLY if UP/Connected with address/SSID
    selected = next(
        (
            item
            for item in interfaces
            if item.name == route_name
            and item.operational_state.lower() in {"up", "connected"}
            and (
                _has_usable_address(item.ipv4_addresses)
                or _has_usable_address(item.ipv6_addresses)
                or bool(item.ssid)
            )
        ),
        None,
    )
    # 2. Search for an operational physical interface (Wi-Fi / Ethernet first)
    if selected is None:
        primary_candidates = [
            item
            for item in interfaces
            if item.operational_state.lower() in {"up", "connected"}
            and item.kind in {"Wi-Fi", "Ethernet"}
            and (
                _has_usable_address(item.ipv4_addresses)
                or _has_usable_address(item.ipv6_addresses)
                or bool(item.ssid)
            )
            and not any(
                v in (item.name + " " + item.description).lower()
                for v in (
                    "virtual",
                    "vethernet",
                    "wsl",
                    "vmware",
                    "virtualbox",
                    "tap-",
                    "tun-",
                    "tailscale",
                    "zerotier",
                )
            )
        ]
        if primary_candidates:
            selected = primary_candidates[0]
        else:
            # 3. Fallback to any operational non-loopback interface
            selected = next(
                (
                    item
                    for item in interfaces
                    if item.operational_state.lower() in {"up", "connected"}
                    and (
                        _has_usable_address(item.ipv4_addresses)
                        or _has_usable_address(item.ipv6_addresses)
                        or bool(item.ssid)
                    )
                ),
                None,
            )

    is_operational = selected is not None and selected.operational_state.lower() in {
        "up",
        "connected",
    }
    has_address = selected is not None and (
        _has_usable_address(selected.ipv4_addresses)
        or _has_usable_address(selected.ipv6_addresses)
        or bool(selected.ssid)
    )
    is_virtual_only = bool(
        selected is not None
        and any(
            v in (selected.name + " " + selected.description).lower()
            for v in (
                "virtual",
                "vethernet",
                "wsl",
                "vmware",
                "virtualbox",
                "tap-",
                "tun-",
                "tailscale",
                "zerotier",
                "hyper-v",
                "host-only",
            )
        )
        and not selected.gateways
        and selected.name != route_name
        and not getattr(selected, "default_route", False)
    )
    usable = is_operational and has_address and not is_virtual_only

    if usable and selected:
        status = "Connected"
    elif selected and is_operational and not is_virtual_only:
        status = "No IP Assigned"
    elif any(
        item.operational_state.lower() in {"up", "connected"} for item in interfaces
    ):
        status = "Disconnected"
    else:
        status = "Disabled" if interfaces else "Unavailable"

    ipv4 = selected.ipv4_addresses if selected else ()
    ipv6 = selected.ipv6_addresses if selected else ()
    local_ip = _first_usable(ipv4) or _first_usable(ipv6)
    ssid = selected.ssid if selected and selected.ssid else "Unavailable"
    connection_type = selected.kind if selected else "Unavailable"
    gateways = selected.gateways if selected else ()
    dns = selected.dns_servers if selected else ()
    prefixes = selected.subnet_prefixes if selected else ()
    connection_name = None
    if selected:
        connection_name = selected.connection_name or (
            selected.ssid if selected.kind == "Wi-Fi" else None
        )
    if not selected:
        network_name_reason = "No active default-route interface was found."
    elif selected.kind == "Wi-Fi" and not selected.ssid:
        network_name_reason = (
            "Wi-Fi SSID unavailable; the operating system did not report it."
        )
    elif selected.kind == "Ethernet" and not connection_name:
        network_name_reason = (
            "Ethernet is connected, but the operating system reported no profile name."
        )
    elif not connection_name:
        network_name_reason = "The operating system did not report a connection name."
    else:
        network_name_reason = None

    return NetworkInfo(
        status=status,
        interface=connection_type,
        ssid=ssid,
        local_ip=local_ip,
        interface_name=selected.name if selected else "Unavailable",
        interface_state=selected.operational_state if selected else "Unknown",
        ipv4_addresses=ipv4,
        ipv6_addresses=ipv6,
        subnet_prefixes=prefixes,
        default_gateway=gateways[0] if gateways else "Unavailable",
        dns_servers=dns,
        default_route_interface=route_name or "Unavailable",
        connection_name=connection_name or "Unavailable",
        network_name_reason=network_name_reason,
        interface_description=(
            selected.description or "Not exposed by this platform"
            if selected
            else "Unavailable"
        ),
        interface_id=selected.interface_id if selected else None,
        interface_index=selected.interface_index if selected else None,
        signal_strength_percent=(
            selected.signal_strength_percent if selected else None
        ),
        signal_strength_dbm=selected.signal_strength_dbm if selected else None,
        interfaces=interfaces,
        collected_at=time.time(),
        provider_backend=_provider_backend(),
        field_availability=(
            ("connection_name", "available" if connection_name else "unavailable"),
            ("ssid", "available" if selected and selected.ssid else "unavailable"),
            ("interface", "available" if selected else "unavailable"),
            ("ipv4", "available" if ipv4 else "unavailable"),
            ("ipv6", "available" if ipv6 else "unavailable"),
            ("gateway", "available" if gateways else "unavailable"),
            ("dns", "available" if dns else "unavailable"),
        ),
        collection_errors=collection_errors,
    )


def _provider_backend() -> str:
    if sys.platform == "win32":
        return "Windows NetAdapter/NetIPConfiguration + WLAN"
    if sys.platform.startswith("linux"):
        tools = "iproute2" if shutil.which("ip") else "sysfs fallback"
        if shutil.which("nmcli"):
            tools += " + NetworkManager"
        if shutil.which("resolvectl"):
            tools += " + systemd-resolved"
        return f"Linux {tools}"
    return "Python socket fallback"


def _has_usable_address(values: tuple[str, ...]) -> bool:
    for value in values:
        try:
            address = ipaddress.ip_address(value.split("/", 1)[0])
        except ValueError:
            continue
        if (
            not address.is_loopback
            and not address.is_unspecified
            and not address.is_link_local
        ):
            return True
    return False


def _first_usable(values: tuple[str, ...]) -> str:
    for value in values:
        address = value.split("/", 1)[0]
        if _has_usable_address((address,)):
            return address
    return ""


def _as_tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,)


def _classify_interface(name: str, description: str = "", raw_kind: str = "") -> str:
    label = f"{name} {description} {raw_kind}".lower()
    if any(part in label for part in ("wi-fi", "wifi", "wireless", "802.11", "wlan")):
        return "Wi-Fi"
    if any(part in label for part in ("ethernet", "802.3", "gigabit", "gbe", "802.3")):
        return "Ethernet"
    return "Other"


def _parse_address(item: Any) -> tuple[str, int | None] | None:
    if not isinstance(item, dict):
        return None
    address = item.get("Address", item.get("IPAddress", item.get("address")))
    prefix = item.get("PrefixLength", item.get("prefixlen", item.get("prefix")))
    if not isinstance(address, str):
        return None
    try:
        parsed = ipaddress.ip_interface(
            f"{address}/{int(prefix)}" if prefix is not None else address
        )
    except (ValueError, TypeError):
        try:
            parsed_address = ipaddress.ip_address(address.split("/", 1)[0])
        except ValueError:
            return None
        return str(parsed_address), None
    return str(parsed.ip), parsed.network.prefixlen


def _windows_ssids() -> dict[str, tuple[str, int | None]]:
    """Read connected Wi-Fi SSIDs and signal only; never stored profiles/secrets."""
    try:
        proc = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode:
        return {}

    result: dict[str, tuple[str, int | None]] = {}
    blocks = re.split(r"(?m)^\s*Name\s*:\s*", proc.stdout)
    for block in blocks[1:]:
        lines = block.splitlines()
        name = lines[0].strip() if lines else ""
        state = re.search(r"(?m)^\s*State\s*:\s*(.+)$", block)
        ssid = re.search(r"(?m)^\s*SSID\s*:\s*(.+)$", block)
        signal = re.search(r"(?m)^\s*Signal\s*:\s*(\d+)\s*%", block)
        guid = re.search(r"(?m)^\s*GUID\s*:\s*(.+)$", block)
        if name and state and state.group(1).strip().lower() == "connected" and ssid:
            value = ssid.group(1).strip()
            if value:
                entry = (value, int(signal.group(1)) if signal else None)
                result[f"name:{name.lower()}"] = entry
                if guid:
                    result[f"guid:{guid.group(1).strip().strip('{}').lower()}"] = entry
    return result


def _discover_windows() -> tuple[tuple[NetworkInterfaceInfo, ...], str]:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        return _discover_fallback()

    script = r"""
$ipInterfaces = @(Get-NetIPInterface -ErrorAction SilentlyContinue)
$routes = @(Get-NetRoute -ErrorAction SilentlyContinue | Where-Object {
    $_.DestinationPrefix -in @('0.0.0.0/0', '::/0')
} | ForEach-Object {
    $family = if ($_.DestinationPrefix -eq '::/0') { 'IPv6' } else { 'IPv4' }
    $index = $_.InterfaceIndex
    $ipInterface = $ipInterfaces | Where-Object {
        $_.InterfaceIndex -eq $index -and $_.AddressFamily -eq $family
    } |
        Select-Object -First 1
    [pscustomobject]@{
        InterfaceIndex = $index
        RouteMetric = [int]$_.RouteMetric
        InterfaceMetric = [int]$ipInterface.InterfaceMetric
        TotalMetric = [int]$_.RouteMetric + [int]$ipInterface.InterfaceMetric
        NextHop = [string]$_.NextHop
    }
} | Sort-Object TotalMetric)
$profiles = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue)
$rows = @(foreach ($adapter in (
    [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()
)) {
    $ipProperties = $adapter.GetIPProperties()
    $ipInterface = $ipInterfaces | Where-Object {
        $_.InterfaceAlias -eq $adapter.Name -and $_.AddressFamily -eq 'IPv4'
    } | Select-Object -First 1
    if (-not $ipInterface) {
        $ipInterface = $ipInterfaces | Where-Object {
            $_.InterfaceAlias -eq $adapter.Name -and $_.AddressFamily -eq 'IPv6'
        } | Select-Object -First 1
    }
    $index = if ($ipInterface) { $ipInterface.InterfaceIndex } else { $null }
    $profile = $profiles | Where-Object {
        $_.InterfaceIndex -eq $index
    } | Select-Object -First 1
    $v4 = @($ipProperties.UnicastAddresses | Where-Object {
        $_.Address.AddressFamily -eq 'InterNetwork' -and
            -not $_.Address.IsLoopback
    } | ForEach-Object {
        @{ Address = $_.Address.ToString(); PrefixLength = $_.PrefixLength }
    })
    $v6 = @($ipProperties.UnicastAddresses | Where-Object {
        $_.Address.AddressFamily -eq 'InterNetworkV6' -and
            -not $_.Address.IsLoopback
    } | ForEach-Object {
        @{ Address = $_.Address.ToString(); PrefixLength = $_.PrefixLength }
    })
    $gateway = @($routes | Where-Object {
        $_.InterfaceIndex -eq $index -and
            $_.NextHop -and $_.NextHop -notin @('0.0.0.0', '::')
    } | ForEach-Object { $_.NextHop } | Select-Object -Unique)
    [pscustomobject]@{
        Name = $adapter.Name
        Description = $adapter.Description
        InterfaceGuid = [string]$adapter.Id
        ProfileName = [string]$profile.Name
        Kind = [string]$adapter.NetworkInterfaceType
        Status = [string]$adapter.OperationalStatus
        LinkSpeed = [string]$adapter.Speed
        IPv4 = $v4
        IPv6 = $v6
        Gateways = $gateway
        DNS = @($ipProperties.DnsAddresses | ForEach-Object {
            $_.ToString()
        })
        Index = $index
    }
})
( [pscustomobject]@{
    Interfaces = $rows
    Routes = $routes | Select-Object -First 1 InterfaceIndex
} ) | ConvertTo-Json -Depth 6 -Compress
"""
    try:
        proc = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        if proc.returncode:
            return _discover_fallback()
        payload = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return _discover_fallback()

    if not isinstance(payload, dict):
        return _discover_fallback()
    route = payload.get("Routes")
    route_index = route.get("InterfaceIndex") if isinstance(route, dict) else None
    ssids = _windows_ssids()
    found: list[NetworkInterfaceInfo] = []
    for row in _as_tuple(payload.get("Interfaces")):
        if not isinstance(row, dict):
            continue
        name = str(row.get("Name") or "").strip()
        if not name or name.lower() in {"loopback pseudo-interface 1", "loopback"}:
            continue
        description = str(row.get("Description") or "")
        raw_kind = str(row.get("Kind") or "")
        v4 = tuple(
            parsed[0]
            for raw in _as_tuple(row.get("IPv4"))
            if (parsed := _parse_address(raw))
        )
        v6 = tuple(
            parsed[0]
            for raw in _as_tuple(row.get("IPv6"))
            if (parsed := _parse_address(raw))
        )
        prefixes = tuple(
            parsed[1]
            for raw in (*_as_tuple(row.get("IPv4")), *_as_tuple(row.get("IPv6")))
            if (parsed := _parse_address(raw)) and parsed[1] is not None
        )
        index = row.get("Index")
        interface_guid = str(row.get("InterfaceGuid") or "").strip().strip("{}").lower()
        ssid_info = ssids.get(f"guid:{interface_guid}") or ssids.get(
            f"name:{name.lower()}"
        )
        found.append(
            NetworkInterfaceInfo(
                name=name,
                description=description,
                kind=_classify_interface(name, description, raw_kind),
                operational_state=str(row.get("Status") or "Unknown"),
                ipv4_addresses=v4,
                ipv6_addresses=v6,
                subnet_prefixes=prefixes,
                gateways=tuple(
                    str(value) for value in _as_tuple(row.get("Gateways")) if value
                ),
                dns_servers=tuple(
                    str(value) for value in _as_tuple(row.get("DNS")) if value
                ),
                ssid=ssid_info[0] if ssid_info else None,
                connection_name=str(row.get("ProfileName") or "") or None,
                interface_id=str(row.get("InterfaceGuid") or "") or None,
                interface_index=int(index) if index is not None else None,
                signal_strength_percent=ssid_info[1] if ssid_info else None,
                link_speed=str(row.get("LinkSpeed") or "") or None,
                default_route=(index is not None and str(index) == str(route_index)),
            )
        )
    route_name = next((item.name for item in found if item.default_route), "")
    return tuple(found), route_name


def _discover_linux() -> tuple[tuple[NetworkInterfaceInfo, ...], str]:
    ip_cmd = shutil.which("ip")
    if not ip_cmd:
        return _discover_linux_sysfs()
    try:
        addr_proc = subprocess.run(
            [ip_cmd, "-j", "address", "show"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        route_proc = subprocess.run(
            [ip_cmd, "-j", "route", "show", "default"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        route6_proc = subprocess.run(
            [ip_cmd, "-j", "-6", "route", "show", "default"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if addr_proc.returncode:
            return _discover_linux_sysfs()
        addr_rows = json.loads(addr_proc.stdout or "[]")
        routes = (
            json.loads(route_proc.stdout or "[]") if route_proc.returncode == 0 else []
        )
        routes6 = (
            json.loads(route6_proc.stdout or "[]")
            if route6_proc.returncode == 0
            else []
        )
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return _discover_linux_sysfs()

    default_routes = [route for route in (*routes, *routes6) if isinstance(route, dict)]
    default_routes.sort(key=lambda route: int(route.get("metric", 0)))
    route_name = str(default_routes[0].get("dev") or "") if default_routes else ""
    dns_by_interface = _linux_dns_by_interface()
    profiles = _linux_active_profiles()
    found: list[NetworkInterfaceInfo] = []
    for row in addr_rows if isinstance(addr_rows, list) else []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("ifname") or "")
        if not name or name == "lo":
            continue
        addresses = row.get("addr_info", [])
        v4: list[str] = []
        v6: list[str] = []
        prefixes: list[int] = []
        for address in addresses if isinstance(addresses, list) else []:
            if not isinstance(address, dict):
                continue
            local = address.get("local")
            prefix = address.get("prefixlen")
            if not isinstance(local, str):
                continue
            try:
                parsed = ipaddress.ip_address(local)
                if parsed.is_loopback or parsed.is_unspecified:
                    continue
                (v4 if parsed.version == 4 else v6).append(local)
                if isinstance(prefix, int):
                    prefixes.append(prefix)
            except ValueError:
                continue
        path = Path("/sys/class/net") / name
        is_wireless = (path / "wireless").exists()
        state = str(row.get("operstate") or "Unknown").title()
        ssid, signal_dbm = _linux_wireless_link(name) if is_wireless else (None, None)
        kind = "Wi-Fi" if is_wireless else _classify_interface(name)
        try:
            description = (path / "ifalias").read_text(encoding="utf-8").strip()
        except OSError:
            description = ""
        interface_routes = [
            route for route in default_routes if route.get("dev") == name
        ]
        gateways = tuple(
            str(route.get("gateway"))
            for route in interface_routes
            if route.get("gateway")
        )
        found.append(
            NetworkInterfaceInfo(
                name=name,
                description=description,
                kind=kind,
                operational_state=state,
                ipv4_addresses=tuple(v4),
                ipv6_addresses=tuple(v6),
                subnet_prefixes=tuple(prefixes),
                gateways=gateways,
                dns_servers=dns_by_interface.get(name, _linux_resolver_servers()),
                ssid=ssid,
                connection_name=profiles.get(name),
                interface_index=(
                    int(row["ifindex"]) if isinstance(row.get("ifindex"), int) else None
                ),
                signal_strength_dbm=signal_dbm,
                default_route=name == route_name,
            )
        )
    return tuple(found), route_name


def _linux_active_profiles() -> dict[str, str]:
    """Read active NetworkManager connection labels without triggering a Wi-Fi scan."""
    nmcli = shutil.which("nmcli")
    if not nmcli:
        return {}
    try:
        proc = subprocess.run(
            [
                nmcli,
                "-t",
                "--escape",
                "no",
                "-f",
                "DEVICE,TYPE,STATE,CONNECTION",
                "device",
                "status",
            ],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode:
        return {}
    profiles: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        fields = line.split(":", 3)
        if (
            len(fields) == 4
            and fields[2].lower() == "connected"
            and fields[3] not in {"", "--"}
        ):
            profiles[fields[0]] = fields[3]
    return profiles


def _linux_wireless_link(interface: str) -> tuple[str | None, int | None]:
    """Read the current Wi-Fi link without scanning for nearby networks."""
    iw = shutil.which("iw")
    if iw:
        try:
            proc = subprocess.run(
                [iw, "dev", interface, "link"],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
            if proc.returncode == 0:
                ssid_match = re.search(r"(?m)^\s*SSID:\s*(.+?)\s*$", proc.stdout)
                signal_match = re.search(
                    r"(?m)^\s*signal:\s*(-?\d+)\s*dBm", proc.stdout
                )
                ssid = ssid_match.group(1) if ssid_match else None
                signal = int(signal_match.group(1)) if signal_match else None
                if ssid or signal is not None:
                    return ssid, signal
        except (OSError, subprocess.TimeoutExpired):
            pass

    iwgetid = shutil.which("iwgetid")
    if iwgetid:
        try:
            proc = subprocess.run(
                [iwgetid, interface, "-r"],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip(), None
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None, None


def _linux_dns_by_interface() -> dict[str, tuple[str, ...]]:
    resolvectl = shutil.which("resolvectl")
    if resolvectl:
        try:
            proc = subprocess.run(
                [resolvectl, "dns"],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
            results: dict[str, tuple[str, ...]] = {}
            for line in proc.stdout.splitlines():
                if ":" not in line:
                    continue
                name, values = line.split(":", 1)
                servers = tuple(value for value in values.split() if _is_ip(value))
                if servers:
                    results[name.strip().split(" ")[-1]] = servers
            if results:
                return results
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {}


def _linux_resolver_servers() -> tuple[str, ...]:
    try:
        return tuple(
            match.group(1)
            for line in Path("/etc/resolv.conf")
            .read_text(encoding="utf-8")
            .splitlines()
            if (match := re.match(r"\s*nameserver\s+(\S+)", line))
            and _is_ip(match.group(1))
        )
    except OSError:
        return ()


def _discover_linux_sysfs() -> tuple[tuple[NetworkInterfaceInfo, ...], str]:
    """Best-effort interface/status fallback when iproute2 is unavailable."""
    results: list[NetworkInterfaceInfo] = []
    try:
        names = [
            entry.name
            for entry in Path("/sys/class/net").iterdir()
            if entry.name != "lo"
        ]
    except OSError:
        return _discover_fallback()
    profiles = _linux_active_profiles()
    for name in names:
        interface_path = Path("/sys/class/net") / name
        try:
            state = (
                (interface_path / "operstate")
                .read_text(encoding="utf-8")
                .strip()
                .title()
            )
        except OSError:
            state = "Unknown"
        wireless = (interface_path / "wireless").exists()
        ssid, signal_dbm = _linux_wireless_link(name) if wireless else (None, None)
        results.append(
            NetworkInterfaceInfo(
                name=name,
                description="",
                kind="Wi-Fi" if wireless else _classify_interface(name),
                operational_state=state,
                interface_index=None,
                ssid=ssid,
                connection_name=profiles.get(name),
                signal_strength_dbm=signal_dbm,
                dns_servers=_linux_resolver_servers(),
            )
        )
    return tuple(results), ""


def _discover_fallback() -> tuple[tuple[NetworkInterfaceInfo, ...], str]:
    """Conservative stdlib fallback for unsupported platforms and missing tools."""
    try:
        local_names = {name for _, name in socket.if_nameindex()}
    except (AttributeError, OSError):
        local_names = set()
    try:
        addresses = {
            str(info[4][0])
            for info in socket.getaddrinfo(
                socket.gethostname(), None, type=socket.SOCK_STREAM
            )
            if info[0] in (socket.AF_INET, socket.AF_INET6)
        }
    except OSError:
        addresses = set()
    v4 = tuple(
        sorted(
            addr
            for addr in addresses
            if ":" not in addr and _has_usable_address((addr,))
        )
    )
    v6 = tuple(
        sorted(
            addr for addr in addresses if ":" in addr and _has_usable_address((addr,))
        )
    )
    local_ip = v4 or v6
    if not local_names and not local_ip:
        return (), ""
    name = next(iter(sorted(local_names)), "Local interface")
    item = NetworkInterfaceInfo(
        name=name,
        kind="Other",
        operational_state="Up" if local_ip else "Unknown",
        ipv4_addresses=v4,
        ipv6_addresses=v6,
    )
    return (item,), ""


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False
