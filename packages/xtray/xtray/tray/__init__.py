"""Windows tray overlay for quickly applying favorite display profiles.

The implementation is split across focused submodules:

* :mod:`xtray.tray.constants` -- shared layout/color constants
* :mod:`xtray.tray.chrome` -- window chrome, icons, theme resolution
* :mod:`xtray.tray.formatting` -- apply-result and display text helpers
* :mod:`xtray.tray.threading` -- :class:`QtThreadRunner` background worker
* :mod:`xtray.tray.widgets` -- custom widgets and lazy widget-class factories
* :mod:`xtray.tray.dialogs` -- the options dialog
* :mod:`xtray.tray.panel` -- the :class:`TrayPanel` view
* :mod:`xtray.tray.app` -- the :class:`TrayApp` controller

This package module keeps the process entry point and re-exports the names
that the CLI, packaging specs, and tests import from ``xtray.tray``.
"""
from __future__ import annotations

import importlib
import sys
from typing import Any

from .. import config
from ..core import app_identity, app_logging, qt_assets
from ..services import AdapterIpSettings, DriveInfo, NetworkAdapter, parse_hotkey
from ..services.display import audio, display_inventory
from ..services.network import devices as network
from .constants import _DISPLAY_BUTTON_SPACING

_SINGLE_INSTANCE_KEY = "XTray-SingleInstance-v1"

__all__ = [
    "main",
    "TrayApp",
    "TrayPanel",
    "ProfilePanel",
    "ApplyMessage",
    "apply_message",
    "audio",
    "display_inventory",
    "network",
    "config",
    "AdapterIpSettings",
    "DriveInfo",
    "NetworkAdapter",
    "parse_hotkey",
    "_DISPLAY_BUTTON_SPACING",
    "_mqtt_state_dispatcher_class",
    "_ha_state_event_dispatcher_class",
    "app",
]


def __getattr__(name: str) -> Any:
    if name == "app":
        return importlib.import_module(f"{__name__}.app")
    if name == "TrayApp":
        from .app import TrayApp

        return TrayApp
    if name in {"TrayPanel", "ProfilePanel"}:
        from .panel import ProfilePanel, TrayPanel

        return {"TrayPanel": TrayPanel, "ProfilePanel": ProfilePanel}[name]
    if name in {"ApplyMessage", "apply_message"}:
        from .formatting import ApplyMessage, apply_message

        return {"ApplyMessage": ApplyMessage, "apply_message": apply_message}[name]
    if name == "_mqtt_state_dispatcher_class":
        from .widgets import _mqtt_state_dispatcher_class

        return _mqtt_state_dispatcher_class
    if name == "_ha_state_event_dispatcher_class":
        from .widgets import _ha_state_event_dispatcher_class

        return _ha_state_event_dispatcher_class
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--gui" in args:
        app_logging.configure_logging(component="computer_manager")
        from computer_manager.app import main as gui_main

        gui_main()
        return
    if "--network" in args:
        app_logging.configure_logging(component="network_manager")
        from network_manager.app import main as network_main

        network_main()
        return
    app_logging.configure_logging(component="tray")
    try:
        from PySide6.QtCore import QSharedMemory  # type: ignore[import-not-found]
        from PySide6.QtWidgets import (  # type: ignore[import-not-found]
            QApplication,
            QSystemTrayIcon,
        )
    except ImportError as exc:
        raise SystemExit(
            "PySide6 is not installed. Install with: pip install -e .[tray]"
        ) from exc

    app_identity.install_windows_app_user_model_id()
    from ..core.gui import (
        ensure_valid_application_font,
        install_combobox_wheel_guard,
        install_qt_message_handler,
        install_slider_wheel_guard,
    )

    install_qt_message_handler()
    app = QApplication(sys.argv[:1] + args)
    app.aboutToQuit.connect(lambda: app_logging.mark_clean_shutdown("tray"))
    app_identity.apply_qt_application_metadata(app)

    single_instance = QSharedMemory(_SINGLE_INSTANCE_KEY)
    # On Linux/macOS a previous crash can leave the segment orphaned; attaching
    # then detaching forces cleanup. On Windows the OS releases it automatically.
    if single_instance.attach():
        single_instance.detach()
    if not single_instance.create(1):
        app_logging.get_logger("tray").info(
            "another XTray instance is already running; exiting"
        )
        raise SystemExit(0)
    # Keep the lock alive for the whole process lifetime.
    app._xtray_single_instance = single_instance  # type: ignore[attr-defined]

    ensure_valid_application_font(app)
    install_combobox_wheel_guard(app)
    install_slider_wheel_guard(app)
    qt_assets.set_application_window_icon(app)
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        raise SystemExit("Windows system tray is not available")
    from .app import TrayApp

    tray_app = TrayApp(app)
    tray_app.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
