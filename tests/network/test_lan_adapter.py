"""Unit tests for network adapter detection, IP discovery,
and Windows Wi-Fi SSID parsing.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from bitchat.network.adapter import (
    NetworkAdapterManager,
    detect_network_info,
    get_local_ip,
    get_wifi_ssid_and_state,
)


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
    assert info.interface in ("Wi-Fi", "Ethernet", "Loopback", "Unavailable")
    assert isinstance(info.local_ip, str)
    assert len(info.local_ip.split(".")) == 4


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
        patch("platform.system", return_value="Windows"),
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
        patch("platform.system", return_value="Windows"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)
        ssid, state = get_wifi_ssid_and_state()
        assert ssid is None
        assert state == "disconnected"


def test_get_wifi_ssid_parsing_non_windows() -> None:
    with patch("platform.system", return_value="Linux"):
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
