"""Minimal Home Assistant REST client (stdlib only).

Used by the tray to read/write a HA entity that controls a TV volume. Two
entity domains are supported and selected automatically by the entity id
prefix:

* ``number.*`` → service ``number.set_value`` (integer 0-100, as before).
* ``media_player.*`` → service ``media_player.volume_set`` (``volume_level``
  float 0.0-1.0); the state is read from ``attributes.volume_level``.

Only the small subset of endpoints we need is implemented; failures surface
as :class:`HaRestError` so callers can show a friendly status message.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from . import config
from .core import app_logging
from .ha_ids import HA_SERVICE_RE

DEFAULT_TIMEOUT = 5.0


class HaRestError(Exception):
    """Raised when a Home Assistant REST call fails."""


STATUS_CONNECTED = "connected"
STATUS_DISCONNECTED = "disconnected"
STATUS_DISABLED = "disabled"


def ping(*, timeout: float = DEFAULT_TIMEOUT) -> tuple[str, str]:
    """Probe ``/api/`` and return ``(status, detail)``.

    ``status`` is one of :data:`STATUS_CONNECTED`, :data:`STATUS_DISCONNECTED`
    or :data:`STATUS_DISABLED`. ``detail`` is a short human-readable string
    suitable for tooltips.
    """
    creds = credentials_from_settings()
    if creds is None:
        return STATUS_DISABLED, "Home Assistant URL or token not configured"
    url, token = creds
    try:
        _request(f"{url}/api/", token, method="GET", timeout=timeout)
    except HaRestError as exc:
        return STATUS_DISCONNECTED, str(exc)
    return STATUS_CONNECTED, url


def credentials_from_settings() -> tuple[str, str] | None:
    try:
        settings = config.get_mqtt_settings()
    except config.ConfigError:
        return None
    if not settings.get("home_assistant_enabled"):
        return None
    url = settings.get("home_assistant_url")
    token = settings.get("home_assistant_token")
    if not isinstance(url, str) or not url.strip():
        return None
    if not isinstance(token, str) or not token.strip():
        return None
    return url.strip().rstrip("/"), token.strip()


def get_entity_volume_percent(
    entity_id: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> int | None:
    """Read a HA volume entity and return it as an integer 0-100 (or ``None``).

    Dispatch by domain:

    * ``number.*`` → integer ``state`` (0-100).
    * ``media_player.*`` → ``attributes.volume_level`` (0.0-1.0), scaled to %.
    """
    normalized = _normalize_entity_id(entity_id)
    domain = _domain(normalized)
    creds = credentials_from_settings()
    if creds is None:
        raise HaRestError("Home Assistant URL or token is not configured")
    url, token = creds
    data = _request(
        f"{url}/api/states/{normalized}",
        token,
        method="GET",
        timeout=timeout,
    )
    if not isinstance(data, dict):
        return None
    if domain == "number":
        state = data.get("state")
        if state in (None, "", "unknown", "unavailable"):
            return None
        try:
            return int(round(float(state)))
        except (TypeError, ValueError) as exc:
            raise HaRestError(f"unexpected state for {normalized}: {state!r}") from exc
    if domain == "media_player":
        attributes = data.get("attributes")
        level = attributes.get("volume_level") if isinstance(attributes, dict) else None
        if level is None:
            return None
        try:
            return max(0, min(100, int(round(float(level) * 100))))
        except (TypeError, ValueError) as exc:
            raise HaRestError(
                f"unexpected volume_level for {normalized}: {level!r}"
            ) from exc
    raise HaRestError(f"unsupported Home Assistant entity domain: {domain!r}")


def set_entity_volume_percent(
    entity_id: str,
    percent: int,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    """Apply a 0-100 % value to a HA volume entity, dispatching by domain."""
    normalized = _normalize_entity_id(entity_id)
    domain = _domain(normalized)
    creds = credentials_from_settings()
    if creds is None:
        raise HaRestError("Home Assistant URL or token is not configured")
    url, token = creds
    clamped = max(0, min(100, int(percent)))
    if domain == "number":
        _request(
            f"{url}/api/services/number/set_value",
            token,
            method="POST",
            payload={"entity_id": normalized, "value": clamped},
            timeout=timeout,
        )
        return
    if domain == "media_player":
        _request(
            f"{url}/api/services/media_player/volume_set",
            token,
            method="POST",
            payload={"entity_id": normalized, "volume_level": clamped / 100},
            timeout=timeout,
        )
        return
    raise HaRestError(f"unsupported Home Assistant entity domain: {domain!r}")


def get_entity_muted(
    entity_id: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> bool | None:
    """Read media player muted state from ``attributes.is_volume_muted``."""
    normalized = _normalize_entity_id(entity_id)
    domain = _domain(normalized)
    if domain != "media_player":
        raise HaRestError(f"unsupported Home Assistant mute domain: {domain!r}")
    creds = credentials_from_settings()
    if creds is None:
        raise HaRestError("Home Assistant URL or token is not configured")
    url, token = creds
    data = _request(
        f"{url}/api/states/{normalized}",
        token,
        method="GET",
        timeout=timeout,
    )
    if not isinstance(data, dict):
        return None
    attributes = data.get("attributes")
    muted = (
        attributes.get("is_volume_muted")
        if isinstance(attributes, dict)
        else None
    )
    return muted if isinstance(muted, bool) else None


def set_entity_muted(
    entity_id: str,
    muted: bool,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    """Mute or unmute a ``media_player.*`` entity."""
    normalized = _normalize_entity_id(entity_id)
    domain = _domain(normalized)
    if domain != "media_player":
        raise HaRestError(f"unsupported Home Assistant mute domain: {domain!r}")
    creds = credentials_from_settings()
    if creds is None:
        raise HaRestError("Home Assistant URL or token is not configured")
    url, token = creds
    _request(
        f"{url}/api/services/media_player/volume_mute",
        token,
        method="POST",
        payload={"entity_id": normalized, "is_volume_muted": bool(muted)},
        timeout=timeout,
    )


def call_service(
    service_id: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """Call a Home Assistant service/action like ``script.tv_on``."""
    normalized = _normalize_service_id(service_id)
    if payload is not None and not isinstance(payload, dict):
        raise HaRestError("Home Assistant service payload must be an object")
    creds = credentials_from_settings()
    if creds is None:
        raise HaRestError("Home Assistant URL or token is not configured")
    url, token = creds
    domain, service = normalized.split(".", 1)
    return _request(
        f"{url}/api/services/{domain}/{service}",
        token,
        method="POST",
        payload=payload or {},
        timeout=timeout,
    )


def get_number_value(entity_id: str, *, timeout: float = DEFAULT_TIMEOUT) -> int | None:
    """Backwards-compatible alias for :func:`get_entity_volume_percent`."""
    return get_entity_volume_percent(entity_id, timeout=timeout)


def set_number_value(
    entity_id: str,
    value: int,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    """Backwards-compatible alias for :func:`set_entity_volume_percent`."""
    set_entity_volume_percent(entity_id, value, timeout=timeout)


def _normalize_entity_id(entity_id: str) -> str:
    value = (entity_id or "").strip()
    if not value or "." not in value:
        raise HaRestError(f"invalid Home Assistant entity id: {entity_id!r}")
    return value


def _normalize_service_id(service_id: str) -> str:
    value = (service_id or "").strip().casefold()
    if not HA_SERVICE_RE.match(value):
        raise HaRestError(f"invalid Home Assistant service id: {service_id!r}")
    return value


def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0]


def _request(
    url: str,
    token: str,
    *,
    method: str,
    payload: dict[str, Any] | None = None,
    timeout: float,
) -> Any:
    body = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = _safe_read(exc)
        raise HaRestError(f"HA {method} {url} failed: HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise HaRestError(f"HA {method} {url} failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise HaRestError(f"HA {method} {url} timed out after {timeout:g}s") from exc
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        app_logging.get_logger("ha_rest").warning("non-JSON response from %s", url)
        return None


def _safe_read(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return ""
