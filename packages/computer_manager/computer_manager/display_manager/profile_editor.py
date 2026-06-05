"""Controller for the profile-editing surface of Computer Manager.

Owns the preview scene, the object list, the per-display / per-audio form,
and the capture / save / apply / delete workflow. Lifted out of
``computer_manager.app`` so MainWindow stays focused on orchestration.

The controller keeps a back-reference to the host MainWindow so it can read
the widgets created by ``_layout_builder`` and call shared services
(``show_error`` / ``show_info``, ``_run_in_thread``, ``refresh_profiles``).
The ``_updating_form`` flag stays on the host because the inventory tab
controller also needs it.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from xtray.core import app_logging

from .. import audio_manager as audio
from .._helpers import (
    _audio_object_label,
    _copy_display_state,
    _enabled_profile_display_history_by_stable_key,
    _find_matching_display,
    _merge_available_display_history,
    _reconcile_enabled_profile_displays,
    _remove_redundant_disabled_profile_displays,
    _select_combo_data,
    _set_blocked_value,
)
from . import inventory as display_inventory
from . import messages, profiles
from .backend import DisplayMode, DisplayState, SystemState, stable_display_key
from .geometry import ensure_enabled_primary
from .scene_items import MonitorItem
from .ui_model import (
    disambiguate_labels,
    display_object_id,
    format_resolution,
    normalize_display_geometry,
    preview_layout,
    profile_object_layout,
    refresh_rate_options,
    resolution_options,
    scene_to_display_position,
)

SCALE = 0.12

_format_apply_result = messages.format_apply_result


@dataclass(frozen=True)
class PreviewPayload:
    """Result of a `load_current_preview` worker call.

    Centralised so all WinAPI/COM calls happen on the worker thread; the GUI
    thread just consumes pre-built data.
    """

    state: SystemState
    default_audio: audio.AudioSource | None
    audio_sources: list[audio.AudioSource]
    audio_volume_percent: int | None = None
    audio_muted: bool | None = None


class ProfileEditor:  # pragma: no cover - imported only when GUI dependencies exist
    def __init__(self, host: Any) -> None:
        self._host = host
        self._profile: profiles.Profile | None = None
        self._pristine_profile: profiles.Profile | None = None
        self._selected_display: DisplayState | None = None
        self._selection_kind: str = "display"
        self._preview_origin = (0, 0)
        self._preview_scene_offset = (0.0, 0.0)
        self._display_modes_cache: dict[str, list[DisplayMode]] = {}
        self._available_displays: list[DisplayState] = []
        self._label_suffixes: dict[str, str] = {}
        self._populating_object_list = False

    def load_profile(self, name: str) -> None:
        host = self._host
        if not name:
            return
        try:
            loaded = profiles.load_profile(name)
        except Exception as exc:
            host.show_error(str(exc))
            return
        self._pristine_profile = loaded
        self._profile = copy.deepcopy(loaded)
        host.profile_name.setText(self._profile.name)
        self._selected_display = self._profile.displays[0] if self._profile.displays else None
        self._selection_kind = "display" if self._selected_display is not None else "audio"
        self.refresh_available_displays()
        self.redraw_scene()
        self.populate_audio_combo()
        self.populate_form()

    def refresh_available_displays(self) -> None:
        try:
            windows_displays = profiles.list_available_displays()
        except Exception:
            app_logging.get_logger("gui").exception("failed to enumerate available displays")
            self._available_displays = []
            return
        history_by_stable_key = _enabled_profile_display_history_by_stable_key()
        if self._profile is not None:
            _reconcile_enabled_profile_displays(
                self._profile.displays,
                windows_displays,
                history_by_stable_key,
            )
        self._available_displays = _merge_available_display_history(
            windows_displays,
            history_by_stable_key,
        )

    def redraw_scene(self) -> None:
        host = self._host
        host.scene.clear()
        self._preview_scene_offset = (0.0, 0.0)
        if self._profile is None:
            self.refresh_object_list()
            return
        self._normalize_profile_geometry()
        enabled_displays = [d for d in self._profile.displays if d.enabled]
        shelf_displays = self._available_preview_displays()
        self._label_suffixes = disambiguate_labels(enabled_displays + shelf_displays)
        layout = preview_layout(enabled_displays, scale=SCALE)
        self._preview_origin = (layout.origin_x, layout.origin_y)
        enabled_by_object_id = {
            display_object_id(display_state): display_state
            for display_state in enabled_displays
        }
        for rect in layout.rects:
            display_state = enabled_by_object_id.get(rect.object_id) or next(
                (d for d in enabled_displays if d.device_id == rect.device_id),
                None,
            )
            if display_state is None:
                continue
            item = MonitorItem(
                rect.x,
                rect.y,
                rect.width,
                rect.height,
                rect.name + self._label_suffixes.get(stable_display_key(display_state), ""),
                rect.display_number,
                rect.primary,
                display_state,
                self.on_monitor_moved,
                self.on_monitor_released,
                self.on_monitor_selected,
                host._theme.scene,
            )
            host.scene.addItem(item.item)
        host.scene.setSceneRect(host.scene.itemsBoundingRect().adjusted(-80, -80, 80, 80))
        self.refresh_object_list()

    def _available_preview_displays(self) -> list[DisplayState]:
        if self._profile is None:
            return []
        layout = profile_object_layout(
            self._profile.displays,
            available_displays=self._available_displays,
            audio_label=_audio_object_label(self._profile.audio_source),
        )
        by_id = {
            display_object_id(display_state): display_state
            for display_state in self._profile.displays
        }
        available_by_id = {
            display_object_id(display_state): display_state
            for display_state in self._available_displays
        }
        displays: list[DisplayState] = []
        for rect in layout.rects:
            if rect.kind != "display":
                continue
            available_display = available_by_id.get(rect.object_id)
            display_state = available_display or by_id.get(rect.object_id)
            if display_state is None:
                continue
            displays.append(display_state)
        return displays

    def on_available_display_selected(self, display_state: DisplayState) -> None:
        if self._profile is None:
            return
        profile_display = self._ensure_profile_display(display_state)
        profile_display.enabled = False
        profile_display.primary = False
        self._selected_display = _remove_redundant_disabled_profile_displays(
            self._profile.displays,
            selected_display=profile_display,
        )
        profile_display = self._selected_display or profile_display
        self.on_monitor_selected(profile_display)
        self.redraw_scene()

    def _ensure_profile_display(self, display_state: DisplayState) -> DisplayState:
        if self._profile is None:
            return display_state
        profile_display = _find_matching_display(self._profile.displays, display_state)
        if profile_display is None:
            profile_display = DisplayState.from_dict(display_state.to_dict())
            self._profile.displays.append(profile_display)
        elif profile_display is not display_state:
            _copy_display_state(display_state, profile_display)
        return profile_display

    def on_monitor_selected(self, display_state: DisplayState) -> None:
        self._selection_kind = "display"
        self._selected_display = display_state
        self.populate_form()

    def on_audio_selected(self) -> None:
        self._selection_kind = "audio"
        self.populate_form()

    def on_monitor_moved(self, display_state: DisplayState, scene_x: float, scene_y: float) -> None:
        origin_x, origin_y = self._preview_origin
        offset_x, offset_y = self._preview_scene_offset
        display_state.pos_x, display_state.pos_y = scene_to_display_position(
            scene_x - offset_x,
            scene_y - offset_y,
            scale=SCALE,
            origin_x=origin_x,
            origin_y=origin_y,
        )
        self.populate_form()

    def on_monitor_released(
        self, display_state: DisplayState, _scene_x: float, _scene_y: float
    ) -> None:
        self._normalize_profile_geometry()
        self.redraw_scene()
        self.on_monitor_selected(display_state)

    def refresh_object_list(self) -> None:
        from PySide6.QtWidgets import QListWidgetItem  # type: ignore[import-not-found]

        host = self._host
        selected_kind, selected_key = self._object_list_selection_key()
        self._populating_object_list = True
        was_blocked = host.object_list.blockSignals(True)
        try:
            host.object_list.clear()
            audio_item = QListWidgetItem("Audio")
            audio_item.setData(host._qt.ItemDataRole.UserRole, ("audio", ""))
            host.object_list.addItem(audio_item)
            target_row = 0 if selected_kind == "audio" else -1
            row = 1
            enabled: list[DisplayState] = []
            disabled_in_profile: list[DisplayState] = []
            if self._profile is not None:
                for display_state in self._profile.displays:
                    if display_state.enabled:
                        enabled.append(display_state)
                    else:
                        disabled_in_profile.append(display_state)
            profile_keys = {stable_display_key(d) for d in (enabled + disabled_in_profile)}
            extras = [
                d
                for d in self._available_displays
                if stable_display_key(d) not in profile_keys
            ]
            for display_state in enabled:
                key = stable_display_key(display_state)
                title = display_inventory.display_title(display_state)
                item = QListWidgetItem(f"{title}\nenabled")
                item.setData(host._qt.ItemDataRole.UserRole, ("display", key))
                host.object_list.addItem(item)
                if selected_kind == "display" and key == selected_key:
                    target_row = row
                row += 1
            for display_state in disabled_in_profile + extras:
                key = stable_display_key(display_state)
                title = display_inventory.display_title(display_state)
                item = QListWidgetItem(f"{title}\ndisabled")
                font = item.font()
                font.setItalic(True)
                item.setFont(font)
                item.setData(host._qt.ItemDataRole.UserRole, ("available", key))
                host.object_list.addItem(item)
                if selected_kind == "display" and key == selected_key:
                    target_row = row
                row += 1
            if target_row < 0:
                target_row = 0
            host.object_list.setCurrentRow(target_row)
        finally:
            host.object_list.blockSignals(was_blocked)
            self._populating_object_list = False

    def _object_list_selection_key(self) -> tuple[str, str]:
        if self._selection_kind == "audio":
            return ("audio", "")
        if self._selected_display is not None:
            return ("display", stable_display_key(self._selected_display))
        return ("display", "")

    def handle_object_list_changed(self, current: Any, _previous: Any) -> None:
        host = self._host
        if self._populating_object_list or current is None:
            return
        kind, key = current.data(host._qt.ItemDataRole.UserRole)
        if kind == "audio":
            self.on_audio_selected()
            return
        if self._profile is None:
            return
        if kind == "display":
            target = next(
                (
                    d
                    for d in self._profile.displays
                    if d.enabled and stable_display_key(d) == key
                ),
                None,
            )
            if target is not None:
                self.on_monitor_selected(target)
            return
        if kind == "available":
            target = next(
                (
                    d
                    for d in self._profile.displays
                    if not d.enabled and stable_display_key(d) == key
                ),
                None,
            )
            if target is None:
                target = next(
                    (
                        d
                        for d in self._available_displays
                        if stable_display_key(d) == key
                    ),
                    None,
                )
            if target is not None:
                self.on_available_display_selected(target)

    def populate_form(self) -> None:
        host = self._host
        self.populate_profile_fields()
        show_audio = self._selection_kind == "audio"
        host.edit_form.display_props_widget.setVisible(not show_audio)
        host.edit_form.audio_props_widget.setVisible(show_audio)
        if show_audio:
            self.populate_audio_section()
        else:
            self.populate_display_section()

    def populate_display_section(self) -> None:
        host = self._host
        display_state = self._selected_display
        if display_state is None:
            host.display_name.setText("-")
            self._set_blocked_check(host.enabled_checkbox, False)
            self._set_blocked_check(host.primary_checkbox, False)
            host.enabled_checkbox.setEnabled(False)
            host.primary_checkbox.setEnabled(False)
            host.resolution.setEnabled(False)
            host.refresh.setEnabled(False)
            host.orientation.setEnabled(False)
            return
        host.resolution.setEnabled(True)
        host.refresh.setEnabled(True)
        host.orientation.setEnabled(True)
        host._updating_form = True
        try:
            host.display_name.setText(display_state.display_label())
            host.enabled_checkbox.setEnabled(True)
            self._set_blocked_check(host.enabled_checkbox, display_state.enabled)
            host.primary_checkbox.setEnabled(display_state.enabled)
            self._set_blocked_check(host.primary_checkbox, display_state.primary)
            modes = self._modes_for(display_state)
            self._populate_resolution_combo(modes, display_state.width, display_state.height)
            self._populate_refresh_combo(
                modes, display_state.width, display_state.height, display_state.refresh_hz
            )
            _select_combo_data(host.orientation, display_state.orientation)
            _set_blocked_value(host.pos_x, display_state.pos_x)
            _set_blocked_value(host.pos_y, display_state.pos_y)
            _set_blocked_value(
                host.brightness,
                -1 if display_state.brightness is None else display_state.brightness,
            )
            _set_blocked_value(
                host.contrast, -1 if display_state.contrast is None else display_state.contrast
            )
            _set_blocked_value(
                host.input_source,
                -1 if display_state.input_source is None else display_state.input_source,
            )
        finally:
            host._updating_form = False

    def populate_audio_section(self) -> None:
        self.populate_audio_combo()
        self.populate_audio_settings()
        self.populate_audio_status()

    def populate_profile_fields(self) -> None:
        host = self._host
        host.favorite_checkbox.setEnabled(self._profile is not None)
        self._set_blocked_check(
            host.favorite_checkbox,
            self._profile.favorite if self._profile is not None else False,
        )
        host.icon_picker.setEnabled(self._profile is not None)
        host.icon_picker.set_value(self._profile.icon if self._profile is not None else None)

    def on_icon_changed(self, value: str | None) -> None:
        if self._host._updating_form or self._profile is None:
            return
        self._profile.icon = value

    def populate_audio_settings(self) -> None:
        host = self._host
        host._updating_form = True
        try:
            profile = self._profile
            _set_blocked_value(
                host.audio_volume,
                -1 if profile is None or profile.audio_volume_percent is None
                else profile.audio_volume_percent,
            )
            _select_combo_data(
                host.audio_mute,
                None if profile is None else profile.audio_muted,
            )
        finally:
            host._updating_form = False

    def populate_audio_status(self) -> None:
        host = self._host
        current = self._profile.audio_source if self._profile is not None else None
        if current is None:
            host.audio_state.setText("-")
            return
        parts = [current.state or "unknown"]
        if current.role:
            parts.append(current.role)
        host.audio_state.setText(" / ".join(parts))

    @staticmethod
    def _set_blocked_check(widget: Any, value: bool) -> None:
        was_blocked = widget.blockSignals(True)
        try:
            widget.setChecked(bool(value))
        finally:
            widget.blockSignals(was_blocked)

    def on_favorite_toggled(self, checked: bool) -> None:
        if self._host._updating_form or self._profile is None:
            return
        self._profile.favorite = bool(checked)

    def on_enabled_toggled(self, checked: bool) -> None:
        if self._host._updating_form:
            return
        display_state = self._selected_display
        if display_state is None:
            return
        was_enabled = bool(display_state.enabled)
        display_state.enabled = bool(checked)
        if not checked:
            display_state.primary = False
        if checked and not was_enabled:
            display_inventory.apply_display_defaults(display_state)
        if checked and self._profile is not None:
            self._selected_display = _remove_redundant_disabled_profile_displays(
                self._profile.displays,
                selected_display=display_state,
            )
        self._normalize_profile_geometry()
        self.redraw_scene()
        self.populate_form()

    def on_primary_toggled(self, checked: bool) -> None:
        host = self._host
        if host._updating_form:
            return
        display_state = self._selected_display
        if display_state is None or self._profile is None:
            return
        if not checked:
            if display_state.primary:
                self._set_blocked_check(host.primary_checkbox, True)
            return
        display_state.enabled = True
        for candidate in self._profile.displays:
            candidate.primary = candidate is display_state
        self._normalize_profile_geometry()
        self.redraw_scene()
        self.populate_form()

    def on_audio_changed(self) -> None:
        host = self._host
        if host._updating_form or self._profile is None:
            return
        source = host.audio_combo.currentData()
        self._profile.audio_source = source if source is not None else None
        self.populate_audio_status()
        self.redraw_scene()

    def on_audio_volume_changed(self, value: int) -> None:
        if self._host._updating_form or self._profile is None:
            return
        self._profile.audio_volume_percent = value if value >= 0 else None

    def on_audio_mute_changed(self) -> None:
        host = self._host
        if host._updating_form or self._profile is None:
            return
        value = host.audio_mute.currentData()
        self._profile.audio_muted = value if isinstance(value, bool) else None

    def on_resolution_changed(self) -> None:
        host = self._host
        if host._updating_form:
            return
        display_state = self._selected_display
        if display_state is None:
            return
        resolution = host.resolution.currentData()
        width = resolution[0] if resolution else None
        height = resolution[1] if resolution else None
        host._updating_form = True
        try:
            self._populate_refresh_combo(
                self._modes_for(display_state), width, height, display_state.refresh_hz
            )
        finally:
            host._updating_form = False
        self.update_selected_display()

    def update_selected_display(self) -> None:
        host = self._host
        display_state = self._selected_display
        if display_state is None or host._updating_form:
            return
        old_geometry = (
            display_state.width,
            display_state.height,
            display_state.pos_x,
            display_state.pos_y,
            display_state.orientation,
        )
        resolution = host.resolution.currentData()
        if resolution:
            display_state.width, display_state.height = resolution
        else:
            display_state.width = None
            display_state.height = None
        refresh = host.refresh.currentData()
        display_state.refresh_hz = refresh if isinstance(refresh, int) and refresh > 0 else None
        orientation = host.orientation.currentData()
        if isinstance(orientation, int):
            display_state.orientation = orientation
        normalized = self._normalize_profile_geometry()
        new_geometry = (
            display_state.width,
            display_state.height,
            display_state.pos_x,
            display_state.pos_y,
            display_state.orientation,
        )
        if normalized or new_geometry != old_geometry:
            self.redraw_scene()
            self.populate_form()

    def _normalize_profile_geometry(self) -> bool:
        if self._profile is None:
            return False
        primary_changed = ensure_enabled_primary(self._profile.displays)
        return normalize_display_geometry(self._profile.displays) or primary_changed

    def _modes_for(self, display_state: DisplayState) -> list[DisplayMode]:
        adapter = display_state.adapter_name or ""
        if not adapter:
            return []
        if adapter not in self._display_modes_cache:
            try:
                self._display_modes_cache[adapter] = profiles.list_display_modes(adapter)
            except Exception:
                app_logging.get_logger("gui").exception(
                    "failed to enumerate display modes for %s", adapter
                )
                self._display_modes_cache[adapter] = []
        return self._display_modes_cache[adapter]

    def _populate_resolution_combo(
        self, modes: list[DisplayMode], width: int | None, height: int | None
    ) -> None:
        host = self._host
        current = (width, height) if width and height else None
        options = resolution_options(modes, current=current)
        host.resolution.blockSignals(True)
        try:
            host.resolution.clear()
            host.resolution.addItem("-", None)
            for w, h in options:
                host.resolution.addItem(format_resolution(w, h), (w, h))
            if current:
                _select_combo_data(host.resolution, current)
            else:
                host.resolution.setCurrentIndex(0)
        finally:
            host.resolution.blockSignals(False)

    def _populate_refresh_combo(
        self,
        modes: list[DisplayMode],
        width: int | None,
        height: int | None,
        current: int | None,
    ) -> None:
        host = self._host
        rates = refresh_rate_options(modes, width, height, current=current)
        host.refresh.blockSignals(True)
        try:
            host.refresh.clear()
            host.refresh.addItem("-", None)
            for rate in rates:
                host.refresh.addItem(f"{rate} Hz", rate)
            if current and current > 0:
                _select_combo_data(host.refresh, current)
            else:
                host.refresh.setCurrentIndex(0)
        finally:
            host.refresh.blockSignals(False)

    def load_current_preview(self, *, show_errors: bool = True) -> None:
        host = self._host

        def gather() -> PreviewPayload:
            default_audio = audio.get_default_audio_source()
            volume_percent: int | None = None
            muted: bool | None = None
            if default_audio is not None:
                try:
                    volume_percent = audio.get_output_volume_percent(default_audio)
                except Exception:
                    app_logging.get_logger("gui").exception(
                        "failed to read current audio volume"
                    )
                try:
                    muted = audio.get_output_muted(default_audio)
                except Exception:
                    app_logging.get_logger("gui").exception(
                        "failed to read current audio mute state"
                    )
            return PreviewPayload(
                state=profiles.current_state(include_inactive=True),
                default_audio=default_audio,
                audio_sources=audio.list_audio_sources(),
                audio_volume_percent=volume_percent,
                audio_muted=muted,
            )

        def apply_payload(payload: PreviewPayload) -> None:
            self._profile = profiles.Profile(
                name="current",
                displays=payload.state.displays,
                audio_source=payload.default_audio,
                audio_volume_percent=payload.audio_volume_percent,
                audio_muted=payload.audio_muted,
            )
            matched_profile = profiles.find_matching_profile(self._profile)
            if matched_profile is not None:
                self._profile.name = matched_profile.name
                self._profile.favorite = matched_profile.favorite
                self._profile.icon = matched_profile.icon
                self._profile.metadata = dict(matched_profile.metadata)
            self._pristine_profile = copy.deepcopy(self._profile)
            self._selected_display = (
                self._profile.displays[0] if self._profile.displays else None
            )
            self._selection_kind = "display" if self._selected_display is not None else "audio"
            self._available_displays = payload.state.displays
            host.profile_name.setText(self._profile.name)
            host._select_profile_list_item(
                matched_profile.name if matched_profile is not None else None
            )
            self.redraw_scene()
            self.populate_audio_combo(sources=payload.audio_sources)
            self.populate_form()

        def on_failure(message: str) -> None:
            if show_errors:
                host.show_error(message)

        host._run_in_thread(gather, apply_payload, on_failure=on_failure)

    def capture_current(self) -> None:
        host = self._host
        name = host.profile_name.text().strip() or "captured"

        def gather() -> SystemState:
            return profiles.current_state()

        def on_success(state: SystemState) -> None:
            try:
                profiles.save(name, state, overwrite=True)
            except Exception as exc:
                host.show_error(str(exc))
                return
            host.refresh_profiles()
            self.load_profile(name)

        host._run_in_thread(gather, on_success)

    def save_current(self) -> bool:
        host = self._host
        if self._profile is None:
            return False
        self._profile.name = host.profile_name.text().strip() or self._profile.name
        self._profile.favorite = host.favorite_checkbox.isChecked()
        self.refresh_available_displays()
        self._selected_display = _remove_redundant_disabled_profile_displays(
            self._profile.displays,
            selected_display=self._selected_display,
        )
        self._normalize_profile_geometry()
        try:
            profiles.save_profile(self._profile, overwrite=True)
        except Exception as exc:
            host.show_error(str(exc))
            return False
        self._pristine_profile = copy.deepcopy(self._profile)
        host.refresh_profiles()
        return True

    def apply_current(self) -> None:
        host = self._host
        if host._busy_count:
            return
        if self._profile is None:
            return
        if not self.save_current():
            return
        name = self._profile.name

        def run_apply() -> Any:
            return profiles.apply(name)

        def on_success(result: Any) -> None:
            if not result.ok:
                host.show_error(_format_apply_result(result))
                return
            host.show_info(_format_apply_result(result))
            self.load_current_preview(show_errors=False)

        host._run_in_thread(run_apply, on_success)

    def delete_current(self) -> None:
        host = self._host
        if self._profile is None:
            return
        try:
            profiles.delete(self._profile.name)
        except Exception as exc:
            host.show_error(str(exc))
            return
        self._profile = None
        self._pristine_profile = None
        self._selected_display = None
        self._selection_kind = "display"
        host.scene.clear()
        self.populate_audio_combo()
        host.refresh_profiles()

    def populate_audio_combo(
        self, *, sources: list[audio.AudioSource] | None = None
    ) -> None:
        host = self._host
        host._updating_form = True
        try:
            host.audio_combo.clear()
            host.audio_combo.addItem("(none)", None)
            if sources is None:
                try:
                    sources = audio.list_audio_sources()
                except Exception:
                    app_logging.get_logger("gui").exception(
                        "failed to enumerate audio sources"
                    )
                    sources = []
            current = self._profile.audio_source if self._profile is not None else None
            seen_ids: set[str | None] = set()
            for source in sources:
                host.audio_combo.addItem(source.label(), source)
                seen_ids.add(source.endpoint_id)
            if current is not None and current.endpoint_id not in seen_ids:
                host.audio_combo.addItem(current.label(), current)
            target_index = 0
            if current is not None:
                for index in range(host.audio_combo.count()):
                    candidate = host.audio_combo.itemData(index)
                    if candidate is None:
                        continue
                    if (
                        candidate.endpoint_id
                        and candidate.endpoint_id == current.endpoint_id
                    ) or candidate.label() == current.label():
                        target_index = index
                        break
            host.audio_combo.setCurrentIndex(target_index)
        finally:
            host._updating_form = False

    def discard_changes(self) -> None:
        """Drop in-memory edits and restore the last loaded profile snapshot."""
        if self._pristine_profile is None:
            return
        self._profile = copy.deepcopy(self._pristine_profile)
        self._selected_display = self._profile.displays[0] if self._profile.displays else None
        self._selection_kind = "display" if self._selected_display is not None else "audio"
        self.redraw_scene()
        self.populate_audio_combo()
