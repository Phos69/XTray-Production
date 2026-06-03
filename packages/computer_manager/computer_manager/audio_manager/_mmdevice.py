"""IMMDevice / IMMDeviceEnumerator / IPolicyConfig wrappers.

Wraps the Core Audio device enumeration and property-store APIs in plain
Python callables. The resulting `AudioSource` is the public-facing dataclass
from `.core`; this module focuses on the COM plumbing only.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from ._com_runtime import (
    _CLSCTX_ALL,
    _CLSID_MM_DEVICE_ENUMERATOR,
    _CLSID_POLICY_CONFIG,
    _IID_IMM_DEVICE_ENUMERATOR,
    _IID_POLICY_CONFIG,
    _PKEY_DEVICE_DESC_PID,
    _PKEY_DEVICE_FMTID,
    _PKEY_DEVICE_FRIENDLY_NAME_PID,
    _PROPERTYKEY,
    _PROPVARIANT,
    _STGM_READ,
    _VT_LPWSTR,
    _check_hr,
    _com_method,
    _guid,
    _ole32,
    _release,
    _state_label,
)


def _create_mm_device_enumerator() -> ctypes.c_void_p:
    enumerator = ctypes.c_void_p()
    _check_hr(
        _ole32().CoCreateInstance(
            ctypes.byref(_guid(_CLSID_MM_DEVICE_ENUMERATOR)),
            None,
            _CLSCTX_ALL,
            ctypes.byref(_guid(_IID_IMM_DEVICE_ENUMERATOR)),
            ctypes.byref(enumerator),
        ),
        "CoCreateInstance(MMDeviceEnumerator) failed",
    )
    return enumerator


def _create_policy_config() -> ctypes.c_void_p:
    policy_config = ctypes.c_void_p()
    _check_hr(
        _ole32().CoCreateInstance(
            ctypes.byref(_guid(_CLSID_POLICY_CONFIG)),
            None,
            _CLSCTX_ALL,
            ctypes.byref(_guid(_IID_POLICY_CONFIG)),
            ctypes.byref(policy_config),
        ),
        "CoCreateInstance(PolicyConfig) failed",
    )
    return policy_config


def _device_id(device: ctypes.c_void_p) -> str | None:
    get_id = _com_method(device, 5, ctypes.c_long, ctypes.POINTER(wintypes.LPWSTR))
    raw_id = wintypes.LPWSTR()
    _check_hr(get_id(device, ctypes.byref(raw_id)), "IMMDevice.GetId failed")
    try:
        return raw_id.value
    finally:
        if raw_id:
            _ole32().CoTaskMemFree(raw_id)


def _device_state(device: ctypes.c_void_p) -> str | None:
    get_state = _com_method(device, 6, ctypes.c_long, ctypes.POINTER(wintypes.DWORD))
    raw_state = wintypes.DWORD()
    _check_hr(get_state(device, ctypes.byref(raw_state)), "IMMDevice.GetState failed")
    return _state_label(raw_state.value)


def _open_property_store(device: ctypes.c_void_p) -> ctypes.c_void_p:
    open_store = _com_method(
        device,
        4,
        ctypes.c_long,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    )
    store = ctypes.c_void_p()
    _check_hr(open_store(device, _STGM_READ, ctypes.byref(store)), "IMMDevice.OpenPropertyStore failed")
    return store


def _read_property_string(store: ctypes.c_void_p, fmtid: str, pid: int) -> str | None:
    get_value = _com_method(
        store,
        5,
        ctypes.c_long,
        ctypes.POINTER(_PROPERTYKEY),
        ctypes.POINTER(_PROPVARIANT),
    )
    key = _PROPERTYKEY(_guid(fmtid), pid)
    value = _PROPVARIANT()
    try:
        _check_hr(get_value(store, ctypes.byref(key), ctypes.byref(value)), "IPropertyStore.GetValue failed")
        if value.vt != _VT_LPWSTR:
            return None
        return value.pwszVal or None
    finally:
        _ole32().PropVariantClear(ctypes.byref(value))


def _read_property_string_optional(store: ctypes.c_void_p, fmtid: str, pid: int) -> str | None:
    from xtray.core import app_logging

    try:
        return _read_property_string(store, fmtid, pid)
    except OSError as exc:
        app_logging.get_logger("audio").debug(
            "audio endpoint property unavailable fmtid=%s pid=%s: %s",
            fmtid,
            pid,
            exc,
        )
        return None


def _audio_source_from_device(device: ctypes.c_void_p, *, role: str):
    """Build an AudioSource from a live IMMDevice pointer."""
    from .core import AudioSource

    endpoint_id = _device_id(device)
    state = _device_state(device)
    store = _open_property_store(device)
    try:
        name = _read_property_string_optional(store, _PKEY_DEVICE_FMTID, _PKEY_DEVICE_DESC_PID)
        interface_name = _read_property_string_optional(
            store, _PKEY_DEVICE_FMTID, _PKEY_DEVICE_FRIENDLY_NAME_PID
        )
    finally:
        _release(store)
    label = name or interface_name or endpoint_id
    if not label:
        return None
    return AudioSource(
        name=label,
        endpoint_id=endpoint_id,
        interface_name=interface_name,
        role=role,
        state=state,
    )
