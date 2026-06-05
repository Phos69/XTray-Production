"""Device persistence and matching helpers for DeviceManagerWidget.

These pure-functions take the widget as their first argument so the
widget keeps its bookkeeping (``_devices``, ``_selected_device_id``,
``refresh_devices``, ``status``) but the device mutation logic lives
in one place that's straightforward to test without instantiating Qt.
"""
from __future__ import annotations

from typing import Any

from . import storage
from .models import (
    DEFAULT_DEVICE_KIND,
    DEFAULT_SWITCH_MODEL,
    DiscoveredDevice,
    NetworkDevice,
    normalize_mac,
)


def create_or_update_from_scan(widget: Any, result: DiscoveredDevice) -> NetworkDevice:
    existing = find_device_for_scan_result(widget, result)
    seed_mac = result.mac or (existing.mac if existing is not None else None)
    if existing is not None:
        seed_status = existing.dhcp_status
    else:
        seed_status = widget._compute_dhcp_status(seed_mac, result.ip)
    device = NetworkDevice.create(
        id=existing.id if existing is not None else None,
        name=existing.name if existing is not None else (result.name or f"Device {result.ip}"),
        ip=result.ip,
        mac=seed_mac,
        url=existing.url if existing is not None else None,
        icon=existing.icon if existing is not None else None,
        kind=existing.kind if existing is not None else DEFAULT_DEVICE_KIND,
        switch_model=(
            existing.switch_model if existing is not None else DEFAULT_SWITCH_MODEL
        ),
        dhcp_status=seed_status,
        offline=existing.offline if existing is not None else False,
    )
    storage.upsert_device(device)
    widget._selected_device_id = device.id
    widget.status.setText(f"Salvato {device.name} dalla scansione.")
    widget.refresh_devices()
    return device


def save_device(
    widget: Any,
    *,
    name: str,
    ip: str,
    mac: str | None = None,
) -> NetworkDevice:
    existing = find_device_for_ip_or_mac(widget, ip, mac)
    seed_mac = mac or (existing.mac if existing is not None else None)
    if existing is not None:
        seed_status = existing.dhcp_status
    else:
        seed_status = widget._compute_dhcp_status(seed_mac, ip)
    device = NetworkDevice.create(
        id=existing.id if existing is not None else None,
        name=existing.name if existing is not None else name,
        ip=ip,
        mac=seed_mac,
        url=existing.url if existing is not None else None,
        icon=existing.icon if existing is not None else None,
        kind=existing.kind if existing is not None else DEFAULT_DEVICE_KIND,
        switch_model=(
            existing.switch_model if existing is not None else DEFAULT_SWITCH_MODEL
        ),
        dhcp_status=seed_status,
        offline=existing.offline if existing is not None else False,
    )
    storage.upsert_device(device)
    widget._selected_device_id = device.id
    widget.refresh_devices()
    return device


def update_device_network_settings(
    widget: Any,
    device_id: str,
    *,
    ip: str | None = None,
    switch_model: str | None = None,
) -> NetworkDevice | None:
    existing = find_device_by_id(widget, device_id)
    if existing is None:
        return None
    device = NetworkDevice.create(
        id=existing.id,
        name=existing.name,
        ip=ip or existing.ip,
        mac=existing.mac,
        url=existing.url,
        icon=existing.icon,
        kind=existing.kind,
        switch_model=switch_model or existing.switch_model,
        dhcp_status=existing.dhcp_status,
        offline=existing.offline,
    )
    storage.upsert_device(device)
    widget._selected_device_id = device.id
    widget.refresh_devices()
    return device


def find_device_by_id(widget: Any, device_id: str) -> NetworkDevice | None:
    for device in widget._devices:
        if device.id == device_id:
            return device
    return None


def find_device_for_scan_result(
    widget: Any,
    result: DiscoveredDevice,
) -> NetworkDevice | None:
    return find_device_for_ip_or_mac(widget, result.ip, result.mac)


def find_device_for_ip_or_mac(
    widget: Any,
    ip: str,
    mac: str | None,
) -> NetworkDevice | None:
    normalized_mac = normalize_mac(mac) if mac else None
    for device in widget._devices:
        if device.ip == ip:
            return device
        if normalized_mac and device.mac == normalized_mac:
            return device
    return None
