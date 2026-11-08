"""Dedicated settings screen and configuration architecture."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.keys import Keys
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Static,
    Switch,
)

from bitchat.network.adapter import (
    get_cached_network_info_snapshot,
    get_network_info_snapshot,
)
from bitchat.storage.config import (
    DEFAULT_KEYBINDINGS,
    AppConfig,
    FileConfigStorage,
    StorageInterface,
)

logger = logging.getLogger(__name__)
NETWORK_DIAGNOSTICS_TIMEOUT_SECONDS = 15.0
NETWORK_SNAPSHOT_MAX_AGE_SECONDS = 30.0

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult
    from textual.binding import BindingType

KEYBINDING_LABELS: dict[str, str] = {
    "help": "Help",
    "edit_theme": "Edit Theme",
    "settings": "Settings",
    "clear_chat": "Clear Chat",
    "quit": "Quit",
    "scroll_up": "Scroll Up",
    "scroll_down": "Scroll Down",
}
_KEY_MODIFIERS = ("ctrl", "alt", "shift")
_SUPPORTED_KEY_NAMES = frozenset(
    key.value for key in Keys if "+" not in key.value and not key.value.startswith("<")
)
_RESERVED_KEYBINDINGS = {
    "escape": "Escape is reserved for Back and dismiss actions.",
    "enter": "Enter is reserved for activating controls.",
    "return": "Enter is reserved for activating controls.",
    "tab": "Tab is reserved for focus navigation.",
    "shift+tab": "Shift+Tab is reserved for reverse focus navigation.",
    "ctrl+shift+p": "Ctrl+Shift+P is reserved for the command palette.",
    "ctrl+z": "Ctrl+Z is reserved by the terminal.",
    "alt+f4": "Alt+F4 is reserved by the window manager.",
}


def normalize_keybinding(value: str, action: str | None = None) -> str:
    """Validate and canonicalize one Textual key name."""
    if not isinstance(value, str):
        raise ValueError("Key name must be text.")

    parts = [part.strip().lower() for part in value.split("+")]
    if not parts or any(not part for part in parts):
        raise ValueError("Use a key name with optional Ctrl, Alt, or Shift modifiers.")

    base = parts[-1]
    modifiers = parts[:-1]
    if any(modifier not in _KEY_MODIFIERS for modifier in modifiers) or len(
        set(modifiers)
    ) != len(modifiers):
        raise ValueError("Modifiers may be Ctrl, Alt, and Shift, each used once.")
    if base not in _SUPPORTED_KEY_NAMES and not (
        len(base) == 1 and base.isascii() and base.isalnum()
    ):
        raise ValueError(f"Unsupported key name: {base!r}.")

    ordered_modifiers = sorted(modifiers, key=_KEY_MODIFIERS.index)
    key = "+".join((*ordered_modifiers, base))
    if key == "return":
        key = "enter"

    reason = _RESERVED_KEYBINDINGS.get(key)
    if key == "ctrl+c" and action == "quit":
        reason = None
    elif key == "ctrl+c":
        reason = "Ctrl+C is reserved for the terminal interrupt/quit action."
    if reason:
        raise ValueError(reason)
    return key


SETTINGS_CATEGORIES: list[tuple[str, str]] = [
    ("general", "General"),
    ("identity", "Security & Privacy"),
    ("bluetooth", "Bluetooth"),
    ("network", "Network & Connectivity"),
    ("notifications", "Messaging"),
    ("appearance", "Appearance"),
    ("startup", "About & Diagnostics"),
    ("advanced", "Performance"),
]


class SaveStatusIndicator(Static):
    """Status indicator cleanly centered below footer controls."""

    SAVED_TEXT = "✓ ALL CHANGES SAVED"
    UNSAVED_TEXT = "◈ UNSAVED CHANGES"
    SAVING_TEXT = "Saving changes..."
    ERROR_TEXT = "✕ FAILED TO SAVE"

    def __init__(self, id: str | None = None, **kwargs: Any) -> None:  # noqa: A002
        super().__init__(
            f"[#3fb950]{self.SAVED_TEXT}[/#3fb950]",
            id=id or "settings-save-indicator",
            classes="state-saved",
            **kwargs,
        )
        self.is_saved: bool = True

    def set_saved(self, message: str | None = None) -> None:
        self.is_saved = True
        self.remove_class("state-unsaved")
        self.remove_class("state-saving")
        self.remove_class("state-error")
        self.add_class("state-saved")
        text = message or self.SAVED_TEXT
        self.update(f"[#3fb950]{text}[/#3fb950]")

    def set_unsaved(self, message: str | None = None) -> None:
        self.is_saved = False
        self.remove_class("state-saved")
        self.remove_class("state-saving")
        self.remove_class("state-error")
        self.add_class("state-unsaved")
        text = message or self.UNSAVED_TEXT
        self.update(f"[#d29922]{text}[/#d29922]")

    def set_saving(self, message: str | None = None) -> None:
        self.is_saved = False
        self.remove_class("state-saved")
        self.remove_class("state-unsaved")
        self.remove_class("state-error")
        self.add_class("state-saving")
        text = message or self.SAVING_TEXT
        self.update(f"[#58a6ff]{text}[/#58a6ff]")

    def set_error(self, message: str | None = None) -> None:
        self.is_saved = False
        self.remove_class("state-saved")
        self.remove_class("state-unsaved")
        self.remove_class("state-saving")
        self.add_class("state-error")
        text = message or self.ERROR_TEXT
        self.update(f"[#f85149]{text}[/#f85149]")


class UnsavedChangesModal(ModalScreen[bool]):
    """Confirmation modal triggered when navigating away with unsaved settings."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "stay", "Keep Editing", priority=True),
        Binding("enter", "stay", "Keep Editing", priority=True),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="unsaved-changes-dialog"):
            yield Label(
                "[bold #f85149]◈ Unsaved Changes[/bold #f85149]", id="unsaved-title"
            )
            yield Static(
                "You have modified settings that have not yet been saved to disk.\n\n"
                "Discard changes and leave?",
                id="unsaved-desc",
            )
            with (
                Horizontal(id="unsaved-actions"),
                Grid(
                    id="unsaved-footer-buttons",
                    classes="footer-action-grid",
                ),
            ):
                yield Button(
                    "Discard Changes",
                    id="btn-unsaved-discard",
                    classes="action-btn unsaved-btn btn-discard",
                )
                yield Button(
                    "Keep Editing",
                    id="btn-unsaved-stay",
                    classes="action-btn unsaved-btn btn-keep",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-unsaved-discard":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_stay(self) -> None:
        self.dismiss(False)


class SettingsScreen(ModalScreen[None]):
    """Dedicated settings screen with categories and persistent save indicators."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss_modal", "Cancel", priority=True),
        Binding("f3", "dismiss_modal", "Cancel", priority=True),
    ]

    class SettingsSaved(Message):
        """Emitted when user saves modified settings."""

        def __init__(
            self,
            nickname: str,
            max_hops: int,
            inter_fragment_delay_ms: int,
            keybindings: dict[str, str] | None = None,
            transport: str = "bluetooth",
            density: str = "comfortable",
            accent: str = "blue",
        ) -> None:
            super().__init__()
            self.nickname = nickname
            self.max_hops = max_hops
            self.inter_fragment_delay_ms = inter_fragment_delay_ms
            self.keybindings = keybindings or DEFAULT_KEYBINDINGS.copy()
            self.transport = transport
            self.density = density
            self.accent = accent

    def __init__(
        self,
        current_nickname: str = "Anonymous",
        current_max_hops: int = 3,
        current_delay_ms: int = 20,
        current_keybindings: dict[str, str] | None = None,
        current_transport: str = "bluetooth",
        current_density: str = "comfortable",
        current_accent: str = "blue",
        current_show_timestamps: bool = True,
        current_debug: bool = False,
        current_security_mode: str = "normal",
        initial_category: str = "general",
        config: AppConfig | None = None,
        storage: StorageInterface | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._custom_config = config
        self._custom_storage = storage
        self.current_nickname = current_nickname
        self.current_max_hops = current_max_hops
        self.current_delay_ms = current_delay_ms
        self.current_keybindings = (
            current_keybindings.copy()
            if current_keybindings
            else DEFAULT_KEYBINDINGS.copy()
        )
        self.current_transport = current_transport
        self.current_density = current_density
        self.current_accent = current_accent
        self.current_show_timestamps = current_show_timestamps
        self.current_debug = current_debug
        self.current_security_mode = current_security_mode
        self.active_category: str = self._normalize_category(initial_category)
        self.selected_category: str = self.active_category
        self.has_unsaved_changes: bool = False
        self._is_populating: bool = True
        self._initial_snapshot: dict[str, Any] | None = None
        self._network_info: Any | None = None
        self._network_info_worker: Any | None = None
        self._network_error: str | None = None
        self._opened_at = time.perf_counter()
        self._first_render_seconds: float | None = None
        self._network_refresh_seconds: float | None = None

    @staticmethod
    def _normalize_category(cat: str) -> str:
        clean = cat.strip().lower()
        if clean in (
            "network",
            "lan",
            "wifi",
            "wi-fi",
            "ethernet",
            "connectivity",
            "network & connectivity",
        ):
            return "network"
        if clean in ("bluetooth", "ble", "bt"):
            return "bluetooth"
        if clean in ("appearance", "theme", "density", "accent"):
            return "appearance"
        if clean in ("identity", "security", "crypto", "privacy", "security & privacy"):
            return "identity"
        if clean in ("notifications", "notify", "timestamps", "messaging", "chat"):
            return "notifications"
        if clean in (
            "startup",
            "behavior",
            "autostart",
            "about",
            "diagnostics",
            "about & diagnostics",
        ):
            return "startup"
        if clean in ("advanced", "keys", "keybindings", "debug", "performance"):
            return "advanced"
        return "general"

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-dialog"):
            with Horizontal(id="settings-header-bar"):
                yield Label(
                    "BitChat Settings & Configuration",
                    id="settings-title",
                )
                yield Static(id="settings-active-cat-badge")

            # Main split layout: Left categories nav + Right fields scroll
            with Horizontal(id="settings-body-split"):
                with Vertical(id="settings-category-nav"):
                    yield Label(
                        "[dim #8b949e]CATEGORIES[/dim #8b949e]",
                        classes="cat-nav-header",
                    )
                    for cat_id, cat_name in SETTINGS_CATEGORIES:
                        is_active = cat_id == self.active_category
                        active_cls = " active-cat" if is_active else ""
                        indicator = "> " if is_active else "  "
                        yield Button(
                            f"{indicator}{cat_name}",
                            id=f"btn-cat-{cat_id}",
                            classes=f"cat-nav-btn{active_cls}",
                        )

                with VerticalScroll(id="settings-form"):
                    # Category 1: General
                    with Vertical(
                        classes="settings-cat-section", id="section-cat-general"
                    ):
                        yield Label(
                            "[bold #58a6ff]General Configuration[/bold #58a6ff]",
                            classes="settings-field-label",
                        )
                        yield Static(
                            "[dim #8b949e]Core identity, transport selection, and mesh forwarding limits.[/dim #8b949e]",
                            classes="settings-cat-intro",
                        )
                        yield Label(
                            "Local Nickname (visible to mesh peers, max 32 chars):"
                        )
                        yield Input(
                            value=self.current_nickname,
                            placeholder="Enter nickname...",
                            id="settings-input-nickname",
                        )
                        yield Static(
                            "[dim #8b949e]Display name announced to peers across all transport mediums.[/dim #8b949e]",
                            classes="settings-note",
                        )

                        yield Label("Default Transport Medium:")
                        with RadioSet(id="settings-radio-transport"):
                            yield RadioButton(
                                "Bluetooth Low Energy (BLE)",
                                value=(self.current_transport == "bluetooth"),
                                id="radio-transport-bluetooth",
                            )
                            yield RadioButton(
                                "LAN / Wi-Fi Network",
                                value=(self.current_transport == "lan"),
                                id="radio-transport-lan",
                            )
                        yield Static(
                            "[dim #8b949e]Preferred communication interface initialized upon launch.[/dim #8b949e]",
                            classes="settings-note",
                        )

                        yield Label("Max Mesh Relay Hops (TTL 1-7):")
                        yield Input(
                            value=str(self.current_max_hops),
                            placeholder="3",
                            id="settings-input-hops",
                        )
                        yield Static(
                            "[dim #8b949e]Maximum packet hops before a multi-hop mesh message is dropped.[/dim #8b949e]",
                            classes="settings-note",
                        )

                        yield Label("Inter-Fragment Delay (ms, 5-500):")
                        yield Input(
                            value=str(self.current_delay_ms),
                            placeholder="20",
                            id="settings-input-delay",
                        )
                        yield Static(
                            "[dim #8b949e]Delay between packet burst fragments to prevent buffer overrun.[/dim #8b949e]",
                            classes="settings-note",
                        )

                    # Category 2: Security & Privacy (Read-only / Safe)
                    with Vertical(
                        classes="settings-cat-section", id="section-cat-identity"
                    ):
                        yield Label(
                            "[bold #39c5cf]Security & Privacy[/bold #39c5cf]",
                            classes="settings-field-label",
                        )
                        yield Static(
                            "[dim #8b949e]Cryptographic keys uniquely identify your device across all transports.[/dim #8b949e]",
                            classes="settings-cat-intro",
                        )
                        yield Label("Local Peer ID (Public Key Hash):")
                        yield Static(
                            id="settings-static-peer-id", classes="safe-ident-display"
                        )
                        yield Label("Identity Fingerprint (Ed25519 SHA-256):")
                        yield Static(
                            id="settings-static-fingerprint",
                            classes="safe-ident-display",
                        )
                        yield Label("Identity File Location:")
                        yield Static(
                            id="settings-static-storage-path",
                            classes="safe-ident-display",
                        )
                        yield Label("Selectable Security Mode:")
                        with RadioSet(id="settings-radio-security-mode"):
                            yield RadioButton(
                                "Normal Security (Persistent identity across restarts)",
                                value=(self.current_security_mode != "maximum"),
                                id="radio-security-normal",
                            )
                            yield RadioButton(
                                "Maximum Security (Fresh session peer ID on each launch)",
                                value=(self.current_security_mode == "maximum"),
                                id="radio-security-maximum",
                            )
                        yield Static(
                            "[dim #8b949e]Normal Security retains persistent identity and peer ID across restarts.\n"
                            "Maximum Security generates a fresh session ID and keys on every application launch.\n"
                            "Persistent identity file is preserved, but remote peers will see a new session ID.[/dim #8b949e]",
                            classes="settings-note",
                        )
                        yield Static(
                            "[dim #8b949e]Verification Policy: Trust-On-First-Use (TOFU) active.\n"
                            "Private keys are securely encrypted with user-restricted ACLs and never exposed.[/dim #8b949e]",
                            classes="settings-note",
                        )

                    # Category 3: Bluetooth / BLE
                    with Vertical(
                        classes="settings-cat-section", id="section-cat-bluetooth"
                    ):
                        yield Label(
                            "[bold #bc8cff]Bluetooth Low Energy Parameters[/bold #bc8cff]",
                            classes="settings-field-label",
                        )
                        yield Static(
                            "[dim #8b949e]Hardware adapter state, service UUIDs, and BLE operational roles.[/dim #8b949e]",
                            classes="settings-cat-intro",
                        )
                        yield Label("Platform Driver Backend:")
                        yield Static(
                            id="settings-static-ble-backend",
                            classes="safe-ident-display",
                        )
                        yield Label("Standard BitChat BLE Service UUID:")
                        yield Static(
                            "0000fee0-0000-1000-8000-00805f9b34fb",
                            id="settings-static-ble-uuid",
                            classes="safe-ident-display",
                        )
                        yield Label("BLE Peripheral Role (GATT Server):")
                        yield Static(
                            id="settings-static-ble-peripheral",
                            classes="safe-ident-display",
                        )
                        yield Label("BLE Central Role (Background Scanner):")
                        yield Static(
                            id="settings-static-ble-central",
                            classes="safe-ident-display",
                        )
                        yield Static(
                            "[dim #8b949e]Cross-platform parity: Windows uses native WinRT BLE APIs; Linux uses BlueZ via D-Bus.[/dim #8b949e]",
                            classes="settings-note",
                        )

                    # Category 4: Network & Connectivity
                    with Vertical(
                        classes="settings-cat-section", id="section-cat-network"
                    ):
                        yield Label(
                            "[bold #56d364]Network & Connectivity[/bold #56d364]",
                            classes="settings-field-label",
                        )
                        yield Static(
                            "[dim #8b949e]Operating-system connectivity is independent of the selected BitChat transport.[/dim #8b949e]",
                            classes="settings-cat-intro",
                        )
                        yield Label("Network Interface Information:")
                        yield Static(
                            id="settings-network-connection",
                            classes="safe-ident-display",
                        )
                        yield Static(
                            id="settings-network-interface",
                            classes="safe-ident-display",
                        )
                        yield Static(
                            id="settings-network-ssid", classes="safe-ident-display"
                        )
                        yield Static(
                            id="settings-network-signal", classes="safe-ident-display"
                        )
                        yield Static(
                            id="settings-network-ipv4", classes="safe-ident-display"
                        )
                        yield Static(
                            id="settings-network-ipv6", classes="safe-ident-display"
                        )
                        yield Static(
                            id="settings-network-subnet", classes="safe-ident-display"
                        )
                        yield Static(
                            id="settings-network-gateway", classes="safe-ident-display"
                        )
                        yield Static(
                            id="settings-network-dns", classes="safe-ident-display"
                        )
                        yield Static(
                            id="settings-network-diagnostics",
                            classes="safe-ident-display",
                        )
                        yield Button(
                            "Refresh Network Information",
                            id="btn-settings-network-refresh",
                            classes="action-btn",
                        )
                        yield Label("LAN Transport Configuration:")
                        yield Static(
                            id="settings-network-transport",
                            classes="safe-ident-display",
                        )
                        yield Label("UDP Peer Discovery Port (1024-65535):")
                        yield Input(value="41234", id="settings-input-udp-port")
                        yield Label("TCP Transport Server Port (1024-65535):")
                        yield Input(value="41235", id="settings-input-tcp-port")
                        yield Static(
                            "[dim #8b949e]Configured ports apply on the next LAN transport start. Active sockets always report their actual bound ports.[/dim #8b949e]",
                            classes="settings-note",
                        )
                        yield Label("Network Diagnostics:")
                        yield Static(
                            id="settings-network-discovery",
                            classes="safe-ident-display",
                        )
                        yield Static(
                            id="settings-network-listener", classes="safe-ident-display"
                        )
                        yield Static(
                            id="settings-network-error", classes="safe-ident-display"
                        )
                        yield Button(
                            "Retry LAN Transport",
                            id="btn-settings-network-retry",
                            classes="action-btn",
                        )

                    # Category 5: Messaging
                    with Vertical(
                        classes="settings-cat-section", id="section-cat-notifications"
                    ):
                        yield Label(
                            "[bold #e3b341]Messaging & Chat Behavior[/bold #e3b341]",
                            classes="settings-field-label",
                        )
                        yield Static(
                            "[dim #8b949e]Conversation stream formatting and alert presentation options.[/dim #8b949e]",
                            classes="settings-cat-intro",
                        )
                        with Horizontal(classes="settings-switch-row"):
                            yield Label("Show Message Timestamps:")
                            yield Switch(value=True, id="settings-switch-timestamps")
                        yield Static(
                            "[dim #8b949e]Display [HH:MM] timestamps next to incoming and sent messages in chat view.[/dim #8b949e]",
                            classes="settings-note",
                        )

                    # Category 6: Appearance
                    with Vertical(
                        classes="settings-cat-section", id="section-cat-appearance"
                    ):
                        yield Label(
                            "[bold #d2a8ff]Appearance & Density[/bold #d2a8ff]",
                            classes="settings-field-label",
                        )
                        yield Static(
                            "[dim #8b949e]Customize message density and terminal color accent theme.[/dim #8b949e]",
                            classes="settings-cat-intro",
                        )
                        yield Label("Message Density:")
                        with RadioSet(id="settings-radio-density"):
                            yield RadioButton(
                                "Comfortable (Standard line spacing)",
                                value=(self.current_density != "compact"),
                                id="radio-density-comfortable",
                            )
                            yield RadioButton(
                                "Compact (Tight spacing for small terminals)",
                                value=(self.current_density == "compact"),
                                id="radio-density-compact",
                            )

                        yield Label("Theme Accent Color:")
                        with RadioSet(id="settings-radio-accent"):
                            yield RadioButton(
                                "Midnight Blue (Default)",
                                value=(self.current_accent == "blue"),
                                id="radio-accent-blue",
                            )
                            yield RadioButton(
                                "Cyber Cyan",
                                value=(self.current_accent == "cyan"),
                                id="radio-accent-cyan",
                            )
                            yield RadioButton(
                                "Terminal Emerald",
                                value=(self.current_accent == "emerald"),
                                id="radio-accent-emerald",
                            )
                            yield RadioButton(
                                "Amethyst Purple",
                                value=(self.current_accent == "purple"),
                                id="radio-accent-purple",
                            )

                    # Category 7: About & Diagnostics
                    with Vertical(
                        classes="settings-cat-section", id="section-cat-startup"
                    ):
                        yield Label(
                            "[bold #58a6ff]About & System Diagnostics[/bold #58a6ff]",
                            classes="settings-field-label",
                        )
                        yield Static(
                            "[dim #8b949e]Operating system integration and automatic launch configuration.[/dim #8b949e]",
                            classes="settings-cat-intro",
                        )
                        with Horizontal(classes="settings-switch-row"):
                            yield Label("Start BitChat automatically on user sign-in:")
                            yield Switch(value=False, id="settings-switch-startup")
                        yield Static(
                            "[dim #8b949e]Registers a per-user startup shortcut in the Windows Startup folder.[/dim #8b949e]",
                            id="settings-static-startup-note",
                            classes="settings-note",
                        )

                    # Category 8: Performance & Keyboard Shortcuts
                    with Vertical(
                        classes="settings-cat-section", id="section-cat-advanced"
                    ):
                        yield Label(
                            "[bold #f778ba]Performance & Keyboard Shortcuts[/bold #f778ba]",
                            classes="settings-field-label",
                        )
                        yield Static(
                            "[dim #8b949e]Configure terminal hotkeys and protocol diagnostic logging.[/dim #8b949e]",
                            classes="settings-cat-intro",
                        )
                        with Horizontal(classes="settings-switch-row"):
                            yield Label("Enable Debug Logging:")
                            yield Switch(value=False, id="settings-switch-debug")
                        yield Static(
                            "[dim #8b949e]Records detailed technical diagnostics and packet telemetry to rotating log files.[/dim #8b949e]",
                            classes="settings-note",
                        )

                        yield Label(
                            "Key Bindings (Action Shortcuts):",
                            classes="settings-field-label",
                        )
                        for action, label in KEYBINDING_LABELS.items():
                            val = self.current_keybindings.get(
                                action, DEFAULT_KEYBINDINGS.get(action, "")
                            )
                            with Horizontal(classes="settings-kb-row"):
                                yield Label(f"{label}:", classes="settings-kb-label")
                                yield Input(
                                    value=val,
                                    id=f"settings-kb-{action}",
                                    classes="settings-kb-input",
                                )

                        yield Static(
                            "[dim #8b949e]Use Textual key names (for example f1, pageup, "
                            "ctrl+l, alt+a, or ctrl+shift+a). Keys are normalized; "
                            "each action needs a unique, non-reserved key.[/dim #8b949e]",
                            id="settings-hint",
                        )

            # Bottom Controls & Dedicated Status Indicator
            with Vertical(id="settings-footer-bar"):
                with (
                    Horizontal(id="settings-footer-buttons-row"),
                    Grid(
                        id="settings-actions-left",
                        classes="footer-action-grid",
                    ),
                ):
                    yield Button(
                        "Save",
                        id="btn-settings-save",
                        classes="action-btn",
                    )
                    yield Button(
                        "Cancel", id="btn-settings-cancel", classes="action-btn"
                    )
                    yield Button(
                        "Reset",
                        id="btn-settings-restore-defaults",
                        classes="action-btn",
                    )
                with Horizontal(id="settings-actions-right"):
                    yield SaveStatusIndicator()

    def on_mount(self) -> None:
        """Render persisted settings immediately; refresh network only when needed."""
        self._apply_category_visibility()
        self._populate_initial_fields()
        self._render_network_information()
        self._focus_category(self.selected_category)
        self.call_after_refresh(self._record_first_render)
        if self.active_category == "network":
            self._schedule_network_information_refresh()

    def on_unmount(self) -> None:
        if self._network_info_worker is not None:
            self._network_info_worker.cancel()

    def _record_first_render(self) -> None:
        if self._first_render_seconds is None:
            self._first_render_seconds = time.perf_counter() - self._opened_at

    def _schedule_network_information_refresh(self, *, force: bool = False) -> None:
        """Run a cache-aware read-only query only while the network category is open."""
        if self.active_category != "network":
            return
        worker = self._network_info_worker
        if worker is not None and getattr(worker, "is_running", False):
            return
        self._network_info_worker = self.run_worker(
            self._refresh_network_information(force=force),
            name="settings-network-diagnostics",
            group="settings-network-diagnostics",
            exclusive=True,
            exit_on_error=False,
        )

    async def _refresh_network_information(self, *, force: bool = False) -> None:
        """Refresh host interface data with a bounded query and visible errors."""
        started = time.perf_counter()
        try:
            self._network_info = await asyncio.wait_for(
                get_network_info_snapshot(
                    force=force,
                    max_age_seconds=(
                        0.0 if force else NETWORK_SNAPSHOT_MAX_AGE_SECONDS
                    ),
                ),
                timeout=NETWORK_DIAGNOSTICS_TIMEOUT_SECONDS,
            )
            self._network_refresh_seconds = time.perf_counter() - started
            self._network_error = None
        except Exception as error:
            self._network_error = str(error)
            logger.warning("Settings network diagnostics failed: %s", error)
        self._render_network_information()

    def _render_network_information(self) -> None:
        """Render only values present in the current OS and transport snapshots."""
        coord = getattr(self.app, "coordinator", None)
        lan_trans = (
            coord._transports.get("lan")
            if coord and hasattr(coord, "_transports")
            else None
        )
        manager = getattr(lan_trans, "adapter_manager", None)
        info = (
            self._network_info
            or get_cached_network_info_snapshot()
            or getattr(manager, "current_info", None)
        )
        telemetry = (
            lan_trans.get_telemetry()
            if lan_trans is not None and hasattr(lan_trans, "get_telemetry")
            else {}
        )
        connection_name = getattr(info, "connection_name", "Unavailable")
        connection_reason = getattr(info, "network_name_reason", None)
        if connection_name == "Unavailable":
            connection_name = (
                connection_reason or "Not reported by the operating system"
            )
        ssid = getattr(info, "ssid", "Unavailable")
        if getattr(info, "interface", "Unavailable") == "Ethernet":
            ssid = "Not applicable (Ethernet)"
        elif ssid == "Unavailable":
            ssid = (
                connection_reason or "Wi-Fi SSID not reported by the operating system"
            )
        signal_percent = getattr(info, "signal_strength_percent", None)
        signal_dbm = getattr(info, "signal_strength_dbm", None)
        signal = (
            f"{signal_percent}%"
            if isinstance(signal_percent, int)
            else f"{signal_dbm} dBm"
            if isinstance(signal_dbm, int)
            else "Not reported"
        )
        values = {
            "#settings-network-connection": (
                f"Connection: {connection_name} / "
                f"{getattr(info, 'status', 'Unknown')} / "
                f"{getattr(info, 'interface', 'Unavailable')}"
            ),
            "#settings-network-interface": (
                f"Interface: {getattr(info, 'interface_name', 'Unavailable')} "
                f"({getattr(info, 'interface_description', 'Unavailable')}) — "
                f"{getattr(info, 'interface_state', 'Unknown')}"
            ),
            "#settings-network-ssid": f"Wi-Fi SSID: {ssid}",
            "#settings-network-signal": f"Signal strength: {signal}",
            "#settings-network-ipv4": "IPv4: "
            + (", ".join(getattr(info, "ipv4_addresses", ())) or "Unavailable"),
            "#settings-network-ipv6": "IPv6: "
            + (", ".join(getattr(info, "ipv6_addresses", ())) or "Unavailable"),
            "#settings-network-subnet": "Subnet prefix: "
            + (
                ", ".join(str(value) for value in getattr(info, "subnet_prefixes", ()))
                or "Unavailable"
            ),
            "#settings-network-gateway": (
                f"Default gateway: {getattr(info, 'default_gateway', 'Unavailable')}"
            ),
            "#settings-network-dns": "DNS: "
            + (", ".join(getattr(info, "dns_servers", ())) or "Unavailable"),
            "#settings-network-diagnostics": (
                f"Provider: {getattr(info, 'provider_backend', 'unknown')}; "
                f"snapshot age: "
                f"{getattr(info, 'cache_age_seconds', None):.1f}s"
                if isinstance(getattr(info, "cache_age_seconds", None), (int, float))
                else f"Provider: {getattr(info, 'provider_backend', 'unknown')}; "
                "snapshot age: unknown"
            ),
            "#settings-network-transport": (
                f"Configured: {getattr(getattr(self.app, 'config', None), 'transport', 'bluetooth')}; "
                f"Active: {getattr(coord, 'active_transport_name', 'Unavailable')}"
            ),
            "#settings-network-discovery": (
                f"UDP discovery: {telemetry.get('discovery', 'Not initialized')} "
                f"(port {telemetry.get('discovery_port', 'Unavailable')})"
            ),
            "#settings-network-listener": (
                f"TCP listener: {telemetry.get('listening', 'Not initialized')} "
                f"(bound port {telemetry.get('listening_port') or 'Unavailable'})"
            ),
            "#settings-network-error": (
                "Last initialization/runtime error: "
                f"{self._network_error or telemetry.get('error_message') or 'None'}"
            ),
        }
        for selector, value in values.items():
            with contextlib.suppress(NoMatches):
                self.query_one(selector, Static).update(value)

    def _focus_category(self, category_id: str) -> None:
        """Focus a category button without changing the displayed category."""
        with contextlib.suppress(NoMatches):
            self.query_one(f"#btn-cat-{category_id}", Button).focus()

    @staticmethod
    def _is_within(widget: Any, container_id: str) -> bool:
        """Return whether a widget is a descendant of the named container."""
        while widget is not None:
            if getattr(widget, "id", None) == container_id:
                return True
            widget = getattr(widget, "parent", None)
        return False

    def _move_category_focus(self, offset: int) -> None:
        """Move category focus, stopping at the first and last categories."""
        category_ids = [category_id for category_id, _ in SETTINGS_CATEGORIES]
        current_index = category_ids.index(self.selected_category)
        next_index = max(0, min(len(category_ids) - 1, current_index + offset))
        self.selected_category = category_ids[next_index]
        self._focus_category(self.selected_category)

    def _focus_active_category_content(self) -> None:
        """Focus the first interactive control in the displayed category."""
        with contextlib.suppress(NoMatches):
            section = self.query_one(f"#section-cat-{self.active_category}")
            for widget in section.query("Input, Button, RadioButton, Switch"):
                if widget.can_focus and widget.display:
                    widget.focus()
                    return

    def _apply_category_visibility(self) -> None:
        """Update category section visibility and active tab button styling."""
        for cat_id, cat_name in SETTINGS_CATEGORIES:
            with contextlib.suppress(NoMatches):
                sec = self.query_one(f"#section-cat-{cat_id}")
                is_active = cat_id == self.active_category
                sec.display = is_active
                btn = self.query_one(f"#btn-cat-{cat_id}", Button)
                indicator = "> " if is_active else "  "
                btn.label = f"{indicator}{cat_name}"
                if is_active:
                    btn.add_class("active-cat")
                else:
                    btn.remove_class("active-cat")

        with contextlib.suppress(NoMatches):
            badge = self.query_one("#settings-active-cat-badge", Static)
            cat_label = dict(SETTINGS_CATEGORIES).get(self.active_category, "Settings")
            badge.update(
                f"[bold]Category:[/bold] [dim #e6edf3]{cat_label}[/dim #e6edf3]"
            )

    def switch_category(self, category_id: str) -> None:
        """Switch active configuration category and its visible form section."""
        self.active_category = self._normalize_category(category_id)
        self.selected_category = self.active_category
        self._apply_category_visibility()
        if self.active_category == "network":
            self._render_network_information()
            self._schedule_network_information_refresh()
        elif self._network_info_worker is not None:
            self._network_info_worker.cancel()

    def _capture_form_values(self) -> dict[str, Any]:
        """Capture normalized dictionary of all editable settings from form controls."""
        vals: dict[str, Any] = {}
        with contextlib.suppress(Exception):
            nick_w = self.query_one("#settings-input-nickname", Input)
            vals["nickname"] = nick_w.value.strip() or self.current_nickname

            try:
                hops_val = int(
                    self.query_one("#settings-input-hops", Input).value.strip()
                )
                vals["max_hops"] = max(1, min(7, hops_val))
            except (ValueError, TypeError):
                vals["max_hops"] = self.current_max_hops

            try:
                delay_val = int(
                    self.query_one("#settings-input-delay", Input).value.strip()
                )
                vals["delay_ms"] = max(5, min(500, delay_val))
            except (ValueError, TypeError):
                vals["delay_ms"] = self.current_delay_ms

            vals["transport"] = (
                "lan"
                if self.query_one("#radio-transport-lan", RadioButton).value
                else "bluetooth"
            )
            with contextlib.suppress(NoMatches):
                vals["lan_discovery_port"] = self.query_one(
                    "#settings-input-udp-port", Input
                ).value.strip()
                vals["lan_tcp_port"] = self.query_one(
                    "#settings-input-tcp-port", Input
                ).value.strip()

            kb: dict[str, str] = {}
            for action in KEYBINDING_LABELS:
                with contextlib.suppress(NoMatches):
                    inp = self.query_one(f"#settings-kb-{action}", Input)
                    k = inp.value.strip().lower()
                    if k:
                        kb[action] = k
                    else:
                        orig_kb = (
                            self._initial_snapshot.get("keybindings", {})
                            if self._initial_snapshot
                            else self.current_keybindings
                        )
                        kb[action] = orig_kb.get(
                            action, DEFAULT_KEYBINDINGS.get(action, "")
                        )
            vals["keybindings"] = kb

            vals["density"] = (
                "compact"
                if self.query_one("#radio-density-compact", RadioButton).value
                else "comfortable"
            )

            accent = "blue"
            for acc in ("blue", "cyan", "emerald", "purple"):
                if self.query_one(f"#radio-accent-{acc}", RadioButton).value:
                    accent = acc
                    break
            vals["accent"] = accent

            vals["show_timestamps"] = bool(
                self.query_one("#settings-switch-timestamps", Switch).value
            )
            vals["debug"] = bool(self.query_one("#settings-switch-debug", Switch).value)
            with contextlib.suppress(Exception):
                vals["startup"] = bool(
                    self.query_one("#settings-switch-startup", Switch).value
                )
            with contextlib.suppress(Exception):
                is_max = self.query_one("#radio-security-maximum", RadioButton).value
                vals["security_mode"] = "maximum" if is_max else "normal"
        return vals

    def _check_dirty_state(self) -> None:
        """Compare current form values against initial snapshot to set dirty state."""
        if self._is_populating or self._initial_snapshot is None:
            return
        current = self._capture_form_values()
        is_dirty = current != self._initial_snapshot
        self.has_unsaved_changes = is_dirty
        with contextlib.suppress(NoMatches):
            indicator = self.query_one(SaveStatusIndicator)
            if is_dirty:
                indicator.set_unsaved()
            else:
                indicator.set_saved()

    def _populate_initial_fields(self) -> None:
        """Populate current configuration into all UI controls."""
        self._is_populating = True
        cfg = self._custom_config or getattr(self.app, "config", None) or AppConfig()
        coord = getattr(self.app, "coordinator", None)
        storage = (
            self._custom_storage
            or getattr(self.app, "storage", None)
            or FileConfigStorage()
        )

        # Nickname resolution: prioritize explicit argument, then coordinator, then config
        if self.current_nickname and self.current_nickname != "Anonymous":
            nick = self.current_nickname
        elif (
            coord and getattr(coord, "nickname", None) and coord.nickname != "Anonymous"
        ):
            nick = coord.nickname
        elif cfg.nickname and cfg.nickname != "Anonymous":
            nick = cfg.nickname
        else:
            nick = self.current_nickname or "Anonymous"
        self.current_nickname = nick

        # Transport resolution: prioritize configured transport
        if cfg.transport:
            self.current_transport = cfg.transport
        elif coord and hasattr(coord, "active_transport_name"):
            self.current_transport = coord.active_transport_name

        # Max hops & delay & appearance from config
        self.current_max_hops = cfg.max_hops
        self.current_delay_ms = cfg.inter_fragment_delay_ms
        self.current_density = cfg.density
        self.current_accent = cfg.accent
        self.current_show_timestamps = cfg.show_timestamps
        self.current_debug = cfg.debug
        self.current_security_mode = cfg.security_mode

        try:
            # 1. General Configuration
            self.query_one(
                "#settings-input-nickname", Input
            ).value = self.current_nickname
            self.query_one("#settings-input-hops", Input).value = str(
                self.current_max_hops
            )
            self.query_one("#settings-input-delay", Input).value = str(
                self.current_delay_ms
            )
            is_lan = self.current_transport == "lan"
            self.query_one("#radio-transport-lan", RadioButton).value = is_lan
            self.query_one("#radio-transport-bluetooth", RadioButton).value = not is_lan

            # 2. Identity & Security displays
            pid = coord.local_identity.peer_id_hex if coord else ""
            fp = coord.local_identity.fingerprint if coord else ""
            if not pid or not fp:
                with contextlib.suppress(Exception):
                    ident = storage.load_identity()
                    if ident:
                        pid = ident.peer_id_hex
                        fp = ident.fingerprint
            if not pid:
                pid = "Unavailable"
            if not fp:
                fp = "Unavailable"

            self.query_one("#settings-static-peer-id", Static).update(
                f"[dim #58a6ff]{pid}[/dim #58a6ff]"
            )
            self.query_one("#settings-static-fingerprint", Static).update(
                f"[dim #e6edf3]{fp}[/dim #e6edf3]"
            )
            ident_path = str(
                getattr(
                    storage, "identity_path", Path.home() / ".bitchat" / "identity.json"
                )
            )
            with contextlib.suppress(NoMatches):
                self.query_one("#settings-static-storage-path", Static).update(
                    f"[dim #8b949e]{ident_path}[/dim #8b949e]"
                )
            with contextlib.suppress(NoMatches):
                self.query_one("#radio-security-normal", RadioButton).value = (
                    self.current_security_mode != "maximum"
                )
                self.query_one("#radio-security-maximum", RadioButton).value = (
                    self.current_security_mode == "maximum"
                )

            # 3. Bluetooth / BLE parameters
            ble_backend = (
                "Windows WinRT BLE" if sys.platform == "win32" else "Linux BlueZ D-Bus"
            )
            with contextlib.suppress(NoMatches):
                self.query_one("#settings-static-ble-backend", Static).update(
                    f"[dim #e6edf3]{ble_backend}[/dim #e6edf3]"
                )
                status_text = (
                    "Operational"
                    if (coord and getattr(coord, "ble_status", "") == "ready")
                    else "Standby"
                )
                self.query_one("#settings-static-ble-peripheral", Static).update(
                    f"[dim #e6edf3]{status_text}[/dim #e6edf3]"
                )
                self.query_one("#settings-static-ble-central", Static).update(
                    "[dim #e6edf3]Active / Scanning[/dim #e6edf3]"
                )

            # 4. LAN Networking parameters and read-only OS information
            with contextlib.suppress(NoMatches):
                self.query_one("#settings-input-udp-port", Input).value = str(
                    cfg.lan_discovery_port
                )
                self.query_one("#settings-input-tcp-port", Input).value = str(
                    cfg.lan_tcp_port
                )
                self._render_network_information()

            # 5. Notifications
            self.query_one(
                "#settings-switch-timestamps", Switch
            ).value = self.current_show_timestamps

            # 6. Appearance
            is_compact = self.current_density == "compact"
            self.query_one("#radio-density-compact", RadioButton).value = is_compact
            self.query_one(
                "#radio-density-comfortable", RadioButton
            ).value = not is_compact

            for acc in ("blue", "cyan", "emerald", "purple"):
                with contextlib.suppress(NoMatches):
                    self.query_one(f"#radio-accent-{acc}", RadioButton).value = (
                        self.current_accent == acc
                    )

            # 7. Startup & Behavior
            with contextlib.suppress(Exception):
                if sys.platform == "win32":
                    from bitchat.platform.startup import is_startup_enabled

                    self.query_one(
                        "#settings-switch-startup", Switch
                    ).value = is_startup_enabled()
                    self.query_one("#settings-static-startup-note", Static).update(
                        "[dim #8b949e]Registers BitChat shortcut in Windows user Startup folder.[/dim #8b949e]"
                    )
                else:
                    sw = self.query_one("#settings-switch-startup", Switch)
                    sw.value = False
                    sw.disabled = True
                    self.query_one("#settings-static-startup-note", Static).update(
                        "[dim #8b949e]Startup shortcut is supported on Windows (systemd service recommended on Linux).[/dim #8b949e]"
                    )

            # 8. Advanced: Debug & Keybindings
            self.query_one("#settings-switch-debug", Switch).value = cfg.debug

            for action in KEYBINDING_LABELS:
                val = self.current_keybindings.get(
                    action, DEFAULT_KEYBINDINGS.get(action, "")
                )
                with contextlib.suppress(NoMatches):
                    self.query_one(f"#settings-kb-{action}", Input).value = val

        except Exception as e:
            logger.debug("Failed populating settings fields: %s", e)
        finally:
            self._is_populating = False
            self._initial_snapshot = self._capture_form_values()
            self.has_unsaved_changes = False
            with contextlib.suppress(NoMatches):
                self.query_one(SaveStatusIndicator).set_saved()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._check_dirty_state()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        self._check_dirty_state()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        self._check_dirty_state()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("btn-cat-"):
            cat = bid.replace("btn-cat-", "")
            self.selected_category = cat
            self.switch_category(cat)
            event.button.focus()
        elif bid == "btn-settings-network-refresh":
            self._schedule_network_information_refresh(force=True)
        elif bid == "btn-settings-network-retry":
            coord = getattr(self.app, "coordinator", None)
            if coord is not None and hasattr(coord, "switch_transport"):
                await coord.switch_transport("lan")
                self._schedule_network_information_refresh(force=True)
        elif bid in ("btn-settings-cancel", "btn-settings-back"):
            self._handle_cancel_or_back()
        elif bid == "btn-settings-restore-defaults":
            self._restore_defaults()
        elif bid == "btn-settings-save":
            self._save_settings()

    def _restore_defaults(self) -> None:
        """Reset inputs to documented factory defaults and recalculate dirty state."""
        try:
            self.query_one("#settings-input-nickname", Input).value = "Anonymous"
            self.query_one("#settings-input-hops", Input).value = "3"
            self.query_one("#settings-input-delay", Input).value = "20"
            self.query_one("#radio-transport-bluetooth", RadioButton).value = True
            for action, default_key in DEFAULT_KEYBINDINGS.items():
                with contextlib.suppress(NoMatches):
                    self.query_one(f"#settings-kb-{action}", Input).value = default_key
            self.query_one("#settings-switch-timestamps", Switch).value = True
            self.query_one("#radio-density-comfortable", RadioButton).value = True
            self.query_one("#radio-accent-blue", RadioButton).value = True
            self.query_one("#settings-switch-debug", Switch).value = False
            with contextlib.suppress(NoMatches):
                self.query_one("#radio-security-normal", RadioButton).value = True
                self.query_one("#radio-security-maximum", RadioButton).value = False

            hint = self.query_one("#settings-hint", Static)
            hint.update(
                "[bold #58a6ff]Settings restored to factory defaults. "
                "Click 'Save' to persist.[/bold #58a6ff]"
            )
        except Exception as e:
            logger.debug("Failed restoring settings defaults: %s", e)
        finally:
            self._check_dirty_state()

    def _save_settings(self) -> None:
        """Validate, persist safely to disk, and transition save indicator."""
        try:
            indicator = self.query_one(SaveStatusIndicator)
            hint = self.query_one("#settings-hint", Static)
        except NoMatches:
            return

        nick_input = self.query_one("#settings-input-nickname", Input).value.strip()
        hops_input = self.query_one("#settings-input-hops", Input).value.strip()
        delay_input = self.query_one("#settings-input-delay", Input).value.strip()

        nick = nick_input or self.current_nickname or "Anonymous"
        if len(nick) > 32:
            hint.update(
                "[bold #f85149]Error: Nickname must not exceed 32 characters.[/bold #f85149]"
            )
            indicator.set_unsaved("Validation Error")
            return

        try:
            hops = int(hops_input)
            if not (1 <= hops <= 7):
                raise ValueError
        except ValueError:
            hint.update(
                "[bold #f85149]Error: Max hops must be integer 1-7.[/bold #f85149]"
            )
            indicator.set_unsaved("Validation Error")
            return

        try:
            delay = int(delay_input)
            if not (5 <= delay <= 500):
                raise ValueError
        except ValueError:
            hint.update(
                "[bold #f85149]Error: Fragment delay must be integer 5-500 ms.[/bold #f85149]"
            )
            indicator.set_unsaved("Validation Error")
            return

        try:
            udp_port = int(self.query_one("#settings-input-udp-port", Input).value)
            tcp_port = int(self.query_one("#settings-input-tcp-port", Input).value)
            if not (1024 <= udp_port <= 65535 and 1024 <= tcp_port <= 65535):
                raise ValueError
        except (ValueError, NoMatches):
            hint.update(
                "[bold #f85149]Error: LAN ports must be integers from 1024 to 65535.[/bold #f85149]"
            )
            indicator.set_unsaved("Validation Error")
            return

        # Selected transport
        selected_transport = "bluetooth"
        with contextlib.suppress(Exception):
            radio_set = self.query_one("#settings-radio-transport", RadioSet)
            if (
                radio_set.pressed_button
                and radio_set.pressed_button.id == "radio-transport-lan"
            ):
                selected_transport = "lan"

        # Validate keybindings
        keybindings: dict[str, str] = {}
        assigned_keys: dict[str, str] = {}

        for action, label in KEYBINDING_LABELS.items():
            try:
                inp = self.query_one(f"#settings-kb-{action}", Input)
                if not inp.value.strip():
                    hint.update(
                        f"[bold #f85149]Error: Key for '{label}' cannot be empty.[/bold #f85149]"
                    )
                    inp.focus()
                    indicator.set_unsaved("Validation Error")
                    return
                try:
                    raw_key = normalize_keybinding(inp.value, action)
                except ValueError as exc:
                    hint.update(
                        f"[bold #f85149]Invalid key for '{label}': {exc}[/bold #f85149]"
                    )
                    inp.focus()
                    indicator.set_unsaved("Validation Error")
                    return

                if raw_key in assigned_keys:
                    conflict_label = assigned_keys[raw_key]
                    hint.update(
                        f"[bold #f85149]Key conflict: '{raw_key}' is assigned to both '{conflict_label}' and '{label}'.[/bold #f85149]"
                    )
                    inp.focus()
                    indicator.set_unsaved("Validation Error")
                    return

                assigned_keys[raw_key] = label
                keybindings[action] = raw_key
            except NoMatches:
                keybindings[action] = self.current_keybindings.get(
                    action, DEFAULT_KEYBINDINGS.get(action, "")
                )

        # Appearance & behavior
        density = "comfortable"
        with contextlib.suppress(Exception):
            if self.query_one("#radio-density-compact", RadioButton).value:
                density = "compact"

        accent = "blue"
        for acc in ("blue", "cyan", "emerald", "purple"):
            with contextlib.suppress(Exception):
                if self.query_one(f"#radio-accent-{acc}", RadioButton).value:
                    accent = acc
                    break

        timestamps = True
        with contextlib.suppress(Exception):
            timestamps = bool(
                self.query_one("#settings-switch-timestamps", Switch).value
            )

        debug = False
        with contextlib.suppress(Exception):
            debug = bool(self.query_one("#settings-switch-debug", Switch).value)

        # Update and atomically persist configuration
        storage: StorageInterface = (
            self._custom_storage
            or getattr(self.app, "storage", None)
            or FileConfigStorage()
        )
        cfg: AppConfig = (
            self._custom_config or getattr(self.app, "config", None) or AppConfig()
        )

        # Selected security mode
        security_mode = "normal"
        with contextlib.suppress(Exception):
            if self.query_one("#radio-security-maximum", RadioButton).value:
                security_mode = "maximum"

        cfg.nickname = nick
        cfg.max_hops = hops
        cfg.inter_fragment_delay_ms = delay
        cfg.lan_discovery_port = udp_port
        cfg.lan_tcp_port = tcp_port
        cfg.transport = selected_transport
        cfg.security_mode = security_mode
        cfg.keybindings = keybindings
        cfg.density = density
        cfg.accent = accent
        cfg.show_timestamps = timestamps
        cfg.debug = debug
        self.current_security_mode = security_mode

        try:
            storage.save_config(cfg)
        except Exception as e:
            logger.error("Failed persisting settings to disk: %s", e)
            hint.update(f"[bold #f85149]Filesystem Error: {e}[/bold #f85149]")
            indicator.set_unsaved("Save Failed!")
            return

        # Handle startup shortcut on Windows if toggled
        if sys.platform == "win32":
            try:
                startup_switch = self.query_one(
                    "#settings-switch-startup", Switch
                ).value
                from bitchat.platform.startup import (
                    disable_startup,
                    enable_startup,
                    is_startup_enabled,
                )

                if startup_switch and not is_startup_enabled():
                    enable_startup()
                elif not startup_switch and is_startup_enabled():
                    disable_startup()
            except Exception as e:
                logger.debug("Startup shortcut update note: %s", e)

        # Update coordinator state if present
        coord = getattr(self.app, "coordinator", None)
        if coord is not None:
            coord.set_nickname(nick)
            coord.mesh_router.max_relay_ttl = hops
            coord.inter_fragment_delay = delay / 1000.0
            lan_trans = getattr(coord, "_transports", {}).get("lan")
            if lan_trans is not None and not getattr(lan_trans, "is_running", False):
                lan_trans.tcp_port = tcp_port
                lan_trans.server.port = tcp_port
                lan_trans.discovery_port = udp_port
                lan_trans.discovery.discovery_port = udp_port

        # Successful save
        self.current_nickname = nick
        self.current_max_hops = hops
        self.current_delay_ms = delay
        self.current_transport = selected_transport
        self.current_keybindings = keybindings

        self._initial_snapshot = self._capture_form_values()
        self.has_unsaved_changes = False
        indicator.set_saved()
        hint.update(
            "[bold #3fb950]All changes successfully saved to disk.[/bold #3fb950]"
        )

        # Post standard event so coordinator and app update
        msg = self.SettingsSaved(
            nick,
            hops,
            delay,
            keybindings,
            transport=selected_transport,
            density=density,
            accent=accent,
        )
        self.app.post_message(msg)
        self.dismiss()

    def _handle_cancel_or_back(self) -> None:
        """Handle Cancel or Back navigation with confirmation if dirty."""
        if self.has_unsaved_changes:

            def _on_confirm(discard: bool | None) -> None:
                if discard:
                    self.has_unsaved_changes = False
                    self.dismiss()

            self.app.push_screen(UnsavedChangesModal(), _on_confirm)
        else:
            self.dismiss()

    def action_dismiss_modal(self) -> None:
        self._handle_cancel_or_back()

    def on_key(self, event: events.Key) -> None:
        """Handle category focus movement without stealing keys from form controls."""
        focused = self.focused

        # Text inputs own their arrow keys for caret movement. All other controls
        # retain normal Textual Tab / Shift+Tab and Enter behavior.
        if isinstance(focused, Input):
            return

        key = event.key
        in_navigation = self._is_within(focused, "settings-category-nav")
        in_form = self._is_within(focused, "settings-form")

        if in_navigation and key in ("up", "down"):
            self._move_category_focus(-1 if key == "up" else 1)
            event.prevent_default()
            event.stop()
            return

        if key == "left" and in_form:
            self._focus_category(self.active_category)
            self.selected_category = self.active_category
            event.prevent_default()
            event.stop()
            return

        if key == "right" and in_navigation:
            if self.selected_category != self.active_category:
                self.switch_category(self.selected_category)
            self._focus_active_category_content()
            event.prevent_default()
            event.stop()
            return


# Backward compatibility aliases
SettingsModal = SettingsScreen
