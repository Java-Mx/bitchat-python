"""Chat view widget presenting formatted conversation streams."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import RichLog

from bitchat.tui.theme import (
    COLOR_SELF_IDENTITY,
    get_peer_color,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult


@dataclass(frozen=True)
class ChatMessageRecord:
    """Structured record of a conversation or system event."""

    kind: str  # "chat", "system", "security", "error"
    sender: str
    text: str
    is_encrypted: bool = False
    is_self: bool = False
    timestamp: float = field(default_factory=time.time)


class ChatView(Widget):
    """Conversation stream widget displaying formatted messages and alerts."""

    channel_name: reactive[str] = reactive("#public")
    show_timestamps: reactive[bool] = reactive(True)
    compact_mode: reactive[bool] = reactive(False)

    MAX_HISTORY: int = 1000

    def __init__(self, channel_name: str = "#public", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.channel_name = channel_name
        self._message_history: list[ChatMessageRecord] = []
        self._mounted = False

    def on_mount(self) -> None:
        self.border_title = f"Conversation ({self.channel_name})"
        self._mounted = True

    def watch_channel_name(self, new_val: str) -> None:
        self.border_title = f"Conversation ({new_val})"

    def watch_show_timestamps(self, new_val: bool) -> None:
        if self._mounted:
            self.re_render_all()

    def watch_compact_mode(self, new_val: bool) -> None:
        if self._mounted:
            self.re_render_all()

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

    def re_render_all(self) -> None:
        """Clear and re-render all messages with active density and timestamps."""
        try:
            log = self.rich_log
            log.clear()
            for rec in self._message_history:
                self._render_record(rec)
        except Exception:
            pass

    def _render_record(self, record: ChatMessageRecord) -> None:
        """Render a single message record to the RichLog."""
        ts_str = time.strftime("%H:%M", time.localtime(record.timestamp))
        match record.kind:
            case "chat":
                if record.is_self:
                    sender_color = COLOR_SELF_IDENTITY
                    sender_name = "You"
                else:
                    sender_color = get_peer_color(record.sender)
                    sender_name = record.sender

                if record.is_encrypted:
                    type_tag = ("[🔒 DM]", "bold #bc8cff")
                else:
                    type_tag = ("[Public]", "dim #57606a")

                header = Text()
                header.append(sender_name, style=f"bold {sender_color}")
                header.append(" ")
                header.append(*type_tag)
                if self.show_timestamps:
                    header.append(f" • {ts_str}", style="dim #57606a")

                width = max(1, self.rich_log.scrollable_content_region.width)
                prefix_width = header.cell_len + 2
                header_wraps = prefix_width >= width
                continuation_indent = " " * min(
                    2 if header_wraps else prefix_width, width - 1
                )
                body_width = max(1, width - len(continuation_indent))
                wrapped_lines = (
                    list(header.wrap(self.app.console, width, overflow="fold"))
                    if header_wraps
                    else []
                )
                first_line = not header_wraps
                for logical_line in record.text.split("\n"):
                    body_lines = (
                        Text(logical_line).wrap(
                            self.app.console, body_width, overflow="fold"
                        )
                        if logical_line
                        else [Text()]
                    )
                    for body_line in body_lines:
                        line = Text()
                        if first_line and prefix_width < width:
                            line.append_text(header)
                            line.append(": ")
                        else:
                            line.append(continuation_indent)
                        line.append_text(body_line)
                        wrapped_lines.append(line)
                        first_line = False

                aligned_message = Text(
                    justify="right" if record.is_self else "left",
                    overflow="fold",
                )
                for index, line in enumerate(wrapped_lines):
                    if index:
                        aligned_message.append("\n")
                    aligned_message.append_text(line)
                self.rich_log.write(aligned_message, width=width)

            case "system":
                ts_part = (
                    f"[dim #57606a][{ts_str}][/dim #57606a] "
                    if self.show_timestamps
                    else ""
                )
                line = (
                    f"{ts_part}[bold #58a6ff]●[/bold #58a6ff] "
                    f"[#8b949e]{record.text}[/#8b949e]"
                )
                self.rich_log.write(line)

            case "security":
                ts_part = (
                    f"[dim #57606a][{ts_str}][/dim #57606a] "
                    if self.show_timestamps
                    else ""
                )
                line = (
                    f"{ts_part}[bold #bc8cff]●[/bold #bc8cff] "
                    f"[bold #bc8cff]Security:[/bold #bc8cff] "
                    f"[#8b949e]{record.text}[/#8b949e]"
                )
                self.rich_log.write(line)

            case "error":
                ts_part = (
                    f"[dim #57606a][{ts_str}][/dim #57606a] "
                    if self.show_timestamps
                    else ""
                )
                line = (
                    f"{ts_part}[bold #f85149]![/bold #f85149] "
                    f"[#f85149]{record.text}[/#f85149]"
                )
                self.rich_log.write(line)

    def _append_record(self, record: ChatMessageRecord) -> None:
        self._message_history.append(record)
        if len(self._message_history) > self.MAX_HISTORY:
            self._message_history.pop(0)
        self._render_record(record)

    def add_chat_message(
        self,
        sender: str,
        text: str,
        is_encrypted: bool,
        is_self: bool = False,
    ) -> None:
        """Format and write a user message."""
        rec = ChatMessageRecord(
            kind="chat",
            sender=sender,
            text=text,
            is_encrypted=is_encrypted,
            is_self=is_self,
        )
        self._append_record(rec)

    def add_system_message(self, text: str) -> None:
        """Format and write an informative system event."""
        rec = ChatMessageRecord(
            kind="system",
            sender="system",
            text=text,
        )
        self._append_record(rec)

    def add_security_event(self, text: str) -> None:
        """Format and write a security verification event."""
        rec = ChatMessageRecord(
            kind="security",
            sender="security",
            text=text,
            is_encrypted=True,
        )
        self._append_record(rec)

    def add_error_message(self, text: str) -> None:
        """Format and write an error alert."""
        rec = ChatMessageRecord(
            kind="error",
            sender="error",
            text=text,
        )
        self._append_record(rec)

    def clear_log(self) -> None:
        """Clear all messages from the log and memory buffer."""
        self._message_history.clear()
        self.rich_log.clear()

    def page_up(self) -> None:
        """Scroll chat view up one page."""
        self.rich_log.scroll_page_up()

    def page_down(self) -> None:
        """Scroll chat view down one page."""
        self.rich_log.scroll_page_down()
