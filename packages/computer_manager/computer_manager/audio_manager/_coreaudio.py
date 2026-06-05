"""Core Audio queries: enumerate endpoints, set default, read/write volume."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from ._com_runtime import (
    _DEVICE_STATE_ACTIVE,
    _E_MULTIMEDIA,
    _E_RENDER,
    _check_hr,
    _com_method,
    _com_session,
    _release,
)
from ._endpoint_volume import (
    _get_master_volume_scalar,
    _get_mute,
    _set_master_volume_scalar,
    _set_mute,
    _with_audio_endpoint_volume,
)
from ._mmdevice import (
    _audio_source_from_device,
    _create_mm_device_enumerator,
    _create_policy_config,
)


def _get_default_audio_source_coreaudio():
    from .core import AudioSource  # noqa: F401 -- re-export hint

    with _com_session():
        enumerator = _create_mm_device_enumerator()
        try:
            get_default = _com_method(
                enumerator,
                4,
                ctypes.c_long,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_void_p),
            )
            device = ctypes.c_void_p()
            _check_hr(
                get_default(enumerator, _E_RENDER, _E_MULTIMEDIA, ctypes.byref(device)),
                "GetDefaultAudioEndpoint failed",
            )
            if not device.value:
                return None
            try:
                return _audio_source_from_device(device, role="multimedia")
            finally:
                _release(device)
        finally:
            _release(enumerator)


def _list_audio_sources_coreaudio():
    with _com_session():
        enumerator = _create_mm_device_enumerator()
        try:
            enum_endpoints = _com_method(
                enumerator,
                3,
                ctypes.c_long,
                ctypes.c_int,
                wintypes.DWORD,
                ctypes.POINTER(ctypes.c_void_p),
            )
            collection = ctypes.c_void_p()
            _check_hr(
                enum_endpoints(
                    enumerator,
                    _E_RENDER,
                    _DEVICE_STATE_ACTIVE,
                    ctypes.byref(collection),
                ),
                "EnumAudioEndpoints failed",
            )
            if not collection.value:
                return []
            try:
                get_count = _com_method(
                    collection,
                    3,
                    ctypes.c_long,
                    ctypes.POINTER(wintypes.UINT),
                )
                item = _com_method(
                    collection,
                    4,
                    ctypes.c_long,
                    wintypes.UINT,
                    ctypes.POINTER(ctypes.c_void_p),
                )
                count = wintypes.UINT()
                _check_hr(
                    get_count(collection, ctypes.byref(count)),
                    "IMMDeviceCollection.GetCount failed",
                )
                raw: list = []
                for index in range(count.value):
                    device = ctypes.c_void_p()
                    _check_hr(
                        item(collection, index, ctypes.byref(device)),
                        "IMMDeviceCollection.Item failed",
                    )
                    if not device.value:
                        continue
                    try:
                        source = _audio_source_from_device(device, role="multimedia")
                    finally:
                        _release(device)
                    if source is not None:
                        raw.append(source)
                return _dedupe_audio_sources(raw)
            finally:
                _release(collection)
        finally:
            _release(enumerator)


def _dedupe_audio_sources(sources: list) -> list:
    seen: set[tuple] = set()
    deduped: list = []
    for source in sources:
        key = (source.endpoint_id, source.label())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def _resolve_endpoint_id(source) -> str | None:
    from .core import list_audio_sources

    if source.endpoint_id:
        return source.endpoint_id
    source_label = source.label()
    for candidate in list_audio_sources():
        if candidate.endpoint_id and candidate.label() == source_label:
            return candidate.endpoint_id
    return None


def _set_default_audio_source_policy_config(endpoint_id: str, role: int) -> None:
    with _com_session():
        policy_config = _create_policy_config()
        try:
            set_default_endpoint = _com_method(
                policy_config,
                13,
                ctypes.c_long,
                wintypes.LPCWSTR,
                ctypes.c_int,
            )
            _check_hr(
                set_default_endpoint(policy_config, endpoint_id, role),
                "IPolicyConfig.SetDefaultEndpoint failed",
            )
        finally:
            _release(policy_config)


def _get_output_volume_percent_coreaudio(source=None) -> int:
    scalar = _with_audio_endpoint_volume(
        source,
        lambda endpoint_volume: _get_master_volume_scalar(endpoint_volume),
    )
    return int(round(scalar * 100))


def _set_output_volume_percent_coreaudio(
    percent: int,
    source=None,
) -> None:
    scalar = percent / 100
    _with_audio_endpoint_volume(
        source,
        lambda endpoint_volume: _set_master_volume_scalar(endpoint_volume, scalar),
    )


def _get_output_muted_coreaudio(source=None) -> bool:
    return bool(
        _with_audio_endpoint_volume(
            source,
            lambda endpoint_volume: _get_mute(endpoint_volume),
        )
    )


def _set_output_muted_coreaudio(
    muted: bool,
    source=None,
) -> None:
    _with_audio_endpoint_volume(
        source,
        lambda endpoint_volume: _set_mute(endpoint_volume, muted),
    )
