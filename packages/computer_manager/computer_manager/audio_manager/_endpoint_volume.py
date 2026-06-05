"""IAudioEndpointVolume + IMMDevice volume/mute operations and media keys."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any

from ._com_runtime import (
    _CLSCTX_ALL,
    _E_MULTIMEDIA,
    _E_RENDER,
    _GUID,
    _IID_IAUDIO_ENDPOINT_VOLUME,
    _KEYEVENTF_KEYUP,
    _check_hr,
    _com_method,
    _com_session,
    _guid,
    _release,
)
from ._mmdevice import _create_mm_device_enumerator


class _ResolveError(Exception):
    """Raised when the endpoint id of an AudioSource cannot be found."""


def _with_audio_endpoint_volume(source, callback: Any) -> Any:
    with _com_session():
        enumerator = _create_mm_device_enumerator()
        try:
            device = _audio_device_for_source(enumerator, source)
            try:
                endpoint_volume = _activate_audio_endpoint_volume(device)
                try:
                    return callback(endpoint_volume)
                finally:
                    _release(endpoint_volume)
            finally:
                _release(device)
        finally:
            _release(enumerator)


def _audio_device_for_source(
    enumerator: ctypes.c_void_p,
    source,
) -> ctypes.c_void_p:
    # Imported lazily to avoid a cycle: core imports this module's API.
    from ._coreaudio import _resolve_endpoint_id
    from .core import AudioEndpointNotFound

    device = ctypes.c_void_p()
    if source is None:
        get_default = _com_method(
            enumerator,
            4,
            ctypes.c_long,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
        )
        _check_hr(
            get_default(enumerator, _E_RENDER, _E_MULTIMEDIA, ctypes.byref(device)),
            "GetDefaultAudioEndpoint failed",
        )
    else:
        endpoint_id = _resolve_endpoint_id(source)
        if not endpoint_id:
            raise AudioEndpointNotFound(source.label())
        get_device = _com_method(
            enumerator,
            5,
            ctypes.c_long,
            wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_void_p),
        )
        _check_hr(
            get_device(enumerator, endpoint_id, ctypes.byref(device)),
            "IMMDeviceEnumerator.GetDevice failed",
        )
    if not device.value:
        label = source.label() if source is not None else "default output"
        raise AudioEndpointNotFound(label)
    return device


def _activate_audio_endpoint_volume(device: ctypes.c_void_p) -> ctypes.c_void_p:
    from .core import AudioApplyError

    activate = _com_method(
        device,
        3,
        ctypes.c_long,
        ctypes.POINTER(_GUID),
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    )
    endpoint_volume = ctypes.c_void_p()
    endpoint_volume_iid = _guid(_IID_IAUDIO_ENDPOINT_VOLUME)
    _check_hr(
        activate(
            device,
            ctypes.byref(endpoint_volume_iid),
            _CLSCTX_ALL,
            None,
            ctypes.byref(endpoint_volume),
        ),
        "IMMDevice.Activate(IAudioEndpointVolume) failed",
    )
    if not endpoint_volume.value:
        raise AudioApplyError("IAudioEndpointVolume activation returned no interface")
    return endpoint_volume


def _get_master_volume_scalar(endpoint_volume: ctypes.c_void_p) -> float:
    get_volume = _com_method(
        endpoint_volume,
        9,
        ctypes.c_long,
        ctypes.POINTER(ctypes.c_float),
    )
    value = ctypes.c_float()
    _check_hr(
        get_volume(endpoint_volume, ctypes.byref(value)),
        "IAudioEndpointVolume.GetMasterVolumeLevelScalar failed",
    )
    return float(value.value)


def _set_master_volume_scalar(endpoint_volume: ctypes.c_void_p, scalar: float) -> None:
    set_volume = _com_method(
        endpoint_volume,
        7,
        ctypes.c_long,
        ctypes.c_float,
        ctypes.c_void_p,
    )
    _check_hr(
        set_volume(endpoint_volume, ctypes.c_float(scalar), None),
        "IAudioEndpointVolume.SetMasterVolumeLevelScalar failed",
    )


def _get_mute(endpoint_volume: ctypes.c_void_p) -> bool:
    get_mute = _com_method(
        endpoint_volume,
        15,
        ctypes.c_long,
        ctypes.POINTER(ctypes.c_int),
    )
    value = ctypes.c_int()
    _check_hr(
        get_mute(endpoint_volume, ctypes.byref(value)),
        "IAudioEndpointVolume.GetMute failed",
    )
    return bool(value.value)


def _set_mute(endpoint_volume: ctypes.c_void_p, muted: bool) -> None:
    set_mute = _com_method(
        endpoint_volume,
        14,
        ctypes.c_long,
        ctypes.c_int,
        ctypes.c_void_p,
    )
    _check_hr(
        set_mute(endpoint_volume, int(muted), None),
        "IAudioEndpointVolume.SetMute failed",
    )


def _send_media_key(virtual_key: int) -> None:
    keybd_event = ctypes.windll.user32.keybd_event
    keybd_event.argtypes = [
        wintypes.BYTE,
        wintypes.BYTE,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    keybd_event(virtual_key, 0, 0, None)
    keybd_event(virtual_key, 0, _KEYEVENTF_KEYUP, None)
