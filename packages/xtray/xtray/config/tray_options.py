"""Tray visibility and layout settings."""
from __future__ import annotations

from typing import Any

from xtray.core.icons import normalize_icon_name

from ..core.config_base import TRAY_OPTIONS_KEY
from .store import load_settings, save_settings
from .tray_action_icons import (
    default_tray_action_icons,
    normalize_tray_action_icons,
)
from .validators import ConfigError, bool_setting

MEDIA_ROW_ORDER = (
    "media_displays",
    "audio_output",
)
DEFAULT_MEDIA_PROFILE_COLUMNS = 3
MIN_MEDIA_PROFILE_COLUMNS = 2
MAX_TRAY_LAYOUT_COLUMNS = 8

TRAY_OPTION_KEYS = frozenset(
    {
        "show_media_tab",
        "show_display_profiles",
        "show_adapters_tab",
        "show_adapters_popup",
        "show_network_tab",
        "show_drives_tab",
        "show_displays_popup",
        "show_pc_volume",
        "show_audio_output",
        "show_display_volume",
        "show_media_displays",
        "show_media_drives",
        "show_home_assistant_indicator",
        "show_mqtt_indicator",
        "show_options_button",
        "show_network_manager_button",
        "show_computer_manager_button",
        "show_restart_button",
        "media_profile_columns",
        "display_grid_columns",
        "media_row_order",
        "visible_adapter_ids",
        "adapter_icons",
        "visible_drive_ids",
        "action_icons",
    }
)


def default_tray_options() -> dict[str, Any]:
    return {
        "show_media_tab": True,
        "show_display_profiles": True,
        "show_adapters_tab": True,
        "show_adapters_popup": True,
        "show_network_tab": True,
        "show_drives_tab": True,
        "show_displays_popup": True,
        "show_pc_volume": True,
        "show_audio_output": True,
        "show_display_volume": True,
        "show_media_displays": True,
        "show_media_drives": False,
        "show_home_assistant_indicator": True,
        "show_mqtt_indicator": True,
        "show_options_button": True,
        "show_network_manager_button": True,
        "show_computer_manager_button": True,
        "show_restart_button": True,
        "media_profile_columns": DEFAULT_MEDIA_PROFILE_COLUMNS,
        "display_grid_columns": 2,
        "media_row_order": list(MEDIA_ROW_ORDER),
        "visible_adapter_ids": None,
        "adapter_icons": {},
        "visible_drive_ids": None,
        "action_icons": default_tray_action_icons(),
    }


def get_tray_options() -> dict[str, Any]:
    return normalize_tray_options(load_settings().get(TRAY_OPTIONS_KEY))


def set_tray_options(**updates: Any) -> dict[str, Any]:
    unknown = sorted(set(updates) - TRAY_OPTION_KEYS)
    if unknown:
        raise ConfigError(f"unknown tray option: {', '.join(unknown)}")
    current_options = get_tray_options()
    if isinstance(updates.get("action_icons"), dict):
        current_action_icons = current_options.get("action_icons", {})
        merged_action_icons = {
            action_id: dict(action)
            for action_id, action in current_action_icons.items()
            if isinstance(action, dict)
        }
        for action_id, action_update in updates["action_icons"].items():
            if isinstance(action_update, dict):
                merged_action_icons[str(action_id)] = {
                    **merged_action_icons.get(str(action_id), {}),
                    **action_update,
                }
            else:
                merged_action_icons[str(action_id)] = action_update
        updates = {
            **updates,
            "action_icons": merged_action_icons,
        }
    options = {**current_options, **updates}
    options = normalize_tray_options(options)
    settings = load_settings()
    settings[TRAY_OPTIONS_KEY] = options
    save_settings(settings)
    return options


def normalize_tray_options(value: Any) -> dict[str, Any]:
    if value is None:
        raw: dict[str, Any] = {}
    elif isinstance(value, dict):
        raw = value
    else:
        raise ConfigError("tray_options must be an object")

    defaults = default_tray_options()
    normalized: dict[str, Any] = {}
    for key, default in defaults.items():
        if key in {"visible_adapter_ids", "visible_drive_ids"}:
            normalized[key] = _optional_string_list(
                raw.get(key, default),
                name=f"tray_options.{key}",
            )
        elif key == "adapter_icons":
            normalized[key] = _adapter_icons(raw.get(key, default))
        elif key == "media_row_order":
            normalized[key] = _media_row_order(
                raw.get(key, default),
                name=f"tray_options.{key}",
            )
        elif key == "action_icons":
            normalized[key] = normalize_tray_action_icons(raw.get(key, default))
        elif key == "media_profile_columns":
            normalized[key] = _media_profile_columns(
                raw.get(key, default),
                name=f"tray_options.{key}",
            )
        elif key == "show_adapters_tab" and "show_adapters_popup" not in raw:
            normalized[key] = default
        elif key == "show_adapters_popup" and "show_adapters_popup" not in raw:
            normalized[key] = bool_setting(
                raw.get("show_adapters_tab", default),
                "tray_options.show_adapters_popup",
            )
        elif isinstance(default, bool):
            normalized[key] = bool_setting(raw.get(key, default), f"tray_options.{key}")
        else:
            normalized[key] = _bounded_int(
                raw.get(key, default),
                name=f"tray_options.{key}",
                minimum=1,
                maximum=MAX_TRAY_LAYOUT_COLUMNS,
            )
    return normalized


def _media_profile_columns(value: Any, *, name: str) -> int:
    count = _bounded_int(
        value,
        name=name,
        minimum=1,
        maximum=MAX_TRAY_LAYOUT_COLUMNS,
    )
    if count < MIN_MEDIA_PROFILE_COLUMNS:
        return DEFAULT_MEDIA_PROFILE_COLUMNS
    return count


def _media_row_order(value: Any, *, name: str) -> list[str]:
    if not isinstance(value, list):
        raise ConfigError(f"{name} must be a list of media row ids")
    valid = set(MEDIA_ROW_ORDER)
    normalized: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text == "display_profiles":
            text = "media_displays"
        if text in valid and text not in normalized:
            normalized.append(text)
    for item in MEDIA_ROW_ORDER:
        if item not in normalized:
            normalized.append(item)
    return normalized


def _optional_string_list(value: Any, *, name: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ConfigError(f"{name} must be a list of strings")
    normalized: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _adapter_icons(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError("tray_options.adapter_icons must be an object")
    normalized: dict[str, str] = {}
    for key, raw_icon in value.items():
        adapter_name = str(key or "").strip()
        icon_name = normalize_icon_name(raw_icon)
        if adapter_name and icon_name:
            normalized[adapter_name] = icon_name
    return normalized


def _bounded_int(value: Any, *, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ConfigError(f"{name} must be between {minimum} and {maximum}")
        try:
            value = int(text)
        except ValueError as exc:
            raise ConfigError(f"{name} must be between {minimum} and {maximum}") from exc
    if isinstance(value, float):
        if not value.is_integer():
            raise ConfigError(f"{name} must be between {minimum} and {maximum}")
        value = int(value)
    if not isinstance(value, int):
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return value
