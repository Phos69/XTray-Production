"""Import/export bundle model for XTray LAN sync."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xtray import config as xtray_config

from . import config as sync_config

BUNDLE_SCHEMA = "xtray.sync.bundle.v1"


@dataclass
class ImportResult:
    backup_path: Path | None = None
    network_settings_imported: bool = False
    network_devices_imported: int = 0
    network_passwords_imported: int = 0
    network_passwords_deleted: int = 0
    display_profiles_imported: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "backup_path": str(self.backup_path) if self.backup_path else None,
            "network_settings_imported": self.network_settings_imported,
            "network_devices_imported": self.network_devices_imported,
            "network_passwords_imported": self.network_passwords_imported,
            "network_passwords_deleted": self.network_passwords_deleted,
            "display_profiles_imported": self.display_profiles_imported,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class ImportOptions:
    network_settings: bool = True
    network_devices: bool = True
    network_passwords: bool = True
    display_profiles: bool = True


def create_bundle() -> dict[str, Any]:
    settings = _load_settings_safely()
    network_settings = settings.get("network_manager")
    if not isinstance(network_settings, dict):
        network_settings = None
    else:
        network_settings = _sanitize_non_secret_settings(network_settings)
    return {
        "schema": BUNDLE_SCHEMA,
        "created_at": _timestamp(),
        "network_manager_settings": network_settings,
        "network_devices": _export_network_devices(),
        "network_passwords": _export_network_passwords(network_settings),
        "display_profiles": _export_display_profiles(),
    }


def create_preview() -> dict[str, Any]:
    bundle = create_bundle()
    return {
        "schema": BUNDLE_SCHEMA,
        "created_at": bundle["created_at"],
        "sections": {
            "network_manager_settings": bundle.get("network_manager_settings") is not None,
            "network_devices": len(bundle.get("network_devices") or []),
            "network_passwords": len(bundle.get("network_passwords") or []),
            "display_profiles": len(bundle.get("display_profiles") or []),
        },
    }


def import_bundle(bundle: dict[str, Any], options: ImportOptions | None = None) -> ImportResult:
    options = options or ImportOptions()
    result = ImportResult()
    if not isinstance(bundle, dict) or bundle.get("schema") != BUNDLE_SCHEMA:
        result.errors.append("unsupported sync bundle")
        return result

    try:
        result.backup_path = _create_backup(bundle, options)
    except Exception as exc:
        result.errors.append(f"could not create backup: {exc}")
        return result

    if options.network_settings and isinstance(bundle.get("network_manager_settings"), dict):
        try:
            _import_network_settings(bundle["network_manager_settings"])
            result.network_settings_imported = True
        except Exception as exc:
            result.errors.append(f"network settings import failed: {exc}")

    if options.network_devices:
        try:
            result.network_devices_imported = _import_network_devices(
                bundle.get("network_devices")
            )
        except Exception as exc:
            result.errors.append(f"network devices import failed: {exc}")

    if options.network_passwords:
        try:
            imported, deleted = _import_network_passwords(bundle.get("network_passwords"))
            result.network_passwords_imported = imported
            result.network_passwords_deleted = deleted
        except Exception as exc:
            result.errors.append(f"network password import failed: {exc}")

    if options.display_profiles:
        try:
            result.display_profiles_imported = _import_display_profiles(
                bundle.get("display_profiles")
            )
        except Exception as exc:
            result.errors.append(f"display profile import failed: {exc}")

    return result


def _load_settings_safely() -> dict[str, Any]:
    try:
        return xtray_config.load_settings()
    except xtray_config.ConfigError:
        return {}


def _export_network_devices() -> list[dict[str, Any]]:
    try:
        from network_manager.device_manager import storage
    except ImportError:
        return []
    try:
        return [device.to_dict() for device in storage.list_devices()]
    except Exception:
        return []


def _export_network_passwords(network_settings: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(network_settings, dict):
        return []
    try:
        from network_manager import app_config
    except ImportError:
        return []
    switches = network_settings.get("switches")
    if not isinstance(switches, list):
        return []
    by_account: dict[tuple[str, str], dict[str, str]] = {}
    for item in switches:
        if not isinstance(item, dict):
            continue
        host = str(item.get("host") or "").strip()
        username = str(item.get("username") or network_settings.get("username") or "admin").strip()
        if not host or not username:
            continue
        password = app_config.load_password(host, username)
        if not password:
            continue
        by_account[(host, username)] = {
            "host": host,
            "username": username,
            "account": sync_config.network_password_account(host, username),
            "password": password,
        }
    return sorted(by_account.values(), key=lambda item: (item["host"], item["username"]))


def _sanitize_non_secret_settings(value: dict[str, Any]) -> dict[str, Any]:
    secret_keys = {"password", "token", "secret", "api_key"}

    def scrub(item: Any) -> Any:
        if isinstance(item, dict):
            cleaned: dict[str, Any] = {}
            for key, child in item.items():
                lowered = str(key).casefold()
                if lowered in secret_keys or lowered.endswith("_token"):
                    continue
                cleaned[str(key)] = scrub(child)
            return cleaned
        if isinstance(item, list):
            return [scrub(child) for child in item]
        return item

    return scrub(value)


def _export_display_profiles() -> list[dict[str, Any]]:
    try:
        from computer_manager.display_manager import profiles
    except ImportError:
        return []
    exported: list[dict[str, Any]] = []
    for name in profiles.list_profiles():
        try:
            exported.append(profiles.load(name))
        except Exception:
            continue
    return exported


def _create_backup(bundle: dict[str, Any], options: ImportOptions) -> Path:
    backup_dir = xtray_config.config_dir() / "sync_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / f"sync-backup-{time.strftime('%Y%m%d-%H%M%S')}.json"
    backup: dict[str, Any] = {
        "schema": "xtray.sync.backup.v1",
        "created_at": _timestamp(),
        "note": "Passwords are intentionally not included in sync backups.",
    }
    settings = _load_settings_safely()
    if options.network_settings:
        value = settings.get("network_manager")
        backup["network_manager_settings"] = value if isinstance(value, dict) else None
    if options.network_devices:
        backup["network_devices"] = _export_network_devices()
    if options.display_profiles:
        incoming_names = _incoming_profile_names(bundle.get("display_profiles"))
        backup["display_profiles"] = _export_existing_display_profiles(incoming_names)
    path.write_text(json.dumps(backup, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _incoming_profile_names(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    names: set[str] = set()
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.add(item["name"])
    return names


def _export_existing_display_profiles(names: set[str]) -> list[dict[str, Any]]:
    if not names:
        return []
    try:
        from computer_manager.display_manager import profiles
    except ImportError:
        return []
    existing: list[dict[str, Any]] = []
    for name in sorted(names):
        try:
            existing.append(profiles.load(name))
        except Exception:
            continue
    return existing


def _import_network_settings(payload: dict[str, Any]) -> None:
    settings = xtray_config.load_settings()
    settings["network_manager"] = dict(payload)
    xtray_config.save_settings(settings)


def _import_network_devices(value: Any) -> int:
    if value is None:
        value = []
    if not isinstance(value, list):
        raise ValueError("network_devices must be a list")
    from network_manager.device_manager import storage
    from network_manager.device_manager.models import NetworkDevice

    devices = [NetworkDevice.from_dict(item) for item in value]
    storage.save_devices(devices)
    return len(devices)


def _import_network_passwords(value: Any) -> tuple[int, int]:
    if value is None:
        value = []
    if not isinstance(value, list):
        raise ValueError("network_passwords must be a list")
    from network_manager import app_config

    incoming: dict[tuple[str, str], sync_config.ManagedNetworkPassword] = {}
    imported = 0
    for item in value:
        if not isinstance(item, dict):
            continue
        host = str(item.get("host") or "").strip()
        username = str(item.get("username") or "").strip()
        password = str(item.get("password") or "")
        if not host or not username or not password:
            continue
        if app_config.save_password(host, username, password):
            incoming[(host, username)] = sync_config.ManagedNetworkPassword.create(
                host=host,
                username=username,
            )
            imported += 1

    settings = sync_config.load_sync_settings()
    deleted = 0
    for managed in settings.managed_network_passwords:
        key = (managed.host, managed.username)
        if key in incoming:
            continue
        app_config.delete_password(managed.host, managed.username)
        deleted += 1
    sync_config.set_managed_network_passwords(list(incoming.values()))
    return imported, deleted


def _import_display_profiles(value: Any) -> int:
    if value is None:
        value = []
    if not isinstance(value, list):
        raise ValueError("display_profiles must be a list")
    from computer_manager.display_manager import profiles

    imported = 0
    for item in value:
        if not isinstance(item, dict):
            continue
        profile = profiles.Profile.from_dict(item, source_name=item.get("name"))
        profiles.save_profile(profile, overwrite=True)
        imported += 1
    return imported


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
