"""Chat view widget presenting formatted conversation streams."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from textual.widget import Widget
from textual.widgets import RichLog

if TYPE_CHECKING:
    from textual.app import ComposeResult


class ChatView(Widget):
    """Conversation stream widget displaying formatted messages and alerts."""

    DEFAULT_CSS = """
    ChatView {
        height: 1fr;
        background: #0d1117;
        layout: vertical;
    }
    """

    def compose(self) -> ComposeResult:
        yield RichLog(id="chat-log", highlight=False, markup=True, wrap=True)

    @property
    def rich_log(self) -> RichLog:
        """Return the underlying RichLog widget."""
        return self.query_one("#chat-log", RichLog)

    def _format_timestamp(self) -> str:
        return time.strftime("%H:%M")

    def add_chat_message(
        self,
        sender: str,
        text: str,
        is_encrypted: bool,
        is_self: bool = False,
    ) -> None:
        """Format and write a user message to the chat log."""
        ts = self._format_timestamp()
        if is_self:
            sender_badge = "[bold cyan]You[/bold cyan]"
        else:
            sender_badge = f"[bold #58a6ff]{sender}[/bold #58a6ff]"

        if is_encrypted:
            type_tag = "[bold #a371f7][🔒 DM][/bold #a371f7]"
        else:
            type_tag = "[dim][Public][/dim]"

        line = f"[dim][{ts}][/dim] {type_tag} {sender_badge}: {text}"
        self.rich_log.write(line)

    def add_system_message(self, text: str) -> None:
        """Format and write an informative system message."""
        ts = self._format_timestamp()
        line = f"[dim][{ts}][/dim] [bold #d29922][System][/bold #d29922] {text}"
        self.rich_log.write(line)

    def add_security_event(self, text: str) -> None:
        """Format and write a security verification or Noise handshake event."""
        ts = self._format_timestamp()
        line = f"[dim][{ts}][/dim] [bold #3fb950][Security][/bold #3fb950] {text}"
        self.rich_log.write(line)

    def add_error_message(self, text: str) -> None:
        """Format and write an error alert."""
        ts = self._format_timestamp()
        line = f"[dim][{ts}][/dim] [bold #f85149][Error][/bold #f85149] {text}"
        self.rich_log.write(line)

    def clear_log(self) -> None:
        """Clear all messages from the log."""
        self.rich_log.clear()
