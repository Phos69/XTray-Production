"""Build the MainWindow widget tree.

`MainWindow.__init__` previously held ~280 LOC of Qt widget construction
(menu bar, Profiles tab with profile list + edit form + preview scene,
Displays tab with inventory list + Display/Defaults/Home Assistant
groups). That layout had no logic, just sequential QWidget composition
and signal wiring; keeping it in MainWindow mixed visual scaffolding
with event handlers and state mutations.

This module exposes a single ``build(window)`` entry point that the
MainWindow calls after initialising its mutable state. The functions
populate attributes on ``window`` (window.profile_panel, window.edit_form,
window.inventory_*, ecc.) so the rest of MainWindow keeps referring to
``self.X`` unchanged.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from xtray import config
from xtray.core.theme import build_app_stylesheet

from . import _helpers
from .display_manager.ui_model import ORIENTATION_CHOICES
from .display_manager.ui_panels import EditFormPanel, PreviewSceneController, ProfileListPanel

if TYPE_CHECKING:  # pragma: no cover
    from .app import MainWindow

_HIDDEN_DISPLAY_FORM_ROWS = ("pos_x", "pos_y", "brightness", "contrast", "input_source")
_ACTION_BUTTON_ROLES = {
    "capture_button": "accent",
    "save_button": "success",
    "apply_button": "primary",
    "delete_button": "danger",
}


def build(window: MainWindow) -> None:
    """Build the entire MainWindow widget tree on the given window."""
    from PySide6.QtCore import Qt  # type: ignore[import-not-found]
    from PySide6.QtGui import QAction  # type: ignore[import-not-found]
    from PySide6.QtWidgets import (  # type: ignore[import-not-found]
        QAbstractItemView,
        QComboBox,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QMainWindow,
        QPushButton,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )

    _build_window_chrome(window, QMainWindow, QAction, QWidget, QVBoxLayout, QTabWidget)
    _build_profiles_tab(
        window, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QGroupBox,
    )
    _build_displays_tab(
        window,
        Qt,
        QAbstractItemView,
        QComboBox,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
    _wire_signals(window)


def _build_window_chrome(
    window: MainWindow,
    QMainWindow: Any,
    QAction: Any,
    QWidget: Any,
    QVBoxLayout: Any,
    QTabWidget: Any,
) -> None:
    from .app import _install_xtray_window_icon

    window.window = QMainWindow()
    window.window.setWindowTitle("Computer Manager")
    _install_xtray_window_icon(window=window.window)
    window.window.resize(1180, 720)
    window.window.setStyleSheet(build_app_stylesheet(window._theme))
    view_menu = window.window.menuBar().addMenu("View")
    window.dark_theme_action = QAction("Dark theme", window.window)
    window.dark_theme_action.setCheckable(True)
    window.dark_theme_action.setChecked(window._theme.name == "dark")
    window.dark_theme_action.triggered.connect(window.on_theme_toggled)
    view_menu.addAction(window.dark_theme_action)

    root = QWidget()
    root_layout = QVBoxLayout(root)
    window.window.setCentralWidget(root)
    window.main_tabs = QTabWidget()
    root_layout.addWidget(window.main_tabs, 1)


def _build_profiles_tab(
    window: MainWindow,
    QWidget: Any,
    QHBoxLayout: Any,
    QVBoxLayout: Any,
    QLabel: Any,
    QPushButton: Any,
    QGroupBox: Any,
) -> None:
    profiles_tab = QWidget()
    profiles_layout = QHBoxLayout(profiles_tab)
    window.main_tabs.addTab(profiles_tab, "Profiles")

    window.profile_panel = ProfileListPanel(
        on_profile_selected=window.load_profile,
        on_current_selected=window.load_current_preview,
    )
    window.profile_list = window.profile_panel.profile_list
    profiles_layout.addWidget(window.profile_list, 1)

    right_panel = QWidget()
    right_layout = QVBoxLayout(right_panel)
    right_layout.setContentsMargins(0, 0, 0, 0)

    window.edit_form = EditFormPanel()
    window.profile_name = window.edit_form.profile_name
    window.favorite_checkbox = window.edit_form.favorite_checkbox
    window.icon_picker = window.edit_form.icon_picker
    window.icon_picker.set_color(window._theme.text)
    window.selection_name = window.edit_form.selection_name
    window.display_name = window.edit_form.display_name
    window.audio_combo = window.edit_form.audio_combo
    window.audio_volume = window.edit_form.audio_volume
    window.audio_mute = window.edit_form.audio_mute
    window.audio_state = window.edit_form.audio_state
    window.enabled_checkbox = window.edit_form.enabled_checkbox
    window.primary_checkbox = window.edit_form.primary_checkbox
    window.resolution = window.edit_form.resolution
    window.refresh = window.edit_form.refresh
    window.pos_x = window.edit_form.pos_x
    window.pos_y = window.edit_form.pos_y
    window.orientation = window.edit_form.orientation
    window.brightness = window.edit_form.brightness
    window.contrast = window.edit_form.contrast
    window.input_source = window.edit_form.input_source
    for key in _HIDDEN_DISPLAY_FORM_ROWS:
        row = window.edit_form.form_rows.get(key)
        if row is None:
            continue
        label, widget = row
        label.setVisible(False)
        widget.setVisible(False)

    action_layout = QHBoxLayout()
    action_layout.addWidget(QLabel("Profile"))
    action_layout.addWidget(window.profile_name, 1)
    action_layout.addSpacing(12)
    action_layout.addWidget(QLabel("Favorite"))
    action_layout.addWidget(window.favorite_checkbox)
    action_layout.addSpacing(12)
    action_layout.addWidget(QLabel("Icon"))
    action_layout.addWidget(window.icon_picker.widget)
    action_layout.addSpacing(16)
    window.capture_button = QPushButton("Capture")
    window.save_button = QPushButton("Save")
    window.apply_button = QPushButton("Apply")
    window.delete_button = QPushButton("Delete")
    window._action_buttons = [
        window.capture_button,
        window.save_button,
        window.apply_button,
        window.delete_button,
    ]
    for attribute, role in _ACTION_BUTTON_ROLES.items():
        _helpers._set_button_role(getattr(window, attribute), role, window._qt)
    for button in window._action_buttons:
        action_layout.addWidget(button)
    right_layout.addLayout(action_layout)

    window.display_layout_group = QGroupBox("Display arrangement")
    display_layout_box = QVBoxLayout(window.display_layout_group)
    window.preview_controller = PreviewSceneController()
    window.scene = window.preview_controller.scene
    window.view = window.preview_controller.view
    window.view.setMinimumHeight(360)
    display_layout_box.addWidget(window.view, 1)
    right_layout.addWidget(window.display_layout_group, 1)

    window.object_list = window.edit_form.object_list
    right_layout.addWidget(window.edit_form.display_props_group, 2)
    window.edit_form.audio_props_widget.setVisible(False)
    window.object_list.currentItemChanged.connect(window._editor.handle_object_list_changed)

    profiles_layout.addWidget(right_panel, 5)


def _build_displays_tab(
    window: MainWindow,
    Qt: Any,
    QAbstractItemView: Any,
    QComboBox: Any,
    QFormLayout: Any,
    QGroupBox: Any,
    QHBoxLayout: Any,
    QLabel: Any,
    QLineEdit: Any,
    QListWidget: Any,
    QPushButton: Any,
    QVBoxLayout: Any,
    QWidget: Any,
) -> None:
    displays_tab = QWidget()
    displays_layout = QHBoxLayout(displays_tab)
    window.main_tabs.addTab(displays_tab, "Displays")
    window.display_inventory_list = QListWidget()
    window.display_inventory_list.setDragEnabled(True)
    window.display_inventory_list.setAcceptDrops(True)
    window.display_inventory_list.setDropIndicatorShown(True)
    window.display_inventory_list.setDragDropMode(
        QAbstractItemView.DragDropMode.InternalMove
    )
    window.display_inventory_list.setDefaultDropAction(Qt.DropAction.MoveAction)
    window.display_inventory_list.setSelectionMode(
        QAbstractItemView.SelectionMode.SingleSelection
    )
    window.display_inventory_list.setToolTip(
        "Drag to reorder; this order is mirrored in the XTray tray."
    )
    displays_layout.addWidget(window.display_inventory_list, 1)

    display_detail = QWidget()
    display_detail_layout = QVBoxLayout(display_detail)
    display_group = QGroupBox("Display")
    display_detail_form = QFormLayout(display_group)
    display_detail_layout.addWidget(display_group)
    defaults_group = QGroupBox("Default selection")
    defaults_form = QFormLayout(defaults_group)
    display_detail_layout.addWidget(defaults_group)
    home_assistant_group = QGroupBox("Home Assistant")
    home_assistant_form = QFormLayout(home_assistant_group)
    display_detail_layout.addWidget(home_assistant_group)
    window.inventory_name = QLabel("-")
    window.inventory_name.setWordWrap(True)
    window.inventory_friendly_name = QLineEdit()
    window.inventory_status = QLabel("-")
    window.inventory_status.setWordWrap(True)
    window.inventory_identity = QLabel("-")
    window.inventory_identity.setWordWrap(True)
    window.inventory_profiles = QLabel("-")
    window.inventory_profiles.setWordWrap(True)
    window.inventory_volume_control = QComboBox()
    window.inventory_volume_control.addItem("No control", config.VOLUME_CONTROL_NONE)
    window.inventory_volume_control.addItem("HDMI", config.VOLUME_CONTROL_HDMI)
    window.inventory_volume_control.addItem(
        "Home Assistant entity", config.VOLUME_CONTROL_HA_ENTITY
    )
    window.inventory_volume_ha_entity = QLineEdit()
    window.inventory_volume_ha_entity.setPlaceholderText(
        "media_player.tv  or  number.tv_volume"
    )
    window.inventory_volume_ha_entity.setToolTip(
        "Home Assistant entity id. Supported domains:\n"
        "  number.*        → number.set_value (0-100)\n"
        "  media_player.*  → media_player.volume_set (volume_level 0.0-1.0)"
    )
    window.inventory_volume_ha_entity.setVisible(False)
    volume_container = QWidget()
    volume_layout = QVBoxLayout(volume_container)
    volume_layout.setContentsMargins(0, 0, 0, 0)
    volume_layout.setSpacing(4)
    volume_layout.addWidget(window.inventory_volume_control)
    volume_layout.addWidget(window.inventory_volume_ha_entity)
    window.inventory_power_on_ha_service = QLineEdit()
    window.inventory_power_on_ha_service.setPlaceholderText(
        "wake_on_lan.send_magic_packet"
    )
    window.inventory_power_on_ha_service.setToolTip(
        "Home Assistant service/action id called before this display is enabled."
    )
    window.inventory_power_on_ha_service_data = QLineEdit()
    window.inventory_power_on_ha_service_data.setPlaceholderText(
        '{"mac":"AA:BB:CC:DD:EE:FF"}'
    )
    window.inventory_power_on_ha_service_data.setToolTip(
        "Optional Home Assistant service data as a JSON object."
    )
    window.inventory_power_off_ha_service = QLineEdit()
    window.inventory_power_off_ha_service.setPlaceholderText("media_player.turn_off")
    window.inventory_power_off_ha_service.setToolTip(
        "Home Assistant service/action id called after this display is disabled."
    )
    window.inventory_power_off_ha_service_data = QLineEdit()
    window.inventory_power_off_ha_service_data.setPlaceholderText(
        '{"entity_id":"media_player.tv"}'
    )
    window.inventory_power_off_ha_service_data.setToolTip(
        "Optional Home Assistant service data as a JSON object."
    )
    window.inventory_default_resolution = QComboBox()
    window.inventory_default_refresh = QComboBox()
    window.inventory_default_orientation = QComboBox()
    window.inventory_default_orientation.addItem("Use display value", None)
    for degrees, text in ORIENTATION_CHOICES:
        window.inventory_default_orientation.addItem(text, degrees)
    defaults_tooltip = (
        "Applied when a disabled display is enabled in a profile.\n"
        "Leave on the placeholder row to keep the value the display\n"
        "reports at that moment."
    )
    window.inventory_default_resolution.setToolTip(defaults_tooltip)
    window.inventory_default_refresh.setToolTip(defaults_tooltip)
    window.inventory_default_orientation.setToolTip(defaults_tooltip)
    display_detail_form.addRow("Display", window.inventory_name)
    display_detail_form.addRow("Friendly name", window.inventory_friendly_name)
    display_detail_form.addRow("Status", window.inventory_status)
    display_detail_form.addRow("Identity", window.inventory_identity)
    display_detail_form.addRow("Profiles", window.inventory_profiles)
    defaults_form.addRow("Resolution", window.inventory_default_resolution)
    defaults_form.addRow("Refresh", window.inventory_default_refresh)
    defaults_form.addRow("Orientation", window.inventory_default_orientation)
    home_assistant_form.addRow("Volume", volume_container)
    home_assistant_form.addRow("Power on service", window.inventory_power_on_ha_service)
    home_assistant_form.addRow(
        "Power on arguments", window.inventory_power_on_ha_service_data
    )
    home_assistant_form.addRow(
        "Power off service", window.inventory_power_off_ha_service
    )
    home_assistant_form.addRow(
        "Power off arguments", window.inventory_power_off_ha_service_data
    )
    window.refresh_displays_button = QPushButton("Refresh")
    display_detail_layout.addWidget(window.refresh_displays_button)
    display_detail_layout.addStretch(1)
    displays_layout.addWidget(display_detail, 2)


def _wire_signals(window: MainWindow) -> None:
    from .app import _install_computer_manager_extension

    editor = window._editor
    window.capture_button.clicked.connect(editor.capture_current)
    window.save_button.clicked.connect(editor.save_current)
    window.apply_button.clicked.connect(editor.apply_current)
    window.delete_button.clicked.connect(editor.delete_current)
    window.resolution.currentIndexChanged.connect(editor.on_resolution_changed)
    window.refresh.currentIndexChanged.connect(editor.update_selected_display)
    window.orientation.currentIndexChanged.connect(editor.update_selected_display)
    window.favorite_checkbox.toggled.connect(editor.on_favorite_toggled)
    window.enabled_checkbox.toggled.connect(editor.on_enabled_toggled)
    window.primary_checkbox.toggled.connect(editor.on_primary_toggled)
    window.audio_combo.currentIndexChanged.connect(editor.on_audio_changed)
    window.audio_volume.valueChanged.connect(editor.on_audio_volume_changed)
    window.audio_mute.currentIndexChanged.connect(editor.on_audio_mute_changed)
    window.icon_picker.on_change = editor.on_icon_changed
    window.main_tabs.currentChanged.connect(window.on_main_tab_changed)
    inventory = window._inventory
    window.display_inventory_list.currentRowChanged.connect(
        inventory.on_display_inventory_selected
    )
    window.display_inventory_list.model().rowsMoved.connect(
        inventory.persist_display_inventory_order
    )
    window.refresh_displays_button.clicked.connect(inventory.refresh_display_inventory_async)
    window.inventory_friendly_name.editingFinished.connect(
        inventory.on_inventory_friendly_name_changed
    )
    window.inventory_volume_control.currentIndexChanged.connect(
        inventory.on_inventory_volume_control_changed
    )
    window.inventory_volume_ha_entity.editingFinished.connect(
        inventory.on_inventory_volume_ha_entity_changed
    )
    window.inventory_power_on_ha_service.editingFinished.connect(
        inventory.on_inventory_power_on_ha_service_changed
    )
    window.inventory_power_on_ha_service_data.editingFinished.connect(
        inventory.on_inventory_power_on_ha_service_data_changed
    )
    window.inventory_power_off_ha_service.editingFinished.connect(
        inventory.on_inventory_power_off_ha_service_changed
    )
    window.inventory_power_off_ha_service_data.editingFinished.connect(
        inventory.on_inventory_power_off_ha_service_data_changed
    )
    window.inventory_default_resolution.currentIndexChanged.connect(
        inventory.on_inventory_default_resolution_changed
    )
    window.inventory_default_refresh.currentIndexChanged.connect(
        inventory.on_inventory_default_refresh_changed
    )
    window.inventory_default_orientation.currentIndexChanged.connect(
        inventory.on_inventory_default_orientation_changed
    )
    window._computer_manager_extension = _install_computer_manager_extension(window)
