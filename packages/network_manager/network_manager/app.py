"""Public PySide6 entry point for Network Manager.

The production app intentionally exposes only the saved-device manager. The
full router/switch UI remains available in private development builds when
``experimental_features.network_manager_full`` is enabled locally.
"""
from __future__ import annotations

import logging
import sys
from importlib import import_module
from typing import Any

from PySide6.QtWidgets import QApplication, QMainWindow, QStatusBar, QVBoxLayout, QWidget
from xtray.core.gui import install_combobox_wheel_guard
from xtray.core.theme import build_app_stylesheet

from .device_manager.manager import (
    DeviceManagerWidget,
    _current_theme,
    _install_xtray_window_icon,
)

log = logging.getLogger("network_manager.gui")

__all__ = ["DeviceMainWindow", "MainWindow", "main"]


def _full_network_manager_enabled() -> bool:
    try:
        from xtray import config as xtray_config

        return xtray_config.experimental_feature_enabled("network_manager_full")
    except Exception:
        return False


def _experimental_main_window_class() -> type[Any] | None:
    try:
        module = import_module(f"{__package__}.{'experimental_app'}")
    except ImportError:
        log.warning("full Network Manager requested but experimental modules are unavailable")
        return None
    return module.MainWindow


class DeviceMainWindow(QMainWindow):
    """Production-safe Network Manager window containing only the Device tab."""

    def __init__(self) -> None:
        super().__init__()
        install_combobox_wheel_guard()
        _install_xtray_window_icon(window=self)
        self.setWindowTitle("Network Manager")
        self.resize(900, 680)
        self._theme = _current_theme()
        self.setStyleSheet(build_app_stylesheet(self._theme))
        self._build_ui()
        self.statusBar().showMessage("Pronto.")

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        self.setStatusBar(QStatusBar())

        self.device_page = DeviceManagerWidget()
        layout.addWidget(self.device_page.widget, 1)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt signature)
        self.device_page._cancel_async()
        super().closeEvent(event)


def MainWindow() -> Any:  # noqa: N802 - public compatibility constructor
    if _full_network_manager_enabled():
        experimental_cls = _experimental_main_window_class()
        if experimental_cls is not None:
            return experimental_cls()
    return DeviceMainWindow()


def __getattr__(name: str) -> Any:
    if name == "WifiDeviceSnapshot":
        module = import_module(f"{__package__}.{'experimental_app'}")
        return module.WifiDeviceSnapshot
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main() -> int:
    from xtray.core import app_logging
    from xtray.core.gui import install_qt_message_handler

    app_logging.configure_logging(component="network_manager")
    install_qt_message_handler()
    app = QApplication(sys.argv)
    app.aboutToQuit.connect(lambda: app_logging.mark_clean_shutdown("network_manager"))
    install_combobox_wheel_guard(app)
    _install_xtray_window_icon(app=app)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
