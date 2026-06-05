"""Custom Qt widgets and lazy widget-class factories for the tray UI."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..core import app_logging, qt_assets
from ..core.theme import DEFAULT_THEME, AppTheme, indicator_colors
from .constants import (
    _DISPLAY_ACTION_ROW_HEIGHT,
    _DISPLAY_BUTTON_SPACING,
    _DISPLAY_CARD_MARGIN,
    _DISPLAY_CARD_SIZE,
    _DISPLAY_TITLE_HEIGHT,
)


def _faceplate_height(
    *, has_volume: bool, has_power: bool, has_primary_row: bool
) -> int:
    """Pixel height for a display faceplate.

    The card stacks a title above the action buttons: an optional
    "Make primary" / "Primary" row, the Enable/Disable row, and an optional
    power on/off row. Volume cards keep at least the full square so the
    vertical volume bar has room; cards without audio/volume controls shrink to
    just their content height so consecutive ones can be packed under each
    other.
    """
    content = _DISPLAY_TITLE_HEIGHT + 6 + _DISPLAY_ACTION_ROW_HEIGHT
    if has_primary_row:
        content += _DISPLAY_BUTTON_SPACING + _DISPLAY_ACTION_ROW_HEIGHT
    if has_power:
        content += _DISPLAY_BUTTON_SPACING + _DISPLAY_ACTION_ROW_HEIGHT
    content += 2 * _DISPLAY_CARD_MARGIN
    if has_volume:
        return max(_DISPLAY_CARD_SIZE, content)
    return content


_VOLUME_FILL_BAR_CLASS: Any = None
_MQTT_STATE_DISPATCHER_CLASS: type[Any] | None = None
_HA_STATE_EVENT_DISPATCHER_CLASS: type[Any] | None = None
_VOLUME_EVENT_DISPATCHER_CLASS: type[Any] | None = None
_ENDPOINT_EVENT_DISPATCHER_CLASS: type[Any] | None = None
_CENTERED_ICON_TAB_BAR_CLASS: type[Any] | None = None


def _centered_icon_tab_bar_class() -> type[Any]:
    """Return a QTabBar that centers icon-only tab labels."""
    global _CENTERED_ICON_TAB_BAR_CLASS
    if _CENTERED_ICON_TAB_BAR_CLASS is not None:
        return _CENTERED_ICON_TAB_BAR_CLASS

    from PySide6.QtCore import QSize, Qt  # type: ignore[import-not-found]
    from PySide6.QtGui import QIcon  # type: ignore[import-not-found]
    from PySide6.QtWidgets import (  # type: ignore[import-not-found]
        QStyle,
        QStyleOptionTab,
        QStylePainter,
        QTabBar,
    )

    class _CenteredIconTabBar(QTabBar):
        """Paint icon-only tabs with the icon centered in the tab rect."""

        def paintEvent(self, event: Any) -> None:  # noqa: N802 - Qt signature
            painter = QStylePainter(self)
            option = QStyleOptionTab()
            for index in range(self.count()):
                self.initStyleOption(option, index)
                if option.text or option.icon.isNull():
                    painter.drawControl(QStyle.ControlElement.CE_TabBarTab, option)
                    continue

                icon = QIcon(option.icon)
                icon_size = QSize(option.iconSize)
                option.icon = QIcon()
                painter.drawControl(QStyle.ControlElement.CE_TabBarTab, option)

                if not icon_size.isValid() or icon_size.isEmpty():
                    icon_size = self.iconSize()
                if not icon_size.isValid() or icon_size.isEmpty():
                    icon_size = QSize(16, 16)
                available = option.rect.size()
                icon_size = QSize(
                    min(icon_size.width(), available.width()),
                    min(icon_size.height(), available.height()),
                )
                icon_rect = QStyle.alignedRect(
                    self.layoutDirection(),
                    Qt.AlignmentFlag.AlignCenter,
                    icon_size,
                    option.rect,
                )
                pixmap = icon.pixmap(icon_size)
                if not pixmap.isNull():
                    painter.drawPixmap(icon_rect, pixmap)

    _CENTERED_ICON_TAB_BAR_CLASS = _CenteredIconTabBar
    return _CENTERED_ICON_TAB_BAR_CLASS


def _volume_fill_bar_class() -> Any:
    """Build (once) the custom vertical volume bar widget class."""
    global _VOLUME_FILL_BAR_CLASS
    if _VOLUME_FILL_BAR_CLASS is not None:
        return _VOLUME_FILL_BAR_CLASS

    from PySide6.QtCore import Qt, Signal  # type: ignore[import-not-found]
    from PySide6.QtGui import QColor, QPainter  # type: ignore[import-not-found]
    from PySide6.QtWidgets import QWidget  # type: ignore[import-not-found]

    class _VolumeFillBar(QWidget):
        """Volume control drawn as a fill bar.

        Vertical bars fill from the bottom; horizontal bars fill from the left.
        """

        valueChanged = Signal(int)
        released = Signal()

        def __init__(
            self,
            parent: Any = None,
            *,
            orientation: Any = Qt.Orientation.Vertical,
        ) -> None:
            super().__init__(parent)
            self._value = 0
            self._orientation = orientation
            self._track_color = QColor("#3a3a3a")
            self._fill_color = QColor("#60cdff")
            self._disabled_color = QColor("#888888")
            self._pressed = False
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        def setColors(self, track: str, fill: str, disabled: str) -> None:
            self._track_color = QColor(track)
            self._fill_color = QColor(fill)
            self._disabled_color = QColor(disabled)
            self.update()

        def value(self) -> int:
            return self._value

        def setValue(self, value: int) -> None:
            value = max(0, min(100, int(value)))
            if value == self._value:
                return
            self._value = value
            self.update()
            self.valueChanged.emit(value)

        def _value_from_position(self, x: float, y: float) -> int:
            if self._orientation == Qt.Orientation.Horizontal:
                width = max(1, self.width())
                ratio = max(0.0, min(1.0, x / width))
                return round(ratio * 100)
            height = max(1, self.height())
            ratio = 1.0 - max(0.0, min(1.0, y / height))
            return round(ratio * 100)

        def mousePressEvent(self, event: Any) -> None:
            if not self.isEnabled():
                return
            self._pressed = True
            self.setValue(
                self._value_from_position(
                    event.position().x(),
                    event.position().y(),
                )
            )

        def mouseMoveEvent(self, event: Any) -> None:
            if self._pressed:
                self.setValue(
                    self._value_from_position(
                        event.position().x(),
                        event.position().y(),
                    )
                )

        def mouseReleaseEvent(self, event: Any) -> None:
            if not self._pressed:
                return
            self._pressed = False
            self.setValue(
                self._value_from_position(
                    event.position().x(),
                    event.position().y(),
                )
            )
            self.released.emit()

        def paintEvent(self, event: Any) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = self.rect()
            radius = min(rect.width(), rect.height()) / 2.0
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._track_color)
            painter.drawRoundedRect(rect, radius, radius)
            if self._orientation == Qt.Orientation.Horizontal:
                fill_width = round(rect.width() * self._value / 100)
                fill_rect = rect.adjusted(0, 0, fill_width - rect.width(), 0)
                has_fill = fill_width > 0
            else:
                fill_height = round(rect.height() * self._value / 100)
                fill_rect = rect.adjusted(0, rect.height() - fill_height, 0, 0)
                has_fill = fill_height > 0
            if has_fill:
                painter.setBrush(
                    self._fill_color if self.isEnabled() else self._disabled_color
                )
                painter.drawRoundedRect(fill_rect, radius, radius)
            painter.end()

    _VOLUME_FILL_BAR_CLASS = _VolumeFillBar
    return _VOLUME_FILL_BAR_CLASS


def _mqtt_state_dispatcher_class() -> type[Any]:
    """Return a QObject that marshals MQTT state callbacks onto the Qt thread."""
    global _MQTT_STATE_DISPATCHER_CLASS
    if _MQTT_STATE_DISPATCHER_CLASS is not None:
        return _MQTT_STATE_DISPATCHER_CLASS

    from PySide6.QtCore import QObject, Qt, Signal, Slot  # type: ignore[import-not-found]

    class _MqttStateDispatcher(QObject):
        stateChanged = Signal(str, str)

        def __init__(self, handler: Callable[[str, str], None], parent: Any = None) -> None:
            super().__init__(parent)
            self._handler = handler
            self.stateChanged.connect(
                self._handle_state,
                Qt.ConnectionType.QueuedConnection,
            )

        def notify(self, state: str, detail: str) -> None:
            self.stateChanged.emit(state, detail)

        @Slot(str, str)
        def _handle_state(self, state: str, detail: str) -> None:
            try:
                self._handler(state, detail)
            except Exception:
                app_logging.get_logger("tray").exception("queued MQTT state handler failed")

    _MQTT_STATE_DISPATCHER_CLASS = _MqttStateDispatcher
    return _MQTT_STATE_DISPATCHER_CLASS


def _volume_event_dispatcher_class() -> type[Any]:
    """Return a QObject that marshals Windows volume events onto the Qt thread.

    `IAudioEndpointVolumeCallback::OnNotify` fires on a Windows-managed
    thread; emitting through a queued signal hops the payload to the Qt
    main loop before any widget is touched.
    """
    global _VOLUME_EVENT_DISPATCHER_CLASS
    if _VOLUME_EVENT_DISPATCHER_CLASS is not None:
        return _VOLUME_EVENT_DISPATCHER_CLASS

    from PySide6.QtCore import QObject, Qt, Signal, Slot  # type: ignore[import-not-found]

    class _VolumeEventDispatcher(QObject):
        volumeEvent = Signal(object)

        def __init__(self, handler: Callable[[Any], None], parent: Any = None) -> None:
            super().__init__(parent)
            self._handler = handler
            self.volumeEvent.connect(
                self._handle_event,
                Qt.ConnectionType.QueuedConnection,
            )

        def notify(self, event: Any) -> None:
            self.volumeEvent.emit(event)

        @Slot(object)
        def _handle_event(self, event: Any) -> None:
            try:
                self._handler(event)
            except Exception:
                app_logging.get_logger("tray").exception(
                    "queued volume event handler failed"
                )

    _VOLUME_EVENT_DISPATCHER_CLASS = _VolumeEventDispatcher
    return _VOLUME_EVENT_DISPATCHER_CLASS


def _ha_state_event_dispatcher_class() -> type[Any]:
    """Return a QObject that marshals HA WebSocket events onto the Qt thread."""
    global _HA_STATE_EVENT_DISPATCHER_CLASS
    if _HA_STATE_EVENT_DISPATCHER_CLASS is not None:
        return _HA_STATE_EVENT_DISPATCHER_CLASS

    from PySide6.QtCore import QObject, Qt, Signal, Slot  # type: ignore[import-not-found]

    class _HaStateEventDispatcher(QObject):
        haStateEvent = Signal(object)

        def __init__(self, handler: Callable[[Any], None], parent: Any = None) -> None:
            super().__init__(parent)
            self._handler = handler
            self.haStateEvent.connect(
                self._handle_event,
                Qt.ConnectionType.QueuedConnection,
            )

        def notify(self, event: Any) -> None:
            self.haStateEvent.emit(event)

        @Slot(object)
        def _handle_event(self, event: Any) -> None:
            try:
                self._handler(event)
            except Exception:
                app_logging.get_logger("tray").exception(
                    "queued HA state event handler failed"
                )

    _HA_STATE_EVENT_DISPATCHER_CLASS = _HaStateEventDispatcher
    return _HA_STATE_EVENT_DISPATCHER_CLASS


def _endpoint_event_dispatcher_class() -> type[Any]:
    """Return a QObject that marshals MMDevice endpoint events onto the Qt thread."""
    global _ENDPOINT_EVENT_DISPATCHER_CLASS
    if _ENDPOINT_EVENT_DISPATCHER_CLASS is not None:
        return _ENDPOINT_EVENT_DISPATCHER_CLASS

    from PySide6.QtCore import QObject, Qt, Signal, Slot  # type: ignore[import-not-found]

    class _EndpointEventDispatcher(QObject):
        endpointEvent = Signal(object)

        def __init__(self, handler: Callable[[Any], None], parent: Any = None) -> None:
            super().__init__(parent)
            self._handler = handler
            self.endpointEvent.connect(
                self._handle_event,
                Qt.ConnectionType.QueuedConnection,
            )

        def notify(self, event: Any) -> None:
            self.endpointEvent.emit(event)

        @Slot(object)
        def _handle_event(self, event: Any) -> None:
            try:
                self._handler(event)
            except Exception:
                app_logging.get_logger("tray").exception(
                    "queued endpoint event handler failed"
                )

    _ENDPOINT_EVENT_DISPATCHER_CLASS = _EndpointEventDispatcher
    return _ENDPOINT_EVENT_DISPATCHER_CLASS


class _StatusIndicator:  # pragma: no cover - imported only when GUI dependencies exist
    """Tinted service icon used to surface connection state."""

    def __init__(self, label: str, logo_asset: str) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QHBoxLayout,
            QLabel,
            QWidget,
        )

        self._label_prefix = label
        self._fallback_text = "".join(part[0] for part in label.split()).upper() or label
        if len(self._fallback_text) == 1:
            self._fallback_text = label[:4].upper()
        self._logo_asset = logo_asset
        self._state = "disabled"
        self._detail = ""
        self._state_colors = indicator_colors(DEFAULT_THEME)
        self.widget = QWidget()
        self.widget.setObjectName("trayPanelHeaderIndicatorBox")
        layout = QHBoxLayout(self.widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.logo = QLabel()
        self.logo.setObjectName("trayPanelHeaderIndicatorLogo")
        self.logo.setFixedSize(26, 26)
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.logo)

        self.set_state("disabled", "")

    def set_theme(self, theme: AppTheme) -> None:
        self._state_colors = indicator_colors(theme)
        self.set_state(self._state, self._detail)

    def set_state(self, state: str, detail: str) -> None:
        self._state = state
        self._detail = detail
        color = self._state_colors.get(state, self._state_colors["disabled"])
        logo_pixmap = qt_assets.svg_asset_pixmap(
            self._logo_asset,
            22,
            22,
            color=color,
        )
        if logo_pixmap.isNull():
            self.logo.setPixmap(logo_pixmap)
            self.logo.setText(self._fallback_text)
            self.logo.setStyleSheet(
                f"color: {color}; font-size: 10px; font-weight: 700;"
            )
        else:
            self.logo.setStyleSheet("")
            self.logo.setText("")
            self.logo.setPixmap(logo_pixmap)
        suffix = f": {detail}" if detail else ""
        self.widget.setToolTip(f"{self._label_prefix} {state}{suffix}")


