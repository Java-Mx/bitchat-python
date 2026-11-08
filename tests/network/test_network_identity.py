from __future__ import annotations

import json
from unittest.mock import MagicMock

from bitchat.network.models import NetworkInfo, NetworkInterfaceInfo
from bitchat.network.provider import (
    _discover_windows,
    _linux_active_profiles,
    _linux_wireless_link,
    _windows_ssids,
    discover_network_info,
)


def test_network_snapshot_uses_all_values_from_default_route_interface(
    monkeypatch,
) -> None:
    route_interface = NetworkInterfaceInfo(
        name="wlan0",
        description="Wireless Adapter",
        kind="Wi-Fi",
        operational_state="Up",
        ipv4_addresses=("192.0.2.10",),
        ipv6_addresses=("2001:db8::10",),
        subnet_prefixes=(24, 64),
        gateways=("192.0.2.1",),
        dns_servers=("192.0.2.53",),
        ssid="Example Wi-Fi",
        connection_name="Example profile",
        interface_id="wlan0-guid",
        signal_strength_dbm=-55,
        default_route=True,
    )
    other_interface = NetworkInterfaceInfo(
        name="eth0",
        kind="Ethernet",
        operational_state="Up",
        ipv4_addresses=("198.51.100.10",),
        gateways=("198.51.100.1",),
    )
    monkeypatch.setattr(
        "bitchat.network.provider._discover_linux",
        lambda: ((route_interface, other_interface), "wlan0"),
    )
    monkeypatch.setattr("bitchat.network.provider.sys.platform", "linux")

    snapshot = discover_network_info()

    assert snapshot.connection_name == "Example profile"
    assert snapshot.interface_name == "wlan0"
    assert snapshot.interface_description == "Wireless Adapter"
    assert snapshot.interface_id == "wlan0-guid"
    assert snapshot.ipv4_addresses == ("192.0.2.10",)
    assert snapshot.default_gateway == "192.0.2.1"
    assert snapshot.dns_servers == ("192.0.2.53",)
    assert snapshot.signal_strength_dbm == -55
    assert snapshot.interfaces == (route_interface, other_interface)


def test_linux_active_profile_lookup_does_not_scan_wifi(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        "bitchat.network.provider.shutil.which",
        lambda name: "/usr/bin/nmcli" if name == "nmcli" else None,
    )

    def run(command, **kwargs):
        calls.append(command)
        return MagicMock(
            returncode=0,
            stdout="wlan0:wifi:connected:Home profile\neth0:ethernet:disconnected:--\n",
        )

    monkeypatch.setattr("bitchat.network.provider.subprocess.run", run)

    profiles = _linux_active_profiles()

    assert profiles == {"wlan0": "Home profile"}
    assert calls[0][-2:] == ["device", "status"]
    assert "wifi" not in calls[0]


def test_linux_wireless_details_read_current_link_without_scanning(
    monkeypatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        "bitchat.network.provider.shutil.which",
        lambda name: "/usr/sbin/iw" if name == "iw" else None,
    )

    def run(command, **kwargs):
        calls.append(command)
        return MagicMock(
            returncode=0,
            stdout="Connected to 00:11:22:33:44:55\n\tSSID: Home Wi-Fi\n\tsignal: -55 dBm\n",
        )

    monkeypatch.setattr("bitchat.network.provider.subprocess.run", run)

    ssid, signal = _linux_wireless_link("wlan0")

    assert (ssid, signal) == ("Home Wi-Fi", -55)
    assert calls == [["/usr/sbin/iw", "dev", "wlan0", "link"]]


def test_windows_ssid_parser_reports_connected_name_and_signal(monkeypatch) -> None:
    monkeypatch.setattr(
        "bitchat.network.provider.subprocess.run",
        lambda *args, **kwargs: MagicMock(
            returncode=0,
            stdout=(
                "Name : Wi-Fi\nGUID : {12345678-1234-1234-1234-123456789abc}\n"
                "State : connected\n"
                "SSID : Example Wi-Fi\nSignal : 82%\n"
            ),
        ),
    )

    assert _windows_ssids() == {
        "name:wi-fi": ("Example Wi-Fi", 82),
        "guid:12345678-1234-1234-1234-123456789abc": ("Example Wi-Fi", 82),
    }


def test_windows_snapshot_joins_ssid_by_guid_and_keeps_virtual_interfaces(
    monkeypatch,
) -> None:
    guid = "12345678-1234-1234-1234-123456789abc"
    payload = {
        "Routes": {"InterfaceIndex": 7},
        "Interfaces": [
            {
                "Name": "ethernet_0",
                "Description": "Intel(R) Wi-Fi Adapter",
                "InterfaceGuid": "{" + guid + "}",
                "ProfileName": "Home Wi-Fi",
                "Kind": "Native 802.11",
                "Status": "Up",
                "Index": 7,
                "IPv4": [{"Address": "192.0.2.10", "PrefixLength": 24}],
                "IPv6": [{"Address": "2001:db8::10", "PrefixLength": 64}],
                "Gateways": ["192.0.2.1"],
                "DNS": ["192.0.2.53"],
            },
            {
                "Name": "VirtualBox Host-Only Network",
                "Description": "VirtualBox Virtual Ethernet Adapter",
                "InterfaceGuid": "{other-guid}",
                "Kind": "802.3",
                "Status": "Up",
                "Index": 19,
                "IPv4": [{"Address": "198.51.100.1", "PrefixLength": 24}],
                "IPv6": [],
                "Gateways": [],
                "DNS": [],
            },
        ],
    }
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == "netsh":
            return MagicMock(
                returncode=0,
                stdout=(
                    f"Name : Wi-Fi\nGUID : {{{guid}}}\nState : connected\n"
                    "SSID : Example Wi-Fi\nSignal : 82%\n"
                ),
            )
        return MagicMock(returncode=0, stdout=json.dumps(payload))

    monkeypatch.setattr(
        "bitchat.network.provider.shutil.which",
        lambda name: "powershell.exe" if name == "powershell.exe" else None,
    )
    monkeypatch.setattr("bitchat.network.provider.subprocess.run", run)

    interfaces, route_name = _discover_windows()

    assert route_name == "ethernet_0"
    assert interfaces[0].kind == "Wi-Fi"
    assert interfaces[0].ssid == "Example Wi-Fi"
    assert interfaces[0].interface_index == 7
    assert interfaces[0].default_route
    assert interfaces[1].ipv4_addresses == ("198.51.100.1",)
    assert not interfaces[1].default_route
    powershell = calls[0][4]
    assert "ConvertTo-Json" in powershell
    assert "InterfaceMetric" in powershell
    assert "TotalMetric" in powershell


def test_shared_snapshot_cache_refreshes_once_and_keeps_os_fields_separate(
    monkeypatch,
) -> None:
    import asyncio

    from bitchat.network.adapter import (
        clear_network_info_snapshot_cache,
        get_network_info_snapshot,
    )

    snapshots = iter(
        (
            NetworkInfo(
                status="Connected",
                interface="Wi-Fi",
                connection_name="Example Wi-Fi",
                listening_port=41235,
                discovery_active=True,
                collected_at=100.0,
            ),
            NetworkInfo(
                status="Connected",
                interface="Ethernet",
                connection_name="Office LAN",
                collected_at=200.0,
            ),
        )
    )
    calls = []

    def detect():
        calls.append(True)
        return next(snapshots)

    monkeypatch.setattr("bitchat.network.adapter.detect_network_info", detect)
    clear_network_info_snapshot_cache()
    try:

        async def collect():
            initial = await get_network_info_snapshot(force=True)
            cached = await get_network_info_snapshot()
            refreshed = await get_network_info_snapshot(force=True)
            return initial, cached, refreshed

        initial, cached, refreshed = asyncio.run(collect())
    finally:
        clear_network_info_snapshot_cache()

    assert len(calls) == 2
    assert initial is cached
    assert initial.listening_port == 0
    assert not initial.discovery_active
    assert refreshed.connection_name == "Office LAN"


def test_telemetry_and_settings_import_the_shared_snapshot_provider() -> None:
    from bitchat.network.adapter import get_network_info_snapshot
    from bitchat.tui.screens import settings, telemetry

    assert settings.get_network_info_snapshot is get_network_info_snapshot
    assert telemetry.get_network_info_snapshot is get_network_info_snapshot
