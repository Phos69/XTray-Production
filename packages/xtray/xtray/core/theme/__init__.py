"""Centralised visual theme tokens for the desktop UI.

Split across:

* :mod:`xtray.core.theme.dataclasses` -- frozen dataclass tokens
* :mod:`xtray.core.theme.palettes` -- ``DEFAULT_THEME``, named themes, accent generator
* :mod:`xtray.core.theme.api` -- registry helpers (``theme_by_name``, ``theme_names``, ...)
* :mod:`xtray.core.theme.qss` -- ``build_app_stylesheet``, ``build_tray_stylesheet``
"""
from .api import (
    indicator_colors,
    normalize_theme_name,
    ping_button_style,
    ping_button_styles,
    theme_by_name,
    theme_label,
    theme_names,
    tray_palette,
)
from .dataclasses import (
    AppTheme,
    ButtonRole,
    ButtonTheme,
    MetricsTheme,
    PaletteTheme,
    SceneTheme,
    TableTheme,
    TrayTheme,
)
from .palettes import (
    ACCENT_THEMES,
    DARK_THEME,
    DEFAULT_THEME,
    GRAPHITE_THEME,
    HIGH_CONTRAST_THEME,
    OCEAN_THEME,
    THEMES,
)
from .qss import build_app_stylesheet, build_stylesheet, build_tray_stylesheet

__all__ = [
    "ACCENT_THEMES",
    "AppTheme",
    "ButtonRole",
    "ButtonTheme",
    "DARK_THEME",
    "DEFAULT_THEME",
    "GRAPHITE_THEME",
    "HIGH_CONTRAST_THEME",
    "MetricsTheme",
    "OCEAN_THEME",
    "PaletteTheme",
    "SceneTheme",
    "THEMES",
    "TableTheme",
    "TrayTheme",
    "build_app_stylesheet",
    "build_stylesheet",
    "build_tray_stylesheet",
    "indicator_colors",
    "normalize_theme_name",
    "ping_button_style",
    "ping_button_styles",
    "theme_by_name",
    "theme_label",
    "theme_names",
    "tray_palette",
]
