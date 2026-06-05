"""Reusable QThread runner for background work behind the tray UI.

``TrayApp`` and the Home Assistant settings dialog both need to run slow
backend calls off the Qt thread and marshal the result back. This module
holds the single implementation they share.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from xtray.core import qt_helpers

from ..core import app_logging


class QtThreadRunner:
    """Runs callables on background ``QThread``s and marshals results to Qt.

    A strong reference to every in-flight ``(thread, worker, callbacks)``
    triple is kept so Qt does not garbage-collect them mid-run; entries are
    dropped automatically once their thread finishes. :meth:`wait_for_workers`
    drains anything still running, e.g. during shutdown.
    """

    def __init__(
        self,
        *,
        log_label: str = "tray",
        log_context: str = "background task",
    ) -> None:
        self._workers: list[tuple[Any, Any, Any]] = []
        self._log_label = log_label
        self._log_context = log_context

    def run(
        self,
        target: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_failure: Callable[[str], None],
        cleanup: Callable[[], None],
    ) -> None:
        from PySide6.QtCore import Qt, QThread  # type: ignore[import-not-found]

        worker_cls = qt_helpers.worker_class(self._log_label)
        callbacks_cls = qt_helpers.thread_callbacks_class()
        thread = QThread()
        worker = worker_cls(target)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        logger = app_logging.get_logger(self._log_label)
        context = self._log_context

        def final_cleanup() -> None:
            try:
                cleanup()
            except Exception:
                logger.exception("%s cleanup failed", context)
            finally:
                for entry in list(self._workers):
                    if entry[0] is thread:
                        self._workers.remove(entry)
                        break

        def handle_success(result: Any) -> None:
            try:
                on_success(result)
            except Exception:
                logger.exception("%s success handler failed", context)

        def handle_failure(message: str) -> None:
            try:
                on_failure(message)
            except Exception:
                logger.exception("%s failure handler failed", context)

        callbacks = callbacks_cls(handle_success, handle_failure, final_cleanup)
        worker.finished.connect(callbacks.handle_success, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(callbacks.handle_failure, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(callbacks.cleanup, Qt.ConnectionType.QueuedConnection)
        thread.finished.connect(callbacks.deleteLater, Qt.ConnectionType.QueuedConnection)
        self._workers.append((thread, worker, callbacks))
        thread.start()

    def wait_for_workers(self) -> None:
        """Stop and join any background threads still running."""
        for thread, _worker, _callbacks in list(self._workers):
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait(3000)
            except RuntimeError:
                # Thread object already destroyed by Qt; nothing left to wait for.
                pass
        self._workers.clear()
