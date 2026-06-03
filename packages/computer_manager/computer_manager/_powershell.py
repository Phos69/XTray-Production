"""Shared PowerShell and value coercion helpers for Windows services."""
from __future__ import annotations

import json
import subprocess
from typing import Any


def run_powershell_json(script: str, error_cls: type[Exception]) -> Any:
    output = run_powershell(script, error_cls)
    if not output.strip():
        return {}
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise error_cls("PowerShell returned invalid JSON") from exc


def run_powershell(script: str, error_cls: type[Exception]) -> str:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=hidden_subprocess_creationflags(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "PowerShell command failed").strip()
        raise error_cls(detail)
    return result.stdout


def ps_quote(value: str | None) -> str:
    text = "" if value is None else str(value)
    return "'" + text.replace("'", "''") + "'"


def hidden_subprocess_creationflags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
