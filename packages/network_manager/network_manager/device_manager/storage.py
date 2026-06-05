"""JSON persistence for Network Manager devices."""
from __future__ import annotations

import ipaddress
import json
import os
import shutil
from pathlib import Path

from ..storage_utils import atomic_write_json, network_manager_data_dir
from .models import NetworkConfigError, NetworkDevice, normalize_kind

NETWORK_DEVICES_SCHEMA_VERSION = 1
NETWORK_DEVICES_FILE: Path | None = None
LEGACY_NETWORK_DEVICES_FILE: Path | None = None


def devices_path() -> Path:
    if NETWORK_DEVICES_FILE is not None:
        return NETWORK_DEVICES_FILE
    return network_manager_data_dir() / "network_devices.json"


def legacy_devices_path() -> Path:
    if LEGACY_NETWORK_DEVICES_FILE is not None:
        return LEGACY_NETWORK_DEVICES_FILE
    root = os.environ.get("APPDATA")
    base = Path(root) if root else Path.home() / ".config"
    return base / "DisplayManager" / "network_devices.json"


def migrate_legacy_devices_file() -> bool:
    """Import the old DisplayManager device file once, without deleting it."""
    target = devices_path()
    if target.exists():
        return False
    source = legacy_devices_path()
    if not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def list_devices() -> list[NetworkDevice]:
    migrate_legacy_devices_file()
    path = devices_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NetworkConfigError(f"invalid network devices file: {path}") from exc
    if not isinstance(data, dict):
        raise NetworkConfigError("network devices file must contain an object")
    version = data.get("version")
    if version != NETWORK_DEVICES_SCHEMA_VERSION:
        raise NetworkConfigError(f"unsupported network devices version: {version}")
    raw_devices = data.get("devices", [])
    if not isinstance(raw_devices, list):
        raise NetworkConfigError("network devices must be a list")
    return [NetworkDevice.from_dict(item) for item in raw_devices]


def save_devices(devices: list[NetworkDevice]) -> Path:
    seen_ids: set[str] = set()
    normalized: list[NetworkDevice] = []
    for device in devices:
        if device.id in seen_ids:
            raise NetworkConfigError(f"duplicate network device id: {device.id}")
        seen_ids.add(device.id)
        normalized.append(NetworkDevice.from_dict(device.to_dict()))
    path = devices_path()
    atomic_write_json(
        path,
        {
            "version": NETWORK_DEVICES_SCHEMA_VERSION,
            "devices": [device.to_dict() for device in normalized],
        },
    )
    return path


def reorder_devices_for_kind(kind: str | None, ordered_ids: list[str]) -> list[NetworkDevice]:
    """Persist a new order for one device kind, preserving all other rows."""
    devices = list_devices()
    target_kind = normalize_kind(kind)
    return _save_reordered_devices_for_kind(
        devices,
        target_kind,
        [str(device_id) for device_id in ordered_ids],
    )


def sort_devices_for_kind(kind: str | None, by: str) -> list[NetworkDevice]:
    """Sort one device kind by a supported key and persist the result."""
    devices = list_devices()
    target_kind = normalize_kind(kind)
    key = str(by).strip().casefold()
    kind_devices = [
        device for device in devices if normalize_kind(device.kind) == target_kind
    ]
    if key == "name":
        ordered = sorted(
            kind_devices,
            key=lambda device: (
                device.name.casefold(),
                _ip_sort_key(device.ip),
                device.id,
            ),
        )
    elif key == "ip":
        ordered = sorted(
            kind_devices,
            key=lambda device: (
                _ip_sort_key(device.ip),
                device.name.casefold(),
                device.id,
            ),
        )
    else:
        raise NetworkConfigError("device sort key must be one of: name, ip")
    return _save_reordered_devices_for_kind(
        devices,
        target_kind,
        [device.id for device in ordered],
    )


def upsert_device(device: NetworkDevice) -> list[NetworkDevice]:
    devices = list_devices()
    replaced = False
    updated: list[NetworkDevice] = []
    for existing in devices:
        if existing.id == device.id:
            updated.append(device)
            replaced = True
        else:
            updated.append(existing)
    if not replaced:
        updated.append(device)
    save_devices(updated)
    return updated


def delete_device(device_id: str) -> list[NetworkDevice]:
    devices = [device for device in list_devices() if device.id != device_id]
    save_devices(devices)
    return devices


def _save_reordered_devices_for_kind(
    devices: list[NetworkDevice],
    kind: str,
    ordered_ids: list[str],
) -> list[NetworkDevice]:
    expected_ids = [
        device.id for device in devices if normalize_kind(device.kind) == kind
    ]
    _validate_kind_order(kind, expected_ids, ordered_ids)
    by_id = {device.id: device for device in devices}
    ordered_devices = iter(by_id[device_id] for device_id in ordered_ids)
    updated: list[NetworkDevice] = []
    for device in devices:
        if normalize_kind(device.kind) == kind:
            updated.append(next(ordered_devices))
        else:
            updated.append(device)
    save_devices(updated)
    return updated


def _validate_kind_order(kind: str, expected_ids: list[str], ordered_ids: list[str]) -> None:
    seen: set[str] = set()
    duplicate_ids: list[str] = []
    for device_id in ordered_ids:
        if device_id in seen and device_id not in duplicate_ids:
            duplicate_ids.append(device_id)
        seen.add(device_id)

    expected = set(expected_ids)
    requested = set(ordered_ids)
    missing_ids = [device_id for device_id in expected_ids if device_id not in requested]
    extra_ids = [device_id for device_id in ordered_ids if device_id not in expected]

    problems: list[str] = []
    if duplicate_ids:
        problems.append(f"duplicate ids: {', '.join(duplicate_ids)}")
    if missing_ids:
        problems.append(f"missing ids: {', '.join(missing_ids)}")
    if extra_ids:
        problems.append(f"unknown ids: {', '.join(extra_ids)}")
    if problems:
        raise NetworkConfigError(
            f"invalid network device order for {kind}: " + "; ".join(problems)
        )


def _ip_sort_key(value: str) -> int:
    try:
        return int(ipaddress.IPv4Address(value))
    except ValueError:
        return -1
