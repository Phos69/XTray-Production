"""EDID parsing and Windows monitor registry readers.

Why a separate module: the EDID bit unpacking and the
``SYSTEM\\CurrentControlSet\\Enum\\DISPLAY`` registry lookup are
self-contained and have no dependency on the apply/plan/topology
machinery — keeping them isolated makes both halves easier to test and
unblocks the main module from carrying ~200 LOC of registry boilerplate.
"""
from __future__ import annotations

from typing import Any

from xtray.core import app_logging

_MANUFACTURER_NAMES = {
    "ACR": "Acer",
    "AOC": "AOC",
    "APP": "Apple",
    "AUO": "AU Optronics",
    "BNQ": "BenQ",
    "CMN": "Chimei Innolux",
    "DEL": "Dell",
    "GSM": "LG",
    "HEC": "Hisense",
    "HPN": "HP",
    "IVM": "Iiyama",
    "LEN": "Lenovo",
    "PHL": "Philips",
    "SAM": "Samsung",
    "SNY": "Sony",
    "VSC": "ViewSonic",
}


def _read_monitor_edid(device_id: str) -> bytes | None:
    path = _monitor_registry_path(device_id)
    if path is None:
        return None
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
        value, _value_type = winreg.QueryValueEx(key, "EDID")
    except Exception as exc:
        app_logging.get_logger("display").warning(
            "could not read EDID for %s from registry path %s: %s",
            device_id,
            path,
            exc,
            exc_info=True,
        )
        return None
    return bytes(value) if isinstance(value, bytes | bytearray) else None


def _read_monitor_container_id(device_id: str) -> str | None:
    """Read the Windows ``ContainerID`` GUID of a physical monitor.

    Why: ContainerID is assigned by the OS to the physical device and survives
    cable swaps and adapter route changes, while ``device_id`` and
    ``adapter_name`` can change. ``Device Parameters`` sits one level below
    the device instance key, so the GUID lives at the parent of the path
    returned by ``_monitor_registry_path``.
    """
    device_path = _monitor_registry_path(device_id)
    if device_path is None:
        return None
    parent = device_path.rsplit("\\", 1)[0]
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, parent)
        value, _value_type = winreg.QueryValueEx(key, "ContainerID")
    except Exception as exc:
        app_logging.get_logger("display").warning(
            "could not read ContainerID for %s from registry path %s: %s",
            device_id,
            parent,
            exc,
            exc_info=True,
        )
        return None
    if isinstance(value, str) and value:
        return value
    return None


def _monitor_registry_path(device_id: str) -> str | None:
    parsed = _monitor_registry_root_and_driver(device_id)
    if parsed is None:
        return None
    root_path, driver_id = parsed
    exact_path = f"{root_path}\\{driver_id}\\Device Parameters"
    if _registry_key_exists(exact_path):
        return exact_path
    return _find_monitor_registry_path_by_driver(root_path, driver_id)


def _monitor_registry_root_and_driver(device_id: str) -> tuple[str, str] | None:
    parts = device_id.split("\\")
    if len(parts) < 3 or parts[0] != "MONITOR":
        return None
    root_path = f"SYSTEM\\CurrentControlSet\\Enum\\DISPLAY\\{parts[1]}"
    driver_id = "\\".join(parts[2:])
    return root_path, driver_id


def _registry_key_exists(path: str) -> bool:
    try:
        import winreg

        winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
    except Exception:
        return False
    return True


def _find_monitor_registry_path_by_driver(root_path: str, driver_id: str) -> str | None:
    try:
        import winreg

        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root_path)
        count = winreg.QueryInfoKey(root)[0]
        for index in range(count):
            instance = winreg.EnumKey(root, index)
            instance_path = f"{root_path}\\{instance}"
            try:
                instance_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, instance_path)
                driver_value, _value_type = winreg.QueryValueEx(instance_key, "Driver")
            except Exception as exc:
                app_logging.get_logger("display").debug(
                    "skipping monitor registry instance %s: %s",
                    instance_path,
                    exc,
                    exc_info=True,
                )
                continue
            if driver_value == driver_id:
                device_parameters = f"{instance_path}\\Device Parameters"
                if _registry_key_exists(device_parameters):
                    return device_parameters
    except Exception as exc:
        app_logging.get_logger("display").warning(
            "could not scan monitor registry root %s for driver %s: %s",
            root_path,
            driver_id,
            exc,
            exc_info=True,
        )
        return None
    return None


def _parse_edid(edid: bytes) -> dict[str, Any]:
    if len(edid) < 128:
        return {}
    manufacturer_id = _decode_edid_manufacturer(edid[8], edid[9])
    product_code = f"{edid[11] << 8 | edid[10]:04X}"
    width_cm = edid[21] or None
    height_cm = edid[22] or None
    diagonal_inches = None
    if width_cm and height_cm:
        diagonal_inches = round(((width_cm**2 + height_cm**2) ** 0.5) / 2.54, 1)
    descriptors = _parse_edid_descriptors(edid)
    serial_number = descriptors.get("serial")
    if not serial_number:
        serial_value = int.from_bytes(edid[12:16], "little")
        serial_number = str(serial_value) if serial_value else None
    return {
        "manufacturer_id": manufacturer_id,
        "manufacturer": _MANUFACTURER_NAMES.get(manufacturer_id, manufacturer_id),
        "product_code": product_code,
        "model": descriptors.get("model"),
        "serial_number": serial_number,
        "physical_width_cm": width_cm,
        "physical_height_cm": height_cm,
        "diagonal_inches": diagonal_inches,
        "manufacture_year": 1990 + edid[17] if edid[17] else None,
    }


def _decode_edid_manufacturer(byte_a: int, byte_b: int) -> str:
    value = (byte_a << 8) | byte_b
    chars = [
        chr(((value >> 10) & 0x1F) + 64),
        chr(((value >> 5) & 0x1F) + 64),
        chr((value & 0x1F) + 64),
    ]
    return "".join(chars)


def _parse_edid_descriptors(edid: bytes) -> dict[str, str]:
    descriptors: dict[str, str] = {}
    for offset in (54, 72, 90, 108):
        block = edid[offset : offset + 18]
        if len(block) < 18 or block[:3] != b"\x00\x00\x00":
            continue
        tag = block[3]
        text = _decode_edid_text(block[5:18])
        if not text:
            continue
        if tag == 0xFC:
            descriptors["model"] = text
        elif tag == 0xFF:
            descriptors["serial"] = text
    return descriptors


def _decode_edid_text(raw: bytes) -> str:
    text = raw.split(b"\n", 1)[0].split(b"\x00", 1)[0]
    return text.decode("ascii", errors="ignore").strip()
