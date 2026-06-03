"""Display inventory helpers shared by GUI, tray, and MQTT."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from xtray import config
from xtray.core import app_logging

from ..audio_manager import core as audio
from . import backend as display
from . import profiles
from .backend import DisplayState

_UNSET = object()


@dataclass(frozen=True)
class DisplayInventoryItem:
    display: DisplayState
    key: str
    aliases: tuple[str, ...]
    assigned_profiles: list[str]
    available: bool
    enabled: bool
    expose_hdmi_volume: bool
    friendly_name: str | None = None
    volume_control: str = config.VOLUME_CONTROL_NONE
    volume_ha_entity: str | None = None
    power_on_ha_service: str | None = None
    power_on_ha_service_data: dict[str, Any] | None = None
    power_off_ha_service: str | None = None
    power_off_ha_service_data: dict[str, Any] | None = None
    default_width: int | None = None
    default_height: int | None = None
    default_refresh_hz: int | None = None
    default_orientation: int | None = None


def collect_display_inventory(
    *,
    available_displays: list[DisplayState] | None = None,
    profile_names: Iterable[str] | None = None,
) -> list[DisplayInventoryItem]:
    """Return one item per physical display known from Windows or profiles."""
    logger = app_logging.get_logger("display_inventory")
    if available_displays is None:
        try:
            available_displays = profiles.list_available_displays()
        except Exception:
            logger.exception("failed to enumerate display inventory from Windows")
            available_displays = []

    names = list(profile_names) if profile_names is not None else profiles.list_profiles()
    records: list[tuple[DisplayState, bool, str | None]] = [
        (display_state, True, None) for display_state in available_displays
    ]
    for profile_name in names:
        try:
            profile = profiles.load_profile(profile_name)
        except Exception:
            logger.exception("failed to load profile %s for display inventory", profile_name)
            continue
        for display_state in profile.displays:
            if display_state.enabled:
                records.append((display_state, False, profile_name))

    buckets: list[dict[str, object]] = []
    for display_state, available, profile_name in records:
        bucket = _find_bucket(buckets, display_state)
        if bucket is None:
            bucket = {
                "display": display_state,
                "available": bool(available),
                "enabled": bool(display_state.enabled and available),
                "profiles": set(),
                "source_score": _display_score(display_state, available),
            }
            buckets.append(bucket)
        else:
            bucket["available"] = bool(bucket["available"]) or bool(available)
            bucket["enabled"] = bool(bucket["enabled"]) or bool(display_state.enabled and available)
            score = _display_score(display_state, available)
            if score > int(bucket["source_score"]):
                bucket["display"] = display_state
                bucket["source_score"] = score
        if profile_name is not None:
            profiles_set = bucket["profiles"]
            assert isinstance(profiles_set, set)
            profiles_set.add(profile_name)

    items: list[DisplayInventoryItem] = []
    for bucket in buckets:
        display_state = bucket["display"]
        assert isinstance(display_state, DisplayState)
        profiles_set = bucket["profiles"]
        assert isinstance(profiles_set, set)
        key = display.stable_display_key(display_state)
        aliases = display_identity_keys(display_state)
        setting = volume_control_setting(display_state)
        mode = setting["volume_control"]
        ha_entity = setting["volume_ha_entity"]
        friendly_name = friendly_name_setting(display_state)
        power_services = home_assistant_power_setting(display_state)
        defaults = display_defaults_setting(display_state)
        items.append(
            DisplayInventoryItem(
                display=display_state,
                key=key,
                aliases=aliases,
                assigned_profiles=sorted(str(name) for name in profiles_set),
                available=bool(bucket["available"]),
                enabled=bool(bucket["enabled"]),
                expose_hdmi_volume=mode == config.VOLUME_CONTROL_HDMI,
                friendly_name=friendly_name,
                volume_control=mode,
                volume_ha_entity=ha_entity,
                power_on_ha_service=power_services["power_on_ha_service"],
                power_on_ha_service_data=power_services["power_on_ha_service_data"],
                power_off_ha_service=power_services["power_off_ha_service"],
                power_off_ha_service_data=power_services["power_off_ha_service_data"],
                default_width=defaults["default_width"],
                default_height=defaults["default_height"],
                default_refresh_hz=defaults["default_refresh_hz"],
                default_orientation=defaults["default_orientation"],
            )
        )
    return _sort_inventory_items(items)


def reorder_display_inventory(
    ordered_keys: list[str] | tuple[str, ...],
) -> list[DisplayInventoryItem]:
    """Persist a user-defined display order and return the reordered inventory."""
    config.set_display_order(list(ordered_keys))
    return collect_display_inventory()


def display_identity_keys(display_state: DisplayState) -> tuple[str, ...]:
    keys: list[str] = [display.stable_display_key(display_state)]
    keys.extend(display.display_identity_aliases(display_state))
    return tuple(dict.fromkeys(key.casefold() for key in keys if key))


def assigned_profiles_for_display(
    display_state: DisplayState,
    *,
    profile_names: Iterable[str] | None = None,
) -> list[str]:
    names = list(profile_names) if profile_names is not None else profiles.list_profiles()
    assigned: list[str] = []
    for profile_name in names:
        try:
            profile = profiles.load_profile(profile_name)
        except Exception:
            app_logging.get_logger("display_inventory").exception(
                "failed to load profile %s for display assignment", profile_name
            )
            continue
        if any(
            candidate.enabled and _display_matches(candidate, display_state)
            for candidate in profile.displays
        ):
            assigned.append(profile_name)
    return sorted(assigned)


def volume_control_setting(display_state: DisplayState) -> dict[str, Any]:
    keys = display_identity_keys(display_state)
    entry = config.get_display_setting_for_keys(keys)
    mode = entry.get("volume_control", config.VOLUME_CONTROL_NONE)
    ha_entity = entry.get("volume_ha_entity") if mode == config.VOLUME_CONTROL_HA_ENTITY else None
    _migrate_display_setting(display_state, mode=mode, ha_entity=ha_entity)
    return {"volume_control": mode, "volume_ha_entity": ha_entity}


def hdmi_volume_exposed(display_state: DisplayState) -> bool:
    return volume_control_setting(display_state)["volume_control"] == config.VOLUME_CONTROL_HDMI


def friendly_name_setting(display_state: DisplayState) -> str | None:
    keys = display_identity_keys(display_state)
    entry = config.get_display_setting_for_keys(keys)
    friendly_name = entry.get("friendly_name")
    _migrate_display_setting(display_state, friendly_name=friendly_name)
    return str(friendly_name).strip() if friendly_name else None


def set_friendly_name(display_state: DisplayState, friendly_name: str | None) -> None:
    config.set_display_setting_for_keys(
        display.stable_display_key(display_state),
        display_identity_keys(display_state),
        friendly_name=friendly_name,
    )


def set_hdmi_volume_exposed(display_state: DisplayState, exposed: bool) -> None:
    set_volume_control(
        display_state,
        config.VOLUME_CONTROL_HDMI if exposed else config.VOLUME_CONTROL_NONE,
    )


def set_volume_control(
    display_state: DisplayState,
    mode: str,
    *,
    ha_entity: str | None = None,
) -> None:
    config.set_display_setting_for_keys(
        display.stable_display_key(display_state),
        display_identity_keys(display_state),
        volume_control=mode,
        volume_ha_entity=ha_entity,
    )


def home_assistant_power_setting(display_state: DisplayState) -> dict[str, Any]:
    keys = display_identity_keys(display_state)
    entry = config.get_display_setting_for_keys(keys)
    return {
        "power_on_ha_service": entry.get("power_on_ha_service"),
        "power_on_ha_service_data": entry.get("power_on_ha_service_data"),
        "power_off_ha_service": entry.get("power_off_ha_service"),
        "power_off_ha_service_data": entry.get("power_off_ha_service_data"),
    }


def set_home_assistant_power_services(
    display_state: DisplayState,
    *,
    power_on_service: object = _UNSET,
    power_on_data: object = _UNSET,
    power_off_service: object = _UNSET,
    power_off_data: object = _UNSET,
) -> None:
    kwargs: dict[str, Any] = {}
    if power_on_service is not _UNSET:
        kwargs["power_on_ha_service"] = power_on_service
    if power_on_data is not _UNSET:
        kwargs["power_on_ha_service_data"] = power_on_data
    if power_off_service is not _UNSET:
        kwargs["power_off_ha_service"] = power_off_service
    if power_off_data is not _UNSET:
        kwargs["power_off_ha_service_data"] = power_off_data
    config.set_display_setting_for_keys(
        display.stable_display_key(display_state),
        display_identity_keys(display_state),
        **kwargs,
    )


def display_defaults_setting(display_state: DisplayState) -> dict[str, int | None]:
    """Per-display defaults applied when the display is enabled in a profile.

    Returned dict always contains the four keys; values are ``None`` when no
    default is configured.
    """
    keys = display_identity_keys(display_state)
    entry = config.get_display_setting_for_keys(keys)
    return {
        "default_width": entry.get("default_width"),
        "default_height": entry.get("default_height"),
        "default_refresh_hz": entry.get("default_refresh_hz"),
        "default_orientation": entry.get("default_orientation"),
    }


def set_display_defaults(display_state: DisplayState, **fields: Any) -> None:
    """Persist per-display default resolution/refresh/orientation.

    Accepted keyword arguments: ``width``, ``height``, ``refresh_hz``,
    ``orientation``. Pass ``None`` for a field to clear it; omit the kwarg to
    leave it unchanged.
    """
    unknown = sorted(set(fields) - {"width", "height", "refresh_hz", "orientation"})
    if unknown:
        raise TypeError(f"unexpected keyword arguments: {', '.join(unknown)}")
    kwargs: dict[str, Any] = {}
    if "width" in fields:
        kwargs["default_width"] = fields["width"]
    if "height" in fields:
        kwargs["default_height"] = fields["height"]
    if "refresh_hz" in fields:
        kwargs["default_refresh_hz"] = fields["refresh_hz"]
    if "orientation" in fields:
        kwargs["default_orientation"] = fields["orientation"]
    config.set_display_setting_for_keys(
        display.stable_display_key(display_state),
        display_identity_keys(display_state),
        **kwargs,
    )


def apply_display_defaults(display_state: DisplayState) -> bool:
    """Override resolution/refresh/orientation on ``display_state`` in place.

    Each field is only overwritten when a corresponding default is configured.
    Returns ``True`` when at least one field was modified.
    """
    defaults = display_defaults_setting(display_state)
    changed = False
    width = defaults["default_width"]
    height = defaults["default_height"]
    if width and height:
        if display_state.width != width or display_state.height != height:
            display_state.width = width
            display_state.height = height
            changed = True
    refresh = defaults["default_refresh_hz"]
    if refresh and display_state.refresh_hz != refresh:
        display_state.refresh_hz = refresh
        changed = True
    orientation = defaults["default_orientation"]
    if orientation is not None and display_state.orientation != orientation:
        display_state.orientation = orientation
        changed = True
    return changed


def exposed_hdmi_volume_displays(
    *,
    available_displays: list[DisplayState] | None = None,
) -> list[DisplayState]:
    return [
        item.display
        for item in collect_display_inventory(available_displays=available_displays)
        if item.expose_hdmi_volume
    ]


def display_matches_audio_source(
    display_state: DisplayState,
    source: audio.AudioSource | None,
) -> bool:
    """Heuristic: does this audio endpoint belong to this display?

    Why: Windows has no first-class link between a DisplayState and an audio
    endpoint. For HDMI/DP outputs the endpoint name typically contains the
    monitor's manufacturer or model, so a case-insensitive substring match is
    the most reliable signal we can compute without per-display config.
    """
    if source is None:
        return False
    candidates: list[str] = []
    for value in (
        display_state.model,
        display_state.manufacturer,
        display_state.name,
    ):
        if value:
            candidates.append(value.strip())
    label_first_line = display_state.display_label().splitlines()[0]
    if label_first_line:
        candidates.append(label_first_line.strip())
    candidates = [c.casefold() for c in candidates if c]
    target_parts = [source.name or "", source.interface_name or ""]
    target = " ".join(part for part in target_parts if part).casefold()
    if not candidates or not target:
        return False
    return any(c in target or target in c for c in candidates)


def active_volume_display(
    *,
    source: audio.AudioSource | None = None,
    available_displays: list[DisplayState] | None = None,
) -> DisplayInventoryItem | None:
    """Return the inventory item to render the volume slider for, or ``None``.

    The rule: the display whose volume_control mode is not ``none`` AND whose
    audio endpoint matches the currently active audio source.
    """
    if source is None:
        try:
            source = audio.get_default_audio_source()
        except Exception:
            app_logging.get_logger("display_inventory").exception(
                "failed to read default audio source"
            )
            source = None
    if source is None:
        return None
    items = collect_display_inventory(available_displays=available_displays)
    for item in items:
        if item.volume_control == config.VOLUME_CONTROL_NONE:
            continue
        if display_matches_audio_source(item.display, source):
            return item
    return None


def display_volume_entity_key(display_state: DisplayState) -> str:
    return display.stable_display_key(display_state)


def display_title(display_state: DisplayState) -> str:
    friendly_name = friendly_name_setting(display_state)
    if friendly_name:
        return friendly_name
    return display_state.display_label().splitlines()[0] or display_state.name


def _find_bucket(
    buckets: list[dict[str, object]], target: DisplayState
) -> dict[str, object] | None:
    for bucket in buckets:
        candidate = bucket["display"]
        assert isinstance(candidate, DisplayState)
        if _display_matches(candidate, target):
            return bucket
    return None


def _display_matches(left: DisplayState, right: DisplayState) -> bool:
    if display.display_identity_matches(left, right):
        return True
    return bool(set(display_identity_keys(left)) & set(display_identity_keys(right)))


def _display_score(display_state: DisplayState, available: bool) -> int:
    score = 0
    if available:
        score += 100
    if display_state.enabled:
        score += 40
    score += 5 * len(display.display_identity_aliases(display_state))
    for field_name in (
        "manufacturer_id",
        "manufacturer",
        "product_code",
        "model",
        "serial_number",
        "container_id",
        "edid_hash",
    ):
        if getattr(display_state, field_name):
            score += 2
    if display_state.adapter_name:
        score += 1
    return score


def _sort_inventory_items(
    items: list[DisplayInventoryItem],
) -> list[DisplayInventoryItem]:
    """Order inventory by the user's saved order, falling back to availability.

    Displays the user has explicitly placed (via drag-and-drop in the GUI) come
    first, in that order. Anything not yet ordered keeps the previous default:
    available displays before saved ones, then alphabetically by title.
    """
    order = config.get_display_order()
    index_by_key = {key: position for position, key in enumerate(order)}

    def sort_key(item: DisplayInventoryItem) -> tuple[int, int, str]:
        positions = [
            index_by_key[alias] for alias in item.aliases if alias in index_by_key
        ]
        if positions:
            return (0, min(positions), "")
        return (
            1,
            0 if item.available else 1,
            display_title(item.display).casefold(),
        )

    return sorted(items, key=sort_key)


def _migrate_display_setting(
    display_state: DisplayState,
    *,
    mode: str | None = None,
    ha_entity: str | None = None,
    friendly_name: str | None = None,
) -> None:
    keys = display_identity_keys(display_state)
    canonical = display.stable_display_key(display_state).casefold()
    settings = config.get_display_settings()
    if canonical in settings:
        return
    if not any(key in settings for key in keys if key != canonical):
        return
    kwargs: dict[str, Any] = {}
    if mode is not None:
        kwargs["volume_control"] = mode
        kwargs["volume_ha_entity"] = ha_entity
    if friendly_name is not None:
        kwargs["friendly_name"] = friendly_name
    config.set_display_setting_for_keys(canonical, keys, **kwargs)
