"""DDC/CI monitor matching and apply helpers."""
from __future__ import annotations

import re
from typing import Any

from xtray.core import app_logging

from .models import ApplyResult, ApplyWarning, DisplayState, SystemState

_DDC_IDENTITY_FIELDS = (
    "edid_hash",
    "serial_number",
    "serial",
    "model",
    "model_name",
    "manufacturer_id",
    "manufacturer",
    "product_code",
    "device_id",
    "name",
    "description",
    "display_name",
)

_VCP_AUDIO_VOLUME = 0x62


def get_audio_volume_percent(target: DisplayState | None = None) -> int | None:
    """Return audio volume for a DDC/CI monitor responding to VCP 0x62.

    When ``target`` is provided, only the matching physical monitor is queried.
    When omitted, the first responding monitor is used for backward
    compatibility. Returns None when monitorcontrol is missing, no monitor responds, or the
    monitor reports a max of zero. Failures are per-monitor and silenced at
    debug level so a non-TV monitor in the chain does not poison the result.
    """
    monitors = _enumerate_ddc_monitors()
    if monitors is None:
        return None
    if target is not None:
        monitor = find_ddc_monitor(target, monitors, set())
        return _try_get_monitor_volume(monitor) if monitor is not None else None
    for monitor in monitors:
        percent = _try_get_monitor_volume(monitor)
        if percent is not None:
            return percent
    return None


def set_audio_volume_percent(percent: int, target: DisplayState | None = None) -> int | None:
    """Set audio volume on a DDC/CI monitor that accepts VCP 0x62.

    Returns the applied 0-100 value, or None when no monitor accepted the
    command. When ``target`` is omitted, the first accepting monitor is used.
    """
    if not 0 <= percent <= 100:
        raise ValueError("audio volume percent must be between 0 and 100")
    monitors = _enumerate_ddc_monitors()
    if monitors is None:
        return None
    if target is not None:
        monitor = find_ddc_monitor(target, monitors, set())
        if monitor is None:
            return None
        return percent if _try_set_monitor_volume(monitor, percent) else None
    for monitor in monitors:
        if _try_set_monitor_volume(monitor, percent):
            return percent
    return None


def _enumerate_ddc_monitors() -> list[Any] | None:
    try:
        import monitorcontrol  # type: ignore[import-not-found,import-untyped]
    except ImportError:
        return None
    try:
        return list(monitorcontrol.get_monitors())
    except Exception as exc:
        app_logging.get_logger("display").debug(
            "could not enumerate DDC/CI monitors for audio: %s", exc, exc_info=True
        )
        return None


def _try_get_monitor_volume(monitor: Any) -> int | None:
    try:
        with monitor:
            value = monitor.get_vcp_feature(_VCP_AUDIO_VOLUME)
    except Exception as exc:
        app_logging.get_logger("display").debug(
            "DDC/CI audio volume read failed on %s: %s",
            type(monitor).__name__,
            exc,
            exc_info=True,
        )
        return None
    current, maximum = _vcp_volume_values(value)
    if current is None or maximum is None or maximum <= 0:
        return None
    scaled = int(round(current * 100 / maximum))
    return max(0, min(100, scaled))


def _try_set_monitor_volume(monitor: Any, percent: int) -> bool:
    try:
        with monitor:
            value = monitor.get_vcp_feature(_VCP_AUDIO_VOLUME)
            current, maximum = _vcp_volume_values(value)
            if maximum is None or maximum <= 0:
                return False
            scaled = int(round(percent * maximum / 100))
            scaled = max(0, min(maximum, scaled))
            monitor.set_vcp_feature(_VCP_AUDIO_VOLUME, scaled)
    except Exception as exc:
        app_logging.get_logger("display").debug(
            "DDC/CI audio volume set failed on %s: %s",
            type(monitor).__name__,
            exc,
            exc_info=True,
        )
        return False
    return True


def _vcp_volume_values(value: Any) -> tuple[int | None, int | None]:
    if value is None:
        return None, None
    raw_current = getattr(value, "value", None)
    raw_max = getattr(value, "max", None)
    if raw_current is None and isinstance(value, tuple) and len(value) >= 2:
        raw_current, raw_max = value[0], value[1]
    elif raw_current is None and isinstance(value, int):
        raw_current = value
    current = raw_current if isinstance(raw_current, int) else None
    maximum = raw_max if isinstance(raw_max, int) else None
    return current, maximum


def apply_ddcci(state: SystemState, result: ApplyResult) -> None:
    targets = [
        display
        for display in state.displays
        if display.brightness is not None
        or display.contrast is not None
        or display.input_source is not None
    ]
    if not targets:
        return
    try:
        import monitorcontrol  # type: ignore[import-not-found,import-untyped]
    except ImportError:
        result.warnings.append(ApplyWarning("monitorcontrol is not installed; DDC/CI skipped"))
        return

    try:
        monitors = monitorcontrol.get_monitors()
    except Exception as exc:
        result.warnings.append(ApplyWarning("could not enumerate DDC/CI monitors", detail=str(exc)))
        return

    used: set[int] = set()
    for target in targets:
        monitor = find_ddc_monitor(target, monitors, used)
        if monitor is None:
            result.warnings.append(
                ApplyWarning(
                    "no matching DDC/CI monitor found; brightness/contrast/input skipped",
                    display_id=target.device_id,
                )
            )
            continue
        used.add(id(monitor))
        try:
            with monitor:
                if target.brightness is not None:
                    monitor.set_luminance(target.brightness)
                if target.contrast is not None:
                    monitor.set_contrast(target.contrast)
                if target.input_source is not None:
                    if hasattr(monitor, "set_input_source"):
                        monitor.set_input_source(target.input_source)
                    else:
                        result.warnings.append(
                            ApplyWarning(
                                "monitorcontrol backend cannot set input source",
                                display_id=target.device_id,
                            )
                        )
        except Exception as exc:
            result.warnings.append(
                ApplyWarning(
                    "DDC/CI operation failed",
                    display_id=target.device_id,
                    detail=str(exc),
                )
            )


def find_ddc_monitor(target: DisplayState, monitors: list[Any], used: set[int]) -> Any | None:
    best_monitor = None
    best_score = 0
    for monitor in monitors:
        if id(monitor) in used:
            continue
        score = ddc_monitor_match_score(target, monitor)
        if score > best_score:
            best_score = score
            best_monitor = monitor
    return best_monitor if best_score > 0 else None


def ddc_monitor_match_score(target: DisplayState, monitor: Any) -> int:
    identity = ddc_monitor_identity_values(monitor)
    if has_conflicting_ddc_identity(target, identity):
        return 0

    score = 0
    if ddc_value_matches(target.edid_hash, identity["edid_hash"]):
        score = max(score, 100)
    if ddc_value_matches(target.serial_number, identity["serial_number"]):
        score = max(score, 80)
    if ddc_value_matches(target.model, identity["model"]):
        score = max(score, 55)
    if (
        ddc_value_matches(target.model, identity["model"])
        and (
            ddc_value_matches(target.manufacturer_id, identity["manufacturer_id"])
            or ddc_value_matches(target.manufacturer, identity["manufacturer"])
            or ddc_value_matches(target.product_code, identity["product_code"])
        )
    ):
        score = max(score, 70)

    labels = identity["label"]
    if ddc_compact_value_matches(target.edid_hash, labels):
        score = max(score, 90)
    if ddc_compact_value_matches(target.serial_number, labels):
        score = max(score, 75)
    if ddc_compact_value_matches(target.model, labels):
        score = max(score, 45)
    if ddc_compact_value_matches(target.product_code, labels) and (
        ddc_compact_value_matches(target.manufacturer_id, labels)
        or ddc_compact_value_matches(target.manufacturer, labels)
    ):
        score = max(score, 60)

    if not target_has_strong_ddc_identity(target):
        if ddc_compact_value_matches(target.device_id, labels):
            score = max(score, 20)
        if ddc_compact_value_matches(target.name, labels):
            score = max(score, 10)
    return score


def ddc_monitor_identity_values(monitor: Any) -> dict[str, set[str]]:
    values: dict[str, set[str]] = {
        "edid_hash": set(),
        "serial_number": set(),
        "model": set(),
        "manufacturer_id": set(),
        "manufacturer": set(),
        "product_code": set(),
        "device_id": set(),
        "label": set(),
    }
    add_ddc_identity_value(values["label"], safe_ddc_label(monitor))
    for field_name in _DDC_IDENTITY_FIELDS:
        collect_ddc_identity_attr(values, monitor, field_name)
    for mapping_name in ("identity", "metadata", "edid"):
        mapping = safe_ddc_attr(monitor, mapping_name)
        if isinstance(mapping, dict):
            for key, value in mapping.items():
                collect_ddc_identity_value(values, str(key), value)
    return values


def collect_ddc_identity_attr(
    values: dict[str, set[str]],
    monitor: Any,
    field_name: str,
) -> None:
    value = safe_ddc_attr(monitor, field_name)
    if value is None or callable(value):
        return
    collect_ddc_identity_value(values, field_name, value)


def collect_ddc_identity_value(
    values: dict[str, set[str]],
    field_name: str,
    value: Any,
) -> None:
    category = ddc_identity_category(field_name)
    if category is None:
        add_ddc_identity_value(values["label"], value)
        return
    add_ddc_identity_value(values[category], value)


def ddc_identity_category(field_name: str) -> str | None:
    normalized = field_name.casefold()
    if normalized in {"edid_hash", "edidhash"}:
        return "edid_hash"
    if normalized in {"serial", "serial_number", "serialnumber"}:
        return "serial_number"
    if normalized in {"model", "model_name", "modelname"}:
        return "model"
    if normalized in {"manufacturer_id", "manufacturerid", "mfg", "mfg_id"}:
        return "manufacturer_id"
    if normalized in {"manufacturer", "vendor"}:
        return "manufacturer"
    if normalized in {"product_code", "productcode", "product_id", "productid"}:
        return "product_code"
    if normalized in {"device_id", "deviceid"}:
        return "device_id"
    return None


def safe_ddc_attr(monitor: Any, field_name: str) -> Any:
    try:
        return getattr(monitor, field_name, None)
    except Exception as exc:
        app_logging.get_logger("display").debug(
            "could not read DDC/CI monitor attribute %s from %s: %s",
            field_name,
            type(monitor).__name__,
            exc,
            exc_info=True,
        )
        return None


def safe_ddc_label(monitor: Any) -> str:
    try:
        return str(monitor)
    except Exception as exc:
        app_logging.get_logger("display").debug(
            "could not format DDC/CI monitor label for %s: %s",
            type(monitor).__name__,
            exc,
            exc_info=True,
        )
        return type(monitor).__name__


def add_ddc_identity_value(bucket: set[str], value: Any) -> None:
    normalized = normalize_ddc_identity(value)
    if normalized:
        bucket.add(normalized)


def has_conflicting_ddc_identity(
    target: DisplayState,
    identity: dict[str, set[str]],
) -> bool:
    return (
        ddc_value_conflicts(target.edid_hash, identity["edid_hash"])
        or ddc_value_conflicts(target.serial_number, identity["serial_number"])
    )


def target_has_strong_ddc_identity(target: DisplayState) -> bool:
    return any(
        (
            target.edid_hash,
            target.serial_number,
            target.model and (target.manufacturer_id or target.manufacturer or target.product_code),
        )
    )


def ddc_value_matches(value: str | None, candidates: set[str]) -> bool:
    normalized = normalize_ddc_identity(value)
    return bool(normalized and normalized in candidates)


def ddc_value_conflicts(value: str | None, candidates: set[str]) -> bool:
    normalized = normalize_ddc_identity(value)
    return bool(normalized and candidates and normalized not in candidates)


def ddc_compact_value_matches(value: str | None, labels: set[str]) -> bool:
    compact = compact_ddc_identity(value)
    if not compact:
        return False
    return any(compact in compact_ddc_identity(label) for label in labels)


def normalize_ddc_identity(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().casefold()
    return " ".join(text.split())


def compact_ddc_identity(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_ddc_identity(value))
