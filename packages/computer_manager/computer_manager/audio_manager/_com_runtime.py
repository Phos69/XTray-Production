"""Low-level Windows COM types, constants, and primitive helpers.

This module isolates ctypes Structure/Union definitions, Windows GUID
constants for the audio endpoint APIs, the `_com_session` context manager
for CoInitializeEx, and the `_com_method` vtable resolver. Other audio
modules build on these primitives without redefining ctypes plumbing.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any

from xtray.core import app_logging

_CLSID_MM_DEVICE_ENUMERATOR = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_IMM_DEVICE_ENUMERATOR = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_CLSID_POLICY_CONFIG = "{870af99c-171d-4f9e-af0d-e63df40c2bc9}"
_IID_POLICY_CONFIG = "{f8679f50-850a-41cf-9c72-430f290290c8}"
_IID_IAUDIO_ENDPOINT_VOLUME = "{5CDF2C82-841E-4546-9722-0CF74078229A}"
_PKEY_DEVICE_FMTID = "{a45c254e-df1c-4efd-8020-67d146a850e0}"
_PKEY_DEVICE_DESC_PID = 2
_PKEY_DEVICE_FRIENDLY_NAME_PID = 14
_E_RENDER = 0
_E_MULTIMEDIA = 1
_DEVICE_STATE_ACTIVE = 0x1
_DEVICE_STATE_DISABLED = 0x2
_DEVICE_STATE_NOT_PRESENT = 0x4
_DEVICE_STATE_UNPLUGGED = 0x8
_DEVICE_STATE_ALL = (
    _DEVICE_STATE_ACTIVE
    | _DEVICE_STATE_DISABLED
    | _DEVICE_STATE_NOT_PRESENT
    | _DEVICE_STATE_UNPLUGGED
)
_CLSCTX_ALL = 23
_STGM_READ = 0
_VT_LPWSTR = 31
_RPC_E_CHANGED_MODE = 0x80010106
_VK_MEDIA_PLAY_PAUSE = 0xB3
_KEYEVENTF_KEYUP = 0x0002


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.DWORD)]


class _PROPVARIANT_UNION(ctypes.Union):
    _fields_ = [
        ("pwszVal", wintypes.LPWSTR),
        ("ulVal", wintypes.ULONG),
        ("boolVal", ctypes.c_short),
    ]


class _PROPVARIANT(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [
        ("vt", wintypes.USHORT),
        ("wReserved1", wintypes.USHORT),
        ("wReserved2", wintypes.USHORT),
        ("wReserved3", wintypes.USHORT),
        ("value", _PROPVARIANT_UNION),
    ]


class _com_session:
    def __init__(self) -> None:
        self._uninitialize = False

    def __enter__(self) -> None:
        hr = _ole32().CoInitializeEx(None, 0)
        normalized = hr & 0xFFFFFFFF
        if normalized in (0, 1):
            self._uninitialize = True
            return
        if normalized == _RPC_E_CHANGED_MODE:
            return
        _check_hr(hr, "CoInitializeEx failed")

    def __exit__(self, *_exc: object) -> None:
        if self._uninitialize:
            _ole32().CoUninitialize()


def _com_method(
    pointer: ctypes.c_void_p,
    index: int,
    result_type: Any,
    *argument_types: Any,
) -> Any:
    vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(result_type, ctypes.c_void_p, *argument_types)(vtable[index])


def _release(pointer: ctypes.c_void_p) -> None:
    if not pointer.value:
        return
    release = _com_method(pointer, 2, ctypes.c_ulong)
    release(pointer)


def _guid(value: str) -> _GUID:
    result = _GUID()
    _check_hr(
        _ole32().CLSIDFromString(wintypes.LPCWSTR(value), ctypes.byref(result)),
        f"invalid GUID {value}",
    )
    return result


def _ole32() -> Any:
    return ctypes.windll.ole32


def _check_hr(hr: int, message: str) -> None:
    if hr & 0x80000000:
        normalized = hr & 0xFFFFFFFF
        error = OSError(f"{message}: HRESULT 0x{normalized:08X}")
        app_logging.get_logger("audio").warning(
            "%s: HRESULT 0x%08X",
            message,
            normalized,
            exc_info=(type(error), error, error.__traceback__),
        )
        raise error


def _state_label(state: int) -> str:
    if state == _DEVICE_STATE_ACTIVE:
        return "active"
    if state == _DEVICE_STATE_DISABLED:
        return "disabled"
    if state == _DEVICE_STATE_NOT_PRESENT:
        return "not_present"
    if state == _DEVICE_STATE_UNPLUGGED:
        return "unplugged"
    parts = []
    if state & _DEVICE_STATE_ACTIVE:
        parts.append("active")
    if state & _DEVICE_STATE_DISABLED:
        parts.append("disabled")
    if state & _DEVICE_STATE_NOT_PRESENT:
        parts.append("not_present")
    if state & _DEVICE_STATE_UNPLUGGED:
        parts.append("unplugged")
    return "|".join(parts) if parts else f"unknown:{state}"


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
