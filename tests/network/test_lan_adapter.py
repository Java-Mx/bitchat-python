"""Unit tests for network adapter detection, IP discovery,
and Windows Wi-Fi SSID parsing.
"""

from __future__ import annotations

import asyncio
import socket
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bitchat.network.adapter import (
    NetworkAdapterManager,
    detect_network_info,
    get_local_ip,
    get_wifi_ssid_and_state,
)
from bitchat.network.models import NetworkInfo
from bitchat.network.transport import LANTransport


def test_get_local_ip_returns_valid_ipv4() -> None:
    ip = get_local_ip()
    assert isinstance(ip, str)
    parts = ip.split(".")
    assert len(parts) == 4
    for p in parts:
        assert p.isdigit()
        assert 0 <= int(p) <= 255


def test_detect_network_info_real_or_fallback() -> None:
    info = detect_network_info(listening_port=41235)
    assert info.listening_port == 41235
    assert info.status in ("Connected", "Disconnected")
    assert info.interface in (
        "Wi-Fi",
        "Ethernet",
        "Loopback",
        "Other",
        "Unavailable",
    )
    assert isinstance(info.local_ip, str)
    assert len(info.local_ip.split(".")) == 4


def test_detect_network_info_reports_loopback_as_disconnected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bitchat.network.adapter.discover_network_info",
        lambda: NetworkInfo(
            status="Disconnected",
            interface="Unavailable",
            ssid="unavailable",
            local_ip="127.0.0.1",
        ),
    )

    info = detect_network_info()

    assert info.status == "Disconnected"
    assert info.interface == "Unavailable"
    assert not info.is_connected


def test_detect_network_info_reports_active_wifi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bitchat.network.adapter.discover_network_info",
        lambda: NetworkInfo(
            status="Connected",
            interface="Wi-Fi",
            ssid="Home",
            local_ip="192.168.1.40",
        ),
    )

    info = detect_network_info()

    assert info.status == "Connected"
    assert info.interface == "Wi-Fi"
    assert info.local_ip == "192.168.1.40"


@pytest.mark.asyncio
async def test_lan_start_reuses_its_network_probe_for_monitoring() -> None:
    manager = NetworkAdapterManager()
    transport = LANTransport(
        local_peer_id="aabbccdd",
        adapter_manager=manager,
    )
    info = NetworkInfo(
        status="Connected",
        interface="Wi-Fi",
        local_ip="192.0.2.10",
    )
    refresh = AsyncMock(return_value=info)
    start_monitoring = AsyncMock()

    with (
        patch.object(manager, "refresh_async", new=refresh),
        patch.object(manager, "start_monitoring", new=start_monitoring),
        patch.object(manager, "stop_monitoring", new=AsyncMock()),
        patch.object(transport.server, "start", new=AsyncMock()),
        patch.object(transport.server, "stop", new=AsyncMock()),
        patch.object(transport.discovery, "start", new=AsyncMock()),
        patch.object(transport.discovery, "stop", new=AsyncMock()),
    ):
        await transport.start()
        assert refresh.await_count == 1
        start_monitoring.assert_awaited_once_with(
            listening_port=transport.server.bound_port,
            discovery_active=True,
            refresh=False,
        )
        await transport.stop()


def test_fallback_network_discovery_extracts_addresses_from_sockaddrs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bitchat.network.provider import _discover_fallback

    monkeypatch.setattr("socket.if_nameindex", lambda: [(1, "eth0")])
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, 0, 0, "", ("192.0.2.8", 0)),
            (socket.AF_INET6, 0, 0, "", ("2001:db8::8", 0, 0, 0)),
        ],
    )

    interfaces, _ = _discover_fallback()

    assert interfaces[0].ipv4_addresses == ("192.0.2.8",)
    assert interfaces[0].ipv6_addresses == ("2001:db8::8",)


def test_get_wifi_ssid_parsing_connected() -> None:
    mock_output = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    GUID                   : 757c96a4-44b4-4b92-b413-eb895d315ef9
    Physical address       : 12:34:56:78:9a:bc
    Interface type         : Primary
    State                  : connected
    SSID                   : Office_5G
    BSSID                  : 00:11:22:33:44:55
    Network type           : Infrastructure
    Radio type             : 802.11ax
    Authentication         : WPA2-Personal
    Cipher                 : CCMP
    Connection mode        : Auto Connect
"""
    with (
        patch.object(sys, "platform", "win32"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)
        ssid, state = get_wifi_ssid_and_state()
        assert ssid == "Office_5G"
        assert state == "connected"


def test_get_wifi_ssid_parsing_disconnected() -> None:
    mock_output = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    State                  : disconnected
"""
    with (
        patch.object(sys, "platform", "win32"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)
        ssid, state = get_wifi_ssid_and_state()
        assert ssid is None
        assert state == "disconnected"


def test_get_wifi_ssid_parsing_non_windows() -> None:
    with patch.object(sys, "platform", "linux"):
        ssid, state = get_wifi_ssid_and_state()
        assert ssid is None
        assert state is None


@pytest.mark.asyncio
async def test_network_adapter_manager_lifecycle() -> None:
    events: list[str] = []
    manager = NetworkAdapterManager(
        poll_interval=0.1,
        on_network_changed=lambda info: events.append(info.status),
    )
    assert not manager.is_running
    await manager.start()
    assert manager.is_running
    assert manager.current_info is not None

    await asyncio.sleep(0.2)
    await manager.stop()
    assert not manager.is_running


@pytest.mark.asyncio
async def test_network_adapter_manager_reports_changed_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = NetworkInfo(
        status="Connected",
        interface="Ethernet",
        local_ip="192.168.1.10",
    )
    changed = NetworkInfo(
        status="Connected",
        interface="Ethernet",
        local_ip="192.168.1.20",
    )
    snapshots = iter((original, original, changed))
    monkeypatch.setattr(
        "bitchat.network.adapter.detect_network_info",
        lambda **kwargs: next(snapshots),
    )
    events: list[NetworkInfo] = []
    manager = NetworkAdapterManager(
        on_network_changed=events.append,
        poll_interval=0.01,
    )

    await manager.start_monitoring()
    for _ in range(20):
        if events:
            break
        await asyncio.sleep(0.01)
    await manager.stop_monitoring()

    assert events == [changed]
    assert manager.current_info.local_ip == "192.168.1.20"
