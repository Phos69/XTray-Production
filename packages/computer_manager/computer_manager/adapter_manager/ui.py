"""UI mixin for the Adapter tab of the Computer Manager window.

This module owns the "Network Adapters" tab grafted into the Computer Manager
main window. Methods stay as instance methods of a mixin so the original
`ComputerManagerExtension` class composes them by inheritance and shares
`self.host`, `self._adapter_service`, etc. without rewiring call sites.
"""
from __future__ import annotations

from typing import Any

from xtray import config
from xtray.core import icons
from xtray.core.computer_models import AdapterIpSettings, NetworkAdapter
from xtray.core.dialogs import AdapterInfoDialog
from xtray.core.icons import IconPickerButton


def _adapter_list_label(adapter: NetworkAdapter) -> str:
    status = adapter.status or "-"
    address = adapter.primary_ipv4 or "-"
    return f"{adapter.name}\n{status} | {address}"


class AdapterTabMixin:  # pragma: no cover - imported only when GUI dependencies exist
    """All methods that own the Network Adapters tab.

    Hosting class must provide instance attributes: `host`, `_adapter_service`,
    `_adapters`, `_selected_adapter`, `_adapters_loaded`, `_adapters_refreshing`,
    `_updating_adapter_detail`.
    """

    def _build_adapters_tab(self) -> None:
        from PySide6.QtWidgets import (
            QCheckBox,
            QFormLayout,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QPushButton,
            QSpinBox,
            QVBoxLayout,
            QWidget,
        )

        tab = QWidget()
        layout = QHBoxLayout(tab)

        lists_area = QWidget()
        lists_layout = QVBoxLayout(lists_area)
        lists_layout.setContentsMargins(0, 0, 0, 0)
        lists_layout.setSpacing(8)
        self.adapter_membership_layout = lists_layout

        visible_group = QGroupBox("Included in tray")
        visible_layout = QVBoxLayout(visible_group)
        self.adapter_visible_list = QListWidget()
        visible_layout.addWidget(self.adapter_visible_list)

        move_box = QWidget()
        move_layout = QHBoxLayout(move_box)
        move_layout.setContentsMargins(0, 0, 0, 0)
        move_layout.addStretch(1)
        self.hide_adapter_button = QPushButton("Exclude from tray")
        self.show_adapter_button = QPushButton("Include in tray")
        move_layout.addWidget(self.hide_adapter_button)
        move_layout.addWidget(self.show_adapter_button)
        move_layout.addStretch(1)

        hidden_group = QGroupBox("Not included in tray")
        hidden_layout = QVBoxLayout(hidden_group)
        self.adapter_hidden_list = QListWidget()
        hidden_layout.addWidget(self.adapter_hidden_list)

        lists_layout.addWidget(visible_group, 1)
        lists_layout.addWidget(move_box)
        lists_layout.addWidget(hidden_group, 1)
        layout.addWidget(lists_area, 2)

        detail_group = QGroupBox("Adapter")
        detail_layout = QVBoxLayout(detail_group)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        detail_layout.addLayout(form)

        self.adapter_name = QLineEdit()
        self.adapter_description = QLineEdit()
        self.adapter_status = QLineEdit()
        self.adapter_mac = QLineEdit()
        self.adapter_speed = QLineEdit()
        self.adapter_ipv4 = QLineEdit()
        self.adapter_icon_picker = IconPickerButton(
            on_change=self._on_adapter_icon_changed
        )
        for widget in (
            self.adapter_name,
            self.adapter_description,
            self.adapter_status,
            self.adapter_mac,
            self.adapter_speed,
            self.adapter_ipv4,
        ):
            widget.setReadOnly(True)
        self.adapter_dhcp = QCheckBox("Use DHCP")
        self.adapter_ip = QLineEdit()
        self.adapter_ip.setPlaceholderText("192.168.1.10")
        self.adapter_prefix = QSpinBox()
        self.adapter_prefix.setRange(1, 32)
        self.adapter_gateway = QLineEdit()
        self.adapter_gateway.setPlaceholderText("192.168.1.1")
        self.adapter_dns = QLineEdit()
        self.adapter_dns.setPlaceholderText("1.1.1.1, 8.8.8.8")

        form.addRow("Name", self.adapter_name)
        form.addRow("Description", self.adapter_description)
        form.addRow("Status", self.adapter_status)
        form.addRow("MAC", self.adapter_mac)
        form.addRow("Speed", self.adapter_speed)
        form.addRow("IPv4", self.adapter_ipv4)
        form.addRow("Icon", self.adapter_icon_picker.widget)
        form.addRow("DHCP", self.adapter_dhcp)
        form.addRow("IP address", self.adapter_ip)
        form.addRow("Prefix length", self.adapter_prefix)
        form.addRow("Gateway", self.adapter_gateway)
        form.addRow("DNS", self.adapter_dns)

        buttons = QHBoxLayout()
        self.refresh_adapters_button = QPushButton("Refresh")
        self.network_connections_button = QPushButton("Network Connections")
        self.adapter_enable_button = QPushButton("Enable")
        self.adapter_apply_button = QPushButton("Apply IP settings")
        self.adapter_info_button = QPushButton("Info dialog")
        buttons.addWidget(self.refresh_adapters_button)
        buttons.addWidget(self.network_connections_button)
        buttons.addWidget(self.adapter_enable_button)
        buttons.addWidget(self.adapter_apply_button)
        buttons.addWidget(self.adapter_info_button)
        detail_layout.addLayout(buttons)
        self.adapter_status_label = QLabel("")
        self.adapter_status_label.setWordWrap(True)
        detail_layout.addWidget(self.adapter_status_label)
        detail_layout.addStretch(1)
        layout.addWidget(detail_group, 2)

        self.adapter_visible_list.currentRowChanged.connect(
            lambda _row: self._select_adapter_from(self.adapter_visible_list)
        )
        self.adapter_hidden_list.currentRowChanged.connect(
            lambda _row: self._select_adapter_from(self.adapter_hidden_list)
        )
        self.hide_adapter_button.clicked.connect(self.hide_selected_adapter)
        self.show_adapter_button.clicked.connect(self.show_selected_adapter)
        self.refresh_adapters_button.clicked.connect(self.refresh_adapters_async)
        self.network_connections_button.clicked.connect(self.open_network_connections)
        self.adapter_enable_button.clicked.connect(self.toggle_selected_adapter)
        self.adapter_apply_button.clicked.connect(self.apply_selected_adapter_ip)
        self.adapter_info_button.clicked.connect(self.open_selected_adapter_info)
        self.adapter_dhcp.toggled.connect(self._sync_adapter_static_fields)

        self.adapters_tab = tab
        self.host.main_tabs.addTab(tab, "Network Adapters")
        self._populate_adapter_detail(None)

    def refresh_adapters_async(self, *, silent: bool = False) -> None:
        if self._adapters_refreshing:
            return
        self._adapters_refreshing = True
        if not silent:
            self.adapter_status_label.setText("Loading network adapters...")

        def gather() -> list[NetworkAdapter]:
            return self._adapter_service.list_adapters()

        def on_success(adapters: list[NetworkAdapter]) -> None:
            self._apply_adapters(adapters)

        def on_failure(message: str) -> None:
            self.adapter_status_label.setText(message)
            self._apply_adapters([])

        def cleanup() -> None:
            self._adapters_refreshing = False

        self.host._run_in_thread(
            gather,
            on_success,
            on_failure=on_failure,
            cleanup=cleanup,
            busy=False,
        )

    def open_network_connections(self) -> None:
        try:
            self._adapter_service.open_network_connections()
        except Exception as exc:
            self.adapter_status_label.setText(str(exc))

    def _apply_adapters(self, adapters: list[NetworkAdapter]) -> None:
        from PySide6.QtWidgets import QListWidgetItem

        current = self._selected_adapter.name if self._selected_adapter else None
        self._adapters = sorted(adapters, key=lambda item: item.name.casefold())
        self._adapters_loaded = True
        visible_names = self._visible_adapter_names()

        self.adapter_visible_list.clear()
        self.adapter_hidden_list.clear()
        for adapter in self._adapters:
            target = (
                self.adapter_visible_list
                if adapter.name in visible_names
                else self.adapter_hidden_list
            )
            item = QListWidgetItem(_adapter_list_label(adapter))
            item.setData(self.host._qt.ItemDataRole.UserRole, adapter.name)
            icon = icons.qicon_for(self._adapter_icon(adapter), size=48)
            if not icon.isNull():
                item.setIcon(icon)
            target.addItem(item)

        self.adapter_status_label.setText("")
        self._select_adapter_by_name(current)
        if self._selected_adapter is None and self._adapters:
            self._select_adapter_by_name(self._adapters[0].name)

    def _visible_adapter_names(self) -> set[str]:
        try:
            options = config.get_tray_options()
        except config.ConfigError:
            options = config.default_tray_options()
        configured = options.get("visible_adapter_ids")
        all_names = {adapter.name for adapter in self._adapters}
        if configured is None:
            return all_names
        return {name for name in configured if name in all_names}

    def _adapter_icons(self) -> dict[str, str]:
        try:
            options = config.get_tray_options()
        except config.ConfigError:
            options = config.default_tray_options()
        raw = options.get("adapter_icons")
        if not isinstance(raw, dict):
            return {}
        return {
            str(name): icon
            for name, value in raw.items()
            if (icon := icons.normalize_icon_name(value))
        }

    def _adapter_icon(self, adapter: NetworkAdapter) -> str | None:
        return self._adapter_icons().get(adapter.name)

    def _on_adapter_icon_changed(self, icon_name: str | None) -> None:
        adapter = self._selected_adapter
        if adapter is None:
            return
        adapter_icons = self._adapter_icons()
        normalized = icons.normalize_icon_name(icon_name)
        if normalized:
            adapter_icons[adapter.name] = normalized
            message = f"{adapter.name}: icon saved."
        else:
            adapter_icons.pop(adapter.name, None)
            message = f"{adapter.name}: icon cleared."
        try:
            config.set_tray_options(adapter_icons=adapter_icons)
        except config.ConfigError as exc:
            self.host.show_error(str(exc))
            self.adapter_icon_picker.set_value(self._adapter_icon(adapter))
            return
        self._apply_adapters(self._adapters)
        self.adapter_status_label.setText(message)

    def _select_adapter_from(self, list_widget: Any) -> None:
        item = list_widget.currentItem()
        if item is None:
            return
        other = (
            self.adapter_hidden_list
            if list_widget is self.adapter_visible_list
            else self.adapter_visible_list
        )
        other.blockSignals(True)
        try:
            other.clearSelection()
            other.setCurrentRow(-1)
        finally:
            other.blockSignals(False)
        self._select_adapter_by_name(str(item.data(self.host._qt.ItemDataRole.UserRole)))

    def _select_adapter_by_name(self, name: str | None) -> None:
        adapter = next((item for item in self._adapters if item.name == name), None)
        self._selected_adapter = adapter
        self._populate_adapter_detail(adapter)
        if adapter is None:
            return
        for list_widget in (self.adapter_visible_list, self.adapter_hidden_list):
            for row in range(list_widget.count()):
                item = list_widget.item(row)
                if item.data(self.host._qt.ItemDataRole.UserRole) == adapter.name:
                    list_widget.setCurrentRow(row)
                    return

    def hide_selected_adapter(self) -> None:
        if self._selected_adapter is None:
            return
        visible = [
            adapter.name
            for adapter in self._adapters
            if adapter.name in self._visible_adapter_names()
            and adapter.name != self._selected_adapter.name
        ]
        self._save_visible_adapter_names(visible)

    def show_selected_adapter(self) -> None:
        if self._selected_adapter is None:
            return
        visible = [
            adapter.name
            for adapter in self._adapters
            if adapter.name in self._visible_adapter_names()
            or adapter.name == self._selected_adapter.name
        ]
        self._save_visible_adapter_names(visible)

    def _save_visible_adapter_names(self, names: list[str]) -> None:
        try:
            config.set_tray_options(visible_adapter_ids=names)
        except config.ConfigError as exc:
            self.host.show_error(str(exc))
            return
        self._apply_adapters(self._adapters)

    def _populate_adapter_detail(self, adapter: NetworkAdapter | None) -> None:
        self._updating_adapter_detail = True
        try:
            enabled = adapter is not None
            for widget in (
                self.adapter_dhcp,
                self.adapter_ip,
                self.adapter_prefix,
                self.adapter_gateway,
                self.adapter_dns,
                self.adapter_enable_button,
                self.adapter_apply_button,
                self.adapter_info_button,
                self.adapter_icon_picker.widget,
            ):
                widget.setEnabled(enabled)
            if adapter is None:
                self.adapter_name.setText("")
                self.adapter_description.setText("")
                self.adapter_status.setText("")
                self.adapter_mac.setText("")
                self.adapter_speed.setText("")
                self.adapter_ipv4.setText("")
                self.adapter_dhcp.setChecked(True)
                self.adapter_ip.setText("")
                self.adapter_prefix.setValue(24)
                self.adapter_gateway.setText("")
                self.adapter_dns.setText("")
                self.adapter_icon_picker.set_value(None)
                self.adapter_enable_button.setText("Enable")
                return
            self.adapter_name.setText(adapter.name)
            self.adapter_description.setText(adapter.description)
            self.adapter_status.setText(adapter.status)
            self.adapter_mac.setText(adapter.mac_address or "")
            self.adapter_speed.setText(adapter.link_speed or "")
            self.adapter_ipv4.setText(", ".join(adapter.ipv4_addresses))
            self.adapter_dhcp.setChecked(adapter.dhcp_enabled)
            self.adapter_ip.setText(adapter.primary_ipv4 or "")
            self.adapter_prefix.setValue(int(adapter.primary_prefix_length or 24))
            self.adapter_gateway.setText(adapter.gateway or "")
            self.adapter_dns.setText(", ".join(adapter.dns_servers))
            self.adapter_icon_picker.set_value(self._adapter_icon(adapter))
            self.adapter_enable_button.setText(
                "Disable" if adapter.enabled else "Enable"
            )
            self._sync_adapter_static_fields(adapter.dhcp_enabled)
        finally:
            self._updating_adapter_detail = False

    def _sync_adapter_static_fields(self, dhcp_enabled: bool) -> None:
        enabled = not dhcp_enabled and self._selected_adapter is not None
        for widget in (
            self.adapter_ip,
            self.adapter_prefix,
            self.adapter_gateway,
            self.adapter_dns,
        ):
            widget.setEnabled(enabled)

    def toggle_selected_adapter(self) -> None:
        adapter = self._selected_adapter
        if adapter is None:
            return
        target_enabled = not adapter.enabled
        action = "Enabling" if target_enabled else "Disabling"
        self.adapter_status_label.setText(f"{action} {adapter.name}...")

        def run() -> None:
            self._adapter_service.set_adapter_enabled(adapter, target_enabled)

        self._run_adapter_mutation(run, f"{adapter.name}: change applied.")

    def apply_selected_adapter_ip(self) -> None:
        adapter = self._selected_adapter
        if adapter is None:
            return
        settings = AdapterIpSettings(
            dhcp_enabled=self.adapter_dhcp.isChecked(),
            ip_address=self.adapter_ip.text().strip() or None,
            prefix_length=self.adapter_prefix.value(),
            gateway=self.adapter_gateway.text().strip() or None,
            dns_servers=tuple(
                part.strip()
                for part in self.adapter_dns.text().replace(";", ",").split(",")
                if part.strip()
            ),
        )
        mode = "DHCP" if settings.dhcp_enabled else "static IP"
        self.adapter_status_label.setText(f"Applying {mode} settings to {adapter.name}...")

        def run() -> None:
            self._adapter_service.set_ip_settings(adapter, settings)

        self._run_adapter_mutation(run, f"{adapter.name}: {mode} settings applied.")

    def open_selected_adapter_info(self) -> None:
        adapter = self._selected_adapter
        if adapter is None:
            return
        dialog = AdapterInfoDialog(adapter, self.host.window)
        if not dialog.exec():
            return
        settings = dialog.ip_settings()

        def run() -> None:
            self._adapter_service.set_ip_settings(adapter, settings)

        self._run_adapter_mutation(run, f"{adapter.name}: network settings applied.")

    def _run_adapter_mutation(self, target: Any, success_message: str) -> None:
        def on_success(_result: None) -> None:
            self.adapter_status_label.setText(success_message)
            self.refresh_adapters_async()

        def on_failure(message: str) -> None:
            self.adapter_status_label.setText(message)
            self.refresh_adapters_async()

        self.host._run_in_thread(target, on_success, on_failure=on_failure)
