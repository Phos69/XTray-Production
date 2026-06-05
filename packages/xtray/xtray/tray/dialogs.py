"""Modal dialogs for the tray app."""
from __future__ import annotations

from typing import Any

from xtray.core.theme import build_app_stylesheet, theme_by_name, theme_label, theme_names

from .. import config, ha_mqtt
from ..core import app_logging, qt_assets
from ..services.display import display_inventory, profiles
from .chrome import _current_theme


class TrayOptionsDialog:  # pragma: no cover - imported only when GUI dependencies exist
    def __init__(
        self,
        parent: Any = None,
        *,
        dark_theme_enabled: bool,
        theme_name: str | None = None,
        start_with_windows_enabled: bool,
        start_with_windows_available: bool,
        tray_options: dict[str, Any] | None = None,
        hotkey_settings: dict[str, Any] | None = None,
        mqtt_settings: dict[str, Any] | None = None,
        experimental_features: dict[str, Any] | None = None,
        experimental_features_available: bool = False,
        sync_settings: dict[str, Any] | None = None,
        sync_password_configured: bool = False,
        initial_section: str = "general",
    ) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QAbstractItemView,
            QCheckBox,
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QListWidgetItem,
            QPushButton,
            QScrollArea,
            QSpinBox,
            QStackedWidget,
            QTabWidget,
            QVBoxLayout,
            QWidget,
        )

        self._section_ids: list[str] = []
        self.tray_option_checks: dict[str, Any] = {}
        self.dialog = QDialog(parent)
        self.dialog.setWindowTitle("Options")
        qt_assets.set_window_icon(self.dialog)
        self.dialog.setMinimumWidth(620)
        self.dialog.setStyleSheet(build_app_stylesheet(_current_theme()))

        current_tray_options = config.normalize_tray_options(
            tray_options or config.default_tray_options()
        )
        self._current_tray_options = dict(current_tray_options)
        current_hotkeys = hotkey_settings or config.default_hotkey_settings()
        current_mqtt = mqtt_settings or config.default_mqtt_settings()
        current_experimental = config.normalize_experimental_features(
            experimental_features or config.default_experimental_features()
        )
        current_sync = dict(sync_settings or {})
        self._sync_password_configured = bool(sync_password_configured)
        self._current_experimental_features = dict(current_experimental)
        self.network_manager_full_check = None
        current_theme_name = theme_by_name(
            theme_name or ("dark" if dark_theme_enabled else None)
        ).name

        layout = QVBoxLayout(self.dialog)
        body = QHBoxLayout()
        body.setSpacing(12)
        layout.addLayout(body, 1)

        self.section_list = QListWidget()
        self.section_list.setObjectName("trayOptionsSectionList")
        self.section_list.setFixedWidth(150)
        body.addWidget(self.section_list)

        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)

        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        general_form = QFormLayout()
        general_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        general_layout.addLayout(general_form)

        self.start_check = QCheckBox("Start with Windows")
        self.start_check.setChecked(start_with_windows_enabled)
        self.start_check.setEnabled(start_with_windows_available)
        general_form.addRow("Startup", self.start_check)

        self.hotkey_enabled_check = QCheckBox("Enable global toggle hotkey")
        self.hotkey_enabled_check.setChecked(bool(current_hotkeys.get("toggle_panel_enabled")))
        general_form.addRow("Hotkey", self.hotkey_enabled_check)

        self.hotkey_edit = QLineEdit()
        self.hotkey_edit.setPlaceholderText("Ctrl+Alt+X")
        self.hotkey_edit.setText(str(current_hotkeys.get("toggle_panel") or "Ctrl+Alt+X"))
        general_form.addRow("Toggle XTray", self.hotkey_edit)

        hotkey_note = QLabel(
            "Assign the same shortcut to an MX Master custom button in Logi Options+."
        )
        hotkey_note.setWordWrap(True)
        hotkey_note.setObjectName("trayPanelStatus")
        general_layout.addWidget(hotkey_note)
        general_layout.addStretch(1)
        self._add_section("general", "General", general_tab)

        sync_tab = QWidget()
        sync_layout = QVBoxLayout(sync_tab)
        sync_form = QFormLayout()
        sync_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        sync_layout.addLayout(sync_form)
        self.sync_enabled_check = QCheckBox("Enable LAN sync")
        self.sync_enabled_check.setChecked(bool(current_sync.get("enabled", False)))
        sync_form.addRow("LAN sync", self.sync_enabled_check)
        self.sync_peer_name = QLineEdit()
        self.sync_peer_name.setText(str(current_sync.get("peer_name") or ""))
        sync_form.addRow("Peer name", self.sync_peer_name)
        self.sync_port = QSpinBox()
        self.sync_port.setRange(1, 65535)
        self.sync_port.setValue(int(current_sync.get("port") or 37665))
        sync_form.addRow("Port", self.sync_port)
        self.sync_password = QLineEdit()
        self.sync_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.sync_password.setPlaceholderText(
            "Configured" if self._sync_password_configured else "Required"
        )
        sync_form.addRow("Password", self.sync_password)
        self.sync_enabled_check.toggled.connect(self._sync_lan_sync_fields)
        self._sync_lan_sync_fields()
        sync_layout.addStretch(1)
        self._add_section("lan_sync", "LAN Sync", sync_tab)

        appearance_tab = QWidget()
        appearance_layout = QVBoxLayout(appearance_tab)
        appearance_form = QFormLayout()
        appearance_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        appearance_layout.addLayout(appearance_form)
        self.theme_combo = QComboBox()
        for name in theme_names():
            self.theme_combo.addItem(theme_label(name), name)
        index = self.theme_combo.findData(current_theme_name)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
        appearance_form.addRow("Theme", self.theme_combo)
        appearance_layout.addStretch(1)
        self._add_section("appearance", "Appearance", appearance_tab)

        tray_tabs = QTabWidget()
        tray_tabs.setObjectName("trayOptionsTabs")
        self.tray_options_tabs = tray_tabs

        top_bar_layout, self.tray_top_bar_scroll = self._add_tray_options_tab(
            tray_tabs,
            "Top bar",
        )
        top_bar_section = self._add_tray_section(top_bar_layout, "Popup launchers")
        self._add_tray_checks(
            top_bar_section,
            (
                ("show_displays_popup", "Displays popup button"),
                ("show_adapters_popup", "Network adapters popup button"),
                ("show_drives_tab", "Drives tab and popup button"),
            ),
            current_tray_options,
        )
        top_bar_layout.addStretch(1)

        bottom_bar_layout, self.tray_bottom_bar_scroll = self._add_tray_options_tab(
            tray_tabs,
            "Bottom bar",
        )
        bottom_status_section = self._add_tray_section(
            bottom_bar_layout,
            "Status indicators",
        )
        self._add_tray_checks(
            bottom_status_section,
            (
                ("show_mqtt_indicator", "MQTT indicator"),
                ("show_home_assistant_indicator", "Home Assistant indicator"),
            ),
            current_tray_options,
        )
        bottom_actions_section = self._add_tray_section(
            bottom_bar_layout,
            "Launch buttons",
        )
        self._add_tray_checks(
            bottom_actions_section,
            (
                ("show_options_button", "Options button"),
                ("show_network_manager_button", "Network Manager button"),
                ("show_computer_manager_button", "Computer Manager button"),
            ),
            current_tray_options,
        )
        bottom_bar_layout.addStretch(1)

        media_tab_layout, self.tray_media_scroll = self._add_tray_options_tab(
            tray_tabs,
            "Media tab",
        )
        media_visibility_section = self._add_tray_section(
            media_tab_layout,
            "Tab visibility",
        )
        self._add_tray_checks(
            media_visibility_section,
            (("show_media_tab", "Enable Media tab"),),
            current_tray_options,
        )
        media_content_section = self._add_tray_section(
            media_tab_layout,
            "Media controls",
        )
        self._add_tray_checks(
            media_content_section,
            (
                ("show_display_profiles", "Display profiles"),
                ("show_audio_output", "Audio section"),
                ("show_pc_volume", "PC volume slider"),
                ("show_display_volume", "Display volume controls"),
            ),
            current_tray_options,
        )
        media_layout_section = self._add_tray_section(media_tab_layout, "Layout")
        self.media_profile_columns_spin = QSpinBox()
        self.media_profile_columns_spin.setRange(2, 8)
        self.media_profile_columns_spin.setValue(
            int(
                current_tray_options.get(
                    "media_profile_columns",
                    config.DEFAULT_MEDIA_PROFILE_COLUMNS,
                )
            )
        )
        self._add_tray_form_row(
            media_layout_section,
            "Profile buttons per row",
            self.media_profile_columns_spin,
        )

        self.media_order_list = QListWidget()
        self.media_order_list.setObjectName("trayMediaOrderList")
        self.media_order_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.media_order_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.media_order_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.media_order_list.setMinimumHeight(104)
        media_order_labels = {
            "media_displays": "Displays",
            "audio_output": "Audio",
        }
        order_ids = [
            str(row_id)
            for row_id in current_tray_options.get("media_row_order", [])
            if str(row_id) in media_order_labels
        ]
        for row_id in config.MEDIA_ROW_ORDER:
            if row_id not in order_ids:
                order_ids.append(row_id)
        for row_id in order_ids:
            item = QListWidgetItem(media_order_labels.get(str(row_id), str(row_id)))
            item.setData(256, str(row_id))
            self.media_order_list.addItem(item)
        if self.media_order_list.count():
            self.media_order_list.setCurrentRow(0)
        order_buttons = QWidget()
        order_buttons_layout = QHBoxLayout(order_buttons)
        order_buttons_layout.setContentsMargins(0, 0, 0, 0)
        order_buttons_layout.setSpacing(8)
        self.media_order_up_button = QPushButton("Move up")
        self.media_order_down_button = QPushButton("Move down")
        self.media_order_up_button.clicked.connect(
            lambda _checked=False: self._move_media_order(-1)
        )
        self.media_order_down_button.clicked.connect(
            lambda _checked=False: self._move_media_order(1)
        )
        order_buttons_layout.addWidget(self.media_order_up_button)
        order_buttons_layout.addWidget(self.media_order_down_button)
        order_buttons_layout.addStretch(1)
        media_order_box = QWidget()
        media_order_layout = QVBoxLayout(media_order_box)
        media_order_layout.setContentsMargins(0, 0, 0, 0)
        media_order_layout.setSpacing(6)
        media_order_layout.addWidget(self.media_order_list)
        media_order_layout.addWidget(order_buttons)
        self._add_tray_form_row(media_layout_section, "Media order", media_order_box)
        media_tab_layout.addStretch(1)

        network_tab_layout, self.tray_network_scroll = self._add_tray_options_tab(
            tray_tabs,
            "Network tab",
        )
        network_section = self._add_tray_section(network_tab_layout, "Tab visibility")
        self._add_tray_checks(
            network_section,
            (("show_network_tab", "Enable Network tab"),),
            current_tray_options,
        )
        network_tab_layout.addStretch(1)

        adapters_tab_layout, self.tray_adapters_scroll = self._add_tray_options_tab(
            tray_tabs,
            "Adapters tab",
        )
        adapters_section = self._add_tray_section(
            adapters_tab_layout,
            "Tab visibility",
        )
        self._add_tray_checks(
            adapters_section,
            (("show_adapters_tab", "Enable Network adapters tab"),),
            current_tray_options,
        )
        adapters_tab_layout.addStretch(1)

        device_tab_layout, self.tray_device_scroll = self._add_tray_options_tab(
            tray_tabs,
            "Device tab",
        )
        device_faceplate_section = self._add_tray_section(
            device_tab_layout,
            "Device faceplates",
        )
        self._add_tray_checks(
            device_faceplate_section,
            (
                ("show_media_displays", "Display faceplates in Media tab"),
                ("show_media_drives", "Drive faceplates in Drives tab"),
            ),
            current_tray_options,
        )
        display_popup_section = self._add_tray_section(
            device_tab_layout,
            "Displays popup",
        )
        self.display_grid_columns_spin = QSpinBox()
        self.display_grid_columns_spin.setRange(1, 8)
        self.display_grid_columns_spin.setValue(
            int(current_tray_options.get("display_grid_columns", 2))
        )
        self._add_tray_form_row(
            display_popup_section,
            "Display cards per row",
            self.display_grid_columns_spin,
        )
        device_tab_layout.addStretch(1)

        self._media_dependent_controls = [
            self.tray_option_checks["show_display_profiles"],
            self.tray_option_checks["show_audio_output"],
            self.tray_option_checks["show_media_displays"],
            self.media_profile_columns_spin,
            self.media_order_list,
            self.media_order_up_button,
            self.media_order_down_button,
        ]
        self._audio_dependent_controls = [
            self.tray_option_checks["show_pc_volume"],
            self.tray_option_checks["show_display_volume"],
        ]
        self._drives_dependent_controls = [
            self.tray_option_checks["show_media_drives"],
        ]
        self.tray_option_checks["show_media_tab"].toggled.connect(
            self._sync_tray_option_dependencies
        )
        self.tray_option_checks["show_audio_output"].toggled.connect(
            self._sync_tray_option_dependencies
        )
        self.tray_option_checks["show_drives_tab"].toggled.connect(
            self._sync_tray_option_dependencies
        )
        self.tray_option_checks["show_displays_popup"].toggled.connect(
            self._sync_tray_option_dependencies
        )
        self._sync_tray_option_dependencies()
        self._add_section("tray_options", "Tray options", tray_tabs)

        ha_tab = QWidget()
        ha_layout = QVBoxLayout(ha_tab)
        ha_form = QFormLayout()
        ha_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        ha_layout.addLayout(ha_form)
        self.home_assistant_enabled = QCheckBox("Enable Home Assistant")
        self.home_assistant_enabled.setChecked(
            bool(current_mqtt.get("home_assistant_enabled"))
        )
        ha_form.addRow("Home Assistant", self.home_assistant_enabled)

        self.home_assistant_url = QLineEdit()
        self.home_assistant_url.setPlaceholderText("http://homeassistant.local:8123")
        self.home_assistant_url.setText(str(current_mqtt.get("home_assistant_url") or ""))
        ha_form.addRow("HA URL", self.home_assistant_url)

        self.home_assistant_token = QLineEdit()
        self.home_assistant_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.home_assistant_token.setPlaceholderText("Long-lived access token")
        self.home_assistant_token.setText(str(current_mqtt.get("home_assistant_token") or ""))
        ha_form.addRow("HA token", self.home_assistant_token)
        self.home_assistant_enabled.toggled.connect(self._sync_home_assistant_fields)
        self._sync_home_assistant_fields()
        ha_layout.addStretch(1)
        self._add_section("home_assistant", "Home Assistant", ha_tab)

        mqtt_tab = QWidget()
        mqtt_layout = QVBoxLayout(mqtt_tab)
        mqtt_form = QFormLayout()
        mqtt_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        mqtt_layout.addLayout(mqtt_form)
        self.enabled = QCheckBox()
        self.enabled.setChecked(bool(current_mqtt.get("enabled")))
        mqtt_form.addRow("Enable MQTT", self.enabled)

        self.host = QLineEdit()
        self.host.setPlaceholderText("homeassistant.local")
        self.host.setText(str(current_mqtt.get("host") or ""))
        mqtt_form.addRow("Broker host", self.host)

        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(current_mqtt.get("port") or 1883))
        mqtt_form.addRow("Port", self.port)

        self.username = QLineEdit()
        self.username.setText(str(current_mqtt.get("username") or ""))
        mqtt_form.addRow("Username", self.username)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setText(str(current_mqtt.get("password") or ""))
        mqtt_form.addRow("Password", self.password)

        self.tls = QCheckBox()
        self.tls.setChecked(bool(current_mqtt.get("tls")))
        mqtt_form.addRow("TLS", self.tls)

        self.device_name = QLineEdit()
        self.device_name.setPlaceholderText(ha_mqtt._device_name(current_mqtt))
        self.device_name.setText(str(current_mqtt.get("device_name") or ""))
        mqtt_form.addRow("Device name", self.device_name)

        entity_scroll = QScrollArea()
        entity_scroll.setWidgetResizable(True)
        entity_container = QWidget()
        entity_form = QFormLayout(entity_container)
        entity_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.entity_enabled: dict[str, Any] = {}
        self.entity_names: dict[str, Any] = {}
        for key, label, default_name, default_enabled, tooltip in self._entity_rows(current_mqtt):
            enabled = QCheckBox(label)
            enabled.setChecked(self._entity_enabled(current_mqtt, key, default_enabled))
            if tooltip:
                enabled.setToolTip(tooltip)
            name = QLineEdit()
            name.setPlaceholderText(default_name)
            name.setText(self._entity_name(current_mqtt, key))
            self.entity_enabled[key] = enabled
            self.entity_names[key] = name
            entity_form.addRow(enabled, name)
        entity_scroll.setWidget(entity_container)
        mqtt_layout.addWidget(entity_scroll, 1)
        self._add_section("mqtt", "MQTT", mqtt_tab)

        if experimental_features_available:
            experimental_tab = QWidget()
            experimental_layout = QVBoxLayout(experimental_tab)
            experimental_form = QFormLayout()
            experimental_form.setFieldGrowthPolicy(
                QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
            )
            experimental_layout.addLayout(experimental_form)
            self.network_manager_full_check = QCheckBox("Enable full Network Manager")
            self.network_manager_full_check.setChecked(
                bool(current_experimental.get("network_manager_full"))
            )
            experimental_form.addRow(
                "Network Manager",
                self.network_manager_full_check,
            )
            experimental_note = QLabel(
                "Shows Switch Manager, Network Map, and Wi-Fi in private builds."
            )
            experimental_note.setWordWrap(True)
            experimental_note.setObjectName("trayPanelStatus")
            experimental_layout.addWidget(experimental_note)
            experimental_layout.addStretch(1)
            self._add_section("experimental", "Experimental", experimental_tab)

        self.status = QLabel("")
        self.status.setObjectName("trayPanelStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.rejected.connect(self.dialog.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)

        self.section_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.select_section(initial_section)

    def _add_section(self, section_id: str, label: str, widget: Any) -> None:
        from PySide6.QtWidgets import QListWidgetItem  # type: ignore[import-not-found]

        self._section_ids.append(section_id)
        item = QListWidgetItem(label)
        item.setData(256, section_id)
        self.section_list.addItem(item)
        self.stack.addWidget(widget)

    def _add_tray_options_tab(self, tabs: Any, label: str) -> tuple[Any, Any]:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QFrame,
            QScrollArea,
            QVBoxLayout,
            QWidget,
        )

        scroll = QScrollArea()
        scroll.setObjectName("trayOptionsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)
        scroll.setWidget(container)
        tabs.addTab(scroll, label)
        return layout, scroll

    def _add_tray_section(self, parent_layout: Any, title: str) -> Any:
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QLabel,
            QVBoxLayout,
            QWidget,
        )

        section = QWidget()
        section.setObjectName("trayOptionsSection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("trayPanelTitle")
        layout.addWidget(label)
        parent_layout.addWidget(section)
        return layout

    def _add_tray_checks(
        self,
        parent_layout: Any,
        rows: tuple[tuple[str, str], ...],
        current_tray_options: dict[str, Any],
    ) -> None:
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QCheckBox,
            QGridLayout,
            QWidget,
        )

        grid_widget = QWidget()
        grid_widget.setObjectName("trayOptionsCheckGrid")
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for index, (key, label) in enumerate(rows):
            checkbox = QCheckBox(label)
            checkbox.setChecked(bool(current_tray_options.get(key)))
            self.tray_option_checks[key] = checkbox
            row, column = divmod(index, 2)
            grid.addWidget(checkbox, row, column)
        parent_layout.addWidget(grid_widget)

    def _add_tray_form_row(self, parent_layout: Any, label: str, widget: Any) -> None:
        from PySide6.QtWidgets import QFormLayout  # type: ignore[import-not-found]

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.addRow(label, widget)
        parent_layout.addLayout(form)

    def _sync_tray_option_dependencies(self) -> None:
        media_enabled = self.tray_option_checks["show_media_tab"].isChecked()
        for control in self._media_dependent_controls:
            control.setEnabled(media_enabled)
        audio_enabled = (
            media_enabled
            and self.tray_option_checks["show_audio_output"].isChecked()
        )
        for control in self._audio_dependent_controls:
            control.setEnabled(audio_enabled)
        drives_enabled = self.tray_option_checks["show_drives_tab"].isChecked()
        for control in self._drives_dependent_controls:
            control.setEnabled(drives_enabled)
        displays_enabled = self.tray_option_checks["show_displays_popup"].isChecked()
        self.display_grid_columns_spin.setEnabled(displays_enabled)

    def _sync_home_assistant_fields(self) -> None:
        enabled = self.home_assistant_enabled.isChecked()
        self.home_assistant_url.setEnabled(enabled)
        self.home_assistant_token.setEnabled(enabled)

    def _sync_lan_sync_fields(self) -> None:
        enabled = self.sync_enabled_check.isChecked()
        self.sync_peer_name.setEnabled(enabled)
        self.sync_port.setEnabled(enabled)
        self.sync_password.setEnabled(enabled)

    def _move_media_order(self, direction: int) -> None:
        row = self.media_order_list.currentRow()
        target = row + direction
        if row < 0 or target < 0 or target >= self.media_order_list.count():
            return
        item = self.media_order_list.takeItem(row)
        self.media_order_list.insertItem(target, item)
        self.media_order_list.setCurrentRow(target)

    def _media_order_ids(self) -> list[str]:
        order: list[str] = []
        for index in range(self.media_order_list.count()):
            value = self.media_order_list.item(index).data(256)
            order.append(str(value))
        return order

    def exec(self) -> int:
        return self.dialog.exec()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.dialog, name)

    def select_section(self, section_id: str) -> None:
        try:
            index = self._section_ids.index(section_id)
        except ValueError:
            index = 0
        self.section_list.setCurrentRow(index)
        self.stack.setCurrentIndex(index)

    def accept(self) -> None:
        if self.enabled.isChecked() and not self.host.text().strip():
            self.select_section("mqtt")
            self.status.setText("Broker host is required.")
            return
        if self.hotkey_enabled_check.isChecked() and not self.hotkey_edit.text().strip():
            self.select_section("general")
            self.status.setText("Hotkey is required when enabled.")
            return
        if (
            self.sync_enabled_check.isChecked()
            and not self._sync_password_configured
            and not self.sync_password.text()
        ):
            self.select_section("lan_sync")
            self.status.setText("LAN sync password is required.")
            return
        self.dialog.accept()

    def tray_options(self) -> dict[str, Any]:
        options = {
            key: checkbox.isChecked()
            for key, checkbox in self.tray_option_checks.items()
        }
        options["media_profile_columns"] = self.media_profile_columns_spin.value()
        options["display_grid_columns"] = self.display_grid_columns_spin.value()
        options["media_row_order"] = self._media_order_ids()
        options["visible_adapter_ids"] = self._current_tray_options.get(
            "visible_adapter_ids"
        )
        options["visible_drive_ids"] = self._current_tray_options.get(
            "visible_drive_ids"
        )
        options["action_icons"] = self._current_tray_options.get("action_icons")
        return options

    def hotkey_settings(self) -> dict[str, Any]:
        return {
            "toggle_panel_enabled": self.hotkey_enabled_check.isChecked(),
            "toggle_panel": self.hotkey_edit.text().strip() or "Ctrl+Alt+X",
        }

    def sync_settings(self) -> dict[str, Any]:
        return {
            "enabled": self.sync_enabled_check.isChecked(),
            "peer_name": self.sync_peer_name.text().strip() or None,
            "port": self.sync_port.value(),
        }

    def sync_password_text(self) -> str | None:
        return self.sync_password.text() or None

    def selected_theme_name(self) -> str:
        value = self.theme_combo.currentData()
        return value if isinstance(value, str) else theme_names()[0]

    def mqtt_settings(self) -> dict[str, Any]:
        entities = {
            key: {
                "enabled": enabled.isChecked(),
                "name": self.entity_names[key].text().strip() or None,
            }
            for key, enabled in self.entity_enabled.items()
        }
        return {
            "enabled": self.enabled.isChecked(),
            "host": self.host.text().strip(),
            "port": self.port.value(),
            "username": self.username.text().strip() or None,
            "password": self.password.text() or None,
            "tls": self.tls.isChecked(),
            "allow_shutdown": bool(
                entities["shutdown"]["enabled"] or entities["power"]["enabled"]
            ),
            "device_name": self.device_name.text().strip() or None,
            "home_assistant_enabled": self.home_assistant_enabled.isChecked(),
            "home_assistant_url": self.home_assistant_url.text().strip() or None,
            "home_assistant_token": self.home_assistant_token.text().strip() or None,
            "entities": entities,
        }

    def experimental_features(self) -> dict[str, bool]:
        features = dict(self._current_experimental_features)
        if self.network_manager_full_check is not None:
            features["network_manager_full"] = self.network_manager_full_check.isChecked()
        return features

    def reset_dark_theme(self, checked: bool) -> None:
        self.reset_theme("dark" if checked else theme_names()[0])

    def reset_theme(self, name: str) -> None:
        was_blocked = self.theme_combo.blockSignals(True)
        try:
            index = self.theme_combo.findData(theme_by_name(name).name)
            if index >= 0:
                self.theme_combo.setCurrentIndex(index)
        finally:
            self.theme_combo.blockSignals(was_blocked)

    def reset_start_with_windows(self, checked: bool) -> None:
        was_blocked = self.start_check.blockSignals(True)
        try:
            self.start_check.setChecked(checked)
        finally:
            self.start_check.blockSignals(was_blocked)

    def _entity_rows(
        self,
        settings: dict[str, Any],
    ) -> list[tuple[str, str, str, bool, str | None]]:
        return _entity_rows(settings)

    def _entity_enabled(
        self,
        settings: dict[str, Any],
        key: str,
        default: bool,
    ) -> bool:
        return _entity_enabled(settings, key, default)

    def _entity_name(self, settings: dict[str, Any], key: str) -> str:
        return _entity_name(settings, key)

    def _entity_entry(self, settings: dict[str, Any], key: str) -> dict[str, Any]:
        return _entity_entry(settings, key)


def _entity_rows(settings: dict[str, Any]) -> list[tuple[str, str, str, bool, str | None]]:
    rows: list[tuple[str, str, str, bool, str | None]] = [
        ("current_profile", "Current profile", "Current profile", True, None),
        ("profile_select", "Profile selector", "Profile", True, None),
        ("volume", "Volume", "Volume", True, None),
        ("audio_output", "Audio output", "Audio output", True, None),
        ("play_pause", "Play/Pause media", "Play/Pause media", True, None),
        ("mute_toggle", "Mute/Unmute", "Mute/Unmute", True, None),
        ("mute", "Mute", "Mute", True, None),
        ("unmute", "Unmute", "Unmute", True, None),
        ("muted", "Muted sensor", "Muted", True, None),
        (
            "shutdown",
            "Shutdown",
            "Shutdown",
            bool(settings.get("allow_shutdown")),
            "Expose the Home Assistant Shutdown button. It powers off Windows immediately.",
        ),
        ("online", "Online", "Online", True, None),
        (
            "power",
            "Power switch",
            "Power",
            bool(settings.get("allow_shutdown")),
            (
                "Switch OFF shuts down Windows. Switch ON publishes a wake payload "
                "with this PC MAC."
            ),
        ),
    ]
    try:
        profile_names = profiles.list_favorite_profiles()
    except Exception:
        app_logging.get_logger("tray").exception("failed to list favorite profiles")
        profile_names = []
    for profile_name in profile_names:
        rows.append(
            (
                ha_mqtt.profile_entity_key(profile_name),
                f"Profile: {profile_name}",
                f"Apply {profile_name}",
                True,
                None,
            )
        )
    try:
        hdmi_volume_displays = display_inventory.exposed_hdmi_volume_displays()
    except Exception:
        app_logging.get_logger("tray").exception(
            "failed to list exposed HDMI volume displays"
        )
        hdmi_volume_displays = []
    for display_state in hdmi_volume_displays:
        title = display_inventory.display_title(display_state)
        rows.append(
            (
                ha_mqtt.display_volume_entity_key(display_state),
                f"Display volume: {title}",
                f"{title} HDMI volume",
                True,
                None,
            )
        )
    return rows


def _entity_enabled(settings: dict[str, Any], key: str, default: bool) -> bool:
    entry = _entity_entry(settings, key)
    if "enabled" not in entry:
        return default
    return bool(entry["enabled"])


def _entity_name(settings: dict[str, Any], key: str) -> str:
    value = _entity_entry(settings, key).get("name")
    return value if isinstance(value, str) else ""


def _entity_entry(settings: dict[str, Any], key: str) -> dict[str, Any]:
    entities = settings.get("entities")
    if not isinstance(entities, dict):
        return {}
    entry = entities.get(key)
    return entry if isinstance(entry, dict) else {}


def show_missing_displays_dialog(
    parent: Any,
    profile_name: str,
    missing_display_names: list[str],
) -> None:  # pragma: no cover - imported only when GUI dependencies exist
    from PySide6.QtWidgets import (  # type: ignore[import-not-found]
        QDialog,
        QDialogButtonBox,
        QLabel,
        QVBoxLayout,
    )

    dialog = QDialog(parent)
    dialog.setWindowTitle("Profilo non applicabile")
    qt_assets.set_window_icon(dialog)
    dialog.setStyleSheet(build_app_stylesheet(_current_theme()))
    dialog.setMinimumWidth(380)

    layout = QVBoxLayout(dialog)
    layout.setSpacing(10)

    if len(missing_display_names) == 1:
        intro_text = (
            f"Impossibile applicare il profilo \"{profile_name}\": "
            "lo schermo seguente non è disponibile."
        )
    else:
        intro_text = (
            f"Impossibile applicare il profilo \"{profile_name}\": "
            "i seguenti schermi non sono disponibili."
        )
    intro = QLabel(intro_text)
    intro.setWordWrap(True)
    layout.addWidget(intro)

    if missing_display_names:
        bullet_list = "\n".join(f"• {name}" for name in missing_display_names)
        bullets = QLabel(bullet_list)
        bullets.setWordWrap(True)
        bullets.setObjectName("trayMissingDisplayList")
        layout.addWidget(bullets)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)

    dialog.exec()


class LanSyncImportDialog:  # pragma: no cover - imported only when GUI dependencies exist
    def __init__(self, parent: Any = None) -> None:
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QCheckBox,
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )

        self._peers: list[Any] = []
        self.dialog = QDialog(parent)
        self.dialog.setWindowTitle("Import from LAN PC")
        qt_assets.set_window_icon(self.dialog)
        self.dialog.setMinimumWidth(460)
        self.dialog.setStyleSheet(build_app_stylesheet(_current_theme()))

        layout = QVBoxLayout(self.dialog)
        peer_row = QWidget()
        peer_layout = QHBoxLayout(peer_row)
        peer_layout.setContentsMargins(0, 0, 0, 0)
        self.peer_combo = QComboBox()
        peer_layout.addWidget(self.peer_combo, 1)
        self.refresh_button = QPushButton("Refresh")
        peer_layout.addWidget(self.refresh_button)
        layout.addWidget(peer_row)

        form = QFormLayout()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password", self.password)
        layout.addLayout(form)

        self.preview = QLabel("")
        self.preview.setObjectName("trayPanelStatus")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)

        self.network_settings_check = QCheckBox("Network settings")
        self.network_settings_check.setChecked(True)
        self.network_devices_check = QCheckBox("Network devices")
        self.network_devices_check.setChecked(True)
        self.network_passwords_check = QCheckBox("Network passwords")
        self.network_passwords_check.setChecked(True)
        self.display_profiles_check = QCheckBox("Display profiles")
        self.display_profiles_check.setChecked(True)
        for checkbox in (
            self.network_settings_check,
            self.network_devices_check,
            self.network_passwords_check,
            self.display_profiles_check,
        ):
            layout.addWidget(checkbox)

        self.status = QLabel("")
        self.status.setObjectName("trayPanelStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.import_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.import_button.setText("Import")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.dialog.reject)
        layout.addWidget(self.buttons)

        self.refresh_button.clicked.connect(self.refresh_peers)
        self.peer_combo.currentIndexChanged.connect(self.refresh_preview)
        self.refresh_peers()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.dialog, name)

    def exec(self) -> int:
        return self.dialog.exec()

    def refresh_peers(self) -> None:
        try:
            from xtray_sync.discovery import discover_peers
        except ImportError as exc:
            self.status.setText(f"xtray-sync unavailable: {exc}")
            return
        self.peer_combo.clear()
        self._peers = discover_peers(timeout=1.0)
        for peer in self._peers:
            self.peer_combo.addItem(peer.label, peer)
        if not self._peers:
            self.peer_combo.addItem("No XTray peers found", None)
            self.preview.setText("")
        self.refresh_preview()

    def refresh_preview(self) -> None:
        peer = self.selected_peer()
        if peer is None:
            self.preview.setText("")
            return
        try:
            from xtray_sync.client import SyncPeer, preview

            data = preview(SyncPeer.from_peer(peer), timeout=2.0)
            sections = data.get("sections") if isinstance(data, dict) else {}
            if not isinstance(sections, dict):
                sections = {}
            self.preview.setText(
                "Settings: {settings}; devices: {devices}; passwords: {passwords}; profiles: {profiles}".format(
                    settings="yes" if sections.get("network_manager_settings") else "no",
                    devices=int(sections.get("network_devices") or 0),
                    passwords=int(sections.get("network_passwords") or 0),
                    profiles=int(sections.get("display_profiles") or 0),
                )
            )
        except Exception as exc:
            self.preview.setText(f"Preview unavailable: {exc}")

    def selected_peer(self) -> Any | None:
        return self.peer_combo.currentData()

    def sync_password(self) -> str:
        return self.password.text()

    def import_options(self) -> Any:
        from xtray_sync.bundle import ImportOptions

        return ImportOptions(
            network_settings=self.network_settings_check.isChecked(),
            network_devices=self.network_devices_check.isChecked(),
            network_passwords=self.network_passwords_check.isChecked(),
            display_profiles=self.display_profiles_check.isChecked(),
        )

    def accept(self) -> None:
        if self.selected_peer() is None:
            self.status.setText("Select a LAN peer.")
            return
        if not self.sync_password():
            self.status.setText("Password is required.")
            return
        self.dialog.accept()


class UpdateOptionsDialog:  # pragma: no cover - imported only when GUI dependencies exist
    def __init__(
        self,
        parent: Any,
        *,
        update_info: Any,
        pc_sync_enabled: bool = False,
        network_manager_full_enabled: bool = False,
        network_manager_full_available: bool = False,
    ) -> None:
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QCheckBox,
            QDialog,
            QDialogButtonBox,
            QLabel,
            QVBoxLayout,
        )

        self.dialog = QDialog(parent)
        self.dialog.setWindowTitle("XTray Update")
        qt_assets.set_window_icon(self.dialog)
        self.dialog.setMinimumWidth(420)
        self.dialog.setStyleSheet(build_app_stylesheet(_current_theme()))

        layout = QVBoxLayout(self.dialog)
        intro = QLabel(
            f"XTray {update_info.version} is available.\n"
            "Select optional features to enable after installing the update."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.core_check = QCheckBox("Core XTray")
        self.core_check.setChecked(True)
        self.core_check.setEnabled(False)
        layout.addWidget(self.core_check)

        self.pc_sync_check = QCheckBox("PC Sync")
        self.pc_sync_check.setChecked(bool(pc_sync_enabled))
        layout.addWidget(self.pc_sync_check)

        self.network_manager_full_check = QCheckBox("Full Network Manager experimental")
        self.network_manager_full_check.setChecked(bool(network_manager_full_enabled))
        self.network_manager_full_check.setEnabled(bool(network_manager_full_available))
        if not network_manager_full_available:
            self.network_manager_full_check.setToolTip(
                "This build does not include the private full Network Manager modules."
            )
        layout.addWidget(self.network_manager_full_check)

        note = QLabel("XTray will close and reopen after the installer starts.")
        note.setWordWrap(True)
        note.setObjectName("trayPanelStatus")
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Download and Install")
        buttons.accepted.connect(self.dialog.accept)
        buttons.rejected.connect(self.dialog.reject)
        layout.addWidget(buttons)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.dialog, name)

    def exec(self) -> int:
        return self.dialog.exec()

    def install_options(self) -> Any:
        from xtray import updater

        return updater.UpdateInstallOptions(
            pc_sync=self.pc_sync_check.isChecked(),
            network_manager_full=self.network_manager_full_check.isChecked()
            and self.network_manager_full_check.isEnabled(),
        )
