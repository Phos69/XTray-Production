"""Background worker runner for DeviceManagerWidget.

Wraps the QThread + Worker QObject + cross-thread Dispatcher dance into a
single helper. The widget previously had ~100 LOC of `_run_async`,
`_on_worker_done`, `_on_worker_failed`, `_async_finished`, and
`_cancel_async` methods sharing state through `self._thread / self._worker /
self._dispatcher / self._pending_callback / self._disabled_for_async`.
That stateful Qt plumbing has no business sitting in the form/list
controller and is reused identically for every async operation
(ping/scan/list_adapters), so it lives here.
"""
from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any


class AsyncRunner:  # pragma: no cover - requires PySide6
    """Run a sync callable on a background QThread and dispatch the result
    back on the GUI thread.

    Only one task at a time. While a task is in flight subsequent `run()`
    calls report ``busy`` via the optional ``on_busy`` callback (typically
    a status-line setter) and return False.
    """

    def __init__(self, *, on_busy: Callable[[str], None] | None = None) -> None:
        self._thread: Any | None = None
        self._worker: Any | None = None
        self._dispatcher: Any | None = None
        self._pending_callback: Callable[[Any, str | None], None] | None = None
        self._disabled_for_async: list[Any] = []
        self._on_busy = on_busy

    def run(
        self,
        fn: Callable[..., Any],
        on_done: Callable[[Any, str | None], None],
        *args: Any,
        disable: list[Any] | None = None,
        on_progress: Callable[[int, str], None] | None = None,
        **kwargs: Any,
    ) -> bool:
        if self._thread is not None:
            if self._on_busy is not None:
                self._on_busy("Operazione gia' in corso.")
            return False
        from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

        class Worker(QObject):
            done = Signal(object)
            failed = Signal(str)
            progress = Signal(int, str)

            def __init__(
                self,
                target: Callable[..., Any],
                target_args: tuple[Any, ...],
                target_kwargs: dict[str, Any],
                *,
                with_progress: bool,
            ) -> None:
                super().__init__()
                self._target = target
                self._args = target_args
                self._kwargs = target_kwargs
                self._with_progress = with_progress

            def run(self) -> None:
                try:
                    kwargs = dict(self._kwargs)
                    if self._with_progress:
                        kwargs["progress"] = self.progress.emit
                    result = self._target(*self._args, **kwargs)
                except Exception as exc:
                    tb = traceback.format_exc()
                    self.failed.emit(f"{type(exc).__name__}: {exc}\n\n{tb}")
                else:
                    self.done.emit(result)

        class _Dispatcher(QObject):
            def __init__(
                self,
                on_done_cb: Callable[[Any], None],
                on_failed_cb: Callable[[str], None],
            ) -> None:
                super().__init__()
                self._on_done_cb = on_done_cb
                self._on_failed_cb = on_failed_cb

            @Slot(object)
            def handle_done(self, result: Any) -> None:
                self._on_done_cb(result)

            @Slot(str)
            def handle_failed(self, err: str) -> None:
                self._on_failed_cb(err)

        self._pending_callback = on_done
        self._disabled_for_async = list(disable or [])
        for widget in self._disabled_for_async:
            widget.setEnabled(False)
        self._thread = QThread()
        self._worker = Worker(
            fn,
            args,
            dict(kwargs),
            with_progress=on_progress is not None,
        )
        self._worker.moveToThread(self._thread)
        self._dispatcher = _Dispatcher(self._on_worker_done, self._on_worker_failed)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(
            self._dispatcher.handle_done, Qt.ConnectionType.QueuedConnection
        )
        self._worker.failed.connect(
            self._dispatcher.handle_failed, Qt.ConnectionType.QueuedConnection
        )
        if on_progress is not None:
            self._worker.progress.connect(on_progress)
        self._thread.start()
        return True

    def cancel(self) -> None:
        """Stop the in-flight task (best effort) and drop the pending callback."""
        self._pending_callback = None
        if self._thread is not None:
            try:
                if self._thread.isRunning():
                    self._thread.quit()
                    self._thread.wait(3000)
            except RuntimeError:
                pass
            self._thread = None
            self._worker = None
        self._dispatcher = None

    def _on_worker_done(self, result: Any) -> None:
        self._finish(result, None)

    def _on_worker_failed(self, err: str) -> None:
        self._finish(None, err)

    def _finish(self, result: Any, err: str | None) -> None:
        callback = self._pending_callback
        self._pending_callback = None
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread.deleteLater()
            self._thread = None
            if self._worker is not None:
                self._worker.deleteLater()
            self._worker = None
        if self._dispatcher is not None:
            self._dispatcher.deleteLater()
            self._dispatcher = None
        for widget in self._disabled_for_async:
            widget.setEnabled(True)
        self._disabled_for_async = []
        if callback is not None:
            callback(result, err)
