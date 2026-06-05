"""Inventory snapshot exported for xtray to consume.

XTray runs without Computer Manager installed. When it does, it reads the
JSON snapshot written here to populate the tray's adapter/drive/display
panels in read-only mode. Writing always uses the new ComputerManager
AppData path (`paths.inventory_path()`).

The snapshot is built by `build_snapshot()` (pure, accepts pre-fetched
data — easy to test) and persisted by `write_inventory()` (calls the
services to collect live data first, Windows-only).
"""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import paths
from .adapter_manager import NetworkAdapter
from .display_manager import profiles as display_profiles
from .drive_manager import DriveInfo

SCHEMA_VERSION = 1


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _serialize(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _serialize(val) for key, val in asdict(value).items()}
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(val) for key, val in value.items()}
    return value


def build_snapshot(
    *,
    adapters: Iterable[NetworkAdapter] = (),
    drives: Iterable[DriveInfo] = (),
    profiles: Iterable[str] | None = None,
    displays: Iterable[Any] = (),
    audio_sources: Iterable[Any] = (),
) -> dict[str, Any]:
    """Build the inventory dict from pre-fetched data.

    All inputs are optional — empty collections produce a well-formed snapshot
    with empty lists. This keeps the function safe to call from tests without
    touching Windows APIs.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": _now_utc(),
        "adapters": [_serialize(adapter) for adapter in adapters],
        "drives": [_serialize(drive) for drive in drives],
        "displays": [_serialize(display) for display in displays],
        "audio_sources": [_serialize(source) for source in audio_sources],
        "profiles": sorted(profiles) if profiles is not None else display_profiles.list_profiles(),
    }


def capture_snapshot() -> dict[str, Any]:
    """Collect live data from the local OS and build a snapshot.

    Windows-only: invokes PowerShell-backed services. Use `build_snapshot()`
    directly in unit tests.
    """
    from .adapter_manager import AdapterService
    from .audio_manager import list_audio_sources
    from .display_manager.inventory import collect_display_inventory
    from .drive_manager import DriveService

    try:
        adapters = AdapterService().list_adapters()
    except Exception:
        adapters = []
    try:
        drives = DriveService().list_drives()
    except Exception:
        drives = []
    try:
        displays = collect_display_inventory()
    except Exception:
        displays = []
    try:
        audio_sources = list_audio_sources()
    except Exception:
        audio_sources = []

    return build_snapshot(
        adapters=adapters,
        drives=drives,
        displays=displays,
        audio_sources=audio_sources,
    )


def write_inventory(path: Path | None = None) -> Path:
    """Capture a live snapshot and persist it atomically."""
    target = path or paths.inventory_path()
    snapshot = capture_snapshot()
    _atomic_write_json(target, snapshot)
    return target


def read_inventory(path: Path | None = None) -> dict[str, Any] | None:
    """Read a previously-exported snapshot. Returns None if the file is missing
    or malformed (callers fall back to a no-Computer-Manager mode)."""
    target = path or paths.inventory_path()
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
