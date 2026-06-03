"""Shared display identity helpers."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from xtray.core import app_logging

if TYPE_CHECKING:
    from .backend.models import DisplayState


def stable_display_key(display_state: DisplayState) -> str:
    """Canonical, stable identity for a physical monitor."""
    if display_state.container_id:
        return f"container:{display_state.container_id.casefold()}"
    if display_state.edid_hash:
        return f"edid:{display_state.edid_hash.casefold()}"
    if (
        display_state.manufacturer_id
        and display_state.product_code
        and display_state.serial_number
    ):
        return (
            f"edid:{display_state.manufacturer_id.casefold()}:"
            f"{display_state.product_code.casefold()}:"
            f"{display_state.serial_number.casefold()}"
        )
    if display_state.device_id:
        return f"device:{display_state.device_id.casefold()}"
    if display_state.adapter_name:
        return f"adapter:{display_state.adapter_name.casefold()}"
    app_logging.get_logger("display").warning(
        "stable_display_key falling back to display name; identity is unreliable: %s",
        display_state.name,
    )
    return f"name:{display_state.name.casefold()}"


def display_identity_aliases(display_state: DisplayState) -> tuple[str, ...]:
    """Return every strong identity known for a physical monitor."""
    aliases: list[str] = []

    def add(prefix: str, value: Any) -> None:
        normalized = _normalize_identity_value(value)
        if normalized:
            aliases.append(f"{prefix}:{normalized}")

    add("container", display_state.container_id)
    add("edid", display_state.edid_hash)
    if (
        display_state.manufacturer_id
        and display_state.product_code
        and display_state.serial_number
    ):
        aliases.append(
            "edid:"
            f"{_normalize_identity_value(display_state.manufacturer_id)}:"
            f"{_normalize_identity_value(display_state.product_code)}:"
            f"{_normalize_identity_value(display_state.serial_number)}"
        )
    add("device", display_state.device_id)
    return tuple(dict.fromkeys(aliases))


def display_identity_matches(left: DisplayState, right: DisplayState) -> bool:
    """Return whether two display descriptions can refer to the same monitor."""
    if _display_identity_conflicts(left, right):
        return False
    return bool(set(display_identity_aliases(left)) & set(display_identity_aliases(right)))


def display_match_aliases(display_state: DisplayState) -> set[str]:
    aliases = set(display_identity_aliases(display_state))
    if aliases:
        return aliases
    return {stable_display_key(display_state)}


def _normalize_identity_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().casefold()


def _display_identity_values(display_state: DisplayState) -> dict[str, str]:
    values: dict[str, str] = {}
    container_id = _normalize_identity_value(display_state.container_id)
    if container_id:
        values["container"] = container_id
    edid_hash = _normalize_identity_value(display_state.edid_hash)
    if edid_hash:
        values["edid_hash"] = edid_hash
    if (
        display_state.manufacturer_id
        and display_state.product_code
        and display_state.serial_number
    ):
        values["edid_triple"] = (
            f"{_normalize_identity_value(display_state.manufacturer_id)}:"
            f"{_normalize_identity_value(display_state.product_code)}:"
            f"{_normalize_identity_value(display_state.serial_number)}"
        )
    device_id = _normalize_identity_value(display_state.device_id)
    if device_id:
        values["device"] = device_id
    return values


def _display_identity_conflicts(left: DisplayState, right: DisplayState) -> bool:
    left_values = _display_identity_values(left)
    right_values = _display_identity_values(right)
    for category in ("container", "edid_hash", "edid_triple"):
        left_value = left_values.get(category)
        right_value = right_values.get(category)
        if left_value and right_value and left_value != right_value:
            return True

    left_device = left_values.get("device")
    right_device = right_values.get("device")
    matching_aliases = set(display_identity_aliases(left)) & set(
        display_identity_aliases(right)
    )
    return bool(
        left_device
        and right_device
        and left_device != right_device
        and not matching_aliases
    )
