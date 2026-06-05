"""Shared configuration constants."""
from __future__ import annotations

from typing import Any

from .theme import theme_names

MQTT_SETTINGS_KEY = "mqtt"
LAST_APPLIED_PROFILE_KEY = "last_applied_profile"
THEME_KEY = "theme"
DISPLAY_SETTINGS_KEY = "display_settings"
DISPLAY_ORDER_KEY = "display_order"
TRAY_OPTIONS_KEY = "tray_options"
HOTKEYS_KEY = "hotkeys"
EXPERIMENTAL_FEATURES_KEY = "experimental_features"
MIGRATED_SETTINGS_KEYS = frozenset(
    {
        "api_token",
        MQTT_SETTINGS_KEY,
        THEME_KEY,
        DISPLAY_SETTINGS_KEY,
        DISPLAY_ORDER_KEY,
        LAST_APPLIED_PROFILE_KEY,
        TRAY_OPTIONS_KEY,
        HOTKEYS_KEY,
        EXPERIMENTAL_FEATURES_KEY,
        "network_manager",
    }
)

THEME_NAMES = frozenset(theme_names())

VOLUME_CONTROL_NONE = "none"
VOLUME_CONTROL_HDMI = "hdmi"
VOLUME_CONTROL_HA_ENTITY = "ha_entity"
VOLUME_CONTROL_MODES = frozenset(
    {VOLUME_CONTROL_NONE, VOLUME_CONTROL_HDMI, VOLUME_CONTROL_HA_ENTITY}
)

DISPLAY_DEFAULT_ORIENTATIONS = frozenset({0, 90, 180, 270})

MQTT_FIXED_ENTITY_KEYS = frozenset(
    {
        "current_profile",
        "profile_select",
        "volume",
        "audio_output",
        "play_pause",
        "mute_toggle",
        "mute",
        "unmute",
        "muted",
        "shutdown",
        "online",
        "power",
    }
)

UNSET: Any = object()
