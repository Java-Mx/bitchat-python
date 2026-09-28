"""Bluetooth error recovery and hardware diagnosis modal dialog."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.binding import BindingType


class BLEErrorModal(ModalScreen[bool]):
    """Modal dialog displayed when Bluetooth adapter is missing, disabled, or fails."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "dismiss_modal", "Close"),
        ("q", "dismiss_modal", "Close"),
    ]

    def __init__(
        self,
        error_message: str = "Bluetooth adapter not found or disabled.",
        *,
        bluetooth_available: bool = False,
        central_active: bool = False,
        peripheral_failure: bool = False,
        peripheral_supported: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.error_message = error_message
        self.bluetooth_available = bluetooth_available
        self.central_active = central_active
        self.peripheral_failure = peripheral_failure
        self.peripheral_supported = peripheral_supported

    def compose(self) -> ComposeResult:
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
                yield Button(
                    "Continue Offline", id="btn-ble-close", classes="action-btn"
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-ble-close":
            self.dismiss(False)
        elif event.button.id == "btn-ble-retry":
            self.dismiss(True)

    def action_dismiss_modal(self) -> None:
        self.dismiss()
