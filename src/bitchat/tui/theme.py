"""Visual theme, color constants, and TCSS definitions for BitChat TUI."""

from __future__ import annotations

# Theme color palette (GitHub Dark / JetBrains Dark inspired)
COLOR_BG_DARK = "#0d1117"
COLOR_PANEL_BG = "#161b22"
COLOR_BORDER = "#30363d"
COLOR_BORDER_FOCUS = "#58a6ff"
COLOR_TEXT_PRIMARY = "#e6edf3"
COLOR_TEXT_MUTED = "#8b949e"
COLOR_ACCENT = "#58a6ff"
COLOR_SUCCESS = "#3fb950"
COLOR_WARNING = "#d29922"
COLOR_ERROR = "#f85149"
COLOR_SECURITY = "#a371f7"

TCSS_STYLES = """
Screen {
    background: #0d1117;
    color: #e6edf3;
    layout: vertical;
}

#top-header {
    dock: top;
    height: 3;
    background: #161b22;
    border-bottom: solid #30363d;
    padding: 0 1;
    layout: horizontal;
    align: left middle;
}

#header-title {
    text-style: bold;
    color: #58a6ff;
    width: auto;
}

#header-version {
    color: #8b949e;
    width: auto;
    margin-left: 1;
}

#header-status {
    width: auto;
    margin-left: 2;
    color: #3fb950;
    text-style: bold;
}

#header-identity {
    dock: right;
    width: auto;
    color: #8b949e;
}

#main-body {
    height: 1fr;
    layout: horizontal;
}

#sidebar {
    width: 32;
    min-width: 24;
    max-width: 38;
    background: #161b22;
    border-right: solid #30363d;
    padding: 0 1;
    layout: vertical;
}

.sidebar-title {
    text-style: bold;
    color: #58a6ff;
    margin-top: 1;
    margin-bottom: 0;
}

#identity-card {
    height: auto;
    background: #0d1117;
    border: solid #30363d;
    padding: 1;
    margin-top: 1;
    margin-bottom: 1;
}

.peer-list-container {
    height: 1fr;
    layout: vertical;
}

.peer-list-view {
    height: 1fr;
    background: #161b22;
    border: none;
}

.peer-item {
    height: auto;
    padding: 0 1;
    margin-bottom: 0;
}

#chat-column {
    width: 1fr;
    height: 1fr;
    layout: vertical;
    background: #0d1117;
    padding: 0 1;
}

#chat-log {
    height: 1fr;
    background: #0d1117;
    color: #e6edf3;
    border: none;
    padding: 0 1;
    scrollbar-size-vertical: 1;
}

#input-container {
    dock: bottom;
    height: auto;
    layout: vertical;
}

#autocomplete-popup {
    height: auto;
    max-height: 8;
    background: #161b22;
    border: solid #58a6ff;
    padding: 0 1;
    display: none;
    margin-bottom: 0;
}

.autocomplete-item {
    height: 1;
    padding: 0;
}

.autocomplete-item-selected {
    background: #1f6feb;
    color: #ffffff;
    text-style: bold;
}

#message-input {
    height: 3;
    background: #161b22;
    border: solid #30363d;
    color: #e6edf3;
    padding: 0 1;
}

#message-input:focus {
    border: solid #58a6ff;
}

#status-bar {
    dock: bottom;
    height: 1;
    background: #161b22;
    color: #8b949e;
    padding: 0 1;
    layout: horizontal;
}

#status-left {
    width: 1fr;
    color: #8b949e;
}

#status-right {
    width: auto;
    color: #8b949e;
}

/* Help Modal Screen */
HelpScreen {
    align: center middle;
    background: rgba(0, 0, 0, 0.75);
}

#help-dialog {
    width: 70;
    max-width: 90%;
    height: auto;
    max-height: 85%;
    background: #161b22;
    border: solid #58a6ff;
    padding: 1 2;
}

#help-title {
    text-style: bold;
    color: #58a6ff;
    margin-bottom: 1;
}

#help-table {
    height: auto;
    max-height: 20;
    background: #0d1117;
    border: solid #30363d;
    margin-bottom: 1;
}
"""
