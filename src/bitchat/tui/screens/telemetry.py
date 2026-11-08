"""Dedicated System & Radio Telemetry screen for BitChat."""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
import sys
import time
import tracemalloc
from typing import TYPE_CHECKING, Any, ClassVar

from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Collapsible, Label, Static

from bitchat import __version__
from bitchat.network.adapter import (
    get_cached_network_info_snapshot,
    get_network_info_snapshot,
)
from bitchat.transport.base import TransportError, TransportType

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.binding import BindingType

logger = logging.getLogger(__name__)
NETWORK_DIAGNOSTICS_TIMEOUT_SECONDS = 15.0
NETWORK_SNAPSHOT_MAX_AGE_SECONDS = 30.0


class TelemetryScreen(Screen[None]):
    """Dedicated screen presenting complete system, radio, network, and identity telemetry."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss_screen", "Back", priority=True),
        Binding("r", "refresh_telemetry", "Refresh", priority=True),
        Binding("b", "retry_ble", "Retry Bluetooth", priority=True),
        Binding("l", "retry_lan", "Retry LAN", priority=True),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._is_retrying_ble: bool = False
        self._is_retrying_lan: bool = False
        self._opened_at = time.perf_counter()
        self._first_render_seconds: float | None = None
        self._data_available_seconds: float | None = None
        self._network_data_available_seconds: float | None = None
        self._network_refresh_seconds: float | None = None
        self._network_info: Any | None = None
        self._network_error: str | None = None
        self._network_info_worker: Any | None = None
        self._ble_retry_worker: Any | None = None
        self._lan_retry_worker: Any | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="telemetry-screen-container"):
            with Horizontal(id="telemetry-top-header"):
                yield Label(
                    "[bold #58a6ff]BitChat — System Telemetry[/bold #58a6ff]",
                    id="telemetry-title",
                )
                yield Static(id="telemetry-header-runtime")

            with VerticalScroll(id="telemetry-sections-scroll"):
                with Vertical(classes="telemetry-card", id="card-telemetry-app"):
                    yield Label("Application Status", classes="card-header")
                    with Vertical(classes="card-body"):
                        yield Static(id="telem-summary-app", classes="telem-row")
                        yield Static(id="telem-summary-transport", classes="telem-row")
                        yield Static(id="telem-summary-health", classes="telem-row")
                        yield Static(id="telem-summary-peer", classes="telem-row")
                        with Collapsible(
                            title="Runtime and performance details",
                            collapsed=True,
                            id="details-telemetry-app",
                        ):
                            yield Static(id="telem-app-version", classes="telem-row")
                            yield Static(id="telem-app-runtime", classes="telem-row")
                            yield Static(id="telem-app-transport", classes="telem-row")
                            yield Static(
                                id="telem-app-switch-metrics", classes="telem-row"
                            )
                            yield Static(
                                id="telem-app-open-metrics", classes="telem-row"
                            )
                            yield Static(id="telem-app-tasks", classes="telem-row")

                with Vertical(classes="telemetry-card", id="card-telemetry-ble"):
                    yield Label("Bluetooth / BLE", classes="card-header")
                    with Vertical(classes="card-body"):
                        yield Static(id="telem-summary-ble-radio", classes="telem-row")
                        yield Static(id="telem-summary-ble-roles", classes="telem-row")
                        yield Static(id="telem-summary-ble-gatt", classes="telem-row")
                        yield Static(id="telem-summary-ble-peers", classes="telem-row")
                        yield Static(
                            id="telem-diagnostic-summary", classes="telem-row-warning"
                        )
                        with Collapsible(
                            title="Bluetooth technical details",
                            collapsed=True,
                            id="details-telemetry-ble",
                        ):
                            yield Static(id="telem-ble-adapter", classes="telem-row")
                            yield Static(id="telem-ble-hardware", classes="telem-row")
                            yield Static(id="telem-ble-backend", classes="telem-row")
                            yield Static(id="telem-ble-central", classes="telem-row")
                            yield Static(id="telem-ble-peripheral", classes="telem-row")
                            yield Static(id="telem-ble-adv", classes="telem-row")
                            yield Static(id="telem-ble-scan", classes="telem-row")
                            yield Static(
                                id="telem-ble-error", classes="telem-row-error"
                            )

                with Vertical(classes="telemetry-card", id="card-telemetry-lan"):
                    yield Label("Wi-Fi / Network", classes="card-header")
                    with Vertical(classes="card-body"):
                        yield Static(
                            id="telem-summary-network-connection",
                            classes="telem-row",
                        )
                        yield Static(
                            id="telem-summary-network-interface",
                            classes="telem-row",
                        )
                        yield Static(
                            id="telem-summary-network-addresses",
                            classes="telem-row",
                        )
                        yield Static(
                            id="telem-summary-network-route",
                            classes="telem-row",
                        )
                        yield Static(
                            id="telem-summary-network-signal",
                            classes="telem-row",
                        )
                        yield Static(id="telem-os-status", classes="telem-row")
                        yield Static(id="telem-os-connection", classes="telem-row")
                        yield Static(id="telem-os-type", classes="telem-row")
                        yield Static(id="telem-os-interface", classes="telem-row")
                        yield Static(id="telem-os-adapter", classes="telem-row")
                        yield Static(id="telem-os-profile", classes="telem-row")
                        yield Static(id="telem-os-ssid", classes="telem-row")
                        yield Static(id="telem-os-ipv4", classes="telem-row")
                        yield Static(id="telem-os-ipv6", classes="telem-row")
                        yield Static(id="telem-os-subnet", classes="telem-row")
                        yield Static(id="telem-os-gateway", classes="telem-row")
                        yield Static(id="telem-os-dns", classes="telem-row")
                        yield Static(id="telem-os-signal", classes="telem-row")
                        with Collapsible(
                            title="Network collection details",
                            collapsed=True,
                            id="details-telemetry-network",
                        ):
                            yield Static(
                                id="telem-os-interface-id", classes="telem-row"
                            )
                            yield Static(id="telem-os-refresh", classes="telem-row")
                            yield Static(
                                id="telem-os-other-interfaces", classes="telem-row"
                            )

                with Vertical(classes="telemetry-card", id="card-telemetry-lan-state"):
                    yield Label("BitChat LAN Transport", classes="card-header")
                    with Vertical(classes="card-body"):
                        yield Static(id="telem-summary-lan", classes="telem-row")
                        yield Static(
                            id="telem-summary-lan-services", classes="telem-row"
                        )
                        yield Static(id="telem-summary-lan-peers", classes="telem-row")
                        yield Static(id="telem-summary-lan-last", classes="telem-row")
                        yield Static(
                            id="telem-diagnostic-lan-summary",
                            classes="telem-row-warning",
                        )
                        with Collapsible(
                            title="LAN technical details",
                            collapsed=True,
                            id="details-telemetry-lan",
                        ):
                            yield Static(id="telem-lan-interface", classes="telem-row")
                            yield Static(id="telem-lan-discovery", classes="telem-row")
                            yield Static(id="telem-lan-listener", classes="telem-row")
                            yield Static(id="telem-lan-ports", classes="telem-row")
                            yield Static(id="telem-lan-peers", classes="telem-row")
                            yield Static(
                                id="telem-lan-last-discovery", classes="telem-row"
                            )
                            yield Static(
                                id="telem-lan-error", classes="telem-row-error"
                            )

                with Vertical(classes="telemetry-card", id="card-telemetry-ident"):
                    yield Label("Identity & Security", classes="card-header")
                    with Vertical(classes="card-body"):
                        yield Static(id="telem-ident-loaded", classes="telem-row")
                        yield Static(id="telem-ident-peerid", classes="telem-row")
                        yield Static(id="telem-ident-fp", classes="telem-row")
                        yield Static(
                            "[dim #8b949e]Private keys are encrypted and never exposed in the UI or telemetry.[/dim #8b949e]",
                            classes="telem-note",
                        )

            with (
                Horizontal(id="telemetry-action-bar"),
                Grid(
                    id="telemetry-footer-buttons",
                    classes="footer-action-grid",
                ),
            ):
                yield Button(
                    "Refresh [R]",
                    id="btn-telem-refresh",
                    classes="action-btn",
                )
                yield Button(
                    "Retry BLE [B]",
                    id="btn-telem-retry-ble",
                    classes="action-btn",
                )
                yield Button(
                    "Retry LAN [L]",
                    id="btn-telem-retry-lan",
                    classes="action-btn",
                )
                yield Button("Back (Esc)", id="btn-telem-back", classes="action-btn")

    def on_mount(self) -> None:
        """Render cached state immediately and schedule any stale OS query."""
        self.refresh_status()
        self.call_after_refresh(self._record_first_render)
        self._schedule_network_refresh()

    def on_unmount(self) -> None:
        if self._network_info_worker is not None:
            self._network_info_worker.cancel()

    def _record_first_render(self) -> None:
        if self._first_render_seconds is None:
            self._first_render_seconds = time.perf_counter() - self._opened_at
            self.refresh_status()

    def _schedule_network_refresh(self, *, force: bool = False) -> None:
        worker = self._network_info_worker
        if worker is not None and getattr(worker, "is_running", False):
            return
        self._network_info_worker = self.run_worker(
            self._refresh_system_network(force=force),
            name="telemetry-network-diagnostics",
            group="telemetry-network-diagnostics",
            exclusive=True,
            exit_on_error=False,
        )

    async def _refresh_system_network(self, *, force: bool = False) -> None:
        """Refresh host network diagnostics asynchronously and retain failures."""
        try:
            started = time.perf_counter()
            info = await asyncio.wait_for(
                get_network_info_snapshot(
                    force=force,
                    max_age_seconds=(
                        0.0 if force else NETWORK_SNAPSHOT_MAX_AGE_SECONDS
                    ),
                ),
                timeout=NETWORK_DIAGNOSTICS_TIMEOUT_SECONDS,
            )
            self._network_refresh_seconds = time.perf_counter() - started
            self._network_info = info
            self._network_error = None
            if self._network_data_available_seconds is None:
                self._network_data_available_seconds = (
                    time.perf_counter() - self._opened_at
                )
        except Exception as error:
            self._network_error = str(error)
            logger.warning("Telemetry network diagnostics failed: %s", error)
        self.refresh_status()

    def refresh_status(self) -> None:
        """Query subsystems and format truthful status metrics."""
        if self._data_available_seconds is None:
            self._data_available_seconds = time.perf_counter() - self._opened_at
        coord = getattr(self.app, "coordinator", None)
        ident = getattr(coord, "local_identity", None)
        bt_trans = (
            coord._transports.get("bluetooth")
            if coord and hasattr(coord, "_transports")
            else None
        )
        lan_trans = (
            coord._transports.get("lan")
            if coord and hasattr(coord, "_transports")
            else None
        )

        bt_telem = (
            bt_trans.get_telemetry()
            if bt_trans and hasattr(bt_trans, "get_telemetry")
            else {}
        )
        lan_telem = (
            lan_trans.get_telemetry()
            if lan_trans and hasattr(lan_trans, "get_telemetry")
            else {}
        )
        adapter_manager = getattr(lan_trans, "adapter_manager", None)
        network_info = (
            self._network_info
            or get_cached_network_info_snapshot()
            or getattr(adapter_manager, "current_info", None)
        )

        # Runtime Header
        with contextlib.suppress(Exception):
            py_ver = sys.version.split()[0]
            self.query_one("#telemetry-header-runtime", Static).update(
                f"[dim #8b949e]Python {py_ver} • {sys.platform} • BitChat v{__version__}[/dim #8b949e]"
            )

        # 1. BLE Telemetry
        is_windows = sys.platform == "win32"
        backend_name = bt_telem.get(
            "backend_name",
            "Windows WinRT GATT" if is_windows else "Linux BlueZ (D-Bus)",
        )
        adapter_avail = bt_telem.get("adapter_available", False)
        adapter_state_str = bt_telem.get("adapter_state", "Unavailable")
        if adapter_avail and adapter_state_str == "On":
            adapter_state = "[bold #3fb950]● Available (Enabled)[/bold #3fb950]"
        elif adapter_avail and adapter_state_str == "Off":
            adapter_state = "[bold #d29922]○ Disabled / Radio Off[/bold #d29922]"
        elif bt_telem.get("adapter_initialization") == "Not checked":
            adapter_state = "[dim #8b949e]Not checked (read-only screen)[/dim #8b949e]"
        else:
            adapter_state = "[bold #f85149]✕ Not Available / Absent[/bold #f85149]"

        gatt_telem = bt_telem.get("gatt", {})
        if not isinstance(gatt_telem, dict):
            gatt_telem = {}
        gatt_stat = bt_telem.get("gatt_server_status", "Stopped")
        is_adv = bt_telem.get("advertising_active", False)
        ble_history = (
            getattr(coord, "transport_diagnostics", {}).get(TransportType.BLUETOOTH, [])
            if coord
            else []
        )
        last_ble_event = ble_history[-1] if ble_history else None
        current_peripheral_error = bt_telem.get("peripheral_error") or gatt_telem.get(
            "last_error"
        )
        current_ble_error = current_peripheral_error or bt_telem.get("error_message")
        if (
            current_ble_error is None
            and coord
            and coord.active_transport_name == "bluetooth"
        ):
            current_ble_error = getattr(coord, "ble_error_message", None)
        peripheral_failure = bool(current_peripheral_error or gatt_stat == "Failed")
        last_error = current_ble_error or (
            last_ble_event.message if last_ble_event else None
        )

        if is_adv:
            gatt_status = (
                "[bold #3fb950]● Running (Advertising Service Active)[/bold #3fb950]"
            )
        elif gatt_stat == "Failed" or current_ble_error:
            gatt_status = "[bold #f85149]✕ Failed / Error[/bold #f85149]"
        elif not bt_telem.get("peripheral_supported", True):
            gatt_status = "[dim #8b949e]○ Unsupported by adapter/backend[/dim #8b949e]"
        else:
            gatt_status = "[dim #8b949e]○ Standby / Stopped[/dim #8b949e]"

        adapter_checked = bt_telem.get("adapter_initialization") != "Not checked"
        radio_summary = (
            "Available"
            if adapter_avail
            else "Unavailable"
            if adapter_checked
            else "Not checked"
        )
        adapter_summary = (
            "Enabled"
            if adapter_avail and adapter_state_str == "On"
            else "Disabled"
            if adapter_avail and adapter_state_str == "Off"
            else "Unavailable"
            if adapter_checked
            else "Not checked"
        )
        peripheral_summary = (
            "Ready" if is_adv else "Failed" if peripheral_failure else "Not Initialized"
        )
        adv_state = (
            "[bold #3fb950]● Active[/bold #3fb950]"
            if is_adv
            else "[dim #8b949e]○ Idle / Inactive[/dim #8b949e]"
        )

        is_scanning = bt_telem.get("scanner_status") == "Active"
        scan_started_at = bt_telem.get("scan_started_at")
        scan_duration = bt_telem.get("scan_duration_seconds")
        scan_last_success = bt_telem.get("last_successful_scan_at")
        scan_started_text = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(scan_started_at))
            if isinstance(scan_started_at, (int, float))
            else "Never"
        )
        scan_success_text = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(scan_last_success))
            if isinstance(scan_last_success, (int, float))
            else "Never"
        )
        scan_state = (
            (
                f"[bold #3fb950]● Active[/bold #3fb950]; "
                f"started {scan_started_text}; "
                f"duration {scan_duration:.1f}s"
                if isinstance(scan_duration, (int, float))
                else f"[bold #3fb950]● Active[/bold #3fb950]; "
                f"started {scan_started_text}"
            )
            if is_scanning
            else "[dim #8b949e]○ Idle / Inactive[/dim #8b949e]"
        )

        with contextlib.suppress(Exception):
            self.query_one("#telem-summary-ble-radio", Static).update(
                f"[{'✓' if adapter_avail else '—' if adapter_checked else '?'}] "
                f"Bluetooth radio: "
                f"{radio_summary}; adapter: {adapter_summary}"
            )
            self.query_one("#telem-summary-ble-roles", Static).update(
                f"[{'✓' if is_scanning else '—'}] BLE Central: "
                f"{'Active' if is_scanning else 'Inactive'}; "
                f"Peripheral: {peripheral_summary}"
            )
            self.query_one("#telem-summary-ble-gatt", Static).update(
                f"[{'✓' if gatt_telem.get('service_registered') else '—'}] "
                f"GATT Service: "
                f"{'Registered' if gatt_telem.get('service_registered') else 'Not Registered'}; "
                f"Advertising: {'Active' if is_adv else 'Inactive'}"
            )
            self.query_one("#telem-summary-ble-peers", Static).update(
                f"[✓] Connected BLE peers: {bt_telem.get('connected_peers_count', 0)}"
            )
            if peripheral_failure:
                error_summary = (
                    "Bluetooth peripheral unavailable. "
                    "BitChat can still scan for nearby devices."
                    if bt_telem.get("central_supported", True)
                    else "Bluetooth peripheral unavailable. See technical details."
                )
            elif current_ble_error:
                error_summary = "Bluetooth unavailable. See technical details."
            else:
                error_summary = "No current Bluetooth peripheral error."
            self.query_one("#telem-diagnostic-summary", Static).update(
                f"[!] {error_summary}"
            )
            self.query_one("#telem-diagnostic-summary", Static).display = bool(
                peripheral_failure or current_ble_error
            )
            self.query_one("#telem-ble-adapter", Static).update(
                f"[dim #8b949e]Bluetooth Adapter   :[/dim #8b949e] {adapter_state} "
                f"({bt_telem.get('adapter_initialization', 'Not checked')})"
            )
            adapter_name = bt_telem.get("adapter_name", "Unavailable")
            adapter_id = bt_telem.get("adapter_id", "Unavailable")
            self.query_one("#telem-ble-hardware", Static).update(
                f"[dim #8b949e]Name / ID / permission:[/dim #8b949e] "
                f"{adapter_name} / {adapter_id} / "
                f"{bt_telem.get('permission_status', 'Unknown')}"
            )
            self.query_one("#telem-ble-backend", Static).update(
                f"[dim #8b949e]Platform backend    :[/dim #8b949e] {backend_name}; "
                f"peripheral {gatt_status}"
            )
            self.query_one("#telem-ble-central", Static).update(
                f"[dim #8b949e]BLE Central         :[/dim #8b949e] "
                f"{'Scanning' if is_scanning else 'Stopped'}; "
                f"last successful scan {scan_success_text}; "
                f"{bt_telem.get('discovered_peers_count', 0)} discovered / "
                f"{bt_telem.get('connected_peers_count', 0)} connected"
            )
            self.query_one("#telem-ble-peripheral", Static).update(
                f"[dim #8b949e]GATT service/char   :[/dim #8b949e] "
                f"{'registered' if gatt_telem.get('service_registered') else 'not registered'} / "
                f"{'registered' if gatt_telem.get('characteristic_registered') else 'not registered'}; "
                f"notifications {'supported' if gatt_telem.get('notifications_supported') else 'unavailable'} "
                f"({gatt_telem.get('subscribed_client_count', 0)} subscribers)"
            )
            self.query_one("#telem-ble-adv", Static).update(
                f"[dim #8b949e]BLE Advertising    :[/dim #8b949e] {adv_state}; "
                f"registration {'active' if gatt_telem.get('advertisement_registered') else 'inactive'}"
            )
            self.query_one("#telem-ble-scan", Static).update(
                f"[dim #8b949e]BLE Scan session   :[/dim #8b949e] {scan_state}"
            )
            err_widget = self.query_one("#telem-ble-error", Static)
            if last_error:
                details = ""
                if last_ble_event and last_error == last_ble_event.message:
                    diagnostic_fields = [
                        f"operation={last_ble_event.operation}",
                        f"operation_id={last_ble_event.operation_id}",
                        f"timestamp={last_ble_event.occurred_at:.3f}",
                    ]
                    if last_ble_event.stage:
                        diagnostic_fields.append(f"stage={last_ble_event.stage}")
                    if last_ble_event.native_error_code is not None:
                        diagnostic_fields.append(
                            f"native_code={last_ble_event.native_error_code}"
                        )
                    if last_ble_event.hresult:
                        diagnostic_fields.append(f"hresult={last_ble_event.hresult}")
                    if last_ble_event.original_error:
                        diagnostic_fields.append(
                            f"original={last_ble_event.original_error}"
                        )
                    diagnostic_fields.append(
                        "kind="
                        + (
                            "error"
                            if isinstance(last_ble_event, TransportError)
                            else "warning"
                        )
                    )
                    details = f" ({'; '.join(diagnostic_fields)})"
                stage = (
                    bt_telem.get("failed_stage")
                    or gatt_telem.get("failed_stage")
                    or (last_ble_event.stage if last_ble_event else None)
                )
                native_code = (
                    bt_telem.get("error_code")
                    if bt_telem.get("error_code") is not None
                    else gatt_telem.get("error_code")
                )
                hresult = bt_telem.get("hresult") or gatt_telem.get("hresult")
                source = bt_telem.get("error_source") or gatt_telem.get("error_source")
                original = last_ble_event.original_error if last_ble_event else None
                platform_details = "; ".join(
                    f"{key}={value}"
                    for key, value in (
                        ("stage", stage),
                        ("native_code", native_code),
                        ("hresult", hresult),
                        ("source", source),
                        ("original", original),
                    )
                    if value is not None
                )
                if platform_details and not details:
                    details = f" ({platform_details})"
                err_widget.update(
                    f"[bold #d29922][!] Last BLE Diagnostic:[/bold #d29922] "
                    f"[dim #f85149]{last_error}{details}[/dim #f85149]"
                )
                err_widget.display = True
            else:
                err_widget.update("")
                err_widget.display = False

        # 2. Operating-system networking remains visible when Bluetooth is selected.
        lan_running = lan_trans is not None and getattr(lan_trans, "is_running", False)
        lan_selected = getattr(coord, "selected_transport_name", "") == "lan"
        lan_active = getattr(coord, "effective_active_transport_name", "") == "lan"
        network_status = str(
            getattr(network_info, "status", lan_telem.get("status", "Unknown"))
        )
        connection_type = str(
            getattr(
                network_info, "interface", lan_telem.get("interface", "Unavailable")
            )
        )
        interface_name = str(
            getattr(
                network_info,
                "interface_name",
                lan_telem.get("interface_name", "Unavailable"),
            )
        )
        interface_state = str(
            getattr(
                network_info,
                "interface_state",
                lan_telem.get("interface_state", "Unknown"),
            )
        )
        ssid = str(getattr(network_info, "ssid", lan_telem.get("ssid", "Unavailable")))
        ipv4 = (
            ", ".join(
                getattr(
                    network_info, "ipv4_addresses", lan_telem.get("ipv4_addresses", ())
                )
            )
            or "Unavailable"
        )
        ipv6 = (
            ", ".join(
                getattr(
                    network_info, "ipv6_addresses", lan_telem.get("ipv6_addresses", ())
                )
            )
            or "Unavailable"
        )
        prefixes = (
            ", ".join(
                str(value)
                for value in getattr(
                    network_info,
                    "subnet_prefixes",
                    lan_telem.get("subnet_prefixes", ()),
                )
            )
            or "Unavailable"
        )
        gateway = str(
            getattr(
                network_info,
                "default_gateway",
                lan_telem.get("default_gateway", "Unavailable"),
            )
        )
        dns_servers = (
            ", ".join(
                getattr(network_info, "dns_servers", lan_telem.get("dns_servers", ()))
            )
            or "Unavailable"
        )
        connection_name = str(getattr(network_info, "connection_name", "Unavailable"))
        network_name_reason = getattr(network_info, "network_name_reason", None)
        interface_description = str(
            getattr(network_info, "interface_description", interface_name)
        )
        interface_id = getattr(network_info, "interface_id", None)
        signal_percent = getattr(network_info, "signal_strength_percent", None)
        signal_dbm = getattr(network_info, "signal_strength_dbm", None)
        route_interface = getattr(
            network_info,
            "default_route_interface",
            lan_telem.get("default_route_interface", "Unavailable"),
        )
        if self._network_error:
            network_status = f"{network_status} (refresh failed: {self._network_error})"
        if interface_name == "Unavailable":
            interface_summary = "Unavailable (no active route interface reported)"
        else:
            interface_summary = (
                f"{interface_name} ({interface_description}); {interface_state}"
            )
        if connection_name.lower() == "unavailable":
            connection_summary = (
                network_name_reason or "The operating system did not report a name."
            )
        else:
            connection_summary = connection_name
        if connection_type == "Ethernet":
            ssid = "Not applicable (Ethernet)"
        elif not ssid or ssid.lower() == "unavailable":
            ssid = network_name_reason or "Wi-Fi SSID unavailable from operating system"
        signal = (
            f"{signal_percent}%"
            if isinstance(signal_percent, int)
            else f"{signal_dbm} dBm"
            if isinstance(signal_dbm, int)
            else "Not reported"
        )

        discovery_running = lan_telem.get("discovery") == "Active"
        discovery_port = lan_telem.get("discovery_port")
        discovery_broadcasting = bool(lan_telem.get("discovery_broadcasting"))
        discovery_state = (
            f"Listening UDP :{discovery_port}; "
            f"{'beacon sending' if discovery_broadcasting else 'beacon stopped'}"
            if discovery_running and discovery_port
            else "Stopped"
            if not lan_running
            else "Not initialized"
        )
        listener_running = lan_telem.get("listening") == "Active"
        bound_port = lan_telem.get("listening_port")
        listener_state = (
            f"Active (TCP :{bound_port})"
            if listener_running and bound_port
            else "Stopped"
            if not lan_running
            else "Not initialized"
        )
        advertised = str(lan_telem.get("advertised_address") or "Unavailable")
        broadcast = str(lan_telem.get("broadcast_address") or "Unavailable")
        discovered_count = lan_telem.get("discovered_peers_count", 0)
        connected_count = lan_telem.get("connected_peers_count", 0)
        last_discovery = lan_telem.get("last_discovery_at")
        if isinstance(last_discovery, (int, float)):
            last_discovery = datetime.datetime.fromtimestamp(
                last_discovery, tz=datetime.UTC
            ).strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            last_discovery = "Never"
        current_lan_error = lan_telem.get("error_message") or lan_telem.get(
            "discovery_last_error"
        )
        lan_err = current_lan_error or "None"
        lan_history = (
            getattr(coord, "transport_diagnostics", {}).get(TransportType.LAN, [])
            if coord
            else []
        )
        if lan_err == "None" and lan_history:
            lan_err = f"Last LAN diagnostic: {lan_history[-1].message}"
        transport_state = str(lan_telem.get("state", "Not initialized"))

        with contextlib.suppress(Exception):
            if self._network_info_worker is not None and getattr(
                self._network_info_worker, "is_running", False
            ):
                network_refresh_state = "refreshing"
            elif network_info is not None:
                network_refresh_state = "ready"
            else:
                network_refresh_state = "unavailable"
            network_refresh_duration = (
                f"{self._network_refresh_seconds:.3f}s"
                if self._network_refresh_seconds is not None
                else "not measured"
            )
            network_collected_at = getattr(network_info, "collected_at", None)
            network_age = getattr(network_info, "cache_age_seconds", None)
            network_timestamp = (
                datetime.datetime.fromtimestamp(
                    network_collected_at, tz=datetime.UTC
                ).isoformat(timespec="seconds")
                if isinstance(network_collected_at, (int, float))
                else "not recorded"
            )
            field_availability = (
                "; ".join(
                    f"{name}: {state}"
                    for name, state in getattr(network_info, "field_availability", ())
                )
                or "not recorded"
            )
            collection_errors = (
                "; ".join(getattr(network_info, "collection_errors", ())) or "none"
            )
            extra_interfaces = []
            for item in getattr(network_info, "interfaces", ()):
                if item.name == interface_name:
                    continue
                if item.operational_state.lower() not in {"up", "connected"}:
                    continue
                addresses = (*item.ipv4_addresses, *item.ipv6_addresses)
                address_text = ", ".join(addresses) if addresses else "no IP address"
                extra_interfaces.append(
                    f"{item.name} ({item.kind}, {item.operational_state}): {address_text}"
                )
            extra_interfaces_text = (
                "Additional active interfaces: " + "; ".join(extra_interfaces)
                if extra_interfaces
                else "No additional active interfaces reported."
            )
            network_marker = (
                "✓"
                if network_status.lower().startswith("connected")
                else "—"
                if network_status.lower().startswith("disconnected")
                else "!"
            )
            ipv4_summary = ipv4 if ipv4 != "Unavailable" else "not assigned"
            ipv6_summary = ipv6 if ipv6 != "Unavailable" else "not assigned"
            route_summary = (
                f"Subnet {prefixes if prefixes != 'Unavailable' else 'not reported'}; "
                f"gateway {gateway if gateway != 'Unavailable' else 'not reported'}"
            )
            dns_summary = (
                dns_servers if dns_servers != "Unavailable" else "not reported"
            )
            values = {
                "#telem-summary-network-connection": (
                    f"[{network_marker}] Network connection: "
                    f"{network_status} — {connection_summary} ({connection_type})"
                ),
                "#telem-summary-network-interface": (
                    f"[✓] Active interface: {interface_summary}"
                ),
                "#telem-summary-network-addresses": (
                    f"[✓] IPv4: {ipv4_summary}; IPv6: {ipv6_summary}"
                ),
                "#telem-summary-network-route": (f"[✓] {route_summary}"),
                "#telem-summary-network-signal": (
                    f"[✓] SSID: {ssid}; signal: {signal}; DNS: {dns_summary}"
                ),
                "#telem-os-status": f"[dim #8b949e]Network status:[/dim #8b949e] {network_status}",
                "#telem-os-connection": (
                    f"[dim #8b949e]Connection name:[/dim #8b949e] {connection_summary}"
                ),
                "#telem-os-type": (
                    f"[dim #8b949e]Connection type:[/dim #8b949e] {connection_type}"
                ),
                "#telem-os-interface": (
                    f"[dim #8b949e]Network interface:[/dim #8b949e] "
                    f"{interface_summary}; default route: {route_interface}"
                ),
                "#telem-os-adapter": (
                    f"[dim #8b949e]Adapter description:[/dim #8b949e] "
                    f"{interface_description}"
                ),
                "#telem-os-profile": (
                    f"[dim #8b949e]Network profile:[/dim #8b949e] {connection_name}"
                ),
                "#telem-os-interface-id": (
                    f"[dim #8b949e]Interface ID:[/dim #8b949e] "
                    f"{interface_id or 'not exposed'}"
                ),
                "#telem-os-ssid": f"[dim #8b949e]Wi-Fi SSID:[/dim #8b949e] {ssid}",
                "#telem-os-ipv4": f"[dim #8b949e]IPv4 addresses:[/dim #8b949e] {ipv4}",
                "#telem-os-ipv6": f"[dim #8b949e]IPv6 addresses:[/dim #8b949e] {ipv6}",
                "#telem-os-subnet": f"[dim #8b949e]Subnet prefix:[/dim #8b949e] {prefixes}",
                "#telem-os-gateway": f"[dim #8b949e]Default gateway:[/dim #8b949e] {gateway}",
                "#telem-os-dns": f"[dim #8b949e]DNS servers:[/dim #8b949e] {dns_servers}",
                "#telem-os-signal": f"[dim #8b949e]Wi-Fi signal:[/dim #8b949e] {signal}",
                "#telem-os-refresh": (
                    "[dim #8b949e]Network diagnostics:[/dim #8b949e] "
                    f"{network_refresh_state}; "
                    f"last query {network_refresh_duration}; "
                    f"provider {getattr(network_info, 'provider_backend', 'unknown')}; "
                    f"snapshot {network_timestamp}; "
                    f"age {f'{network_age:.1f}s' if isinstance(network_age, (int, float)) else 'unknown'}; "
                    f"fields [{field_availability}]; errors [{collection_errors}]"
                ),
                "#telem-os-other-interfaces": extra_interfaces_text,
                "#telem-lan-interface": (
                    f"[dim #8b949e]Transport:[/dim #8b949e] "
                    f"{'Selected' if lan_selected else 'Not selected'}; "
                    f"{'Active' if lan_active else 'Inactive'}; "
                    f"{'Running' if lan_running else 'Stopped'} ({transport_state})"
                ),
                "#telem-lan-discovery": f"[dim #8b949e]UDP discovery:[/dim #8b949e] {discovery_state}",
                "#telem-lan-listener": f"[dim #8b949e]TCP listener:[/dim #8b949e] {listener_state}",
                "#telem-lan-ports": (
                    f"[dim #8b949e]Advertised / broadcast:[/dim #8b949e] "
                    f"{advertised} / {broadcast}"
                ),
                "#telem-lan-peers": (
                    f"[dim #8b949e]Peers:[/dim #8b949e] "
                    f"{discovered_count} discovered / {connected_count} authenticated"
                ),
                "#telem-lan-last-discovery": (
                    f"[dim #8b949e]Last successful discovery:[/dim #8b949e] {last_discovery}"
                ),
                "#telem-summary-lan": (
                    f"[{'✓' if lan_active else '—'}] LAN transport: "
                    f"{'Active' if lan_active else 'Inactive'}; "
                    f"{'selected' if lan_selected else 'not selected'}"
                ),
                "#telem-summary-lan-services": (
                    f"[{'✓' if discovery_running else '—'}] UDP discovery: "
                    f"{'Running' if discovery_running else 'Stopped'}; "
                    f"TCP listener: "
                    f"{'Listening' if listener_running else 'Stopped'}"
                    f"{f' on port {bound_port}' if listener_running and bound_port else ''}"
                ),
                "#telem-summary-lan-peers": (
                    f"[✓] LAN peers: {discovered_count} discovered / "
                    f"{connected_count} authenticated; advertised {advertised}"
                ),
                "#telem-summary-lan-last": (
                    f"[✓] Last successful discovery: {last_discovery}"
                ),
            }
            for selector, value in values.items():
                self.query_one(selector, Static).update(value)
            lan_summary = self.query_one("#telem-diagnostic-lan-summary", Static)
            if current_lan_error:
                lan_summary.update(f"[!] LAN transport issue: {current_lan_error}")
                lan_summary.display = True
            else:
                lan_summary.update("")
                lan_summary.display = False
            lan_err_widget = self.query_one("#telem-lan-error", Static)
            if lan_err != "None":
                lan_err_widget.update(
                    f"[bold #f85149]Last network error:[/bold #f85149] "
                    f"[dim #f85149]{lan_err}[/dim #f85149]"
                )
                lan_err_widget.display = True
            else:
                lan_err_widget.update("")
                lan_err_widget.display = False

        # 3. Identity Telemetry
        pid = ""
        peer_id_summary = "Unavailable"
        with contextlib.suppress(Exception):
            if ident is not None:
                pid = getattr(ident, "peer_id_hex", "")
                fp = getattr(ident, "fingerprint_hex", "")
                peer_id_summary = (
                    f"{pid[:12]}…{pid[-8:]}" if len(pid) > 24 else pid or "Unavailable"
                )
                self.query_one("#telem-ident-loaded", Static).update(
                    "[dim #8b949e]Identity State     :[/dim #8b949e] "
                    "[bold #3fb950]✓ Loaded & Verified (Ed25519)[/bold #3fb950]"
                )
                self.query_one("#telem-ident-peerid", Static).update(
                    f"[dim #8b949e]Local Peer ID      :[/dim #8b949e] "
                    f"[bold #79c0ff]{pid}[/bold #79c0ff]"
                )
                self.query_one("#telem-ident-fp", Static).update(
                    f"[dim #8b949e]Public Fingerprint :[/dim #8b949e] "
                    f"[bold #d2a8ff]{fp}[/bold #d2a8ff]"
                )
            else:
                pid = ""
                peer_id_summary = "Unavailable"
                self.query_one("#telem-ident-loaded", Static).update(
                    "[dim #8b949e]Identity State     :[/dim #8b949e] "
                    "[bold #f85149]✕ Uninitialized[/bold #f85149]"
                )
                self.query_one("#telem-ident-peerid", Static).update(
                    "[dim #8b949e]Local Peer ID      :[/dim #8b949e] -"
                )
                self.query_one("#telem-ident-fp", Static).update(
                    "[dim #8b949e]Public Fingerprint :[/dim #8b949e] -"
                )

        # 4. Application & Runtime Health
        with contextlib.suppress(Exception):
            selected_name = (
                getattr(coord, "selected_transport_name", "Standby").upper()
                if coord
                else "STANDBY"
            )
            active_name = (
                getattr(coord, "effective_active_transport_name", "Standby").upper()
                if coord
                else "STANDBY"
            )
            config = getattr(self.app, "config", None)
            security_mode = (
                str(getattr(config, "security_mode", "Unknown"))
                .replace("_", " ")
                .title()
            )
            last_successful = (
                getattr(coord, "last_successful_transport_name", None) or "None"
                if coord
                else "None"
            )
            self.query_one("#telem-app-version", Static).update(
                f"[dim #8b949e]BitChat Version    :[/dim #8b949e] "
                f"[bold #e6edf3]v{__version__}[/bold #e6edf3]"
            )
            py_ver = sys.version.split()[0]
            self.query_one("#telem-app-runtime", Static).update(
                f"[dim #8b949e]Python Runtime     :[/dim #8b949e] "
                f"[bold #e6edf3]{py_ver}[/bold #e6edf3] "
                f"([dim #8b949e]{sys.platform}[/dim #8b949e])"
            )
            self.query_one("#telem-app-transport", Static).update(
                f"[dim #8b949e]Selected / Active :[/dim #8b949e] "
                f"[bold #39c5cf]{selected_name} / {active_name}[/bold #39c5cf] "
                f"[dim #8b949e](last successful: {last_successful.upper()})[/dim #8b949e]"
            )
            metrics = (
                getattr(coord, "last_transport_switch_metrics", {}) if coord else {}
            )
            if metrics:
                indicator_seconds = metrics.get("indicator_update_seconds")
                indicator_text = (
                    f"{indicator_seconds:.3f}s"
                    if isinstance(indicator_seconds, (int, float))
                    else "pending"
                )
                discovery_seconds = metrics.get("discovery_ready_seconds")
                discovery_text = (
                    f"{discovery_seconds:.3f}s"
                    if isinstance(discovery_seconds, (int, float))
                    else "not ready"
                )
                metrics_text = (
                    f"cleanup {metrics['cleanup_seconds']:.3f}s; "
                    f"init {metrics['initialization_seconds']:.3f}s; "
                    f"total {metrics['total_seconds']:.3f}s; "
                    f"indicator {indicator_text}; discovery {discovery_text}"
                )
            else:
                metrics_text = "No transport switch measured this session"
            self.query_one("#telem-app-switch-metrics", Static).update(
                f"[dim #8b949e]Last switch timings:[/dim #8b949e] {metrics_text}"
            )
            telemetry_open = (
                f"{self._first_render_seconds:.3f}s"
                if self._first_render_seconds is not None
                else "pending"
            )
            telemetry_data = (
                f"{self._data_available_seconds:.3f}s"
                if self._data_available_seconds is not None
                else "pending"
            )
            network_data = (
                f"{self._network_data_available_seconds:.3f}s"
                if self._network_data_available_seconds is not None
                else "pending"
            )
            self.query_one("#telem-app-open-metrics", Static).update(
                "[dim #8b949e]Screen timing:[/dim #8b949e] "
                f"first render {telemetry_open}; telemetry data {telemetry_data}; "
                f"OS network data {network_data}"
            )
            app_tasks = getattr(self.app, "_background_tasks", set())
            running_app_tasks = sum(not task.done() for task in app_tasks)
            coordinator_tasks = getattr(coord, "_background_tasks", set())
            running_coordinator_tasks = sum(
                not task.done() for task in coordinator_tasks
            )
            screen_workers = (
                self._network_info_worker,
                self._ble_retry_worker,
                self._lan_retry_worker,
            )
            running_screen_tasks = sum(
                bool(worker and getattr(worker, "is_running", False))
                for worker in screen_workers
            )
            try:
                running_loop_tasks = len(asyncio.all_tasks())
            except RuntimeError:
                running_loop_tasks = 0
            if tracemalloc.is_tracing():
                memory_current, memory_peak = tracemalloc.get_traced_memory()
                memory_summary = (
                    f"{memory_current / 1024 / 1024:.1f} MiB current / "
                    f"{memory_peak / 1024 / 1024:.1f} MiB peak"
                )
            else:
                memory_summary = "not sampled"
            self.query_one("#telem-app-tasks", Static).update(
                "[dim #8b949e]Running tasks / memory:[/dim #8b949e] "
                f"app {running_app_tasks}; coordinator {running_coordinator_tasks}; "
                f"screen {running_screen_tasks}; "
                f"event loop {running_loop_tasks}; {memory_summary}"
            )
            self.query_one("#telem-summary-app", Static).update(
                f"[✓] BitChat v{__version__} · {sys.platform} · Python {py_ver}"
            )
            self.query_one("#telem-summary-transport", Static).update(
                f"[{'✓' if active_name not in {'STANDBY', 'OFFLINE'} else '—'}] "
                f"Transport: {active_name}; selected: {selected_name}"
            )
            self.query_one("#telem-summary-health", Static).update(
                f"[✓] Application running · security mode: {security_mode} · "
                f"{running_app_tasks + running_coordinator_tasks + running_screen_tasks} "
                "tracked background tasks"
            )
            self.query_one("#telem-summary-peer", Static).update(
                f"[✓] Local peer ID: {peer_id_summary}"
            )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        match bid:
            case "btn-telem-refresh":
                await self.action_refresh_telemetry()
            case "btn-telem-retry-ble":
                self.action_retry_ble()
            case "btn-telem-retry-lan":
                self.action_retry_lan()
            case "btn-telem-back":
                self.action_dismiss_screen()

    async def action_refresh_telemetry(self) -> None:
        """Manual refresh of OS network and subsystem telemetry."""
        self._schedule_network_refresh(force=True)
        self.refresh_status()

    def action_retry_ble(self) -> None:
        """Trigger Bluetooth retry on active coordinator."""
        if self._is_retrying_ble:
            return
        self._is_retrying_ble = True
        coord = getattr(self.app, "coordinator", None)
        if (
            coord is not None
            and getattr(coord, "active_transport_name", "") != "bluetooth"
        ):
            self._ble_retry_worker = self.run_worker(
                self._retry_ble_independent(),
                name="telemetry-ble-retry",
                group="telemetry-ble-retry",
                exclusive=True,
                exit_on_error=False,
            )
            return
        fn = getattr(self.app, "action_retry_bluetooth", None)
        if callable(fn):
            fn()
        self.set_timer(1.0, self._finish_ble_retry)

    async def _retry_ble_independent(self) -> None:
        from bitchat.app.session_coordinator import SessionCoordinator

        coord = getattr(self.app, "coordinator", None)
        try:
            if not isinstance(coord, SessionCoordinator):
                logger.warning("Cannot retry BLE: session coordinator unavailable")
                return
            await coord.retry_ble_independent()
        finally:
            self._is_retrying_ble = False
            self.refresh_status()

    def _finish_ble_retry(self) -> None:
        self._is_retrying_ble = False
        self.refresh_status()

    def action_retry_lan(self) -> None:
        """Trigger LAN retry on active coordinator."""
        if self._is_retrying_lan:
            return
        self._is_retrying_lan = True
        self._lan_retry_worker = self.run_worker(
            self._retry_lan(),
            name="telemetry-lan-retry",
            group="telemetry-lan-retry",
            exclusive=True,
            exit_on_error=False,
        )

    async def _retry_lan(self) -> None:
        from bitchat.app.session_coordinator import SessionCoordinator

        coord = getattr(self.app, "coordinator", None)
        try:
            if not isinstance(coord, SessionCoordinator):
                logger.warning("Cannot retry LAN: session coordinator unavailable")
                return
            await coord.retry_lan()
        except Exception:
            logger.exception("LAN retry failed")
        finally:
            self._is_retrying_lan = False
            self.refresh_status()

    def action_dismiss_screen(self) -> None:
        """Return to previous screen."""
        if len(self.app._screen_stack) > 1:
            self.app.pop_screen()
