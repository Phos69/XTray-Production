"""JSON-RPC backend used by the native tray shell.

The backend intentionally keeps the Python process as the owner of XTray's
existing settings, sync, updater, display, adapter, drive, and network service
logic. A native tray can talk to it over newline-delimited JSON without
importing Qt or PySide.
"""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
import webbrowser
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from collections.abc import Callable, Iterable, Mapping
from importlib import resources
from pathlib import Path
from typing import Any, TextIO

from . import __version__, config, updater
from .core import app_logging, icons
from .core.theme import theme_by_name
from .core.computer_models import DriveInfo, NetworkAdapter
from .services import AdapterService, DisplayService, DriveService, NetworkService
from .services.display import audio as audio_backend
from .services.display import display as display_backend


Handler = Callable[[Mapping[str, Any]], Any]


class BackendError(RuntimeError):
    """Raised for client-facing backend errors."""


class XTrayBackend:
    """Command adapter exposed to the native tray through JSON-RPC."""

    def __init__(
        self,
        *,
        display_service: DisplayService | None = None,
        adapter_service: AdapterService | None = None,
        drive_service: DriveService | None = None,
        network_service: NetworkService | None = None,
    ) -> None:
        self.display_service = display_service or DisplayService()
        self.adapter_service = adapter_service or AdapterService()
        self.drive_service = drive_service or DriveService()
        self.network_service = network_service or NetworkService()
        self._executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="xtray-backend",
        )
        self._cache: dict[str, Any] = {}
        self._inflight: dict[str, Future[Any]] = {}
        self._handlers: dict[str, Handler] = {
            "app.health": self._health,
            "app.paths": self._paths,
            "app.open_logs": self._open_logs,
            "app.open_computer_manager": self._open_computer_manager,
            "app.open_network_manager": self._open_network_manager,
            "diagnostics.bundle": self._diagnostics_bundle,
            "assets.svg": self._assets_svg,
            "tray.snapshot": self._snapshot,
            "tray.adapters": self._adapters,
            "tray.drives": self._drives,
            "settings.get": self._settings,
            "settings.update_theme": self._update_theme,
            "settings.update_tray_options": self._update_tray_options,
            "settings.update_hotkeys": self._update_hotkeys,
            "settings.update_mqtt": self._update_mqtt,
            "settings.update_experimental": self._update_experimental,
            "profiles.apply": self._apply_profile,
            "audio.set_volume": self._set_audio_volume,
            "audio.set_muted": self._set_audio_muted,
            "audio.set_source": self._set_audio_source,
            "audio.toggle_media_play_pause": self._toggle_media_play_pause,
            "display.set_monitor_volume": self._set_display_monitor_volume,
            "display.set_hdmi_volume_exposed": self._set_hdmi_volume_exposed,
            "display.set_enabled": self._set_display_enabled,
            "display.set_primary": self._set_display_primary,
            "display.call_power_service": self._call_display_power_service,
            "network.open_device": self._open_network_device,
            "adapter.open_network_connections": self._open_network_connections,
            "adapter.open_properties": self._open_adapter_properties,
            "adapter.set_enabled": self._set_adapter_enabled,
            "drive.open": self._open_drive,
            "drive.map_network": self._map_network_drive,
            "sync.status": self._sync_status,
            "sync.configure": self._sync_configure,
            "sync.peers": self._sync_peers,
            "sync.import": self._sync_import,
            "updates.check": self._updates_check,
            "updates.download_install": self._updates_download_install,
        }

    def handle(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        handler = self._handlers.get(method)
        if handler is None:
            raise BackendError(f"unknown method: {method}")
        return handler(params or {})

    def _health(self, _params: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "version": __version__,
            "pid": os.getpid(),
            "frozen": bool(getattr(sys, "frozen", False)),
        }

    def _paths(self, _params: Mapping[str, Any]) -> dict[str, Any]:
        return _paths_payload()

    def _open_logs(self, _params: Mapping[str, Any]) -> dict[str, Any]:
        _open_path(config.log_dir())
        return {"opened": str(config.log_dir())}

    def _open_computer_manager(self, _params: Mapping[str, Any]) -> dict[str, Any]:
        _launch_backend_mode("computer-manager")
        return {"launched": "computer-manager"}

    def _open_network_manager(self, _params: Mapping[str, Any]) -> dict[str, Any]:
        _launch_backend_mode("network-manager")
        return {"launched": "network-manager"}

    def _diagnostics_bundle(self, _params: Mapping[str, Any]) -> dict[str, Any]:
        path = app_logging.create_diagnostics_bundle(component="backend")
        return {"path": str(path)}

    def _snapshot(self, _params: Mapping[str, Any]) -> dict[str, Any]:
        favorites = _safe_call(self.display_service.list_favorite_profiles, [])
        icons = _safe_call(self.display_service.list_favorite_profile_icons, {})
        missing = _safe_call(
            lambda: self.display_service.profiles_missing_displays(favorites),
            {},
        )
        return {
            "version": __version__,
            "paths": _paths_payload(),
            "settings": self._settings({}),
            "profiles": {
                "favorites": favorites,
                "active": _safe_call(
                    lambda: self.display_service.detect_current_favorite_profile(favorites),
                    None,
                ),
                "icons": icons,
                "missing_displays": missing,
            },
            "audio": _safe_call(self.display_service.load_audio_panel_state, None),
            "displays": _safe_call(self.display_service.list_display_inventory, []),
            "network": {
                "devices": self._cached_call(
                    "network.devices",
                    self.network_service.list_devices,
                    [],
                    timeout_seconds=0.3,
                ),
                "local_adapter_mac": _safe_call(self.network_service.local_adapter_mac, None),
            },
            "adapters": self._adapters({}),
            "drives": self._drives({}),
            "sync": self._sync_status({}),
        }

    def _adapters(self, _params: Mapping[str, Any]) -> Any:
        return self._cached_call(
            "adapters",
            self.adapter_service.list_adapters,
            [],
            timeout_seconds=0.3,
        )

    def _drives(self, _params: Mapping[str, Any]) -> Any:
        return self._cached_call(
            "drives",
            self.drive_service.list_drives,
            [],
            timeout_seconds=0.3,
        )

    def _cached_call(
        self,
        key: str,
        func: Callable[[], Any],
        fallback: Any,
        *,
        timeout_seconds: float,
    ) -> Any:
        future = self._inflight.get(key)
        if future is None or future.done():
            if future is not None and future.done():
                try:
                    self._cache[key] = future.result()
                except Exception as exc:
                    app_logging.get_logger("backend").warning(
                        "cached backend call failed: %s",
                        exc,
                    )
            future = self._executor.submit(func)
            self._inflight[key] = future
        try:
            result = future.result(timeout=timeout_seconds)
        except FutureTimeoutError:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            return {"error": f"{key} is still refreshing", "value": fallback}
        except Exception as exc:
            app_logging.get_logger("backend").warning("backend call failed: %s", exc)
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            return {"error": str(exc), "value": fallback}
        self._cache[key] = result
        return result

    def _settings(self, _params: Mapping[str, Any]) -> dict[str, Any]:
        mqtt = _safe_call(config.get_mqtt_settings, config.default_mqtt_settings())
        theme_name = _safe_call(config.get_theme_name, "vibrant")
        return {
            "theme": theme_name,
            "theme_names": list(config.THEME_NAMES),
            "theme_data": _theme_payload(str(theme_name)),
            "tray_options": _safe_call(config.get_tray_options, config.default_tray_options()),
            "hotkeys": _safe_call(config.get_hotkey_settings, config.default_hotkey_settings()),
            "mqtt": config.redact_mqtt_settings(mqtt),
            "experimental_features": _safe_call(
                config.get_experimental_features,
                config.default_experimental_features(),
            ),
        }

    def _assets_svg(self, params: Mapping[str, Any]) -> dict[str, Any]:
        ids = params.get("ids")
        if not isinstance(ids, list):
            raise BackendError("ids must be a list")
        payload: dict[str, str] = {}
        missing: list[str] = []
        for raw_id in ids:
            asset_id = str(raw_id or "").strip()
            if not asset_id:
                continue
            svg = _svg_asset_text(asset_id)
            if svg is None:
                missing.append(asset_id)
            else:
                payload[asset_id] = svg
        return {"icons": payload, "missing": missing}

    def _update_theme(self, params: Mapping[str, Any]) -> str:
        return config.set_theme_name(_required_str(params, "theme"))

    def _update_tray_options(self, params: Mapping[str, Any]) -> dict[str, Any]:
        updates = _required_mapping(params, "updates")
        return config.set_tray_options(**dict(updates))

    def _update_hotkeys(self, params: Mapping[str, Any]) -> dict[str, Any]:
        updates = _required_mapping(params, "updates")
        return config.set_hotkey_settings(**dict(updates))

    def _update_mqtt(self, params: Mapping[str, Any]) -> dict[str, Any]:
        updates = _required_mapping(params, "updates")
        settings = config.set_mqtt_settings(**dict(updates))
        return config.redact_mqtt_settings(settings)

    def _update_experimental(self, params: Mapping[str, Any]) -> dict[str, Any]:
        updates = _required_mapping(params, "updates")
        return config.set_experimental_features(**dict(updates))

    def _apply_profile(self, params: Mapping[str, Any]) -> Any:
        return self.display_service.apply_profile(_required_str(params, "name"))

    def _set_audio_volume(self, params: Mapping[str, Any]) -> int:
        return self.display_service.set_volume(
            _bounded_percent(params.get("percent")),
            _audio_source_from_params(params),
        )

    def _set_audio_muted(self, params: Mapping[str, Any]) -> bool:
        return self.display_service.set_muted(
            _bool_param(params, "muted"),
            _audio_source_from_params(params),
        )

    def _set_audio_source(self, params: Mapping[str, Any]) -> Any:
        source = _audio_source_from_params(params, required=True)
        return self.display_service.set_audio_source(source)

    def _toggle_media_play_pause(self, _params: Mapping[str, Any]) -> dict[str, bool]:
        self.display_service.toggle_media_play_pause()
        return {"ok": True}

    def _set_display_monitor_volume(self, params: Mapping[str, Any]) -> int | None:
        target = _display_state_from_params(params)
        return self.display_service.set_display_monitor_volume(
            target,
            _bounded_percent(params.get("percent")),
        )

    def _set_hdmi_volume_exposed(self, params: Mapping[str, Any]) -> dict[str, bool]:
        target = _display_state_from_params(params)
        self.display_service.set_display_hdmi_volume_exposed(
            target,
            _bool_param(params, "exposed"),
        )
        return {"ok": True}

    def _set_display_enabled(self, params: Mapping[str, Any]) -> Any:
        target = _display_state_from_params(params)
        return self.display_service.set_display_enabled(target, _bool_param(params, "enabled"))

    def _set_display_primary(self, params: Mapping[str, Any]) -> Any:
        return self.display_service.set_display_primary(_display_state_from_params(params))

    def _call_display_power_service(self, params: Mapping[str, Any]) -> str:
        return self.display_service.call_display_power_service(
            _display_state_from_params(params),
            turn_on=_bool_param(params, "turn_on"),
        )

    def _open_network_device(self, params: Mapping[str, Any]) -> dict[str, str]:
        url = _required_str(params, "url")
        webbrowser.open(url)
        return {"opened": url}

    def _open_network_connections(self, _params: Mapping[str, Any]) -> dict[str, bool]:
        self.adapter_service.open_network_connections()
        return {"ok": True}

    def _open_adapter_properties(self, params: Mapping[str, Any]) -> dict[str, bool]:
        self.adapter_service.open_adapter_properties(_adapter_from_params(params))
        return {"ok": True}

    def _set_adapter_enabled(self, params: Mapping[str, Any]) -> dict[str, bool]:
        self.adapter_service.set_adapter_enabled(
            _adapter_from_params(params),
            _bool_param(params, "enabled"),
        )
        return {"ok": True}

    def _open_drive(self, params: Mapping[str, Any]) -> dict[str, bool]:
        self.drive_service.open_drive(_drive_from_params(params))
        return {"ok": True}

    def _map_network_drive(self, params: Mapping[str, Any]) -> dict[str, bool]:
        mapping = _required_mapping(params, "mapping")
        self.drive_service.map_network_drive(**dict(mapping))
        return {"ok": True}

    def _sync_status(self, _params: Mapping[str, Any]) -> dict[str, Any]:
        try:
            from xtray_sync import config as sync_config
        except ImportError:
            return {"enabled": False, "ready": False, "available": False}
        status = sync_config.status_summary()
        status["available"] = True
        return status

    def _sync_configure(self, params: Mapping[str, Any]) -> dict[str, Any]:
        try:
            from xtray_sync import config as sync_config
        except ImportError as exc:
            raise BackendError("xtray_sync is not installed") from exc
        updates = {
            "enabled": params.get("enabled") if "enabled" in params else None,
            "peer_name": params.get("peer_name") if "peer_name" in params else None,
            "port": params.get("port") if "port" in params else None,
            "discovery_port": params.get("discovery_port")
            if "discovery_port" in params
            else None,
            "password": params.get("password") if "password" in params else None,
        }
        return sync_config.set_sync_settings(**updates).to_dict()

    def _sync_peers(self, params: Mapping[str, Any]) -> list[Any]:
        try:
            from xtray_sync import discovery
        except ImportError as exc:
            raise BackendError("xtray_sync is not installed") from exc
        timeout = float(params.get("timeout", 2.0))
        return discovery.discover_peers(timeout=timeout)

    def _sync_import(self, params: Mapping[str, Any]) -> Any:
        try:
            from xtray_sync import bundle, client, config as sync_config, discovery
        except ImportError as exc:
            raise BackendError("xtray_sync is not installed") from exc
        peers = discovery.discover_peers(timeout=float(params.get("timeout", 2.0)))
        target = params.get("target")
        peer = client.peer_from_discovery_target(str(target) if target else None, peers)
        password = str(params.get("password") or sync_config.get_password() or "")
        if not password:
            raise BackendError("sync password is not configured")
        options_payload = params.get("options")
        options = (
            bundle.ImportOptions(**dict(options_payload))
            if isinstance(options_payload, dict)
            else None
        )
        return client.import_from_peer(peer, password, options=options)

    def _updates_check(self, params: Mapping[str, Any]) -> dict[str, Any] | None:
        return updater.check_for_update(
            include_prereleases=bool(params.get("include_prereleases", False))
        )

    def _updates_download_install(self, params: Mapping[str, Any]) -> dict[str, Any]:
        update_payload = _required_mapping(params, "update")
        asset_payload = _required_mapping(update_payload, "asset")
        update = updater.UpdateInfo(
            version=_required_str(update_payload, "version"),
            release_url=str(update_payload.get("release_url") or ""),
            title=str(update_payload.get("title") or ""),
            published_at=str(update_payload.get("published_at") or ""),
            asset=updater.ReleaseAsset(
                name=_required_str(asset_payload, "name"),
                download_url=_required_str(asset_payload, "download_url"),
                size=asset_payload.get("size")
                if isinstance(asset_payload.get("size"), int)
                else None,
            ),
        )
        installer = updater.download_update_installer(update)
        helper = updater.start_update_installer(installer)
        return {"installer": str(installer), "helper": str(helper)}


def serve_jsonrpc(
    backend: XTrayBackend | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    """Serve newline-delimited JSON requests until EOF."""

    backend = backend or XTrayBackend()
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        if not line.strip():
            continue
        response = _handle_line(backend, line)
        stdout.write(json.dumps(response, ensure_ascii=False, default=_to_jsonable) + "\n")
        stdout.flush()
    return 0


def _handle_line(backend: XTrayBackend, line: str) -> dict[str, Any]:
    try:
        request = json.loads(line)
        if not isinstance(request, dict):
            raise BackendError("request must be an object")
        request_id = request.get("id")
        method = request.get("method")
        if not isinstance(method, str) or not method.strip():
            raise BackendError("method is required")
        params = request.get("params")
        if params is None:
            params = {}
        if not isinstance(params, Mapping):
            raise BackendError("params must be an object")
        result = backend.handle(method.strip(), params)
        return {"id": request_id, "ok": True, "result": _to_jsonable(result)}
    except Exception as exc:
        app_logging.get_logger("backend").exception("JSON-RPC request failed")
        return {
            "id": request.get("id") if isinstance(locals().get("request"), dict) else None,
            "ok": False,
            "error": {
                "code": "backend_error",
                "message": str(exc),
                "type": type(exc).__name__,
            },
        }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    app_logging.configure_logging()
    if "--cli" in args:
        cli_args = [arg for arg in args if arg != "--cli"]
        from xtray.cli import main as cli_main

        return int(
            cli_main(args=cli_args, prog_name="xtray", standalone_mode=True) or 0
        )
    if args[:2] == ["--launch", "computer-manager"]:
        from computer_manager.app import main as computer_manager_main

        computer_manager_main()
        return 0
    if args[:2] == ["--launch", "network-manager"]:
        from network_manager.gui_entry import main as network_manager_main

        network_manager_main()
        return 0
    return serve_jsonrpc()


def _paths_payload() -> dict[str, str]:
    return {
        "config_dir": str(config.config_dir()),
        "data_dir": str(config.data_dir()),
        "profiles_dir": str(config.profiles_dir()),
        "log_dir": str(config.log_dir()),
        "settings_path": str(config.settings_path()),
    }


def _theme_payload(theme_name: str) -> dict[str, Any]:
    return dataclasses.asdict(theme_by_name(theme_name))


_APP_SVG_ASSETS = {
    "xtray_nav_icon": "assets/xtray_nav_icon.svg",
    "xtray_tray_glyph": "assets/xtray_tray_glyph.svg",
    "xtray_minimal_logo": "assets/xtray_minimal_logo.svg",
    "homeassistant_logo": "assets/homeassistant_logo.svg",
    "mqtt_logo": "assets/mqtt_logo.svg",
}


def _svg_asset_text(asset_id: str) -> str | None:
    normalized = asset_id.strip()
    if normalized.startswith("mdi:"):
        path = icons.icon_path(normalized)
        if path is None:
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None
    if not normalized.startswith("asset:"):
        return None
    name = normalized.removeprefix("asset:").strip()
    relative_path = _APP_SVG_ASSETS.get(name)
    if relative_path is None:
        return None
    try:
        return resources.files("xtray").joinpath(relative_path).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        fallback = Path(__file__).resolve().parent / Path(relative_path)
        try:
            return fallback.read_text(encoding="utf-8")
        except OSError:
            return None


def _safe_call(func: Callable[[], Any], fallback: Any) -> Any:
    try:
        return func()
    except Exception as exc:
        app_logging.get_logger("backend").warning("backend snapshot call failed: %s", exc)
        return {"error": str(exc), "value": fallback} if fallback is not None else {"error": str(exc)}


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        data = _dataclass_to_jsonable(value)
        return _augment_known_model(value, data)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        data = _to_jsonable(value.to_dict())
        return _augment_known_model(value, data) if isinstance(data, dict) else data
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(child) for key, child in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_jsonable(child) for child in value]
    return str(value)


def _dataclass_to_jsonable(value: Any) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for field in dataclasses.fields(value):
        child = getattr(value, field.name)
        if field.name == "source_labels" and isinstance(child, Mapping):
            data[field.name] = [
                {"source": _to_jsonable(source), "label": _to_jsonable(label)}
                for source, label in child.items()
            ]
            continue
        data[field.name] = _to_jsonable(child)
    return data


def _augment_known_model(value: Any, data: dict[str, Any]) -> dict[str, Any]:
    if hasattr(value, "path"):
        data.setdefault("path", _safe_attr(value, "path"))
    if hasattr(value, "open_target"):
        data.setdefault("open_target", _safe_attr(value, "open_target"))
    if hasattr(value, "used_percent"):
        data.setdefault("used_percent", _safe_attr(value, "used_percent"))
    if hasattr(value, "enabled"):
        data.setdefault("enabled", _safe_attr(value, "enabled"))
    if hasattr(value, "primary_ipv4"):
        data.setdefault("primary_ipv4", _safe_attr(value, "primary_ipv4"))
    if hasattr(value, "primary_prefix_length"):
        data.setdefault(
            "primary_prefix_length",
            _safe_attr(value, "primary_prefix_length"),
        )
    if hasattr(value, "web_url") and callable(value.web_url):
        try:
            data.setdefault("web_url", value.web_url())
        except Exception:
            pass
    if hasattr(value, "label") and callable(value.label):
        try:
            data.setdefault("label", value.label())
        except Exception:
            pass
    return data


def _safe_attr(value: Any, name: str) -> Any:
    try:
        return _to_jsonable(getattr(value, name))
    except Exception:
        return None


def _audio_source_from_params(
    params: Mapping[str, Any],
    *,
    required: bool = False,
) -> Any | None:
    value = params.get("source")
    if value is None:
        if required:
            raise BackendError("source is required")
        return None
    if not isinstance(value, dict):
        raise BackendError("source must be an object")
    if hasattr(audio_backend.AudioSource, "from_dict"):
        return audio_backend.AudioSource.from_dict(value)
    return audio_backend.AudioSource(
        name=_required_str(value, "name"),
        endpoint_id=value.get("endpoint_id"),
        interface_name=value.get("interface_name"),
        role=str(value.get("role") or "multimedia"),
        state=value.get("state"),
    )


def _display_state_from_params(params: Mapping[str, Any]) -> Any:
    value = params.get("display")
    if not isinstance(value, dict):
        raise BackendError("display is required")
    return display_backend.DisplayState.from_dict(value)


def _adapter_from_params(params: Mapping[str, Any]) -> NetworkAdapter:
    value = params.get("adapter")
    if not isinstance(value, dict):
        raise BackendError("adapter is required")
    return NetworkAdapter.from_dict(value)


def _drive_from_params(params: Mapping[str, Any]) -> DriveInfo:
    value = params.get("drive")
    if not isinstance(value, dict):
        raise BackendError("drive is required")
    return DriveInfo.from_dict(value)


def _required_mapping(params: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = params.get(key)
    if not isinstance(value, Mapping):
        raise BackendError(f"{key} must be an object")
    return value


def _required_str(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BackendError(f"{key} is required")
    return value.strip()


def _bool_param(params: Mapping[str, Any], key: str) -> bool:
    value = params.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y", "on"}


def _bounded_percent(value: Any) -> int:
    try:
        percent = int(value)
    except (TypeError, ValueError) as exc:
        raise BackendError("percent must be an integer") from exc
    if not 0 <= percent <= 100:
        raise BackendError("percent must be between 0 and 100")
    return percent


def _open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
        return
    webbrowser.open(path.as_uri())


def _launch_backend_mode(mode: str) -> None:
    cmd = _self_command(["--launch", mode])
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(cmd, close_fds=True, creationflags=creationflags)


def _self_command(extra_args: Iterable[str]) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *extra_args]
    return [sys.executable, "-m", "xtray.backend_jsonrpc", *extra_args]


if __name__ == "__main__":
    raise SystemExit(main())
