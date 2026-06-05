"""Service adapters used by the tray and web surfaces.

Adapter/drive types come from `xtray.core.computer_models` (the cross-package
contract). The live adapter/drive services are optional and degrade to
read-only empty services when `computer_manager` is not installed.
"""
from __future__ import annotations

from typing import Any

try:
    from computer_manager.adapter_manager import AdapterService
except ImportError:

    class AdapterService:  # pragma: no cover - exercised by optional-boundary tests
        def list_adapters(self) -> list[NetworkAdapter]:
            return []

        def open_network_connections(self) -> None:
            raise RuntimeError("computer_manager is not installed")

        def open_adapter_properties(self, adapter: NetworkAdapter) -> None:
            raise RuntimeError("computer_manager is not installed")

        def set_adapter_enabled(self, adapter: NetworkAdapter, enabled: bool) -> None:
            raise RuntimeError("computer_manager is not installed")

        def set_ip_settings(self, adapter: NetworkAdapter, settings: AdapterIpSettings) -> None:
            raise RuntimeError("computer_manager is not installed")


try:
    from computer_manager.drive_manager import DriveService
except ImportError:

    class DriveService:  # pragma: no cover - exercised by optional-boundary tests
        def list_drives(self) -> list[DriveInfo]:
            return []

        def open_drive(self, drive: DriveInfo) -> None:
            raise RuntimeError("computer_manager is not installed")

        def map_network_drive(self, **_mapping: Any) -> None:
            raise RuntimeError("computer_manager is not installed")

from ..core.computer_models import AdapterIpSettings, DriveInfo, NetworkAdapter
from .display import DisplayService
from .hotkeys import GlobalHotkeyManager, HotkeyError, ParsedHotkey, parse_hotkey
from .network import NetworkService

__all__ = [
    "AdapterIpSettings",
    "AdapterService",
    "DisplayService",
    "DriveInfo",
    "DriveService",
    "GlobalHotkeyManager",
    "HotkeyError",
    "NetworkAdapter",
    "NetworkService",
    "ParsedHotkey",
    "parse_hotkey",
]
