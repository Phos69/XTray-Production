"""Windows display backend.

Wraps WinAPI (via pywin32) for resolution / refresh / arrangement / orientation
and DDC/CI (via monitorcontrol) for brightness / contrast / input source.

The module intentionally keeps file and network I/O out of the backend. Callers
receive structured results so CLI, API, and GUI can report partial failures.
"""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from xtray.core import app_logging

from ..geometry import (
    ensure_enabled_primary,
    normalize_display_geometry,
    normalize_display_mode,
    normalized_mode_size,
)
from ..identity import (
    display_identity_aliases,
    display_identity_matches,
    stable_display_key,
)
from ..identity import (
    display_match_aliases as _display_match_aliases,
)
from . import ddcci as _ddcci_backend
from .metadata import (
    cached_display_modes as _cached_display_modes,
)
from .metadata import (
    clear_display_metadata_cache as clear_display_metadata_cache,
)
from .metadata import (
    enrich_display_metadata,
)
from .metadata import (
    positive_or_none as _positive_or_none,
)
from .metadata import (
    refresh_display_metadata_cache_topology as _refresh_display_metadata_cache_topology,
)
from .metadata import (
    set_cached_display_modes as _set_cached_display_modes,
)
from .models import (
    HDR_NOT_MANAGED_LABEL as HDR_NOT_MANAGED_LABEL,
)
from .models import (
    VALID_ORIENTATIONS,
    ApplyResult,
    ApplyWarning,
    DisplayMode,
    DisplayState,
    PlannedDisplayChange,
    SystemState,
)
from .models import (
    DisplayApplyPlan as _DisplayApplyPlan,
)
from .waiting import poll_until, wait_seconds

_ORIENTATION_TO_DEVMODE = {0: 0, 90: 1, 180: 2, 270: 3}
_DEVMODE_TO_ORIENTATION = {value: key for key, value in _ORIENTATION_TO_DEVMODE.items()}
_DISPLAY_IDENTITY_FIELDS = (
    "device_id",
    "name",
    "manufacturer_id",
    "manufacturer",
    "product_code",
    "model",
    "serial_number",
    "physical_width_cm",
    "physical_height_cm",
    "diagonal_inches",
    "manufacture_year",
    "container_id",
    "edid_hash",
    "stable_id",
)
_PRIMARY_SWITCH_INITIAL_DELAY_SECONDS = 0.1
# Confirm is "cosmetic": the Windows API call already returned
# DISP_CHANGE_SUCCESSFUL, so a polling miss only means the enumeration cache
# has not refreshed yet — not that the change was rejected. Keep the budget
# tight (1.5s @ 50ms) so we do not burn 8s per primary switch waiting for a
# refresh that, in practice, rarely arrives within the previous 8s budget.
_PRIMARY_SWITCH_POLL_SECONDS = 0.05
_PRIMARY_SWITCH_TIMEOUT_SECONDS = 1.5
_PRIMARY_REFRESH_TIMEOUT_SECONDS = 1.5
_TEMP_PRIMARY_SETTLE_SECONDS = 0.5
_DISPLAYSWITCH_SETTLE_SECONDS = 2.0


def _require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError("displaymanager.display requires Windows")


def list_displays() -> list[DisplayState]:
    """Enumerate connected displays with stable monitor IDs where available."""
    _require_windows()
    win32api, win32con = _win32()
    _refresh_display_metadata_cache_topology(win32api, win32con)
    displays = _list_displays_from_monitors(win32api, win32con)
    if displays:
        return _dedupe_displays(displays)
    return _dedupe_displays(_list_displays_from_adapters(win32api, win32con))


def list_available_displays() -> list[DisplayState]:
    """Enumerate active and known inactive displays with EDID metadata."""
    _require_windows()
    win32api, win32con = _win32()
    _refresh_display_metadata_cache_topology(win32api, win32con)
    active = _list_displays_from_monitors(win32api, win32con)
    known = _list_displays_from_adapters(win32api, win32con, include_inactive=True)
    return _dedupe_displays(active + known)


def _list_displays_from_monitors(win32api: Any, win32con: Any) -> list[DisplayState]:
    displays: list[DisplayState] = []
    try:
        monitors = win32api.EnumDisplayMonitors(None, None)
    except Exception as exc:
        app_logging.get_logger("display").warning(
            "EnumDisplayMonitors failed: %s; falling back to adapter enumeration", exc
        )
        return displays

    adapter_by_name = _adapters_by_name(win32api)
    primary_flag = getattr(win32con, "MONITORINFOF_PRIMARY", 1)

    for monitor_handle, _hdc, monitor_rect in monitors:
        try:
            monitor_info = win32api.GetMonitorInfo(monitor_handle)
        except Exception as exc:
            app_logging.get_logger("display").warning(
                "GetMonitorInfo failed for monitor handle %r: %s",
                monitor_handle,
                exc,
                exc_info=True,
            )
            monitor_info = {}
        adapter_name = str(monitor_info.get("Device") or "")
        adapter = adapter_by_name.get(adapter_name)
        monitor = _first_monitor_device(win32api, win32con, adapter_name)
        settings = _current_settings(win32api, win32con, adapter_name)
        rect = monitor_info.get("Monitor") or monitor_rect
        left, top, right, bottom = _rect_tuple(rect)
        device_id = (
            str(getattr(monitor, "DeviceID", ""))
            or str(getattr(adapter, "DeviceID", ""))
            or adapter_name
            or f"monitor-{len(displays) + 1}"
        )
        display_name = (
            str(getattr(monitor, "DeviceString", ""))
            or str(getattr(adapter, "DeviceString", ""))
            or adapter_name
            or device_id
        )
        adapter_flags = int(getattr(adapter, "StateFlags", 0)) if adapter is not None else 0
        display_state = DisplayState(
                device_id=device_id,
                name=display_name,
                primary=bool(int(monitor_info.get("Flags", 0)) & primary_flag)
                or bool(adapter_flags & getattr(win32con, "DISPLAY_DEVICE_PRIMARY_DEVICE", 4)),
                enabled=True,
                width=getattr(settings, "PelsWidth", None) if settings else max(right - left, 0),
                height=getattr(settings, "PelsHeight", None) if settings else max(bottom - top, 0),
                refresh_hz=getattr(settings, "DisplayFrequency", None) if settings else None,
                orientation=_DEVMODE_TO_ORIENTATION.get(
                    getattr(settings, "DisplayOrientation", 0), 0
                )
                if settings
                else 0,
                pos_x=_get_position(settings, "x") if settings else left,
                pos_y=_get_position(settings, "y") if settings else top,
                adapter_name=adapter_name or None,
        )
        enrich_display_metadata(display_state)
        displays.append(display_state)
    return displays


def _list_displays_from_adapters(
    win32api: Any, win32con: Any, *, include_inactive: bool = False
) -> list[DisplayState]:
    displays: list[DisplayState] = []
    index = 0
    while True:
        try:
            adapter = win32api.EnumDisplayDevices(None, index, 0)
        except Exception as exc:
            if index == 0:
                app_logging.get_logger("display").warning(
                    "EnumDisplayDevices failed before listing any adapter: %s", exc
                )
            break
        index += 1

        state_flags = int(getattr(adapter, "StateFlags", 0))
        active_flag = getattr(win32con, "DISPLAY_DEVICE_ACTIVE", 1)
        attached_flag = getattr(win32con, "DISPLAY_DEVICE_ATTACHED_TO_DESKTOP", 1)
        primary_flag = getattr(win32con, "DISPLAY_DEVICE_PRIMARY_DEVICE", 4)
        enabled = bool(state_flags & (active_flag | attached_flag))
        if not enabled and not include_inactive:
            continue

        adapter_name = str(getattr(adapter, "DeviceName", ""))
        display_name = str(getattr(adapter, "DeviceString", adapter_name))
        device_id = str(getattr(adapter, "DeviceID", "")) or adapter_name
        monitor = _first_monitor_device(win32api, win32con, adapter_name)
        if monitor is None:
            # No monitor child means this is a GPU output without an attached
            # display (e.g. an unused HDMI port). Emitting it as a DisplayState
            # used to produce phantom entries (the adapter's PCI DeviceID) in
            # saved profiles, which later failed apply with "display not
            # connected" against the same adapter.
            app_logging.get_logger("display").debug(
                "skipping adapter %s: no monitor child device", adapter_name or device_id
            )
            continue
        device_id = str(getattr(monitor, "DeviceID", "")) or device_id
        display_name = str(getattr(monitor, "DeviceString", "")) or display_name

        settings = _current_settings(win32api, win32con, adapter_name) or _registry_settings(
            win32api, win32con, adapter_name
        )
        display_state = DisplayState(
                device_id=device_id,
                name=display_name,
                primary=bool(state_flags & primary_flag),
                enabled=enabled,
                width=_positive_or_none(
                    getattr(settings, "PelsWidth", None) if settings else None
                ),
                height=_positive_or_none(
                    getattr(settings, "PelsHeight", None) if settings else None
                ),
                refresh_hz=_positive_or_none(
                    getattr(settings, "DisplayFrequency", None) if settings else None
                ),
                orientation=_DEVMODE_TO_ORIENTATION.get(
                    getattr(settings, "DisplayOrientation", 0), 0
                )
                if settings
                else 0,
                pos_x=_get_position(settings, "x") if settings else 0,
                pos_y=_get_position(settings, "y") if settings else 0,
                adapter_name=adapter_name,
        )
        enrich_display_metadata(display_state)
        displays.append(display_state)
    return displays


def _adapters_by_name(win32api: Any) -> dict[str, Any]:
    adapters: dict[str, Any] = {}
    index = 0
    while True:
        try:
            adapter = win32api.EnumDisplayDevices(None, index, 0)
        except Exception:
            break
        index += 1
        name = str(getattr(adapter, "DeviceName", ""))
        if name:
            adapters[name] = adapter
    return adapters


def _first_monitor_device(win32api: Any, win32con: Any, adapter_name: str) -> Any | None:
    """Return the monitor child device of ``adapter_name``.

    Why: Windows can enumerate a stale placeholder monitor at index 0 (e.g. a
    previously-attached LG TV) alongside the *actually attached* monitor at a
    higher index. Picking index 0 unconditionally makes two physically
    different monitors appear identical because their EDID is read from the
    same stale entry. Prefer the device flagged
    ``DISPLAY_DEVICE_ATTACHED_TO_DESKTOP``; only fall back to the first
    enumerated entry when nothing is attached (inactive adapter routes).
    """
    if not adapter_name:
        return None
    attached_flag = getattr(win32con, "DISPLAY_DEVICE_ATTACHED_TO_DESKTOP", 1)
    fallback: Any | None = None
    index = 0
    while True:
        try:
            monitor = win32api.EnumDisplayDevices(adapter_name, index, 0)
        except Exception:
            break
        if int(getattr(monitor, "StateFlags", 0)) & attached_flag:
            return monitor
        if fallback is None:
            fallback = monitor
        index += 1
    return fallback


def _rect_tuple(rect: Any) -> tuple[int, int, int, int]:
    try:
        left, top, right, bottom = rect
        return int(left), int(top), int(right), int(bottom)
    except Exception:
        return 0, 0, 0, 0


def _dedupe_displays(displays: list[DisplayState]) -> list[DisplayState]:
    """Return one entry per physical monitor, preferring the enabled copy.

    Why: Windows can enumerate the same physical monitor on multiple GPU
    adapters (an Iiyama appearing on DISPLAY1/3/4 with the same EDID), and
    each enumeration becomes a ``DisplayState``. Identity is collapsed via
    ``stable_display_key`` so the same monitor surfaces only once even when
    its volatile ``device_id`` or ``adapter_name`` differ between routes.
    """
    active_keys: set[str] = set()
    for display_state in displays:
        if display_state.enabled:
            active_keys.update(_display_match_aliases(display_state))
    seen_keys: set[str] = set()
    unique: list[DisplayState] = []
    for display_state in displays:
        keys = _display_match_aliases(display_state)
        if not display_state.enabled and keys & active_keys:
            continue
        if keys & seen_keys:
            continue
        seen_keys.update(keys)
        unique.append(display_state)
    return unique


def _dedupe_displays_by_adapter(displays: list[DisplayState]) -> list[DisplayState]:
    """Return one entry per Windows adapter route, preserving inactive duplicates.

    Why: the apply planner needs per-adapter visibility — the same physical
    monitor may have inactive route candidates on DISPLAY1/3/4, and the
    profile may explicitly target one of them. The shared dedupe keeps one
    entry per ``adapter_name``; entries without an adapter fall back to
    ``stable_display_key``.
    """
    seen_adapters: set[str] = set()
    seen_without_adapter: set[str] = set()
    unique: list[DisplayState] = []
    for display_state in displays:
        adapter_name = display_state.adapter_name
        if adapter_name:
            key = adapter_name.casefold()
            if key in seen_adapters:
                continue
            seen_adapters.add(key)
            unique.append(display_state)
            continue
        key = stable_display_key(display_state)
        if key in seen_without_adapter:
            continue
        seen_without_adapter.add(key)
        unique.append(display_state)
    return unique


def _normalize_requested_displays_for_adapters(
    win32api: Any,
    win32con: Any,
    requested: list[DisplayState],
    available_displays: list[DisplayState],
    result: ApplyResult,
) -> None:
    by_adapter = {
        display_state.adapter_name.casefold(): display_state
        for display_state in available_displays
        if display_state.adapter_name
    }
    modes_by_adapter: dict[str, list[DisplayMode]] = {}
    for target in requested:
        original_adapter_name = target.adapter_name
        original_display_id = target.device_id
        adapter_display = _choose_display_for_target(available_displays, target)
        if adapter_display is not None:
            if adapter_display.enabled:
                _copy_display_identity(adapter_display, target)
            if adapter_display.adapter_name:
                if (
                    original_adapter_name
                    and original_adapter_name.casefold()
                    != adapter_display.adapter_name.casefold()
                ):
                    result.warnings.append(
                        ApplyWarning(
                            "profile adapter is stale; using current Windows adapter",
                            display_id=original_display_id or target.device_id,
                            detail=f"{original_adapter_name} -> {adapter_display.adapter_name}",
                        )
                    )
                target.adapter_name = adapter_display.adapter_name
        if not target.adapter_name:
            continue
        adapter_key = target.adapter_name.casefold()
        adapter_display = by_adapter.get(adapter_key)
        if _has_conflicting_edid_identity(adapter_display, target):
            continue
        if not target.enabled:
            continue
        normalize_display_mode(target)
        if adapter_key not in modes_by_adapter:
            modes_by_adapter[adapter_key] = _display_modes_for_adapter(
                win32api,
                win32con,
                adapter_key,
                target.adapter_name,
                monitor_device_id=target.device_id,
            )
        _normalize_requested_mode(target, adapter_display, modes_by_adapter[adapter_key], result)


def _display_modes_for_adapter(
    win32api: Any,
    win32con: Any,
    adapter_key: str,
    adapter_name: str,
    *,
    monitor_device_id: str | None = None,
) -> list[DisplayMode]:
    cached = _cached_display_modes(monitor_device_id)
    if cached is not None:
        return cached
    modes: list[DisplayMode] = []
    seen: set[tuple[int, int, int]] = set()
    for flags in _display_mode_query_flags(win32con):
        index = 0
        while True:
            try:
                settings = win32api.EnumDisplaySettingsEx(adapter_name, index, flags)
            except Exception:
                break
            index += 1
            if settings is None:
                break
            try:
                mode = DisplayMode(
                    width=int(settings.PelsWidth),
                    height=int(settings.PelsHeight),
                    refresh_hz=int(settings.DisplayFrequency),
                )
            except Exception:
                continue
            key = (mode.width, mode.height, mode.refresh_hz)
            if min(key) <= 0 or key in seen:
                continue
            seen.add(key)
            modes.append(mode)
    app_logging.get_logger("display").debug(
        "enumerated %s display modes for %s", len(modes), adapter_key
    )
    _set_cached_display_modes(monitor_device_id, modes)
    return modes


def _display_mode_query_flags(win32con: Any) -> tuple[int, ...]:
    rotated = getattr(win32con, "EDS_ROTATEDMODE", 0x4)
    flags = [0]
    if rotated not in flags:
        flags.append(int(rotated))
    return tuple(flags)


def _copy_display_identity(source: DisplayState, target: DisplayState) -> None:
    for field_name in _DISPLAY_IDENTITY_FIELDS:
        setattr(target, field_name, getattr(source, field_name))


def _normalize_requested_mode(
    target: DisplayState,
    adapter_display: DisplayState | None,
    modes: list[DisplayMode],
    result: ApplyResult,
) -> None:
    if not modes:
        return

    supported_by_resolution: dict[tuple[int, int], list[int]] = {}
    for mode in modes:
        supported_by_resolution.setdefault((mode.width, mode.height), []).append(mode.refresh_hz)
    for rates in supported_by_resolution.values():
        rates.sort()

    requested_resolution = (
        (target.width, target.height) if target.width and target.height else None
    )
    replacement = None
    if requested_resolution not in supported_by_resolution:
        replacement = _preferred_replacement_mode(adapter_display, modes)
    elif target.refresh_hz is not None:
        rates = supported_by_resolution[requested_resolution]
        if target.refresh_hz not in rates:
            replacement = DisplayMode(
                width=requested_resolution[0],
                height=requested_resolution[1],
                refresh_hz=_preferred_refresh(adapter_display, rates),
            )

    if replacement is None:
        return

    old_mode = f"{target.width or '?'}x{target.height or '?'}@{target.refresh_hz or '?'}Hz"
    target.width = replacement.width
    target.height = replacement.height
    target.refresh_hz = replacement.refresh_hz
    result.warnings.append(
        ApplyWarning(
            "profile mode is not supported by this adapter; using nearest available mode",
            display_id=target.device_id,
            detail=f"{old_mode} -> {replacement.width}x{replacement.height}@{replacement.refresh_hz}Hz",
        )
    )


def _preferred_replacement_mode(
    adapter_display: DisplayState | None,
    modes: list[DisplayMode],
) -> DisplayMode:
    if adapter_display and adapter_display.width and adapter_display.height:
        current_resolution = (adapter_display.width, adapter_display.height)
        matching = [
            mode for mode in modes if (mode.width, mode.height) == current_resolution
        ]
        if matching:
            preferred_rate = adapter_display.refresh_hz or 60
            return min(matching, key=lambda mode: abs(mode.refresh_hz - preferred_rate))
    return max(modes, key=lambda mode: (mode.width * mode.height, mode.refresh_hz))


def _preferred_refresh(adapter_display: DisplayState | None, rates: list[int]) -> int:
    if adapter_display and adapter_display.refresh_hz in rates:
        return int(adapter_display.refresh_hz)
    return min(rates, key=lambda rate: abs(rate - 60))


def get_state(*, include_inactive: bool = False) -> SystemState:
    """Capture the current system display configuration.

    When include_inactive is True, also include adapters that are connected but
    currently disabled, so callers (e.g. the GUI profile editor) can render and
    re-enable them.
    """
    displays = list_available_displays() if include_inactive else list_displays()
    return SystemState(displays=displays)


def list_display_modes(adapter_name: str | None) -> list[DisplayMode]:
    """Enumerate supported display modes for a Windows adapter name."""
    if not adapter_name:
        return []
    _require_windows()
    win32api, win32con = _win32()
    modes: list[DisplayMode] = []
    seen: set[tuple[int, int, int]] = set()
    for flags in _display_mode_query_flags(win32con):
        index = 0
        while True:
            try:
                settings = win32api.EnumDisplaySettingsEx(adapter_name, index, flags)
            except Exception:
                break
            index += 1
            if settings is None:
                break
            try:
                width = int(settings.PelsWidth)
                height = int(settings.PelsHeight)
                refresh = int(settings.DisplayFrequency)
            except Exception:
                continue
            if width <= 0 or height <= 0 or refresh <= 0:
                continue
            key = (width, height, refresh)
            if key in seen:
                continue
            seen.add(key)
            modes.append(DisplayMode(width=width, height=height, refresh_hz=refresh))
    return modes


def _normalized_requested_display_copies(displays: list[DisplayState]) -> list[DisplayState]:
    requested = [DisplayState.from_dict(item.to_dict()) for item in displays]
    normalize_display_geometry(requested)
    return requested


def _build_display_apply_plan(
    win32api: Any,
    win32con: Any,
    base_requested_displays: list[DisplayState],
    result: ApplyResult,
    *,
    current: list[DisplayState] | None = None,
    disable_missing: bool = True,
) -> _DisplayApplyPlan:
    current_displays = list_displays() if current is None else current
    known_displays = _dedupe_displays_by_adapter(
        current_displays
        + _list_displays_from_adapters(win32api, win32con, include_inactive=True)
    )
    requested_displays = [
        DisplayState.from_dict(item.to_dict()) for item in base_requested_displays
    ]
    _normalize_requested_displays_for_adapters(
        win32api,
        win32con,
        requested_displays,
        current_displays + known_displays,
        result,
    )
    planned_changes = _plan_display_changes(
        current_displays,
        requested_displays,
        result,
        known_displays,
        disable_missing=disable_missing,
    )
    return _DisplayApplyPlan(
        current=current_displays,
        known=known_displays,
        requested=requested_displays,
        planned=planned_changes,
    )


def apply_state(
    state: SystemState, *, test_first: bool = True, dry_run: bool = False
) -> ApplyResult:
    """Apply a target system state.

    When test_first is True, validates the change with CDS_TEST per device
    before committing. Caller is responsible for any auto-revert UX.
    """
    result = ApplyResult(dry_run=dry_run)
    _validate_requested_state(state, result)
    if result.errors:
        return result
    if dry_run:
        result.warnings.append(ApplyWarning("dry run completed without applying changes"))
        return result

    _require_windows()
    logger = app_logging.get_logger("display")
    win32api, win32con = _win32()
    base_requested_displays = _normalized_requested_display_copies(state.displays)
    planning_warning_start = len(result.warnings)
    plan = _build_display_apply_plan(win32api, win32con, base_requested_displays, result)
    current = plan.current
    rollback_snapshot = list(current)
    planned_changes = plan.planned
    if result.errors:
        if _has_missing_monitor_errors(result.errors) and any(d.enabled for d in current):
            stashed_errors = list(result.errors)
            result.errors.clear()
            _attempt_mst_topology_rescue(result)
            if result.errors:
                result.errors.extend(stashed_errors)
                return result
            plan = _build_display_apply_plan(
                win32api, win32con, base_requested_displays, result
            )
            current = plan.current
            rollback_snapshot = list(current)
            planned_changes = plan.planned
            if result.errors:
                return result
        else:
            return result
    if _requires_desktop_extend(planned_changes):
        result.warnings = result.warnings[:planning_warning_start]
        expected_enabled = sum(1 for d in base_requested_displays if d.enabled)
        _extend_desktop_with_displayswitch(
            result, expected_enabled_count=expected_enabled
        )
        if result.errors:
            return result
        plan = _build_display_apply_plan(win32api, win32con, base_requested_displays, result)
        current = plan.current
        planned_changes = plan.planned
        if result.errors:
            return result

    primary_change = next(
        (change for change in planned_changes if _is_new_primary_change(change)),
        None,
    )
    if primary_change is not None:
        if primary_change.current.adapter_name and _apply_primary_switch_in_isolation(
            win32api, win32con, primary_change, current, result, logger
        ):
            plan = _build_display_apply_plan(win32api, win32con, base_requested_displays, result)
            current = plan.current
            rollback_snapshot = list(current)
            planned_changes = plan.planned
            if result.errors:
                return result
        else:
            result.warnings.append(
                ApplyWarning(
                    "isolated primary switch failed; falling back to deferred staging pipeline",
                    display_id=primary_change.target.device_id,
                )
            )
            if _would_disable_current_primary(planned_changes):
                result.errors.append(
                    "primary switch could not be confirmed; skipped changes that would disable the current primary display"
                )
                return result

    allow_failed_mode_test = len(planned_changes) > 1
    staged_any = _stage_planned_changes(
        win32api,
        win32con,
        planned_changes,
        test_first,
        result,
        defer_commit=True,
        persist_changes=True,
        logger=logger,
        allow_failed_mode_test=allow_failed_mode_test,
    )

    if result.errors:
        if not staged_any and _can_retry_with_immediate_changes(result.errors):
            for err in result.errors:
                result.warnings.append(
                    ApplyWarning(f"deferred staging error: {err}")
                )
            result.errors.clear()
            result.warnings.append(
                ApplyWarning(
                    "deferred Windows display staging failed; retrying with immediate changes"
                )
            )
            staged_any = _stage_planned_changes(
                win32api,
                win32con,
                planned_changes,
                test_first,
                result,
                defer_commit=False,
                persist_changes=True,
                logger=logger,
                allow_failed_mode_test=allow_failed_mode_test,
            )
            if result.errors:
                if not staged_any and _can_retry_with_immediate_changes(result.errors):
                    for err in result.errors:
                        result.warnings.append(
                            ApplyWarning(f"immediate staging error: {err}")
                        )
                    result.errors.clear()
                    result.warnings.append(
                        ApplyWarning(
                            "persistent Windows display change failed; retrying with temporary changes"
                        )
                    )
                    staged_any = _stage_planned_changes(
                        win32api,
                        win32con,
                        planned_changes,
                        test_first,
                        result,
                        defer_commit=False,
                        persist_changes=False,
                        logger=logger,
                        allow_failed_mode_test=allow_failed_mode_test,
                    )
                    if result.errors:
                        if staged_any:
                            _attempt_rollback(win32api, win32con, rollback_snapshot, result)
                        return result
                    _ddcci_backend.apply_ddcci(SystemState(displays=base_requested_displays), result)
                    result.applied = result.ok
                    return result
                if staged_any:
                    _attempt_rollback(win32api, win32con, rollback_snapshot, result)
                return result
            _ddcci_backend.apply_ddcci(SystemState(displays=base_requested_displays), result)
            result.applied = result.ok
            return result
        if staged_any:
            _attempt_rollback(win32api, win32con, rollback_snapshot, result)
        return result

    if not staged_any:
        _ddcci_backend.apply_ddcci(SystemState(displays=base_requested_displays), result)
        result.applied = result.ok
        return result

    try:
        commit_code = _change_display_settings_ex(win32api, None, None, 0)
    except Exception as exc:
        result.errors.append(f"failed to commit display changes: {exc}")
        if staged_any:
            _attempt_rollback(win32api, win32con, rollback_snapshot, result)
        return result

    success_code = getattr(win32con, "DISP_CHANGE_SUCCESSFUL", 0)
    if commit_code != success_code:
        result.errors.append(
            f"Windows rejected final display commit: {_display_change_code_name(win32con, commit_code)}"
        )
        if staged_any:
            _attempt_rollback(win32api, win32con, rollback_snapshot, result)
        return result

    _ddcci_backend.apply_ddcci(SystemState(displays=base_requested_displays), result)
    result.applied = result.ok
    return result


def _stage_planned_changes(
    win32api: Any,
    win32con: Any,
    planned_changes: list[PlannedDisplayChange],
    test_first: bool,
    result: ApplyResult,
    *,
    defer_commit: bool,
    persist_changes: bool,
    logger: Any,
    allow_failed_mode_test: bool,
) -> bool:
    staged_any = False
    requested_targets = [change.target for change in planned_changes]
    ordered_changes = (
        _ordered_planned_changes_for_staging(planned_changes)
        if defer_commit
        else _ordered_planned_changes_for_immediate_apply(planned_changes)
    )
    index = 0
    while index < len(ordered_changes):
        planned_change = ordered_changes[index]
        current_display = planned_change.current
        target = planned_change.target
        if not _display_change_required(current_display, target):
            index += 1
            continue
        adapter_name = current_display.adapter_name
        if not adapter_name:
            result.errors.append(f"{target.device_id}: no Windows adapter name available")
            index += 1
            continue
        allow_failed_enable_test = target.enabled and not current_display.enabled
        allow_failed_disable_test = (
            not target.enabled
            and current_display.primary
            and any(change.target.primary for change in planned_changes)
        )
        errors_before = len(result.errors)
        try:
            _stage_display_change(
                win32api,
                win32con,
                adapter_name,
                target,
                test_first,
                result,
                current=current_display,
                allow_failed_enable_test=allow_failed_enable_test,
                allow_failed_disable_test=allow_failed_disable_test,
                allow_failed_mode_test=allow_failed_mode_test,
                defer_commit=defer_commit,
                persist_changes=persist_changes,
            )
        except Exception as exc:
            logger.exception("failed to stage display change for %s", target.device_id)
            result.errors.append(f"{target.device_id}: {exc}")
        if len(result.errors) == errors_before:
            staged_any = True
            if not defer_commit and _is_new_primary_change(planned_change):
                _commit_immediate_primary_switch(win32api, win32con, result)
                refreshed_changes = _refresh_planned_changes_after_primary_switch(
                    win32api,
                    win32con,
                    requested_targets,
                    target,
                    result,
                )
                if refreshed_changes is not None:
                    ordered_changes = _ordered_planned_changes_for_immediate_apply(
                        refreshed_changes
                    )
                    index = 0
                    continue
                result.warnings.append(
                    ApplyWarning(
                        "primary switch was accepted but Windows did not report the updated display mapping; skipped remaining stale layout changes"
                    )
                )
                return staged_any
        index += 1
    return staged_any


def _is_new_primary_change(change: PlannedDisplayChange) -> bool:
    return change.target.enabled and change.target.primary and not change.current.primary


def _would_disable_current_primary(planned_changes: list[PlannedDisplayChange]) -> bool:
    return any(
        change.current.primary and change.current.enabled and not change.target.enabled
        for change in planned_changes
    )


def _commit_immediate_primary_switch(
    win32api: Any,
    win32con: Any,
    result: ApplyResult,
) -> None:
    try:
        commit_code = _change_display_settings_ex(win32api, None, None, 0)
    except Exception as exc:
        result.warnings.append(
            ApplyWarning(
                "primary switch commit raised while refreshing display mapping",
                detail=str(exc),
            )
        )
        return
    success_code = getattr(win32con, "DISP_CHANGE_SUCCESSFUL", 0)
    if commit_code != success_code:
        result.warnings.append(
            ApplyWarning(
                "primary switch commit was rejected while refreshing display mapping",
                detail=_display_change_code_name(win32con, commit_code),
            )
        )


def _apply_primary_switch_in_isolation(
    win32api: Any,
    win32con: Any,
    primary_change: PlannedDisplayChange,
    current_displays: list[DisplayState],
    result: ApplyResult,
    logger: Any,
) -> bool:
    """Try every known reliable strategy for swapping the primary display.

    Some drivers reject ``CDS_SET_PRIMARY | CDS_UPDATEREGISTRY`` whenever
    the call asks the new primary to occupy ``(0, 0)`` while the old
    primary still owns that origin, even with ``CDS_NORESET``. We try
    progressively more conservative shapes of the same intent until one
    sticks, surfacing each rejection as a warning so the failure mode is
    visible in the apply result.

    Strategies, in order:

    1. **Null devmode promotion.** Pass ``lpDevMode=NULL`` with
       ``CDS_SET_PRIMARY | CDS_UPDATEREGISTRY``. Windows reads the
       persisted mode from the registry and re-bases coordinates around
       the new primary itself. Avoids supplying any conflicting
       ``DM_POSITION``.
    2. **SetPrimary atomic batch.** Stage every active display with
       ``DM_POSITION`` adjusted by the offset that would land the new
       primary at ``(0, 0)``, all using ``CDS_NORESET``, then commit
       once. This is the canonical community pattern.

    Each strategy that fails leaves a warning and we move on. Returning
    ``True`` means Windows confirmed the primary swap and the caller
    should re-plan against the post-swap topology. ``False`` lets the
    caller fall through to the legacy deferred/immediate retry pipeline.
    """
    if not primary_change.current.adapter_name:
        return False

    if _try_primary_switch_null_devmode(
        win32api, win32con, primary_change, result, logger
    ):
        return True
    if _try_primary_switch_setprimary_batch(
        win32api, win32con, primary_change, current_displays, result, logger
    ):
        return True
    if _try_primary_switch_temp_then_persist(
        win32api, win32con, primary_change, result, logger
    ):
        return True
    return False


def _try_primary_switch_null_devmode(
    win32api: Any,
    win32con: Any,
    primary_change: PlannedDisplayChange,
    result: ApplyResult,
    logger: Any,
) -> bool:
    target = primary_change.target
    adapter_name = primary_change.current.adapter_name
    if not adapter_name:
        return False
    flags = (
        getattr(win32con, "CDS_UPDATEREGISTRY", 1)
        | getattr(win32con, "CDS_SET_PRIMARY", 0x10)
    )
    success_code = getattr(win32con, "DISP_CHANGE_SUCCESSFUL", 0)
    try:
        change_code = _change_display_settings_ex(win32api, adapter_name, None, flags)
    except Exception as exc:
        logger.exception("null-devmode primary switch raised for %s", target.device_id)
        result.warnings.append(
            ApplyWarning(
                "null-devmode primary switch raised an exception",
                display_id=target.device_id,
                detail=str(exc),
            )
        )
        return False
    if change_code != success_code:
        result.warnings.append(
            ApplyWarning(
                "null-devmode primary switch was rejected by Windows",
                display_id=target.device_id,
                detail=(
                    f"{_display_change_code_name(win32con, change_code)}; "
                    f"adapter={adapter_name}, flags={hex(flags)}"
                ),
            )
        )
        return False
    return _confirm_primary_switch(win32api, win32con, target, result, logger)


def _try_primary_switch_setprimary_batch(
    win32api: Any,
    win32con: Any,
    primary_change: PlannedDisplayChange,
    current_displays: list[DisplayState],
    result: ApplyResult,
    logger: Any,
) -> bool:
    target = primary_change.target
    current = primary_change.current
    offset_x = -int(current.pos_x)
    offset_y = -int(current.pos_y)

    update_registry = getattr(win32con, "CDS_UPDATEREGISTRY", 1)
    no_reset = getattr(win32con, "CDS_NORESET", 0x10000000)
    set_primary_flag = getattr(win32con, "CDS_SET_PRIMARY", 0x10)
    success_code = getattr(win32con, "DISP_CHANGE_SUCCESSFUL", 0)
    dm_position = getattr(win32con, "DM_POSITION", 0x20)

    ordered_displays = [d for d in current_displays if d.device_id == current.device_id]
    ordered_displays += [d for d in current_displays if d.device_id != current.device_id]
    staged_any = False
    for display_state in ordered_displays:
        if not display_state.enabled or not display_state.adapter_name:
            continue
        settings = _settings_for_change(win32api, win32con, display_state.adapter_name)
        if settings is None:
            result.warnings.append(
                ApplyWarning(
                    "SetPrimary batch could not read current Windows mode",
                    display_id=display_state.device_id,
                )
            )
            return False
        new_x = int(display_state.pos_x) + offset_x
        new_y = int(display_state.pos_y) + offset_y
        _set_position(settings, "x", new_x)
        _set_position(settings, "y", new_y)
        settings.Fields = dm_position
        flags = update_registry | no_reset
        if display_state.device_id == current.device_id:
            flags |= set_primary_flag
        try:
            change_code = _change_display_settings_ex(
                win32api, display_state.adapter_name, settings, flags
            )
        except Exception as exc:
            logger.exception(
                "SetPrimary batch staging raised for %s", display_state.device_id
            )
            result.warnings.append(
                ApplyWarning(
                    "SetPrimary batch staging raised an exception",
                    display_id=display_state.device_id,
                    detail=str(exc),
                )
            )
            return False
        if change_code != success_code:
            result.warnings.append(
                ApplyWarning(
                    "SetPrimary batch staging was rejected by Windows",
                    display_id=display_state.device_id,
                    detail=(
                        f"{_display_change_code_name(win32con, change_code)}; "
                        f"adapter={display_state.adapter_name}, "
                        f"pos=({new_x},{new_y}), "
                        f"flags={hex(flags)}"
                    ),
                )
            )
            return False
        staged_any = True

    if not staged_any:
        return False

    try:
        commit_code = _change_display_settings_ex(win32api, None, None, 0)
    except Exception as exc:
        logger.exception("SetPrimary batch commit raised")
        result.warnings.append(
            ApplyWarning(
                "SetPrimary batch commit raised an exception",
                display_id=target.device_id,
                detail=str(exc),
            )
        )
        return False
    if commit_code != success_code:
        result.warnings.append(
            ApplyWarning(
                "SetPrimary batch commit was rejected by Windows",
                display_id=target.device_id,
                detail=_display_change_code_name(win32con, commit_code),
            )
        )
        return False

    return _confirm_primary_switch(win32api, win32con, target, result, logger)


def _try_primary_switch_temp_then_persist(
    win32api: Any,
    win32con: Any,
    primary_change: PlannedDisplayChange,
    result: ApplyResult,
    logger: Any,
) -> bool:
    """Apply ``CDS_SET_PRIMARY`` temporarily, then persist it.

    Why: some drivers reject any persistent (``CDS_UPDATEREGISTRY``)
    primary swap while the registry still shows the old primary at
    ``(0, 0)``. They DO accept the same swap in volatile memory
    (``CDS_SET_PRIMARY`` alone). Once that volatile change has applied,
    the in-memory topology already places the new primary at ``(0, 0)``
    and the driver accepts the persistent follow-up because there is no
    longer a coordinate collision to validate.
    """
    target = primary_change.target
    adapter_name = primary_change.current.adapter_name
    if not adapter_name:
        return False

    set_primary_flag = getattr(win32con, "CDS_SET_PRIMARY", 0x10)
    update_registry = getattr(win32con, "CDS_UPDATEREGISTRY", 1)
    success_code = getattr(win32con, "DISP_CHANGE_SUCCESSFUL", 0)

    settings = _settings_for_change(win32api, win32con, adapter_name)
    if settings is None:
        return False
    settings.Fields = 0
    try:
        temp_code = _change_display_settings_ex(
            win32api, adapter_name, settings, set_primary_flag
        )
    except Exception as exc:
        logger.exception(
            "temp-then-persist primary switch step 1 raised for %s", target.device_id
        )
        result.warnings.append(
            ApplyWarning(
                "temp-then-persist primary switch step 1 raised an exception",
                display_id=target.device_id,
                detail=str(exc),
            )
        )
        return False
    if temp_code != success_code:
        result.warnings.append(
            ApplyWarning(
                "temp-then-persist primary switch step 1 was rejected by Windows",
                display_id=target.device_id,
                detail=(
                    f"{_display_change_code_name(win32con, temp_code)}; "
                    f"adapter={adapter_name}, flags={hex(set_primary_flag)}"
                ),
            )
        )
        return False

    _wait_seconds(_TEMP_PRIMARY_SETTLE_SECONDS)

    settings = _settings_for_change(win32api, win32con, adapter_name)
    if settings is None:
        return False
    settings.Fields = 0
    persist_flags = set_primary_flag | update_registry
    try:
        persist_code = _change_display_settings_ex(
            win32api, adapter_name, settings, persist_flags
        )
    except Exception as exc:
        logger.exception(
            "temp-then-persist primary switch step 2 raised for %s", target.device_id
        )
        result.warnings.append(
            ApplyWarning(
                "temp-then-persist primary switch step 2 raised an exception",
                display_id=target.device_id,
                detail=str(exc),
            )
        )
        return False
    if persist_code != success_code:
        result.warnings.append(
            ApplyWarning(
                "temp-then-persist primary switch step 2 was rejected by Windows",
                display_id=target.device_id,
                detail=(
                    f"{_display_change_code_name(win32con, persist_code)}; "
                    f"adapter={adapter_name}, flags={hex(persist_flags)}"
                ),
            )
        )
        return False

    return _confirm_primary_switch(win32api, win32con, target, result, logger)


def _confirm_primary_switch(
    win32api: Any,
    win32con: Any,
    target: DisplayState,
    result: ApplyResult,
    logger: Any,
) -> bool:
    """Poll ``list_displays`` until the target shows up as primary.

    Returns ``True`` on success. On timeout, returns ``True`` *and* records
    a warning — the Windows API call already reported success, so the
    commit is trusted; the polling miss usually means the live monitor
    enumeration cache has not refreshed yet, not that the change was
    rejected. Returning ``False`` here would force the caller to fall
    through to the legacy retry pipeline, which then tries to "set the
    same primary again" against an already-shifted topology and fails.
    """
    switched = _poll_until(
        lambda: _primary_switch_candidate(target),
        timeout=_PRIMARY_SWITCH_TIMEOUT_SECONDS,
        interval=_PRIMARY_SWITCH_POLL_SECONDS,
        initial_delay=_PRIMARY_SWITCH_INITIAL_DELAY_SECONDS,
    )
    if switched is not None:
        return True
    result.warnings.append(
        ApplyWarning(
            "primary switch was committed but Windows did not report the updated mapping in time",
            display_id=target.device_id,
        )
    )
    return True


def _primary_switch_candidate(target: DisplayState) -> DisplayState | None:
    live = list_displays()
    switched = _choose_display_for_target(live, target)
    if switched is not None and switched.primary:
        return switched
    return None


def _wait_seconds(seconds: float) -> None:
    wait_seconds(seconds)


def _poll_until(
    predicate: Callable[[], Any | None],
    *,
    timeout: float,
    interval: float,
    initial_delay: float = 0,
) -> Any | None:
    return poll_until(
        predicate,
        timeout=timeout,
        interval=interval,
        initial_delay=initial_delay,
        wait=_wait_seconds,
    )


def _primary_refresh_candidate(
    primary_target: DisplayState,
) -> tuple[list[DisplayState], DisplayState] | None:
    current = list_displays()
    switched_display = _choose_display_for_target(current, primary_target)
    if switched_display is not None and switched_display.primary:
        return current, switched_display
    return None


def _refresh_planned_changes_after_primary_switch(
    win32api: Any,
    win32con: Any,
    requested_targets: list[DisplayState],
    primary_target: DisplayState,
    result: ApplyResult,
) -> list[PlannedDisplayChange] | None:
    """Replan immediate changes after Windows may have reassigned DISPLAY names."""
    try:
        refreshed = _poll_until(
            lambda: _primary_refresh_candidate(primary_target),
            timeout=_PRIMARY_REFRESH_TIMEOUT_SECONDS,
            interval=_PRIMARY_SWITCH_POLL_SECONDS,
        )
        if refreshed is None:
            return None
        current, _switched_display = refreshed
        known_displays = _dedupe_displays_by_adapter(
            current + _list_displays_from_adapters(win32api, win32con, include_inactive=True)
        )
    except Exception as exc:
        result.warnings.append(
            ApplyWarning(
                "could not refresh Windows display mapping after primary switch; continuing with previous adapter names",
                detail=str(exc),
            )
        )
        return None

    available_displays = current + known_displays
    refreshed_targets = [DisplayState.from_dict(target.to_dict()) for target in requested_targets]
    for target in refreshed_targets:
        adapter_display = _choose_display_for_target(available_displays, target)
        if adapter_display is None:
            continue
        if adapter_display.enabled:
            _copy_display_identity(adapter_display, target)
        if adapter_display.adapter_name:
            target.adapter_name = adapter_display.adapter_name

    return _plan_display_changes(
        current,
        refreshed_targets,
        result,
        known_displays,
        disable_missing=False,
    )


def _can_retry_with_immediate_changes(errors: list[str]) -> bool:
    return bool(errors) and all(
        "Windows rejected mode change DISP_CHANGE_FAILED" in error for error in errors
    )


def _display_change_required(current: DisplayState, target: DisplayState) -> bool:
    """Return whether applying this target needs a Windows display API call."""
    if current.enabled != target.enabled:
        return True
    if not target.enabled:
        return False
    if target.primary and not current.primary:
        return True
    if target.width is not None and current.width != target.width:
        return True
    if target.height is not None and current.height != target.height:
        return True
    if target.refresh_hz is not None and current.refresh_hz != target.refresh_hz:
        return True
    return (
        current.orientation != target.orientation
        or current.pos_x != target.pos_x
        or current.pos_y != target.pos_y
    )


def _plan_display_changes(
    current: list[DisplayState],
    requested: list[DisplayState],
    result: ApplyResult,
    known_displays: list[DisplayState] | None = None,
    *,
    disable_missing: bool = True,
) -> list[PlannedDisplayChange]:
    if not requested:
        result.errors.append("profile contains no displays")
        return []

    if _ensure_requested_primary(current, requested):
        normalize_display_geometry(requested)

    matched_current: set[str] = set()
    planned: list[PlannedDisplayChange] = []

    for target in requested:
        synthesized_current = False
        current_display = _choose_display_for_target(
            current,
            target,
            matched_identities=matched_current,
        )
        if current_display is None:
            current_display = _choose_display_for_target(
                known_displays or [],
                target,
                matched_identities=matched_current,
            )
        if current_display is None:
            conflicting_display = _conflicting_display_on_adapter(
                current + (known_displays or []),
                target,
            )
            if conflicting_display is not None:
                # The profile's monitor identity does not match any active or
                # known-inactive display, and its old adapter slot is now used
                # by a different monitor. The adapter conflict is a symptom,
                # not the cause — the root issue is that Windows does not see
                # this monitor at all (powered off, cable unplugged, or the
                # GPU output it was on is now driving something else).
                result.errors.append(
                    f"monitor not detected by Windows: {target.device_id} "
                    f"(check that it is powered on and the cable is connected). "
                    f"Its previous adapter {target.adapter_name} is now used by "
                    f"{_display_label_for_error(conflicting_display)}"
                )
                continue
            if target.enabled and target.adapter_name:
                current_display = DisplayState(
                    device_id=target.device_id,
                    name=target.name,
                    enabled=False,
                    adapter_name=target.adapter_name,
                )
                synthesized_current = True
                result.warnings.append(
                    ApplyWarning(
                        "display is not active; attempting to enable it by adapter name",
                        display_id=target.device_id,
                    )
                )
            elif target.enabled:
                result.errors.append(f"display not connected: {target.device_id}")
                continue
            else:
                result.warnings.append(
                    ApplyWarning(
                        "display is already absent; disable skipped",
                        display_id=target.device_id,
                    )
                )
                continue
        if target.enabled and not current_display.enabled and not synthesized_current:
            result.warnings.append(
                ApplyWarning(
                    "display is currently disabled; enabling it",
                    display_id=target.device_id,
                )
            )
        matched_current.update(_display_match_aliases(current_display))
        planned.append(PlannedDisplayChange(current=current_display, target=target))

    if not disable_missing:
        return planned

    for current_display in current:
        if _display_match_aliases(current_display) & matched_current:
            continue
        target = DisplayState(
            device_id=current_display.device_id,
            name=current_display.name,
            primary=False,
            enabled=False,
            width=current_display.width,
            height=current_display.height,
            refresh_hz=current_display.refresh_hz,
            orientation=current_display.orientation,
            pos_x=current_display.pos_x,
            pos_y=current_display.pos_y,
            brightness=current_display.brightness,
            contrast=current_display.contrast,
            input_source=current_display.input_source,
            adapter_name=current_display.adapter_name,
        )
        result.warnings.append(
            ApplyWarning(
                "display is not in the profile; disabling it",
                display_id=current_display.device_id,
            )
        )
        planned.append(PlannedDisplayChange(current=current_display, target=target))
    return planned


def _ensure_requested_primary(
    current: list[DisplayState], requested: list[DisplayState]
) -> bool:
    if any(target.enabled and target.primary for target in requested):
        return ensure_enabled_primary(requested)

    current_primary = next(
        (
            display_state
            for display_state in current
            if display_state.enabled and display_state.primary
        ),
        None,
    )
    if current_primary is None:
        return False

    enabled_requested = [target for target in requested if target.enabled]
    preferred = _choose_display_for_target(enabled_requested, current_primary)
    return ensure_enabled_primary(requested, preferred=preferred)


def _requires_desktop_extend(planned_changes: list[PlannedDisplayChange]) -> bool:
    return any(change.target.enabled and not change.current.enabled for change in planned_changes)


def _ordered_planned_changes_for_staging(
    planned_changes: list[PlannedDisplayChange],
) -> list[PlannedDisplayChange]:
    return sorted(planned_changes, key=_planned_change_staging_order)


def _ordered_planned_changes_for_immediate_apply(
    planned_changes: list[PlannedDisplayChange],
) -> list[PlannedDisplayChange]:
    return sorted(planned_changes, key=_planned_change_immediate_order)


def _planned_change_staging_order(change: PlannedDisplayChange) -> tuple[int, int]:
    if change.target.enabled and change.target.primary and not change.current.primary:
        return (0, 0)
    if change.target.enabled and not change.current.enabled:
        return (1, 0)
    if not change.target.enabled:
        return (3, 1 if change.current.primary else 0)
    return (2, 0)


def _planned_change_immediate_order(change: PlannedDisplayChange) -> tuple[int, int]:
    if change.target.enabled and change.target.primary and not change.current.primary:
        return (0, 0)
    if change.target.enabled and not change.current.enabled:
        return (1, 0)
    if change.target.enabled and not change.target.primary and not change.current.primary:
        return (2, 0)
    if change.target.enabled:
        return (3, 0)
    return (4, 1 if change.current.primary else 0)


def _extend_desktop_with_displayswitch(
    result: ApplyResult, *, expected_enabled_count: int | None = None
) -> None:
    exe = _displayswitch_path()
    result.warnings.append(
        ApplyWarning(
            "one or more displays are disabled; running DisplaySwitch.exe /extend before applying profile"
        )
    )
    try:
        completed = subprocess.run(
            [str(exe), "/extend"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception as exc:
        result.errors.append(f"failed to run DisplaySwitch.exe /extend: {exc}")
        return
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        result.errors.append(
            f"DisplaySwitch.exe /extend failed with exit code {completed.returncode}{suffix}"
        )
        return
    if expected_enabled_count is None:
        _wait_seconds(_DISPLAYSWITCH_SETTLE_SECONDS)
        return
    # Adaptive settle: poll until the active display count reaches the
    # caller's expectation, capped at the legacy fixed wait. Lets us proceed
    # in 200-500ms on common topologies instead of the previous 2s flat.
    _poll_until(
        lambda: _enabled_count_reached(expected_enabled_count),
        timeout=_DISPLAYSWITCH_SETTLE_SECONDS,
        interval=0.1,
        initial_delay=0.1,
    )


def _enabled_count_reached(expected: int) -> int | None:
    try:
        active = list_displays()
    except Exception:
        return None
    count = sum(1 for d in active if d.enabled)
    return count if count >= expected else None


_MISSING_MONITOR_ERROR_PREFIX = "monitor not detected by Windows:"


def _has_missing_monitor_errors(errors: list[str]) -> bool:
    return any(_MISSING_MONITOR_ERROR_PREFIX in err for err in errors)


def _attempt_mst_topology_rescue(result: ApplyResult) -> bool:
    """Force a DisplayPort MST topology rescan.

    On DP daisy chains the MST hub can lose sink negotiation after rapid mode
    changes, making monitors vanish from Windows enumeration even though they
    are still physically connected. Triggering DisplaySwitch.exe /clone then
    /extend forces Windows to rebuild the DP topology, which re-discovers the
    missing sinks.

    Returns True if the rescue ran (regardless of whether DisplaySwitch
    succeeded). The caller should re-plan and check whether the missing
    monitors are now visible.
    """
    exe = _displayswitch_path()
    result.warnings.append(
        ApplyWarning(
            "monitor missing from Windows enumeration; attempting DP MST rescue (DisplaySwitch /clone -> /extend)"
        )
    )
    for mode in ("/clone", "/extend"):
        try:
            completed = subprocess.run(
                [str(exe), mode],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except Exception as exc:
            result.warnings.append(
                ApplyWarning(f"MST rescue: DisplaySwitch.exe {mode} failed: {exc}")
            )
            return True
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            suffix = f": {detail}" if detail else ""
            result.warnings.append(
                ApplyWarning(
                    f"MST rescue: DisplaySwitch.exe {mode} returned {completed.returncode}{suffix}"
                )
            )
        _wait_seconds(_DISPLAYSWITCH_SETTLE_SECONDS)
    return True


def _displayswitch_path() -> Path:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    return windir / "System32" / "DisplaySwitch.exe"


def _attempt_rollback(
    win32api: Any,
    win32con: Any,
    snapshot: list[DisplayState],
    result: ApplyResult,
) -> None:
    """Re-stage and commit the snapshot after a forward apply failed mid-flight.

    Why: ``CDS_UPDATEREGISTRY | CDS_NORESET`` writes to the Windows registry
    immediately. If we abort between the per-adapter staging and the final
    commit, the registry holds a half-applied configuration that will become
    visible after the next logon. This helper attempts a best-effort restore.
    """
    logger = app_logging.get_logger("display")
    if not snapshot:
        return
    rollback_result = ApplyResult()
    staged_any = False
    for original in snapshot:
        if not original.adapter_name:
            continue
        try:
            _stage_display_change(
                win32api,
                win32con,
                original.adapter_name,
                original,
                test_first=False,
                result=rollback_result,
            )
            staged_any = True
        except Exception as exc:
            logger.warning("rollback stage failed for %s: %s", original.device_id, exc)
    if not staged_any:
        result.errors.append(
            "rollback could not be staged; system may need manual recovery"
        )
        return
    try:
        commit_code = _change_display_settings_ex(win32api, None, None, 0)
    except Exception as exc:
        logger.warning("rollback commit raised: %s", exc)
        result.errors.append(
            f"rollback commit raised; system may need manual recovery: {exc}"
        )
        return
    success_code = getattr(win32con, "DISP_CHANGE_SUCCESSFUL", 0)
    if commit_code != success_code:
        result.errors.append(
            "rollback commit was rejected by Windows; system may need manual recovery "
            f"({_display_change_code_name(win32con, commit_code)})"
        )
        return
    result.warnings.append(
        ApplyWarning(
            "applied rollback to previous configuration after the change failed"
        )
    )


def _choose_display_for_target(
    candidates: list[DisplayState],
    target: DisplayState,
    *,
    matched_identities: set[str] | None = None,
) -> DisplayState | None:
    unmatched = [
        candidate
        for candidate in candidates
        if matched_identities is None
        or not (_display_match_aliases(candidate) & matched_identities)
    ]
    if not unmatched:
        return None

    physical_matches = [
        candidate
        for candidate in unmatched
        if display_identity_matches(candidate, target)
    ]
    if physical_matches:
        return _choose_preferred_display_candidate(physical_matches, target)

    if target.adapter_name:
        adapter_key = target.adapter_name.casefold()
        adapter_matches = [
            candidate
            for candidate in unmatched
            if candidate.adapter_name and candidate.adapter_name.casefold() == adapter_key
        ]
        adapter_matches = _safe_adapter_fallback_candidates(adapter_matches, target)
        if adapter_matches:
            return _choose_preferred_display_candidate(adapter_matches, target)

    return None


def _choose_preferred_display_candidate(
    candidates: list[DisplayState],
    target: DisplayState,
) -> DisplayState:
    active_candidates = [candidate for candidate in candidates if candidate.enabled]
    if target.adapter_name:
        adapter_key = target.adapter_name.casefold()
        for candidate in active_candidates:
            if candidate.adapter_name and candidate.adapter_name.casefold() == adapter_key:
                return candidate
    if active_candidates:
        return active_candidates[0]
    if target.adapter_name:
        adapter_key = target.adapter_name.casefold()
        for candidate in candidates:
            if candidate.adapter_name and candidate.adapter_name.casefold() == adapter_key:
                return candidate
    return candidates[0]


def _safe_adapter_fallback_candidates(
    candidates: list[DisplayState],
    target: DisplayState,
) -> list[DisplayState]:
    target_aliases = display_identity_aliases(target)
    if not target_aliases:
        return candidates
    return [
        candidate
        for candidate in candidates
        if not display_identity_aliases(candidate)
        or display_identity_matches(candidate, target)
    ]


def _has_conflicting_edid_identity(
    candidate: DisplayState | None,
    target: DisplayState,
) -> bool:
    if candidate is None:
        return False
    if not display_identity_aliases(candidate) or not display_identity_aliases(target):
        return False
    return not display_identity_matches(candidate, target)


def _conflicting_display_on_adapter(
    candidates: list[DisplayState],
    target: DisplayState,
) -> DisplayState | None:
    if not display_identity_aliases(target) or not target.adapter_name:
        return None
    adapter_key = target.adapter_name.casefold()
    for candidate in candidates:
        if not candidate.adapter_name or candidate.adapter_name.casefold() != adapter_key:
            continue
        if (
            display_identity_aliases(candidate)
            and not display_identity_matches(candidate, target)
        ):
            return candidate
    return None


def _display_label_for_error(display_state: DisplayState) -> str:
    label_parts = [
        part
        for part in (
            display_state.manufacturer,
            display_state.model,
            display_state.device_id,
        )
        if part
    ]
    return " ".join(label_parts) if label_parts else display_state.name


def _win32() -> tuple[Any, Any]:
    try:
        import win32api  # type: ignore[import-not-found,import-untyped]
        import win32con  # type: ignore[import-not-found,import-untyped]
    except ImportError as exc:
        raise RuntimeError("pywin32 is required on Windows") from exc
    return win32api, win32con


def _current_settings(win32api: Any, win32con: Any, adapter_name: str) -> Any | None:
    try:
        return win32api.EnumDisplaySettingsEx(
            adapter_name, getattr(win32con, "ENUM_CURRENT_SETTINGS", -1), 0
        )
    except Exception:
        return None


def _registry_settings(win32api: Any, win32con: Any, adapter_name: str) -> Any | None:
    try:
        return win32api.EnumDisplaySettingsEx(
            adapter_name, getattr(win32con, "ENUM_REGISTRY_SETTINGS", -2), 0
        )
    except Exception:
        return None


def _settings_for_change(win32api: Any, win32con: Any, adapter_name: str) -> Any | None:
    return _current_settings(win32api, win32con, adapter_name) or _registry_settings(
        win32api, win32con, adapter_name
    )


def _change_display_settings_ex(
    win32api: Any,
    device_name: str | None,
    settings: Any | None,
    flags: int,
) -> int:
    """Call pywin32's compact ChangeDisplaySettingsEx signature.

    The native WinAPI has five parameters, but pywin32 exposes only
    (deviceName, devMode, flags). Keeping this wrapper prevents accidental use
    of the C signature in apply paths.
    """
    return int(win32api.ChangeDisplaySettingsEx(device_name, settings, flags))


def _display_change_code_name(win32con: Any, code: int) -> str:
    for name in (
        "DISP_CHANGE_SUCCESSFUL",
        "DISP_CHANGE_RESTART",
        "DISP_CHANGE_FAILED",
        "DISP_CHANGE_BADMODE",
        "DISP_CHANGE_NOTUPDATED",
        "DISP_CHANGE_BADFLAGS",
        "DISP_CHANGE_BADPARAM",
        "DISP_CHANGE_BADDUALVIEW",
    ):
        if getattr(win32con, name, None) == code:
            return f"{name} ({code})"
    return f"code {code}"


def _target_summary(adapter_name: str, target: DisplayState) -> str:
    width, height = normalized_mode_size(target.width, target.height, target.orientation)
    mode = (
        f"{width or '?'}x{height or '?'}"
        f"@{target.refresh_hz or '?'}Hz"
    )
    return (
        f"adapter={adapter_name}, device_id={target.device_id}, enabled={target.enabled}, "
        f"mode={mode}, pos=({target.pos_x},{target.pos_y}), orientation={target.orientation}"
    )


def _get_position(settings: Any, axis: str) -> int:
    if settings is None:
        return 0
    candidates = (
        (f"Position_{axis}", f"Position{axis.upper()}"),
        (f"Position{axis.upper()}", f"Position_{axis.upper()}"),
    )
    for names in candidates:
        for name in names:
            if hasattr(settings, name):
                return int(getattr(settings, name))
    return 0


def _set_position(settings: Any, axis: str, value: int) -> None:
    for name in (f"Position_{axis}", f"Position{axis.upper()}", f"Position_{axis.upper()}"):
        try:
            setattr(settings, name, int(value))
            return
        except Exception:
            continue


def _validate_requested_state(state: SystemState, result: ApplyResult) -> None:
    primary_count = sum(1 for display in state.displays if display.primary)
    if primary_count > 1:
        result.errors.append("profile contains more than one primary display")
    for display in state.displays:
        if display.orientation not in VALID_ORIENTATIONS:
            result.errors.append(f"{display.device_id}: unsupported orientation {display.orientation}")
        for field_name in ("brightness", "contrast"):
            value = getattr(display, field_name)
            if value is not None and not 0 <= value <= 100:
                result.errors.append(f"{display.device_id}: {field_name} must be between 0 and 100")


def _stage_display_change(
    win32api: Any,
    win32con: Any,
    adapter_name: str,
    target: DisplayState,
    test_first: bool,
    result: ApplyResult,
    *,
    current: DisplayState | None = None,
    allow_failed_enable_test: bool = False,
    allow_failed_disable_test: bool = False,
    allow_failed_mode_test: bool = False,
    defer_commit: bool = True,
    persist_changes: bool = True,
) -> None:
    success_code = getattr(win32con, "DISP_CHANGE_SUCCESSFUL", 0)
    update_flags = getattr(win32con, "CDS_UPDATEREGISTRY", 1) if persist_changes else 0
    if defer_commit:
        update_flags |= getattr(win32con, "CDS_NORESET", 0x10000000)
    if target.primary:
        update_flags |= getattr(win32con, "CDS_SET_PRIMARY", 0x10)

    if not target.enabled:
        result.warnings.append(
            ApplyWarning(
                "disable display requested; Windows support depends on driver behavior",
                display_id=target.device_id,
            )
        )
        settings = _settings_for_change(win32api, win32con, adapter_name)
        if settings is None:
            result.errors.append(f"{target.device_id}: no current Windows mode available")
            return
        settings.PelsWidth = 0
        settings.PelsHeight = 0
        _set_position(settings, "x", 0)
        _set_position(settings, "y", 0)
        settings.Fields = (
            getattr(win32con, "DM_PELSWIDTH", 0x80000)
            | getattr(win32con, "DM_PELSHEIGHT", 0x100000)
            | getattr(win32con, "DM_POSITION", 0x20)
        )
        test_code = (
            _change_display_settings_ex(
                win32api, adapter_name, settings, getattr(win32con, "CDS_TEST", 0x2)
            )
            if test_first
            else success_code
        )
        if test_code != success_code:
            if _can_stage_after_failed_disable_test(
                win32con, test_code, allow_failed_disable_test
            ):
                result.warnings.append(
                    ApplyWarning(
                        "CDS_TEST failed while disabling the old primary display; staging the disable anyway",
                        display_id=target.device_id,
                        detail=(
                            f"{_display_change_code_name(win32con, test_code)}; "
                            f"{_target_summary(adapter_name, target)}"
                        ),
                    )
                )
            else:
                result.errors.append(
                    f"{target.device_id}: Windows rejected disable test "
                    f"{_display_change_code_name(win32con, test_code)}; "
                    f"{_target_summary(adapter_name, target)}"
                )
                return
        change_code = _change_display_settings_ex(win32api, adapter_name, settings, update_flags)
        if change_code != success_code:
            result.errors.append(
                f"{target.device_id}: Windows rejected disable "
                f"{_display_change_code_name(win32con, change_code)}; "
                f"{_target_summary(adapter_name, target)}"
            )
        return

    settings = _settings_for_change(win32api, win32con, adapter_name)
    if settings is None:
        result.errors.append(f"{target.device_id}: no current Windows mode available")
        return

    fields = 0
    force_full_mode = current is None or not current.enabled
    mode_width, mode_height = normalized_mode_size(
        target.width, target.height, target.orientation
    )
    if mode_width is not None and (force_full_mode or current.width != mode_width):
        settings.PelsWidth = int(mode_width)
        fields |= getattr(win32con, "DM_PELSWIDTH", 0x80000)
    if mode_height is not None and (force_full_mode or current.height != mode_height):
        settings.PelsHeight = int(mode_height)
        fields |= getattr(win32con, "DM_PELSHEIGHT", 0x100000)
    if target.refresh_hz is not None and (force_full_mode or current.refresh_hz != target.refresh_hz):
        settings.DisplayFrequency = int(target.refresh_hz)
        fields |= getattr(win32con, "DM_DISPLAYFREQUENCY", 0x400000)
    if force_full_mode or current.orientation != target.orientation:
        settings.DisplayOrientation = _ORIENTATION_TO_DEVMODE[target.orientation]
        fields |= getattr(win32con, "DM_DISPLAYORIENTATION", 0x80)
    position_changed = (
        force_full_mode
        or current.pos_x != target.pos_x
        or current.pos_y != target.pos_y
        or (target.primary and not current.primary)
    )
    if position_changed:
        _set_position(settings, "x", target.pos_x)
        _set_position(settings, "y", target.pos_y)
        fields |= getattr(win32con, "DM_POSITION", 0x20)
    settings.Fields = fields

    if test_first:
        test_code = _change_display_settings_ex(
            win32api, adapter_name, settings, getattr(win32con, "CDS_TEST", 0x2)
        )
        if test_code != success_code:
            if _can_stage_after_failed_enable_test(win32con, test_code, allow_failed_enable_test):
                result.warnings.append(
                    ApplyWarning(
                        "CDS_TEST failed while enabling a disabled display; staging the enable anyway",
                        display_id=target.device_id,
                        detail=(
                            f"{_display_change_code_name(win32con, test_code)}; "
                            f"{_target_summary(adapter_name, target)}"
                        ),
                    )
                )
            elif _can_stage_after_failed_mode_test(win32con, test_code, allow_failed_mode_test):
                result.warnings.append(
                    ApplyWarning(
                        "CDS_TEST failed during a multi-display change; staging the mode anyway",
                        display_id=target.device_id,
                        detail=(
                            f"{_display_change_code_name(win32con, test_code)}; "
                            f"{_target_summary(adapter_name, target)}"
                        ),
                    )
                )
            else:
                result.errors.append(
                    f"{target.device_id}: Windows rejected mode test "
                    f"{_display_change_code_name(win32con, test_code)}; "
                    f"{_target_summary(adapter_name, target)}"
                )
                return

    change_code = _change_display_settings_ex(win32api, adapter_name, settings, update_flags)
    if change_code != success_code:
        result.errors.append(
            f"{target.device_id}: Windows rejected mode change "
            f"{_display_change_code_name(win32con, change_code)}; "
            f"{_target_summary(adapter_name, target)}"
        )


def _can_stage_after_failed_enable_test(
    win32con: Any,
    test_code: int,
    allow_failed_enable_test: bool,
) -> bool:
    return allow_failed_enable_test and test_code == getattr(win32con, "DISP_CHANGE_FAILED", -1)


def _can_stage_after_failed_disable_test(
    win32con: Any,
    test_code: int,
    allow_failed_disable_test: bool,
) -> bool:
    return allow_failed_disable_test and test_code == getattr(win32con, "DISP_CHANGE_FAILED", -1)


def _can_stage_after_failed_mode_test(
    win32con: Any,
    test_code: int,
    allow_failed_mode_test: bool,
) -> bool:
    return allow_failed_mode_test and test_code == getattr(win32con, "DISP_CHANGE_FAILED", -1)


def get_monitor_audio_volume_percent(
    display_state: DisplayState | None = None,
) -> int | None:
    """Return the audio volume of a DDC/CI monitor responding to VCP 0x62."""
    return _ddcci_backend.get_audio_volume_percent(display_state)


def set_monitor_audio_volume_percent(
    percent: int,
    display_state: DisplayState | None = None,
) -> int | None:
    """Set the audio volume on a DDC/CI monitor that accepts VCP 0x62."""
    return _ddcci_backend.set_audio_volume_percent(percent, display_state)


