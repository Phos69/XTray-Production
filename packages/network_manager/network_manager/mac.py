"""Shared MAC address normalization helpers."""
from __future__ import annotations

import re

_MAC_RE = re.compile(r"^[0-9A-Fa-f]{12}$")


def mac_key(value: str | None) -> str:
    """Return a hex-only uppercase key for comparing MAC addresses."""
    if not value:
        return ""
    return re.sub(r"[^0-9A-Fa-f]", "", str(value)).upper()


def normalize_mac(value: str | None) -> str | None:
    """Normalize a MAC address to AA:BB:CC:DD:EE:FF, or None if invalid."""
    key = mac_key(value)
    if not key or not _MAC_RE.match(key):
        return None
    return ":".join(key[index : index + 2] for index in range(0, 12, 2))


def normalize_mac_or_original(
    value: str | None,
    *,
    uppercase_invalid: bool = False,
) -> str:
    """Normalize valid MACs and keep invalid values readable for diagnostics."""
    normalized = normalize_mac(value)
    if normalized is not None:
        return normalized
    fallback = str(value or "").strip()
    return fallback.upper() if uppercase_invalid else fallback
