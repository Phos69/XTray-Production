"""Pure user-facing text formatting for shared apply results.

Lives outside ``profiles``/``gui``/``tray`` so it can be imported by any surface
without dragging in Qt or WinAPI dependencies.
"""
from __future__ import annotations

from typing import Any


def format_apply_result(result: Any) -> str:
    """Render a ``display.ApplyResult`` as a multi-line message for the user."""
    data = result.to_dict()
    if data["ok"]:
        status = "Profile applied."
    elif data.get("applied"):
        status = "Profile partially applied."
    else:
        status = "Profile was not applied."
    lines = [status]
    if data.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for warning in data["warnings"]:
            display_id = f" [{warning['display_id']}]" if warning.get("display_id") else ""
            detail = f": {warning['detail']}" if warning.get("detail") else ""
            lines.append(f"- {warning['message']}{display_id}{detail}")
    if data.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for error in data["errors"]:
            lines.append(f"- {error}")
    return "\n".join(lines)


def format_apply_result_summary(result: Any) -> str:
    """Render a compact tray-safe summary without warning/error details."""
    data = result.to_dict()
    status = "Profilo applicato" if data.get("applied") else "Profilo non applicato"
    return format_profile_apply_summary(
        status,
        warning_count=len(data.get("warnings") or []),
        error_count=len(data.get("errors") or []),
    )


def format_profile_apply_summary(
    status: str,
    *,
    warning_count: int = 0,
    error_count: int = 0,
) -> str:
    counts = []
    if warning_count:
        counts.append(f"{warning_count} warning")
    if error_count:
        label = "errore" if error_count == 1 else "errori"
        counts.append(f"{error_count} {label}")
    if not counts:
        return status
    return f"{status}, {_join_italian_counts(counts)}"


def _join_italian_counts(counts: list[str]) -> str:
    if len(counts) == 1:
        return counts[0]
    return " e ".join(counts)
