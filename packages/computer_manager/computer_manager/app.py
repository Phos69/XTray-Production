"""PySide6 desktop interface for Computer Manager."""
from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from xtray import config
from xtray.core import app_logging
from xtray.core.gui import install_combobox_wheel_guard, install_qt_message_handler
from xtray.core.theme import DEFAULT_THEME, build_app_stylesheet, theme_by_name

from ._helpers import (
    _print_console_message,
)
from ._helpers import (
    _print_runtime_diagnostics as _print_runtime_diagnostics_impl,
)
from ._thread_runner import ThreadRunner
from .display_manager import profiles
from .display_manager.backend import DisplayMode, DisplayState
from .display_manager.inventory_controller import InventoryController
from .display_manager.profile_editor import ProfileEditor


def _install_xtray_window_icon(
    *, app: Any | None = None, window: Any | None = None
) -> None:
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


def _install_computer_manager_extension(window: Any) -> Any | None:
    try:
        from .ui_extensions import install_computer_manager_tabs
    except Exception:
        app_logging.get_logger("gui").debug("XTray Computer Manager tabs unavailable")
        return None
    return install_computer_manager_tabs(window)


def _configured_theme_name() -> str:
    try:
        return config.get_theme_name()
    except config.ConfigError as exc:
        app_logging.get_logger("gui").warning("invalid theme setting: %s", exc)
        return DEFAULT_THEME.name


def main() -> None:
    app_logging.configure_logging(component="computer_manager")
    try:
        from PySide6.QtWidgets import QApplication  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SystemExit(
            "PySide6 is not installed. Install with: pip install -e .[gui]"
        ) from exc

    _print_runtime_diagnostics()
    install_qt_message_handler()
    app = QApplication(sys.argv)
    app.aboutToQuit.connect(lambda: app_logging.mark_clean_shutdown("computer_manager"))
    install_combobox_wheel_guard(app)

    _install_xtray_window_icon(app=app)
    window = MainWindow()
    window.resize(1180, 720)
    window.show()
    app.aboutToQuit.connect(_export_inventory_on_quit)
    raise SystemExit(app.exec())


def _export_inventory_on_quit() -> None:
    """Snapshot adapter/drive/display state on exit so the tray (running in a
    separate process, possibly without computer_manager installed) can keep
    rendering its panels using `computer_inventory.json`."""
    from . import export

    try:
        path = export.write_inventory()
    except Exception:
        app_logging.get_logger("computer_manager").warning(
            "inventory snapshot on exit failed", exc_info=True
        )
        return
    app_logging.get_logger("computer_manager").info("wrote inventory snapshot to %s", path)


class MainWindow:  # pragma: no cover - imported only when GUI dependencies exist
    def __init__(self) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QMessageBox  # type: ignore[import-not-found]

        from . import _layout_builder

        install_combobox_wheel_guard()
        self._qt = Qt
        self._message_box = QMessageBox
        self._updating_form = False
        self._theme = theme_by_name(_configured_theme_name())

        self._inventory = InventoryController(self)
        self._editor = ProfileEditor(self)
        _layout_builder.build(self)
        self._runner = ThreadRunner(self)

        self.refresh_profiles()
        self._inventory.show_display_inventory_loading()
        self.load_current_preview(show_errors=False)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.window, name)

    def refresh_profiles(self) -> None:
        self.profile_panel.set_profiles(profiles.list_profiles())

    def _select_profile_list_item(self, name: str | None) -> None:
        self.profile_panel.select_profile(name)

    def on_main_tab_changed(self, index: int) -> None:
        label = self.main_tabs.tabText(index)
        if label == "Displays":
            if not self.window.isVisible():
                self._inventory.refresh_display_inventory()
                return
            self._inventory.refresh_display_inventory_async()
            return
        extension = getattr(self, "_computer_manager_extension", None)
        if extension is not None:
            extension.on_tab_changed(label)

    def on_theme_toggled(self, checked: bool) -> None:
        theme_name = "dark" if checked else DEFAULT_THEME.name
        try:
            config.set_theme_name(theme_name)
        except config.ConfigError as exc:
            self.show_error(str(exc))
            self.dark_theme_action.setChecked(self._theme.name == "dark")
            return
        self._set_theme(theme_by_name(theme_name))

    def _set_theme(self, theme: Any) -> None:
        self._theme = theme
        self.window.setStyleSheet(build_app_stylesheet(theme))
        self.icon_picker.set_color(theme.text)
        self._editor.redraw_scene()

    # ------- Delegates kept for backward compat with external callers -------
    # load_current_preview: monkey-patched by test_ui_extensions on the class.
    # load_profile: bound as ProfileListPanel callback in _layout_builder.
    # _modes_for: called by InventoryController via host._modes_for.

    def load_current_preview(self, *, show_errors: bool = True) -> None:
        self._editor.load_current_preview(show_errors=show_errors)

    def load_profile(self, name: str) -> None:
        self._editor.load_profile(name)

    def _modes_for(self, display_state: DisplayState) -> list[DisplayMode]:
        return self._editor._modes_for(display_state)

    def show_error(self, message: str) -> None:
        _print_console_message("ERROR", message, stream=sys.stderr)
        self._message_box.critical(self.window, "Computer Manager", message)

    def show_info(self, message: str) -> None:
        _print_console_message("INFO", message, stream=sys.stdout)
        self._message_box.information(self.window, "Computer Manager", message)

    @property
    def _busy_count(self) -> int:
        return self._runner.busy_count

    def _run_in_thread(
        self,
        target: Callable[[], Any],
        on_success: Callable[[Any], None],
        *,
        on_failure: Callable[[str], None] | None = None,
        busy: bool = True,
        cleanup: Callable[[], None] | None = None,
    ) -> None:
        self._runner.run(
            target,
            on_success,
            on_failure=on_failure,
            busy=busy,
            cleanup=cleanup,
        )

    def _set_busy(self, busy: bool) -> None:
        self._runner.set_busy(busy)


def _print_runtime_diagnostics() -> None:
    _print_runtime_diagnostics_impl(__file__)


if __name__ == "__main__":
    main()
