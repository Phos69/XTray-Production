"""User-level app settings: router IP, username, optional saved password.

Persisted as the ``network_manager`` key inside the shared XTray settings
file (``%APPDATA%\\XTray\\settings.json``) so XTray, Computer Manager and
Network Manager all read from the same store. Legacy
``%APPDATA%\\Network_Manager\\settings.json`` is read once on the first
load and merged in automatically.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from xtray import config as xtray_config

try:
    import keyring
except ImportError:
    keyring = None  # type: ignore

KEYRING_SERVICE = "Network_Manager"
NETWORK_MANAGER_SETTINGS_KEY = "network_manager"


@dataclass
class SwitchProfileSettings:
    id: str
    label: str
    host: str
    vendor: str
    username: str = "admin"


_DEFAULT_SWITCH_PROFILES = (
    SwitchProfileSettings(
        id="switch-1",
        label="Switch .1",
        host="192.168.1.1",
        vendor="technicolor_agmy2020",
    ),
    SwitchProfileSettings(
        id="old-2",
        label="Vecchio .2",
        host="192.168.1.2",
        vendor="huawei_dn8245x6",
    ),
    SwitchProfileSettings(
        id="ap-3",
        label="AP .3",
        host="192.168.1.3",
        vendor="netgear_ex6120",
    ),
    SwitchProfileSettings(
        id="new-4",
        label="Nuovo .4",
        host="192.168.1.4",
        vendor="technicolor_agmy2020",
    ),
    SwitchProfileSettings(
        id="extender-5",
        label="Extender .5",
        host="192.168.1.5",
        vendor="tplink_tl_wa850re",
    ),
)


def default_switch_profiles(username: str = "admin") -> list[SwitchProfileSettings]:
    return [
        SwitchProfileSettings(
            id=profile.id,
            label=profile.label,
            host=profile.host,
            vendor=profile.vendor,
            username=username,
        )
        for profile in _DEFAULT_SWITCH_PROFILES
    ]


def _switch_profile_from_dict(
    raw: dict[str, Any],
    fallback: SwitchProfileSettings,
    username: str,
) -> SwitchProfileSettings:
    return SwitchProfileSettings(
        id=str(raw.get("id") or fallback.id),
        label=str(raw.get("label") or fallback.label),
        host=str(raw.get("host") or fallback.host),
        vendor=str(raw.get("vendor") or fallback.vendor),
        username=str(raw.get("username") or username or fallback.username),
    )


def _extra_switch_profile_from_dict(
    raw: dict[str, Any],
    username: str,
) -> SwitchProfileSettings | None:
    profile_id = str(raw.get("id") or "")
    host = str(raw.get("host") or "")
    vendor = str(raw.get("vendor") or "")
    if not profile_id or not host or not vendor:
        return None
    return SwitchProfileSettings(
        id=profile_id,
        label=str(raw.get("label") or profile_id),
        host=host,
        vendor=vendor,
        username=str(raw.get("username") or username or "admin"),
    )


def _normalize_switch_profiles(
    raw_switches: Any,
    legacy_username: str,
) -> list[SwitchProfileSettings]:
    defaults = default_switch_profiles(legacy_username)
    if not isinstance(raw_switches, list):
        return defaults

    by_id = {
        str(item.get("id")): item
        for item in raw_switches
        if isinstance(item, dict) and item.get("id")
    }
    default_ids = {profile.id for profile in defaults}
    extra_by_id = {
        str(item.get("id")): item
        for item in raw_switches
        if isinstance(item, dict)
        and item.get("id")
        and str(item.get("id")) not in default_ids
    }
    normalized = [
        _switch_profile_from_dict(by_id.get(default.id, {}), default, legacy_username)
        for default in defaults
    ]
    normalized.extend(
        profile
        for profile in (
            _extra_switch_profile_from_dict(raw, legacy_username)
            for raw in extra_by_id.values()
        )
        if profile is not None
    )
    return normalized


def _legacy_settings_file() -> Path:
    """Pre-unification %APPDATA%/Network_Manager/settings.json, if present."""
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "Network_Manager" / "settings.json"


def _load_legacy_settings() -> dict[str, Any] | None:
    """Read the legacy Network_Manager/settings.json once, returning a dict or None."""
    path = _legacy_settings_file()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


@dataclass
class AppSettings:
    host: str = "192.168.1.1"
    scheme: str = "http"
    username: str = "admin"
    vendor: str = "technicolor_agmy2020"
    remember_password: bool = False
    switches: list[SwitchProfileSettings] = field(default_factory=default_switch_profiles)

    @classmethod
    def load(cls) -> AppSettings:
        try:
            xtray_settings = xtray_config.load_settings()
        except xtray_config.ConfigError:
            xtray_settings = {}
        data = xtray_settings.get(NETWORK_MANAGER_SETTINGS_KEY)
        if not isinstance(data, dict):
            legacy = _load_legacy_settings()
            if legacy is None:
                return cls()
            data = legacy
        legacy_username = str(data.get("username") or cls.username)
        allowed = {
            k: data[k]
            for k in ("host", "scheme", "username", "vendor", "remember_password")
            if k in data
        }
        allowed["switches"] = _normalize_switch_profiles(
            data.get("switches"),
            legacy_username,
        )
        return cls(**allowed)

    def save(self) -> None:
        try:
            settings = xtray_config.load_settings()
        except xtray_config.ConfigError:
            settings = {}
        settings[NETWORK_MANAGER_SETTINGS_KEY] = asdict(self)
        xtray_config.save_settings(settings)

    def upsert_switch_profile(self, profile: SwitchProfileSettings) -> None:
        saved = SwitchProfileSettings(
            id=str(profile.id),
            label=str(profile.label),
            host=str(profile.host),
            vendor=str(profile.vendor),
            username=str(profile.username or self.username or "admin"),
        )
        for index, existing in enumerate(self.switches):
            if existing.id == saved.id:
                self.switches[index] = saved
                return
        self.switches.append(saved)


def _keyring_account(host: str, username: str) -> str:
    return f"{username}@{host}"


def load_password(host: str, username: str) -> str | None:
    if keyring is None:
        return None
    try:
        return keyring.get_password(KEYRING_SERVICE, _keyring_account(host, username))
    except Exception:
        return None


def save_password(host: str, username: str, password: str) -> bool:
    if keyring is None:
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, _keyring_account(host, username), password)
        return True
    except Exception:
        return False


def delete_password(host: str, username: str) -> None:
    if keyring is None:
        return
    try:
        keyring.delete_password(KEYRING_SERVICE, _keyring_account(host, username))
    except Exception:
        pass
