"""Minimal header bar for the BitChat TUI."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

if TYPE_CHECKING:
    from textual.app import ComposeResult


class HeaderWidget(Widget):
    """Top bar displaying branding, connection status, and identity info."""

    DEFAULT_CSS = """
    HeaderWidget {
        height: 3;
        background: #161b22;
        border-bottom: solid #30363d;
        padding: 0 1;
        layout: horizontal;
        align: left middle;
    }
    """

    status_text: reactive[str] = reactive("○ Scanning...")
    peer_count: reactive[int] = reactive(0)
    nickname: reactive[str] = reactive("Anonymous")
    peer_id_hex: reactive[str] = reactive("")
    fingerprint: reactive[str] = reactive("")

    def __init__(
        self,
        nickname: str = "Anonymous",
        peer_id_hex: str = "",
        fingerprint: str = "",
        **kwargs,
    ) -> None:
        super().__init__(id="top-header", **kwargs)
        self.nickname = nickname
        self.peer_id_hex = peer_id_hex
        self.fingerprint = fingerprint

    def compose(self) -> ComposeResult:
        yield Label("BitChat", id="header-title")
        yield Label("v0.1.0", id="header-version")
        yield Label(self._format_status(), id="header-status")
        yield Label(self._format_identity(), id="header-identity")

    def _format_status(self) -> str:
        if self.peer_count > 0:
            return f"● Connected ({self.peer_count} peers)"
        return f"{self.status_text}"

    def _format_identity(self) -> str:
        short_id = self.peer_id_hex[:8] if self.peer_id_hex else "--------"
        short_fp = self.fingerprint[:12] + "..." if self.fingerprint else "--------"
        return f"Nick: {self.nickname} | ID: {short_id} | FP: {short_fp}"

    def watch_status_text(self, new_val: str) -> None:
        """Update status label reactively."""
        with contextlib.suppress(Exception):
            lbl = self.query_one("#header-status", Label)
            lbl.update(self._format_status())

    def watch_peer_count(self, new_count: int) -> None:
        """Update status label reactively."""
        with contextlib.suppress(Exception):
            lbl = self.query_one("#header-status", Label)
            lbl.update(self._format_status())

    def watch_nickname(self, new_nick: str) -> None:
        """Update identity label reactively."""
        with contextlib.suppress(Exception):
            lbl = self.query_one("#header-identity", Label)
            lbl.update(self._format_identity())
