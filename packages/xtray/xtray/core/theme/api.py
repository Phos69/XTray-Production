"""Theme registry API: lookup, names, helper palettes."""
from __future__ import annotations

from dataclasses import asdict

from .dataclasses import AppTheme
from .palettes import DEFAULT_THEME, THEMES


def normalize_theme_name(name: str | None) -> str:
    key = str(name or "").strip().casefold().replace("-", "_")
    if key in THEMES:
        return key
    raise ValueError(f"theme must be one of: {', '.join(theme_names())}")


def theme_by_name(name: str | None) -> AppTheme:
    try:
        key = normalize_theme_name(name)
    except ValueError:
        return DEFAULT_THEME
    return THEMES[key]


def theme_names() -> tuple[str, ...]:
    return tuple(THEMES)


def theme_label(name: str | None) -> str:
    theme = theme_by_name(name)
    return theme.name.replace("_", " ").title()


def tray_palette(theme: AppTheme = DEFAULT_THEME) -> dict[str, str]:
    return asdict(theme.tray)


def indicator_colors(theme: AppTheme = DEFAULT_THEME) -> dict[str, str]:
    return {
        "connected": theme.tray.indicator_connected,
        "disconnected": theme.tray.indicator_disconnected,
        "disabled": theme.tray.indicator_disabled,
    }


def ping_button_style(theme: AppTheme = DEFAULT_THEME, state: str = "idle") -> str:
    if state == "success":
        background = theme.tray.success
        text_color = theme.tray.success_text
    elif state == "failure":
        background = theme.tray.close_hover
        text_color = theme.tray.close_text
    else:
        background = theme.tray.ping_idle
        text_color = theme.tray.ping_idle_text
    return (
        "QPushButton {"
        f" background-color: {background};"
        f" color: {text_color};"
        f" border: 1px solid {background};"
        f" border-radius: {theme.metrics.radius_small}px;"
        f" min-height: {theme.metrics.control_height}px;"
        " padding: 4px 11px;"
        " font-weight: 500;"
        "}"
    )


def ping_button_styles(theme: AppTheme = DEFAULT_THEME) -> dict[str, str]:
    return {state: ping_button_style(theme, state) for state in ("idle", "success", "failure")}
