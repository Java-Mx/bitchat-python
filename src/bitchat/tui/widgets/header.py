"""Minimal, edge-to-edge application header for BitChat TUI."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

if TYPE_CHECKING:
    from textual.app import ComposeResult


class HeaderWidget(Widget):
    """Top application header bar displaying branding, status, and telemetry."""

    status_text: reactive[str] = reactive("○ Scanning...")
    peer_count: reactive[int] = reactive(0)
    nickname: reactive[str] = reactive("Anonymous")
    peer_id_hex: reactive[str] = reactive("")
    fingerprint: reactive[str] = reactive("")
    channel_name: reactive[str] = reactive("#public")

    def __init__(
        self,
        nickname: str = "Anonymous",
        peer_id_hex: str = "",
        fingerprint: str = "",
        channel_name: str = "#public",
        **kwargs: Any,
    ) -> None:
        super().__init__(id="top-header", **kwargs)
        self.nickname = nickname
        self.peer_id_hex = peer_id_hex
        self.fingerprint = fingerprint
        self.channel_name = channel_name

    def compose(self) -> ComposeResult:
        yield Label("● BitChat", id="header-brand")
        yield Label("v0.1.0", id="header-version")
        yield Label("Secure • BLE Mesh", id="header-channel")
        yield Label(self._format_status(), id="header-status")
        yield Label(self._format_identity(), id="header-identity")

    def _format_status(self) -> str:
        if self.peer_count > 0:
            return f"● {self.peer_count} peer{'s' if self.peer_count != 1 else ''}"
        return self.status_text

    def _format_identity(self) -> str:
        short_id = self.peer_id_hex[:8] if self.peer_id_hex else "--------"
        short_fp = self.fingerprint[:12] + "..." if self.fingerprint else "--------"
        return f"{self.nickname} [{short_id} • {short_fp}]"

    def watch_status_text(self, new_val: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#header-status", Label).update(self._format_status())

    def watch_peer_count(self, new_count: int) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#header-status", Label).update(self._format_status())

    def watch_nickname(self, new_nick: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#header-identity", Label).update(self._format_identity())

    def watch_peer_id_hex(self, new_val: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#header-identity", Label).update(self._format_identity())

    def watch_fingerprint(self, new_val: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#header-identity", Label).update(self._format_identity())
