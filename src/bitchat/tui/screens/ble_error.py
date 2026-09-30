"""Bluetooth and LAN error recovery and hardware diagnosis modal dialog."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.binding import BindingType


class BLEErrorModal(ModalScreen[str | None]):
    """Modal dialog displayed when Bluetooth or LAN transport encounters an error.

    Dismiss values
    --------------
    ``"retry"``   - user pressed *Retry Adapter* / *Retry LAN*
    ``"lan"``     - user pressed *Continue with LAN*
    ``"ble"``     - user pressed *Switch to BLE*
    ``None``      - user pressed *Continue Offline* or dismissed with Escape/Q
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "dismiss_modal", "Close"),
        ("q", "dismiss_modal", "Close"),
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

    def compose(self) -> ComposeResult:
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
                        + f"{self.error_message}[/dim #e6edf3]\n\n"
                        + guidance,
                        classes="ble-error-text",
                    )

                with Horizontal(id="ble-error-actions"):
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

        if self.bluetooth_available:
            intro = (
                "[bold #e6edf3]Bluetooth radio is ON; "
                + (
                    "BLE central scanning remains active."
                    if self.central_active
                    else "BLE peripheral advertising is unavailable."
                )
                + "[/bold #e6edf3]\n\n"
            )
            guidance = (
                "[dim #8b949e]Windows may abort GATT advertising even when "
                "the Bluetooth radio and peripheral role are available.\n"
                "Click 'Retry Adapter' to re-check capabilities and retry "
                "BLE startup.[/dim #8b949e]\n\n"
                "[bold #58a6ff]Central-mode BLE remains available."
                "[/bold #58a6ff]"
                if self.peripheral_failure and self.central_active
                else "[dim #8b949e]Click 'Retry Adapter' to retry supported "
                "BLE roles.[/dim #8b949e]\n\n"
                "[bold #58a6ff]Bluetooth radio is available.[/bold #58a6ff]"
            )
        else:
            intro = (
                "[bold #e6edf3]Could not initialize Bluetooth Low Energy "
                "transport.[/bold #e6edf3]\n\n"
            )
            guidance = (
                "[dim #8b949e]Possible solutions:\n"
                "  1. Ensure your PC's Bluetooth adapter is enabled in settings.\n"
                "  2. On Linux, ensure BlueZ is active\n"
                "     (`systemctl status bluetooth`).\n"
                "  3. On Windows, ensure Bluetooth is toggled ON in Settings.\n"
                "  4. Click 'Retry Adapter' after turning Bluetooth on."
                "[/dim #8b949e]\n\n"
                "[bold #58a6ff]BitChat is operating safely in Offline / Local Mode."
                "[/bold #58a6ff]"
            )

        with Vertical(id="ble-error-dialog"):
            yield Label(
                (
                    "[bold #d2a8ff]! BLE Peripheral Mode Warning[/bold #d2a8ff]"
                    if self.bluetooth_available and self.peripheral_failure
                    else "[bold #d2a8ff]! BLE Peripheral Role Unsupported"
                    "[/bold #d2a8ff]"
                    if self.bluetooth_available and not self.peripheral_supported
                    else "[bold #f85149]! BLE Startup Error "
                    "• Bluetooth Available[/bold #f85149]"
                    if self.bluetooth_available
                    else "[bold #f85149]! Bluetooth Hardware Error[/bold #f85149]"
                ),
                id="ble-error-title",
            )

            with Vertical(id="ble-error-content"):
                yield Static(
                    intro
                    + f"[#f85149]Details:[/#f85149] [dim #e6edf3]{self.error_message}"
                    "[/dim #e6edf3]\n\n" + guidance,
                    classes="ble-error-text",
                )

            with Horizontal(id="ble-error-actions"):
                yield Button("Retry Adapter", id="btn-ble-retry", classes="action-btn")
                if self.lan_available:
                    yield Button(
                        "Continue with LAN",
                        id="btn-ble-lan",
                        classes="action-btn",
                    )
                yield Button(
                    "Continue Offline", id="btn-ble-close", classes="action-btn"
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in ("btn-ble-close", "btn-lan-close"):
            self.dismiss(None)
        elif event.button.id in ("btn-ble-retry", "btn-lan-retry", "btn-retry-lan"):
            self.dismiss("retry")
        elif event.button.id == "btn-ble-lan":
            self.dismiss("lan")
        elif event.button.id in ("btn-lan-ble", "btn-switch-ble"):
            self.dismiss("ble")

    def action_dismiss_modal(self) -> None:
        self.dismiss(None)


# Aliases for unified modal screen reuse across transports
TransportErrorModal = BLEErrorModal
LANErrorModal = BLEErrorModal
