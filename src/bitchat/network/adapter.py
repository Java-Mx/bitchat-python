"""Real network adapter, local IPv4 selection, and SSID detection."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import platform
import re
import socket
import subprocess
from typing import TYPE_CHECKING, Any

from bitchat.network.models import NetworkInfo

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


def get_local_ip() -> str:
    """Detect the primary usable IPv4 address on the local network."""
    # Attempt 1: Route probe to arbitrary LAN broadcast address
    for target in (("10.255.255.255", 1), ("192.168.255.255", 1), ("8.8.8.8", 80)):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(target)
                ip = s.getsockname()[0]
                if ip and not ip.startswith("127."):
                    return ip
        except Exception:
            continue

    # Attempt 2: Resolve hostname addresses
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            candidate = info[4][0]
            if isinstance(candidate, str) and not candidate.startswith("127."):
                return candidate
    except Exception:
        pass

    return ""


def get_wifi_ssid_and_state() -> tuple[str | None, str | None]:
    """Retrieve connected Wi-Fi SSID and state on Windows or return (None, None)."""
    if platform.system() != "Windows":
        return None, None

    try:
        proc = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if proc.returncode != 0:
            return None, None

        output = proc.stdout
        ssid_match = re.search(r"^\s*SSID\s*:\s*(.+)$", output, re.MULTILINE)
        state_match = re.search(r"^\s*State\s*:\s*(.+)$", output, re.MULTILINE)

        ssid = ssid_match.group(1).strip() if ssid_match else None
        state = state_match.group(1).strip().lower() if state_match else None
        return ssid, state
    except Exception as e:
        logger.debug("Failed querying netsh wlan interfaces: %s", e)
        return None, None


def detect_network_info(
    listening_port: int = 0, discovery_active: bool = False
) -> NetworkInfo:
    """Inspect the host system and return a truthful NetworkInfo snapshot."""
    local_ip = get_local_ip()
    ssid, wifi_state = get_wifi_ssid_and_state()

    is_loopback = local_ip.startswith("127.") or local_ip in ("0.0.0.0", "")

    if wifi_state == "connected" and ssid:
        status = "Connected"
        interface = "Wi-Fi"
        active_ssid = ssid
    elif not is_loopback:
        status = "Connected"
        interface = "Ethernet"
        active_ssid = "unavailable"
    else:
        status = "Disconnected"
        interface = "Unavailable"
        active_ssid = "unavailable"

    return NetworkInfo(
        status=status,
        interface=interface,
        ssid=active_ssid,
        local_ip=local_ip,
        listening_address="0.0.0.0",
        listening_port=listening_port,
        discovery_active=discovery_active,
    )


class NetworkAdapterManager:
    """Monitors local IP and Wi-Fi interface state transitions."""

    def __init__(
        self,
        on_network_changed: Callable[[NetworkInfo], None] | None = None,
        poll_interval: float = 4.0,
    ) -> None:
        self.on_network_changed = on_network_changed
        self.poll_interval = poll_interval
        self._current_info: NetworkInfo = detect_network_info()
        self._is_monitoring: bool = False
        self._monitor_task: asyncio.Task[Any] | None = None

    @property
    def is_running(self) -> bool:
        return self._is_monitoring

    async def start(
        self, listening_port: int = 0, discovery_active: bool = False
    ) -> None:
        await self.start_monitoring(
            listening_port=listening_port, discovery_active=discovery_active
        )

    async def stop(self) -> None:
        await self.stop_monitoring()

    @property
    def current_info(self) -> NetworkInfo:
        return self._current_info

    def refresh(
        self, listening_port: int = 0, discovery_active: bool = False
    ) -> NetworkInfo:
        """Query host for fresh network information synchronously."""
        self._current_info = detect_network_info(
            listening_port=listening_port, discovery_active=discovery_active
        )
        return self._current_info

    async def start_monitoring(
        self, listening_port: int = 0, discovery_active: bool = False
    ) -> None:
        """Start background loop monitoring for IP and interface transitions."""
        if self._is_monitoring:
            return
        self._is_monitoring = True
        self.refresh(listening_port=listening_port, discovery_active=discovery_active)
        self._monitor_task = asyncio.create_task(self._poll_loop())

    async def stop_monitoring(self) -> None:
        """Stop background network monitoring."""
        self._is_monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task
            self._monitor_task = None

    async def _poll_loop(self) -> None:
        while self._is_monitoring:
            try:
                await asyncio.sleep(self.poll_interval)
                if not self._is_monitoring:
                    break

                prev = self._current_info
                curr = detect_network_info(
                    listening_port=prev.listening_port,
                    discovery_active=prev.discovery_active,
                )

                if (
                    curr.local_ip != prev.local_ip
                    or curr.status != prev.status
                    or curr.interface != prev.interface
                    or curr.ssid != prev.ssid
                ):
                    logger.info(
                        "Network transition detected: %s (%s) IP %s -> %s (%s) IP %s",
                        prev.interface,
                        prev.status,
                        prev.local_ip,
                        curr.interface,
                        curr.status,
                        curr.local_ip,
                    )
                    self._current_info = curr
                    if self.on_network_changed:
                        try:
                            self.on_network_changed(curr)
                        except Exception as e:
                            logger.warning(
                                "Error in on_network_changed callback: %s", e
                            )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Error in network adapter poll loop: %s", e)
