"""Peer security, cryptographic identity, and diagnostics modal screen."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, ClassVar

from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from bitchat.tui.theme import get_peer_color

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.binding import BindingType


class PeerInfoModal(ModalScreen[None]):
    """Modal displaying full peer ID, fingerprint, and Noise XX security state."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "dismiss_modal", "Close"),
        ("q", "dismiss_modal", "Close"),
        ("enter", "dismiss_modal", "Close"),
    ]

    class StartDirectMessage(Message):
        """Emitted when user chooses to initiate DM with this peer."""

        def __init__(self, nickname: str, peer_id_hex: str) -> None:
            super().__init__()
            self.nickname = nickname
            self.peer_id_hex = peer_id_hex

    def __init__(
        self,
        nickname: str,
        peer_id_hex: str,
        fingerprint: str = "",
        address: str = "",
        is_connected: bool = True,
        is_encrypted: bool = True,
        rssi: int | None = None,
        last_seen: str = "Active",
        cipher_suite: str = "ChaCha20-Poly1305 / SHA-256 / X25519",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.peer_nickname = nickname or "Unknown"
        self.peer_id_hex = peer_id_hex or "Unknown"
        self.fingerprint = fingerprint or "Not available (Handshake pending)"
        self.address = address or "Mesh Multi-Hop"
        self.is_connected = is_connected
        self.is_encrypted = is_encrypted
        self.rssi = rssi
        self.last_seen = last_seen
        self.cipher_suite = cipher_suite

    def compose(self) -> ComposeResult:
        peer_color = get_peer_color(self.peer_nickname)
        status_dot = "●" if self.is_connected else "○"
        status_color = "#3fb950" if self.is_connected else "#d29922"
        status_text = (
            "Connected (BLE Central/Peripheral)"
            if self.is_connected
            else "Discovered Nearby"
        )

        enc_badge = (
            "[bold #3fb950]Established & Verified (Noise XX)[/bold #3fb950]"
            if self.is_encrypted
            else "[dim #d29922]Handshake Pending / Public[/dim #d29922]"
        )

        rssi_str = f"{self.rssi} dBm" if self.rssi is not None else "Multi-Hop Mesh"

        with Vertical(id="peer-info-dialog"):
            yield Label(
                "[bold #58a6ff]Peer Identity & Cryptographic Diagnostics"
                "[/bold #58a6ff]",
                id="peer-info-title",
            )

            with Vertical(id="peer-info-card"):
                yield Static(
                    f"[bold {peer_color}]{self.peer_nickname}[/bold {peer_color}]  "
                    f"[{status_color}]{status_dot} {status_text}[/{status_color}]\n"
                    f"[dim #57606a]Transport: {self.address}  │  Signal: {rssi_str}\n"
                    f"Status: {self.last_seen}[/dim #57606a]",
                    classes="peer-info-section",
                )

                yield Static(
                    f"[bold #8b949e]Noise XX Protocol State[/bold #8b949e]\n"
                    f"Session State: {enc_badge}\n"
                    f"Cipher Suite:  [dim #e6edf3]{self.cipher_suite}[/dim #e6edf3]\n"
                    "Forward Secrecy: [bold #3fb950]Active "
                    "(Ephemeral ECDH per-session keys)[/bold #3fb950]",
                    classes="peer-info-section",
                )

                yield Static(
                    "[bold #8b949e]Identity Public Key Fingerprint (SHA-256)"
                    "[/bold #8b949e]\n"
                    f"[dim #79c0ff]{self.fingerprint}[/dim #79c0ff]\n"
                    "[dim #57606a]Compare this 64-char fingerprint out-of-band "
                    "to verify authenticity.[/dim #57606a]",
                    classes="peer-info-section",
                )

                yield Static(
                    "[bold #8b949e]Full Peer Identifier "
                    "(32-byte Ed25519 Public ID)[/bold #8b949e]\n"
                    f"[dim #e6edf3]{self.peer_id_hex}[/dim #e6edf3]",
                    classes="peer-info-section",
                )

            with Horizontal(id="peer-info-actions"):
                yield Button("Direct Message", id="btn-peer-dm", classes="action-btn")
                yield Button(
                    "Copy Fingerprint", id="btn-peer-copy-fp", classes="action-btn"
                )
                yield Button("Close (Esc)", id="btn-peer-close", classes="action-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-peer-close":
            self.dismiss()
        elif event.button.id == "btn-peer-copy-fp":
            self._copy_fingerprint()
        elif event.button.id == "btn-peer-dm":
            self.post_message(
                self.StartDirectMessage(self.peer_nickname, self.peer_id_hex)
            )
            self.dismiss()

    def _copy_fingerprint(self) -> None:
        """Copy fingerprint to system clipboard if supported."""
        with contextlib.suppress(Exception):
            self.app.copy_to_clipboard(self.fingerprint)
        with contextlib.suppress(Exception):
            btn = self.query_one("#btn-peer-copy-fp", Button)
            btn.label = "Copied!"

    def action_dismiss_modal(self) -> None:
        self.dismiss()
