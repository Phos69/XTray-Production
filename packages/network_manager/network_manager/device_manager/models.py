"""Network device models and validation helpers."""
from __future__ import annotations

import ipaddress
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from ..mac import normalize_mac as _shared_normalize_mac

DEVICE_KIND_NETWORK = "network"
DEVICE_KIND_IOT = "iot"
DEVICE_KIND_MEDIA = "media"
DEVICE_KIND_PERSONAL = "personal"
DEVICE_KINDS: tuple[str, ...] = (
    DEVICE_KIND_NETWORK,
    DEVICE_KIND_IOT,
    DEVICE_KIND_MEDIA,
    DEVICE_KIND_PERSONAL,
)
DEFAULT_DEVICE_KIND = DEVICE_KIND_NETWORK

SWITCH_MODEL_UNSUPPORTED = "unsupported"
DEFAULT_SWITCH_MODEL = SWITCH_MODEL_UNSUPPORTED

DHCP_STATUS_STATIC = "static"
DHCP_STATUS_DYNAMIC = "dynamic"
DHCP_STATUS_RESERVED = "reserved"
DHCP_STATUSES: tuple[str, ...] = (
    DHCP_STATUS_STATIC,
    DHCP_STATUS_DYNAMIC,
    DHCP_STATUS_RESERVED,
)
DEFAULT_DHCP_STATUS = DHCP_STATUS_STATIC


class NetworkConfigError(Exception):
    """Raised when network manager configuration is invalid."""


@dataclass(frozen=True)
class NetworkDevice:
    id: str
    name: str
    ip: str
    mac: str | None = None
    url: str | None = None
    icon: str | None = None
    kind: str = DEFAULT_DEVICE_KIND
    switch_model: str = DEFAULT_SWITCH_MODEL
    dhcp_status: str = DEFAULT_DHCP_STATUS
    offline: bool = False

    @classmethod
    def create(
        cls,
        *,
        name: str,
        ip: str,
        mac: str | None = None,
        url: str | None = None,
        icon: str | None = None,
        id: str | None = None,
        kind: str | None = None,
        switch_model: str | None = None,
        dhcp_status: str | None = None,
        offline: Any = False,
    ) -> NetworkDevice:
        return cls(
            id=_normalize_id(id),
            name=_required_text(name, "device name"),
            ip=normalize_ip(ip),
            mac=normalize_mac(mac),
            url=normalize_url(url),
            icon=normalize_icon(icon),
            kind=normalize_kind(kind),
            switch_model=normalize_switch_model(switch_model),
            dhcp_status=normalize_dhcp_status(dhcp_status),
            offline=normalize_offline(offline),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NetworkDevice:
        if not isinstance(data, dict):
            raise NetworkConfigError("network device must be an object")
        return cls.create(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            ip=str(data.get("ip") or ""),
            mac=_optional_text(data.get("mac")),
            url=_optional_text(data.get("url")),
            icon=_optional_text(data.get("icon")),
            kind=_optional_text(data.get("kind")),
            switch_model=_optional_text(data.get("switch_model")),
            dhcp_status=_optional_text(data.get("dhcp_status")),
            offline=data.get("offline", False),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def web_url(self) -> str:
        return self.url or f"http://{self.ip}"


@dataclass(frozen=True)
class NetworkStatus:
    device: NetworkDevice
    online: bool
    latency_ms: int | None = None
    detail: str | None = None


@dataclass(frozen=True)
class NetworkAdapter:
    name: str
    interface_index: int
    ip: str
    prefix_length: int
    mac: str | None = None

    @classmethod
    def from_values(
        cls,
        *,
        name: str,
        interface_index: int,
        ip: str,
        prefix_length: int,
        mac: str | None = None,
    ) -> NetworkAdapter:
        if not 0 <= int(prefix_length) <= 32:
            raise NetworkConfigError("adapter prefix length must be between 0 and 32")
        return cls(
            name=_required_text(name, "adapter name"),
            interface_index=int(interface_index),
            ip=normalize_ip(ip),
            prefix_length=int(prefix_length),
            mac=normalize_mac(mac),
        )

    def label(self) -> str:
        return f"{self.name} ({self.ip}/{self.prefix_length})"


@dataclass(frozen=True)
class DiscoveredDevice:
    ip: str
    mac: str | None = None
    name: str | None = None

    @classmethod
    def create(
        cls,
        *,
        ip: str,
        mac: str | None = None,
        name: str | None = None,
    ) -> DiscoveredDevice:
        normalized_ip = normalize_ip(ip)
        return cls(
            ip=normalized_ip,
            mac=normalize_mac(mac),
            name=_optional_text(name) or f"Device {normalized_ip}",
        )


def normalize_ip(value: str) -> str:
    text = _required_text(value, "IP address")
    try:
        address = ipaddress.ip_address(text)
    except ValueError as exc:
        raise NetworkConfigError(f"invalid IP address: {value!r}") from exc
    if address.version != 4:
        raise NetworkConfigError("only IPv4 addresses are supported")
    return str(address)


def normalize_mac(value: str | None) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    normalized = _shared_normalize_mac(text)
    if normalized is None:
        raise NetworkConfigError(f"invalid MAC address: {value!r}")
    return normalized


def normalize_icon(value: str | None) -> str | None:
    from xtray.core import icons

    return icons.normalize_icon_name(value)


def normalize_kind(value: str | None) -> str:
    """Coerce a device kind to a known value, defaulting to 'network'."""
    text = _optional_text(value)
    if text is None:
        return DEFAULT_DEVICE_KIND
    candidate = text.casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "personal_device": DEVICE_KIND_PERSONAL,
        "personal_devices": DEVICE_KIND_PERSONAL,
    }
    if candidate in aliases:
        return aliases[candidate]
    if candidate in DEVICE_KINDS:
        return candidate
    return DEFAULT_DEVICE_KIND


def normalize_switch_model(value: str | None) -> str:
    """Coerce an optional switch model key to a stable persisted value."""
    text = _optional_text(value)
    if text is None:
        return DEFAULT_SWITCH_MODEL
    return text.casefold()


def normalize_dhcp_status(value: str | None) -> str:
    """Coerce a DHCP status to a known value, defaulting to 'static'."""
    text = _optional_text(value)
    if text is None:
        return DEFAULT_DHCP_STATUS
    candidate = text.casefold()
    if candidate in DHCP_STATUSES:
        return candidate
    return DEFAULT_DHCP_STATUS


def normalize_offline(value: Any) -> bool:
    """Coerce persisted offline flags without hiding devices by accident."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "y", "on", "offline"}:
        return True
    if text in {"0", "false", "no", "n", "off", "online", ""}:
        return False
    return False


def normalize_url(value: str | None) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    if "://" not in text:
        text = f"http://{text}"
    scheme = text.split("://", 1)[0].casefold()
    if scheme not in {"http", "https"}:
        raise NetworkConfigError("device URL must use http or https")
    return text


def _normalize_id(value: str | None) -> str:
    text = _optional_text(value)
    return text or uuid.uuid4().hex


def _required_text(value: str, name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise NetworkConfigError(f"{name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
