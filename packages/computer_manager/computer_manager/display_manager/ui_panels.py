"""Qt panel builders used by the desktop GUI."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from xtray.core.icons import IconPickerButton

from .ui_model import ORIENTATION_CHOICES


class ProfileListPanel:  # pragma: no cover - imported only when GUI dependencies exist
    """Owns the saved-profile list widget plus the always-present *current* entry."""

    CURRENT_SENTINEL = "__current__"
    CURRENT_LABEL = "(current)"

    def __init__(
        self,
        on_profile_selected: Callable[[str], None],
        on_current_selected: Callable[[], None],
    ) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QListWidget, QListWidgetItem  # type: ignore[import-not-found]

        self._qt = Qt
        self._list_item_cls = QListWidgetItem
        self.widget = QListWidget()
        self.profile_list = self.widget
        self._on_profile_selected = on_profile_selected
        self._on_current_selected = on_current_selected
        self._suppress_callback = False
        self._add_current_row()
        self.profile_list.currentItemChanged.connect(self._handle_selection)

    def _add_current_row(self) -> None:
        item = self._list_item_cls(self.CURRENT_LABEL)
        item.setData(self._qt.ItemDataRole.UserRole, self.CURRENT_SENTINEL)
        font = item.font()
        font.setItalic(True)
        item.setFont(font)
        self.profile_list.addItem(item)

    def _handle_selection(self, current: Any, _previous: Any) -> None:
        if self._suppress_callback or current is None:
            return
        data = current.data(self._qt.ItemDataRole.UserRole)
        if data == self.CURRENT_SENTINEL:
            self._on_current_selected()
        else:
            self._on_profile_selected(current.text())

    def set_profiles(self, names: list[str]) -> None:
        """Replace the saved-profile rows while keeping *current* pinned at row 0."""
        selected_name = self.selected_profile_name()
        was_blocked = self.profile_list.blockSignals(True)
        self._suppress_callback = True
        try:
            self.profile_list.clear()
            self._add_current_row()
            for name in names:
                self.profile_list.addItem(name)
            if selected_name:
                self._set_selection_by_name(selected_name)
        finally:
            self._suppress_callback = False
            self.profile_list.blockSignals(was_blocked)

    def selected_profile_name(self) -> str | None:
        item = self.profile_list.currentItem()
        if item is None:
            return None
        data = item.data(self._qt.ItemDataRole.UserRole)
        if data == self.CURRENT_SENTINEL:
            return None
        return item.text()

    def select_current(self) -> None:
        was_blocked = self.profile_list.blockSignals(True)
        self._suppress_callback = True
        try:
            self.profile_list.setCurrentRow(0)
        finally:
            self._suppress_callback = False
            self.profile_list.blockSignals(was_blocked)

    def select_profile(self, name: str | None) -> None:
        was_blocked = self.profile_list.blockSignals(True)
        self._suppress_callback = True
        try:
            if not name:
                self.select_current()
                return
            self._set_selection_by_name(name)
        finally:
            self._suppress_callback = False
            self.profile_list.blockSignals(was_blocked)

    def _set_selection_by_name(self, name: str) -> None:
        for row in range(self.profile_list.count()):
            item = self.profile_list.item(row)
            if item is None:
                continue
            if item.data(self._qt.ItemDataRole.UserRole) == self.CURRENT_SENTINEL:
                continue
            if item.text() == name:
                self.profile_list.setCurrentItem(item)
                return
        self.profile_list.setCurrentRow(0)


class PreviewSceneController:  # pragma: no cover - imported only when GUI dependencies exist
    """Owns the monitor preview scene and view."""

    def __init__(self) -> None:
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QGraphicsScene,
            QGraphicsView,
        )

        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHints(self.view.renderHints())


class EditFormPanel:  # pragma: no cover - imported only when GUI dependencies exist
    """Owns the profile/audio/display edit form widgets grouped into sub-frames."""

    def __init__(self) -> None:
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QCheckBox,
            QComboBox,
            QFormLayout,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QSpinBox,
            QVBoxLayout,
            QWidget,
        )

        self.widget = QWidget()
        outer = QVBoxLayout(self.widget)
        outer.setContentsMargins(0, 0, 0, 0)
        self.form_rows: dict[str, tuple[Any, Any]] = {}

        # Profile fields live on the top action row, not in this panel.
        self.profile_name = QLineEdit()
        self.favorite_checkbox = QCheckBox()
        self.favorite_checkbox.setEnabled(False)
        self.icon_picker = IconPickerButton()
        self.icon_picker.setEnabled(False)

        self.display_props_group = QGroupBox("Display properties")
        props_h = QHBoxLayout(self.display_props_group)

        self.object_list = QListWidget()
        props_h.addWidget(self.object_list, 1)

        right_pane = QWidget()
        right_v = QVBoxLayout(right_pane)
        right_v.setContentsMargins(0, 0, 0, 0)

        self.display_props_widget = QWidget()
        display_form = QFormLayout(self.display_props_widget)
        display_form.setContentsMargins(0, 0, 0, 0)
        self.selection_name = QLabel("-")
        self.display_name = self.selection_name
        self.enabled_checkbox = QCheckBox()
        self.primary_checkbox = QCheckBox()
        self.resolution = QComboBox()
        self.refresh = QComboBox()
        self.pos_x = _spinbox(QSpinBox, -50000, 50000)
        self.pos_y = _spinbox(QSpinBox, -50000, 50000)
        self.orientation = QComboBox()
        for degrees, text in ORIENTATION_CHOICES:
            self.orientation.addItem(text, degrees)
        self.brightness = _spinbox(QSpinBox, -1, 100)
        self.contrast = _spinbox(QSpinBox, -1, 100)
        self.input_source = _spinbox(QSpinBox, -1, 255)
        for key, label, widget in (
            ("selection", "Display", self.selection_name),
            ("enabled", "Enabled", self.enabled_checkbox),
            ("primary", "Primary", self.primary_checkbox),
            ("resolution", "Resolution", self.resolution),
            ("refresh", "Refresh", self.refresh),
            ("pos_x", "X", self.pos_x),
            ("pos_y", "Y", self.pos_y),
            ("orientation", "Orientation", self.orientation),
            ("brightness", "Brightness", self.brightness),
            ("contrast", "Contrast", self.contrast),
            ("input_source", "Input", self.input_source),
        ):
            label_widget = QLabel(label)
            display_form.addRow(label_widget, widget)
            self.form_rows[key] = (label_widget, widget)
        right_v.addWidget(self.display_props_widget)

        self.audio_props_widget = QWidget()
        audio_form = QFormLayout(self.audio_props_widget)
        audio_form.setContentsMargins(0, 0, 0, 0)
        self.audio_combo = QComboBox()
        self.audio_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.audio_volume = _spinbox(QSpinBox, -1, 100)
        self.audio_volume.setSpecialValueText("Keep current")
        self.audio_volume.setSuffix("%")
        self.audio_mute = QComboBox()
        self.audio_mute.addItem("Keep current", None)
        self.audio_mute.addItem("Muted", True)
        self.audio_mute.addItem("Unmuted", False)
        self.audio_state = QLabel("-")
        for key, label, widget in (
            ("audio_combo", "Source", self.audio_combo),
            ("audio_volume", "Volume", self.audio_volume),
            ("audio_mute", "Mute", self.audio_mute),
            ("audio_state", "State", self.audio_state),
        ):
            label_widget = QLabel(label)
            audio_form.addRow(label_widget, widget)
            self.form_rows[key] = (label_widget, widget)
        right_v.addWidget(self.audio_props_widget)
        right_v.addStretch(1)

        props_h.addWidget(right_pane, 2)
        outer.addWidget(self.display_props_group)

        outer.addStretch(1)


def _spinbox(cls: type, minimum: int, maximum: int) -> Any:
    widget = cls()
    widget.setRange(minimum, maximum)
    return widget
