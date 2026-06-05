"""Read-only Windows HDR/Advanced Color state via DisplayConfig."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

from xtray.core import app_logging

QDC_ONLY_ACTIVE_PATHS = 0x00000002
ERROR_SUCCESS = 0
ERROR_INSUFFICIENT_BUFFER = 122
DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME = 1
DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO = 9


@dataclass(frozen=True)
class HdrState:
    supported: bool | None = None
    enabled: bool | None = None


class _LUID(ctypes.Structure):
    _fields_ = [
        ("LowPart", wintypes.DWORD),
        ("HighPart", wintypes.LONG),
    ]


class _DISPLAYCONFIG_RATIONAL(ctypes.Structure):
    _fields_ = [
        ("Numerator", wintypes.UINT),
        ("Denominator", wintypes.UINT),
    ]


class _DISPLAYCONFIG_2DREGION(ctypes.Structure):
    _fields_ = [
        ("cx", wintypes.UINT),
        ("cy", wintypes.UINT),
    ]


class _DISPLAYCONFIG_VIDEO_SIGNAL_INFO(ctypes.Structure):
    _fields_ = [
        ("pixelRate", ctypes.c_ulonglong),
        ("hSyncFreq", _DISPLAYCONFIG_RATIONAL),
        ("vSyncFreq", _DISPLAYCONFIG_RATIONAL),
        ("activeSize", _DISPLAYCONFIG_2DREGION),
        ("totalSize", _DISPLAYCONFIG_2DREGION),
        ("videoStandard", wintypes.UINT),
        ("scanLineOrdering", wintypes.UINT),
    ]


class _DISPLAYCONFIG_TARGET_MODE(ctypes.Structure):
    _fields_ = [("targetVideoSignalInfo", _DISPLAYCONFIG_VIDEO_SIGNAL_INFO)]


class _POINTL(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _DISPLAYCONFIG_SOURCE_MODE(ctypes.Structure):
    _fields_ = [
        ("width", wintypes.UINT),
        ("height", wintypes.UINT),
        ("pixelFormat", wintypes.UINT),
        ("position", _POINTL),
    ]


class _RECTL(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _DISPLAYCONFIG_DESKTOP_IMAGE_INFO(ctypes.Structure):
    _fields_ = [
        ("PathSourceSize", _POINTL),
        ("DesktopImageRegion", _RECTL),
        ("DesktopImageClip", _RECTL),
    ]


class _DISPLAYCONFIG_MODE_INFO_UNION(ctypes.Union):
    _fields_ = [
        ("targetMode", _DISPLAYCONFIG_TARGET_MODE),
        ("sourceMode", _DISPLAYCONFIG_SOURCE_MODE),
        ("desktopImageInfo", _DISPLAYCONFIG_DESKTOP_IMAGE_INFO),
    ]


class _DISPLAYCONFIG_MODE_INFO(ctypes.Structure):
    _fields_ = [
        ("infoType", wintypes.UINT),
        ("id", wintypes.UINT),
        ("adapterId", _LUID),
        ("mode", _DISPLAYCONFIG_MODE_INFO_UNION),
    ]


class _DISPLAYCONFIG_PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", _LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("statusFlags", wintypes.UINT),
    ]


class _DISPLAYCONFIG_PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", _LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("outputTechnology", wintypes.UINT),
        ("rotation", wintypes.UINT),
        ("scaling", wintypes.UINT),
        ("refreshRate", _DISPLAYCONFIG_RATIONAL),
        ("scanLineOrdering", wintypes.UINT),
        ("targetAvailable", wintypes.BOOL),
        ("statusFlags", wintypes.UINT),
    ]


class _DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", _DISPLAYCONFIG_PATH_SOURCE_INFO),
        ("targetInfo", _DISPLAYCONFIG_PATH_TARGET_INFO),
        ("flags", wintypes.UINT),
    ]


class _DISPLAYCONFIG_DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.UINT),
        ("size", wintypes.UINT),
        ("adapterId", _LUID),
        ("id", wintypes.UINT),
    ]


class _DISPLAYCONFIG_SOURCE_DEVICE_NAME(ctypes.Structure):
    _fields_ = [
        ("header", _DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("viewGdiDeviceName", wintypes.WCHAR * 32),
    ]


class _DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO(ctypes.Structure):
    _fields_ = [
        ("header", _DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("value", wintypes.UINT),
        ("colorEncoding", wintypes.UINT),
        ("bitsPerColorChannel", wintypes.UINT),
    ]


def read_hdr_state(adapter_name: str | None) -> HdrState:
    if sys.platform != "win32" or not adapter_name:
        return HdrState()
    try:
        return _read_hdr_state(adapter_name)
    except Exception as exc:
        app_logging.get_logger("display").debug(
            "could not read HDR state for %s: %s",
            adapter_name,
            exc,
            exc_info=True,
        )
        return HdrState()


def _read_hdr_state(adapter_name: str) -> HdrState:
    normalized_name = _normalize_adapter_name(adapter_name)
    for path in _query_active_paths():
        source_name = _source_device_name(path.sourceInfo.adapterId, path.sourceInfo.id)
        if _normalize_adapter_name(source_name) != normalized_name:
            continue
        return _advanced_color_info(path.targetInfo.adapterId, path.targetInfo.id)
    return HdrState()


def _query_active_paths() -> list[_DISPLAYCONFIG_PATH_INFO]:
    user32 = ctypes.windll.user32
    for _attempt in range(3):
        path_count = wintypes.UINT()
        mode_count = wintypes.UINT()
        code = user32.GetDisplayConfigBufferSizes(
            QDC_ONLY_ACTIVE_PATHS,
            ctypes.byref(path_count),
            ctypes.byref(mode_count),
        )
        if code != ERROR_SUCCESS:
            raise OSError(f"GetDisplayConfigBufferSizes failed: {code}")
        paths = (_DISPLAYCONFIG_PATH_INFO * max(path_count.value, 1))()
        modes = (_DISPLAYCONFIG_MODE_INFO * max(mode_count.value, 1))()
        code = user32.QueryDisplayConfig(
            QDC_ONLY_ACTIVE_PATHS,
            ctypes.byref(path_count),
            paths,
            ctypes.byref(mode_count),
            modes,
            None,
        )
        if code == ERROR_SUCCESS:
            return list(paths[: path_count.value])
        if code != ERROR_INSUFFICIENT_BUFFER:
            raise OSError(f"QueryDisplayConfig failed: {code}")
    raise OSError("QueryDisplayConfig failed: display topology changed while reading")


def _source_device_name(adapter_id: _LUID, source_id: int) -> str:
    info = _DISPLAYCONFIG_SOURCE_DEVICE_NAME()
    info.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
    info.header.size = ctypes.sizeof(info)
    info.header.adapterId = adapter_id
    info.header.id = int(source_id)
    _display_config_get_device_info(info)
    return str(info.viewGdiDeviceName)


def _advanced_color_info(adapter_id: _LUID, target_id: int) -> HdrState:
    info = _DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO()
    info.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO
    info.header.size = ctypes.sizeof(info)
    info.header.adapterId = adapter_id
    info.header.id = int(target_id)
    _display_config_get_device_info(info)
    return _advanced_color_value_to_hdr_state(int(info.value))


def _display_config_get_device_info(info: Any) -> None:
    code = ctypes.windll.user32.DisplayConfigGetDeviceInfo(ctypes.byref(info))
    if code != ERROR_SUCCESS:
        raise OSError(f"DisplayConfigGetDeviceInfo failed: {code}")


def _advanced_color_value_to_hdr_state(value: int) -> HdrState:
    return HdrState(
        supported=bool(value & 0x1),
        enabled=bool(value & 0x2),
    )


def _normalize_adapter_name(value: str) -> str:
    return value.strip().casefold()
