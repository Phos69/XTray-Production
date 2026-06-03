"""Global hotkey settings."""
from __future__ import annotations

from typing import Any

from ..core.config_base import HOTKEYS_KEY
from .store import load_settings, save_settings
from .validators import ConfigError, bool_setting, optional_text

HOTKEY_SETTING_KEYS = frozenset({"toggle_panel_enabled", "toggle_panel"})


def default_hotkey_settings() -> dict[str, Any]:
    return {
        "toggle_panel_enabled": True,
        "toggle_panel": "Ctrl+Alt+X",
    }


def get_hotkey_settings() -> dict[str, Any]:
    return normalize_hotkey_settings(load_settings().get(HOTKEYS_KEY))


def set_hotkey_settings(**updates: Any) -> dict[str, Any]:
    unknown = sorted(set(updates) - HOTKEY_SETTING_KEYS)
    if unknown:
        raise ConfigError(f"unknown hotkey setting: {', '.join(unknown)}")
    settings = {**get_hotkey_settings(), **updates}
    settings = normalize_hotkey_settings(settings)
    saved = load_settings()
    saved[HOTKEYS_KEY] = settings
    save_settings(saved)
    return settings


def normalize_hotkey_settings(value: Any) -> dict[str, Any]:
    if value is None:
        raw: dict[str, Any] = {}
    elif isinstance(value, dict):
        raw = value
    else:
        raise ConfigError("hotkeys must be an object")

    defaults = default_hotkey_settings()
    enabled = bool_setting(
        raw.get("toggle_panel_enabled", defaults["toggle_panel_enabled"]),
        "hotkeys.toggle_panel_enabled",
    )
    sequence = optional_text(raw.get("toggle_panel", defaults["toggle_panel"]), strip=True)
    if enabled and not sequence:
        raise ConfigError("hotkeys.toggle_panel is required when the hotkey is enabled")
    return {
        "toggle_panel_enabled": enabled,
        "toggle_panel": sequence or defaults["toggle_panel"],
    }
