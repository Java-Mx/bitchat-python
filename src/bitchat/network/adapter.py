"""Real network adapter, local IPv4 selection, and SSID detection."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import socket
import subprocess
import time
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from bitchat.network.models import NetworkInfo
from bitchat.network.provider import discover_network_info

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_network_snapshot: NetworkInfo | None = None
_network_snapshot_monotonic: float | None = None
_network_snapshot_task: asyncio.Task[NetworkInfo] | None = None


def get_cached_network_info_snapshot() -> NetworkInfo | None:
    """Return the latest shared snapshot without triggering collection."""
    return _network_snapshot


async def get_network_info_snapshot(
    *, force: bool = False, max_age_seconds: float = 30.0
) -> NetworkInfo:
    """Return the shared OS network snapshot, refreshing it off the event loop."""
    global _network_snapshot, _network_snapshot_monotonic, _network_snapshot_task
    if max_age_seconds < 0:
        raise ValueError("max_age_seconds must not be negative")
    now = time.monotonic()
    if (
        not force
        and _network_snapshot is not None
        and _network_snapshot_monotonic is not None
        and now - _network_snapshot_monotonic < max_age_seconds
    ):
        return _network_snapshot

    task = _network_snapshot_task
    if task is None or task.done():

        async def collect() -> NetworkInfo:
            global _network_snapshot, _network_snapshot_monotonic
            info = _os_network_snapshot(await asyncio.to_thread(detect_network_info))
            _network_snapshot = info
            _network_snapshot_monotonic = time.monotonic()
            return info

        task = asyncio.create_task(collect(), name="shared-network-snapshot")
        _network_snapshot_task = task
    try:
        return await task
    finally:
        if _network_snapshot_task is task and task.done():
            _network_snapshot_task = None


def _publish_network_snapshot(info: NetworkInfo) -> None:
    """Publish a synchronous network refresh to the shared snapshot cache."""
    global _network_snapshot, _network_snapshot_monotonic
    _network_snapshot = _os_network_snapshot(info)
    _network_snapshot_monotonic = time.monotonic()


def _os_network_snapshot(info: NetworkInfo) -> NetworkInfo:
    """Keep LAN socket and discovery state out of the OS network snapshot."""
    return replace(
        info,
        listening_address="0.0.0.0",
        listening_port=0,
        discovery_active=False,
        discovery_error=None,
    )


def clear_network_info_snapshot_cache() -> None:
    """Clear the shared cache for deterministic tests and explicit resets."""
    global _network_snapshot, _network_snapshot_monotonic, _network_snapshot_task
    if _network_snapshot_task is not None and not _network_snapshot_task.done():
        _network_snapshot_task.cancel()
    _network_snapshot = None
    _network_snapshot_monotonic = None
    _network_snapshot_task = None


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


def get_all_local_ips() -> set[str]:
    """Return all IPv4/IPv6 addresses bound to the local machine including loopback."""
    ips = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}
    primary = get_local_ip()
    if primary:
        ips.add(primary)
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            candidate = info[4][0]
            if isinstance(candidate, str):
                ips.add(candidate.lower())
    except Exception:
        pass
    try:
        _, _, host_ips = socket.gethostbyname_ex(socket.gethostname())
        for hip in host_ips:
            if isinstance(hip, str):
                ips.add(hip.lower())
    except Exception:
        pass
    return ips


def is_local_ip(ip: str) -> bool:
    """Return True if the given IP/hostname belongs to the local machine."""
    clean = ip.strip().lower()
    if not clean:
        return True
    if clean.startswith("127.") or clean in ("localhost", "::1", "0.0.0.0"):
        return True
    return clean in get_all_local_ips()


def get_wifi_ssid_and_state() -> tuple[str | None, str | None]:
    """Retrieve connected Wi-Fi SSID and state on Windows or return (None, None)."""
    # Imported lazily: bitchat.platform.capabilities imports this module.
    from bitchat.platform.detection import is_windows

    if not is_windows():
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
    """Inspect host interfaces and return OS state, independent of transport state."""
    return replace(
        discover_network_info(),
        listening_port=listening_port,
        discovery_active=discovery_active,
    )


class NetworkAdapterManager:
    """Monitors local IP and Wi-Fi interface state transitions."""

    def __init__(
        self,
        on_network_changed: Callable[[NetworkInfo], None] | None = None,
        poll_interval: float = 5.0,
    ) -> None:
        self.on_network_changed = on_network_changed
        self.poll_interval = poll_interval
        self._current_info = NetworkInfo(status="Unknown")
        self._is_monitoring: bool = False
        self._monitor_task: asyncio.Task[Any] | None = None
        self._last_refresh_monotonic: float | None = None
        self._last_refresh_duration_seconds: float | None = None
        self._refresh_lock = asyncio.Lock()

    @property
    def last_refresh_duration_seconds(self) -> float | None:
        """Return elapsed time for the most recent system-network query."""
        return self._last_refresh_duration_seconds

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
        started = time.perf_counter()
        self._current_info = detect_network_info(
            listening_port=listening_port, discovery_active=discovery_active
        )
        _publish_network_snapshot(self._current_info)
        self._last_refresh_monotonic = time.monotonic()
        self._last_refresh_duration_seconds = time.perf_counter() - started
        return self._current_info

    async def refresh_async(
        self, listening_port: int | None = None, discovery_active: bool | None = None
    ) -> NetworkInfo:
        """Refresh system network state off the UI/event-loop thread."""
        current = self._current_info
        async with self._refresh_lock:
            started = time.perf_counter()
            snapshot = await get_network_info_snapshot(force=True, max_age_seconds=0.0)
            info = replace(
                snapshot,
                listening_port=(
                    current.listening_port if listening_port is None else listening_port
                ),
                discovery_active=(
                    current.discovery_active
                    if discovery_active is None
                    else discovery_active
                ),
            )
            self._current_info = info
            self._last_refresh_monotonic = time.monotonic()
            self._last_refresh_duration_seconds = time.perf_counter() - started
            return info

    async def refresh_if_stale(
        self,
        max_age_seconds: float = 30.0,
        listening_port: int | None = None,
        discovery_active: bool | None = None,
    ) -> NetworkInfo:
        """Return the recent host snapshot or refresh it once when stale."""
        if max_age_seconds < 0:
            raise ValueError("max_age_seconds must not be negative")
        async with self._refresh_lock:
            started = time.perf_counter()
            snapshot = await get_network_info_snapshot(max_age_seconds=max_age_seconds)
            current = self._current_info
            info = replace(
                snapshot,
                listening_port=(
                    current.listening_port if listening_port is None else listening_port
                ),
                discovery_active=(
                    current.discovery_active
                    if discovery_active is None
                    else discovery_active
                ),
            )
            self._current_info = info
            if snapshot.collected_at != current.collected_at:
                self._last_refresh_monotonic = time.monotonic()
                self._last_refresh_duration_seconds = time.perf_counter() - started
            return info

    async def start_monitoring(
        self,
        listening_port: int = 0,
        discovery_active: bool = False,
        *,
        refresh: bool = True,
    ) -> None:
        """Start background loop monitoring for IP and interface transitions."""
        if self._is_monitoring:
            return
        if refresh:
            await self.refresh_async(
                listening_port=listening_port, discovery_active=discovery_active
            )
        else:
            self._current_info = replace(
                self._current_info,
                listening_port=listening_port,
                discovery_active=discovery_active,
            )
        self._is_monitoring = True
        self._monitor_task = asyncio.create_task(self._poll_loop())

    async def stop_monitoring(self) -> None:
        """Stop background network monitoring."""
        self._is_monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task
            self._monitor_task = None

    @staticmethod
    def _is_network_changed(prev: NetworkInfo, curr: NetworkInfo) -> bool:
        """Compare meaningful network properties, ignoring collection timestamps."""
        return (
            prev.status != curr.status
            or prev.interface != curr.interface
            or prev.interface_name != curr.interface_name
            or prev.interface_state != curr.interface_state
            or prev.local_ip != curr.local_ip
            or prev.ssid != curr.ssid
            or prev.is_connected != curr.is_connected
            or prev.ipv4_addresses != curr.ipv4_addresses
            or prev.default_gateway != curr.default_gateway
        )

    async def _poll_loop(self) -> None:
        while self._is_monitoring:
            try:
                await asyncio.sleep(self.poll_interval)
                if not self._is_monitoring:
                    break

                prev = self._current_info
                curr = await self.refresh_async()
                if self._is_network_changed(prev, curr):
                    logger.info(
                        "Network transition detected: %s (%s) -> %s (%s)",
                        prev.interface,
                        prev.status,
                        curr.interface,
                        curr.status,
                    )
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
