"""JSON settings store and legacy DisplayManager/ComputerManager migration."""
from __future__ import annotations

import json
from typing import Any

from ..core.config_base import MIGRATED_SETTINGS_KEYS
from .paths import legacy_settings_paths, settings_path
from .validators import ConfigError


def migrate_legacy_settings() -> bool:
    """Copy tray/web settings from legacy storages once, leaving the old files intact.

    Sources searched in order: DisplayManager, ComputerManager (in %APPDATA%).
    The first legacy file that yields a non-empty migration wins. The legacy
    file is left untouched as a fallback read.
    """
    target = settings_path()
    if target.exists():
        return False
    for source in legacy_settings_paths():
        if not source.exists():
            continue
        try:
            legacy = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(legacy, dict):
            continue
        migrated = {key: legacy[key] for key in MIGRATED_SETTINGS_KEYS if key in legacy}
        if not migrated:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(migrated, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return True
    return False


def load_settings() -> dict[str, Any]:
    path = settings_path()
    if not path.exists():
        migrate_legacy_settings()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid settings file: {path}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"settings file must contain a JSON object: {path}")
    return data


def save_settings(settings: dict[str, Any]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
