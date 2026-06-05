"""Cross-pacakge models for adapter/drive/audio data.

Why this lives in xtray.core: the data shape is the contract between
- computer_manager (live data from Windows APIs)
- xtray.services (read-only consumer; also reads exported inventory.json
  when computer_manager is not installed).

Both sides must agree on the field names. Centralising the dataclasses
here avoids duplication and lets each side import the same type.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AdapterIpSettings:
    dhcp_enabled: bool
    ip_address: str | None = None
    prefix_length: int | None = None
    gateway: str | None = None
    dns_servers: tuple[str, ...] = ()


@dataclass(frozen=True)
class NetworkAdapter:
    name: str
    description: str
    status: str
    mac_address: str | None
    link_speed: str | None
    if_index: int
    dhcp_enabled: bool
    connection_state: str | None = None
    ipv4_addresses: tuple[str, ...] = ()
    ipv4_prefix_lengths: tuple[int, ...] = ()
    gateway: str | None = None
    dns_servers: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return self.status.casefold() != "disabled"

    @property
    def primary_ipv4(self) -> str | None:
        return self.ipv4_addresses[0] if self.ipv4_addresses else None

    @property
    def primary_prefix_length(self) -> int | None:
        return self.ipv4_prefix_lengths[0] if self.ipv4_prefix_lengths else None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NetworkAdapter:
        return cls(
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            status=str(data.get("status") or ""),
            mac_address=data.get("mac_address"),
            link_speed=data.get("link_speed"),
            if_index=int(data.get("if_index") or 0),
            dhcp_enabled=bool(data.get("dhcp_enabled", False)),
            connection_state=data.get("connection_state"),
            ipv4_addresses=tuple(data.get("ipv4_addresses") or ()),
            ipv4_prefix_lengths=tuple(data.get("ipv4_prefix_lengths") or ()),
            gateway=data.get("gateway"),
            dns_servers=tuple(data.get("dns_servers") or ()),
            raw=dict(data.get("raw") or {}),
        )


@dataclass(frozen=True)
class DriveInfo:
    letter: str
    drive_type: str
    label: str | None = None
    filesystem: str | None = None
    size: int | None = None
    free_space: int | None = None
    provider_name: str | None = None
    remote_path: str | None = None
    status: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> str:
        return f"{self.letter}:\\"

    @property
    def open_target(self) -> str:
        if self.drive_type == "Network" and self.status == "Disconnected" and self.remote_path:
            return self.remote_path
        return self.path

    @property
    def used_percent(self) -> int | None:
        if not self.size or self.free_space is None or self.size <= 0:
            return None
        used = max(0, self.size - self.free_space)
        return round(used * 100 / self.size)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DriveInfo:
        return cls(
            letter=str(data.get("letter") or ""),
            drive_type=str(data.get("drive_type") or ""),
            label=data.get("label"),
            filesystem=data.get("filesystem"),
            size=data.get("size"),
            free_space=data.get("free_space"),
            provider_name=data.get("provider_name"),
            remote_path=data.get("remote_path"),
            status=data.get("status"),
            raw=dict(data.get("raw") or {}),
        )


__all__ = [
    "AdapterIpSettings",
    "NetworkAdapter",
    "DriveInfo",
]
