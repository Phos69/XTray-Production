"""Module-level helpers used by the Computer Manager MainWindow.

These were previously appended at the bottom of `app.py` and account for
~250 LOC of pure functions: Qt widget helpers, display
reconcile/identity matching across enabled/disabled/historical lists,
small formatters and the runtime diagnostics dumper. None of them touch
mutable MainWindow state — they receive everything they need as
arguments — so they live in their own module to keep `app.py` focused on
event handling and lifecycle.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from xtray.core import app_logging
from xtray.core.gui import set_button_role as _core_set_button_role

import computer_manager as _computer_manager_pkg

from . import audio_manager as audio
from .display_manager import backend as display
from .display_manager import profiles
from .display_manager.backend import DisplayState, stable_display_key

_DISPLAY_IDENTITY_FIELDS = (
    "device_id",
    "name",
    "manufacturer_id",
    "manufacturer",
    "product_code",
    "model",
    "serial_number",
    "physical_width_cm",
    "physical_height_cm",
    "diagonal_inches",
    "manufacture_year",
)


def _set_button_role(button: Any, role: str, qt: Any | None = None) -> None:
    _core_set_button_role(button, role)
    if qt is not None:
        button.setCursor(qt.CursorShape.PointingHandCursor)


def _set_blocked_value(widget: Any, value: int) -> None:
    was_blocked = widget.blockSignals(True)
    try:
        widget.setValue(value)
    finally:
        widget.blockSignals(was_blocked)


def _select_combo_data(widget: Any, value: Any) -> None:
    for index in range(widget.count()):
        if widget.itemData(index) == value:
            widget.setCurrentIndex(index)
            return
    widget.setCurrentIndex(0)


def _reconcile_enabled_profile_displays(
    profile_displays: list[DisplayState],
    windows_displays: list[DisplayState],
    history_by_stable_key: dict[str, DisplayState] | None = None,
) -> None:
    active_displays = [
        display_state for display_state in windows_displays if display_state.enabled
    ]
    for profile_display in profile_displays:
        if not profile_display.enabled:
            continue
        current = _find_matching_display(active_displays, profile_display)
        if current is not None:
            _copy_display_identity(current, profile_display)
            continue
        historical = _find_matching_history_display(
            history_by_stable_key or {},
            profile_display,
        )
        if historical is None:
            continue
        identity_changed = (
            bool(profile_display.device_id and historical.device_id)
            and profile_display.device_id.casefold() != historical.device_id.casefold()
        )
        _copy_display_identity(historical, profile_display)
        if identity_changed:
            _copy_display_default_mode(historical, profile_display)


def _copy_display_identity(source: DisplayState, target: DisplayState) -> None:
    for field_name in _DISPLAY_IDENTITY_FIELDS:
        setattr(target, field_name, getattr(source, field_name))


def _copy_display_default_mode(source: DisplayState, target: DisplayState) -> None:
    target.width = source.width
    target.height = source.height
    target.refresh_hz = source.refresh_hz


def _copy_display_state(source: DisplayState, target: DisplayState) -> None:
    for field_name in DisplayState.__dataclass_fields__:
        setattr(target, field_name, getattr(source, field_name))


def _remove_redundant_disabled_profile_displays(
    displays: list[DisplayState],
    *,
    selected_display: DisplayState | None = None,
) -> DisplayState | None:
    """Drop disabled profile entries that duplicate an enabled or sibling entry.

    Why: as the user toggles a monitor between enabled and disabled in the
    editor, the profile can accumulate two entries with the same physical
    identity (one enabled, one disabled). Identity is taken from
    ``stable_display_key`` so the same Iiyama is collapsed even if its
    ``adapter_name`` was rerouted by Windows between sessions.
    """
    drop_ids: set[int] = set()
    enabled_displays = [display_state for display_state in displays if display_state.enabled]
    for display_state in displays:
        if display_state.enabled:
            continue
        if _find_matching_display(enabled_displays, display_state) is not None:
            drop_ids.add(id(display_state))

    seen_disabled: list[DisplayState] = []
    for display_state in displays:
        if display_state.enabled or id(display_state) in drop_ids:
            continue
        duplicate = _find_matching_display(seen_disabled, display_state)
        if duplicate is not None:
            if selected_display is not None and display_state is selected_display:
                drop_ids.add(id(duplicate))
                seen_disabled = [item for item in seen_disabled if item is not duplicate]
                seen_disabled.append(display_state)
            else:
                drop_ids.add(id(display_state))
                continue
        else:
            seen_disabled.append(display_state)

    if not drop_ids:
        return selected_display

    replacement = selected_display
    displays[:] = [display_state for display_state in displays if id(display_state) not in drop_ids]
    if replacement is not None and id(replacement) in drop_ids:
        replacement = _find_matching_display(displays, replacement)
    return replacement


def _merge_available_display_history(
    windows_displays: list[DisplayState],
    history_by_stable_key: dict[str, DisplayState],
) -> list[DisplayState]:
    """Enrich inactive Windows displays with metadata from saved profiles.

    Why: Windows often returns a generic ``Generic PnP Monitor`` for inactive
    routes, hiding which physical monitor that route belongs to. When the
    user has already saved a profile referencing the same ``stable_id``,
    reuse that profile's metadata so the shelf shows a meaningful label.
    Source displays are already deduped per physical monitor by
    ``list_available_displays`` so no further dedupe is required here.
    """
    merged: list[DisplayState] = []
    for windows_display in windows_displays:
        if windows_display.enabled:
            merged.append(windows_display)
            continue
        historical = _find_matching_history_display(
            history_by_stable_key,
            windows_display,
        )
        if historical is not None and not _has_display_identity(windows_display):
            display_state = DisplayState.from_dict(historical.to_dict())
            display_state.enabled = False
            display_state.primary = False
            display_state.adapter_name = windows_display.adapter_name
            merged.append(display_state)
            continue
        merged.append(windows_display)
    return merged


def _enabled_profile_display_history_by_stable_key() -> dict[str, DisplayState]:
    history: dict[str, DisplayState] = {}
    for profile_name in profiles.list_profiles():
        try:
            profile = profiles.load_profile(profile_name)
        except Exception:
            app_logging.get_logger("gui").exception(
                "failed to load profile history from %s", profile_name
            )
            continue
        for display_state in profile.displays:
            if not display_state.enabled:
                continue
            key = stable_display_key(display_state)
            if key in history or _find_matching_display(
                list(history.values()), display_state
            ):
                continue
            history[key] = display_state
    return history


def _has_display_identity(display_state: DisplayState) -> bool:
    return bool(
        display_state.manufacturer_id
        or display_state.manufacturer
        or display_state.product_code
        or display_state.model
        or display_state.serial_number
    )


def _audio_object_label(source: audio.AudioSource | None) -> str:
    return source.label() if source is not None else "(none)"


def _ha_service_data_text(data: dict[str, Any] | None) -> str:
    if not data:
        return ""
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def _find_matching_display(
    displays: list[DisplayState], target: DisplayState
) -> DisplayState | None:
    for display_state in displays:
        if display.display_identity_matches(display_state, target):
            return display_state
    return None


def _find_matching_history_display(
    history_by_stable_key: dict[str, DisplayState],
    target: DisplayState,
) -> DisplayState | None:
    historical = history_by_stable_key.get(stable_display_key(target))
    if historical is not None:
        return historical
    return _find_matching_display(list(history_by_stable_key.values()), target)


def _print_console_message(label: str, message: str, *, stream: Any) -> None:
    print(f"[ComputerManager] {label}", file=stream, flush=True)
    for line in message.splitlines() or [""]:
        print(line, file=stream, flush=True)


def _print_runtime_diagnostics(app_module_file: str) -> None:
    """Dump python/package/display/gui module paths to stdout.

    The GUI module path is passed in by the caller because at import time
    `_helpers.__file__` would point here, not at `app.py`.
    """
    _print_console_message(
        "RUNTIME",
        app_logging.redact(
            "\n".join(
                [
                    f"python={sys.executable}",
                    f"package={_computer_manager_pkg.__file__}",
                    f"display={display.__file__}",
                    f"gui={app_module_file}",
                ]
            )
        ),
        stream=sys.stdout,
    )
