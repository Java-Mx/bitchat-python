"""Appearance, display density, and theme customization modal screen."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any, ClassVar

from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Label, RadioButton, RadioSet, Static

from bitchat.tui.screens.settings import SaveStatusIndicator, UnsavedChangesModal

if TYPE_CHECKING:
    from textual import events
    from textual.app import ComposeResult
    from textual.binding import BindingType

logger = logging.getLogger(__name__)


class EditThemeModal(ModalScreen[None]):
    """Modal screen for editing appearance, density, and accent options."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss_modal", "Cancel", priority=True),
        Binding("f2", "dismiss_modal", "Cancel", priority=True),
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
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.current_density = current_density
        self.current_show_timestamps = current_show_timestamps
        self.current_accent = current_accent

        self._initial_snapshot: dict[str, Any] = {
            "density": current_density,
            "show_timestamps": current_show_timestamps,
            "accent": current_accent,
        }
        self.has_unsaved_changes: bool = False
        self._is_populating: bool = True

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-theme-dialog"):
            yield Label(
                "Appearance & Theme Settings",
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
                    "All themes adhere to the high-contrast dark midnight design system.",
                    id="edit-theme-hint",
                )

            with Vertical(id="edit-theme-footer-bar"):
                with (
                    Horizontal(id="edit-theme-actions"),
                    Grid(
                        id="edit-theme-footer-buttons",
                        classes="footer-action-grid",
                    ),
                ):
                    yield Button("Apply", id="btn-theme-apply", classes="action-btn")
                    yield Button("Cancel", id="btn-theme-close", classes="action-btn")
                    yield Button(
                        "Reset to Default", id="btn-theme-reset", classes="action-btn"
                    )
                with Horizontal(id="edit-theme-actions-right"):
                    yield SaveStatusIndicator(id="edit-theme-save-indicator")

    def query_one(self, selector: Any, *args: Any, **kwargs: Any) -> Any:
        if selector == "#btn-theme-cancel":
            return super().query_one("#btn-theme-close", *args, **kwargs)
        return super().query_one(selector, *args, **kwargs)

    def on_mount(self) -> None:
        self._is_populating = False
        self._check_dirty_state()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """Handle theme or density option change, trigger live preview, and track dirty state."""
        if self._is_populating:
            return

        values = self._get_form_values()
        # Preview theme and density live on the running application
        self._preview_theme(values["accent"], values["density"])
        self._check_dirty_state()

    def _get_form_values(self) -> dict[str, Any]:
        """Read selected density, timestamp, and accent values from form controls."""
        density = self.current_density
        with contextlib.suppress(Exception):
            density_rs = self.query_one("#density-radios", RadioSet)
            if density_rs.pressed_button:
                density = (
                    "compact"
                    if density_rs.pressed_button.id == "rb-density-comp"
                    else "comfortable"
                )
            elif density_rs.pressed_index is not None and density_rs.pressed_index >= 0:
                density = "compact" if density_rs.pressed_index == 1 else "comfortable"

        show_ts = self.current_show_timestamps
        with contextlib.suppress(Exception):
            ts_rs = self.query_one("#timestamp-radios", RadioSet)
            if ts_rs.pressed_button:
                show_ts = bool(ts_rs.pressed_button.id == "rb-ts-show")
            elif ts_rs.pressed_index is not None and ts_rs.pressed_index >= 0:
                show_ts = ts_rs.pressed_index == 0

        accent = self.current_accent
        with contextlib.suppress(Exception):
            accent_rs = self.query_one("#accent-radios", RadioSet)
            aid = ""
            if accent_rs.pressed_button:
                aid = accent_rs.pressed_button.id or ""
            elif accent_rs.pressed_index is not None and accent_rs.pressed_index >= 0:
                idx = accent_rs.pressed_index
                aid = ["blue", "cyan", "emerald", "purple"][min(idx, 3)]
            if "cyan" in aid:
                accent = "cyan"
            elif "emerald" in aid:
                accent = "emerald"
            elif "purple" in aid:
                accent = "purple"
            elif "blue" in aid:
                accent = "blue"

        return {
            "density": density,
            "show_timestamps": show_ts,
            "accent": accent,
        }

    def _preview_theme(self, accent: str, density: str) -> None:
        """Visually preview the accent and density on the running app and modal."""
        try:
            for acc in ("blue", "cyan", "emerald", "purple"):
                self.app.remove_class(f"accent-{acc}")
                self.remove_class(f"accent-{acc}")
            self.app.add_class(f"accent-{accent}")
            self.add_class(f"accent-{accent}")

            self.app.remove_class("density-comfortable")
            self.app.remove_class("density-compact")
            self.app.add_class(f"density-{density}")
        except Exception as e:
            logger.debug("Failed previewing theme: %s", e)

    def _check_dirty_state(self) -> None:
        """Evaluate unsaved changes status against initial snapshot."""
        try:
            indicator = self.query_one(SaveStatusIndicator)
            hint = self.query_one("#edit-theme-hint", Static)
        except Exception:
            return

        current_values = self._get_form_values()
        is_dirty = current_values != self._initial_snapshot
        self.has_unsaved_changes = is_dirty

        if is_dirty:
            indicator.set_unsaved()
            hint.update(
                "[bold #d29922]◈ Unsaved appearance changes. "
                "Click 'Apply' to persist or 'Cancel' to revert.[/bold #d29922]"
            )
        else:
            indicator.set_saved()
            hint.update(
                "[dim #8b949e]All themes adhere to the high-contrast dark "
                "midnight design system.[/dim #8b949e]"
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "btn-theme-apply":
                self._apply_theme()
            case "btn-theme-cancel" | "btn-theme-close":
                self._handle_cancel()
            case "btn-theme-reset":
                self._restore_defaults()

    def _apply_theme(self) -> None:
        """Validate, persist to disk, and apply theme changes across all UI components."""
        vals = self._get_form_values()
        density = vals["density"]
        show_ts = vals["show_timestamps"]
        accent = vals["accent"]

        if density not in ("comfortable", "compact"):
            density = "comfortable"
        if accent not in ("blue", "cyan", "emerald", "purple"):
            accent = "blue"

        indicator = None
        with contextlib.suppress(Exception):
            indicator = self.query_one(SaveStatusIndicator)
            if indicator is not None:
                indicator.set_saving()

        # 1. Update application state
        app: Any = self.app
        if hasattr(app, "current_density"):
            app.current_density = density
        if hasattr(app, "current_show_timestamps"):
            app.current_show_timestamps = show_ts
        if hasattr(app, "current_accent"):
            app.current_accent = accent

        app_config = getattr(self.app, "config", None)
        if app_config is not None:
            app_config.density = density
            app_config.show_timestamps = show_ts
            app_config.accent = accent

        # 2. Persist configuration
        save_success = True
        storage = getattr(self.app, "storage", None)
        if storage is not None and app_config is not None:
            try:
                storage.save_config(app_config)
            except Exception as e:
                logger.error("Failed saving theme settings: %s", e)
                save_success = False

        if not save_success:
            if indicator is not None:
                indicator.set_error()
            with contextlib.suppress(Exception):
                hint = self.query_one("#edit-theme-hint", Static)
                hint.update(
                    "[bold #f85149]✕ Failed to persist settings to disk.[/bold #f85149]"
                )
            return

        # 3. Apply classes on application root
        self._preview_theme(accent, density)

        # 4. Notify ChatView if present
        get_chat = getattr(self.app, "_get_chat_view", None)
        chat: Any = get_chat() if callable(get_chat) else None
        if chat is not None:
            chat.compact_mode = density == "compact"
            chat.show_timestamps = show_ts
            re_render = getattr(chat, "re_render_all", None)
            if callable(re_render):
                re_render()

        # 5. Post ThemeApplied event
        msg = self.ThemeApplied(density, show_ts, accent)
        self.app.post_message(msg)
        self.post_message(msg)

        # 6. Update snapshot and save status indicator
        self._initial_snapshot = dict(vals)
        self.current_density = density
        self.current_show_timestamps = show_ts
        self.current_accent = accent
        self.has_unsaved_changes = False

        if indicator is not None:
            indicator.set_saved()
        with contextlib.suppress(Exception):
            hint = self.query_one("#edit-theme-hint", Static)
            hint.update(
                "[bold #3fb950]Theme settings successfully applied and saved.[/bold #3fb950]"
            )

        self.dismiss()

    def _restore_defaults(self) -> None:
        """Restore factory default theme and density; require Apply to persist."""
        self._is_populating = True
        try:
            self.query_one("#density-radios", RadioSet).pressed_index = 0
            self.query_one("#rb-density-comf", RadioButton).value = True
            self.query_one("#timestamp-radios", RadioSet).pressed_index = 0
            self.query_one("#rb-ts-show", RadioButton).value = True
            self.query_one("#accent-radios", RadioSet).pressed_index = 0
            self.query_one("#rb-accent-blue", RadioButton).value = True
        except Exception as e:
            logger.debug("Failed resetting radio controls: %s", e)
        finally:
            self._is_populating = False

        self._preview_theme("blue", "comfortable")

        # Recalculate dirty state
        current_values = self._get_form_values()
        is_dirty = current_values != self._initial_snapshot
        self.has_unsaved_changes = is_dirty

        with contextlib.suppress(Exception):
            indicator = self.query_one(SaveStatusIndicator)
            hint = self.query_one("#edit-theme-hint", Static)
            if is_dirty:
                indicator.set_unsaved()
                hint.update(
                    "[bold #58a6ff]Theme restored to factory defaults. "
                    "Click 'Apply' to persist.[/bold #58a6ff]"
                )
            else:
                indicator.set_saved()
                hint.update(
                    "[dim #8b949e]Settings match factory defaults.[/dim #8b949e]"
                )

    def _handle_cancel(self) -> None:
        """Discard uncommitted changes, restore previous theme and density, and close modal."""
        self._revert_to_initial()
        self.has_unsaved_changes = False
        self.dismiss()

    def _revert_to_initial(self) -> None:
        """Restore initial theme and density on the running application."""
        init_accent = self._initial_snapshot.get("accent", "blue")
        init_density = self._initial_snapshot.get("density", "comfortable")
        self._preview_theme(init_accent, init_density)

    def action_dismiss_modal(self) -> None:
        """Handle escape or dismiss action with dirty check."""
        if self.has_unsaved_changes:

            def _on_confirm(discard: bool | None) -> None:
                if discard:
                    self._revert_to_initial()
                    self.has_unsaved_changes = False
                    self.dismiss()

            self.app.push_screen(UnsavedChangesModal(), _on_confirm)
        else:
            self._handle_cancel()

    def on_key(self, event: events.Key) -> None:
        """Handle global function keys inside modal."""
        get_action = getattr(self.app, "get_action_for_key", None)
        if callable(get_action):
            action = get_action(event.key)
            if action == "edit_theme":
                event.prevent_default()
                event.stop()
                self.action_dismiss_modal()
            elif action in ("help", "settings"):
                event.prevent_default()
                event.stop()
                self.action_dismiss_modal()
                trigger = getattr(self.app, "trigger_action", None)
                if callable(trigger):
                    trigger(action)
