"""Bluetooth and LAN error recovery and hardware diagnosis modal dialog."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from bitchat.platform.recovery import bluetooth_recovery_hints, gatt_failure_hint

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult
    from textual.binding import BindingType


GATT_FAILURE_MESSAGE = (
    "Bluetooth hardware was detected, but BitChat could not initialize or use "
    "the BLE GATT service. Choose how you want to continue."
)


def explain_transport_diagnostic(
    source: str | None,
    code: int | None,
    hresult: str | None,
    stage: str | None,
) -> str | None:
    """Translate technical error codes, HRESULTs, and sources into helpful text."""
    if source and "GattServiceProviderAdvertisementStatus" in source:
        if code == 3:
            return (
                "WinRT GATT Advertising Aborted (status 3: Aborted). Windows stopped "
                "BLE service advertising. The Bluetooth adapter hardware may lack "
                "BLE peripheral role advertising support, driver limits were reached, "
                "or another application holds exclusive advertising rights."
            )
        if code == 1:
            return "WinRT GATT Advertising Stopped (status 1)."
    elif source and "GattServiceProvider.create_async" in source:
        if code == 3:
            return (
                "WinRT Bluetooth Error 3 (DeviceNotConnected). The Bluetooth radio "
                "or adapter is not connected or ready for GATT service hosting."
            )
        if code == 1:
            return "WinRT Bluetooth Error 1 (RadioNotAvailable)."
        if code == 2:
            return "WinRT Bluetooth Error 2 (ResourceInUse)."
    elif source and "BluetoothLEAdvertisementPublisher" in source:
        if code == 3:
            return (
                "WinRT Discovery Advertisement Publisher Aborted (status 3). Windows "
                "aborted the companion BLE discovery beacon."
            )
    elif source and ("LANServer" in source or "tcp_server" in (stage or "")):
        if code == 10048 or (hresult and "10048" in hresult):
            return (
                "Port Collision (WSAEADDRINUSE 10048). Another process is already "
                "listening on the BitChat TCP mesh port."
            )
    elif hresult == "0x80070003":
        return (
            "Win32 ERROR_PATH_NOT_FOUND (0x80070003). A required system path or "
            "device was not found."
        )
    elif hresult == "0x80004005":
        return (
            "WinRT E_FAIL (0x80004005). Unspecified failure in Windows Bluetooth stack."
        )

    return None


class BLEErrorModal(ModalScreen[str | None]):
    """Modal dialog displayed when Bluetooth or LAN transport encounters an error.

    Dismiss values
    --------------
    ``"retry"``   - user pressed *Retry Adapter* / *Retry LAN*
    ``"lan"``     - user pressed *Continue Wi-Fi/LAN*
    ``"ble"``     - user pressed *Switch to BLE*
    ``None``      - user pressed *Continue Offline* or dismissed with Escape/Q
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss_modal", "Close", priority=True),
        Binding("q", "dismiss_modal", "Close", priority=True),
    ]

    def __init__(
        self,
        error_message: str = "Bluetooth adapter not found or disabled.",
        *,
        transport: str = "bluetooth",
        bluetooth_available: bool = False,
        central_active: bool = False,
        peripheral_failure: bool = False,
        peripheral_supported: bool = True,
        lan_available: bool = True,
        ble_available: bool = False,
        failed_stage: str | None = None,
        error_code: int | None = None,
        hresult: str | None = None,
        error_source: str | None = None,
        acknowledgement_mode: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.error_message = error_message
        self.transport = transport.lower().strip()
        self.bluetooth_available = bluetooth_available
        self.central_active = central_active
        self.peripheral_failure = peripheral_failure
        self.peripheral_supported = peripheral_supported
        self.lan_available = lan_available
        self.ble_available = ble_available
        self.failed_stage = failed_stage
        self.error_code = error_code
        self.hresult = hresult
        self.error_source = error_source
        self.acknowledgement_mode = acknowledgement_mode

    def compose(self) -> ComposeResult:
        diag_parts = []
        if self.failed_stage:
            diag_parts.append(f"stage={self.failed_stage}")
        if self.error_code is not None:
            diag_parts.append(f"code={self.error_code}")
        if self.hresult:
            diag_parts.append(f"hresult={self.hresult}")
        if self.error_source:
            diag_parts.append(f"source={self.error_source}")
        diag_line = (
            f"\n[dim #79c0ff]Diagnostics: {' | '.join(diag_parts)}[/dim #79c0ff]"
            if diag_parts
            else ""
        )
        explanation = explain_transport_diagnostic(
            self.error_source, self.error_code, self.hresult, self.failed_stage
        )
        explanation_line = (
            f"\n[bold #f0883e]Technical Analysis:[/bold #f0883e] [dim #e6edf3]{explanation}[/dim #e6edf3]"
            if explanation
            else ""
        )

        if self.transport == "lan":
            intro = (
                "[bold #e6edf3]Local network connectivity is unavailable."
                "[/bold #e6edf3]\n\n"
            )
            guidance = (
                "[dim #8b949e]BitChat cannot currently use LAN/Wi-Fi transport.\n\n"
                "Possible solutions:\n"
                "  1. Ensure your network cable is plugged in or Wi-Fi is connected.\n"
                "  2. Verify your router or local network configuration.\n"
                "  3. Click 'Retry LAN' once connectivity is restored."
                "[/dim #8b949e]\n\n"
                "[bold #58a6ff]BitChat is operating safely in Offline / Local Mode."
                "[/bold #58a6ff]"
            )

            with Vertical(id="ble-error-dialog"):
                yield Label(
                    "[bold #f85149]! LAN / Network Connection Lost[/bold #f85149]",
                    id="ble-error-title",
                )

                with Vertical(id="ble-error-content"):
                    yield Static(
                        intro
                        + "[#f85149]Details:[/#f85149] [dim #e6edf3]"
                        + f"{self.error_message}[/dim #e6edf3]"
                        + explanation_line
                        + diag_line
                        + "\n\n"
                        + guidance,
                        classes="ble-error-text",
                    )

                action_count = 2 + int(self.ble_available)
                with (
                    Horizontal(id="ble-error-actions"),
                    Grid(
                        id="ble-error-buttons",
                        classes=f"footer-action-grid footer-actions-{action_count}",
                    ),
                ):
                    if self.ble_available:
                        yield Button(
                            "Switch to BLE",
                            id="btn-lan-ble",
                            classes="action-btn",
                        )
                    yield Button("Retry LAN", id="btn-lan-retry", classes="action-btn")
                    yield Button(
                        "Continue Offline", id="btn-lan-close", classes="action-btn"
                    )
            return

        gatt_startup_failure = (
            self.bluetooth_available
            and self.peripheral_failure
            and not self.central_active
            and self.peripheral_supported
        )
        if gatt_startup_failure:
            intro = f"[bold #e6edf3]{GATT_FAILURE_MESSAGE}[/bold #e6edf3]\n\n"
            guidance = (
                f"[dim #8b949e]{gatt_failure_hint()}\n"
                "Click 'Retry Adapter' to reset BLE and try again, or continue "
                "without Bluetooth.[/dim #8b949e]"
            )
        elif self.bluetooth_available:
            intro = (
                "[bold #e6edf3]Bluetooth radio is ON; "
                + (
                    "BLE central scanning remains active."
                    if self.central_active
                    else "BLE central scanning is not active."
                )
                + "[/bold #e6edf3]\n\n"
                + (
                    f"[bold #e6edf3]{GATT_FAILURE_MESSAGE}[/bold #e6edf3]\n\n"
                    if self.peripheral_failure
                    else ""
                )
            )
            if self.peripheral_failure and self.central_active:
                guidance = (
                    f"[dim #8b949e]{gatt_failure_hint()}\n"
                    "Click 'Retry Adapter' to re-check capabilities and retry "
                    "BLE startup.[/dim #8b949e]\n\n"
                    "[bold #58a6ff]Central-mode BLE remains available."
                    "[/bold #58a6ff]"
                )
            else:
                guidance = (
                    "[dim #8b949e]Click 'Retry Adapter' to check the adapter and "
                    "retry BLE initialization.[/dim #8b949e]\n\n"
                    "[bold #58a6ff]Bluetooth radio is available."
                    "[/bold #58a6ff]"
                )
        else:
            intro = (
                "[bold #e6edf3]Could not initialize Bluetooth Low Energy "
                "transport.[/bold #e6edf3]\n\n"
            )
            steps = "\n".join(
                f"  {i}. {hint}"
                for i, hint in enumerate(bluetooth_recovery_hints(), start=1)
            )
            guidance = (
                f"[dim #8b949e]Possible solutions:\n{steps}[/dim #8b949e]\n\n"
                "[bold #58a6ff]BitChat is operating safely in Offline / Local Mode."
                "[/bold #58a6ff]"
            )

        if self.acknowledgement_mode:
            guidance = (
                "[dim #8b949e]Acknowledge this warning to continue. "
                "If a later Bluetooth attempt fails, recovery choices will be shown."
                "[/dim #8b949e]"
            )

        if self.bluetooth_available and self.peripheral_failure and self.central_active:
            title = "[bold #d2a8ff]! BLE Peripheral Mode Warning[/bold #d2a8ff]"
        elif self.bluetooth_available and not self.peripheral_supported:
            title = "[bold #d2a8ff]! BLE Peripheral Role Unsupported[/bold #d2a8ff]"
        elif self.bluetooth_available and self.peripheral_failure:
            title = (
                "[bold #f85149]! BLE Peripheral Initialization Failed[/bold #f85149]"
            )
        elif self.bluetooth_available:
            title = "[bold #f85149]! Bluetooth Transport Error[/bold #f85149]"
        else:
            title = "[bold #f85149]! Bluetooth Unavailable[/bold #f85149]"

        with Vertical(id="ble-error-dialog"):
            yield Label(title, id="ble-error-title")

            with Vertical(id="ble-error-content"):
                yield Static(
                    intro
                    + f"[#f85149]Details:[/#f85149] [dim #e6edf3]{self.error_message}"
                    f"[/dim #e6edf3]{explanation_line}{diag_line}\n\n" + guidance,
                    classes="ble-error-text",
                )

            action_count = (
                1 if self.acknowledgement_mode else 2 + int(self.lan_available)
            )
            with (
                Horizontal(id="ble-error-actions"),
                Grid(
                    id="ble-error-buttons",
                    classes=f"footer-action-grid footer-actions-{action_count}",
                ),
            ):
                if self.acknowledgement_mode:
                    yield Button(
                        "Okay, I understand",
                        id="btn-ble-ack",
                        classes="action-btn",
                    )
                else:
                    yield Button(
                        "Retry Adapter", id="btn-ble-retry", classes="action-btn"
                    )
                    if self.lan_available:
                        yield Button(
                            "Continue Wi-Fi/LAN",
                            id="btn-ble-lan",
                            classes="action-btn",
                        )
                    yield Button(
                        "Continue Offline", id="btn-ble-close", classes="action-btn"
                    )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-ble-ack":
            self.dismiss("acknowledged")
        elif event.button.id in ("btn-ble-close", "btn-lan-close"):
            self.dismiss(None)
        elif event.button.id in ("btn-ble-retry", "btn-lan-retry", "btn-retry-lan"):
            self.dismiss("retry")
        elif event.button.id == "btn-ble-lan":
            self.dismiss("lan")
        elif event.button.id in ("btn-lan-ble", "btn-switch-ble"):
            self.dismiss("ble")

    def on_mount(self) -> None:
        self.call_after_refresh(self._focus_first_action)

    def _focus_first_action(self) -> None:
        for button in self.query(Button):
            button.focus()
            break

    def on_key(self, event: events.Key) -> None:
        if event.key in ("escape", "q"):
            event.stop()
            event.prevent_default()
            self.dismiss(None)

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


# Aliases for unified modal screen reuse across transports
TransportErrorModal = BLEErrorModal
LANErrorModal = BLEErrorModal
