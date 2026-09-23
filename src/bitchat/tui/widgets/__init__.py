"""BitChat TUI widgets package."""

from bitchat.tui.widgets.autocomplete import AutocompletePalette
from bitchat.tui.widgets.chat_view import ChatView
from bitchat.tui.widgets.header import HeaderWidget
from bitchat.tui.widgets.message_input import MessageInput
from bitchat.tui.widgets.sidebar import PeerSidebar
from bitchat.tui.widgets.status_bar import StatusBar

__all__ = [
    "AutocompletePalette",
    "ChatView",
    "HeaderWidget",
    "MessageInput",
    "PeerSidebar",
    "StatusBar",
]
