"""Computer Manager local configuration (re-export of xtray.config).

Settings (MQTT, display_settings, display_order, theme, api_token,
last_applied_profile, hotkeys, tray_options) are persisted in xtray's
settings.json. Computer Manager and XTray share a single store; the legacy
``%APPDATA%/ComputerManager/settings.json`` (and even older
``%APPDATA%/DisplayManager/settings.json``) is migrated automatically on the
first read via ``xtray.config.migrate_legacy_settings``.

The package-specific AppData paths (profile directory and the inventory
snapshot) live in ``computer_manager.paths`` because they own filesystem
assets that XTray doesn't need.

The legacy ``COMPUTERMANAGER_*`` and ``DISPLAYMANAGER_*`` environment
variables remain documented here for backwards compatibility but no longer
have any effect on settings storage (XTray's ``XTRAY_*`` env vars take
precedence).
"""
# ruff: noqa: F401
from __future__ import annotations

from xtray.config import (
    DISPLAY_DEFAULT_ORIENTATIONS,
    DISPLAY_ORDER_KEY,
    DISPLAY_SETTINGS_KEY,
    LAST_APPLIED_PROFILE_KEY,
    MQTT_SETTINGS_KEY,
    THEME_KEY,
    THEME_NAMES,
    UNSET,
    VOLUME_CONTROL_HA_ENTITY,
    VOLUME_CONTROL_HDMI,
    VOLUME_CONTROL_MODES,
    VOLUME_CONTROL_NONE,
    ConfigError,
    assert_safe_api_bind,
    auth_disabled_by_env,
    default_mqtt_settings,
    ensure_api_token,
    get_api_token,
    get_display_order,
    get_display_setting_for_keys,
    get_display_settings,
    get_last_applied_profile,
    get_mqtt_password,
    get_mqtt_settings,
    get_theme_name,
    is_loopback_host,
    load_settings,
    redact_mqtt_settings,
    save_settings,
    set_api_token,
    set_display_order,
    set_display_setting_for_keys,
    set_last_applied_profile,
    set_mqtt_settings,
    set_theme_name,
    settings_path,
)

from .paths import (
    APP_NAME,
    LEGACY_APP_NAME,
    config_dir,
    legacy_config_dir,
    profiles_dir,
)

# Legacy env var names kept for documentation. Setting these no longer
# affects storage paths: xtray's XTRAY_* env vars apply instead.
ENV_API_TOKEN = "COMPUTERMANAGER_API_TOKEN"
ENV_APPDATA = "COMPUTERMANAGER_APPDATA"
ENV_CONFIG_DIR = "COMPUTERMANAGER_CONFIG_DIR"
ENV_LOCALAPPDATA = "COMPUTERMANAGER_LOCALAPPDATA"
ENV_PROFILES_DIR = "COMPUTERMANAGER_PROFILES_DIR"
ENV_UNSAFE_NO_AUTH = "COMPUTERMANAGER_UNSAFE_NO_AUTH"

LEGACY_ENV_API_TOKEN = "DISPLAYMANAGER_API_TOKEN"
LEGACY_ENV_APPDATA = "DISPLAYMANAGER_APPDATA"
LEGACY_ENV_CONFIG_DIR = "DISPLAYMANAGER_CONFIG_DIR"
LEGACY_ENV_LOCALAPPDATA = "DISPLAYMANAGER_LOCALAPPDATA"
LEGACY_ENV_PROFILES_DIR = "DISPLAYMANAGER_PROFILES_DIR"
LEGACY_ENV_UNSAFE_NO_AUTH = "DISPLAYMANAGER_UNSAFE_NO_AUTH"


def data_dir():
    """Backwards-compatible alias for :func:`config_dir`."""
    return config_dir()


def log_dir():
    """Computer Manager log directory.

    Lives next to the legacy ``%LOCALAPPDATA%\\ComputerManager\\logs`` for
    operator familiarity; this is independent of the settings file location.
    """
    import os
    from pathlib import Path

    root = os.environ.get("LOCALAPPDATA")
    base = Path(root) if root else Path.home() / ".local" / "state"
    path = base / APP_NAME / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
