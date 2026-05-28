"""Windows audio endpoint capture and control: public API.

Implementation is split across focused private modules:

* :mod:`._com_runtime` -- ctypes structures, GUID constants, COM session
  primitives (`_com_method`, `_com_session`, `_check_hr`).
* :mod:`._mmdevice` -- IMMDevice/IMMDeviceEnumerator/IPolicyConfig wrappers
  and property-store readers.
* :mod:`._endpoint_volume` -- IAudioEndpointVolume volume/mute helpers and
  the global media-key sender.
* :mod:`._coreaudio` -- Core Audio enumerate/set-default/volume operations.
* :mod:`._registry_fallback` -- registry-based device enumeration and the
  configurable subprocess fallback used when IPolicyConfig is refused.
"""
from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from typing import Any

from xtray.core import app_logging

from ._com_runtime import _E_MULTIMEDIA, _VK_MEDIA_PLAY_PAUSE
from ._coreaudio import (
    _get_default_audio_source_coreaudio,
    _get_output_muted_coreaudio,
    _get_output_volume_percent_coreaudio,
    _list_audio_sources_coreaudio,
    _resolve_endpoint_id,
    _set_default_audio_source_policy_config,
    _set_output_muted_coreaudio,
    _set_output_volume_percent_coreaudio,
)
from ._endpoint_volume import _send_media_key
from ._registry_fallback import (
    ENV_AUDIO_FALLBACK_COMMAND,
    _get_default_audio_source_registry,
    _list_audio_sources_registry,
    _try_set_default_audio_source_fallback,
)


class AudioEndpointNotFound(Exception):
    """Raised when an ``AudioSource`` cannot be matched to any live endpoint."""


class AudioApplyError(Exception):
    """Raised when Windows refuses to switch the default audio endpoint."""


@dataclass(frozen=True)
class AudioSource:
    """Default Windows playback endpoint captured alongside a display profile."""

    name: str
    endpoint_id: str | None = None
    interface_name: str | None = None
    role: str = "multimedia"
    state: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AudioSource:
        if not isinstance(data, dict):
            raise ValueError("audio_source must be an object")
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("audio_source.name is required")
        return cls(
            name=name.strip(),
            endpoint_id=_optional_str(data.get("endpoint_id")),
            interface_name=_optional_str(data.get("interface_name")),
            role=_optional_str(data.get("role")) or "multimedia",
            state=_optional_str(data.get("state")),
        )

    def label(self) -> str:
        if self.interface_name and self.interface_name != self.name:
            if self.interface_name.lower().startswith(self.name.lower()):
                return self.interface_name
            return f"{self.name} ({self.interface_name})"
        return self.name


def get_default_audio_source() -> AudioSource | None:
    """Return the current default playback endpoint, or None when unavailable."""
    if sys.platform != "win32":
        return None
    try:
        return _get_default_audio_source_coreaudio()
    except Exception as exc:
        app_logging.get_logger("audio").warning(
            "Core Audio endpoint capture failed: %s", exc, exc_info=True
        )
        return _get_default_audio_source_registry()


def list_audio_sources() -> list[AudioSource]:
    """Return known playback endpoints without mutating Windows audio settings."""
    if sys.platform != "win32":
        return []
    try:
        return _list_audio_sources_coreaudio()
    except Exception as exc:
        app_logging.get_logger("audio").warning(
            "Core Audio endpoint inventory failed: %s", exc, exc_info=True
        )
        return _list_audio_sources_registry()


def set_default_audio_source(source: AudioSource) -> None:
    """Set the default Windows playback endpoint for the multimedia role."""
    if sys.platform != "win32":
        raise RuntimeError("computer_manager.audio requires Windows")
    endpoint_id = _resolve_endpoint_id(source)
    if not endpoint_id:
        raise AudioEndpointNotFound(source.label())
    try:
        _set_default_audio_source_policy_config(endpoint_id, _E_MULTIMEDIA)
    except Exception as exc:
        if _try_set_default_audio_source_fallback(source, endpoint_id, exc):
            return
        raise AudioApplyError(
            f"failed to set default audio source {source.label()}: {exc}"
        ) from exc


def get_output_volume_percent(source: AudioSource | None = None) -> int | None:
    """Return the endpoint master volume as 0-100, or None when unavailable."""
    if sys.platform != "win32":
        return None
    try:
        return _get_output_volume_percent_coreaudio(source)
    except AudioEndpointNotFound:
        raise
    except Exception as exc:
        app_logging.get_logger("audio").warning(
            "Core Audio volume read failed: %s", exc, exc_info=True
        )
        return None


def set_output_volume_percent(percent: int, source: AudioSource | None = None) -> None:
    """Set the endpoint master volume to a 0-100 percentage."""
    if not 0 <= percent <= 100:
        raise ValueError("volume percent must be between 0 and 100")
    if sys.platform != "win32":
        raise RuntimeError("computer_manager.audio requires Windows")
    try:
        _set_output_volume_percent_coreaudio(percent, source)
    except AudioEndpointNotFound:
        raise
    except Exception as exc:
        label = source.label() if source is not None else "default output"
        raise AudioApplyError(f"failed to set volume for {label}: {exc}") from exc


def get_output_muted(source: AudioSource | None = None) -> bool | None:
    """Return endpoint mute state, or None when unavailable."""
    if sys.platform != "win32":
        return None
    try:
        return _get_output_muted_coreaudio(source)
    except AudioEndpointNotFound:
        raise
    except Exception as exc:
        app_logging.get_logger("audio").warning(
            "Core Audio mute read failed: %s", exc, exc_info=True
        )
        return None


def set_output_muted(muted: bool, source: AudioSource | None = None) -> None:
    """Set endpoint mute state."""
    if sys.platform != "win32":
        raise RuntimeError("computer_manager.audio requires Windows")
    try:
        _set_output_muted_coreaudio(bool(muted), source)
    except AudioEndpointNotFound:
        raise
    except Exception as exc:
        label = source.label() if source is not None else "default output"
        raise AudioApplyError(f"failed to set mute for {label}: {exc}") from exc


def toggle_media_play_pause() -> None:
    """Send the Windows global media play/pause key."""
    if sys.platform != "win32":
        raise RuntimeError("computer_manager.audio requires Windows")
    _send_media_key(_VK_MEDIA_PLAY_PAUSE)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


__all__ = [
    "ENV_AUDIO_FALLBACK_COMMAND",
    "AudioApplyError",
    "AudioEndpointNotFound",
    "AudioSource",
    "get_default_audio_source",
    "get_output_muted",
    "get_output_volume_percent",
    "list_audio_sources",
    "set_default_audio_source",
    "set_output_muted",
    "set_output_volume_percent",
    "toggle_media_play_pause",
]
