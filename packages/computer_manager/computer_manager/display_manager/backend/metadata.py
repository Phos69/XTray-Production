"""Display metadata cache and EDID/HDR enrichment."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from xtray.core import app_logging

from ..identity import stable_display_key
from . import hdr as _hdr_backend
from .edid import _parse_edid, _read_monitor_container_id, _read_monitor_edid
from .models import DisplayState


@dataclass(frozen=True)
class _MonitorMetadata:
    edid: bytes | None
    container_id: str | None


_DISPLAY_METADATA_CACHE: dict[str, _MonitorMetadata] = {}
_DISPLAY_METADATA_TOPOLOGY_SIGNATURE: tuple[tuple[str, str, int], ...] | None = None
# Cache of EnumDisplaySettingsEx results, keyed by monitor device_id (casefold).
# Supported display modes are a property of the monitor hardware (EDID) plus
# the GPU output port; they do not change for the lifetime of the process for
# a given monitor, so we keep this cache independent of topology rescans.
_DISPLAY_MODES_CACHE: dict[str, Any] = {}


def positive_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return None
    return ivalue if ivalue > 0 else None


def enrich_display_metadata(display_state: DisplayState) -> None:
    """Attach EDID-derived monitor metadata when Windows registry data is available."""
    metadata_entry = _cached_monitor_metadata(display_state.device_id)
    edid = metadata_entry.edid
    if edid:
        metadata = _parse_edid(edid)
        for key, value in metadata.items():
            setattr(display_state, key, value)
        display_state.edid_hash = hashlib.sha1(edid).hexdigest()
    container_id = metadata_entry.container_id
    if container_id:
        display_state.container_id = container_id
    hdr_state = _hdr_backend.read_hdr_state(display_state.adapter_name)
    if hdr_state.supported is not None:
        display_state.hdr_supported = hdr_state.supported
    if hdr_state.enabled is not None:
        display_state.hdr_enabled = hdr_state.enabled
    display_state.stable_id = stable_display_key(display_state)


def clear_display_metadata_cache() -> None:
    """Clear cached EDID and ContainerID reads."""
    global _DISPLAY_METADATA_TOPOLOGY_SIGNATURE
    _DISPLAY_METADATA_CACHE.clear()
    _DISPLAY_METADATA_TOPOLOGY_SIGNATURE = None
    _DISPLAY_MODES_CACHE.clear()


def cached_display_modes(monitor_device_id: str | None) -> Any | None:
    if not monitor_device_id:
        return None
    return _DISPLAY_MODES_CACHE.get(monitor_device_id.casefold())


def set_cached_display_modes(monitor_device_id: str | None, modes: Any) -> None:
    if not monitor_device_id:
        return
    _DISPLAY_MODES_CACHE[monitor_device_id.casefold()] = modes


def refresh_display_metadata_cache_topology(win32api: Any, win32con: Any) -> None:
    global _DISPLAY_METADATA_TOPOLOGY_SIGNATURE
    signature = _display_topology_signature(win32api, win32con)
    if _DISPLAY_METADATA_TOPOLOGY_SIGNATURE is None:
        if _DISPLAY_METADATA_CACHE:
            app_logging.get_logger("display").debug(
                "display topology baseline initialized; clearing stale EDID metadata cache"
            )
            _DISPLAY_METADATA_CACHE.clear()
    elif signature != _DISPLAY_METADATA_TOPOLOGY_SIGNATURE:
        app_logging.get_logger("display").debug(
            "display topology changed; clearing EDID metadata cache"
        )
        _DISPLAY_METADATA_CACHE.clear()
    _DISPLAY_METADATA_TOPOLOGY_SIGNATURE = signature


def _cached_monitor_metadata(device_id: str) -> _MonitorMetadata:
    cache_key = device_id.casefold()
    cached = _DISPLAY_METADATA_CACHE.get(cache_key)
    if cached is not None:
        return cached
    metadata = _MonitorMetadata(
        edid=_read_monitor_edid(device_id),
        container_id=_read_monitor_container_id(device_id),
    )
    _DISPLAY_METADATA_CACHE[cache_key] = metadata
    return metadata


def _display_topology_signature(
    win32api: Any,
    win32con: Any,
) -> tuple[tuple[str, str, int], ...]:
    attached_flag = getattr(win32con, "DISPLAY_DEVICE_ATTACHED_TO_DESKTOP", 1)
    active_flag = getattr(win32con, "DISPLAY_DEVICE_ACTIVE", 1)
    items: list[tuple[str, str, int]] = []
    index = 0
    while True:
        try:
            adapter = win32api.EnumDisplayDevices(None, index, 0)
        except Exception:
            break
        index += 1
        adapter_name = str(getattr(adapter, "DeviceName", ""))
        adapter_id = str(getattr(adapter, "DeviceID", "")) or adapter_name
        adapter_flags = int(getattr(adapter, "StateFlags", 0))
        monitor_index = 0
        monitor_count = 0
        while adapter_name:
            try:
                monitor = win32api.EnumDisplayDevices(adapter_name, monitor_index, 0)
            except Exception:
                break
            monitor_index += 1
            monitor_count += 1
            monitor_id = str(getattr(monitor, "DeviceID", "")) or adapter_id
            monitor_flags = int(getattr(monitor, "StateFlags", 0))
            relevant_flags = monitor_flags & (attached_flag | active_flag)
            items.append((adapter_name, monitor_id, relevant_flags))
        if monitor_count == 0:
            relevant_flags = adapter_flags & (attached_flag | active_flag)
            items.append((adapter_name, adapter_id, relevant_flags))
    return tuple(items)
