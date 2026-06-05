"""Filesystem paths owned by Computer Manager.

Writes always go to the new `ComputerManager` AppData directory. Reads fall
back to the legacy `DisplayManager` directory when a file is not present in
the new location — this preserves user profiles created before the rename
without forcing a migration step.

Env vars (override the resolved paths, mostly for tests):

- COMPUTERMANAGER_APPDATA, COMPUTERMANAGER_CONFIG_DIR, COMPUTERMANAGER_PROFILES_DIR
- DISPLAYMANAGER_APPDATA, DISPLAYMANAGER_CONFIG_DIR, DISPLAYMANAGER_PROFILES_DIR
  (legacy read fallback)
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "ComputerManager"
LEGACY_APP_NAME = "DisplayManager"

ENV_APPDATA = "COMPUTERMANAGER_APPDATA"
ENV_CONFIG_DIR = "COMPUTERMANAGER_CONFIG_DIR"
ENV_PROFILES_DIR = "COMPUTERMANAGER_PROFILES_DIR"

LEGACY_ENV_APPDATA = "DISPLAYMANAGER_APPDATA"
LEGACY_ENV_CONFIG_DIR = "DISPLAYMANAGER_CONFIG_DIR"
LEGACY_ENV_PROFILES_DIR = "DISPLAYMANAGER_PROFILES_DIR"


def _config_dir(app_name: str, env_config: str, env_appdata: str) -> Path:
    override = os.environ.get(env_config)
    if override:
        return Path(override)
    root = os.environ.get(env_appdata) or os.environ.get("APPDATA")
    if root:
        return Path(root) / app_name
    return Path.home() / ".config" / app_name


def config_dir() -> Path:
    return _config_dir(APP_NAME, ENV_CONFIG_DIR, ENV_APPDATA)


def legacy_config_dir() -> Path | None:
    """Legacy DisplayManager config dir. Returns None when nothing exists there."""
    path = _config_dir(LEGACY_APP_NAME, LEGACY_ENV_CONFIG_DIR, LEGACY_ENV_APPDATA)
    return path if path.exists() else None


def profiles_dir() -> Path:
    """Write target for profiles. Created on access."""
    override = os.environ.get(ENV_PROFILES_DIR)
    path = Path(override) if override else config_dir() / "profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def legacy_profiles_dir() -> Path | None:
    """Legacy DisplayManager profile read path. Returns None if absent."""
    override = os.environ.get(LEGACY_ENV_PROFILES_DIR)
    if override:
        path = Path(override)
        return path if path.exists() else None
    legacy_cfg = legacy_config_dir()
    if legacy_cfg is None:
        return None
    path = legacy_cfg / "profiles"
    return path if path.exists() else None


def profile_search_paths() -> list[Path]:
    """Dirs to consult when locating an existing profile by name.

    Order: new path first, legacy path second. Writing always targets
    `profiles_dir()` (the first entry); the legacy dir is read-only.
    """
    paths = [profiles_dir()]
    legacy = legacy_profiles_dir()
    if legacy is not None:
        paths.append(legacy)
    return paths


def find_existing_profile(name: str) -> Path | None:
    """Return the first existing path for `<name>.json`, searching all
    profile directories. None when no copy exists.
    """
    filename = f"{name}.json"
    for directory in profile_search_paths():
        candidate = directory / filename
        if candidate.exists():
            return candidate
    return None


def inventory_path() -> Path:
    """Snapshot exported for xtray to consume without importing computer_manager."""
    return config_dir() / "computer_inventory.json"
