"""The XTray tray controller: orchestrates the panel, MQTT, and background work."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import webbrowser
from collections.abc import Callable
from dataclasses import is_dataclass
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import Any

from xtray.core import icons
from xtray.core.dialogs import AdapterInfoDialog, NetworkDriveDialog
from xtray.core.theme import DEFAULT_THEME, build_app_stylesheet, theme_by_name

from .. import __version__, autostart, config, ha_mqtt, ha_ws, updater
from ..core import app_logging, qt_assets
from ..services import (
    AdapterIpSettings,
    AdapterService,
    DisplayService,
    DriveService,
    GlobalHotkeyManager,
    HotkeyError,
)
from ..services.display import audio, display_inventory
from ..services.network import devices as network
from . import app_mqtt as _app_mqtt
from .chrome import _app_icon, _current_theme
from .dialogs import LanSyncImportDialog, TrayOptionsDialog, UpdateOptionsDialog
from .formatting import _format_apply_result_summary, _log_apply_result, apply_message
from .live_data import LiveDataKey, LiveDataSource, LiveSnapshot, TrayLiveDataHub
from .panel import TrayPanel
from .threading import QtThreadRunner
from .widgets import (
    _endpoint_event_dispatcher_class,
    _ha_state_event_dispatcher_class,
    _mqtt_state_dispatcher_class,
    _volume_event_dispatcher_class,
)

try:
    from computer_manager.audio_manager import (
        EndpointChangeListener,
        VolumeChangeEvent,
        VolumeChangeListener,
        read_current_volume,
    )
except ImportError:  # pragma: no cover - audio listener is Windows-only
    EndpointChangeListener = None  # type: ignore[assignment]
    VolumeChangeEvent = None  # type: ignore[assignment]
    VolumeChangeListener = None  # type: ignore[assignment]
    read_current_volume = None  # type: ignore[assignment]

try:
    from computer_manager.display_manager import messages
except ImportError:

    class messages:  # pragma: no cover - optional read-only mode
        @staticmethod
        def format_profile_apply_summary(result: Any) -> str:
            data = result.to_dict()
            errors = data.get("errors") or []
            if errors:
                return "; ".join(str(error) for error in errors)
            return "Profile applied." if data.get("applied") else "Profile not applied."


_UNSET_ENDPOINT = object()
_ENABLE_NATIVE_AUDIO_EVENTS_ENV = "XTRAY_ENABLE_NATIVE_AUDIO_EVENTS"
_DISABLE_NATIVE_AUDIO_EVENTS_ENV = "XTRAY_DISABLE_NATIVE_AUDIO_EVENTS"

_PANEL_LIVE_KEYS = (
    LiveDataKey.PROFILES,
    LiveDataKey.ACTIVE_PROFILE,
    LiveDataKey.AUDIO,
    LiveDataKey.DISPLAYS,
    LiveDataKey.NETWORK,
    LiveDataKey.ADAPTERS,
    LiveDataKey.DRIVES,
)

# Sources warmed up right after the tray icon appears. Adapters and drives
# are intentionally excluded — their loaders are the slowest (WMI / disk)
# and they are only needed when the user selects the relevant tab.
_STARTUP_PRIME_KEYS = (
    LiveDataKey.PROFILES,
    LiveDataKey.ACTIVE_PROFILE,
    LiveDataKey.AUDIO,
    LiveDataKey.DISPLAYS,
    LiveDataKey.NETWORK,
)


def _env_truthy(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _native_audio_events_disabled_from_env() -> tuple[bool, str]:
    native_audio_requested = _env_truthy(os.environ.get(_ENABLE_NATIVE_AUDIO_EVENTS_ENV))
    native_audio_blocked = _env_truthy(os.environ.get(_DISABLE_NATIVE_AUDIO_EVENTS_ENV))
    if native_audio_blocked:
        return True, f"{_DISABLE_NATIVE_AUDIO_EVENTS_ENV}=1"
    if not native_audio_requested:
        return True, f"{_ENABLE_NATIVE_AUDIO_EVENTS_ENV} is not enabled"
    return False, ""


_TAB_LIVE_KEYS = {
    # Adapters and drives intentionally omitted: their data only feeds the
    # popup launchers on the media header, which trigger their own refresh
    # in toggle_*_popup. Including them here would (a) reload slow WMI/disk
    # data on every media tab click and (b) light up the adapters/drives
    # tab icons as "refreshing" whenever the user touches media — and vice
    # versa lighting up the media icon when adapters/drives reload.
    "media": (
        LiveDataKey.PROFILES,
        LiveDataKey.ACTIVE_PROFILE,
        LiveDataKey.AUDIO,
        LiveDataKey.DISPLAYS,
    ),
    "network": (LiveDataKey.NETWORK,),
    "adapters": (LiveDataKey.ADAPTERS,),
    "drives": (LiveDataKey.DRIVES,),
}


class TrayApp:  # pragma: no cover - imported only when GUI dependencies exist
    def __init__(self, app: Any) -> None:
        from PySide6.QtCore import QProcess, QTimer  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon  # type: ignore[import-not-found]

        self.app = app
        self._qprocess = QProcess
        self._threads = QtThreadRunner(log_context="background task")
        self._closing = False
        self._initializing = True
        self._panel_destroyed = False
        self._busy = False
        self._ha_status_refreshing = False
        self._mqtt_publish_in_progress = False
        self._update_check_in_progress = False
        self._update_install_in_progress = False
        self._service = DisplayService()
        self._adapter_service = AdapterService()
        self._drive_service = DriveService()
        self._hotkey_manager: GlobalHotkeyManager | None = None
        self._network_manager_window: Any | None = None
        self._network_manager_watcher: Any | None = None
        self._options_dialog: Any | None = None
        self._sync_runtime: Any | None = None
        self._sync_import_dialog: Any | None = None
        dispatcher_cls = _mqtt_state_dispatcher_class()
        self._mqtt_state_dispatcher = dispatcher_cls(self._set_mqtt_indicator, app)
        ha_dispatcher_cls = _ha_state_event_dispatcher_class()
        self._ha_state_event_dispatcher = ha_dispatcher_cls(
            self._handle_ha_media_player_event, app
        )
        self._ha_state_listener: ha_ws.HomeAssistantMediaPlayerListener | None = None
        volume_dispatcher_cls = _volume_event_dispatcher_class()
        self._volume_event_dispatcher = volume_dispatcher_cls(
            self._handle_volume_event, app
        )
        self._volume_listener: Any | None = None
        self._volume_listener_endpoint_id: str | None | object = _UNSET_ENDPOINT
        endpoint_dispatcher_cls = _endpoint_event_dispatcher_class()
        self._endpoint_event_dispatcher = endpoint_dispatcher_cls(
            self._handle_endpoint_event, app
        )
        self._endpoint_listener: Any | None = None
        (
            self._native_audio_events_disabled,
            native_audio_disabled_reason,
        ) = _native_audio_events_disabled_from_env()
        if self._native_audio_events_disabled:
            app_logging.get_logger("tray").info(
                "native audio event listeners disabled (%s); using polling",
                native_audio_disabled_reason,
            )
        self._endpoint_refresh_timer = QTimer(app)
        self._endpoint_refresh_timer.setSingleShot(True)
        self._endpoint_refresh_timer.setInterval(250)
        self._endpoint_refresh_timer.timeout.connect(self.refresh_panel_audio)
        self._audio_poll_timer = QTimer(app)
        self._audio_poll_timer.setInterval(1500)
        self._audio_poll_timer.timeout.connect(self._poll_pc_volume)
        self._mqtt_commands: queue.Queue[ha_mqtt.MqttCommand] = queue.Queue()
        self._mqtt_bridge: ha_mqtt.HomeAssistantMqttBridge | None = None
        self._theme = _current_theme()
        try:
            autostart.migrate_legacy_autostart()
        except autostart.AutostartError:
            app_logging.get_logger("tray").debug("legacy autostart migration skipped", exc_info=True)
        # Create the hub before the panel: TrayPanel's constructor applies
        # tray_options, which fires tabs.currentChanged → on_tray_tab_changed
        # → _apply_cached_live_data on self._live_data. The hub has no
        # sources registered yet (apply_cached is a no-op without sources),
        # so the call succeeds without starting background work.
        # During initialization, on_tray_tab_changed suppresses refresh; the
        # startup warm-up happens through _prime_live_data after show().
        self._live_data = TrayLiveDataHub(
            self._run_in_thread,
            on_state_changed=self._on_live_data_state_changed,
        )
        self.panel = TrayPanel(self, service=self._service, theme=self._theme)
        self.panel.destroyed.connect(self._on_panel_destroyed)
        self._register_live_data_sources()
        self._initializing = False
        self._start_volume_listener()
        self._start_endpoint_listener()
        self._start_audio_polling()
        self._start_ha_state_listener()
        self._reload_integration_options()
        self.tray = QSystemTrayIcon(_app_icon(self._theme), app)
        self.tray.setToolTip("XTray")
        self.menu = QMenu()
        self.options_action = self.menu.addAction("Options...")
        self.open_gui_action = self.menu.addAction("Open Computer Manager")
        self.open_network_manager_action = self.menu.addAction("Open Network Manager")
        self.import_sync_action = self.menu.addAction("Import from LAN PC...")
        self.menu.addSeparator()
        self.check_updates_action = self.menu.addAction("Check for Updates")
        self.menu.addSeparator()
        self.open_logs_action = self.menu.addAction("Open Logs Folder")
        self.create_diagnostics_action = self.menu.addAction("Create Diagnostics ZIP")
        self.menu.addSeparator()
        self.restart_action = self.menu.addAction("Restart")
        self.quit_action = self.menu.addAction("Quit")
        self.tray.setContextMenu(self.menu)

        self.options_action.triggered.connect(lambda _checked=False: self.open_options())
        self.open_gui_action.triggered.connect(self.open_gui)
        self.open_network_manager_action.triggered.connect(self.open_network_manager)
        self.import_sync_action.triggered.connect(self.open_sync_import)
        self.check_updates_action.triggered.connect(self.check_for_updates)
        self.open_logs_action.triggered.connect(self.open_logs_folder)
        self.create_diagnostics_action.triggered.connect(self.create_diagnostics_zip)
        self.restart_action.triggered.connect(self.restart)
        self.quit_action.triggered.connect(self.quit)
        self.tray.activated.connect(self.on_tray_activated)
        self._mqtt_command_timer = QTimer(app)
        self._mqtt_command_timer.setInterval(250)
        self._mqtt_command_timer.timeout.connect(self._drain_mqtt_commands)
        self._mqtt_refresh_timer = QTimer(app)
        self._mqtt_refresh_timer.setInterval(30_000)
        self._mqtt_refresh_timer.timeout.connect(self.publish_mqtt_snapshot)
        self._ha_status_timer = QTimer(app)
        self._ha_status_timer.setInterval(15_000)
        self._ha_status_timer.timeout.connect(self._refresh_ha_status)
        self._ha_status_timer.start()
        self._panel_data_refresh_timer = QTimer(app)
        self._panel_data_refresh_timer.setInterval(180_000)  # 3 minutes
        self._panel_data_refresh_timer.timeout.connect(self._auto_refresh_panel_data)
        self._panel_data_refresh_timer.start()
        # Eager initial load so all tray widget data is warm the first time
        # the user opens it; deferred so the QApplication event loop drives
        # the worker threads.
        QTimer.singleShot(0, self._prime_live_data)
        if updater.automatic_checks_enabled():
            QTimer.singleShot(updater.AUTO_CHECK_DELAY_MS, self._auto_check_for_updates)
        self._start_mqtt_bridge()
        self._restart_sync_runtime()
        self._refresh_mqtt_indicator()
        self._refresh_ha_status()
        self._configure_global_hotkey()
        try:
            app.styleHints().colorSchemeChanged.connect(self._on_system_color_scheme_changed)
        except (AttributeError, RuntimeError):
            pass
        app_logging.get_logger("tray").info("tray controller initialized")

    def show(self) -> None:
        self.tray.show()

    def _is_closing(self) -> bool:
        return bool(
            getattr(self, "_closing", False)
            or getattr(self, "_panel_destroyed", False)
        )

    def _panel_is_available(self) -> bool:
        if self._is_closing():
            return False
        panel = getattr(self, "panel", None)
        if panel is None:
            return False
        try:
            from shiboken6 import isValid  # type: ignore[import-not-found]

            return bool(isValid(panel))
        except Exception:
            return True

    def _on_panel_destroyed(self, *_args: Any) -> None:
        self._panel_destroyed = True
        self._closing = True

    def _register_live_data_sources(self) -> None:
        self._live_data.register(
            LiveDataSource(
                key=LiveDataKey.PROFILES,
                load=self._display_service().list_favorite_profile_icons,
                apply_value=self.panel.apply_profile_icon_map,
                apply_error=self._apply_profiles_error,
                show_loading=self.panel.show_profiles_loading,
            )
        )
        self._live_data.register(
            LiveDataSource(
                key=LiveDataKey.ACTIVE_PROFILE,
                load=self._load_active_profile,
                apply_value=self.panel.set_active_profile,
                apply_error=self._apply_active_profile_error,
            )
        )
        self._live_data.register(
            LiveDataSource(
                key=LiveDataKey.AUDIO,
                load=lambda: self._display_service().load_audio_panel_state(),
                apply_value=self._apply_audio_state,
                apply_error=self._apply_audio_error,
                show_loading=self.panel.show_audio_loading,
            )
        )
        self._live_data.register(
            LiveDataSource(
                key=LiveDataKey.DISPLAYS,
                load=lambda: self._display_service().list_display_inventory(),
                apply_value=self._apply_display_inventory,
                apply_error=self._apply_display_error,
                show_loading=self.panel.show_displays_loading,
            )
        )
        self._live_data.register(
            LiveDataSource(
                key=LiveDataKey.NETWORK,
                load=network.list_devices,
                apply_value=self._apply_network_devices,
                apply_error=self._apply_network_error,
                show_loading=self.panel.show_network_loading,
            )
        )
        self._live_data.register(
            LiveDataSource(
                key=LiveDataKey.ADAPTERS,
                load=self._adapter_service.list_adapters,
                apply_value=self._apply_adapters,
                apply_error=self._apply_adapters_error,
                show_loading=self.panel.show_adapters_loading,
            )
        )
        self._live_data.register(
            LiveDataSource(
                key=LiveDataKey.DRIVES,
                load=self._drive_service.list_drives,
                apply_value=self._apply_drives,
                apply_error=self._apply_drives_error,
                show_loading=self.panel.show_drives_loading,
            )
        )

    def _prime_live_data(self) -> None:
        if self._is_closing():
            return
        if not self.tray.isVisible() and not self.panel.isVisible():
            return
        self._stagger_refresh(
            _STARTUP_PRIME_KEYS,
            reason="initial",
            show_loading=False,
        )

    def _stagger_refresh(
        self,
        keys: tuple[LiveDataKey, ...],
        *,
        reason: str,
        show_loading: bool | None = None,
    ) -> None:
        from PySide6.QtCore import QTimer  # type: ignore[import-not-found]

        pending = list(keys)

        def step() -> None:
            if self._is_closing():
                return
            if not pending:
                return
            key = pending.pop(0)
            self._live_data.refresh(key, reason=reason, show_loading=show_loading)
            if pending:
                QTimer.singleShot(0, step)

        QTimer.singleShot(0, step)

    def _apply_cached_live_data(self, keys: tuple[LiveDataKey, ...]) -> None:
        if self._is_closing():
            return
        self._live_data.apply_cached(keys)

    def _refresh_live_data(
        self,
        keys: tuple[LiveDataKey, ...],
        *,
        reason: str,
        show_loading: bool | None = None,
    ) -> None:
        if self._is_closing():
            return
        self._live_data.refresh_many(
            keys,
            reason=reason,
            show_loading=show_loading,
        )

    def _on_live_data_state_changed(
        self,
        _key: LiveDataKey,
        _snapshot: LiveSnapshot,
    ) -> None:
        if self._is_closing():
            return
        self._refresh_live_tab_indicators()

    def _refresh_live_tab_indicators(self) -> None:
        if not self._panel_is_available():
            return
        snapshots = self._live_data.snapshots()
        for tab_key, live_keys in _TAB_LIVE_KEYS.items():
            refreshing = any(
                snapshots.get(live_key, LiveSnapshot()).refreshing
                for live_key in live_keys
            )
            self.panel.set_main_tab_refreshing(tab_key, refreshing)

    def on_tray_tab_changed(self, tab_key: str) -> None:
        from PySide6.QtCore import QTimer  # type: ignore[import-not-found]

        if self._is_closing():
            return
        live_keys = _TAB_LIVE_KEYS.get(tab_key)
        if not live_keys:
            return
        self._apply_cached_live_data(live_keys)
        if getattr(self, "_initializing", False):
            return
        # Defer the refresh so Qt repaints the new tab before we kick off
        # show_loading() / worker threads — otherwise switching to drives or
        # adapters feels laggy because their loaders (WMI / disk) are slow.
        QTimer.singleShot(
            0,
            lambda keys=live_keys, key=tab_key: self._refresh_live_data(
                keys, reason=f"tab:{key}"
            ),
        )

    def _load_active_profile(self) -> str | None:
        snapshot = self._live_data.snapshot(LiveDataKey.PROFILES)
        if snapshot.loaded and isinstance(snapshot.value, dict):
            profile_names = list(snapshot.value)
        else:
            profile_names = self._display_service().list_favorite_profiles()
        return self._display_service().detect_current_favorite_profile(profile_names)

    def _reposition_if_visible(self) -> None:
        if self.panel.isVisible():
            self._position_panel()

    def _apply_profiles_error(self, message: str, snapshot: LiveSnapshot) -> None:
        if snapshot.loaded:
            self.panel.set_status(message)
            return
        self.panel.apply_profile_icon_map({}, error=message)

    def _apply_active_profile_error(self, message: str, snapshot: LiveSnapshot) -> None:
        if not snapshot.loaded:
            self.panel.set_active_profile(None)
        self.panel.set_status(message)

    def _apply_audio_state(self, state: Any) -> None:
        self.panel.apply_audio_panel_state(state)
        self._sync_volume_listener_endpoint(state)
        self._reposition_if_visible()

    def _start_volume_listener(self) -> None:
        if getattr(self, "_native_audio_events_disabled", False):
            self._volume_listener_endpoint_id = _UNSET_ENDPOINT
            return
        if VolumeChangeListener is None:
            return
        if sys.platform != "win32":
            return
        app_logging.get_logger("tray").info("starting native volume listener")
        listener = VolumeChangeListener(self._volume_event_dispatcher.notify)
        if listener.start():
            self._volume_listener = listener
            self._volume_listener_endpoint_id = None
            app_logging.get_logger("tray").info("native volume listener started")
        else:
            self._volume_listener_endpoint_id = _UNSET_ENDPOINT
            app_logging.get_logger("tray").warning("native volume listener did not start")

    def _stop_volume_listener(self) -> None:
        listener = self._volume_listener
        if listener is None:
            return
        try:
            listener.stop()
        except Exception:
            app_logging.get_logger("tray").exception("stop volume listener failed")
        self._volume_listener = None
        self._volume_listener_endpoint_id = _UNSET_ENDPOINT

    def _sync_volume_listener_endpoint(self, state: Any) -> None:
        listener = self._volume_listener
        if listener is None:
            return
        default_source = getattr(state, "default_source", None)
        endpoint_id = getattr(default_source, "endpoint_id", None) if default_source else None
        if self._volume_listener_endpoint_id == endpoint_id:
            return
        if listener.replace_endpoint(endpoint_id):
            self._volume_listener_endpoint_id = endpoint_id

    def _start_audio_polling(self) -> None:
        if not getattr(self, "_native_audio_events_disabled", False):
            return
        if sys.platform != "win32":
            return
        if read_current_volume is None:
            return
        self._audio_poll_timer.start()
        app_logging.get_logger("tray").info("PC volume polling started")

    def _stop_audio_polling(self) -> None:
        timer = getattr(self, "_audio_poll_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()

    def _poll_pc_volume(self) -> None:
        if self._is_closing() or not self._panel_is_available():
            return
        if sys.platform != "win32":
            return
        if not self.panel.isVisible():
            return
        if read_current_volume is None:
            return
        snapshot = self._live_data.snapshot(LiveDataKey.AUDIO)
        if not snapshot.loaded:
            return
        state = snapshot.value
        current_source = getattr(state, "default_source", None)
        current_endpoint = (
            getattr(current_source, "endpoint_id", None) if current_source else None
        )
        try:
            latest_source = self._display_service().get_default_audio_source()
        except Exception:
            app_logging.get_logger("tray").debug(
                "default audio source polling failed",
                exc_info=True,
            )
            latest_source = current_source
        latest_endpoint = (
            getattr(latest_source, "endpoint_id", None) if latest_source else None
        )
        if latest_endpoint != current_endpoint:
            self.refresh_panel_audio()
            return
        event = read_current_volume(latest_endpoint)
        if event is not None:
            self._handle_volume_event(event)

    def _start_endpoint_listener(self) -> None:
        if getattr(self, "_native_audio_events_disabled", False):
            return
        if EndpointChangeListener is None:
            return
        if sys.platform != "win32":
            return
        app_logging.get_logger("tray").info("starting native endpoint listener")
        listener = EndpointChangeListener(self._endpoint_event_dispatcher.notify)
        if listener.start():
            self._endpoint_listener = listener
            app_logging.get_logger("tray").info("native endpoint listener started")
        else:
            app_logging.get_logger("tray").warning("native endpoint listener did not start")

    def _stop_endpoint_listener(self) -> None:
        listener = self._endpoint_listener
        if listener is None:
            return
        try:
            listener.stop()
        except Exception:
            app_logging.get_logger("tray").exception("stop endpoint listener failed")
        self._endpoint_listener = None
        if self._endpoint_refresh_timer.isActive():
            self._endpoint_refresh_timer.stop()

    def _start_ha_state_listener(self) -> None:
        listener = ha_ws.HomeAssistantMediaPlayerListener(
            self._ha_state_event_dispatcher.notify
        )
        if listener.start():
            self._ha_state_listener = listener

    def _stop_ha_state_listener(self) -> None:
        listener = self._ha_state_listener
        if listener is None:
            return
        try:
            listener.stop()
        except Exception:
            app_logging.get_logger("tray").exception("stop HA state listener failed")
        self._ha_state_listener = None

    def _restart_ha_state_listener(self) -> None:
        self._stop_ha_state_listener()
        self._start_ha_state_listener()

    def _handle_endpoint_event(self, event: Any) -> None:
        # Property changes fire frequently (sample rate, format). We only
        # care about list/default changes for the combo + volume slider.
        if event is None:
            return
        kind = getattr(event, "kind", None)
        if kind is not None and getattr(kind, "value", "") == "property_changed":
            return
        # Coalesce bursty events (plug-in fires Added + DefaultChanged +
        # StateChanged) into one panel refresh.
        self._endpoint_refresh_timer.start()

    def _handle_volume_event(self, event: Any) -> None:
        if event is None:
            return

        def patch(state: Any) -> Any:
            if is_dataclass(state):
                return dataclass_replace(
                    state,
                    pc_volume_percent=int(event.volume_percent),
                    pc_muted=bool(event.muted),
                    pc_volume_error=None,
                )
            return state

        self._live_data.patch_snapshot(LiveDataKey.AUDIO, patch)

    def _handle_ha_media_player_event(self, event: Any) -> None:
        if event is None:
            return
        event_entity = str(getattr(event, "entity_id", "") or "").strip().casefold()
        if not event_entity:
            return
        volume_percent = getattr(event, "volume_percent", None)
        muted = getattr(event, "muted", None)
        if volume_percent is None and muted is None:
            return

        def patch(state: Any) -> Any:
            display_volume = getattr(state, "display_volume", None)
            if display_volume is None:
                return state
            state_entity = (
                str(getattr(display_volume, "ha_entity", "") or "")
                .strip()
                .casefold()
            )
            if state_entity != event_entity:
                return state

            updates: dict[str, Any] = {}
            if volume_percent is not None:
                updates["percent"] = int(volume_percent)
            if muted is not None:
                updates["muted"] = bool(muted)
            if not updates:
                return state

            if is_dataclass(display_volume):
                display_volume = dataclass_replace(display_volume, **updates)
            else:
                for key, value in updates.items():
                    try:
                        setattr(display_volume, key, value)
                    except Exception:
                        return state

            if is_dataclass(state):
                return dataclass_replace(
                    state,
                    display_volume=display_volume,
                    display_volume_error=None,
                )
            try:
                state.display_volume = display_volume
                state.display_volume_error = None
            except Exception:
                return state
            return state

        self._live_data.patch_snapshot(LiveDataKey.AUDIO, patch)

    def _apply_audio_error(self, message: str, snapshot: LiveSnapshot) -> None:
        if snapshot.loaded:
            self.panel.set_status(message)
            return
        self.panel.show_audio_unavailable(message)

    def _apply_display_inventory(self, items: list[Any]) -> None:
        self.panel.apply_display_inventory(items)
        self._reposition_if_visible()

    def _apply_display_error(self, message: str, snapshot: LiveSnapshot) -> None:
        if snapshot.loaded:
            self.panel.set_display_status(message)
            return
        self.panel.apply_display_inventory([], error=message)

    def _apply_network_devices(self, devices: list[network.NetworkDevice]) -> None:
        self.panel.apply_network_devices(devices)
        self._reposition_if_visible()

    def _apply_network_error(self, message: str, snapshot: LiveSnapshot) -> None:
        if snapshot.loaded:
            self.panel.set_network_status(message)
            return
        self.panel.apply_network_devices([], error=message)

    def _apply_adapters(self, adapters: list[Any]) -> None:
        self.panel.apply_adapters(adapters)
        self._reposition_if_visible()

    def _apply_adapters_error(self, message: str, snapshot: LiveSnapshot) -> None:
        if snapshot.loaded:
            self.panel.set_adapters_status(message)
            return
        self.panel.apply_adapters([], error=message)

    def _apply_drives(self, drives: list[Any]) -> None:
        self.panel.apply_drives(drives)
        self._reposition_if_visible()

    def _apply_drives_error(self, message: str, snapshot: LiveSnapshot) -> None:
        if snapshot.loaded:
            self.panel.set_drives_status(message)
            return
        self.panel.apply_drives([], error=message)

    def _on_system_color_scheme_changed(self, _scheme: Any) -> None:
        self.tray.setIcon(_app_icon(self._theme))
        qt_assets.set_application_window_icon(self.app)
        if self._network_manager_window is not None:
            qt_assets.set_window_icon(self._network_manager_window)

    def _start_mqtt_bridge(self) -> None:
        _app_mqtt.start_mqtt_bridge(self)

    def _stop_mqtt_bridge(self) -> None:
        _app_mqtt.stop_mqtt_bridge(self)

    def _restart_mqtt_bridge(self) -> None:
        _app_mqtt.restart_mqtt_bridge(self)

    def _refresh_mqtt_indicator(self) -> None:
        _app_mqtt.refresh_mqtt_indicator(self)

    def _on_mqtt_state_changed(self, state: str, detail: str) -> None:
        self._set_mqtt_indicator(state, detail)

    def _set_mqtt_indicator(self, state: str, detail: str) -> None:
        _app_mqtt.set_mqtt_indicator(self, state, detail)

    def _set_ha_indicator(self, state: str, detail: str) -> None:
        _app_mqtt.set_ha_indicator(self, state, detail)

    def _refresh_ha_status(self) -> None:
        _app_mqtt.refresh_ha_status(self)

    def publish_mqtt_snapshot(self) -> None:
        _app_mqtt.publish_mqtt_snapshot(self)

    def _drain_mqtt_commands(self) -> None:
        _app_mqtt.drain_mqtt_commands(self)

    def _handle_mqtt_command(self, command: ha_mqtt.MqttCommand) -> None:
        _app_mqtt.handle_mqtt_command(self, command)

    def on_tray_activated(self, reason: Any) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon  # type: ignore[import-not-found]

        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.toggle_panel()

    def show_tray_context_menu(self, global_pos: Any) -> None:
        self.menu.popup(global_pos)

    def open_logs_folder(self) -> None:
        path = app_logging.log_dir()
        app_logging.get_logger("tray").info("opening logs folder: %s", path)
        try:
            if sys.platform == "win32" and hasattr(os, "startfile"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)], shell=False)
            else:
                subprocess.Popen(["xdg-open", str(path)], shell=False)
        except Exception as exc:
            app_logging.get_logger("tray").exception("failed to open logs folder")
            self.notify("XTray", f"Could not open logs folder: {exc}", error=True)

    def create_diagnostics_zip(self) -> None:
        try:
            bundle = app_logging.create_diagnostics_bundle(component="tray")
            self.app.clipboard().setText(str(bundle))
        except Exception as exc:
            app_logging.get_logger("tray").exception("failed to create diagnostics bundle")
            self.notify("XTray", f"Could not create diagnostics ZIP: {exc}", error=True)
            return
        app_logging.get_logger("tray").info("created diagnostics bundle: %s", bundle)
        self.notify("XTray", f"Diagnostics ZIP created and copied:\n{bundle}")

    def _auto_check_for_updates(self) -> None:
        self.check_for_updates(automatic=True)

    def _refresh_update_action(self) -> None:
        action = getattr(self, "check_updates_action", None)
        if action is None:
            return
        if self._update_install_in_progress:
            action.setText("Installing Update...")
            action.setEnabled(False)
        elif self._update_check_in_progress:
            action.setText("Checking for Updates...")
            action.setEnabled(False)
        else:
            action.setText("Check for Updates")
            action.setEnabled(True)

    def check_for_updates(self, _checked: bool = False, *, automatic: bool = False) -> None:
        if self._update_check_in_progress or self._update_install_in_progress:
            return
        if automatic and not updater.automatic_checks_enabled():
            return
        if not updater.update_checks_supported():
            if not automatic:
                self.notify("XTray", "Updates are only supported on Windows.", error=True)
            return

        self._update_check_in_progress = True
        self._refresh_update_action()
        app_logging.get_logger("tray").info("checking for XTray updates automatic=%s", automatic)

        def run_check() -> updater.UpdateInfo | None:
            return updater.check_for_update(include_prereleases=not automatic)

        def on_success(update_info: updater.UpdateInfo | None) -> None:
            if update_info is None:
                if not automatic:
                    self.notify("XTray", f"XTray {__version__} is up to date.")
                return
            app_logging.get_logger("tray").info(
                "XTray update available: current=%s latest=%s asset=%s",
                __version__,
                update_info.version,
                update_info.asset.name,
            )
            self._offer_update(update_info, automatic=automatic)

        def on_failure(message: str) -> None:
            app_logging.get_logger("tray").warning("update check failed: %s", message)
            if not automatic:
                self.notify("XTray", f"Could not check for updates: {message}", error=True)

        def cleanup() -> None:
            self._update_check_in_progress = False
            self._refresh_update_action()

        self._run_in_thread(run_check, on_success, on_failure, cleanup)

    def _offer_update(self, update_info: updater.UpdateInfo, *, automatic: bool) -> None:
        from PySide6.QtWidgets import QMessageBox  # type: ignore[import-not-found]

        if not automatic:
            sync_settings, _sync_password_configured = self._load_sync_options()
            try:
                experimental = config.get_experimental_features()
            except config.ConfigError:
                experimental = config.default_experimental_features()
            dialog = UpdateOptionsDialog(
                self.panel.window,
                update_info=update_info,
                pc_sync_enabled=bool(sync_settings.get("enabled")),
                network_manager_full_enabled=bool(
                    experimental.get("network_manager_full")
                ),
                network_manager_full_available=config.experimental_feature_available(
                    "network_manager_full"
                ),
            )
            if not dialog.exec():
                return
            self._download_and_install_update(update_info, dialog.install_options())
            return

        message = (
            f"XTray {update_info.version} is available.\n"
            f"Installed version: {__version__}\n\n"
            "Download and install it now? XTray will close and reopen after the update."
        )
        result = QMessageBox.question(
            self.panel.window,
            "XTray Update",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes if not automatic else QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        self._download_and_install_update(update_info)

    def _download_and_install_update(
        self,
        update_info: updater.UpdateInfo,
        install_options: updater.UpdateInstallOptions | None = None,
    ) -> None:
        if self._update_install_in_progress:
            return
        self._update_install_in_progress = True
        self._refresh_update_action()
        self.notify("XTray", f"Downloading XTray {update_info.version}...")

        def run_install() -> Path:
            installer = updater.download_update_installer(update_info)
            return updater.start_update_installer(
                installer,
                installer_args=updater.installer_args_for_options(install_options),
            )

        def on_success(helper: Path) -> None:
            app_logging.get_logger("tray").info("update helper started: %s", helper)
            self.notify("XTray", "Update installer started. XTray will close now.")
            self._release_for_restart()
            self.quit()

        def on_failure(message: str) -> None:
            app_logging.get_logger("tray").warning("update install failed: %s", message)
            self._update_install_in_progress = False
            self._refresh_update_action()
            self.notify("XTray", f"Could not install update: {message}", error=True)

        self._run_in_thread(run_install, on_success, on_failure, lambda: None)

    def toggle_panel(self) -> None:
        if self.panel.isVisible():
            self.panel.hide()
            return
        self.show_panel()

    def show_panel(self) -> None:
        from PySide6.QtCore import QTimer  # type: ignore[import-not-found]

        # Show the panel with whatever the widgets last rendered — Qt keeps
        # widget state across hide(), so reposition+show+raise produces a
        # paint with the previous content. Any config or live-data sync
        # happens in _post_show_sync after the paint, so reopening feels
        # instant even when slow loaders are still in flight.
        if not self._panel_is_available():
            return
        self._position_panel(anchor_to_tray=True)
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()
        QTimer.singleShot(0, self._post_show_sync)

    def _post_show_sync(self) -> None:
        if not self._panel_is_available():
            return
        if not self.panel.isVisible():
            return
        self._reload_tray_options()
        # Version-guarded inside the hub: a no-op when no snapshot has
        # changed since the last apply (the common reopen case).
        self._apply_cached_live_data(_PANEL_LIVE_KEYS)
        active_keys = self._active_tab_live_keys()
        if active_keys:
            self._refresh_live_data(active_keys, reason="show_panel")

    def refresh_panel(self) -> None:
        if not self._panel_is_available():
            return
        self._reload_tray_options()
        self._apply_cached_live_data(_PANEL_LIVE_KEYS)
        active_keys = self._active_tab_live_keys()
        if active_keys:
            self._refresh_live_data(active_keys, reason="refresh_panel")
        self.publish_mqtt_snapshot()
        if self.panel.isVisible():
            self._position_panel()

    def _active_tab_live_keys(self) -> tuple[LiveDataKey, ...]:
        if not self._panel_is_available():
            return ()
        tabs = getattr(self.panel, "tabs", None)
        if tabs is None:
            return ()
        tab_key = self.panel._tab_key_for_index(tabs.currentIndex())
        if tab_key is None:
            return ()
        return _TAB_LIVE_KEYS.get(tab_key, ())

    def refresh_profiles(self, *, silent: bool = False) -> None:
        self._refresh_live_data(
            (LiveDataKey.PROFILES,),
            reason="profiles",
            show_loading=False if silent else None,
        )

    def refresh_active_profile(self, *, silent: bool = False) -> None:
        self._refresh_live_data(
            (LiveDataKey.ACTIVE_PROFILE,),
            reason="active_profile",
            show_loading=False if silent else None,
        )

    def refresh_panel_audio(self) -> None:
        self._refresh_live_data((LiveDataKey.AUDIO,), reason="audio")

    def refresh_display_inventory(self) -> None:
        self._refresh_live_data((LiveDataKey.DISPLAYS,), reason="displays")

    def refresh_network_devices(self) -> None:
        self._refresh_live_data((LiveDataKey.NETWORK,), reason="network")

    def refresh_adapters(self, *, silent: bool = False) -> None:
        self._reload_tray_options()
        self._refresh_live_data(
            (LiveDataKey.ADAPTERS,),
            reason="adapters",
            show_loading=False if silent else None,
        )

    def refresh_drives(self, *, silent: bool = False) -> None:
        self._reload_tray_options()
        self._refresh_live_data(
            (LiveDataKey.DRIVES,),
            reason="drives",
            show_loading=False if silent else None,
        )

    def _auto_refresh_panel_data(self) -> None:
        self._reload_tray_options()
        self._refresh_live_data(
            self._auto_refresh_live_keys(),
            reason="timer",
            show_loading=False,
        )

    def _auto_refresh_live_keys(self) -> tuple[LiveDataKey, ...]:
        options = getattr(self.panel, "_tray_options", {}) or {}

        def enabled(key: str) -> bool:
            return bool(options.get(key, config.default_tray_options()[key]))

        keys: list[LiveDataKey] = []
        if enabled("show_media_tab"):
            keys.extend(
                [
                    LiveDataKey.PROFILES,
                    LiveDataKey.ACTIVE_PROFILE,
                    LiveDataKey.AUDIO,
                ]
            )
            if enabled("show_display_profiles") or enabled("show_media_displays"):
                keys.append(LiveDataKey.DISPLAYS)
            if enabled("show_adapters_tab"):
                keys.append(LiveDataKey.ADAPTERS)
            if enabled("show_media_drives"):
                keys.append(LiveDataKey.DRIVES)
        if enabled("show_network_tab"):
            keys.append(LiveDataKey.NETWORK)
        if enabled("show_adapters_tab") or enabled("show_adapters_popup"):
            keys.append(LiveDataKey.ADAPTERS)
        if enabled("show_drives_tab"):
            keys.append(LiveDataKey.DRIVES)
        if enabled("show_displays_popup"):
            keys.append(LiveDataKey.DISPLAYS)

        deduped: list[LiveDataKey] = []
        for key in keys:
            if key not in deduped:
                deduped.append(key)
        return tuple(deduped)

    def apply_profile(self, name: str) -> None:
        def run_apply() -> Any:
            return self._display_service().apply_profile(name)

        def on_success(result: Any) -> None:
            message = apply_message(name, result)
            _log_apply_result(name, result)
            self.panel.set_status(message.message)
            data = result.to_dict()
            if data.get("applied") and data.get("ok", True):
                self.panel.set_active_profile(name)
            if data.get("applied"):
                self.publish_mqtt_snapshot()
            icon_name = self.panel.profile_icons.get(name)
            self.notify(message.title, f"{name}: {message.message}", icon=icon_name)

        def on_failure(detail: str) -> None:
            app_logging.get_logger("tray").error(
                "apply profile %s failed before a result was returned: %s",
                name,
                detail,
            )
            self.panel.set_status(
                messages.format_profile_apply_summary(
                    "Profilo non applicato",
                    error_count=1,
                )
            )

        self._start_busy_action(
            run_apply, on_success, on_failure, set_busy_kwargs={"active_name": name}
        )

    def apply_audio_source(self, source: audio.AudioSource) -> None:
        label = source.label()

        def run_apply() -> audio.AudioSource:
            return self._display_service().set_audio_source(source)

        def on_success(applied_source: audio.AudioSource) -> None:
            message = f"Audio output changed to {applied_source.label()}."
            self.panel.set_status(message)
            self.refresh_panel_audio()
            self.publish_mqtt_snapshot()
            self.notify("XTray", message)

        def on_failure(message: str) -> None:
            self.panel.set_status(message)
            self.refresh_panel_audio()
            self.notify("XTray", message, error=True)

        self._start_busy_action(
            run_apply, on_success, on_failure,
            setup=lambda: self.panel.set_status(f"Changing audio output to {label}..."),
        )

    def apply_volume_percent(
        self, source: audio.AudioSource | None, percent: int
    ) -> None:
        label = source.label() if source is not None else "default output"

        def run_apply() -> int:
            return self._display_service().set_volume(percent, source)

        def on_success(applied_percent: int) -> None:
            self.panel.set_status(f"PC volume set to {applied_percent}%.")
            self.refresh_panel_audio()
            self.publish_mqtt_snapshot()

        def on_failure(message: str) -> None:
            self.panel.set_status(message)
            self.refresh_panel_audio()
            self.notify("XTray", message, error=True)

        self._start_busy_action(
            run_apply, on_success, on_failure,
            setup=lambda: self.panel.set_status(f"Setting {label} volume to {percent}%..."),
        )

    def apply_tv_volume_percent(self, percent: int) -> None:
        item = self._display_service().get_active_volume_display()
        if item is not None and item.volume_control == config.VOLUME_CONTROL_HA_ENTITY:
            if item.volume_ha_entity:
                self.apply_ha_volume_percent(item.volume_ha_entity, percent)
                return
        if item is not None and item.volume_control == config.VOLUME_CONTROL_HDMI:
            self.apply_display_volume_percent(item.display, percent)
            return
        def run_apply() -> int | None:
            return self._display_service().set_monitor_volume(percent)

        def on_success(applied_percent: int | None) -> None:
            if applied_percent is None:
                self.panel.set_status("No DDC/CI monitor accepted the volume change.")
            else:
                self.panel.set_status(f"TV volume set to {applied_percent}%.")
            self.refresh_panel_audio()

        def on_failure(message: str) -> None:
            self.panel.set_status(message)
            self.refresh_panel_audio()
            self.notify("XTray", message, error=True)

        self._start_busy_action(
            run_apply, on_success, on_failure,
            setup=lambda: self.panel.set_status(f"Setting TV volume to {percent}%..."),
        )

    def apply_ha_volume_percent(self, entity_id: str, percent: int) -> None:
        def run_apply() -> int:
            return self._display_service().set_ha_entity_volume_percent(entity_id, percent)

        def on_success(applied_percent: int) -> None:
            self.panel.set_status(f"{entity_id} set to {applied_percent}%.")
            self.refresh_panel_audio()
            self.publish_mqtt_snapshot()

        def on_failure(message: str) -> None:
            self.panel.set_status(message)
            self.refresh_panel_audio()
            self.notify("XTray", message, error=True)

        self._start_busy_action(
            run_apply, on_success, on_failure,
            setup=lambda: self.panel.set_status(f"Setting {entity_id} to {percent}%..."),
        )

    def apply_ha_muted(self, entity_id: str, muted: bool) -> bool:
        action = "Muting" if muted else "Unmuting"

        def run_apply() -> bool:
            return self._display_service().set_ha_entity_muted(entity_id, muted)

        def on_success(applied_muted: bool) -> None:
            message = (
                f"{entity_id} muted."
                if applied_muted
                else f"{entity_id} unmuted."
            )
            self.panel.set_status(message)
            self.refresh_panel_audio()
            self.refresh_display_inventory()
            self.publish_mqtt_snapshot()

        def on_failure(message: str) -> None:
            self.panel.set_status(message)
            self.refresh_panel_audio()
            self.refresh_display_inventory()
            self.notify("XTray", message, error=True)

        return self._start_busy_action(
            run_apply,
            on_success,
            on_failure,
            setup=lambda: self.panel.set_status(f"{action} {entity_id}..."),
        )

    def apply_display_volume_percent(
        self,
        target: Any,
        percent: int,
    ) -> None:
        label = display_inventory.display_title(target)

        def run_apply() -> int | None:
            return self._display_service().set_display_monitor_volume(target, percent)

        def on_success(applied_percent: int | None) -> None:
            if applied_percent is None:
                self.panel.set_status(f"{label} did not accept the HDMI volume change.")
            else:
                self.panel.set_status(f"{label} HDMI volume set to {applied_percent}%.")
            self.refresh_panel_audio()
            self.publish_mqtt_snapshot()

        def on_failure(message: str) -> None:
            self.panel.set_status(message)
            self.refresh_panel_audio()
            self.notify("XTray", message, error=True)

        self._start_busy_action(
            run_apply, on_success, on_failure,
            setup=lambda: self.panel.set_status(
                f"Setting {label} HDMI volume to {percent}%..."
            ),
        )

    def apply_display_enabled(self, target: Any, enabled: bool) -> None:
        label = display_inventory.display_title(target)
        action = "Enabling" if enabled else "Disabling"

        def run_apply() -> Any:
            return self._display_service().set_display_enabled(target, enabled)

        def on_success(result: Any) -> None:
            summary = _format_apply_result_summary(result)
            self.panel.set_display_status(summary)
            if result.to_dict().get("applied"):
                self.publish_mqtt_snapshot()
            self.refresh_display_inventory()
            self.refresh_panel_audio()
            title = (
                "Display updated"
                if result.to_dict().get("applied")
                else "Display unchanged"
            )
            self.notify(title, f"{label}: {summary}")

        def on_failure(message: str) -> None:
            self.panel.set_display_status(message)
            self.refresh_display_inventory()
            self.notify("XTray", message, error=True)

        self._start_busy_action(
            run_apply, on_success, on_failure,
            setup=lambda: self.panel.set_display_status(f"{action} {label}..."),
        )

    def apply_display_primary(self, target: Any) -> None:
        label = display_inventory.display_title(target)

        def run_apply() -> Any:
            return self._display_service().set_display_primary(target)

        def on_success(result: Any) -> None:
            summary = _format_apply_result_summary(result)
            self.panel.set_display_status(summary)
            if result.to_dict().get("applied"):
                self.publish_mqtt_snapshot()
            self.refresh_display_inventory()
            self.refresh_panel_audio()
            title = (
                "Display updated"
                if result.to_dict().get("applied")
                else "Display unchanged"
            )
            self.notify(title, f"{label}: {summary}")

        def on_failure(message: str) -> None:
            self.panel.set_display_status(message)
            self.refresh_display_inventory()
            self.notify("XTray", message, error=True)

        self._start_busy_action(
            run_apply, on_success, on_failure,
            setup=lambda: self.panel.set_display_status(f"Making {label} primary..."),
        )

    def apply_display_power(self, target: Any, turn_on: bool) -> None:
        label = display_inventory.display_title(target)
        action = "Powering on" if turn_on else "Powering off"

        def run_apply() -> str:
            return self._display_service().call_display_power_service(
                target,
                turn_on=turn_on,
            )

        def on_success(service_id: str) -> None:
            message = f"{label}: {service_id} sent."
            self.panel.set_display_status(message)
            self.refresh_display_inventory()
            self.notify("XTray", message)

        def on_failure(message: str) -> None:
            self.panel.set_display_status(message)
            self.refresh_display_inventory()
            self.notify("XTray", message, error=True)

        self._start_busy_action(
            run_apply, on_success, on_failure,
            setup=lambda: self.panel.set_display_status(f"{action} {label}..."),
        )

    def apply_muted(self, muted: bool) -> bool:
        action = "Muting" if muted else "Unmuting"

        def run_apply() -> bool:
            source = self._display_service().get_default_audio_source()
            return self._display_service().set_muted(muted, source)

        def on_success(applied_muted: bool) -> None:
            message = "Audio muted." if applied_muted else "Audio unmuted."
            self.panel.set_status(message)
            self.refresh_panel_audio()
            self.refresh_display_inventory()
            self.publish_mqtt_snapshot()

        def on_failure(message: str) -> None:
            self.panel.set_status(message)
            self.refresh_panel_audio()
            self.refresh_display_inventory()
            self.notify("XTray", message, error=True)

        return self._start_busy_action(
            run_apply, on_success, on_failure,
            setup=lambda: self.panel.set_status(f"{action} audio output..."),
        )

    def toggle_muted(self) -> bool:
        def run_apply() -> bool:
            source = self._display_service().get_default_audio_source()
            current = self._display_service().get_muted(source)
            return self._display_service().set_muted(not bool(current), source)

        def on_success(applied_muted: bool) -> None:
            message = "Audio muted." if applied_muted else "Audio unmuted."
            self.panel.set_status(message)
            self.refresh_panel_audio()
            self.refresh_display_inventory()
            self.publish_mqtt_snapshot()

        def on_failure(message: str) -> None:
            self.panel.set_status(message)
            self.refresh_panel_audio()
            self.refresh_display_inventory()
            self.notify("XTray", message, error=True)

        return self._start_busy_action(
            run_apply, on_success, on_failure,
            setup=lambda: self.panel.set_status("Toggling audio mute..."),
        )

    def toggle_media_play_pause(self) -> None:
        def run_apply() -> None:
            self._display_service().toggle_media_play_pause()

        def on_success(_result: Any) -> None:
            self.panel.set_status("Play/pause sent.")

        def on_failure(message: str) -> None:
            self.panel.set_status(message)
            self.notify("XTray", message, error=True)

        self._start_busy_action(
            run_apply, on_success, on_failure,
            setup=lambda: self.panel.set_status("Sending play/pause..."),
        )

    def set_start_with_windows(self, checked: bool) -> bool:
        try:
            if checked:
                autostart.enable()
            else:
                autostart.disable()
        except autostart.AutostartError as exc:
            self.notify("XTray", str(exc), error=True)
            return False
        return True

    def open_options(self, initial_section: str = "general") -> None:
        from PySide6.QtCore import Qt  # type: ignore[import-not-found]
        from PySide6.QtWidgets import QDialog  # type: ignore[import-not-found]

        if self._options_dialog is not None and self._options_dialog.dialog.isVisible():
            self._options_dialog.select_section(initial_section)
            self._options_dialog.dialog.raise_()
            self._options_dialog.dialog.activateWindow()
            return

        try:
            autostart_enabled = autostart.is_enabled()
            autostart_available = True
        except autostart.AutostartError:
            autostart_enabled = False
            autostart_available = False
        try:
            tray_options = config.get_tray_options()
        except config.ConfigError:
            tray_options = config.default_tray_options()
        try:
            hotkey_settings = config.get_hotkey_settings()
        except config.ConfigError:
            hotkey_settings = config.default_hotkey_settings()
        try:
            mqtt_settings = config.get_mqtt_settings()
        except config.ConfigError:
            mqtt_settings = config.default_mqtt_settings()
        try:
            experimental_features = config.get_experimental_features()
        except config.ConfigError:
            experimental_features = config.default_experimental_features()
        sync_settings, sync_password_configured = self._load_sync_options()

        dialog = TrayOptionsDialog(
            self.panel.window,
            dark_theme_enabled=self._theme.name == "dark",
            theme_name=self._theme.name,
            start_with_windows_enabled=autostart_enabled,
            start_with_windows_available=autostart_available,
            tray_options=tray_options,
            hotkey_settings=hotkey_settings,
            mqtt_settings=mqtt_settings,
            experimental_features=experimental_features,
            experimental_features_available=config.experimental_feature_available(
                "network_manager_full"
            ),
            sync_settings=sync_settings,
            sync_password_configured=sync_password_configured,
            initial_section=initial_section,
        )
        self._options_dialog = dialog

        def on_theme_changed(_index: int) -> None:
            if not self.set_theme(dialog.selected_theme_name()):
                dialog.reset_theme(self._theme.name)
                return
            dialog.dialog.setStyleSheet(build_app_stylesheet(self._theme))

        def on_startup_toggled(checked: bool) -> None:
            if self.set_start_with_windows(checked):
                return
            try:
                actual = autostart.is_enabled()
            except autostart.AutostartError:
                actual = False
            dialog.reset_start_with_windows(actual)

        def on_finished(result: int) -> None:
            self._set_launcher_button_active("options_button", False)
            self._options_dialog = None
            if result != QDialog.DialogCode.Accepted:
                return
            try:
                saved_tray_options = config.set_tray_options(**dialog.tray_options())
                saved_hotkeys = config.set_hotkey_settings(**dialog.hotkey_settings())
                saved_mqtt = config.set_mqtt_settings(**dialog.mqtt_settings())
                saved_experimental = config.set_experimental_features(
                    **dialog.experimental_features()
                )
                self._save_sync_options(dialog.sync_settings(), dialog.sync_password_text())
            except config.ConfigError as exc:
                self.notify("XTray", str(exc), error=True)
                return
            if (
                saved_experimental != experimental_features
                and self._network_manager_window is not None
            ):
                self._network_manager_window.close()
                self._network_manager_window = None
                self._network_manager_watcher = None
            self.panel.apply_tray_options(saved_tray_options)
            self.panel.apply_integration_options(saved_mqtt)
            self.refresh_profiles()
            self.refresh_active_profile()
            self.refresh_display_inventory()
            self._restart_mqtt_bridge()
            self._restart_ha_state_listener()
            self._restart_sync_runtime()
            self._configure_global_hotkey(saved_hotkeys)
            if saved_mqtt.get("enabled"):
                self.notify("XTray", "Options saved. MQTT bridge restarted.")
            else:
                self.notify("XTray", "Options saved.")

        dialog.theme_combo.currentIndexChanged.connect(on_theme_changed)
        dialog.start_check.toggled.connect(on_startup_toggled)
        dialog.dialog.finished.connect(on_finished)
        dialog.dialog.setWindowModality(Qt.WindowModality.NonModal)
        self._set_launcher_button_active("options_button", True)
        dialog.dialog.show()
        dialog.dialog.raise_()
        dialog.dialog.activateWindow()

    def _load_sync_options(self) -> tuple[dict[str, Any], bool]:
        try:
            from xtray_sync import config as sync_config
        except ImportError:
            return {}, False
        try:
            settings = sync_config.load_sync_settings()
        except Exception as exc:
            app_logging.get_logger("sync").warning("could not load sync settings: %s", exc)
            return {}, False
        return settings.to_dict(), sync_config.password_available()

    def _save_sync_options(
        self,
        settings: dict[str, Any],
        password: str | None,
    ) -> None:
        try:
            from xtray_sync import config as sync_config
        except ImportError as exc:
            if settings.get("enabled"):
                raise config.ConfigError(f"xtray-sync is not installed: {exc}") from exc
            return
        sync_config.set_sync_settings(
            enabled=bool(settings.get("enabled")),
            peer_name=settings.get("peer_name"),
            port=int(settings.get("port") or 37665),
            password=password,
        )

    def _restart_sync_runtime(self) -> None:
        try:
            from xtray_sync.service import SyncRuntime
        except ImportError:
            return
        if self._sync_runtime is None:
            self._sync_runtime = SyncRuntime()
        status = self._sync_runtime.restart()
        if status.enabled and not status.running:
            app_logging.get_logger("sync").info("sync runtime not running: %s", status.reason)

    def open_sync_import(self) -> None:
        from PySide6.QtWidgets import QDialog  # type: ignore[import-not-found]

        if self._sync_import_dialog is not None and self._sync_import_dialog.dialog.isVisible():
            self._sync_import_dialog.dialog.raise_()
            self._sync_import_dialog.dialog.activateWindow()
            return
        try:
            import xtray_sync  # noqa: F401
        except ImportError as exc:
            self.notify("XTray", f"xtray-sync is not installed: {exc}", error=True)
            return
        dialog = LanSyncImportDialog(self.panel.window)
        self._sync_import_dialog = dialog

        def on_finished(result: int) -> None:
            self._sync_import_dialog = None
            if result != QDialog.DialogCode.Accepted:
                return
            peer = dialog.selected_peer()
            password = dialog.sync_password()
            options = dialog.import_options()

            def run_import() -> Any:
                from xtray_sync.client import SyncPeer, import_from_peer

                return import_from_peer(SyncPeer.from_peer(peer), password, options=options)

            def on_success(import_result: Any) -> None:
                self.refresh_profiles(silent=True)
                self.refresh_active_profile(silent=True)
                self.refresh_network_devices()
                backup = import_result.backup_path
                suffix = f" Backup: {backup}" if backup else ""
                if import_result.ok:
                    self.notify("XTray", f"LAN import completed.{suffix}")
                    return
                self.notify(
                    "XTray",
                    "LAN import completed with errors: "
                    + "; ".join(import_result.errors),
                    error=True,
                )

            def on_failure(message: str) -> None:
                self.notify("XTray", f"LAN import failed: {message}", error=True)

            self._start_busy_action(
                run_import,
                on_success,
                on_failure,
                setup=lambda: self.panel.set_status("Importing from LAN PC..."),
            )

        dialog.dialog.finished.connect(on_finished)
        dialog.dialog.show()
        dialog.dialog.raise_()
        dialog.dialog.activateWindow()

    def _set_launcher_button_active(self, attr: str, active: bool) -> None:
        from xtray.core.gui import repolish

        button = getattr(self.panel, attr, None)
        if button is None:
            return
        button.setProperty("popupOpen", bool(active))
        repolish(button)

    def configure_home_assistant(self) -> None:
        self.open_options(initial_section="home_assistant")

    def set_dark_theme(self, checked: bool) -> bool:
        return self.set_theme("dark" if checked else DEFAULT_THEME.name)

    def set_theme(self, theme_name: str) -> bool:
        try:
            config.set_theme_name(theme_name)
        except config.ConfigError as exc:
            self.notify("XTray", str(exc), error=True)
            return False
        self._theme = theme_by_name(theme_name)
        self.panel.set_theme(self._theme)
        self.tray.setIcon(_app_icon(self._theme))
        if self._network_manager_window is not None:
            self._network_manager_window.setStyleSheet(build_app_stylesheet(self._theme))
        return True

    def _configure_global_hotkey(self, settings: dict[str, Any] | None = None) -> None:
        try:
            hotkeys = settings or config.get_hotkey_settings()
        except config.ConfigError as exc:
            app_logging.get_logger("tray").warning("invalid hotkey settings: %s", exc)
            return
        if self._hotkey_manager is not None:
            self._hotkey_manager.clear()
        if not hotkeys.get("toggle_panel_enabled"):
            return
        if sys.platform != "win32":
            app_logging.get_logger("tray").debug("global hotkey skipped outside Windows")
            return
        if self._hotkey_manager is None:
            self._hotkey_manager = GlobalHotkeyManager(self.app, self.toggle_panel)
        try:
            parsed = self._hotkey_manager.register_toggle_hotkey(
                str(hotkeys.get("toggle_panel") or "Ctrl+Alt+X")
            )
        except HotkeyError as exc:
            app_logging.get_logger("tray").warning("global hotkey registration failed: %s", exc)
            self.notify("XTray", str(exc), error=True)
            return
        app_logging.get_logger("tray").info("registered global hotkey: %s", parsed.sequence)

    def open_gui(self) -> None:
        app_logging.get_logger("tray").info("launching Computer Manager")
        if getattr(sys, "frozen", False):
            ok = self._qprocess.startDetached(sys.executable, ["--gui"])
        else:
            ok = self._qprocess.startDetached(
                autostart.consoleless_python_runtime(),
                ["-m", "computer_manager.app"],
            )
        if not ok:
            app_logging.get_logger("tray").warning("failed to launch Computer Manager")
            self.notify(
                "XTray",
                "Could not launch Computer Manager.",
                error=True,
            )

    def open_network_manager(self) -> None:
        if self._network_manager_window is None:
            try:
                from network_manager.app import MainWindow as NetworkManagerWindow
            except ImportError as exc:
                app_logging.get_logger("tray").exception("Network Manager unavailable")
                self.notify("Network Manager unavailable", str(exc))
                return
            app_logging.get_logger("tray").info("opening embedded Network Manager window")
            self._network_manager_window = NetworkManagerWindow()
            qt_assets.set_window_icon(self._network_manager_window)
            self._install_network_manager_visibility_watcher()
        if hasattr(self._network_manager_window, "device_page"):
            self._attach_network_manager_device_refresh()
            self._network_manager_window.device_page.refresh_devices()
        self._network_manager_window.show()
        self._network_manager_window.raise_()
        self._network_manager_window.activateWindow()

    def _install_network_manager_visibility_watcher(self) -> None:
        from PySide6.QtCore import QEvent, QObject  # type: ignore[import-not-found]

        if self._network_manager_window is None or self._network_manager_watcher is not None:
            return

        controller = self

        class _VisibilityWatcher(QObject):
            def eventFilter(self, _obj: Any, event: Any) -> bool:  # noqa: N802 - Qt signature
                event_type = event.type()
                if event_type in (QEvent.Type.Show, QEvent.Type.ShowToParent):
                    controller._set_launcher_button_active("network_manage_button", True)
                elif event_type in (QEvent.Type.Hide, QEvent.Type.Close, QEvent.Type.HideToParent):
                    controller._set_launcher_button_active("network_manage_button", False)
                return False

        watcher = _VisibilityWatcher()
        self._network_manager_window.installEventFilter(watcher)
        self._network_manager_watcher = watcher

    def _attach_network_manager_device_refresh(self) -> None:
        if self._network_manager_window is None:
            return
        device_page = getattr(self._network_manager_window, "device_page", None)
        if device_page is None:
            return
        current_callback = getattr(device_page, "on_devices_changed", None)
        installed_callback = getattr(device_page, "_xtray_on_devices_changed", None)
        if installed_callback is not None and current_callback is installed_callback:
            return

        def on_devices_changed() -> None:
            if callable(current_callback):
                current_callback()
            self.refresh_network_devices()

        device_page.on_devices_changed = on_devices_changed
        device_page._xtray_on_devices_changed = on_devices_changed

    def ping_network_device(self, device: network.NetworkDevice) -> None:
        self.panel.set_network_status(f"Pinging {device.name}...")

        def run_ping() -> network.NetworkStatus:
            return network.ping_device(device)

        def on_success(status: network.NetworkStatus) -> None:
            self.panel.update_network_status(status)

        def on_failure(message: str) -> None:
            self.panel.set_network_status(message)

        self._run_in_thread(run_ping, on_success, on_failure, lambda: None)

    def open_network_device(self, device: network.NetworkDevice) -> None:
        webbrowser.open(device.web_url())

    def _reload_tray_options(self) -> None:
        try:
            options = config.get_tray_options()
        except config.ConfigError as exc:
            app_logging.get_logger("tray").warning("invalid tray options: %s", exc)
        else:
            # apply_tray_options() rebuilds every tab and reflows the
            # profile grid; skip the call when nothing changed so reopening
            # the panel doesn't repeatedly tear down and rebuild widgets.
            if options != getattr(self.panel, "_tray_options", None):
                self.panel.apply_tray_options(options)
        self._reload_integration_options()

    def _reload_integration_options(self) -> None:
        try:
            settings = config.get_mqtt_settings()
        except config.ConfigError as exc:
            app_logging.get_logger("tray").warning("invalid MQTT settings: %s", exc)
            settings = config.default_mqtt_settings()
        self.panel.apply_integration_options(settings)

    def apply_adapter_enabled(self, adapter: Any, enabled: bool) -> None:
        action = "Enabling" if enabled else "Disabling"

        def run_apply() -> None:
            self._adapter_service.set_adapter_enabled(adapter, enabled)

        def on_success(_result: None) -> None:
            self.panel.set_adapters_status(f"{adapter.name}: change applied.")
            self.refresh_adapters()
            self.notify("XTray", f"{adapter.name}: adapter change applied.")

        def on_failure(message: str) -> None:
            self.panel.set_adapters_status(message)
            self.refresh_adapters()
            self.notify("XTray", message, error=True)

        self._start_busy_action(
            run_apply, on_success, on_failure,
            setup=lambda: self.panel.set_adapters_status(f"{action} {adapter.name}..."),
        )

    def open_adapter_info(self, adapter: Any) -> None:
        dialog = AdapterInfoDialog(adapter, self.panel.window)
        if not dialog.exec():
            return
        self.apply_adapter_ip_settings(adapter, dialog.ip_settings())

    def open_adapter_properties(self, adapter: Any) -> None:
        try:
            self._adapter_service.open_adapter_properties(adapter)
        except Exception as exc:
            self.panel.set_adapters_status(str(exc))

    def open_network_connections(self) -> None:
        try:
            self._adapter_service.open_network_connections()
        except Exception as exc:
            self.panel.set_adapters_status(str(exc))
            self.notify("XTray", str(exc), error=True)

    def apply_adapter_ip_settings(self, adapter: Any, settings: AdapterIpSettings) -> None:
        mode = "DHCP" if settings.dhcp_enabled else "static IP"

        def run_apply() -> None:
            self._adapter_service.set_ip_settings(adapter, settings)

        def on_success(_result: None) -> None:
            self.panel.set_adapters_status(f"{adapter.name}: {mode} settings applied.")
            self.refresh_adapters()
            self.notify("XTray", f"{adapter.name}: network settings applied.")

        def on_failure(message: str) -> None:
            self.panel.set_adapters_status(message)
            self.refresh_adapters()
            self.notify("XTray", message, error=True)

        self._start_busy_action(
            run_apply, on_success, on_failure,
            setup=lambda: self.panel.set_adapters_status(
                f"Applying {mode} settings to {adapter.name}..."
            ),
        )

    def open_drive(self, drive: Any) -> None:
        try:
            self._drive_service.open_drive(drive)
        except Exception as exc:
            self.notify("XTray", f"Could not open drive {drive.letter}: {exc}", error=True)

    def open_add_network_drive(self) -> None:
        dialog = NetworkDriveDialog(self.panel.window)
        if not dialog.exec():
            return
        self.map_network_drive(dialog.mapping())

    def map_network_drive(self, mapping: dict[str, Any]) -> None:
        letter = str(mapping.get("letter") or "").strip().rstrip(":").upper()

        def run_apply() -> None:
            self._drive_service.map_network_drive(**mapping)

        def on_success(_result: None) -> None:
            self.panel.set_drives_status(f"Drive {letter}: mapped.")
            self.refresh_drives()
            self.notify("XTray", f"Drive {letter}: mapped.")

        def on_failure(message: str) -> None:
            self.panel.set_drives_status(message)
            self.refresh_drives()
            self.notify("XTray", message, error=True)

        self._start_busy_action(
            run_apply, on_success, on_failure,
            setup=lambda: self.panel.set_drives_status(f"Mapping drive {letter}:..."),
        )

    def shutdown_windows(self) -> None:
        if sys.platform != "win32":
            self.notify("XTray", "Shutdown is only available on Windows.", error=True)
            return
        try:
            subprocess.Popen(["shutdown", "/s", "/t", "0"], shell=False)
        except OSError as exc:
            self.notify("XTray", f"Could not start shutdown: {exc}", error=True)

    def quit(self) -> None:
        app_logging.get_logger("tray").info("tray clean quit requested")
        self._closing = True
        if self._hotkey_manager is not None:
            self._hotkey_manager.close()
            self._hotkey_manager = None
        self._stop_audio_polling()
        self._stop_volume_listener()
        self._stop_endpoint_listener()
        self._stop_ha_state_listener()
        self._stop_sync_runtime()
        self._stop_mqtt_bridge()
        self._ha_status_timer.stop()
        self._wait_for_workers()
        self.tray.hide()
        self.panel.close()
        if self._network_manager_window is not None:
            self._network_manager_window.close()
        app_logging.mark_clean_shutdown("tray")
        self.app.quit()

    def restart(self) -> None:
        """Re-launch the tray process with the same arguments, then quit.

        Used to pick up source-folder updates without manually quitting the
        tray.
        """
        app_logging.get_logger("tray").info("tray restart requested")
        cli_args = list(sys.argv[1:])
        if getattr(sys, "frozen", False):
            # PyInstaller / similar frozen executable
            program = sys.executable
            args = cli_args
        else:
            # Avoid relying on sys.argv[0], which on Windows console_scripts
            # entry points (e.g. `xtray-tray`) lacks the `.exe` extension and
            # cannot be re-launched via python.exe. `-m xtray.tray` is stable
            # regardless of how the process was originally started.
            program = autostart.consoleless_python_runtime()
            args = ["-m", "xtray.tray", *cli_args]
        # Release the single-instance lock and the global hotkey BEFORE spawning
        # the replacement: otherwise the new process either bounces off the
        # single-instance guard or fails to register Ctrl+Alt+X because the old
        # process still holds it.
        self._release_for_restart()
        ok = self._qprocess.startDetached(program, args)
        if not ok:
            app_logging.get_logger("tray").warning("failed to start replacement tray process")
            self.notify(
                "XTray",
                "Could not start a new tray process — restart aborted.",
                error=True,
            )
            return
        self.quit()

    def _release_for_restart(self) -> None:
        self._closing = True
        if self._hotkey_manager is not None:
            self._hotkey_manager.close()
            self._hotkey_manager = None
        self._stop_audio_polling()
        self._stop_volume_listener()
        self._stop_endpoint_listener()
        self._stop_ha_state_listener()
        self._stop_sync_runtime()
        lock = getattr(self.app, "_xtray_single_instance", None)
        if lock is not None:
            lock.detach()
            try:
                delattr(self.app, "_xtray_single_instance")
            except AttributeError:
                pass

    def _stop_sync_runtime(self) -> None:
        if self._sync_runtime is None:
            return
        try:
            self._sync_runtime.stop()
        except Exception:
            app_logging.get_logger("sync").debug("sync runtime stop failed", exc_info=True)
        self._sync_runtime = None

    def _wait_for_workers(self) -> None:
        self._threads.wait_for_workers()

    def notify(
        self,
        title: str,
        message: str,
        *,
        error: bool = False,
        icon: str | None = None,
    ) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon  # type: ignore[import-not-found]

        if icon:
            custom = icons.qicon_for(icon, color=self._theme.tray.accent)
            if not custom.isNull():
                self.tray.showMessage(title, message, custom, 5000)
                return
        fallback = (
            QSystemTrayIcon.MessageIcon.Warning
            if error
            else QSystemTrayIcon.MessageIcon.Information
        )
        self.tray.showMessage(title, message, fallback, 5000)

    def _position_panel(self, *, anchor_to_tray: bool = False) -> None:
        if not self._panel_is_available():
            return
        if self.panel.has_user_geometry():
            return
        if self.panel.isVisible() and not anchor_to_tray:
            return
        from PySide6.QtGui import QCursor, QGuiApplication  # type: ignore[import-not-found]

        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        rect = screen.availableGeometry()
        self.panel.adjustSize()
        width = max(self.panel.width(), self.panel.sizeHint().width())
        height = max(self.panel.height(), self.panel.sizeHint().height())
        margin = 16
        self.panel.move(rect.right() - width - margin, rect.bottom() - height - margin)

    def _run_in_thread(
        self,
        target: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_failure: Callable[[str], None],
        cleanup: Callable[[], None],
    ) -> None:
        if self._is_closing():
            return

        def guarded_success(result: Any) -> None:
            if self._is_closing():
                return
            on_success(result)

        def guarded_failure(message: str) -> None:
            if self._is_closing():
                return
            on_failure(message)

        def guarded_cleanup() -> None:
            if self._is_closing():
                return
            cleanup()

        self._threads.run(target, guarded_success, guarded_failure, guarded_cleanup)

    def _start_busy_action(
        self,
        run_apply: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_failure: Callable[[str], None],
        *,
        set_busy_kwargs: dict[str, Any] | None = None,
        setup: Callable[[], None] | None = None,
    ) -> bool:
        """Common scaffolding for the apply_* methods.

        Returns False if a busy action is already in flight (the caller
        should bail out). Otherwise sets the panel busy, calls `setup` for
        any initial status text, runs `run_apply` in a worker thread, and
        clears the busy state when the thread finishes.
        """
        if self._busy:
            return False
        self._busy = True
        self.panel.set_busy(True, **(set_busy_kwargs or {}))
        if setup is not None:
            setup()

        def cleanup() -> None:
            self._busy = False
            self.panel.set_busy(False)

        self._run_in_thread(run_apply, on_success, on_failure, cleanup)
        return True

    def _display_service(self) -> DisplayService:
        service = getattr(self, "_service", None)
        if service is None:
            service = DisplayService()
            self._service = service
        return service
