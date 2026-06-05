"""MQTT settings schema and normalization."""
from __future__ import annotations

from typing import Any

from ..core.config_base import MQTT_FIXED_ENTITY_KEYS, MQTT_SETTINGS_KEY
from .store import load_settings, save_settings
from .validators import (
    ConfigError,
    bool_setting,
    hostname_slug,
    normalize_ha_url,
    optional_text,
    topic_setting,
)


def default_mqtt_settings() -> dict[str, Any]:
    hostname = hostname_slug()
    return {
        "enabled": False,
        "host": "",
        "port": 1883,
        "username": None,
        "password": None,
        "tls": False,
        "client_id": f"xtray-{hostname}",
        "base_topic": f"xtray/{hostname}",
        "discovery_prefix": "homeassistant",
        "allow_shutdown": False,
        "device_name": None,
        "home_assistant_enabled": False,
        "home_assistant_url": None,
        "home_assistant_token": None,
        "entities": default_mqtt_entities(allow_shutdown=False),
    }


def get_mqtt_settings() -> dict[str, Any]:
    raw = load_settings().get(MQTT_SETTINGS_KEY, {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("mqtt settings must be an object")
    settings = {**default_mqtt_settings(), **raw}
    if "home_assistant_enabled" not in raw:
        settings["home_assistant_enabled"] = bool(
            raw.get("home_assistant_url") or raw.get("home_assistant_token")
        )
    if "entities" not in raw:
        settings.pop("entities", None)
    return normalize_mqtt_settings(settings)


def set_mqtt_settings(**updates: Any) -> dict[str, Any]:
    unknown = sorted(set(updates) - set(default_mqtt_settings()))
    if unknown:
        raise ConfigError(f"unknown mqtt setting: {', '.join(unknown)}")
    settings = {**get_mqtt_settings(), **updates}
    if "allow_shutdown" in updates and "entities" not in updates:
        entities = dict(settings.get("entities") or {})
        for key in ("shutdown", "power"):
            entry = dict(entities.get(key) or {})
            entry["enabled"] = bool(updates["allow_shutdown"])
            entities[key] = entry
        settings["entities"] = entities
    settings = normalize_mqtt_settings(settings, require_host=bool(settings.get("enabled")))
    saved = load_settings()
    saved[MQTT_SETTINGS_KEY] = settings
    save_settings(saved)
    return settings


def redact_mqtt_settings(settings: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(settings)
    if redacted.get("password"):
        redacted["password"] = "<MQTT_PASSWORD>"
    if redacted.get("home_assistant_token"):
        redacted["home_assistant_token"] = "<HA_TOKEN>"
    return redacted


def get_mqtt_password() -> str | None:
    try:
        password = get_mqtt_settings().get("password")
    except ConfigError:
        return None
    return password if isinstance(password, str) and password else None


def normalize_mqtt_settings(
    settings: dict[str, Any], *, require_host: bool = False
) -> dict[str, Any]:
    normalized = dict(settings)
    normalized["enabled"] = bool_setting(normalized.get("enabled"), "mqtt.enabled")
    normalized["tls"] = bool_setting(normalized.get("tls"), "mqtt.tls")
    normalized["allow_shutdown"] = bool_setting(
        normalized.get("allow_shutdown", False), "mqtt.allow_shutdown"
    )
    normalized["home_assistant_enabled"] = bool_setting(
        normalized.get("home_assistant_enabled", False),
        "mqtt.home_assistant_enabled",
    )
    normalized["host"] = optional_text(normalized.get("host"), strip=True) or ""
    if require_host and not normalized["host"]:
        raise ConfigError("mqtt host is required when MQTT is enabled")
    try:
        normalized["port"] = int(normalized.get("port", 1883))
    except (TypeError, ValueError) as exc:
        raise ConfigError("mqtt port must be an integer") from exc
    if not 1 <= normalized["port"] <= 65535:
        raise ConfigError("mqtt port must be between 1 and 65535")
    normalized["username"] = optional_text(normalized.get("username"), strip=True)
    normalized["password"] = optional_text(normalized.get("password"), strip=False)
    normalized["client_id"] = optional_text(normalized.get("client_id"), strip=True) or (
        f"xtray-{hostname_slug()}"
    )
    normalized["base_topic"] = topic_setting(
        normalized.get("base_topic") or default_mqtt_settings()["base_topic"],
        "mqtt.base_topic",
    )
    normalized["discovery_prefix"] = topic_setting(
        normalized.get("discovery_prefix") or "homeassistant",
        "mqtt.discovery_prefix",
    )
    normalized["device_name"] = optional_text(normalized.get("device_name"), strip=True)
    normalized["home_assistant_url"] = normalize_ha_url(normalized.get("home_assistant_url"))
    normalized["home_assistant_token"] = optional_text(
        normalized.get("home_assistant_token"), strip=True
    )
    normalized["entities"] = normalize_mqtt_entities(
        normalized.get("entities"),
        allow_shutdown=normalized["allow_shutdown"],
    )
    normalized["allow_shutdown"] = bool(
        normalized["entities"]["shutdown"]["enabled"]
        or normalized["entities"]["power"]["enabled"]
    )
    return normalized


def default_mqtt_entities(*, allow_shutdown: bool) -> dict[str, dict[str, Any]]:
    return {
        "current_profile": {"enabled": True, "name": None},
        "profile_select": {"enabled": True, "name": None},
        "volume": {"enabled": True, "name": None},
        "audio_output": {"enabled": True, "name": None},
        "play_pause": {"enabled": True, "name": None},
        "mute_toggle": {"enabled": True, "name": None},
        "mute": {"enabled": True, "name": None},
        "unmute": {"enabled": True, "name": None},
        "muted": {"enabled": True, "name": None},
        "shutdown": {"enabled": allow_shutdown, "name": None},
        "online": {"enabled": True, "name": None},
        "power": {"enabled": allow_shutdown, "name": None},
    }


def normalize_mqtt_entities(
    value: Any,
    *,
    allow_shutdown: bool,
) -> dict[str, dict[str, Any]]:
    if value is None:
        raw: dict[Any, Any] = {}
    elif isinstance(value, dict):
        raw = value
    else:
        raise ConfigError("mqtt.entities must be an object")

    defaults = default_mqtt_entities(allow_shutdown=allow_shutdown)
    normalized: dict[str, dict[str, Any]] = {
        key: dict(default_entry) for key, default_entry in defaults.items()
    }
    for raw_key, raw_entry in raw.items():
        key = normalize_mqtt_entity_key(raw_key)
        if isinstance(raw_entry, bool):
            entry = {"enabled": raw_entry}
        elif isinstance(raw_entry, dict):
            entry = raw_entry
        else:
            raise ConfigError(f"mqtt.entities.{key} must be an object")
        default_entry = normalized.get(key, {"enabled": True, "name": None})
        normalized[key] = {
            "enabled": bool_setting(
                entry.get("enabled", default_entry["enabled"]),
                f"mqtt.entities.{key}.enabled",
            ),
            "name": optional_text(entry.get("name"), strip=True),
        }
    return normalized


def normalize_mqtt_entity_key(value: Any) -> str:
    key = str(value or "").strip()
    if key in MQTT_FIXED_ENTITY_KEYS:
        return key
    if key.startswith("profile:") and key[len("profile:") :].strip():
        return key
    if key.startswith("display_volume:") and key[len("display_volume:") :].strip():
        return key
    raise ConfigError(
        "mqtt.entities keys must be one of current_profile, profile_select, volume, audio_output, "
        "play_pause, mute_toggle, mute, unmute, muted, shutdown, online, power, "
        "profile:<name>, or display_volume:<display-key>"
    )
