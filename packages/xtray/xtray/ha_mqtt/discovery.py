"""Building Home Assistant MQTT discovery payloads and audio/device labels."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import __version__
from ..audio_utils import active_audio_sources as _active_audio_sources
from ..audio_utils import same_audio_source as _same_audio_source
from ..services.display import audio, display, display_inventory
from .snapshot import MqttSnapshot
from .topics import (
    DISPLAY_VOLUME_ENTITY_PREFIX,
    PROFILE_ENTITY_PREFIX,
    _base_topic,
    _discovery_topic,
    _entity_object_id,
    _short_hash,
    _slug,
    availability_topic,
    display_volume_command_topic,
    display_volume_discovery_topic,
    display_volume_entity_key,
    display_volume_state_topic,
    entity_discovery_topic,
    mqtt_command_topics,
    profile_discovery_topic,
    profile_entity_key,
    state_topics,
)

DisplayState = display.DisplayState
UNKNOWN = "unknown"
FIXED_ENTITY_KEYS = (
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
)


@dataclass(frozen=True)
class DiscoveryMessage:
    topic: str
    payload: dict[str, Any] | str
    retain: bool = True


def build_discovery_messages(
    settings: dict[str, Any],
    snapshot: MqttSnapshot,
) -> list[DiscoveryMessage]:
    messages: list[DiscoveryMessage] = []
    for profile_name in snapshot.favorite_profiles:
        if _entity_enabled(settings, profile_entity_key(profile_name), default=True):
            messages.append(_profile_button_message(settings, profile_name))
    if _entity_enabled(settings, "current_profile", default=True):
        messages.append(_current_profile_sensor_message(settings))
    if _entity_enabled(settings, "profile_select", default=True):
        messages.append(_profile_select_message(settings, snapshot.favorite_profiles))
    if _entity_enabled(settings, "volume", default=True):
        messages.append(_volume_number_message(settings))
    for display_state in snapshot.hdmi_volume_displays:
        key = display_volume_entity_key(display_state)
        if _entity_enabled(settings, key, default=True):
            messages.append(_display_volume_number_message(settings, display_state))
    if _entity_enabled(settings, "audio_output", default=True):
        messages.append(_audio_select_message(settings, snapshot.audio_sources))
    if _entity_enabled(settings, "play_pause", default=True):
        messages.append(_media_play_pause_button_message(settings))
    if _entity_enabled(settings, "mute_toggle", default=True):
        messages.append(_mute_toggle_button_message(settings))
    if _entity_enabled(settings, "mute", default=True):
        messages.append(_mute_button_message(settings))
    if _entity_enabled(settings, "unmute", default=True):
        messages.append(_unmute_button_message(settings))
    if _entity_enabled(settings, "muted", default=True):
        messages.append(_muted_binary_sensor_message(settings))
    if _entity_enabled(settings, "shutdown", default=bool(settings.get("allow_shutdown"))):
        messages.append(_shutdown_button_message(settings))
    if _entity_enabled(settings, "online", default=True):
        messages.append(_online_binary_sensor_message(settings))
    if _entity_enabled(settings, "power", default=bool(settings.get("allow_shutdown"))):
        messages.append(_power_switch_message(settings, snapshot.local_mac))
    return messages


def build_discovery_cleanup_messages(
    settings: dict[str, Any],
    snapshot: MqttSnapshot,
) -> list[DiscoveryMessage]:
    messages: list[DiscoveryMessage] = []
    current_profiles = set(snapshot.favorite_profiles)
    for key in FIXED_ENTITY_KEYS:
        default_enabled = (
            bool(settings.get("allow_shutdown")) if key in {"shutdown", "power"} else True
        )
        if not _entity_enabled(settings, key, default=default_enabled):
            messages.append(DiscoveryMessage(entity_discovery_topic(settings, key), ""))
    profile_keys = {
        profile_entity_key(profile_name)
        for profile_name in current_profiles
    } | {
        key
        for key in _entity_settings(settings)
        if key.startswith(PROFILE_ENTITY_PREFIX)
    }
    for key in sorted(profile_keys):
        profile_name = key[len(PROFILE_ENTITY_PREFIX) :]
        if profile_name not in current_profiles or not _entity_enabled(settings, key, default=True):
            messages.append(DiscoveryMessage(profile_discovery_topic(settings, profile_name), ""))
    current_display_volume_keys = {
        display_volume_entity_key(display_state)
        for display_state in snapshot.hdmi_volume_displays
    }
    display_volume_keys = current_display_volume_keys | {
        key
        for key in _entity_settings(settings)
        if key.startswith(DISPLAY_VOLUME_ENTITY_PREFIX)
    }
    for key in sorted(display_volume_keys):
        display_key = key[len(DISPLAY_VOLUME_ENTITY_PREFIX) :]
        if key not in current_display_volume_keys or not _entity_enabled(
            settings,
            key,
            default=True,
        ):
            messages.append(
                DiscoveryMessage(display_volume_discovery_topic(settings, display_key), "")
            )
    return messages


def audio_option_map(sources: list[audio.AudioSource]) -> dict[str, audio.AudioSource]:
    active_sources = _active_audio_sources(sources)
    base_counts: dict[str, int] = {}
    for source in active_sources:
        base = _audio_option_base_label(source)
        base_counts[base] = base_counts.get(base, 0) + 1

    options: dict[str, audio.AudioSource] = {}
    fallback_counts: dict[str, int] = {}
    for index, source in enumerate(active_sources, start=1):
        base = _audio_option_base_label(source)
        if base_counts[base] == 1:
            label = base
        else:
            identity = source.endpoint_id or source.interface_name or source.name or str(index)
            label = f"{base} [{_short_hash(identity)}]"
        if label in options:
            fallback_counts[label] = fallback_counts.get(label, 1) + 1
            label = f"{label} {fallback_counts[label]}"
        options[label] = source
    return options


def _entity_message(
    settings: dict[str, Any],
    *,
    component: str,
    key: str,
    suffix: str,
    default_name: str,
    extra: dict[str, Any],
    include_availability: bool = True,
) -> DiscoveryMessage:
    """Assemble a discovery message for an entity addressed by a fixed object id.

    Centralises the object-id / common-payload / discovery-topic boilerplate
    shared by every fixed entity; callers only supply the entity-specific
    ``extra`` payload fields.
    """
    object_id = _entity_object_id(settings, suffix)
    payload = _common_payload(
        settings,
        _entity_name(settings, key, default_name),
        object_id,
        include_availability=include_availability,
    )
    payload.update(extra)
    return DiscoveryMessage(_discovery_topic(settings, component, object_id), payload)


def _profile_button_message(settings: dict[str, Any], profile_name: str) -> DiscoveryMessage:
    object_id = _entity_object_id(settings, f"profile_{profile_name}")
    key = profile_entity_key(profile_name)
    payload = _common_payload(
        settings,
        _entity_name(settings, key, f"Apply {profile_name}"),
        object_id,
    )
    payload.update(
        {
            "command_topic": mqtt_command_topics(settings)["profile"],
            "payload_press": profile_name,
            "icon": "mdi:monitor-dashboard",
        }
    )
    return DiscoveryMessage(profile_discovery_topic(settings, profile_name), payload)


def _current_profile_sensor_message(settings: dict[str, Any]) -> DiscoveryMessage:
    return _entity_message(
        settings,
        component="sensor",
        key="current_profile",
        suffix="current_profile",
        default_name="Current profile",
        extra={
            "state_topic": state_topics(settings)["current_profile"],
            "icon": "mdi:monitor-shimmer",
        },
    )


def _profile_select_message(
    settings: dict[str, Any],
    profile_names: list[str],
) -> DiscoveryMessage:
    return _entity_message(
        settings,
        component="select",
        key="profile_select",
        suffix="profile_select",
        default_name="Profile",
        extra={
            "state_topic": state_topics(settings)["current_profile"],
            "command_topic": mqtt_command_topics(settings)["profile"],
            "options": list(profile_names) or ["Unavailable"],
            "icon": "mdi:monitor-dashboard",
        },
    )


def _volume_number_message(settings: dict[str, Any]) -> DiscoveryMessage:
    return _entity_message(
        settings,
        component="number",
        key="volume",
        suffix="volume",
        default_name="Volume",
        extra={
            "state_topic": state_topics(settings)["volume"],
            "command_topic": mqtt_command_topics(settings)["volume"],
            "min": 0,
            "max": 100,
            "step": 1,
            "mode": "slider",
            "unit_of_measurement": "%",
            "payload_reset": UNKNOWN,
            "icon": "mdi:volume-high",
        },
    )


def _display_volume_number_message(
    settings: dict[str, Any],
    display_state: DisplayState,
) -> DiscoveryMessage:
    display_key = display_inventory.display_volume_entity_key(display_state)
    entity_key = display_volume_entity_key(display_state)
    title = display_inventory.display_title(display_state)
    object_id = _entity_object_id(settings, f"display_volume_{display_key}")
    payload = _common_payload(
        settings,
        _entity_name(settings, entity_key, f"{title} HDMI volume"),
        object_id,
    )
    payload.update(
        {
            "state_topic": display_volume_state_topic(settings, display_key),
            "command_topic": display_volume_command_topic(settings, display_key),
            "min": 0,
            "max": 100,
            "step": 1,
            "mode": "slider",
            "unit_of_measurement": "%",
            "payload_reset": UNKNOWN,
            "icon": "mdi:television-speaker",
        }
    )
    return DiscoveryMessage(display_volume_discovery_topic(settings, display_key), payload)


def _audio_select_message(
    settings: dict[str, Any], sources: list[audio.AudioSource]
) -> DiscoveryMessage:
    options = list(audio_option_map(sources)) or ["Unavailable"]
    return _entity_message(
        settings,
        component="select",
        key="audio_output",
        suffix="audio_output",
        default_name="Audio output",
        extra={
            "state_topic": state_topics(settings)["audio_output"],
            "command_topic": mqtt_command_topics(settings)["audio_output"],
            "options": options,
            "icon": "mdi:speaker",
        },
    )


def _media_play_pause_button_message(settings: dict[str, Any]) -> DiscoveryMessage:
    return _entity_message(
        settings,
        component="button",
        key="play_pause",
        suffix="play_pause",
        default_name="Play/Pause media",
        extra={
            "command_topic": mqtt_command_topics(settings)["media"],
            "payload_press": "play_pause",
            "icon": "mdi:play-pause",
        },
    )


def _mute_toggle_button_message(settings: dict[str, Any]) -> DiscoveryMessage:
    return _entity_message(
        settings,
        component="button",
        key="mute_toggle",
        suffix="mute_toggle",
        default_name="Mute/Unmute",
        extra={
            "command_topic": mqtt_command_topics(settings)["mute"],
            "payload_press": "toggle",
            "icon": "mdi:volume-mute",
        },
    )


def _mute_button_message(settings: dict[str, Any]) -> DiscoveryMessage:
    return _entity_message(
        settings,
        component="button",
        key="mute",
        suffix="mute",
        default_name="Mute",
        extra={
            "command_topic": mqtt_command_topics(settings)["mute"],
            "payload_press": "mute",
            "icon": "mdi:volume-off",
        },
    )


def _unmute_button_message(settings: dict[str, Any]) -> DiscoveryMessage:
    return _entity_message(
        settings,
        component="button",
        key="unmute",
        suffix="unmute",
        default_name="Unmute",
        extra={
            "command_topic": mqtt_command_topics(settings)["mute"],
            "payload_press": "unmute",
            "icon": "mdi:volume-high",
        },
    )


def _muted_binary_sensor_message(settings: dict[str, Any]) -> DiscoveryMessage:
    return _entity_message(
        settings,
        component="binary_sensor",
        key="muted",
        suffix="muted",
        default_name="Muted",
        extra={
            "state_topic": state_topics(settings)["muted"],
            "payload_on": "ON",
            "payload_off": "OFF",
            "icon": "mdi:volume-mute",
        },
    )


def _shutdown_button_message(settings: dict[str, Any]) -> DiscoveryMessage:
    return _entity_message(
        settings,
        component="button",
        key="shutdown",
        suffix="shutdown",
        default_name="Shutdown",
        extra={
            "command_topic": mqtt_command_topics(settings)["shutdown"],
            "payload_press": "shutdown",
            "entity_category": "config",
            "icon": "mdi:power",
        },
    )


def _power_switch_message(settings: dict[str, Any], mac: str | None) -> DiscoveryMessage:
    return _entity_message(
        settings,
        component="switch",
        key="power",
        suffix="power",
        default_name="Power",
        include_availability=False,
        extra={
            "state_topic": availability_topic(settings),
            "command_topic": mqtt_command_topics(settings)["power"],
            "payload_on": _wake_payload(mac),
            "payload_off": "shutdown",
            "state_on": "online",
            "state_off": "offline",
            "json_attributes_topic": state_topics(settings)["power_attributes"],
            "icon": "mdi:power",
        },
    )


def _online_binary_sensor_message(settings: dict[str, Any]) -> DiscoveryMessage:
    return _entity_message(
        settings,
        component="binary_sensor",
        key="online",
        suffix="online",
        default_name="Online",
        extra={
            "state_topic": state_topics(settings)["online"],
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "connectivity",
        },
    )


def _common_payload(
    settings: dict[str, Any],
    name: str,
    unique_id: str,
    *,
    include_availability: bool = True,
) -> dict[str, Any]:
    payload = {
        "name": name,
        "unique_id": unique_id,
        "device": _device_payload(settings),
    }
    if include_availability:
        payload.update(
            {
                "availability_topic": availability_topic(settings),
                "payload_available": "online",
                "payload_not_available": "offline",
            }
        )
    return payload


def _device_payload(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "identifiers": [_device_identifier(settings)],
        "name": _device_name(settings),
        "manufacturer": "XTray",
        "model": "Windows tray",
        "sw_version": __version__,
    }


def _device_identifier(settings: dict[str, Any]) -> str:
    seed = str(settings.get("client_id") or _base_topic(settings))
    prefix = "displaymanager" if _is_legacy_topic_or_client(settings) else "xtray"
    return f"{prefix}_{_slug(seed)}"


def _device_name(settings: dict[str, Any]) -> str:
    configured = settings.get("device_name")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    client_id = str(settings.get("client_id") or "xtray")
    suffix = client_id
    if suffix.startswith("xtray-"):
        suffix = suffix[len("xtray-") :]
    if suffix.startswith("displaymanager-"):
        suffix = suffix[len("displaymanager-") :]
    return f"XTray {suffix}"


def _is_legacy_topic_or_client(settings: dict[str, Any]) -> bool:
    client_id = str(settings.get("client_id") or "")
    base_topic = str(settings.get("base_topic") or "")
    return client_id.startswith("displaymanager-") or base_topic.startswith("displaymanager/")


def _entity_settings(settings: dict[str, Any]) -> dict[str, Any]:
    entities = settings.get("entities")
    return entities if isinstance(entities, dict) else {}


def _entity_enabled(settings: dict[str, Any], key: str, *, default: bool) -> bool:
    entry = _entity_settings(settings).get(key)
    if not isinstance(entry, dict) or "enabled" not in entry:
        return default
    return bool(entry.get("enabled"))


def _entity_name(settings: dict[str, Any], key: str, default: str) -> str:
    entry = _entity_settings(settings).get(key)
    if isinstance(entry, dict):
        value = entry.get("name")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _audio_state_label(
    default_source: audio.AudioSource | None,
    option_map: dict[str, audio.AudioSource],
) -> str | None:
    if default_source is None:
        return None
    for label, source in option_map.items():
        if _same_audio_source(source, default_source):
            return label
    return _audio_option_base_label(default_source)


def _audio_option_base_label(source: audio.AudioSource) -> str:
    return source.name.strip() or source.label()


def _binary_state(value: bool | None) -> str:
    if value is None:
        return UNKNOWN
    return "ON" if value else "OFF"


def _wake_payload(mac: str | None) -> str:
    return f"wake:{mac}" if mac else "wake"
