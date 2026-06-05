"""Persistent settings and keyring access for XTray LAN sync."""
from __future__ import annotations

import base64
import os
import socket
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from xtray import config as xtray_config

try:  # pragma: no cover - exercised through monkeypatch/fallback tests
    import keyring
except ImportError:  # pragma: no cover
    keyring = None  # type: ignore[assignment]


SYNC_SETTINGS_KEY = "xtray_sync"
KEYRING_SERVICE = "XTray Sync"
KEYRING_PASSWORD_ACCOUNT = "lan_sync_password"
DEFAULT_PORT = 37665
DEFAULT_DISCOVERY_PORT = 37666


@dataclass
class ManagedNetworkPassword:
    host: str
    username: str
    account: str

    @classmethod
    def create(cls, *, host: str, username: str) -> ManagedNetworkPassword:
        clean_host = str(host or "").strip()
        clean_username = str(username or "").strip()
        return cls(
            host=clean_host,
            username=clean_username,
            account=network_password_account(clean_host, clean_username),
        )


@dataclass
class SyncSettings:
    enabled: bool = False
    instance_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    peer_name: str = field(default_factory=socket.gethostname)
    port: int = DEFAULT_PORT
    discovery_port: int = DEFAULT_DISCOVERY_PORT
    salt: str = field(default_factory=lambda: _random_b64(16))
    managed_network_passwords: list[ManagedNetworkPassword] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["managed_network_passwords"] = [
            asdict(item) for item in self.managed_network_passwords
        ]
        return payload


def load_sync_settings() -> SyncSettings:
    try:
        raw_settings = xtray_config.load_settings()
    except xtray_config.ConfigError:
        raw_settings = {}
    raw = raw_settings.get(SYNC_SETTINGS_KEY)
    return normalize_sync_settings(raw)


def ensure_sync_settings() -> SyncSettings:
    settings = load_sync_settings()
    saved = xtray_config.load_settings()
    if saved.get(SYNC_SETTINGS_KEY) != settings.to_dict():
        saved[SYNC_SETTINGS_KEY] = settings.to_dict()
        xtray_config.save_settings(saved)
    return settings


def save_sync_settings(settings: SyncSettings) -> SyncSettings:
    normalized = normalize_sync_settings(settings.to_dict())
    saved = xtray_config.load_settings()
    saved[SYNC_SETTINGS_KEY] = normalized.to_dict()
    xtray_config.save_settings(saved)
    return normalized


def set_sync_settings(
    *,
    enabled: bool | None = None,
    peer_name: str | None = None,
    port: int | None = None,
    discovery_port: int | None = None,
    password: str | None = None,
) -> SyncSettings:
    settings = load_sync_settings()
    if enabled is not None:
        settings.enabled = bool(enabled)
    if peer_name is not None:
        clean_name = str(peer_name).strip()
        settings.peer_name = clean_name or socket.gethostname()
    if port is not None:
        settings.port = _normalize_port(port, "xtray_sync.port")
    if discovery_port is not None:
        settings.discovery_port = _normalize_port(
            discovery_port,
            "xtray_sync.discovery_port",
        )
    saved = save_sync_settings(settings)
    if password is not None:
        if not save_password(password):
            raise xtray_config.ConfigError(
                "could not store LAN sync password in the OS credential manager"
            )
    return saved


def set_managed_network_passwords(
    entries: list[ManagedNetworkPassword],
) -> SyncSettings:
    unique: dict[tuple[str, str], ManagedNetworkPassword] = {}
    for entry in entries:
        managed = ManagedNetworkPassword.create(host=entry.host, username=entry.username)
        if managed.host and managed.username:
            unique[(managed.host, managed.username)] = managed
    settings = load_sync_settings()
    settings.managed_network_passwords = sorted(
        unique.values(),
        key=lambda item: (item.host.casefold(), item.username.casefold()),
    )
    return save_sync_settings(settings)


def normalize_sync_settings(value: Any) -> SyncSettings:
    raw = value if isinstance(value, dict) else {}
    instance_id = str(raw.get("instance_id") or "").strip() or uuid.uuid4().hex
    peer_name = str(raw.get("peer_name") or "").strip() or socket.gethostname()
    salt = str(raw.get("salt") or "").strip()
    if not _valid_b64(salt):
        salt = _random_b64(16)
    managed = []
    raw_managed = raw.get("managed_network_passwords")
    if isinstance(raw_managed, list):
        for item in raw_managed:
            if not isinstance(item, dict):
                continue
            host = str(item.get("host") or "").strip()
            username = str(item.get("username") or "").strip()
            if host and username:
                managed.append(ManagedNetworkPassword.create(host=host, username=username))
    return SyncSettings(
        enabled=_bool_setting(raw.get("enabled", False)),
        instance_id=instance_id,
        peer_name=peer_name,
        port=_normalize_port(raw.get("port", DEFAULT_PORT), "xtray_sync.port"),
        discovery_port=_normalize_port(
            raw.get("discovery_port", DEFAULT_DISCOVERY_PORT),
            "xtray_sync.discovery_port",
        ),
        salt=salt,
        managed_network_passwords=managed,
    )


def password_available() -> bool:
    return bool(get_password())


def get_password() -> str | None:
    if keyring is None:
        return os.environ.get("XTRAY_SYNC_PASSWORD") or None
    try:
        value = keyring.get_password(KEYRING_SERVICE, KEYRING_PASSWORD_ACCOUNT)
    except Exception:
        value = None
    return value or os.environ.get("XTRAY_SYNC_PASSWORD") or None


def save_password(password: str) -> bool:
    value = str(password or "")
    if not value:
        delete_password()
        return True
    if keyring is None:
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_PASSWORD_ACCOUNT, value)
        return True
    except Exception:
        return False


def delete_password() -> None:
    if keyring is None:
        return
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_PASSWORD_ACCOUNT)
    except Exception:
        pass


def network_password_account(host: str, username: str) -> str:
    return f"{username}@{host}"


def status_summary() -> dict[str, Any]:
    settings = load_sync_settings()
    return {
        "enabled": settings.enabled,
        "ready": settings.enabled and password_available(),
        "instance_id": settings.instance_id,
        "peer_name": settings.peer_name,
        "port": settings.port,
        "discovery_port": settings.discovery_port,
        "password_configured": password_available(),
        "managed_network_passwords": [
            item.account for item in settings.managed_network_passwords
        ],
    }


def _normalize_port(value: Any, name: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise xtray_config.ConfigError(f"{name} must be an integer") from exc
    if not 1 <= port <= 65535:
        raise xtray_config.ConfigError(f"{name} must be between 1 and 65535")
    return port


def _bool_setting(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y", "on"}


def _random_b64(size: int) -> str:
    return base64.urlsafe_b64encode(os.urandom(size)).decode("ascii")


def _valid_b64(value: str) -> bool:
    if not value:
        return False
    try:
        base64.urlsafe_b64decode(value.encode("ascii"))
    except Exception:
        return False
    return True
