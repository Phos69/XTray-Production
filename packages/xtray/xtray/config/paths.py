"""Application configuration, data, profile, and log paths."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "XTray"
LEGACY_APP_NAME = "DisplayManager"
LEGACY_APP_NAMES: tuple[str, ...] = ("DisplayManager", "ComputerManager")

ENV_API_TOKEN = "XTRAY_API_TOKEN"
ENV_APPDATA = "XTRAY_APPDATA"
ENV_CONFIG_DIR = "XTRAY_CONFIG_DIR"
ENV_LOCALAPPDATA = "XTRAY_LOCALAPPDATA"
ENV_PROFILES_DIR = "XTRAY_PROFILES_DIR"
ENV_UNSAFE_NO_AUTH = "XTRAY_UNSAFE_NO_AUTH"
LEGACY_ENV_API_TOKEN = "DISPLAYMANAGER_API_TOKEN"
LEGACY_ENV_APPDATA = "DISPLAYMANAGER_APPDATA"
LEGACY_ENV_CONFIG_DIR = "DISPLAYMANAGER_CONFIG_DIR"
LEGACY_ENV_LOCALAPPDATA = "DISPLAYMANAGER_LOCALAPPDATA"
LEGACY_ENV_UNSAFE_NO_AUTH = "DISPLAYMANAGER_UNSAFE_NO_AUTH"


def config_dir() -> Path:
    override = os.environ.get(ENV_CONFIG_DIR) or os.environ.get(LEGACY_ENV_CONFIG_DIR)
    if override:
        return Path(override)
    root = (
        os.environ.get(ENV_APPDATA)
        or os.environ.get(LEGACY_ENV_APPDATA)
        or os.environ.get("APPDATA")
    )
    if root:
        return Path(root) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def data_dir() -> Path:
    return config_dir()


def profiles_dir() -> Path:
    override = os.environ.get(ENV_PROFILES_DIR)
    path = Path(override) if override else data_dir() / "profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    root_value = (
        os.environ.get(ENV_LOCALAPPDATA)
        or os.environ.get(LEGACY_ENV_LOCALAPPDATA)
        or os.environ.get("LOCALAPPDATA")
    )
    root = Path(root_value) if root_value else Path.home() / ".local" / "state"
    path = root / APP_NAME / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return config_dir() / "settings.json"


def legacy_settings_path() -> Path:
    return legacy_settings_paths()[0]


def legacy_settings_paths() -> list[Path]:
    """Pre-rename settings paths to search (DisplayManager, ComputerManager)."""
    root = os.environ.get("APPDATA")
    if root:
        base = Path(root)
    else:
        base = Path.home() / ".config"
    return [base / name / "settings.json" for name in LEGACY_APP_NAMES]
