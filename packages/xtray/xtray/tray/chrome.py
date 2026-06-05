"""Window chrome, icon, and theme helpers for the tray windows."""
from __future__ import annotations

from typing import Any

from xtray.core import icons, qt_helpers
from xtray.core.theme import DEFAULT_THEME, AppTheme, theme_by_name

from .. import config
from ..core import app_logging, qt_assets

_clear_layout = qt_helpers.clear_layout


def _current_theme() -> AppTheme:
    try:
        return theme_by_name(config.get_theme_name())
    except config.ConfigError as exc:
        app_logging.get_logger("tray").warning("invalid theme setting: %s", exc)
        return DEFAULT_THEME


def _qicon_for_first(
    icon_names: tuple[str | None, ...],
    *,
    color: str | None = None,
    size: int = 64,
) -> Any:
    from PySide6.QtGui import QIcon  # type: ignore[import-not-found]

    for icon_name in icon_names:
        if not icon_name:
            continue
        icon = icons.qicon_for(icon_name, color=color, size=size)
        if not icon.isNull():
            return icon
    return QIcon()


def _app_icon(theme: AppTheme | None = None) -> Any:
    icon = qt_assets.tray_icon(accent_color=(theme or _current_theme()).tray.accent)
    if icon.isNull():
        app_logging.get_logger("tray").warning("could not load tray icon asset")
    return icon
