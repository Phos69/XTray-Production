"""API token and bind-safety settings."""
from __future__ import annotations

import os
import secrets

from .paths import (
    ENV_API_TOKEN,
    ENV_UNSAFE_NO_AUTH,
    LEGACY_ENV_API_TOKEN,
    LEGACY_ENV_UNSAFE_NO_AUTH,
)
from .store import load_settings, save_settings
from .validators import ConfigError, truthy


def get_api_token() -> str | None:
    env_token = os.environ.get(ENV_API_TOKEN)
    if env_token:
        return env_token
    legacy_env_token = os.environ.get(LEGACY_ENV_API_TOKEN)
    if legacy_env_token:
        return legacy_env_token
    token = load_settings().get("api_token")
    return token if isinstance(token, str) and token else None


def set_api_token(token: str) -> str:
    value = token.strip()
    if len(value) < 16:
        raise ConfigError("API token must be at least 16 characters")
    settings = load_settings()
    settings["api_token"] = value
    save_settings(settings)
    return value


def ensure_api_token(*, force: bool = False) -> str:
    if not force:
        existing = get_api_token()
        if existing:
            return existing
    return set_api_token(secrets.token_urlsafe(32))


def auth_disabled_by_env() -> bool:
    return truthy(os.environ.get(ENV_UNSAFE_NO_AUTH)) or truthy(
        os.environ.get(LEGACY_ENV_UNSAFE_NO_AUTH)
    )


def is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in {"localhost", "127.0.0.1", "::1"} or normalized.startswith("127.")


def assert_safe_api_bind(host: str, *, unsafe_no_auth: bool = False) -> None:
    if is_loopback_host(host):
        return
    if unsafe_no_auth:
        return
    if get_api_token():
        return
    raise ConfigError(
        "refusing to bind the API on a non-loopback host without an API token; "
        "run `xtray config token` or pass `--unsafe-no-auth` explicitly"
    )
