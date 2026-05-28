"""Home Assistant MQTT discovery bridge for the tray app.

The implementation is split across focused submodules; this package module
re-exports the full public (and package-private) API:

* :mod:`xtray.ha_mqtt.snapshot` -- :class:`MqttSnapshot` and ``collect_snapshot``
* :mod:`xtray.ha_mqtt.topics` -- MQTT topic / object-id / slug builders
* :mod:`xtray.ha_mqtt.discovery` -- discovery payload builders and labels
* :mod:`xtray.ha_mqtt.bridge` -- the paho-mqtt bridge and command parsing
"""
# ruff: noqa: F401
from __future__ import annotations

from ..audio_utils import active_audio_sources as _active_audio_sources
from ..audio_utils import same_audio_source as _same_audio_source
from .bridge import (
    HOME_ASSISTANT_STATUS_TOPIC,
    HomeAssistantMqttBridge,
    MqttCommand,
    MqttConnectionResult,
    _connect_reason_text,
    _connect_result_text,
    _create_paho_client,
    _disconnect_reason_text,
    _payload_text,
    _wake_payload_mac,
    parse_mqtt_command,
    test_mqtt_connection,
)
from .discovery import (
    FIXED_ENTITY_KEYS,
    UNKNOWN,
    DiscoveryMessage,
    _audio_option_base_label,
    _audio_state_label,
    _binary_state,
    _common_payload,
    _current_profile_sensor_message,
    _device_identifier,
    _device_name,
    _device_payload,
    _display_volume_number_message,
    _entity_enabled,
    _entity_message,
    _entity_name,
    _entity_settings,
    _is_legacy_topic_or_client,
    _media_play_pause_button_message,
    _mute_button_message,
    _mute_toggle_button_message,
    _muted_binary_sensor_message,
    _online_binary_sensor_message,
    _power_switch_message,
    _profile_button_message,
    _profile_select_message,
    _shutdown_button_message,
    _unmute_button_message,
    _volume_number_message,
    _wake_payload,
    audio_option_map,
    build_discovery_cleanup_messages,
    build_discovery_messages,
)
from .snapshot import MqttSnapshot, _safe, collect_snapshot
from .topics import (
    DISPLAY_VOLUME_ENTITY_PREFIX,
    PROFILE_ENTITY_PREFIX,
    _base_topic,
    _discovery_topic,
    _entity_object_id,
    _short_hash,
    _slug,
    _slug_with_hash,
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

__all__ = [
    # snapshot
    "MqttSnapshot",
    "collect_snapshot",
    # topics
    "PROFILE_ENTITY_PREFIX",
    "DISPLAY_VOLUME_ENTITY_PREFIX",
    "mqtt_command_topics",
    "state_topics",
    "display_volume_command_topic",
    "display_volume_state_topic",
    "availability_topic",
    "profile_discovery_topic",
    "entity_discovery_topic",
    "profile_entity_key",
    "display_volume_entity_key",
    "display_volume_discovery_topic",
    # discovery
    "DiscoveryMessage",
    "UNKNOWN",
    "FIXED_ENTITY_KEYS",
    "build_discovery_messages",
    "build_discovery_cleanup_messages",
    "audio_option_map",
    # bridge
    "HOME_ASSISTANT_STATUS_TOPIC",
    "HomeAssistantMqttBridge",
    "MqttCommand",
    "MqttConnectionResult",
    "parse_mqtt_command",
    "test_mqtt_connection",
]
