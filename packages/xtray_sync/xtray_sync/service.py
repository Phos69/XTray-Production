"""Tray-owned LAN sync runtime."""
from __future__ import annotations

from dataclasses import dataclass

from xtray.core import app_logging

from . import config as sync_config
from .discovery import DiscoveryAnnouncer
from .server import ServerThread


@dataclass
class RuntimeStatus:
    enabled: bool
    ready: bool
    running: bool
    reason: str | None = None


class SyncRuntime:
    def __init__(self) -> None:
        self._server: ServerThread | None = None
        self._announcer: DiscoveryAnnouncer | None = None
        self._status = RuntimeStatus(enabled=False, ready=False, running=False)

    def start(self) -> RuntimeStatus:
        self.stop()
        settings = sync_config.load_sync_settings()
        if not settings.enabled:
            self._status = RuntimeStatus(False, False, False, "sync disabled")
            return self._status
        if not sync_config.password_available():
            self._status = RuntimeStatus(True, False, False, "sync password missing")
            return self._status
        try:
            self._server = ServerThread(port=settings.port)
            self._server.start()
            self._announcer = DiscoveryAnnouncer()
            self._announcer.start()
        except Exception as exc:
            app_logging.get_logger("sync").warning("sync runtime failed to start: %s", exc)
            self.stop()
            self._status = RuntimeStatus(True, True, False, str(exc))
            return self._status
        app_logging.get_logger("sync").info("sync runtime started on port %s", settings.port)
        self._status = RuntimeStatus(True, True, True)
        return self._status

    def restart(self) -> RuntimeStatus:
        return self.start()

    def stop(self) -> None:
        if self._announcer is not None:
            self._announcer.stop()
            self._announcer = None
        if self._server is not None:
            self._server.stop()
            self._server = None
        self._status = RuntimeStatus(
            enabled=self._status.enabled,
            ready=self._status.ready,
            running=False,
            reason=self._status.reason,
        )

    def status(self) -> RuntimeStatus:
        return self._status
