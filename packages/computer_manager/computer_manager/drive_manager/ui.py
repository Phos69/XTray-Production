"""UI mixin for the Drive tab of the Computer Manager window.

Owns the "Drives" tab grafted into the Computer Manager main window:
- two lists (local + network) each with included/excluded sub-lists,
- the drive details panel + Add Network Drive button.
"""
from __future__ import annotations

from typing import Any

from xtray import config
from xtray.core.computer_models import DriveInfo
from xtray.core.dialogs import NetworkDriveDialog


def _drive_list_label(drive: DriveInfo) -> str:
    label = f" {drive.label}" if drive.label else ""
    return f"{drive.letter}:{label}\n{drive.drive_type or '-'}"


def _drive_key(drive: DriveInfo) -> str:
    return drive.letter.upper()


def _normalize_drive_key(value: Any) -> str:
    return str(value or "").strip().upper()


def _is_network_drive(drive: DriveInfo) -> bool:
    return (drive.drive_type or "").casefold() == "network"


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "-"
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024


class DriveTabMixin:  # pragma: no cover - imported only when GUI dependencies exist
    """All methods that own the Drives tab.

    Hosting class must provide: `host`, `_drive_service`, `_drives`,
    `_selected_drive`, `_drives_loaded`, `_drives_refreshing`.
    """

    def _build_drives_tab(self) -> None:
        from PySide6.QtWidgets import (
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

        tab = QWidget()
        layout = QHBoxLayout(tab)

        lists_area = QWidget()
        lists_layout = QHBoxLayout(lists_area)
        lists_layout.setContentsMargins(0, 0, 0, 0)

        local_group = QGroupBox("Local drives")
        local_layout = QVBoxLayout(local_group)
        self.local_drive_included_list = QListWidget()
        self.local_drive_excluded_list = QListWidget()
        self.local_drive_list = self.local_drive_included_list
        local_layout.addWidget(QLabel("Included in tray"))
        local_layout.addWidget(self.local_drive_included_list, 1)
        local_buttons = QHBoxLayout()
        self.exclude_local_drive_button = QPushButton("Exclude from tray")
        self.include_local_drive_button = QPushButton("Include in tray")
        local_buttons.addStretch(1)
        local_buttons.addWidget(self.exclude_local_drive_button)
        local_buttons.addWidget(self.include_local_drive_button)
        local_buttons.addStretch(1)
        local_layout.addLayout(local_buttons)
        local_layout.addWidget(QLabel("Not included in tray"))
        local_layout.addWidget(self.local_drive_excluded_list, 1)

        network_group = QGroupBox("Network drives")
        network_layout = QVBoxLayout(network_group)
        self.network_drive_included_list = QListWidget()
        self.network_drive_excluded_list = QListWidget()
        self.network_drive_list = self.network_drive_included_list
        network_layout.addWidget(QLabel("Included in tray"))
        network_layout.addWidget(self.network_drive_included_list, 1)
        network_buttons = QHBoxLayout()
        self.exclude_network_drive_button = QPushButton("Exclude from tray")
        self.include_network_drive_button = QPushButton("Include in tray")
        network_buttons.addStretch(1)
        network_buttons.addWidget(self.exclude_network_drive_button)
        network_buttons.addWidget(self.include_network_drive_button)
        network_buttons.addStretch(1)
        network_layout.addLayout(network_buttons)
        network_layout.addWidget(QLabel("Not included in tray"))
        network_layout.addWidget(self.network_drive_excluded_list, 1)

        lists_layout.addWidget(local_group, 1)
        lists_layout.addWidget(network_group, 1)
        layout.addWidget(lists_area, 2)

        detail_group = QGroupBox("Drive")
        detail_layout = QVBoxLayout(detail_group)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        detail_layout.addLayout(form)

        self.drive_letter = QLineEdit()
        self.drive_label = QLineEdit()
        self.drive_type = QLineEdit()
        self.drive_filesystem = QLineEdit()
        self.drive_size = QLineEdit()
        self.drive_free = QLineEdit()
        self.drive_remote = QLineEdit()
        self.drive_status = QLineEdit()
        for widget in (
            self.drive_letter,
            self.drive_label,
            self.drive_type,
            self.drive_filesystem,
            self.drive_size,
            self.drive_free,
            self.drive_remote,
            self.drive_status,
        ):
            widget.setReadOnly(True)
        form.addRow("Letter", self.drive_letter)
        form.addRow("Label", self.drive_label)
        form.addRow("Type", self.drive_type)
        form.addRow("Filesystem", self.drive_filesystem)
        form.addRow("Size", self.drive_size)
        form.addRow("Free", self.drive_free)
        form.addRow("Remote path", self.drive_remote)
        form.addRow("Status", self.drive_status)

        buttons = QHBoxLayout()
        self.refresh_drives_button = QPushButton("Refresh")
        self.open_drive_button = QPushButton("Open")
        self.add_network_drive_button = QPushButton("Add network drive")
        buttons.addWidget(self.refresh_drives_button)
        buttons.addWidget(self.open_drive_button)
        buttons.addWidget(self.add_network_drive_button)
        detail_layout.addLayout(buttons)
        self.drive_status_label = QLabel("")
        self.drive_status_label.setWordWrap(True)
        detail_layout.addWidget(self.drive_status_label)
        detail_layout.addStretch(1)
        layout.addWidget(detail_group, 2)

        for list_widget in self._drive_lists():
            list_widget.currentRowChanged.connect(
                lambda _row, current=list_widget: self._select_drive_from(current)
            )
        self.exclude_local_drive_button.clicked.connect(
            lambda: self.hide_selected_drive(self.local_drive_included_list)
        )
        self.include_local_drive_button.clicked.connect(
            lambda: self.show_selected_drive(self.local_drive_excluded_list)
        )
        self.exclude_network_drive_button.clicked.connect(
            lambda: self.hide_selected_drive(self.network_drive_included_list)
        )
        self.include_network_drive_button.clicked.connect(
            lambda: self.show_selected_drive(self.network_drive_excluded_list)
        )
        self.refresh_drives_button.clicked.connect(self.refresh_drives_async)
        self.open_drive_button.clicked.connect(self.open_selected_drive)
        self.add_network_drive_button.clicked.connect(self.add_network_drive)

        self.drives_tab = tab
        self.host.main_tabs.addTab(tab, "Drives")
        self._populate_drive_detail(None)
    def refresh_drives_async(self, *, silent: bool = False) -> None:
        if self._drives_refreshing:
            return
        self._drives_refreshing = True
        if not silent:
            self.drive_status_label.setText("Loading drives...")

        def gather() -> list[DriveInfo]:
            return self._drive_service.list_drives()

        def on_success(drives: list[DriveInfo]) -> None:
            self._apply_drives(drives)

        def on_failure(message: str) -> None:
            self.drive_status_label.setText(message)
            self._apply_drives([])

        def cleanup() -> None:
            self._drives_refreshing = False

        self.host._run_in_thread(
            gather,
            on_success,
            on_failure=on_failure,
            cleanup=cleanup,
            busy=False,
        )

    def _apply_drives(self, drives: list[DriveInfo]) -> None:
        from PySide6.QtWidgets import QListWidgetItem

        current = _drive_key(self._selected_drive) if self._selected_drive else None
        self._drives = sorted(drives, key=lambda item: item.letter)
        self._drives_loaded = True
        visible_keys = self._visible_drive_keys()
        for list_widget in self._drive_lists():
            list_widget.clear()
        for drive in self._drives:
            included = _drive_key(drive) in visible_keys
            target = self._drive_list_for(drive, included=included)
            item = QListWidgetItem(_drive_list_label(drive))
            item.setData(self.host._qt.ItemDataRole.UserRole, _drive_key(drive))
            target.addItem(item)
        self.drive_status_label.setText("")
        self._select_drive_by_key(current)
        if self._selected_drive is None and self._drives:
            self._select_drive_by_key(_drive_key(self._drives[0]))

    def _visible_drive_keys(self) -> set[str]:
        try:
            options = config.get_tray_options()
        except config.ConfigError:
            options = config.default_tray_options()
        configured = options.get("visible_drive_ids")
        all_keys = {_drive_key(drive) for drive in self._drives}
        if configured is None:
            return all_keys
        configured_keys = {_normalize_drive_key(key) for key in configured}
        return configured_keys & all_keys

    def _drive_lists(self) -> tuple[Any, ...]:
        return (
            self.local_drive_included_list,
            self.local_drive_excluded_list,
            self.network_drive_included_list,
            self.network_drive_excluded_list,
        )

    def _drive_list_for(self, drive: DriveInfo, *, included: bool) -> Any:
        if _is_network_drive(drive):
            return (
                self.network_drive_included_list
                if included
                else self.network_drive_excluded_list
            )
        return self.local_drive_included_list if included else self.local_drive_excluded_list

    def _select_drive_from(self, list_widget: Any) -> None:
        item = list_widget.currentItem()
        if item is None:
            return
        for other in self._drive_lists():
            if other is list_widget:
                continue
            other.blockSignals(True)
            try:
                other.clearSelection()
                other.setCurrentRow(-1)
            finally:
                other.blockSignals(False)
        self._select_drive_by_key(str(item.data(self.host._qt.ItemDataRole.UserRole)))

    def _select_drive_by_key(self, key: str | None) -> None:
        drive = next((item for item in self._drives if _drive_key(item) == key), None)
        self._selected_drive = drive
        self._populate_drive_detail(drive)
        if drive is None:
            return
        included = _drive_key(drive) in self._visible_drive_keys()
        list_widget = self._drive_list_for(drive, included=included)
        for row in range(list_widget.count()):
            item = list_widget.item(row)
            if item.data(self.host._qt.ItemDataRole.UserRole) == _drive_key(drive):
                list_widget.setCurrentRow(row)
                return

    def hide_selected_drive(self, list_widget: Any) -> None:
        item = list_widget.currentItem()
        if item is None:
            return
        target_key = _normalize_drive_key(item.data(self.host._qt.ItemDataRole.UserRole))
        visible = [
            _drive_key(drive)
            for drive in self._drives
            if _drive_key(drive) in self._visible_drive_keys()
            and _drive_key(drive) != target_key
        ]
        self._save_visible_drive_keys(visible)

    def show_selected_drive(self, list_widget: Any) -> None:
        item = list_widget.currentItem()
        if item is None:
            return
        target_key = _normalize_drive_key(item.data(self.host._qt.ItemDataRole.UserRole))
        visible = [
            _drive_key(drive)
            for drive in self._drives
            if _drive_key(drive) in self._visible_drive_keys()
            or _drive_key(drive) == target_key
        ]
        self._save_visible_drive_keys(visible)

    def _save_visible_drive_keys(self, keys: list[str]) -> None:
        try:
            config.set_tray_options(visible_drive_ids=keys)
        except config.ConfigError as exc:
            self.host.show_error(str(exc))
            return
        self._apply_drives(self._drives)

    def _populate_drive_detail(self, drive: DriveInfo | None) -> None:
        enabled = drive is not None
        self.open_drive_button.setEnabled(enabled)
        if drive is None:
            for widget in (
                self.drive_letter,
                self.drive_label,
                self.drive_type,
                self.drive_filesystem,
                self.drive_size,
                self.drive_free,
                self.drive_remote,
                self.drive_status,
            ):
                widget.setText("")
            return
        self.drive_letter.setText(f"{drive.letter}:")
        self.drive_label.setText(drive.label or "")
        self.drive_type.setText(drive.drive_type)
        self.drive_filesystem.setText(drive.filesystem or "")
        self.drive_size.setText(_format_bytes(drive.size))
        self.drive_free.setText(_format_bytes(drive.free_space))
        self.drive_remote.setText(drive.remote_path or "")
        self.drive_status.setText(drive.status or "")

    def open_selected_drive(self) -> None:
        drive = self._selected_drive
        if drive is None:
            return
        try:
            self._drive_service.open_drive(drive)
        except Exception as exc:
            self.drive_status_label.setText(str(exc))

    def add_network_drive(self) -> None:
        dialog = NetworkDriveDialog(self.host.window)
        if not dialog.exec():
            return
        mapping = dialog.mapping()
        self.drive_status_label.setText("Mapping network drive...")

        def run() -> None:
            self._drive_service.map_network_drive(**mapping)

        def on_success(_result: None) -> None:
            self.drive_status_label.setText("Network drive mapped.")
            self.refresh_drives_async()

        def on_failure(message: str) -> None:
            self.drive_status_label.setText(message)
            self.refresh_drives_async()

        self.host._run_in_thread(run, on_success, on_failure=on_failure)

