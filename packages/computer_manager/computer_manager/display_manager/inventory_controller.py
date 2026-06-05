"""Controller for the "Displays" inventory tab in Computer Manager.

Owns the inventory list, the per-display detail form (friendly name, volume
control mode, Home Assistant power services, default resolution/refresh/
orientation), and the sync/async refresh flow. Lifted out of
``computer_manager.app`` so MainWindow stays focused on orchestration.

The controller keeps a back-reference to the host MainWindow so it can
read the inventory widgets created by ``_layout_builder`` and call the
shared helpers (``_modes_for`` on the profile editor side, ``show_error``,
``_run_in_thread``). The ``_updating_form`` flag stays on the host because
the profile editor needs it too.
"""
from __future__ import annotations

from typing import Any

from xtray import config
from xtray.core import app_logging

from .._helpers import _ha_service_data_text, _select_combo_data
from . import inventory as display_inventory
from .backend import DisplayMode
from .ui_model import (
    format_resolution,
    refresh_rate_options,
    resolution_options,
)


class InventoryController:  # pragma: no cover - imported only when GUI dependencies exist
    def __init__(self, host: Any) -> None:
        self._host = host
        self._display_inventory_items: list[display_inventory.DisplayInventoryItem] = []
        self._selected_inventory_item: display_inventory.DisplayInventoryItem | None = None
        self._display_inventory_refreshing = False
        self._display_inventory_loaded = False
        self._populating_display_inventory = False

    @property
    def selected_item(self) -> display_inventory.DisplayInventoryItem | None:
        return self._selected_inventory_item

    @property
    def items(self) -> list[display_inventory.DisplayInventoryItem]:
        return self._display_inventory_items

    @property
    def loaded(self) -> bool:
        return self._display_inventory_loaded

    def refresh_display_inventory(self) -> None:
        current_key = (
            self._selected_inventory_item.key if self._selected_inventory_item is not None else None
        )
        try:
            items = display_inventory.collect_display_inventory()
        except Exception as exc:
            app_logging.get_logger("gui").exception("failed to refresh display inventory")
            self._host.show_error(str(exc))
            items = []
        self._apply_display_inventory_items(items, current_key=current_key)

    def refresh_display_inventory_async(self) -> None:
        if self._display_inventory_refreshing:
            return
        self._display_inventory_refreshing = True
        current_key = (
            self._selected_inventory_item.key if self._selected_inventory_item is not None else None
        )
        self.show_display_inventory_loading()

        def gather() -> list[display_inventory.DisplayInventoryItem]:
            return display_inventory.collect_display_inventory()

        def on_success(items: list[display_inventory.DisplayInventoryItem]) -> None:
            self._apply_display_inventory_items(items, current_key=current_key)

        def on_failure(message: str) -> None:
            self._host.show_error(message)
            self._apply_display_inventory_items([], current_key=current_key)

        def clear_refreshing() -> None:
            self._display_inventory_refreshing = False

        self._host._run_in_thread(
            gather,
            on_success,
            on_failure=on_failure,
            cleanup=clear_refreshing,
            busy=False,
        )

    def show_display_inventory_loading(self) -> None:
        host = self._host
        was_blocked = host.display_inventory_list.blockSignals(True)
        self._populating_display_inventory = True
        try:
            host.display_inventory_list.clear()
            host.display_inventory_list.addItem("Loading displays...")
            self._selected_inventory_item = None
        finally:
            self._populating_display_inventory = False
            host.display_inventory_list.blockSignals(was_blocked)
        self.populate_display_inventory_detail(None)

    def _apply_display_inventory_items(
        self,
        items: list[display_inventory.DisplayInventoryItem],
        *,
        current_key: str | None,
    ) -> None:
        from PySide6.QtWidgets import QListWidgetItem  # type: ignore[import-not-found]

        host = self._host
        self._display_inventory_items = items
        self._display_inventory_loaded = True
        was_blocked = host.display_inventory_list.blockSignals(True)
        self._populating_display_inventory = True
        try:
            host.display_inventory_list.clear()
            target_row = -1
            for row, item in enumerate(items):
                suffix = "active" if item.enabled else "available" if item.available else "saved"
                label = f"{display_inventory.display_title(item.display)} ({suffix})"
                if item.volume_control == config.VOLUME_CONTROL_HDMI:
                    label = f"{label} - HDMI volume"
                elif item.volume_control == config.VOLUME_CONTROL_HA_ENTITY:
                    entity = item.volume_ha_entity or "?"
                    label = f"{label} - HA {entity}"
                list_item = QListWidgetItem(label)
                list_item.setData(host._qt.ItemDataRole.UserRole, item.key)
                host.display_inventory_list.addItem(list_item)
                if item.key == current_key:
                    target_row = row
            if items:
                host.display_inventory_list.setCurrentRow(target_row if target_row >= 0 else 0)
            else:
                self._selected_inventory_item = None
        finally:
            self._populating_display_inventory = False
            host.display_inventory_list.blockSignals(was_blocked)
        if items:
            row = host.display_inventory_list.currentRow()
            self.on_display_inventory_selected(row if row >= 0 else 0)
        else:
            self.populate_display_inventory_detail(None)

    def persist_display_inventory_order(self, *_args: Any) -> None:
        """Save the drag-and-drop order so the tray mirrors it."""
        if self._populating_display_inventory:
            return
        host = self._host
        keys: list[str] = []
        for row in range(host.display_inventory_list.count()):
            list_item = host.display_inventory_list.item(row)
            if list_item is None:
                continue
            key = list_item.data(host._qt.ItemDataRole.UserRole)
            if key:
                keys.append(str(key))
        current_key = (
            self._selected_inventory_item.key
            if self._selected_inventory_item is not None
            else None
        )
        try:
            items = display_inventory.reorder_display_inventory(keys)
        except Exception:
            app_logging.get_logger("gui").exception("failed to persist display order")
            self.refresh_display_inventory_async()
            return
        self._apply_display_inventory_items(items, current_key=current_key)

    def on_display_inventory_selected(self, row: int) -> None:
        if 0 <= row < len(self._display_inventory_items):
            self._selected_inventory_item = self._display_inventory_items[row]
        else:
            self._selected_inventory_item = None
        self.populate_display_inventory_detail(self._selected_inventory_item)

    def populate_display_inventory_detail(
        self,
        item: display_inventory.DisplayInventoryItem | None,
    ) -> None:
        host = self._host
        host._updating_form = True
        try:
            if item is None:
                host.inventory_name.setText("-")
                host.inventory_friendly_name.setEnabled(False)
                host.inventory_friendly_name.setText("")
                host.inventory_status.setText("-")
                host.inventory_identity.setText("-")
                host.inventory_profiles.setText("-")
                self._set_volume_control_value(config.VOLUME_CONTROL_NONE)
                host.inventory_volume_control.setEnabled(False)
                host.inventory_volume_ha_entity.setEnabled(False)
                host.inventory_volume_ha_entity.setText("")
                host.inventory_volume_ha_entity.setVisible(False)
                host.inventory_power_on_ha_service.setEnabled(False)
                host.inventory_power_on_ha_service.setText("")
                host.inventory_power_on_ha_service_data.setEnabled(False)
                host.inventory_power_on_ha_service_data.setText("")
                host.inventory_power_off_ha_service.setEnabled(False)
                host.inventory_power_off_ha_service.setText("")
                host.inventory_power_off_ha_service_data.setEnabled(False)
                host.inventory_power_off_ha_service_data.setText("")
                self._populate_inventory_default_combos([], None, None, None, None)
                host.inventory_default_resolution.setEnabled(False)
                host.inventory_default_refresh.setEnabled(False)
                host.inventory_default_orientation.setEnabled(False)
                return
            display_state = item.display
            host.inventory_name.setText(display_state.display_label())
            host.inventory_friendly_name.setEnabled(True)
            host.inventory_friendly_name.setText(item.friendly_name or "")
            status = []
            status.append("available" if item.available else "from saved profiles")
            status.append("enabled" if item.enabled else "disabled")
            host.inventory_status.setText(" / ".join(status))
            identity_parts = [
                f"key: {item.key}",
                f"device: {display_state.device_id or '-'}",
                f"adapter: {display_state.adapter_name or '-'}",
            ]
            if display_state.container_id:
                identity_parts.append(f"container: {display_state.container_id}")
            if display_state.edid_hash:
                identity_parts.append(f"edid: {display_state.edid_hash}")
            host.inventory_identity.setText("\n".join(identity_parts))
            host.inventory_profiles.setText(
                "\n".join(item.assigned_profiles) if item.assigned_profiles else "-"
            )
            host.inventory_volume_control.setEnabled(True)
            self._set_volume_control_value(item.volume_control)
            host.inventory_volume_ha_entity.setText(item.volume_ha_entity or "")
            is_ha = item.volume_control == config.VOLUME_CONTROL_HA_ENTITY
            host.inventory_volume_ha_entity.setEnabled(is_ha)
            host.inventory_volume_ha_entity.setVisible(is_ha)
            host.inventory_power_on_ha_service.setText(item.power_on_ha_service or "")
            host.inventory_power_on_ha_service.setEnabled(True)
            host.inventory_power_on_ha_service_data.setText(
                _ha_service_data_text(item.power_on_ha_service_data)
            )
            host.inventory_power_on_ha_service_data.setEnabled(True)
            host.inventory_power_off_ha_service.setText(item.power_off_ha_service or "")
            host.inventory_power_off_ha_service.setEnabled(True)
            host.inventory_power_off_ha_service_data.setText(
                _ha_service_data_text(item.power_off_ha_service_data)
            )
            host.inventory_power_off_ha_service_data.setEnabled(True)
            modes = host._modes_for(display_state)
            self._populate_inventory_default_combos(
                modes,
                item.default_width,
                item.default_height,
                item.default_refresh_hz,
                item.default_orientation,
            )
            host.inventory_default_resolution.setEnabled(True)
            host.inventory_default_refresh.setEnabled(True)
            host.inventory_default_orientation.setEnabled(True)
        finally:
            host._updating_form = False

    def _set_volume_control_value(self, mode: str) -> None:
        combo = self._host.inventory_volume_control
        index = combo.findData(mode)
        if index < 0:
            index = combo.findData(config.VOLUME_CONTROL_NONE)
        combo.setCurrentIndex(max(index, 0))

    def _current_volume_control(self) -> str:
        data = self._host.inventory_volume_control.currentData()
        return str(data) if data else config.VOLUME_CONTROL_NONE

    def on_inventory_friendly_name_changed(self) -> None:
        host = self._host
        if host._updating_form or self._selected_inventory_item is None:
            return
        friendly_name = host.inventory_friendly_name.text().strip() or None
        try:
            display_inventory.set_friendly_name(
                self._selected_inventory_item.display,
                friendly_name,
            )
        except config.ConfigError as exc:
            host.show_error(str(exc))
            self.populate_display_inventory_detail(self._selected_inventory_item)
            return
        self.refresh_display_inventory()

    def on_inventory_volume_control_changed(self, _index: int) -> None:
        host = self._host
        if host._updating_form or self._selected_inventory_item is None:
            return
        mode = self._current_volume_control()
        is_ha = mode == config.VOLUME_CONTROL_HA_ENTITY
        host.inventory_volume_ha_entity.setEnabled(is_ha)
        host.inventory_volume_ha_entity.setVisible(is_ha)
        if not is_ha:
            host.inventory_volume_ha_entity.setText("")
        entity = host.inventory_volume_ha_entity.text().strip() or None
        try:
            display_inventory.set_volume_control(
                self._selected_inventory_item.display,
                mode,
                ha_entity=entity if is_ha else None,
            )
        except config.ConfigError as exc:
            host.show_error(str(exc))
            self.populate_display_inventory_detail(self._selected_inventory_item)
            return
        self.refresh_display_inventory()

    def on_inventory_volume_ha_entity_changed(self) -> None:
        host = self._host
        if host._updating_form or self._selected_inventory_item is None:
            return
        if self._current_volume_control() != config.VOLUME_CONTROL_HA_ENTITY:
            return
        entity = host.inventory_volume_ha_entity.text().strip() or None
        try:
            display_inventory.set_volume_control(
                self._selected_inventory_item.display,
                config.VOLUME_CONTROL_HA_ENTITY,
                ha_entity=entity,
            )
        except config.ConfigError as exc:
            host.show_error(str(exc))
            self.populate_display_inventory_detail(self._selected_inventory_item)
            return
        self.refresh_display_inventory()

    def on_inventory_power_on_ha_service_changed(self) -> None:
        self._save_inventory_ha_power_services(power_on_changed=True)

    def on_inventory_power_on_ha_service_data_changed(self) -> None:
        self._save_inventory_ha_power_services(power_on_data_changed=True)

    def on_inventory_power_off_ha_service_changed(self) -> None:
        self._save_inventory_ha_power_services(power_off_changed=True)

    def on_inventory_power_off_ha_service_data_changed(self) -> None:
        self._save_inventory_ha_power_services(power_off_data_changed=True)

    def _save_inventory_ha_power_services(
        self,
        *,
        power_on_changed: bool = False,
        power_on_data_changed: bool = False,
        power_off_changed: bool = False,
        power_off_data_changed: bool = False,
    ) -> None:
        host = self._host
        if host._updating_form or self._selected_inventory_item is None:
            return
        kwargs: dict[str, object] = {}
        if power_on_changed:
            kwargs["power_on_service"] = (
                host.inventory_power_on_ha_service.text().strip() or None
            )
        if power_on_data_changed:
            kwargs["power_on_data"] = (
                host.inventory_power_on_ha_service_data.text().strip() or None
            )
        if power_off_changed:
            kwargs["power_off_service"] = (
                host.inventory_power_off_ha_service.text().strip() or None
            )
        if power_off_data_changed:
            kwargs["power_off_data"] = (
                host.inventory_power_off_ha_service_data.text().strip() or None
            )
        if not kwargs:
            return
        try:
            display_inventory.set_home_assistant_power_services(
                self._selected_inventory_item.display,
                **kwargs,
            )
        except config.ConfigError as exc:
            host.show_error(str(exc))
            self.populate_display_inventory_detail(self._selected_inventory_item)
            return
        self.refresh_display_inventory()

    def _populate_inventory_default_combos(
        self,
        modes: list[DisplayMode],
        width: int | None,
        height: int | None,
        refresh_hz: int | None,
        orientation: int | None,
    ) -> None:
        host = self._host
        current_resolution = (width, height) if width and height else None
        resolution_choices = resolution_options(modes, current=current_resolution)
        was_blocked = host.inventory_default_resolution.blockSignals(True)
        try:
            host.inventory_default_resolution.clear()
            host.inventory_default_resolution.addItem("Use display value", None)
            for w, h in resolution_choices:
                host.inventory_default_resolution.addItem(format_resolution(w, h), (w, h))
            if current_resolution is not None:
                _select_combo_data(host.inventory_default_resolution, current_resolution)
            else:
                host.inventory_default_resolution.setCurrentIndex(0)
        finally:
            host.inventory_default_resolution.blockSignals(was_blocked)

        refresh_choices = refresh_rate_options(modes, width, height, current=refresh_hz)
        was_blocked = host.inventory_default_refresh.blockSignals(True)
        try:
            host.inventory_default_refresh.clear()
            host.inventory_default_refresh.addItem("Use display value", None)
            for rate in refresh_choices:
                host.inventory_default_refresh.addItem(f"{rate} Hz", rate)
            if refresh_hz and refresh_hz > 0:
                _select_combo_data(host.inventory_default_refresh, refresh_hz)
            else:
                host.inventory_default_refresh.setCurrentIndex(0)
        finally:
            host.inventory_default_refresh.blockSignals(was_blocked)

        was_blocked = host.inventory_default_orientation.blockSignals(True)
        try:
            if orientation in (None, 0, 90, 180, 270):
                _select_combo_data(host.inventory_default_orientation, orientation)
            else:
                host.inventory_default_orientation.setCurrentIndex(0)
        finally:
            host.inventory_default_orientation.blockSignals(was_blocked)

    def on_inventory_default_resolution_changed(self, _index: int) -> None:
        host = self._host
        if host._updating_form or self._selected_inventory_item is None:
            return
        data = host.inventory_default_resolution.currentData()
        if data is None:
            width: int | None = None
            height: int | None = None
        else:
            width, height = int(data[0]), int(data[1])
        try:
            display_inventory.set_display_defaults(
                self._selected_inventory_item.display,
                width=width,
                height=height,
            )
        except config.ConfigError as exc:
            host.show_error(str(exc))
            self.populate_display_inventory_detail(self._selected_inventory_item)
            return
        self.refresh_display_inventory()

    def on_inventory_default_refresh_changed(self, _index: int) -> None:
        host = self._host
        if host._updating_form or self._selected_inventory_item is None:
            return
        data = host.inventory_default_refresh.currentData()
        refresh_hz = int(data) if data is not None else None
        try:
            display_inventory.set_display_defaults(
                self._selected_inventory_item.display,
                refresh_hz=refresh_hz,
            )
        except config.ConfigError as exc:
            host.show_error(str(exc))
            self.populate_display_inventory_detail(self._selected_inventory_item)
            return
        self.refresh_display_inventory()

    def on_inventory_default_orientation_changed(self, _index: int) -> None:
        host = self._host
        if host._updating_form or self._selected_inventory_item is None:
            return
        data = host.inventory_default_orientation.currentData()
        orientation = int(data) if data is not None else None
        try:
            display_inventory.set_display_defaults(
                self._selected_inventory_item.display,
                orientation=orientation,
            )
        except config.ConfigError as exc:
            host.show_error(str(exc))
            self.populate_display_inventory_detail(self._selected_inventory_item)
            return
        self.refresh_display_inventory()
