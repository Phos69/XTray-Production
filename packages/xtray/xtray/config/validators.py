"""Reusable configuration validators and normalizers."""
from __future__ import annotations

import json
import re
import socket
from typing import Any

from ..core.config_base import (
    DISPLAY_DEFAULT_ORIENTATIONS,
    THEME_NAMES,
    VOLUME_CONTROL_MODES,
    VOLUME_CONTROL_NONE,
)
from ..core.theme import normalize_theme_name as _normalize_theme_name
from ..ha_ids import HA_SERVICE_RE

MQTT_TOPIC_RE = re.compile(r"^[^+#\0]+$")
HA_SERVICE_ALIASES = {
    "wake_on_lan.send_magic_packed": "wake_on_lan.send_magic_packet",
}


class ConfigError(Exception):
    """Raised when local XTray configuration is invalid."""


def truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def bool_setting(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    raise ConfigError(f"{name} must be a boolean")


def optional_text(value: Any, *, strip: bool = True) -> str | None:
    if value is None:
        return None
    text = str(value)
    if strip:
        text = text.strip()
    return text if text else None


def topic_setting(value: Any, name: str) -> str:
    text = str(value).strip().strip("/")
    if not text:
        raise ConfigError(f"{name} cannot be empty")
    if not MQTT_TOPIC_RE.match(text):
        raise ConfigError(f"{name} must not contain MQTT wildcards")
    return text


def normalize_positive_int(value: Any, *, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ConfigError(f"{name} must be a positive integer")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            value = int(text)
        except ValueError as exc:
            raise ConfigError(f"{name} must be a positive integer") from exc
    if isinstance(value, float):
        if not value.is_integer():
            raise ConfigError(f"{name} must be a positive integer")
        value = int(value)
    if not isinstance(value, int):
        raise ConfigError(f"{name} must be a positive integer")
    if value <= 0:
        raise ConfigError(f"{name} must be a positive integer")
    return value


def normalize_orientation(value: Any, *, name: str = "default_orientation") -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ConfigError(f"{name} must be one of: 0, 90, 180, 270")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            value = int(text)
        except ValueError as exc:
            raise ConfigError(f"{name} must be one of: 0, 90, 180, 270") from exc
    if isinstance(value, float):
        if not value.is_integer():
            raise ConfigError(f"{name} must be one of: 0, 90, 180, 270")
        value = int(value)
    if value not in DISPLAY_DEFAULT_ORIENTATIONS:
        raise ConfigError(f"{name} must be one of: 0, 90, 180, 270")
    return int(value)


def normalize_theme_name(value: Any) -> str:
    try:
        return _normalize_theme_name(str(value or ""))
    except ValueError as exc:
        raise ConfigError(f"theme must be one of: {', '.join(sorted(THEME_NAMES))}") from exc


def normalize_ha_url(value: Any) -> str | None:
    text = optional_text(value, strip=True)
    if not text:
        return None
    if not text.lower().startswith(("http://", "https://")):
        raise ConfigError("mqtt.home_assistant_url must start with http:// or https://")
    return text.rstrip("/")


def normalize_volume_control(value: Any, *, name: str = "volume_control") -> str:
    if value is None:
        return VOLUME_CONTROL_NONE
    text = str(value).strip().casefold()
    if text in VOLUME_CONTROL_MODES:
        return text
    raise ConfigError(
        f"{name} must be one of: {', '.join(sorted(VOLUME_CONTROL_MODES))}"
    )


def normalize_ha_entity(value: Any) -> str | None:
    text = optional_text(value, strip=True)
    return text if text else None


def normalize_ha_service(value: Any, *, name: str) -> str | None:
    text = optional_text(value, strip=True)
    if not text:
        return None
    normalized = text.casefold()
    normalized = HA_SERVICE_ALIASES.get(normalized, normalized)
    if not HA_SERVICE_RE.match(normalized):
        raise ConfigError(f"{name} must look like domain.service")
    return normalized


def normalize_ha_service_data(value: Any, *, name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{name} must be a JSON object") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"{name} must be a JSON object")
    try:
        normalized = json.loads(json.dumps(value))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be JSON-serializable") from exc
    if not isinstance(normalized, dict):
        raise ConfigError(f"{name} must be a JSON object")
    return normalized


def hostname_slug() -> str:
    value = socket.gethostname().strip() or "windows"
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-_").lower()
    return slug or "windows"
