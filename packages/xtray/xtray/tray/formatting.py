"""Text formatting helpers for apply results and display descriptions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core import app_logging
from ..services.display import display_inventory

try:
    from computer_manager.display_manager import messages
except ImportError:

    def _format_apply_result_summary(result: Any) -> str:
        data = result.to_dict()
        errors = data.get("errors") or []
        warnings = data.get("warnings") or []
        if errors:
            return "; ".join(str(error) for error in errors)
        if warnings:
            return "; ".join(str(warning.get("message", warning)) for warning in warnings)
        return "Profile applied." if data.get("applied") else "Profile not applied."

else:
    _format_apply_result_summary = messages.format_apply_result_summary


@dataclass(frozen=True)
class ApplyMessage:
    ok: bool
    title: str
    message: str


def apply_message(name: str, result: Any) -> ApplyMessage:
    data = result.to_dict()
    text = _format_apply_result_summary(result)
    ok = bool(data.get("ok"))
    title = "Profilo applicato" if data.get("applied") else "Profilo non applicato"
    return ApplyMessage(ok=ok, title=title, message=text)


def _log_apply_result(name: str, result: Any) -> None:
    data = result.to_dict()
    logger = app_logging.get_logger("tray")
    logger.info(
        "apply profile %s completed: applied=%s ok=%s warnings=%s errors=%s",
        name,
        data.get("applied"),
        data.get("ok"),
        len(data.get("warnings") or []),
        len(data.get("errors") or []),
    )
    for warning in data.get("warnings") or []:
        logger.warning(
            "apply profile %s warning%s: %s%s",
            name,
            _display_suffix(warning.get("display_id")),
            warning.get("message", ""),
            _detail_suffix(warning.get("detail")),
        )
    for error in data.get("errors") or []:
        logger.error("apply profile %s error: %s", name, error)


def _display_suffix(display_id: str | None) -> str:
    return f" [{display_id}]" if display_id else ""


def _detail_suffix(detail: str | None) -> str:
    return f": {detail}" if detail else ""


def _display_short_name(display_state: Any) -> str:
    title = display_inventory.display_title(display_state).strip()
    return title or getattr(display_state, "name", None) or getattr(
        display_state,
        "device_id",
        "Display",
    )


def _display_inventory_detail(item: Any) -> str:
    display_state = item.display
    parts = [
        "Enabled" if item.enabled else "Disabled",
        "Available" if item.available else "Saved profile",
        _display_resolution_label(display_state),
        _display_refresh_label(display_state),
    ]
    if getattr(display_state, "primary", False):
        parts.append("Primary")
    return " - ".join(part for part in parts if part)


def _display_resolution_label(display_state: Any) -> str:
    width = getattr(display_state, "width", None)
    height = getattr(display_state, "height", None)
    if width and height:
        return f"{int(width)}x{int(height)}"
    return "Resolution unknown"


def _display_refresh_label(display_state: Any) -> str:
    refresh_hz = getattr(display_state, "refresh_hz", None)
    if not refresh_hz:
        return "Refresh unknown"
    value = float(refresh_hz)
    label = f"{int(value)}" if value.is_integer() else f"{value:g}"
    return f"{label} Hz"
