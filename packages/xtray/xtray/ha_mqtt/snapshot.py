"""Collecting the live system snapshot published to Home Assistant over MQTT."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from .. import config
from ..audio_utils import active_audio_sources as _active_audio_sources
from ..core import app_logging
from ..services.display import audio, display, display_inventory, profiles
from ..services.network import devices as network

_T = TypeVar("_T")
DisplayState = display.DisplayState


@dataclass(frozen=True)
class MqttSnapshot:
    favorite_profiles: list[str]
    audio_sources: list[audio.AudioSource]
    default_audio_source: audio.AudioSource | None = None
    volume_percent: int | None = None
    muted: bool | None = None
    current_profile: str | None = None
    local_mac: str | None = None
    hdmi_volume_displays: list[DisplayState] = field(default_factory=list)
    hdmi_volume_percents: dict[str, int | None] = field(default_factory=dict)


def _safe(logger: Any, label: str, fn: Callable[[], _T], default: _T) -> _T:
    """Run a snapshot-field collector, logging and falling back on failure."""
    try:
        return fn()
    except Exception:
        logger.exception("failed to collect %s for MQTT", label)
        return default


def collect_snapshot() -> MqttSnapshot:
    logger = app_logging.get_logger("ha_mqtt")
    favorite_profiles = _safe(
        logger, "favorite profiles", profiles.list_favorite_profiles, []
    )
    audio_sources = _safe(
        logger,
        "audio outputs",
        lambda: _active_audio_sources(audio.list_audio_sources()),
        [],
    )
    default_audio_source = _safe(
        logger, "default audio output", audio.get_default_audio_source, None
    )

    volume_percent: int | None = None
    muted: bool | None = None
    if default_audio_source is not None:
        volume_percent = _safe(
            logger,
            "output volume",
            lambda: audio.get_output_volume_percent(default_audio_source),
            None,
        )
        muted = _safe(
            logger,
            "output mute state",
            lambda: audio.get_output_muted(default_audio_source),
            None,
        )

    current_profile = _detect_current_profile(logger, favorite_profiles)

    local_mac = _safe(logger, "local adapter MAC", network.local_adapter_mac, None)

    active_item = _safe(
        logger,
        "active volume display",
        lambda: display_inventory.active_volume_display(source=default_audio_source),
        None,
    )
    hdmi_volume_displays: list[DisplayState] = []
    hdmi_volume_percents: dict[str, int | None] = {}
    if active_item is not None and active_item.volume_control == config.VOLUME_CONTROL_HDMI:
        display_state = active_item.display
        hdmi_volume_displays = [display_state]
        key = display_inventory.display_volume_entity_key(display_state)
        hdmi_volume_percents[key] = _safe(
            logger,
            f"HDMI volume for display {display_state.device_id}",
            lambda: display.get_monitor_audio_volume_percent(display_state),
            None,
        )

    return MqttSnapshot(
        favorite_profiles=favorite_profiles,
        audio_sources=audio_sources,
        default_audio_source=default_audio_source,
        volume_percent=volume_percent,
        muted=muted,
        current_profile=current_profile,
        local_mac=local_mac,
        hdmi_volume_displays=hdmi_volume_displays,
        hdmi_volume_percents=hdmi_volume_percents,
    )


def _detect_current_profile(logger: Any, favorite_profiles: list[str]) -> str | None:
    if not favorite_profiles:
        return None
    try:
        matched = profiles.detect_current_profile(
            profile_names=favorite_profiles,
            match_audio=False,
            include_inactive=True,
        )
    except Exception:
        logger.exception("failed to detect current display profile for MQTT")
        return _last_applied_favorite_profile(favorite_profiles)
    return matched.name if matched is not None else None


def _last_applied_favorite_profile(favorite_profiles: list[str]) -> str | None:
    try:
        last_applied = config.get_last_applied_profile()
    except config.ConfigError:
        return None
    if last_applied in set(favorite_profiles):
        return last_applied
    return None
