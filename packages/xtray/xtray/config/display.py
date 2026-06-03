"""Theme, last-profile, and per-display settings."""
from __future__ import annotations

from typing import Any

from ..core.config_base import (
    DISPLAY_ORDER_KEY,
    DISPLAY_SETTINGS_KEY,
    LAST_APPLIED_PROFILE_KEY,
    THEME_KEY,
    UNSET,
    VOLUME_CONTROL_HA_ENTITY,
    VOLUME_CONTROL_HDMI,
    VOLUME_CONTROL_NONE,
)
from .store import load_settings, save_settings
from .validators import (
    ConfigError,
    bool_setting,
    normalize_ha_entity,
    normalize_ha_service,
    normalize_ha_service_data,
    normalize_orientation,
    normalize_positive_int,
    normalize_theme_name,
    normalize_volume_control,
    optional_text,
)


def get_last_applied_profile() -> str | None:
    value = load_settings().get(LAST_APPLIED_PROFILE_KEY)
    return value if isinstance(value, str) and value.strip() else None


def set_last_applied_profile(name: str | None) -> None:
    settings = load_settings()
    if name is None:
        settings.pop(LAST_APPLIED_PROFILE_KEY, None)
    else:
        value = str(name).strip()
        if not value:
            raise ConfigError("last applied profile name cannot be empty")
        settings[LAST_APPLIED_PROFILE_KEY] = value
    save_settings(settings)


def get_theme_name() -> str:
    value = load_settings().get(THEME_KEY, "vibrant")
    return normalize_theme_name(value)


def set_theme_name(name: str) -> str:
    value = normalize_theme_name(name)
    settings = load_settings()
    settings[THEME_KEY] = value
    save_settings(settings)
    return value


def get_display_settings() -> dict[str, dict[str, Any]]:
    """Return per-physical-display settings keyed by display stable identity."""
    return normalize_display_settings(load_settings().get(DISPLAY_SETTINGS_KEY))


def get_display_setting_for_keys(keys: list[str] | tuple[str, ...]) -> dict[str, Any]:
    settings = get_display_settings()
    for key in display_setting_keys(keys):
        entry = settings.get(key)
        if entry is not None:
            return dict(entry)
    return default_display_setting()


def set_display_setting_for_keys(
    canonical_key: str,
    aliases: list[str] | tuple[str, ...],
    *,
    friendly_name: Any = UNSET,
    expose_hdmi_volume: bool | None = None,
    volume_control: str | None = None,
    volume_ha_entity: str | None = None,
    power_on_ha_service: Any = UNSET,
    power_on_ha_service_data: Any = UNSET,
    power_off_ha_service: Any = UNSET,
    power_off_ha_service_data: Any = UNSET,
    default_width: Any = UNSET,
    default_height: Any = UNSET,
    default_refresh_hz: Any = UNSET,
    default_orientation: Any = UNSET,
) -> dict[str, Any]:
    canonical = normalize_display_setting_key(canonical_key)
    if not canonical:
        raise ConfigError("display setting key cannot be empty")
    keys = display_setting_keys((canonical, *aliases))
    settings = get_display_settings()
    merged = default_display_setting()
    for key in keys:
        entry = settings.get(key)
        if entry is not None:
            merged.update(entry)
    if volume_control is not None:
        mode = normalize_volume_control(volume_control)
    elif expose_hdmi_volume is not None:
        mode = VOLUME_CONTROL_HDMI if bool(expose_hdmi_volume) else VOLUME_CONTROL_NONE
    else:
        mode = merged.get("volume_control", VOLUME_CONTROL_NONE)
    merged["volume_control"] = mode
    if mode == VOLUME_CONTROL_HA_ENTITY:
        entity = volume_ha_entity if volume_ha_entity is not None else merged.get(
            "volume_ha_entity"
        )
        merged["volume_ha_entity"] = normalize_ha_entity(entity)
    else:
        merged["volume_ha_entity"] = None
    merged["expose_hdmi_volume"] = mode == VOLUME_CONTROL_HDMI
    if power_on_ha_service is not UNSET:
        service = normalize_ha_service(power_on_ha_service, name="power_on_ha_service")
        merged["power_on_ha_service"] = service
        if service is None:
            merged["power_on_ha_service_data"] = None
    if power_on_ha_service_data is not UNSET:
        merged["power_on_ha_service_data"] = normalize_ha_service_data(
            power_on_ha_service_data, name="power_on_ha_service_data"
        )
    if power_off_ha_service is not UNSET:
        service = normalize_ha_service(power_off_ha_service, name="power_off_ha_service")
        merged["power_off_ha_service"] = service
        if service is None:
            merged["power_off_ha_service_data"] = None
    if power_off_ha_service_data is not UNSET:
        merged["power_off_ha_service_data"] = normalize_ha_service_data(
            power_off_ha_service_data, name="power_off_ha_service_data"
        )
    if default_width is not UNSET:
        merged["default_width"] = normalize_positive_int(
            default_width, name="default_width"
        )
    if default_height is not UNSET:
        merged["default_height"] = normalize_positive_int(
            default_height, name="default_height"
        )
    if default_refresh_hz is not UNSET:
        merged["default_refresh_hz"] = normalize_positive_int(
            default_refresh_hz, name="default_refresh_hz"
        )
    if default_orientation is not UNSET:
        merged["default_orientation"] = normalize_orientation(default_orientation)
    if friendly_name is not UNSET:
        merged["friendly_name"] = optional_text(friendly_name, strip=True)
    for key in keys:
        if key != canonical:
            settings.pop(key, None)
    settings[canonical] = merged
    saved = load_settings()
    saved[DISPLAY_SETTINGS_KEY] = settings
    save_settings(saved)
    return dict(merged)


def get_display_order() -> list[str]:
    raw = load_settings().get(DISPLAY_ORDER_KEY)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError("display_order must be a list")
    order: list[str] = []
    for value in raw:
        key = normalize_display_setting_key(value)
        if key and key not in order:
            order.append(key)
    return order


def set_display_order(keys: list[str] | tuple[str, ...]) -> list[str]:
    order: list[str] = []
    for value in keys:
        key = normalize_display_setting_key(value)
        if key and key not in order:
            order.append(key)
    settings = load_settings()
    if order:
        settings[DISPLAY_ORDER_KEY] = order
    else:
        settings.pop(DISPLAY_ORDER_KEY, None)
    save_settings(settings)
    return order


def default_display_setting() -> dict[str, Any]:
    return {
        "friendly_name": None,
        "volume_control": VOLUME_CONTROL_NONE,
        "volume_ha_entity": None,
        "expose_hdmi_volume": False,
        "power_on_ha_service": None,
        "power_on_ha_service_data": None,
        "power_off_ha_service": None,
        "power_off_ha_service_data": None,
        "default_width": None,
        "default_height": None,
        "default_refresh_hz": None,
        "default_orientation": None,
    }


def normalize_display_settings(value: Any) -> dict[str, dict[str, Any]]:
    if value is None:
        raw: dict[Any, Any] = {}
    elif isinstance(value, dict):
        raw = value
    else:
        raise ConfigError("display_settings must be an object")

    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_entry in raw.items():
        key = normalize_display_setting_key(raw_key)
        if not key:
            continue
        if isinstance(raw_entry, bool):
            entry: dict[str, Any] = {"expose_hdmi_volume": raw_entry}
        elif isinstance(raw_entry, dict):
            entry = raw_entry
        else:
            raise ConfigError(f"display_settings.{key} must be an object")
        if "volume_control" in entry:
            mode = normalize_volume_control(
                entry.get("volume_control"),
                name=f"display_settings.{key}.volume_control",
            )
        elif "expose_hdmi_volume" in entry:
            exposed = bool_setting(
                entry.get("expose_hdmi_volume"),
                f"display_settings.{key}.expose_hdmi_volume",
            )
            mode = VOLUME_CONTROL_HDMI if exposed else VOLUME_CONTROL_NONE
        else:
            mode = VOLUME_CONTROL_NONE
        ha_entity = (
            normalize_ha_entity(entry.get("volume_ha_entity"))
            if mode == VOLUME_CONTROL_HA_ENTITY
            else None
        )
        normalized[key] = {
            "friendly_name": optional_text(entry.get("friendly_name"), strip=True),
            "volume_control": mode,
            "volume_ha_entity": ha_entity,
            "expose_hdmi_volume": mode == VOLUME_CONTROL_HDMI,
            "power_on_ha_service": normalize_ha_service(
                entry.get("power_on_ha_service"),
                name=f"display_settings.{key}.power_on_ha_service",
            ),
            "power_on_ha_service_data": normalize_ha_service_data(
                entry.get("power_on_ha_service_data"),
                name=f"display_settings.{key}.power_on_ha_service_data",
            ),
            "power_off_ha_service": normalize_ha_service(
                entry.get("power_off_ha_service"),
                name=f"display_settings.{key}.power_off_ha_service",
            ),
            "power_off_ha_service_data": normalize_ha_service_data(
                entry.get("power_off_ha_service_data"),
                name=f"display_settings.{key}.power_off_ha_service_data",
            ),
            "default_width": normalize_positive_int(
                entry.get("default_width"),
                name=f"display_settings.{key}.default_width",
            ),
            "default_height": normalize_positive_int(
                entry.get("default_height"),
                name=f"display_settings.{key}.default_height",
            ),
            "default_refresh_hz": normalize_positive_int(
                entry.get("default_refresh_hz"),
                name=f"display_settings.{key}.default_refresh_hz",
            ),
            "default_orientation": normalize_orientation(
                entry.get("default_orientation"),
                name=f"display_settings.{key}.default_orientation",
            ),
        }
    return normalized


def display_setting_keys(keys: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for key in keys:
        value = normalize_display_setting_key(key)
        if value and value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def normalize_display_setting_key(value: Any) -> str:
    return str(value or "").strip().casefold()
