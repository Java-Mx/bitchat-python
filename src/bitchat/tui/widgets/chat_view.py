"""Chat view widget presenting formatted conversation streams."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import RichLog

from bitchat.tui.theme import (
    COLOR_SELF_IDENTITY,
    get_peer_color,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult


class ChatView(Widget):
    """Conversation stream widget displaying formatted messages and alerts."""

    channel_name: reactive[str] = reactive("#public")

    def __init__(self, channel_name: str = "#public", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.channel_name = channel_name

    def on_mount(self) -> None:
        self.border_title = f"Conversation [{self.channel_name}]"

    def watch_channel_name(self, new_val: str) -> None:
        self.border_title = f"Conversation [{new_val}]"

    def compose(self) -> ComposeResult:
        yield RichLog(
            id="chat-log",
            highlight=False,
            markup=True,
            wrap=True,
            auto_scroll=True,
        )

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
        """Format and write a user message with two-tier visual hierarchy."""
        ts = self._format_timestamp()
        if is_self:
            sender_color = COLOR_SELF_IDENTITY
            sender_name = "You"
        else:
            sender_color = get_peer_color(sender)
            sender_name = sender

        if is_encrypted:
            type_tag = "[bold #bc8cff][🔒 DM][/bold #bc8cff]"
        else:
            type_tag = "[dim #57606a][Public][/dim #57606a]"

        header_line = (
            f"[bold {sender_color}]{sender_name}[/bold {sender_color}] "
            f"{type_tag} [dim #57606a]• {ts}[/dim #57606a]"
        )
        body_line = f"  {text}"
        self.rich_log.write(f"{header_line}\n{body_line}")

    def add_system_message(self, text: str) -> None:
        """Format and write an informative system event."""
        ts = self._format_timestamp()
        line = (
            f"[dim #57606a][{ts}][/dim #57606a] [bold #388bfd]●[/bold #388bfd] "
            f"[#8b949e]{text}[/#8b949e]"
        )
        self.rich_log.write(line)

    def add_security_event(self, text: str) -> None:
        """Format and write a security verification or Noise handshake event."""
        ts = self._format_timestamp()
        line = (
            f"[dim #57606a][{ts}][/dim #57606a] [bold #bc8cff]●[/bold #bc8cff] "
            f"[bold #bc8cff]Security:[/] [#8b949e]{text}[/#8b949e]"
        )
        self.rich_log.write(line)

    def add_error_message(self, text: str) -> None:
        """Format and write an error alert."""
        ts = self._format_timestamp()
        line = (
            f"[dim #57606a][{ts}][/dim #57606a] [bold #f85149]![/bold #f85149] "
            f"[#f85149]{text}[/#f85149]"
        )
        self.rich_log.write(line)

    def clear_log(self) -> None:
        """Clear all messages from the log."""
        self.rich_log.clear()

    def page_up(self) -> None:
        """Scroll chat view up one page."""
        self.rich_log.scroll_page_up()

    def page_down(self) -> None:
        """Scroll chat view down one page."""
        self.rich_log.scroll_page_down()
