"""Reusable, theme-aware ActionGrid component for consistent bottom navigation and action bars."""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING, Any

from textual.containers import Grid
from textual.message import Message
from textual.widgets import Button

if TYPE_CHECKING:
    from collections.abc import Sequence

    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class ActionItem:
    """Definition for a single button item inside an ActionGrid."""

    label: str
    id: str
    action: str | None = None
    classes: str = "action-btn"
    disabled: bool = False
    variant: str = "default"
    shortcut: str | None = None
    column_span: int = 1
    row_span: int = 1
    tooltip: str | None = None


class ActionGrid(Grid):
    """Reusable, accessible, responsive action grid for bottom bars and modal footers.

    Supports standardized proportional layouts:
      - '2:2:1': 3 columns with 2:2:1 width ratio across 2 rows (chat and peers screens).
      - 'equal-3': 3 columns with 1:1:1 ratio (settings, theme modals).
      - 'equal-2': 2 columns with 1:1 ratio (commands, quit modals).
      - 'equal-4': 4 columns with 1:1:1:1 ratio (telemetry).
    """

    DEFAULT_CLASSES = "footer-action-grid"

    class ActionTriggered(Message):
        """Emitted when an action button within this grid is activated."""

        def __init__(self, action_id: str, action: str | None = None) -> None:
            super().__init__()
            self.action_id = action_id
            self.action = action or action_id

    def __init__(
        self,
        items: Sequence[ActionItem] | None = None,
        layout: str = "2:2:1",
        id: str | None = None,  # noqa: A002
        classes: str | None = None,
        **kwargs: Any,
    ) -> None:
        grid_classes = [self.DEFAULT_CLASSES]
        if classes:
            grid_classes.append(classes)

        layout_normalized = layout.lower().strip()
        if layout_normalized in ("2:2:2", "2-2-2", "equal-3-2row"):
            grid_classes.append("action-grid-2-2-2")
            self._grid_size = (3, 2)
            self._grid_cols = "2fr 2fr 2fr"
        elif layout_normalized in ("2:2:1", "2-2-1", "proportional"):
            grid_classes.append("action-grid-2-2-1")
            self._grid_size = (3, 2)
            self._grid_cols = "2fr 2fr 1fr"
        elif layout_normalized in ("equal-3", "3-col", "3"):
            grid_classes.append("action-grid-3-col")
            self._grid_size = (3, 1)
            self._grid_cols = "1fr 1fr 1fr"
        elif layout_normalized in ("equal-2", "2-col", "2"):
            grid_classes.append("action-grid-2-col")
            self._grid_size = (2, 1)
            self._grid_cols = "1fr 1fr"
        elif layout_normalized in ("equal-4", "4-col", "4"):
            grid_classes.append("action-grid-4-col")
            self._grid_size = (4, 1)
            self._grid_cols = "1fr 1fr 1fr 1fr"
        else:
            grid_classes.append(f"action-grid-{layout_normalized}")
            self._grid_size = (3, 1)
            self._grid_cols = "1fr 1fr 1fr"

        super().__init__(
            id=id,
            classes=" ".join(grid_classes),
            **kwargs,
        )
        self.action_items: list[ActionItem] = list(items or [])
        self._action_map: dict[str, str | None] = {
            item.id: item.action for item in self.action_items
        }

    def compose(self) -> ComposeResult:
        """Compose child buttons based on defined ActionItems."""
        for item in self.action_items:
            btn = Button(
                item.label,
                id=item.id,
                classes=item.classes,
                disabled=item.disabled,
            )
            if item.tooltip:
                btn.tooltip = item.tooltip
            if item.column_span > 1:
                btn.styles.column_span = item.column_span
            if item.row_span > 1:
                btn.styles.row_span = item.row_span
            yield btn

    def set_action_disabled(self, action_id: str, disabled: bool) -> None:
        """Update disabled state of a button and apply visual classes."""
        try:
            btn = self.query_one(f"#{action_id}", Button)
            btn.disabled = disabled
            if disabled:
                btn.add_class("action-btn-disabled")
                btn.remove_class("action-btn-enabled")
            else:
                btn.remove_class("action-btn-disabled")
                btn.add_class("action-btn-enabled")
        except Exception as e:
            logger.debug(
                "Failed updating action button %s disabled state: %s", action_id, e
            )

    def set_action_label(self, action_id: str, new_label: str) -> None:
        """Update label of a specific action button."""
        try:
            btn = self.query_one(f"#{action_id}", Button)
            btn.label = new_label
        except Exception as e:
            logger.debug("Failed updating action button %s label: %s", action_id, e)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Post ActionTriggered message on button activation."""
        action_id = event.button.id or ""
        action = self._action_map.get(action_id, action_id)
        self.post_message(self.ActionTriggered(action_id, action))
