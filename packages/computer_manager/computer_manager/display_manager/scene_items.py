"""Qt graphics items used by the profile preview scene.

Lifted out of `computer_manager.app` so the GUI module owns only orchestration
and the visual building blocks live next to the rest of the display_manager
view layer.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from xtray.core import app_logging
from xtray.core.theme import SceneTheme

from .backend import DisplayState


class MonitorItem:  # pragma: no cover - imported only when GUI dependencies exist
    def __init__(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        label: str,
        display_number: str,
        primary: bool,
        display_state: DisplayState,
        moved_callback: Callable[[DisplayState, float, float], None],
        released_callback: Callable[[DisplayState, float, float], None],
        selected_callback: Callable[[DisplayState], None],
        theme: SceneTheme,
    ) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtGui import QBrush, QColor, QFont, QPen  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QGraphicsSimpleTextItem

        position_changed = QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged
        movable = QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        selectable = QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        sends_geometry_changes = QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges

        class _Item(QGraphicsRectItem):
            def itemChange(inner_self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
                if change == position_changed:
                    try:
                        moved_callback(display_state, inner_self.pos().x(), inner_self.pos().y())
                    except Exception:
                        app_logging.get_logger("gui").exception("monitor move callback failed")
                return super().itemChange(change, value)

            def mousePressEvent(inner_self, event: Any) -> None:
                super().mousePressEvent(event)
                try:
                    selected_callback(display_state)
                except Exception:
                    app_logging.get_logger("gui").exception("monitor select callback failed")

            def mouseReleaseEvent(inner_self, event: Any) -> None:
                super().mouseReleaseEvent(event)
                try:
                    released_callback(
                        display_state,
                        inner_self.pos().x() + (width / 2),
                        inner_self.pos().y() + (height / 2),
                    )
                except Exception:
                    app_logging.get_logger("gui").exception("monitor release callback failed")

        self.item = _Item(0, 0, width, height)
        self.item.setPos(x, y)
        self.item.setFlags(movable | selectable | sends_geometry_changes)
        fill = theme.monitor_primary_fill if primary else theme.monitor_fill
        border = theme.monitor_primary_border if primary else theme.monitor_border
        self.item.setBrush(QBrush(QColor(fill)))
        self.item.setPen(QPen(QColor(border), 2))
        number_color = QColor(theme.monitor_number_primary if primary else theme.monitor_number)
        number_color.setAlpha(theme.monitor_number_alpha)
        number = QGraphicsSimpleTextItem(display_number, self.item)
        number_font = QFont()
        number_font.setBold(True)
        number_font.setPointSize(max(24, min(int(height * 0.58), int(width * 0.42))))
        number.setFont(number_font)
        number.setBrush(QBrush(number_color))
        number_rect = number.boundingRect()
        number.setPos(
            (width - number_rect.width()) / 2,
            (height - number_rect.height()) / 2,
        )
        number.setZValue(0)
        text = QGraphicsSimpleTextItem(("Primary\n" if primary else "") + label, self.item)
        text.setBrush(QBrush(QColor(theme.monitor_text)))
        text.setPos(10, 10)
        text.setZValue(1)
        self.item.setToolTip(label)
        self.item.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.item, name)
