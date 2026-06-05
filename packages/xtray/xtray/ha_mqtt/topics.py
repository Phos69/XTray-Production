"""MQTT topic, object-id, and slug builders for the Home Assistant bridge."""
from __future__ import annotations

import re
from hashlib import sha1
from typing import Any

from .. import config
from ..services.display import display, display_inventory

DisplayState = display.DisplayState

PROFILE_ENTITY_PREFIX = "profile:"
DISPLAY_VOLUME_ENTITY_PREFIX = "display_volume:"


def mqtt_command_topics(settings: dict[str, Any]) -> dict[str, str]:
    base = _base_topic(settings)
    return {
        "profile": f"{base}/cmd/profile",
        "volume": f"{base}/cmd/volume",
        "audio_output": f"{base}/cmd/audio_output",
        "media": f"{base}/cmd/media",
        "mute": f"{base}/cmd/mute",
        "shutdown": f"{base}/cmd/shutdown",
        "power": f"{base}/cmd/power",
    }


def state_topics(settings: dict[str, Any]) -> dict[str, str]:
    base = _base_topic(settings)
    return {
        "current_profile": f"{base}/state/current_profile",
        "volume": f"{base}/state/volume",
        "audio_output": f"{base}/state/audio_output",
        "muted": f"{base}/state/muted",
        "online": f"{base}/state/online",
        "power_attributes": f"{base}/state/power_attributes",
    }


def display_volume_command_topic(settings: dict[str, Any], display_key: str) -> str:
    return f"{_base_topic(settings)}/cmd/display_volume/{_short_hash(display_key)}"


def display_volume_state_topic(settings: dict[str, Any], display_key: str) -> str:
    return f"{_base_topic(settings)}/state/display_volume/{_short_hash(display_key)}"


def availability_topic(settings: dict[str, Any]) -> str:
    return f"{_base_topic(settings)}/availability"


def profile_discovery_topic(settings: dict[str, Any], profile_name: str) -> str:
    object_id = _entity_object_id(settings, f"profile_{profile_name}")
    return _discovery_topic(settings, "button", object_id)


def entity_discovery_topic(settings: dict[str, Any], entity_key: str) -> str:
    topics = {
        "current_profile": ("sensor", "current_profile"),
        "profile_select": ("select", "profile_select"),
        "volume": ("number", "volume"),
        "audio_output": ("select", "audio_output"),
        "play_pause": ("button", "play_pause"),
        "mute_toggle": ("button", "mute_toggle"),
        "mute": ("button", "mute"),
        "unmute": ("button", "unmute"),
        "muted": ("binary_sensor", "muted"),
        "shutdown": ("button", "shutdown"),
        "online": ("binary_sensor", "online"),
        "power": ("switch", "power"),
    }
    if entity_key.startswith(PROFILE_ENTITY_PREFIX):
        return profile_discovery_topic(settings, entity_key[len(PROFILE_ENTITY_PREFIX) :])
    if entity_key.startswith(DISPLAY_VOLUME_ENTITY_PREFIX):
        return display_volume_discovery_topic(
            settings,
            entity_key[len(DISPLAY_VOLUME_ENTITY_PREFIX) :],
        )
    component, suffix = topics[entity_key]
    return _discovery_topic(settings, component, _entity_object_id(settings, suffix))


def profile_entity_key(profile_name: str) -> str:
    return f"{PROFILE_ENTITY_PREFIX}{profile_name}"


def display_volume_entity_key(display_state: DisplayState) -> str:
    return f"{DISPLAY_VOLUME_ENTITY_PREFIX}{display_inventory.display_volume_entity_key(display_state)}"


def display_volume_discovery_topic(settings: dict[str, Any], display_key: str) -> str:
    object_id = _entity_object_id(settings, f"display_volume_{display_key}")
    return _discovery_topic(settings, "number", object_id)


def _entity_object_id(settings: dict[str, Any], suffix: str) -> str:
    device = _slug(str(settings.get("client_id") or _base_topic(settings)))
    return f"{device}_{_slug_with_hash(suffix)}"


def _discovery_topic(settings: dict[str, Any], component: str, object_id: str) -> str:
    prefix = str(settings.get("discovery_prefix") or "homeassistant").strip().strip("/")
    return f"{prefix}/{component}/{object_id}/config"


def _base_topic(settings: dict[str, Any]) -> str:
    default_base = config.default_mqtt_settings()["base_topic"]
    return str(settings.get("base_topic") or default_base).strip("/")


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_").lower()
    return slug or "xtray"


def _slug_with_hash(value: str) -> str:
    return f"{_slug(value)}_{_short_hash(value)}"


def _short_hash(value: str) -> str:
    return sha1(value.encode("utf-8")).hexdigest()[:8]
