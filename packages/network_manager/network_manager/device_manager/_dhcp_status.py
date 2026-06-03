"""DHCP status computation shared by DeviceManagerWidget.

The widget needs to derive ``dhcp_status`` for each saved device from
live router data:

- Reserved if the device MAC has a static reservation.
- Dynamic if a lease for that MAC or IP is active.
- Static otherwise (when *both* reservation and lease data sources are
  loaded — without either, the persisted value is kept as the fallback).

The state lives in ``DhcpStatusComputer`` so the widget can drop ~100 LOC
of book-keeping and rely on three explicit methods.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..mac import mac_key as _mac_key
from .models import (
    DEFAULT_DHCP_STATUS,
    DHCP_STATUS_DYNAMIC,
    DHCP_STATUS_RESERVED,
    DHCP_STATUS_STATIC,
    NetworkDevice,
)


class DhcpStatusComputer:
    """Holds reservation and lease snapshots and computes DHCP status."""

    def __init__(self) -> None:
        self.reserved_mac_keys: set[str] = set()
        self.lease_mac_keys: set[str] = set()
        self.lease_ip_keys: set[str] = set()
        self.has_reservation_data: bool = False
        self.has_lease_data: bool = False

    def set_reserved_macs(self, macs: Iterable[str], *, loaded: bool = True) -> None:
        self.reserved_mac_keys = {_mac_key(m) for m in macs if m}
        self.reserved_mac_keys.discard("")
        self.has_reservation_data = loaded

    def set_active_leases(self, leases: Iterable[Any], *, loaded: bool = True) -> None:
        mac_keys: set[str] = set()
        ip_keys: set[str] = set()
        for ls in leases:
            mac = getattr(ls, "mac", None)
            ip = getattr(ls, "ip", None)
            key = _mac_key(mac)
            if key:
                mac_keys.add(key)
            if ip:
                ip_keys.add(ip)
        self.lease_mac_keys = mac_keys
        self.lease_ip_keys = ip_keys
        self.has_lease_data = loaded

    def compute(
        self,
        mac: str | None,
        ip: str | None,
        *,
        fallback: str = DEFAULT_DHCP_STATUS,
    ) -> str:
        """Compute DHCP status from router data, falling back when data is missing.

        Reserved wins over Dynamic. If neither reservation nor lease data is
        loaded, the supplied fallback is returned so the persisted value can
        be shown while disconnected.
        """
        mac_k = _mac_key(mac)
        if self.has_reservation_data and mac_k and mac_k in self.reserved_mac_keys:
            return DHCP_STATUS_RESERVED
        if self.has_lease_data and (
            (mac_k and mac_k in self.lease_mac_keys)
            or (ip and ip in self.lease_ip_keys)
        ):
            return DHCP_STATUS_DYNAMIC
        if self.has_reservation_data and self.has_lease_data:
            return DHCP_STATUS_STATIC
        return fallback

    def recompute_devices(
        self,
        devices: list[NetworkDevice],
    ) -> tuple[list[NetworkDevice], bool]:
        """Recompute dhcp_status for each device. Returns (updated_list, changed)."""
        if not (self.has_lease_data and self.has_reservation_data):
            return devices, False
        updated: list[NetworkDevice] = []
        changed = False
        for device in devices:
            computed = self.compute(device.mac, device.ip)
            if device.dhcp_status != computed:
                changed = True
                updated.append(
                    NetworkDevice(
                        id=device.id,
                        name=device.name,
                        ip=device.ip,
                        mac=device.mac,
                        url=device.url,
                        icon=device.icon,
                        kind=device.kind,
                        switch_model=device.switch_model,
                        dhcp_status=computed,
                        offline=device.offline,
                    )
                )
            else:
                updated.append(device)
        return updated, changed
