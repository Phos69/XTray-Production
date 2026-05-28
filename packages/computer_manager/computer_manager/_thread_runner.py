"""Background-thread runner for the Computer Manager MainWindow.

Encapsulates the QThread + Worker + cross-thread callbacks dance that was
previously inlined in MainWindow as ``_run_in_thread`` + ``_set_busy`` +
the ``_workers`` / ``_busy_count`` / ``_action_buttons`` state. Same pattern
already in use by ``network_manager.device_manager._async_runner.AsyncRunner``.

The runner keeps a back-reference to the host MainWindow so it can read
``host.window`` (QThread parent), ``host._action_buttons`` (the buttons to
gray out while busy), and call ``host.show_error`` for default failure
reporting -- the same coupling already accepted by adapter_manager/ui.py and
drive_manager/ui.py via ``self.host._run_in_thread``.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from xtray.core import app_logging, qt_helpers


class ThreadRunner:  # pragma: no cover - imported only when GUI dependencies exist
    def __init__(self, host: Any) -> None:
        self._host = host
        self._workers: list[tuple[Any, Any, Any]] = []
        self._busy_count = 0

    @property
    def busy_count(self) -> int:
        return self._busy_count

    def run(
        self,
        target: Callable[[], Any],
        on_success: Callable[[Any], None],
        *,
        on_failure: Callable[[str], None] | None = None,
        busy: bool = True,
        cleanup: Callable[[], None] | None = None,
    ) -> None:
        """Run a blocking callable on a Qt worker thread.

        Why: WinAPI / DDC-CI / COM calls can take seconds; running them on
        the Qt event loop freezes the UI and looks like a crash.
        """
        from PySide6.QtCore import Qt, QThread  # type: ignore[import-not-found]

        worker_cls = qt_helpers.worker_class("gui")
        callbacks_cls = qt_helpers.thread_callbacks_class()
        thread = QThread(self._host.window)
        worker = worker_cls(target)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def final_cleanup() -> None:
            if busy:
                self.set_busy(False)
            if cleanup is not None:
                cleanup()
            for entry in list(self._workers):
                if entry[0] is thread:
                    self._workers.remove(entry)
                    break

        def handle_success(result: Any) -> None:
            try:
                on_success(result)
            except Exception as exc:
                app_logging.get_logger("gui").exception("on_success handler failed")
                self._host.show_error(str(exc))

        def handle_failure(message: str) -> None:
            try:
                if on_failure is not None:
                    on_failure(message)
                else:
                    self._host.show_error(message)
            except Exception:
                app_logging.get_logger("gui").exception("on_failure handler failed")

        callbacks = callbacks_cls(handle_success, handle_failure, final_cleanup)

        worker.finished.connect(
            callbacks.handle_success, Qt.ConnectionType.QueuedConnection
        )
        worker.failed.connect(
            callbacks.handle_failure, Qt.ConnectionType.QueuedConnection
        )
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            callbacks.cleanup, Qt.ConnectionType.QueuedConnection
        )
        thread.finished.connect(
            callbacks.deleteLater, Qt.ConnectionType.QueuedConnection
        )

        self._workers.append((thread, worker, callbacks))
        if busy:
            self.set_busy(True)
        thread.start()

    def set_busy(self, busy: bool) -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtGui import QCursor  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QApplication  # type: ignore[import-not-found]

        if busy:
            self._busy_count += 1
            if self._busy_count == 1:
                for button in self._host._action_buttons:
                    button.setEnabled(False)
                QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
            return
        self._busy_count = max(0, self._busy_count - 1)
        if self._busy_count == 0:
            for button in self._host._action_buttons:
                button.setEnabled(True)
            QApplication.restoreOverrideCursor()
