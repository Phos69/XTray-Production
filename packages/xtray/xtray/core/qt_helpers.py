"""Shared PySide6 helpers used by both the GUI and the tray app.

Importing this module triggers a deferred PySide6 import only when a helper is
actually called, so headless environments (CLI, API, tests) can import the
package without PySide6 installed.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import app_logging

_WORKER_CLASS: type[Any] | None = None
_THREAD_CALLBACKS_CLASS: type[Any] | None = None


def worker_class(logger_name: str = "qt") -> type[Any]:
    """Return a cached ``QObject`` worker class that runs a callable on a QThread."""
    global _WORKER_CLASS
    if _WORKER_CLASS is not None:
        return _WORKER_CLASS
    from PySide6.QtCore import QObject, Signal  # type: ignore[import-not-found]

    class _Worker(QObject):
        finished = Signal(object)
        failed = Signal(str)

        def __init__(self, target: Callable[[], Any]) -> None:
            super().__init__()
            self._target = target

        def run(self) -> None:
            try:
                result = self._target()
            except Exception as exc:
                app_logging.get_logger(logger_name).exception("background task failed")
                self.failed.emit(str(exc))
            else:
                self.finished.emit(result)

    _WORKER_CLASS = _Worker
    return _WORKER_CLASS


def thread_callbacks_class() -> type[Any]:
    """Return a cached ``QObject`` that owns the GUI-thread slots for a worker."""
    global _THREAD_CALLBACKS_CLASS
    if _THREAD_CALLBACKS_CLASS is not None:
        return _THREAD_CALLBACKS_CLASS
    from PySide6.QtCore import QObject, Slot  # type: ignore[import-not-found]

    class _ThreadCallbacks(QObject):
        def __init__(
            self,
            on_success: Callable[[Any], None],
            on_failure: Callable[[str], None],
            cleanup: Callable[[], None],
        ) -> None:
            super().__init__()
            self._on_success = on_success
            self._on_failure = on_failure
            self._cleanup = cleanup

        @Slot(object)
        def handle_success(self, result: Any) -> None:
            self._on_success(result)

        @Slot(str)
        def handle_failure(self, message: str) -> None:
            self._on_failure(message)

        @Slot()
        def cleanup(self) -> None:
            self._cleanup()

    _THREAD_CALLBACKS_CLASS = _ThreadCallbacks
    return _THREAD_CALLBACKS_CLASS


def clear_layout(layout: Any) -> None:
    """Detach and schedule deletion of every widget in a Qt layout."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
