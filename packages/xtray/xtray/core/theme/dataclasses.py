"""Theme token dataclasses (button roles, palette, scene, tray, metrics)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ButtonRole:
    background: str
    hover: str
    pressed: str
    text: str
    border: str


@dataclass(frozen=True)
class ButtonTheme:
    default: ButtonRole
    primary: ButtonRole
    success: ButtonRole
    danger: ButtonRole
    info: ButtonRole
    accent: ButtonRole
    disabled_background: str
    disabled_text: str
    disabled_border: str


@dataclass(frozen=True)
class SceneTheme:
    shelf_fill: str
    shelf_border: str
    shelf_title: str
    audio_fill: str
    audio_border: str
    audio_text: str
    object_fill: str
    object_border: str
    object_text: str
    monitor_primary_fill: str
    monitor_primary_border: str
    monitor_fill: str
    monitor_border: str
    monitor_text: str
    monitor_number_primary: str
    monitor_number: str
    monitor_number_alpha: int


@dataclass(frozen=True)
class PaletteTheme:
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_text: str
    success: str
    success_hover: str
    success_pressed: str
    success_text: str
    warning: str
    warning_hover: str
    warning_pressed: str
    warning_text: str
    danger: str
    danger_hover: str
    danger_pressed: str
    danger_text: str
    info: str
    info_hover: str
    info_pressed: str
    info_text: str


@dataclass(frozen=True)
class TableTheme:
    header_background: str
    header_text: str
    grid_line: str
    alternate_row: str
    hover_row: str
    match_background: str
    match_text: str


@dataclass(frozen=True)
class TrayTheme:
    surface: str
    control: str
    row_surface: str
    row_surface_hover: str
    primary_display_surface: str
    primary_display_surface_hover: str
    primary_display_border: str
    primary_display_text: str
    control_hover: str
    control_pressed: str
    border: str
    subtle_border: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_text: str
    success: str
    success_hover: str
    success_pressed: str
    success_text: str
    warning: str
    warning_hover: str
    warning_pressed: str
    warning_text: str
    close_hover: str
    close_pressed: str
    close_text: str
    indicator_connected: str
    indicator_disconnected: str
    indicator_disabled: str
    ping_idle: str
    ping_idle_text: str
    faceplate_enabled_bg: str
    faceplate_enabled_border: str
    faceplate_enabled_text: str
    faceplate_disabled_bg: str
    faceplate_disabled_border: str
    faceplate_disabled_text: str
    faceplate_primary_bg: str
    faceplate_primary_border: str
    faceplate_primary_text: str
    faceplate_unavailable_bg: str
    faceplate_unavailable_border: str
    faceplate_unavailable_text: str


@dataclass(frozen=True)
class MetricsTheme:
    radius_small: int = 6
    radius_medium: int = 8
    radius_panel: int = 14
    control_height: int = 30
    app_control_height: int = 28
    display_action_row_height: int = 32
    display_power_button_width: int = 40
    display_toggle_button_width: int = 80


@dataclass(frozen=True)
class AppTheme:
    name: str
    window_background: str
    panel_background: str
    panel_border: str
    control_background: str
    control_border: str
    control_focus: str
    text: str
    muted_text: str
    selection_background: str
    selection_text: str
    buttons: ButtonTheme
    scene: SceneTheme
    palette: PaletteTheme
    tables: TableTheme
    tray: TrayTheme
    metrics: MetricsTheme


_DEFAULT_METRICS = MetricsTheme()
