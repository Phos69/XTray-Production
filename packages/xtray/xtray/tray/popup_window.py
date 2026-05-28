"""Unified frameless popup window for the tray UI.

Every tray surface (main panel + side popups) shares the same shell:

    +-------------------------------------------------------------+
    | TrayTitleBar  (drag handle + fancy logo + actions + close)  |
    +-------------------------------------------------------------+
    |                                                             |
    |                  content area (set by callers)              |
    |                                                             |
    +-------------------------------------------------------------+
    | TrayBottomBar  (optional widget slot)                       |
    +-------------------------------------------------------------+

The shell owns:

* the frameless ``Tool`` window flags and tray styling hooks,
* drag + edge-resize: the ``_TrayDragBackground`` frame fills the popup
  and is the primary press target — passive children ignore their
  presses and Qt bubbles them up to the background's
  ``mousePressEvent``. As a safety net for any platform/widget combo
  where the press skips the background, ``TrayPopupWindow`` itself
  also handles the same gestures; both paths funnel into one
  drag/resize state machine on the popup,
* show/hide notifications via Qt signals so the panel can mirror
  state on the trigger buttons.

There is no application-level event filter, no recursive child
filter, no ``QWindow.startSystemMove``, no ``grabMouse`` — drag and
resize are plain ``QWidget`` mouse handlers.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from xtray.core import qt_assets
from xtray.core.gui import apply_tray_theme
from xtray.core.theme import AppTheme

_RESIZE_MARGIN = 8

_RGBA_PATTERN = re.compile(
    r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*(\d+))?\s*\)"
)


def _parse_qss_color(value: str) -> tuple[int, int, int, int] | None:
    """Parse ``rgba(r, g, b, a)`` / ``rgb(r, g, b)`` returned by the QSS palette.

    QColor's constructor only understands those formats inside QSS — it
    returns an opaque black when you feed it a literal ``rgba(...)``
    string directly, which silently nukes the theme colors when used
    from a custom QPainter.
    """
    match = _RGBA_PATTERN.match(value.strip())
    if not match:
        return None
    r, g, b, a = match.groups()
    return int(r), int(g), int(b), int(a) if a is not None else 255


_TRAY_POPUP_WINDOW_CLASS: type[Any] | None = None
_TRAY_TITLE_BAR_CLASS: type[Any] | None = None
_TRAY_BOTTOM_BAR_CLASS: type[Any] | None = None


def tray_title_bar_class() -> type[Any]:
    """Return (and cache) the unified draggable title bar class."""
    global _TRAY_TITLE_BAR_CLASS
    if _TRAY_TITLE_BAR_CLASS is not None:
        return _TRAY_TITLE_BAR_CLASS

    from PySide6.QtCore import QSize, Qt  # type: ignore[import-not-found]
    from PySide6.QtGui import QIcon  # type: ignore[import-not-found]
    from PySide6.QtWidgets import (  # type: ignore[import-not-found]
        QHBoxLayout,
        QLabel,
        QPushButton,
        QWidget,
    )

    class TrayTitleBar(QWidget):
        """Top bar with the fancy XTray logo + action slot + close button.

        Drag handling lives on the surrounding popup/background; clicks
        on the bar's empty areas ignore by default so Qt bubbles them
        up to the background's ``mousePressEvent``.
        """

        def __init__(
            self,
            title: str,
            on_close: Callable[[], None],
            parent: Any = None,
            *,
            wordmark: str | None = None,
        ) -> None:
            super().__init__(parent)
            self.setObjectName("trayPanelHeader")
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setFixedHeight(32)
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

            self._title_text = title
            self._wordmark = wordmark
            layout = QHBoxLayout(self)
            layout.setContentsMargins(4, 0, 0, 0)
            layout.setSpacing(8)
            self._layout = layout

            self.title_label = QLabel(title)
            self.title_label.setObjectName("trayPanelHeaderTitle")
            self.title_label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            self.title_label.setMinimumWidth(104)
            self.title_label.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            layout.addWidget(self.title_label)

            layout.addStretch(1)
            self._action_insert_index = layout.count()

            self.close_button = QPushButton()
            self.close_button.setObjectName("trayPanelCloseButton")
            self.close_button.setFixedSize(32, 28)
            self.close_button.setIconSize(QSize(20, 20))
            self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.close_button.setToolTip("Close")
            self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.close_button.clicked.connect(on_close)
            layout.addWidget(self.close_button)

        def set_close_icon_color(self, color: str | None) -> None:
            pixmap = qt_assets.tray_glyph_pixmap(20, color=color)
            if pixmap.isNull():
                self.close_button.setIcon(QIcon())
                self.close_button.setText("X")
                return
            self.close_button.setText("")
            self.close_button.setIcon(QIcon(pixmap))

        @property
        def widget(self) -> Any:
            """Back-compat alias used by tests and `_apply_theme` callers."""
            return self

        def insert_action(self, widget: Any) -> None:
            self._layout.insertWidget(self._action_insert_index, widget)
            self._action_insert_index += 1

        def set_logo_color(
            self, color: str | None, accent_color: str | None = None
        ) -> None:
            pixmap = qt_assets.tray_logo_pixmap(
                118,
                28,
                color=color,
                accent_color=accent_color,
                wordmark_text=self._wordmark,
            )
            if pixmap.isNull():
                self.title_label.clear()
                self.title_label.setText(self._title_text)
                return
            self.title_label.setText("")
            self.title_label.setPixmap(pixmap)
            self.title_label.setMinimumWidth(max(104, pixmap.width()))

        def set_theme(self, theme: AppTheme) -> None:
            self.set_logo_color(theme.tray.text, theme.tray.accent)
            self.set_close_icon_color(theme.tray.accent)

    _TRAY_TITLE_BAR_CLASS = TrayTitleBar
    return _TRAY_TITLE_BAR_CLASS


def tray_bottom_bar_class() -> type[Any]:
    """Return (and cache) the bottom-bar container class."""
    global _TRAY_BOTTOM_BAR_CLASS
    if _TRAY_BOTTOM_BAR_CLASS is not None:
        return _TRAY_BOTTOM_BAR_CLASS

    from PySide6.QtCore import Qt  # type: ignore[import-not-found]
    from PySide6.QtWidgets import (  # type: ignore[import-not-found]
        QFrame,
        QHBoxLayout,
    )

    class TrayBottomBar(QFrame):
        """Container for the bottom-of-popup widget slot.

        Empty by default. Callers use :meth:`add_widget` / :meth:`add_stretch`
        to populate the bar; if no widget is added the bar collapses so popups
        without a bottom area visually match the legacy layout.
        """

        def __init__(self, parent: Any = None) -> None:
            super().__init__(parent)
            self.setObjectName("trayPanelBottomBar")
            self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self._layout = QHBoxLayout(self)
            self._layout.setContentsMargins(6, 4, 6, 0)
            self._layout.setSpacing(8)
            self._has_content = False
            self.setVisible(False)

        def add_widget(self, widget: Any, stretch: int = 0) -> None:
            self._layout.addWidget(widget, stretch)
            self._mark_populated()

        def add_stretch(self, stretch: int = 1) -> None:
            self._layout.addStretch(stretch)
            self._mark_populated()

        def _mark_populated(self) -> None:
            if not self._has_content:
                self._has_content = True
                self.setVisible(True)

    _TRAY_BOTTOM_BAR_CLASS = TrayBottomBar
    return _TRAY_BOTTOM_BAR_CLASS


def tray_popup_window_class() -> type[Any]:
    """Return (and cache) the unified frameless popup window class."""
    global _TRAY_POPUP_WINDOW_CLASS
    if _TRAY_POPUP_WINDOW_CLASS is not None:
        return _TRAY_POPUP_WINDOW_CLASS

    from PySide6.QtCore import (  # type: ignore[import-not-found]
        QEvent,
        QPoint,
        QRect,
        QRectF,
        Qt,
        Signal,
    )
    from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen  # type: ignore[import-not-found]
    from PySide6.QtWidgets import (  # type: ignore[import-not-found]
        QFrame,
        QVBoxLayout,
        QWidget,
    )

    TitleBar = tray_title_bar_class()
    BottomBar = tray_bottom_bar_class()

    _EDGE_NONE = 0
    _EDGE_LEFT = 1
    _EDGE_RIGHT = 2
    _EDGE_TOP = 4
    _EDGE_BOTTOM = 8

    _CURSOR_FOR_EDGES = {
        _EDGE_LEFT: Qt.CursorShape.SizeHorCursor,
        _EDGE_RIGHT: Qt.CursorShape.SizeHorCursor,
        _EDGE_TOP: Qt.CursorShape.SizeVerCursor,
        _EDGE_BOTTOM: Qt.CursorShape.SizeVerCursor,
        _EDGE_LEFT | _EDGE_TOP: Qt.CursorShape.SizeFDiagCursor,
        _EDGE_RIGHT | _EDGE_BOTTOM: Qt.CursorShape.SizeFDiagCursor,
        _EDGE_RIGHT | _EDGE_TOP: Qt.CursorShape.SizeBDiagCursor,
        _EDGE_LEFT | _EDGE_BOTTOM: Qt.CursorShape.SizeBDiagCursor,
    }

    def _color_from(value: str) -> Any:
        parsed = _parse_qss_color(value)
        if parsed is None:
            return QColor(value)
        r, g, b, a = parsed
        return QColor(r, g, b, a)

    def _edge_at_in(rect: QRect, pos: QPoint) -> int:
        if not rect.contains(pos):
            return _EDGE_NONE
        edges = _EDGE_NONE
        if pos.x() <= _RESIZE_MARGIN:
            edges |= _EDGE_LEFT
        elif pos.x() >= rect.right() - _RESIZE_MARGIN:
            edges |= _EDGE_RIGHT
        if pos.y() <= _RESIZE_MARGIN:
            edges |= _EDGE_TOP
        elif pos.y() >= rect.bottom() - _RESIZE_MARGIN:
            edges |= _EDGE_BOTTOM
        return edges

    class _TrayDragBackground(QFrame):
        """The full-bleed frame that absorbs drag/resize gestures.

        It is laid out by the popup as the sole root child, so its rect
        always matches the popup's client rect. Title bar, content host
        and bottom bar sit *inside* it. A press on a passive child
        bubbles up here; we then forward the gesture to the popup's
        shared drag/resize state machine.
        """

        def __init__(self, popup: Any) -> None:
            super().__init__(popup)
            self.setObjectName("trayPanelBackground")
            self.setFrameShape(QFrame.Shape.NoFrame)
            self.setMouseTracking(True)
            self._popup = popup
            # The popup uses WA_TranslucentBackground for DWM effects,
            # which makes Windows do per-pixel hit-testing on the
            # layered window — alpha-0 pixels leak the click through to
            # whatever sits behind. We paint this frame's whole area
            # ourselves with an explicit opaque surface color so the
            # OS sees solid pixels everywhere drag/resize must work,
            # not just under labels and logos.
            self._surface_color: Any = QColor("#1f1f1f")
            self._border_color: Any = QColor("#3f3f3f")
            self._radius = 12

        def apply_surface(self, theme: AppTheme) -> None:
            # Keep the theme's native alpha (most themes use ~246/255 to
            # blend nicely with the DWM mica/acrylic backdrop). Anything
            # above zero is enough for Windows' layered-window hit
            # testing, which was the original failure mode — the
            # background frame was inheriting alpha=0 from the generic
            # transparent CSS rule, not from the theme.
            self._surface_color = _color_from(theme.tray.surface)
            self._border_color = _color_from(theme.tray.border)
            self._radius = theme.metrics.radius_panel
            self.update()

        def paintEvent(self, event: Any) -> None:  # noqa: N802 - Qt signature
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            path = QPainterPath()
            path.addRoundedRect(rect, self._radius, self._radius)
            painter.fillPath(path, self._surface_color)
            painter.setPen(QPen(self._border_color, 1))
            painter.drawPath(path)
            painter.end()

        def _popup_local(self, local: QPoint) -> QPoint:
            return self.mapTo(self._popup, local)

        def mousePressEvent(self, event: Any) -> None:  # noqa: N802 - Qt signature
            if event.button() == Qt.MouseButton.LeftButton:
                local = self._popup_local(event.position().toPoint())
                global_pos = event.globalPosition().toPoint()
                if self._popup._begin_drag_or_resize(local, global_pos):
                    event.accept()
                    return
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802 - Qt signature
            if event.buttons() & Qt.MouseButton.LeftButton:
                if self._popup._apply_drag_or_resize(
                    event.globalPosition().toPoint()
                ):
                    event.accept()
                    return
            local_in_popup = self._popup_local(event.position().toPoint())
            edges = _edge_at_in(self._popup.rect(), local_in_popup)
            self._popup._apply_cursor_to(self, edges)
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802 - Qt signature
            if (
                event.button() == Qt.MouseButton.LeftButton
                and self._popup._finish_drag_or_resize()
            ):
                event.accept()
                return
            super().mouseReleaseEvent(event)

        def leaveEvent(self, event: Any) -> None:  # noqa: N802 - Qt signature
            if not self._popup._is_drag_active():
                self._popup._apply_cursor_to(self, _EDGE_NONE)
            super().leaveEvent(event)

    class TrayPopupWindow(QWidget):
        """Frameless tray popup. Drag/resize state lives here; presses can
        arrive either via the background frame or directly on the popup."""

        aboutToShow = Signal()
        aboutToHide = Signal()

        def __init__(
            self,
            title: str,
            *,
            parent: Any = None,
            on_close: Callable[[], None] | None = None,
            minimum_width: int = 320,
            minimum_height: int = 180,
            wordmark: str | None = None,
        ) -> None:
            flags = (
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            super().__init__(parent, flags)
            self.setObjectName("trayPanel")
            self.setWindowTitle(title)
            qt_assets.set_window_icon(self)
            self.setMinimumSize(minimum_width, minimum_height)
            self.setMouseTracking(True)

            self._user_moved = False
            self._drag_offset: QPoint | None = None
            self._resize_state: tuple[int, QRect, QPoint] | None = None
            self._on_close = on_close or self.hide
            self._theme: AppTheme | None = None

            # Single root child: the drag background frame. Title bar,
            # content host and bottom bar live inside it so Qt's natural
            # mouse-event propagation reaches it for clicks on passive
            # areas.
            root = QVBoxLayout(self)
            root.setContentsMargins(0, 0, 0, 0)
            root.setSpacing(0)
            self._background = _TrayDragBackground(self)
            root.addWidget(self._background)

            inner = QVBoxLayout(self._background)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.setSpacing(0)

            self.title_bar = TitleBar(
                title, self._on_close, parent=self._background, wordmark=wordmark
            )
            inner.addWidget(self.title_bar)

            self._content_host = QWidget(self._background)
            self._content_host.setObjectName("trayPanelContent")
            self._content_layout = QVBoxLayout(self._content_host)
            self._content_layout.setContentsMargins(16, 12, 16, 12)
            self._content_layout.setSpacing(10)
            inner.addWidget(self._content_host, 1)

            self.bottom_bar = BottomBar(self._background)
            inner.addWidget(self.bottom_bar)

            # Install a hover-only cursor tracker on every descendant so
            # that the resize cursor appears whenever the pointer is
            # within _RESIZE_MARGIN of an edge, even when a child widget
            # covers that band. This filter NEVER consumes events and
            # NEVER drives drag/resize — those still live on
            # _TrayDragBackground via natural Qt mouse propagation.
            self._install_cursor_tracker(self)

        # -- public API ---------------------------------------------------

        @property
        def content_layout(self) -> Any:
            return self._content_layout

        @property
        def content_widget(self) -> Any:
            return self._content_host

        @property
        def background(self) -> Any:
            """The internal drag/resize frame (exposed for tests)."""
            return self._background

        def set_content_margins(self, left: int, top: int, right: int, bottom: int) -> None:
            self._content_layout.setContentsMargins(left, top, right, bottom)

        def set_content_spacing(self, spacing: int) -> None:
            self._content_layout.setSpacing(spacing)

        def set_theme(self, theme: AppTheme) -> None:
            self._theme = theme
            apply_tray_theme(self, theme)
            self.title_bar.set_theme(theme)
            self._background.apply_surface(theme)

        def reset_user_geometry(self) -> None:
            """Forget any drag/resize the user did so the next show repositions."""
            self._user_moved = False

        def has_user_geometry(self) -> bool:
            return self._user_moved

        # -- drag/resize state machine -----------------------------------

        def _is_drag_active(self) -> bool:
            return self._drag_offset is not None or self._resize_state is not None

        def _begin_drag_or_resize(self, local_in_popup: QPoint, global_pos: QPoint) -> bool:
            edges = _edge_at_in(self.rect(), local_in_popup)
            if edges:
                self._resize_state = (
                    edges,
                    QRect(self.geometry()),
                    QPoint(global_pos),
                )
            else:
                self._drag_offset = global_pos - self.frameGeometry().topLeft()
            self._user_moved = True
            return True

        def _apply_drag_or_resize(self, global_pos: QPoint) -> bool:
            if self._drag_offset is not None:
                self.move(global_pos - self._drag_offset)
                return True
            if self._resize_state is not None:
                self._apply_resize(global_pos)
                return True
            return False

        def _finish_drag_or_resize(self) -> bool:
            had = self._drag_offset is not None or self._resize_state is not None
            self._drag_offset = None
            self._resize_state = None
            return had

        def _apply_resize(self, global_pos: QPoint) -> None:
            assert self._resize_state is not None
            edges, start_geom, start_pos = self._resize_state
            delta = global_pos - start_pos
            geom = QRect(start_geom)
            min_size = self.minimumSize()
            min_w = max(1, min_size.width())
            min_h = max(1, min_size.height())
            if edges & _EDGE_LEFT:
                new_left = start_geom.left() + delta.x()
                if start_geom.right() - new_left + 1 < min_w:
                    new_left = start_geom.right() - min_w + 1
                geom.setLeft(new_left)
            elif edges & _EDGE_RIGHT:
                new_right = start_geom.right() + delta.x()
                if new_right - start_geom.left() + 1 < min_w:
                    new_right = start_geom.left() + min_w - 1
                geom.setRight(new_right)
            if edges & _EDGE_TOP:
                new_top = start_geom.top() + delta.y()
                if start_geom.bottom() - new_top + 1 < min_h:
                    new_top = start_geom.bottom() - min_h + 1
                geom.setTop(new_top)
            elif edges & _EDGE_BOTTOM:
                new_bottom = start_geom.bottom() + delta.y()
                if new_bottom - start_geom.top() + 1 < min_h:
                    new_bottom = start_geom.top() + min_h - 1
                geom.setBottom(new_bottom)
            self.setGeometry(geom)

        def _apply_cursor_to(self, widget: Any, edges: int) -> None:
            cursor = _CURSOR_FOR_EDGES.get(edges) if edges else None
            if cursor is None:
                if widget.testAttribute(Qt.WidgetAttribute.WA_SetCursor):
                    widget.unsetCursor()
                return
            widget.setCursor(cursor)

        # -- Qt mouse handlers (fallback when presses skip the background) -

        def mousePressEvent(self, event: Any) -> None:  # noqa: N802 - Qt signature
            if event.button() == Qt.MouseButton.LeftButton:
                if self._begin_drag_or_resize(
                    event.position().toPoint(),
                    event.globalPosition().toPoint(),
                ):
                    event.accept()
                    return
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802 - Qt signature
            if event.buttons() & Qt.MouseButton.LeftButton:
                if self._apply_drag_or_resize(event.globalPosition().toPoint()):
                    event.accept()
                    return
            edges = _edge_at_in(self.rect(), event.position().toPoint())
            self._apply_cursor_to(self, edges)
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802 - Qt signature
            if (
                event.button() == Qt.MouseButton.LeftButton
                and self._finish_drag_or_resize()
            ):
                event.accept()
                return
            super().mouseReleaseEvent(event)

        def leaveEvent(self, event: Any) -> None:  # noqa: N802 - Qt signature
            if not self._is_drag_active():
                self._apply_cursor_to(self, _EDGE_NONE)
            super().leaveEvent(event)

        # -- hover-only cursor tracker (purely visual) -------------------

        def _install_cursor_tracker(self, widget: Any) -> None:
            """Install ``self`` as event filter on every descendant.

            We only watch ``MouseMove`` / ``Leave`` to paint the right
            cursor on whichever widget the pointer happens to be over,
            so the resize handle is visible across the whole perimeter
            band — not just on bare background pixels.
            """
            if not isinstance(widget, QWidget):
                return
            if widget is not self:
                if widget.isWindow():
                    # Another popup with its own filter; don't recurse.
                    return
                widget.installEventFilter(self)
                widget.setMouseTracking(True)
            for child in widget.children():
                if isinstance(child, QWidget):
                    self._install_cursor_tracker(child)

        def event(self, event: Any) -> bool:  # noqa: A003 - Qt API
            if event.type() == QEvent.Type.ChildPolished:
                child = event.child()
                if isinstance(child, QWidget):
                    self._install_cursor_tracker(child)
            return super().event(event)

        def eventFilter(self, obj: Any, event: Any) -> bool:  # noqa: N802 - Qt signature
            if event.type() == QEvent.Type.ChildPolished:
                child = event.child()
                if isinstance(child, QWidget):
                    self._install_cursor_tracker(child)
                return False
            if not isinstance(obj, QWidget):
                return False
            event_type = event.type()
            if event_type == QEvent.Type.MouseMove and not event.buttons():
                global_pos = event.globalPosition().toPoint()
                local = self.mapFromGlobal(global_pos)
                self._apply_cursor_to(obj, _edge_at_in(self.rect(), local))
                return False
            if event_type == QEvent.Type.Leave:
                self._apply_cursor_to(obj, _EDGE_NONE)
                return False
            return False

        # -- show/hide hooks ----------------------------------------------

        def showEvent(self, event: Any) -> None:  # noqa: N802 - Qt signature
            self.aboutToShow.emit()
            super().showEvent(event)

        def hideEvent(self, event: Any) -> None:  # noqa: N802 - Qt signature
            # If the popup is hidden mid-drag, drop the in-flight state.
            self._drag_offset = None
            self._resize_state = None
            self.aboutToHide.emit()
            super().hideEvent(event)

    _TRAY_POPUP_WINDOW_CLASS = TrayPopupWindow
    return _TRAY_POPUP_WINDOW_CLASS
