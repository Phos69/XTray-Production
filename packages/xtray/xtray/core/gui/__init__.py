"""Shared Qt GUI helpers for XTray, Computer Manager, and Network Manager."""
from __future__ import annotations

import sys
from typing import Any

from xtray.core.theme import (
    DEFAULT_THEME,
    AppTheme,
    build_app_stylesheet,
    build_tray_stylesheet,
)

_COMBOBOX_WHEEL_GUARD_ATTR = "_xtray_combobox_wheel_guard"
_SLIDER_WHEEL_GUARD_ATTR = "_xtray_slider_wheel_guard"
_QT_MESSAGE_HANDLER: Any | None = None
_BENIGN_QT_FONT_WARNING = (
    "QFont::setPointSize: Point size <= 0 (-1), must be greater than 0"
)


def install_qt_message_handler(app_name: str = "xtray") -> None:
    """Route Qt messages through the app logger and drop one benign startup warning."""
    global _QT_MESSAGE_HANDLER
    if _QT_MESSAGE_HANDLER is not None:
        return

    from PySide6.QtCore import QtMsgType, qInstallMessageHandler  # type: ignore[import-not-found]

    from xtray.core import app_logging

    logger = app_logging.get_logger("qt", app_name=app_name)

    def _handler(mode: Any, context: Any, message: str) -> None:
        text = str(message)
        if text == _BENIGN_QT_FONT_WARNING:
            return
        category = str(getattr(context, "category", "") or "")
        if category and category != "default":
            text = f"{category}: {text}"
        if mode == QtMsgType.QtDebugMsg:
            logger.debug(text)
        elif mode == QtMsgType.QtInfoMsg:
            logger.info(text)
        elif mode == QtMsgType.QtWarningMsg:
            logger.warning(text)
        else:
            logger.error(text)

    _QT_MESSAGE_HANDLER = _handler
    qInstallMessageHandler(_handler)


def ensure_valid_application_font(
    app: Any | None = None,
    *,
    fallback_point_size: int = 9,
) -> bool:
    """Ensure QApplication's default font has a positive point size."""
    from PySide6.QtWidgets import QApplication  # type: ignore[import-not-found]

    target_app = app or QApplication.instance()
    if target_app is None:
        return False
    font = target_app.font()
    if font.pointSize() > 0 or font.pointSizeF() > 0:
        return False

    point_size = max(1, int(fallback_point_size))
    pixel_size = font.pixelSize()
    if pixel_size > 0:
        try:
            screen = target_app.primaryScreen()
            dpi = float(screen.logicalDotsPerInchY()) if screen is not None else 0.0
        except Exception:
            dpi = 0.0
        if dpi > 0:
            point_size = max(1, round(pixel_size * 72.0 / dpi))

    font.setPointSize(point_size)
    target_app.setFont(font)
    return True


def install_combobox_wheel_guard(app: Any | None = None) -> None:
    """Prevent mouse-wheel gestures from changing collapsed combo boxes."""
    from PySide6.QtCore import QEvent, QObject  # type: ignore[import-not-found]
    from PySide6.QtWidgets import QApplication, QComboBox  # type: ignore[import-not-found]

    target_app = app or QApplication.instance()
    if target_app is None:
        return
    if getattr(target_app, _COMBOBOX_WHEEL_GUARD_ATTR, None) is not None:
        return

    class _ComboBoxWheelGuard(QObject):
        def eventFilter(self, watched: Any, event: Any) -> bool:
            if event.type() == QEvent.Type.Wheel and isinstance(watched, QComboBox):
                event.accept()
                return True
            return False

    guard = _ComboBoxWheelGuard(target_app)
    target_app.installEventFilter(guard)
    setattr(target_app, _COMBOBOX_WHEEL_GUARD_ATTR, guard)


def install_slider_wheel_guard(app: Any | None = None) -> None:
    """Redirect mouse-wheel events from sliders to the enclosing scroll area.

    Without this, scrolling over a QSlider would change its value (and thus
    silently start altering volume etc.), which is rarely what the user
    intends inside a scrollable panel. We forward the wheel event to the
    nearest QAbstractScrollArea so the panel scrolls instead.
    """
    from PySide6.QtCore import QEvent, QObject  # type: ignore[import-not-found]
    from PySide6.QtWidgets import (  # type: ignore[import-not-found]
        QAbstractScrollArea,
        QApplication,
        QSlider,
    )

    target_app = app or QApplication.instance()
    if target_app is None:
        return
    if getattr(target_app, _SLIDER_WHEEL_GUARD_ATTR, None) is not None:
        return

    class _SliderWheelGuard(QObject):
        def eventFilter(self, watched: Any, event: Any) -> bool:
            if event.type() != QEvent.Type.Wheel or not isinstance(watched, QSlider):
                return False
            ancestor = watched.parent()
            while ancestor is not None:
                if isinstance(ancestor, QAbstractScrollArea):
                    QApplication.sendEvent(ancestor.viewport(), event)
                    return True
                ancestor = ancestor.parent()
            # No scrollable ancestor: swallow it so the slider value doesn't
            # change accidentally.
            event.accept()
            return True

    guard = _SliderWheelGuard(target_app)
    target_app.installEventFilter(guard)
    setattr(target_app, _SLIDER_WHEEL_GUARD_ATTR, guard)


def apply_app_theme(widget: Any, theme: AppTheme = DEFAULT_THEME) -> None:
    install_combobox_wheel_guard()
    widget.setStyleSheet(build_app_stylesheet(theme))


def apply_tray_theme(widget: Any, theme: AppTheme = DEFAULT_THEME) -> None:
    install_combobox_wheel_guard()
    configure_native_tray_window(widget, theme)
    widget.setStyleSheet(build_app_stylesheet(theme) + "\n" + build_tray_stylesheet(theme))


def set_button_role(button: Any, role: str | None) -> None:
    button.setProperty("role", role or "")
    repolish(button)


def repolish(widget: Any) -> None:
    if not hasattr(widget, "style"):
        return
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def configure_native_tray_window(window: Any, theme: AppTheme = DEFAULT_THEME) -> None:
    from PySide6.QtCore import Qt  # type: ignore[import-not-found]

    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    window.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    dark = theme.name == "dark" or theme.name.endswith("_dark") or theme.name == "high_contrast"
    apply_windows_dwm_style(window, dark=dark)


def apply_windows_dwm_style(window: Any, *, dark: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = wintypes.HWND(int(window.winId()))
        dwmapi = ctypes.WinDLL("dwmapi")
        set_window_attribute = dwmapi.DwmSetWindowAttribute
        set_window_attribute.argtypes = [
            wintypes.HWND,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]

        def set_int_attribute(attribute: int, value: int) -> None:
            raw_value = ctypes.c_int(value)
            set_window_attribute(
                hwnd,
                ctypes.c_uint(attribute),
                ctypes.byref(raw_value),
                ctypes.sizeof(raw_value),
            )

        set_int_attribute(33, 2)
        set_int_attribute(38, 3)
        set_int_attribute(20, 1 if dark else 0)
    except Exception:
        return
