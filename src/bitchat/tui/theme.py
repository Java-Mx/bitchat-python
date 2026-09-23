"""Visual theme, design tokens, and deterministic identity colors for BitChat TUI."""

from __future__ import annotations

import zlib
from pathlib import Path

# ==============================================================================
# 1. Black Family (Backgrounds, deepest surfaces, negative space, inactive areas)
# ==============================================================================
COLOR_BG = "#080a0f"
COLOR_SURFACE = "#0f121c"
COLOR_SURFACE_ACTIVE = "#141824"
COLOR_SURFACE_SELECTED = "#1e2438"
COLOR_SURFACE_CARD = "#121520"
COLOR_BORDER = "#22283a"
COLOR_BORDER_MUTED = "#1b2030"
COLOR_TEXT_PRIMARY = "#e6edf3"
COLOR_TEXT_MUTED = "#8b949e"
COLOR_TEXT_DIM = "#57606a"

# ==============================================================================
# 2. Blue Family (Primary interactive accent, active items, borders, focus)
# ==============================================================================
COLOR_BLUE_ACCENT = "#58a6ff"
COLOR_BLUE_INTERACTIVE = "#388bfd"
COLOR_BLUE_ACTIVE = "#1f6feb"
COLOR_BLUE_SURFACE = "#152238"
COLOR_BORDER_FOCUS = "#388bfd"
COLOR_BORDER_FOCUS_SUBTLE = "#28334e"

# ==============================================================================
# 3. Purple Family (Secondary accent, system metadata, command palette, Noise)
# ==============================================================================
COLOR_PURPLE_ACCENT = "#bc8cff"
COLOR_PURPLE_SUBTLE = "#a371f7"
COLOR_PURPLE_DIM = "#8957e5"
COLOR_PURPLE_SURFACE = "#271b3d"

# ==============================================================================
# 4. Identity / People Colors (Deterministic, restrained set of 8 distinct colors)
# ==============================================================================
PEER_IDENTITY_COLORS: tuple[str, ...] = (
    "#39c5cf",  # Cyan
    "#56d364",  # Emerald
    "#e3b341",  # Amber
    "#f778ba",  # Pink
    "#79c0ff",  # Sky
    "#d2a8ff",  # Lavender
    "#f0883e",  # Coral
    "#ff7b72",  # Rose
)
COLOR_SELF_IDENTITY = "#79c0ff"

# ==============================================================================
# 5. Semantic Status Colors (Single restrained family for exceptional states)
# ==============================================================================
COLOR_STATUS_SUCCESS = "#3fb950"  # Connected, secure, verified
COLOR_STATUS_WARNING = "#d29922"  # Connecting, scanning, warning
COLOR_STATUS_ERROR = "#f85149"  # Disconnected, handshake error, failure

# ==============================================================================
# 6. Accent Themes (Strict 5-Family Preserving Accent Profiles)
# ==============================================================================
ACCENT_THEMES: dict[str, dict[str, str]] = {
    "blue": {
        "name": "Midnight Blue",
        "primary": "#58a6ff",
        "interactive": "#388bfd",
        "active": "#1f6feb",
        "surface": "#152238",
        "border_focus": "#388bfd",
        "border_subtle": "#28334e",
    },
    "cyan": {
        "name": "Cyber Cyan",
        "primary": "#39c5cf",
        "interactive": "#388bfd",
        "active": "#1f6feb",
        "surface": "#10262e",
        "border_focus": "#39c5cf",
        "border_subtle": "#1d3840",
    },
    "emerald": {
        "name": "Terminal Emerald",
        "primary": "#56d364",
        "interactive": "#3fb950",
        "active": "#238636",
        "surface": "#13261a",
        "border_focus": "#56d364",
        "border_subtle": "#1d3a24",
    },
    "purple": {
        "name": "Amethyst Purple",
        "primary": "#bc8cff",
        "interactive": "#a371f7",
        "active": "#8957e5",
        "surface": "#271b3d",
        "border_focus": "#bc8cff",
        "border_subtle": "#392557",
    },
}


def get_peer_color(identifier: str) -> str:
    """Return a deterministic, stable identity color for a peer.

    Uses CRC32 over the UTF-8 bytes of the peer identifier (nickname or peer ID)
    to select an identity color from the fixed PEER_IDENTITY_COLORS palette.
    """
    if not identifier:
        return COLOR_TEXT_MUTED
    if identifier.lower() in ("you", "self", "local"):
        return COLOR_SELF_IDENTITY

    digest = zlib.crc32(identifier.encode("utf-8"))
    return PEER_IDENTITY_COLORS[digest % len(PEER_IDENTITY_COLORS)]


# Legacy compatibility aliases
COLOR_BG_DARK = COLOR_BG
COLOR_PANEL_BG = COLOR_SURFACE
COLOR_ACCENT = COLOR_BLUE_ACCENT
COLOR_SUCCESS = COLOR_STATUS_SUCCESS
COLOR_WARNING = COLOR_STATUS_WARNING
COLOR_ERROR = COLOR_STATUS_ERROR
COLOR_SECURITY = COLOR_PURPLE_SUBTLE

TCSS_FILE = Path(__file__).parent / "styles" / "app.tcss"
TCSS_STYLES = TCSS_FILE.read_text(encoding="utf-8") if TCSS_FILE.exists() else ""
