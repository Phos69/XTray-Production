"""Adapter and Drive tabs grafted into the Computer Manager main window.

The actual tab building + behavior lives in `adapter_manager.ui` and
`drive_manager.ui` as mixin classes. This module just composes them and
exposes the `install_computer_manager_tabs(host)` factory used by app.py.
"""
from __future__ import annotations

from typing import Any

from xtray.core import app_logging
from xtray.core.computer_models import DriveInfo, NetworkAdapter

from .adapter_manager import AdapterService
from .adapter_manager.ui import AdapterTabMixin
from .drive_manager import DriveService
from .drive_manager.ui import DriveTabMixin

AUTO_REFRESH_INTERVAL_MS = 180_000  # 3 minutes


class ComputerManagerExtension(AdapterTabMixin, DriveTabMixin):  # pragma: no cover - GUI only
    """Glues the Adapter + Drive tab mixins onto a Computer Manager host window."""

    def __init__(self, host: Any) -> None:
        from PySide6.QtCore import QTimer  # type: ignore[import-not-found]

        self.host = host
        self._adapter_service = AdapterService()
        self._drive_service = DriveService()
        self._adapters: list[NetworkAdapter] = []
        self._drives: list[DriveInfo] = []
        self._selected_adapter: NetworkAdapter | None = None
        self._selected_drive: DriveInfo | None = None
        self._adapters_loaded = False
        self._drives_loaded = False
        self._adapters_refreshing = False
        self._drives_refreshing = False
        self._updating_adapter_detail = False
        self._build_adapters_tab()
        self._build_drives_tab()

        self._auto_refresh_timer = QTimer(host.window)
        self._auto_refresh_timer.setInterval(AUTO_REFRESH_INTERVAL_MS)
        self._auto_refresh_timer.timeout.connect(self._auto_refresh_tick)
        self._auto_refresh_timer.start()
        # Defer the eager initial refresh to the next event-loop tick so it
        # runs after the window finishes constructing (and stays out of the
        # way during unit tests that never start the event loop).
        QTimer.singleShot(0, self.refresh_adapters_async)
        QTimer.singleShot(0, self.refresh_drives_async)

    def _auto_refresh_tick(self) -> None:
        self.refresh_adapters_async(silent=True)
        self.refresh_drives_async(silent=True)

    def on_tab_changed(self, label: str) -> None:
        # Data is loaded eagerly at startup and refreshed every 3 minutes,
        # so tab switches show the cached state. The fallback below only
        # kicks in if the eager refresh has not completed yet (race window).
        if label == "Network Adapters" and not self._adapters_loaded:
            self.refresh_adapters_async()
        elif label == "Drives" and not self._drives_loaded:
            self.refresh_drives_async()


def install_computer_manager_tabs(host: Any) -> ComputerManagerExtension | None:
    try:
        return ComputerManagerExtension(host)
    except Exception:
        app_logging.get_logger("gui").exception("failed to install Computer Manager tabs")
        raise
