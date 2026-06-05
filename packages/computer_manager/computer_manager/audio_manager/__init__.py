"""Windows audio device selection, volume, media keys.

Public API is exposed at package level — implementation lives in `core.py`.
"""
from ._endpoint_notifications import (
    EndpointChangeEvent,
    EndpointChangeKind,
    EndpointChangeListener,
)
from ._volume_notifications import (
    VolumeChangeEvent,
    VolumeChangeListener,
    read_current_volume,
)
from .core import (
    ENV_AUDIO_FALLBACK_COMMAND,
    AudioApplyError,
    AudioEndpointNotFound,
    AudioSource,
    get_default_audio_source,
    get_output_muted,
    get_output_volume_percent,
    list_audio_sources,
    set_default_audio_source,
    set_output_muted,
    set_output_volume_percent,
    toggle_media_play_pause,
)

__all__ = [
    "AudioApplyError",
    "AudioEndpointNotFound",
    "AudioSource",
    "ENV_AUDIO_FALLBACK_COMMAND",
    "EndpointChangeEvent",
    "EndpointChangeKind",
    "EndpointChangeListener",
    "VolumeChangeEvent",
    "VolumeChangeListener",
    "get_default_audio_source",
    "get_output_muted",
    "get_output_volume_percent",
    "list_audio_sources",
    "read_current_volume",
    "set_default_audio_source",
    "set_output_muted",
    "set_output_volume_percent",
    "toggle_media_play_pause",
]
