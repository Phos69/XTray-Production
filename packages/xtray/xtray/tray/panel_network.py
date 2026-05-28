"""Network-device rendering helpers for :class:`TrayPanel`."""
from __future__ import annotations

from typing import Any

from xtray.core import app_logging, icons
from xtray.core.theme import ping_button_style

from ..services.network import devices as network
from .chrome import _clear_layout


def show_network_loading(panel: Any) -> None:
    from PySide6.QtCore import Qt  # type: ignore[import-not-found]
    from PySide6.QtWidgets import QLabel  # type: ignore[import-not-found]

    panel.network_ping_buttons = {}
    _set_network_kind_tab_visibility(panel, set(panel._network_kind_layouts))
    for kind, layout in panel._network_kind_layouts.items():
        _clear_layout(layout)
        empty = QLabel("Loading network devices...")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(empty)
        panel._network_kind_empty_labels[kind] = empty
    set_network_status(panel, "")


def refresh_network_devices(panel: Any) -> None:
    try:
        devices = network.list_devices()
    except Exception as exc:
        app_logging.get_logger("tray").exception("failed to refresh network devices")
        apply_network_devices(panel, [], error=str(exc))
        return
    apply_network_devices(panel, devices)


def apply_network_devices(
    panel: Any,
    devices: list[network.NetworkDevice],
    *,
    error: str | None = None,
) -> None:
    from PySide6.QtCore import QSize, Qt  # type: ignore[import-not-found]
    from PySide6.QtWidgets import (  # type: ignore[import-not-found]
        QFrame,
        QHBoxLayout,
        QLabel,
        QPushButton,
    )

    panel.network_ping_buttons = {}
    for layout in panel._network_kind_layouts.values():
        _clear_layout(layout)
    for kind in panel._network_kind_empty_labels:
        panel._network_kind_empty_labels[kind] = None

    visible_devices = [device for device in devices if not getattr(device, "offline", False)]
    by_kind: dict[str, list[network.NetworkDevice]] = {
        kind: [] for kind in panel._network_kind_layouts
    }
    for device in visible_devices:
        bucket = network.normalize_kind(getattr(device, "kind", None))
        by_kind.setdefault(bucket, []).append(device)
    populated_kinds = {
        kind
        for kind, kind_devices in by_kind.items()
        if kind in panel._network_kind_layouts and kind_devices
    }
    _set_network_kind_tab_visibility(panel, populated_kinds)

    text_color = panel._theme.tray.text
    icon_size = QSize(24, 24)

    for kind, layout in panel._network_kind_layouts.items():
        kind_devices = by_kind.get(kind, [])
        if not kind_devices:
            placeholder = QLabel("Network devices unavailable" if error else "No devices")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(placeholder)
            panel._network_kind_empty_labels[kind] = placeholder
            continue
        for device in kind_devices:
            row = QFrame()
            row.setObjectName("trayListRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            if device.icon:
                icon_label = QLabel()
                icon_pixmap = icons.qicon_for(device.icon, color=text_color, size=48).pixmap(
                    icon_size
                )
                icon_label.setPixmap(icon_pixmap)
                icon_label.setFixedWidth(28)
                row_layout.addWidget(icon_label)
            label = QLabel(f"{device.name}\n{device.ip}")
            label.setObjectName("trayPanelSection")
            row_layout.addWidget(label, 1)
            ping_button = QPushButton(panel._fallback_label("network.device.ping"))
            ping_button.setObjectName("trayNetworkPingButton")
            ping_button.setStyleSheet(ping_button_style(panel._theme, "idle"))
            panel._apply_action_button_icon(
                ping_button,
                "network.device.ping",
                color=panel._theme.tray.ping_idle_text,
            )
            ping_button.clicked.connect(
                lambda _checked=False, current=device: panel.controller.ping_network_device(current)
            )
            row_layout.addWidget(ping_button)
            open_button = QPushButton(panel._fallback_label("network.device.open"))
            open_button.setObjectName("trayNetworkOpenButton")
            open_button.setProperty("surfaceAction", "window")
            panel._apply_action_button_icon(
                open_button,
                "network.device.open",
            )
            open_button.clicked.connect(
                lambda _checked=False, current=device: panel.controller.open_network_device(
                    current
                )
            )
            row_layout.addWidget(open_button)
            panel.network_ping_buttons[device.id] = ping_button
            layout.addWidget(row)

    if not visible_devices:
        if devices and not error:
            set_network_status(panel, "All devices are marked offline.")
            return
        set_network_status(panel, error or "Add devices in Network Manager.")
    else:
        set_network_status(panel, "")


def _set_network_kind_tab_visibility(panel: Any, visible_kinds: set[str]) -> None:
    kinds = list(panel._network_kind_layouts)
    if not kinds:
        return
    displayed_kinds = [kind for kind in kinds if kind in visible_kinds]
    if not displayed_kinds:
        displayed_kinds = [kinds[0]]
    for index, kind in enumerate(kinds):
        panel.network_kind_tabs.setTabVisible(index, kind in displayed_kinds)
    current_kind = (
        kinds[panel.network_kind_tabs.currentIndex()]
        if 0 <= panel.network_kind_tabs.currentIndex() < len(kinds)
        else None
    )
    if current_kind not in displayed_kinds:
        panel.network_kind_tabs.setCurrentIndex(kinds.index(displayed_kinds[0]))
    panel.network_kind_tabs.tabBar().setVisible(len(visible_kinds) > 1)


def update_network_status(panel: Any, status: network.NetworkStatus) -> None:
    button = panel.network_ping_buttons.get(status.device.id)
    text = "Online" if status.online else "Offline"
    if status.online and status.latency_ms is not None:
        text = f"Online ({status.latency_ms} ms)"
    if button is not None:
        set_ping_button_state(panel, button, "success" if status.online else "failure")
    set_network_status(panel, f"{status.device.name}: {text}")


def set_ping_button_state(panel: Any, button: Any, state: str) -> None:
    from PySide6.QtCore import QTimer  # type: ignore[import-not-found]

    button.setStyleSheet(ping_button_style(panel._theme, state))
    timer = getattr(button, "_ping_reset_timer", None)
    if timer is None:
        timer = QTimer(button)
        timer.setSingleShot(True)
        timer.timeout.connect(
            lambda b=button: b.setStyleSheet(ping_button_style(panel._theme, "idle"))
        )
        button._ping_reset_timer = timer
    timer.start(60_000)


def set_network_status(panel: Any, message: str) -> None:
    panel.network_status.setText(message)
