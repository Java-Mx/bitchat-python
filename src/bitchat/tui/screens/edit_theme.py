"""Appearance, display density, and theme customization modal screen."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Label, RadioButton, RadioSet, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.binding import BindingType


class EditThemeModal(ModalScreen[None]):
    """Modal screen for editing appearance, density, and accent options."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "dismiss_modal", "Close"),
    ]

    class ThemeApplied(Message):
        """Emitted when user applies appearance changes."""

        def __init__(
            self, density: str, show_timestamps: bool, accent_name: str
        ) -> None:
            super().__init__()
            self.density = density
            self.show_timestamps = show_timestamps
            self.accent_name = accent_name

    def __init__(
        self,
        current_density: str = "comfortable",
        current_show_timestamps: bool = True,
        current_accent: str = "blue",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.current_density = current_density
        self.current_show_timestamps = current_show_timestamps
        self.current_accent = current_accent

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-theme-dialog"):
            yield Label(
                "[bold #58a6ff]Appearance & Theme Settings[/bold #58a6ff]",
                id="edit-theme-title",
            )

            with Vertical(id="edit-theme-form"):
                yield Label("Display Density:", classes="settings-field-label")
                with RadioSet(id="density-radios"):
                    yield RadioButton(
                        "Comfortable (Standard spacing)",
                        value=(self.current_density == "comfortable"),
                        id="rb-density-comf",
                    )
                    yield RadioButton(
                        "Compact (Higher information density)",
                        value=(self.current_density == "compact"),
                        id="rb-density-comp",
                    )

                yield Label("Message Timestamps:", classes="settings-field-label")
                with RadioSet(id="timestamp-radios"):
                    yield RadioButton(
                        "Show Timestamps (HH:MM)",
                        value=self.current_show_timestamps,
                        id="rb-ts-show",
                    )
                    yield RadioButton(
                        "Hide Timestamps",
                        value=(not self.current_show_timestamps),
                        id="rb-ts-hide",
                    )

                yield Label(
                    "Accent Tone (Strict 5-Family Palette):",
                    classes="settings-field-label",
                )
                with RadioSet(id="accent-radios"):
                    yield RadioButton(
                        "Midnight Blue (#58a6ff)",
                        value=(self.current_accent == "blue"),
                        id="rb-accent-blue",
                    )
                    yield RadioButton(
                        "Cyber Cyan (#39c5cf)",
                        value=(self.current_accent == "cyan"),
                        id="rb-accent-cyan",
                    )
                    yield RadioButton(
                        "Terminal Emerald (#56d364)",
                        value=(self.current_accent == "emerald"),
                        id="rb-accent-emerald",
                    )
                    yield RadioButton(
                        "Amethyst Purple (#bc8cff)",
                        value=(self.current_accent == "purple"),
                        id="rb-accent-purple",
                    )

                yield Static(
                    "[dim #57606a]All themes adhere to the high-contrast dark "
                    "midnight design system.[/dim #57606a]",
                    id="edit-theme-hint",
                )

            with Horizontal(id="edit-theme-actions"):
                yield Button("Apply Theme", id="btn-theme-apply", classes="action-btn")
                yield Button("Close (Esc)", id="btn-theme-close", classes="action-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-theme-close":
            self.dismiss()
        elif event.button.id == "btn-theme-apply":
            self._apply_theme()

    def _apply_theme(self) -> None:
        density_rs = self.query_one("#density-radios", RadioSet)
        ts_rs = self.query_one("#timestamp-radios", RadioSet)
        accent_rs = self.query_one("#accent-radios", RadioSet)

        density = (
            "comfortable"
            if density_rs.pressed_button
            and density_rs.pressed_button.id == "rb-density-comf"
            else "compact"
        )
        show_ts = bool(ts_rs.pressed_button and ts_rs.pressed_button.id == "rb-ts-show")

        accent = "blue"
        if accent_rs.pressed_button:
            aid = accent_rs.pressed_button.id or ""
            if "cyan" in aid:
                accent = "cyan"
            elif "emerald" in aid:
                accent = "emerald"
            elif "purple" in aid:
                accent = "purple"

        msg = self.ThemeApplied(density, show_ts, accent)
        self.app.post_message(msg)
        self.post_message(msg)
        self.dismiss()

    def action_dismiss_modal(self) -> None:
        self.dismiss()
