"""PySide6 widgets for saved PC-side network devices."""
from __future__ import annotations

import sys
import webbrowser
from collections.abc import Callable, Iterable
from typing import Any

from xtray.core.gui import install_combobox_wheel_guard, set_button_role
from xtray.core.icons import IconPickerButton, qicon_for
from xtray.core.theme import DEFAULT_THEME, build_app_stylesheet, theme_by_name

from . import actions as device_actions
from . import scanner, storage
from ._async_runner import AsyncRunner
from ._dhcp_status import DhcpStatusComputer, _mac_key
from .models import (
    DEFAULT_DEVICE_KIND,
    DEFAULT_DHCP_STATUS,
    DEFAULT_SWITCH_MODEL,
    DEVICE_KIND_IOT,
    DEVICE_KIND_MEDIA,
    DEVICE_KIND_NETWORK,
    DEVICE_KIND_PERSONAL,
    DEVICE_KINDS,
    DHCP_STATUS_DYNAMIC,
    DHCP_STATUS_RESERVED,
    DHCP_STATUS_STATIC,
    DHCP_STATUSES,
    DiscoveredDevice,
    NetworkAdapter,
    NetworkDevice,
    normalize_kind,
    normalize_switch_model,
)
from .switch_models import SWITCH_MODELS

_DEVICE_KIND_LABELS: dict[str, str] = {
    DEVICE_KIND_NETWORK: "Network",
    DEVICE_KIND_IOT: "IoT",
    DEVICE_KIND_MEDIA: "Media",
    DEVICE_KIND_PERSONAL: "Personal devices",
}

_DEVICE_KIND_ICONS: dict[str, str] = {
    DEVICE_KIND_NETWORK: "mdi:router-network",
    DEVICE_KIND_IOT: "mdi:lightbulb-on",
    DEVICE_KIND_MEDIA: "mdi:television",
    DEVICE_KIND_PERSONAL: "mdi:cellphone",
}

_DHCP_STATUS_LABELS: dict[str, str] = {
    DHCP_STATUS_STATIC: "Static",
    DHCP_STATUS_DYNAMIC: "DHCP Dynamic",
    DHCP_STATUS_RESERVED: "DHCP Reserved",
}

_SWITCH_MODEL_UNSUPPORTED_LABEL = "Unsupported"


def _install_xtray_window_icon(*, app=None, window=None) -> None:
    try:
        from xtray.core import qt_assets
    except Exception:
        return
    try:
        if app is not None:
            qt_assets.set_application_window_icon(app)
        if window is not None:
            qt_assets.set_window_icon(window)
    except Exception:
        return


def _current_theme():
    try:
        from xtray import config as xtray_config

        return theme_by_name(xtray_config.get_theme_name())
    except Exception:
        return DEFAULT_THEME


def _apply_shared_theme(widget) -> None:
    install_combobox_wheel_guard()
    widget.setStyleSheet(build_app_stylesheet(_current_theme()))


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise SystemExit("PySide6 is not installed. Install with: pip install -e .") from exc

    app = QApplication.instance() or QApplication(sys.argv)
    install_combobox_wheel_guard(app)
    _install_xtray_window_icon(app=app)
    window = DeviceManagerWindow()
    window.resize(860, 560)
    window.show()
    return app.exec()


class DeviceManagerWindow:  # pragma: no cover - requires PySide6
    def __init__(self) -> None:
        from PySide6.QtWidgets import QMainWindow

        self.window = QMainWindow()
        self.window.setWindowTitle("Network Manager - Device")
        _install_xtray_window_icon(window=self.window)
        _apply_shared_theme(self.window)
        self.widget = DeviceManagerWidget()
        self.window.setCentralWidget(self.widget.widget)

    def __getattr__(self, name: str):
        try:
            return getattr(self.widget, name)
        except AttributeError:
            return getattr(self.window, name)


class DeviceManagerWidget:  # pragma: no cover - requires PySide6
    def __init__(self, parent=None) -> None:
        from PySide6.QtCore import QSize, Qt
        from PySide6.QtWidgets import (
            QAbstractItemView,
            QCheckBox,
            QComboBox,
            QFormLayout,
            QFrame,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QMessageBox,
            QPushButton,
            QSplitter,
            QTabWidget,
            QVBoxLayout,
            QWidget,
        )

        self._qt = Qt
        self._message_box = QMessageBox
        self._devices: list[NetworkDevice] = []
        self._adapters: list[NetworkAdapter] = []
        self._scan_results: list[DiscoveredDevice] = []
        self._selected_device_id: str | None = None
        self._async = AsyncRunner(on_busy=lambda msg: self.status.setText(msg))
        self._dhcp = DhcpStatusComputer()
        self._device_lists: dict[str, Any] = {}
        self._populating_device_lists = False
        self.on_devices_changed: Callable[[], None] | None = None

        self.widget = QWidget(parent)
        _apply_shared_theme(self.widget)
        self.widget.destroyed.connect(self._cancel_async)
        root_layout = QVBoxLayout(self.widget)
        root_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter()
        splitter.setOrientation(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        sort_actions = QHBoxLayout()
        self.sort_name_button = QPushButton("Nome A-Z")
        self.sort_ip_button = QPushButton("IP crescente")
        sort_actions.addWidget(self.sort_name_button)
        sort_actions.addWidget(self.sort_ip_button)
        left_layout.addLayout(sort_actions)

        self.device_tabs = QTabWidget()
        self.device_tabs.setIconSize(QSize(20, 20))
        for kind in DEVICE_KINDS:
            list_widget = QListWidget()
            list_widget.setDragEnabled(True)
            list_widget.setAcceptDrops(True)
            list_widget.setDropIndicatorShown(True)
            list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            list_widget.setDefaultDropAction(Qt.DropAction.MoveAction)
            list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            list_widget.currentRowChanged.connect(
                lambda row, device_kind=kind, device_list=list_widget: self.on_device_selected(
                    row,
                    kind=device_kind,
                    list_widget=device_list,
                )
            )
            list_widget.model().rowsMoved.connect(
                lambda *_args, device_kind=kind: self._persist_kind_order_from_list(
                    device_kind
                )
            )
            self._device_lists[kind] = list_widget
            index = self.device_tabs.addTab(
                list_widget,
                qicon_for(_DEVICE_KIND_ICONS[kind], size=48),
                "",
            )
            self.device_tabs.setTabToolTip(index, _DEVICE_KIND_LABELS[kind])
        self.device_list = self._device_lists[DEFAULT_DEVICE_KIND]
        self.device_tabs.currentChanged.connect(self.on_device_tab_changed)
        left_layout.addWidget(self.device_tabs, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        splitter.addWidget(right)

        form = QFormLayout()
        self.name_input = QLineEdit()
        self.ip_input = QLineEdit()
        self.mac_input = QLineEdit()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("http://192.168.1.10")
        self.icon_picker = IconPickerButton()
        self.offline_check = QCheckBox("Offline")
        self.offline_check.setToolTip(
            "Esclude il device dal tray e dalla Network Map, ma lo mantiene nella tab Device."
        )
        self.kind_combo = QComboBox()
        for kind in DEVICE_KINDS:
            self.kind_combo.addItem(_DEVICE_KIND_LABELS[kind], kind)
        self.kind_combo.setToolTip(
            "Tipologia del device. Determina il sotto-tab nel tray (Network, IoT, Media)."
        )
        self.switch_model_label = QLabel("Modello switch")
        self.switch_model_combo = QComboBox()
        self.switch_model_combo.addItem(_SWITCH_MODEL_UNSUPPORTED_LABEL, DEFAULT_SWITCH_MODEL)
        for key, model in SWITCH_MODELS.items():
            self.switch_model_combo.addItem(model.label, key)
        self.switch_model_combo.setToolTip(
            "Modello switch usato dalle build private complete, oppure Unsupported."
        )
        self.dhcp_status_combo = QComboBox()
        for status in DHCP_STATUSES:
            self.dhcp_status_combo.addItem(_DHCP_STATUS_LABELS[status], status)
        self.dhcp_status_combo.setEnabled(False)
        self.dhcp_status_combo.setToolTip(
            "Determinato dal router: Reserved se il MAC ha una prenotazione, "
            "Dynamic se ha un lease attivo, altrimenti Static."
        )
        form.addRow("Nome", self.name_input)
        form.addRow("IP", self.ip_input)
        form.addRow("MAC", self.mac_input)
        form.addRow("URL", self.url_input)
        form.addRow("Icona", self.icon_picker.widget)
        form.addRow("Tipologia", self.kind_combo)
        form.addRow("Stato", self.offline_check)
        form.addRow(self.switch_model_label, self.switch_model_combo)
        form.addRow("DHCP", self.dhcp_status_combo)
        right_layout.addLayout(form)

        actions = QHBoxLayout()
        self.new_button = QPushButton("Nuovo")
        self.save_button = QPushButton("Salva")
        self.delete_button = QPushButton("Elimina")
        self.ping_button = QPushButton("Ping")
        self.open_button = QPushButton("Apri")
        set_button_role(self.save_button, "primary")
        for button in (
            self.new_button,
            self.save_button,
            self.delete_button,
            self.ping_button,
            self.open_button,
        ):
            actions.addWidget(button)
        right_layout.addLayout(actions)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        right_layout.addWidget(self.status)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        right_layout.addWidget(separator)

        scan_title = QLabel("Scansione rete")
        right_layout.addWidget(scan_title)

        scan_actions = QHBoxLayout()
        self.adapter_combo = QComboBox()
        scan_actions.addWidget(self.adapter_combo, 1)
        self.refresh_adapters_button = QPushButton("Adapter")
        self.scan_button = QPushButton("Scan")
        scan_actions.addWidget(self.refresh_adapters_button)
        scan_actions.addWidget(self.scan_button)
        right_layout.addLayout(scan_actions)

        self.scan_results = QListWidget()
        self.scan_results.currentRowChanged.connect(self.on_scan_result_selected)
        right_layout.addWidget(self.scan_results, 1)
        self.add_scan_result_button = QPushButton("Crea o aggiorna dal risultato")
        right_layout.addWidget(self.add_scan_result_button)

        self.new_button.clicked.connect(self.new_device)
        self.save_button.clicked.connect(self.save_current)
        self.delete_button.clicked.connect(self.delete_current)
        self.ping_button.clicked.connect(self.ping_current_async)
        self.open_button.clicked.connect(self.open_current)
        self.refresh_adapters_button.clicked.connect(self.refresh_adapters_async)
        self.scan_button.clicked.connect(self.scan_network_async)
        self.add_scan_result_button.clicked.connect(self.create_or_update_from_scan)
        self.sort_name_button.clicked.connect(lambda: self.sort_current_kind_by("name"))
        self.sort_ip_button.clicked.connect(lambda: self.sort_current_kind_by("ip"))
        self.kind_combo.currentIndexChanged.connect(self._update_switch_model_visibility)

        splitter.setSizes([260, 600])
        self.refresh_devices()
        self._show_adapters_loading()
        from PySide6.QtCore import QTimer

        self._adapter_refresh_timer = QTimer(self.widget)
        self._adapter_refresh_timer.setSingleShot(True)
        self._adapter_refresh_timer.timeout.connect(self.refresh_adapters_async)
        self._adapter_refresh_timer.start(0)

    def __getattr__(self, name: str):
        return getattr(self.widget, name)

    def _current_device_kind(self) -> str:
        index = self.device_tabs.currentIndex()
        if 0 <= index < len(DEVICE_KINDS):
            return DEVICE_KINDS[index]
        return DEFAULT_DEVICE_KIND

    def _set_current_device_kind(self, kind: str | None) -> None:
        target = normalize_kind(kind)
        try:
            index = DEVICE_KINDS.index(target)
        except ValueError:
            index = DEVICE_KINDS.index(DEFAULT_DEVICE_KIND)
        self.device_tabs.setCurrentIndex(index)

    def _current_device_list(self) -> Any:
        return self._device_lists[self._current_device_kind()]

    def _device_item_label(self, device: NetworkDevice) -> str:
        reserved = _mac_key(device.mac) in self._dhcp.reserved_mac_keys
        marker = "  DHCP" if reserved else ""
        return f"{device.name}{marker}\n{device.ip}"

    def _populate_device_lists(self, selected_id: str | None) -> None:
        from PySide6.QtWidgets import QListWidgetItem

        self._populating_device_lists = True
        locations: dict[str, tuple[str, int]] = {}
        try:
            for kind, list_widget in self._device_lists.items():
                was_blocked = list_widget.blockSignals(True)
                try:
                    list_widget.clear()
                    for device in self._devices:
                        if normalize_kind(device.kind) != kind:
                            continue
                        item = QListWidgetItem(self._device_item_label(device))
                        item.setData(self._qt.ItemDataRole.UserRole, device.id)
                        list_widget.addItem(item)
                        locations[device.id] = (kind, list_widget.count() - 1)
                finally:
                    list_widget.blockSignals(was_blocked)

            target_id = selected_id if selected_id in locations else None
            if target_id is None and self._devices:
                target_id = self._devices[0].id
            if target_id is not None and target_id in locations:
                kind, row = locations[target_id]
                tabs_blocked = self.device_tabs.blockSignals(True)
                try:
                    self._set_current_device_kind(kind)
                finally:
                    self.device_tabs.blockSignals(tabs_blocked)
                list_widget = self._device_lists[kind]
                was_blocked = list_widget.blockSignals(True)
                try:
                    list_widget.setCurrentRow(row)
                finally:
                    list_widget.blockSignals(was_blocked)
        finally:
            self._populating_device_lists = False

        if target_id is not None and target_id in locations:
            kind, row = locations[target_id]
            self.on_device_selected(row, kind=kind, list_widget=self._device_lists[kind])
        else:
            self.new_device()

    def _clear_device_selection(self) -> None:
        for list_widget in self._device_lists.values():
            was_blocked = list_widget.blockSignals(True)
            try:
                list_widget.clearSelection()
                list_widget.setCurrentRow(-1)
            finally:
                list_widget.blockSignals(was_blocked)

    def _clear_other_device_selections(self, selected_list: Any) -> None:
        for list_widget in self._device_lists.values():
            if list_widget is selected_list:
                continue
            was_blocked = list_widget.blockSignals(True)
            try:
                list_widget.clearSelection()
            finally:
                list_widget.blockSignals(was_blocked)

    def _device_ids_from_list(self, kind: str) -> list[str]:
        list_widget = self._device_lists[normalize_kind(kind)]
        ids: list[str] = []
        for row in range(list_widget.count()):
            item = list_widget.item(row)
            if item is None:
                continue
            ids.append(str(item.data(self._qt.ItemDataRole.UserRole)))
        return ids

    def _persist_kind_order_from_list(self, kind: str) -> None:
        if self._populating_device_lists:
            return
        target = normalize_kind(kind)
        try:
            self._devices = storage.reorder_devices_for_kind(
                target,
                self._device_ids_from_list(target),
            )
        except Exception as exc:
            self.show_error(str(exc))
            self.refresh_devices()
            return
        self.status.setText(f"Ordine {_DEVICE_KIND_LABELS[target]} salvato.")
        self._emit_devices_changed()

    def _emit_devices_changed(self) -> None:
        if self.on_devices_changed is not None:
            self.on_devices_changed()

    def on_device_tab_changed(self, _index: int) -> None:
        if self._populating_device_lists:
            return
        list_widget = self._current_device_list()
        row = list_widget.currentRow()
        if row >= 0:
            self.on_device_selected(
                row,
                kind=self._current_device_kind(),
                list_widget=list_widget,
            )
            return
        if list_widget.count():
            list_widget.setCurrentRow(0)
            return
        self.new_device()

    def sort_current_kind_by(self, key: str) -> None:
        kind = self._current_device_kind()
        selected_id = self._selected_device_id
        try:
            self._devices = storage.sort_devices_for_kind(kind, key)
        except Exception as exc:
            self.show_error(str(exc))
            return
        self._populate_device_lists(selected_id)
        label = "nome" if key == "name" else "IP"
        self.status.setText(f"Ordinato {_DEVICE_KIND_LABELS[kind]} per {label}.")
        self._emit_devices_changed()

    def refresh_devices(self) -> None:
        current_id = self._selected_device_id
        try:
            self._devices = storage.list_devices()
        except Exception as exc:
            self.show_error(str(exc))
            self._devices = []
        self._populate_device_lists(current_id)
        self._emit_devices_changed()

    def new_device(self) -> None:
        self._selected_device_id = None
        self._clear_device_selection()
        self.name_input.clear()
        self.ip_input.clear()
        self.mac_input.clear()
        self.url_input.clear()
        self.icon_picker.set_value(None)
        self.offline_check.setChecked(False)
        self._set_kind_combo(self._current_device_kind())
        self._set_switch_model_combo(DEFAULT_SWITCH_MODEL)
        self._update_switch_model_visibility()
        self._refresh_dhcp_status_combo()
        self.status.clear()

    def _compute_dhcp_status(
        self,
        mac: str | None,
        ip: str | None,
        *,
        fallback: str = DEFAULT_DHCP_STATUS,
    ) -> str:
        return self._dhcp.compute(mac, ip, fallback=fallback)

    def _set_dhcp_status_combo(self, status: str) -> None:
        for index in range(self.dhcp_status_combo.count()):
            if self.dhcp_status_combo.itemData(index) == status:
                self.dhcp_status_combo.setCurrentIndex(index)
                return
        self.dhcp_status_combo.setCurrentIndex(0)

    def _refresh_dhcp_status_combo(self) -> None:
        mac = self.mac_input.text().strip() or None
        ip = self.ip_input.text().strip() or None
        current = self.current_device()
        fallback = current.dhcp_status if current is not None else DEFAULT_DHCP_STATUS
        self._set_dhcp_status_combo(
            self._compute_dhcp_status(mac, ip, fallback=fallback)
        )

    def _maybe_persist_dhcp_status(self) -> None:
        """Recompute and persist dhcp_status for every device once both router
        data sources are loaded. No-op while disconnected."""
        updated_list, changed = self._dhcp.recompute_devices(self._devices)
        if not changed:
            return
        try:
            storage.save_devices(updated_list)
        except Exception:  # pragma: no cover - best-effort persistence
            return
        self._devices = updated_list

    def _set_kind_combo(self, kind: str | None) -> None:
        target = normalize_kind(kind)
        for index in range(self.kind_combo.count()):
            if self.kind_combo.itemData(index) == target:
                self.kind_combo.setCurrentIndex(index)
                self._update_switch_model_visibility()
                return
        self.kind_combo.setCurrentIndex(0)
        self._update_switch_model_visibility()

    def _current_kind(self) -> str:
        return normalize_kind(self.kind_combo.currentData())

    def _set_switch_model_combo(self, switch_model: str | None) -> None:
        target = normalize_switch_model(switch_model)
        for index in range(self.switch_model_combo.count()):
            if self.switch_model_combo.itemData(index) == target:
                self.switch_model_combo.setCurrentIndex(index)
                return
        self.switch_model_combo.setCurrentIndex(0)

    def _current_switch_model(self) -> str:
        if self._current_kind() != DEVICE_KIND_NETWORK:
            return DEFAULT_SWITCH_MODEL
        return normalize_switch_model(self.switch_model_combo.currentData())

    def _update_switch_model_visibility(self, *_args: Any) -> None:
        is_network = self._current_kind() == DEVICE_KIND_NETWORK
        self.switch_model_label.setVisible(is_network)
        self.switch_model_combo.setVisible(is_network)
        self.switch_model_combo.setEnabled(is_network)
        if not is_network:
            self._set_switch_model_combo(DEFAULT_SWITCH_MODEL)

    def save_current(self) -> None:
        try:
            existing = self.current_device()
            device = self._device_from_form()
            devices = storage.upsert_device(device)
            if existing is not None and normalize_kind(existing.kind) != device.kind:
                kind_ids = [
                    item.id
                    for item in devices
                    if normalize_kind(item.kind) == device.kind and item.id != device.id
                ]
                kind_ids.append(device.id)
                devices = storage.reorder_devices_for_kind(device.kind, kind_ids)
        except Exception as exc:
            self.show_error(str(exc))
            return
        self._devices = devices
        self._selected_device_id = device.id
        self.status.setText(f"Salvato {device.name}.")
        self.refresh_devices()

    def delete_current(self) -> None:
        device = self.current_device()
        if device is None:
            return
        storage.delete_device(device.id)
        self._selected_device_id = None
        self.status.setText(f"Eliminato {device.name}.")
        self.refresh_devices()

    def ping_current(self) -> None:
        device = self._device_from_form()
        status = scanner.ping_device(device)
        label = "online" if status.online else "offline"
        suffix = f" ({status.latency_ms} ms)" if status.latency_ms is not None else ""
        self.status.setText(f"{device.name} e' {label}{suffix}.")

    def ping_current_async(self) -> None:
        device = self._device_from_form()
        self.status.setText(f"Ping {device.name}...")

        def done(result: Any, err: str | None) -> None:
            if err:
                self.status.setText(err)
                return
            status = result
            label = "online" if status.online else "offline"
            suffix = f" ({status.latency_ms} ms)" if status.latency_ms is not None else ""
            self.status.setText(f"{device.name} e' {label}{suffix}.")

        self._run_async(
            lambda: scanner.ping_device(device),
            done,
            disable=[self.ping_button],
        )

    def open_current(self) -> None:
        device = self._device_from_form()
        webbrowser.open(device.web_url())

    def refresh_adapters(self) -> None:
        self._apply_adapters(scanner.list_adapters())

    def refresh_adapters_async(self) -> None:
        self._show_adapters_loading()

        def done(result: Any, err: str | None) -> None:
            if err:
                self._apply_adapters([])
                self.status.setText(f"Lettura adapter fallita: {err}")
                return
            self._apply_adapters(result)
            self.status.setText(f"{len(result)} adapter IPv4 trovati.")

        self._run_async(
            scanner.list_adapters,
            done,
            disable=[self.refresh_adapters_button, self.scan_button],
        )

    def scan_network(self) -> None:
        adapter = self.adapter_combo.currentData()
        if adapter is None and not self._adapters:
            self.refresh_adapters()
            adapter = self.adapter_combo.currentData()
        if adapter is None:
            self.status.setText("Nessun adapter selezionato.")
            return
        self.status.setText(f"Scansione {adapter.label()}...")
        self._scan_results = scanner.scan_adapter(adapter)
        self._apply_scan_results(self._scan_results)
        self.status.setText(f"Trovati {len(self._scan_results)} device online.")

    def scan_network_async(self) -> None:
        adapter = self.adapter_combo.currentData()
        if adapter is None:
            self.status.setText("Nessun adapter selezionato.")
            return
        self.status.setText(f"Scansione {adapter.label()}...")
        self.scan_results.clear()

        def done(result: Any, err: str | None) -> None:
            if err:
                self.status.setText(f"Scansione fallita: {err}")
                return
            self._scan_results = list(result)
            self._apply_scan_results(self._scan_results)
            self.status.setText(f"Trovati {len(self._scan_results)} device online.")

        self._run_async(
            lambda: scanner.scan_adapter(adapter),
            done,
            disable=[self.scan_button, self.refresh_adapters_button, self.add_scan_result_button],
        )

    def _show_adapters_loading(self) -> None:
        self.adapter_combo.clear()
        self.adapter_combo.addItem("Caricamento adapter...", None)
        self.scan_button.setEnabled(False)

    def _apply_adapters(self, adapters: list[NetworkAdapter]) -> None:
        self.adapter_combo.clear()
        self._adapters = adapters
        for adapter in self._adapters:
            self.adapter_combo.addItem(adapter.label(), adapter)
        if not self._adapters:
            self.adapter_combo.addItem("Nessun adapter IPv4 trovato", None)
        self.scan_button.setEnabled(bool(self._adapters))

    def _apply_scan_results(self, results: list[DiscoveredDevice]) -> None:
        self.scan_results.clear()
        for item in results:
            mac = f"  {item.mac}" if item.mac else ""
            self.scan_results.addItem(f"{item.ip}{mac}")

    def _run_async(
        self,
        fn: Callable[[], Any],
        on_done: Callable[[Any, str | None], None],
        *,
        disable: list[Any] | None = None,
    ) -> None:
        self._async.run(fn, on_done, disable=disable)

    def _cancel_async(self, *_args: Any) -> None:
        timer = getattr(self, "_adapter_refresh_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass
        self._async.cancel()

    def create_or_update_from_scan(self) -> None:
        result = self.current_scan_result()
        if result is None:
            return
        device_actions.create_or_update_from_scan(self, result)

    def set_reserved_macs(self, macs: Iterable[str], *, loaded: bool = True) -> None:
        """Set the set of MACs that have a DHCP static reservation.

        `loaded=False` indicates we have no fresh router data (e.g. after
        disconnect): the in-memory set is cleared but the persisted
        dhcp_status on each device is preserved.
        """
        self._dhcp.set_reserved_macs(macs, loaded=loaded)
        current_id = self._selected_device_id
        self._maybe_persist_dhcp_status()
        self._populate_device_lists(current_id)
        self._refresh_dhcp_status_combo()

    def set_active_leases(self, leases: Iterable[Any], *, loaded: bool = True) -> None:
        """Set the active DHCP leases (each item exposes .mac and .ip).

        `loaded=False` indicates no fresh router data.
        """
        self._dhcp.set_active_leases(leases, loaded=loaded)
        self._maybe_persist_dhcp_status()
        self._refresh_dhcp_status_combo()

    def current_devices(self) -> list[NetworkDevice]:
        return list(self._devices)

    def save_device(self, *, name: str, ip: str, mac: str | None = None) -> NetworkDevice:
        return device_actions.save_device(self, name=name, ip=ip, mac=mac)

    def update_device_network_settings(
        self,
        device_id: str,
        *,
        ip: str | None = None,
        switch_model: str | None = None,
    ) -> NetworkDevice | None:
        return device_actions.update_device_network_settings(
            self, device_id, ip=ip, switch_model=switch_model
        )

    def on_device_selected(
        self,
        row: int,
        *,
        kind: str | None = None,
        list_widget: Any | None = None,
    ) -> None:
        if self._populating_device_lists or row < 0:
            return
        if list_widget is None:
            list_widget = (
                self._device_lists.get(normalize_kind(kind))
                if kind is not None
                else self._current_device_list()
            )
        if list_widget is None or row >= list_widget.count():
            return
        item = list_widget.item(row)
        if item is None:
            return
        device_id = str(item.data(self._qt.ItemDataRole.UserRole))
        device = self._find_device_by_id(device_id)
        if device is None:
            return
        self._clear_other_device_selections(list_widget)
        self._selected_device_id = device.id
        self.name_input.setText(device.name)
        self.ip_input.setText(device.ip)
        self.mac_input.setText(device.mac or "")
        self.url_input.setText(device.url or "")
        self.icon_picker.set_value(device.icon)
        self.offline_check.setChecked(device.offline)
        self._set_kind_combo(device.kind)
        self._set_switch_model_combo(device.switch_model)
        self._update_switch_model_visibility()
        self._refresh_dhcp_status_combo()

    def on_scan_result_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._scan_results):
            return
        result = self._scan_results[row]
        self.ip_input.setText(result.ip)
        if result.mac:
            self.mac_input.setText(result.mac)
        if not self.name_input.text().strip():
            self.name_input.setText(result.name or f"Device {result.ip}")
        self._refresh_dhcp_status_combo()

    def _find_device_by_id(self, device_id: str) -> NetworkDevice | None:
        return device_actions.find_device_by_id(self, device_id)

    def current_device(self) -> NetworkDevice | None:
        if self._selected_device_id is None:
            return None
        return self._find_device_by_id(self._selected_device_id)

    def current_scan_result(self) -> DiscoveredDevice | None:
        row = self.scan_results.currentRow()
        if row < 0 or row >= len(self._scan_results):
            return None
        return self._scan_results[row]

    def show_error(self, message: str) -> None:
        self.status.setText(message)
        self._message_box.critical(self.widget, "Network Manager", message)

    def _device_from_form(self) -> NetworkDevice:
        return NetworkDevice.create(
            id=self._selected_device_id,
            name=self.name_input.text(),
            ip=self.ip_input.text(),
            mac=self.mac_input.text() or None,
            url=self.url_input.text() or None,
            icon=self.icon_picker.value(),
            kind=self._current_kind(),
            switch_model=self._current_switch_model(),
            dhcp_status=self.dhcp_status_combo.currentData(),
            offline=self.offline_check.isChecked(),
        )

    def _find_device_for_scan_result(self, result: DiscoveredDevice) -> NetworkDevice | None:
        return device_actions.find_device_for_scan_result(self, result)

    def _find_device_for_ip_or_mac(self, ip: str, mac: str | None) -> NetworkDevice | None:
        return device_actions.find_device_for_ip_or_mac(self, ip, mac)
