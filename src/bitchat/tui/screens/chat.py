"""ChatScreen providing active messaging interface, history, and peer sidebar."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen

from bitchat.tui.widgets.autocomplete import AutocompletePalette
from bitchat.tui.widgets.chat_view import ChatView
from bitchat.tui.widgets.header import HeaderWidget
from bitchat.tui.widgets.message_input import MessageInput
from bitchat.tui.widgets.sidebar import PeerSidebar
from bitchat.tui.widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.binding import BindingType


class ChatScreen(Screen[None]):
    """Primary chat screen containing conversation log, sidebar, and composer."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "open_home", "Dashboard", priority=False),
        Binding("f4", "open_peers", "Peers", priority=False),
    ]

    def compose(self) -> ComposeResult:
        coord = getattr(self.app, "coordinator", None)
        cfg = getattr(self.app, "config", None)
        nick = coord.nickname if coord else (cfg.nickname if cfg else "Anonymous")
        pid = coord.local_identity.peer_id_hex if coord else ""
        fp = coord.local_identity.fingerprint if coord else ""

        yield HeaderWidget(nickname=nick, peer_id_hex=pid, fingerprint=fp)
        with Horizontal(id="main-body"):
            yield PeerSidebar(nickname=nick, peer_id_hex=pid, fingerprint=fp)
            with Vertical(id="chat-column"):
                yield ChatView(id="chat-view")
                with Vertical(id="input-container"):
                    yield AutocompletePalette()
                    yield MessageInput()
        yield StatusBar()

    def action_open_home(self) -> None:
        """Return to dashboard if input is empty."""
        msg_inp = self.query_one(MessageInput)
        if not msg_inp.value and hasattr(self.app, "action_open_home"):
            self.app.action_open_home()  # type: ignore[attr-defined]

    def action_open_peers(self) -> None:
        """Open peer discovery and inspection screen."""
        if hasattr(self.app, "action_open_peers"):
            self.app.action_open_peers()  # type: ignore[attr-defined]
