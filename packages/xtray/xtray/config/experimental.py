"""Private experimental feature flags.

These settings are deliberately local-user toggles, not public release
contracts. Production builds default everything off and may omit the matching
implementation modules entirely.
"""
from __future__ import annotations

import importlib.util
from typing import Any

from ..core.config_base import EXPERIMENTAL_FEATURES_KEY
from .store import load_settings, save_settings
from .validators import ConfigError, bool_setting

EXPERIMENTAL_FEATURE_KEYS = frozenset({"network_manager_full"})


def default_experimental_features() -> dict[str, bool]:
    return {"network_manager_full": False}


def normalize_experimental_features(value: Any) -> dict[str, bool]:
    if value is None:
        raw: dict[str, Any] = {}
    elif isinstance(value, dict):
        raw = value
    else:
        raise ConfigError("experimental_features must be an object")

    defaults = default_experimental_features()
    return {
        key: bool_setting(raw.get(key, default), f"experimental_features.{key}")
        for key, default in defaults.items()
    }


def get_experimental_features() -> dict[str, bool]:
    return normalize_experimental_features(load_settings().get(EXPERIMENTAL_FEATURES_KEY))


def set_experimental_features(**updates: Any) -> dict[str, bool]:
    unknown = sorted(set(updates) - EXPERIMENTAL_FEATURE_KEYS)
    if unknown:
        raise ConfigError(f"unknown experimental feature: {', '.join(unknown)}")
    features = {**get_experimental_features(), **updates}
    features = normalize_experimental_features(features)
    settings = load_settings()
    settings[EXPERIMENTAL_FEATURES_KEY] = features
    save_settings(settings)
    return features


def experimental_feature_enabled(key: str) -> bool:
    return bool(get_experimental_features().get(key, False))


def experimental_feature_available(key: str) -> bool:
    if key == "network_manager_full":
        return importlib.util.find_spec("network_manager.experimental_app") is not None
    return False
