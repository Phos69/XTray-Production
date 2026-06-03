"""Runtime logging helpers shared by XTray and compatibility shims."""
from __future__ import annotations

import atexit
import faulthandler
import importlib
import json
import logging
import os
import platform
import re
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import ModuleType
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

LOGGER_NAME = "xtray"
_HANDLER_NAME = "xtray-rotating-file"
_FILTER_NAME = "xtray-redaction"
_ROOT_HANDLER_NAME = "xtray-root-rotating-file"
_CRASH_LOG_NAME = "xtray-crash.log"
_ENV_LOG_LEVEL = "XTRAY_LOG_LEVEL"
_LOG_FORMAT = "%(asctime)s %(levelname)s [pid=%(process)d thread=%(threadName)s] %(name)s: %(message)s"
_LOG_MAX_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 5
_HOOKS_INSTALLED = False
_UNHANDLED_EXCEPTION_OCCURRED = False
_FAULT_HANDLER_FILE: Any | None = None
_STARTUP_LOGGED: set[tuple[str, str, str]] = set()
_RUN_MARKERS: dict[str, Path] = {}

# `\\Users\\<name>` on Windows, `/Users/<name>` on macOS, `/home/<name>` on Linux.
_USER_PATH_RE = re.compile(
    r"((?:[A-Za-z]:)?[\\/]Users[\\/])[^\\/\s\"'`]+",
)
_HOME_LIKE_RE = re.compile(r"([\\/]home[\\/])[^\\/\s\"'`]+")


def _normalize_app_name(app_name: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(app_name).strip().casefold()).strip("_")
    return normalized or LOGGER_NAME


def _handler_name(app_name: str) -> str:
    return f"{_normalize_app_name(app_name)}-rotating-file"


def _filter_name(app_name: str) -> str:
    return f"{_normalize_app_name(app_name)}-redaction"


def _config_module(app_name: str) -> ModuleType:
    normalized = _normalize_app_name(app_name)
    if normalized == LOGGER_NAME:
        return importlib.import_module("xtray.config")
    return importlib.import_module(f"{normalized}.config")


def redact(text: str, app_name: str = LOGGER_NAME) -> str:
    """Mask secrets and PII in a text snippet before logging or printing.

    Currently strips: the live API token (if configured) and the username
    component of common home-directory paths. Idempotent: safe to call
    twice. Falls back to the input on any unexpected error so the caller
    never crashes.
    """
    if not text:
        return text
    try:
        config = _config_module(app_name)
        try:
            token = config.get_api_token()
        except Exception:
            token = None
        if token and len(token) >= 8:
            text = text.replace(token, "<API_TOKEN>")
        try:
            mqtt_password = config.get_mqtt_password()
        except Exception:
            mqtt_password = None
        if mqtt_password and len(mqtt_password) >= 4:
            text = text.replace(mqtt_password, "<MQTT_PASSWORD>")
        text = _USER_PATH_RE.sub(r"\1<USER>", text)
        text = _HOME_LIKE_RE.sub(r"\1<USER>", text)
        return text
    except Exception:
        return text


class _RedactingFilter(logging.Filter):
    """Mutate log records so secrets/PII never reach handlers downstream."""

    def __init__(self, app_name: str = LOGGER_NAME) -> None:
        self.app_name = _normalize_app_name(app_name)
        super().__init__(name=_filter_name(self.app_name))

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = redact(message, app_name=self.app_name)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


class _RedactingFormatter(logging.Formatter):
    """Redact the final formatted log text, including tracebacks."""

    def __init__(self, fmt: str, *, app_name: str = LOGGER_NAME) -> None:
        self.app_name = _normalize_app_name(app_name)
        super().__init__(fmt)

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record), app_name=self.app_name)


def attach_redactor(handler: logging.Handler, app_name: str = LOGGER_NAME) -> None:
    """Add the redaction filter to a handler if it isn't already attached.

    The filter must live on the *handler* (not the logger) so that records
    emitted by descendants like ``computer_manager.profiles`` also get masked
    when they bubble up via ``Logger.callHandlers``.
    """
    filter_name = _filter_name(app_name)
    if any(getattr(filter_, "name", None) == filter_name for filter_ in handler.filters):
        return
    handler.addFilter(_RedactingFilter(app_name))


def _level_from_env(default: int = logging.INFO) -> int:
    raw = os.environ.get(_ENV_LOG_LEVEL)
    if not raw:
        return default
    value = raw.strip()
    if not value:
        return default
    if value.isdigit():
        return int(value)
    resolved = getattr(logging, value.upper(), None)
    return int(resolved) if isinstance(resolved, int) else default


def _xtray_log_dir() -> Path:
    config = importlib.import_module("xtray.config")
    return config.log_dir()


def _log_path() -> Path:
    return _xtray_log_dir() / f"{LOGGER_NAME}.log"


def crash_log_path() -> Path:
    path = _xtray_log_dir() / _CRASH_LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    return _xtray_log_dir()


def _runtime_marker_path(component: str) -> Path:
    normalized = _normalize_app_name(component)
    return _xtray_log_dir() / f"{LOGGER_NAME}-{normalized}.running.json"


def _handler_matches_path(handler: logging.Handler, path: Path) -> bool:
    base_filename = getattr(handler, "baseFilename", None)
    if not base_filename:
        return False
    try:
        return Path(base_filename).resolve() == path.resolve()
    except OSError:
        return Path(base_filename) == path


def _remove_named_handlers(logger: logging.Logger, name: str) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, "name", None) != name:
            continue
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


def _find_handler(logger: logging.Logger, name: str, path: Path) -> logging.Handler | None:
    for handler in logger.handlers:
        if getattr(handler, "name", None) == name and _handler_matches_path(handler, path):
            return handler
    return None


def _make_file_handler(path: Path, *, level: int, app_name: str) -> RotatingFileHandler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path,
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.name = _handler_name(LOGGER_NAME)
    handler.setLevel(level)
    handler.setFormatter(_RedactingFormatter(_LOG_FORMAT, app_name=app_name))
    attach_redactor(handler, app_name)
    return handler


def _configure_primary_handler(
    logger: logging.Logger,
    *,
    level: int,
    app_name: str,
) -> logging.Handler:
    path = _log_path()
    handler_name = _handler_name(LOGGER_NAME)
    root = logging.getLogger()
    handler = _find_handler(logger, handler_name, path)
    if handler is None:
        _remove_named_handlers(logger, handler_name)
        _remove_named_handlers(root, _ROOT_HANDLER_NAME)
        handler = _make_file_handler(path, level=level, app_name=app_name)
        logger.addHandler(handler)
    handler.setLevel(level)
    if not any(
        getattr(root_handler, "name", None) == _ROOT_HANDLER_NAME
        and _handler_matches_path(root_handler, path)
        for root_handler in root.handlers
    ):
        root_handler = _make_file_handler(path, level=level, app_name=app_name)
        root_handler.name = _ROOT_HANDLER_NAME
        root.addHandler(root_handler)
    else:
        for root_handler in root.handlers:
            if getattr(root_handler, "name", None) == _ROOT_HANDLER_NAME:
                root_handler.setLevel(level)
    return handler


def _configure_root(level: int) -> None:
    root = logging.getLogger()
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    logging.captureWarnings(True)


def _log_startup_metadata(
    logger: logging.Logger,
    *,
    logger_name: str,
    component: str,
    level: int,
) -> None:
    key = (logger_name, _normalize_app_name(component), str(_log_path()))
    if key in _STARTUP_LOGGED:
        return
    _STARTUP_LOGGED.add(key)
    try:
        from xtray import __version__
    except Exception:
        __version__ = "unknown"
    logger.info(
        "logging configured component=%s version=%s pid=%s executable=%s frozen=%s "
        "argv=%s platform=%s level=%s log_dir=%s",
        component,
        __version__,
        os.getpid(),
        sys.executable,
        bool(getattr(sys, "frozen", False)),
        redact(" ".join(sys.argv)),
        platform.platform(),
        logging.getLevelName(level),
        _xtray_log_dir(),
    )


def _write_runtime_marker(component: str, logger: logging.Logger) -> None:
    marker = _runtime_marker_path(component)
    component_key = _normalize_app_name(component)
    if component_key in _RUN_MARKERS and _RUN_MARKERS[component_key] == marker:
        return
    previous = None
    if marker.exists():
        try:
            previous = json.loads(marker.read_text(encoding="utf-8"))
        except Exception:
            previous = {"unreadable": True}
        if not isinstance(previous, dict) or previous.get("pid") != os.getpid():
            logger.warning("previous run ended unexpectedly: %s", previous)
    payload = {
        "component": _normalize_app_name(component),
        "pid": os.getpid(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "executable": sys.executable,
        "argv": redact(" ".join(sys.argv)),
    }
    try:
        marker.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        _RUN_MARKERS[component_key] = marker
    except Exception:
        logger.debug("could not write runtime marker %s", marker, exc_info=True)


def mark_clean_shutdown(component: str | None = None) -> None:
    """Remove runtime marker(s) after a clean shutdown."""
    if component is None:
        keys = list(_RUN_MARKERS)
    else:
        keys = [_normalize_app_name(component)]
    for key in keys:
        marker = _RUN_MARKERS.pop(key, None)
        if marker is None:
            marker = _runtime_marker_path(key)
        try:
            marker.unlink(missing_ok=True)
        except Exception:
            pass


def _close_faulthandler() -> None:
    global _FAULT_HANDLER_FILE
    if _FAULT_HANDLER_FILE is None:
        return
    try:
        faulthandler.disable()
    except Exception:
        pass
    try:
        _FAULT_HANDLER_FILE.close()
    except Exception:
        pass
    _FAULT_HANDLER_FILE = None


def _atexit_clean_shutdown() -> None:
    if _UNHANDLED_EXCEPTION_OCCURRED:
        return
    mark_clean_shutdown()
    _close_faulthandler()



def _install_faulthandler(logger: logging.Logger) -> None:
    global _FAULT_HANDLER_FILE
    path = crash_log_path()
    try:
        if _FAULT_HANDLER_FILE is not None and not _FAULT_HANDLER_FILE.closed:
            if Path(_FAULT_HANDLER_FILE.name).resolve() == path.resolve():
                return
            faulthandler.disable()
            _FAULT_HANDLER_FILE.close()
        _FAULT_HANDLER_FILE = path.open("a", encoding="utf-8")
        _FAULT_HANDLER_FILE.write(
            f"\n--- faulthandler enabled pid={os.getpid()} at "
            f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} ---\n"
        )
        _FAULT_HANDLER_FILE.flush()
        faulthandler.enable(file=_FAULT_HANDLER_FILE, all_threads=True)
    except Exception:
        logger.debug("could not enable faulthandler", exc_info=True)


def _install_exception_hooks(logger: logging.Logger) -> None:
    global _HOOKS_INSTALLED
    if _HOOKS_INSTALLED:
        return

    def _excepthook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        global _UNHANDLED_EXCEPTION_OCCURRED
        _UNHANDLED_EXCEPTION_OCCURRED = True
        logger.critical("uncaught exception", exc_info=(exc_type, exc, tb))

    def _threading_excepthook(args: threading.ExceptHookArgs) -> None:
        global _UNHANDLED_EXCEPTION_OCCURRED
        _UNHANDLED_EXCEPTION_OCCURRED = True
        logger.critical(
            "uncaught thread exception thread=%s",
            getattr(args, "thread", None),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    def _unraisablehook(args: Any) -> None:
        global _UNHANDLED_EXCEPTION_OCCURRED
        _UNHANDLED_EXCEPTION_OCCURRED = True
        logger.critical(
            "unraisable exception object=%r message=%s",
            getattr(args, "object", None),
            getattr(args, "err_msg", None),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _excepthook
    threading.excepthook = _threading_excepthook
    sys.unraisablehook = _unraisablehook
    atexit.register(_atexit_clean_shutdown)
    _HOOKS_INSTALLED = True


def configure_logging(
    app_name: str | int = LOGGER_NAME,
    level: int | str | None = None,
    *,
    component: str | None = None,
    install_global: bool = True,
    mark_running: bool = True,
) -> logging.Logger:
    if isinstance(app_name, int):
        level = app_name
        app_name = LOGGER_NAME
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    if level is None:
        level = _level_from_env()
    logger_name = _normalize_app_name(app_name)
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = False
    _configure_primary_handler(logger, level=level, app_name=LOGGER_NAME)
    if install_global:
        _configure_root(level)
        _install_exception_hooks(logger)
        _install_faulthandler(logger)
    runtime_component = _normalize_app_name(component or logger_name)
    _log_startup_metadata(
        logger,
        logger_name=logger_name,
        component=runtime_component,
        level=level,
    )
    if mark_running:
        _write_runtime_marker(runtime_component, logger)
    return logger


def get_logger(
    name: str | None = None,
    app_name: str = LOGGER_NAME,
    *,
    component: str | None = None,
) -> logging.Logger:
    logger_name = _normalize_app_name(app_name)
    base = configure_logging(
        logger_name,
        component=component,
        install_global=False,
        mark_running=False,
    )
    if not name:
        return base
    return logging.getLogger(f"{logger_name}.{name}")


def _redact_settings_value(key: str, value: Any) -> Any:
    lowered = key.casefold()
    if any(secret in lowered for secret in ("password", "token", "secret", "api_key")):
        return "<REDACTED>" if value not in (None, "") else value
    if isinstance(value, dict):
        return {str(k): _redact_settings_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_settings_value(key, item) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


def _redacted_settings_json() -> str:
    try:
        config = importlib.import_module("xtray.config")
        settings = config.load_settings()
    except Exception as exc:
        settings = {"error": f"could not load settings: {exc}"}
    redacted = _redact_settings_value("settings", settings)
    return json.dumps(redacted, indent=2, sort_keys=True, default=str)


def _runtime_metadata(component: str | None = None) -> dict[str, Any]:
    try:
        from xtray import __version__
    except Exception:
        __version__ = "unknown"
    return {
        "component": _normalize_app_name(component or LOGGER_NAME),
        "version": __version__,
        "pid": os.getpid(),
        "executable": sys.executable,
        "frozen": bool(getattr(sys, "frozen", False)),
        "argv": redact(" ".join(sys.argv)),
        "platform": platform.platform(),
        "python": sys.version,
        "log_dir": str(_xtray_log_dir()),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def _flush_handlers() -> None:
    seen: set[int] = set()
    for logger in [logging.getLogger(LOGGER_NAME), logging.getLogger()]:
        for handler in logger.handlers:
            identifier = id(handler)
            if identifier in seen:
                continue
            seen.add(identifier)
            try:
                handler.flush()
            except Exception:
                pass


def create_diagnostics_bundle(
    *,
    component: str | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Create a local ZIP with logs and redacted runtime/config metadata."""
    configure_logging(component=component, mark_running=False)
    _flush_handlers()
    target_dir = output_dir or _xtray_log_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    bundle_path = target_dir / f"xtray-diagnostics-{timestamp}.zip"
    with ZipFile(bundle_path, "w", compression=ZIP_DEFLATED) as archive:
        for pattern in ("xtray.log*", "xtray-crash.log*"):
            for path in sorted(_xtray_log_dir().glob(pattern)):
                if path.resolve() == bundle_path.resolve() or not path.is_file():
                    continue
                archive.write(path, arcname=path.name)
        archive.writestr(
            "runtime.json",
            json.dumps(_runtime_metadata(component), indent=2, sort_keys=True),
        )
        archive.writestr("settings-redacted.json", _redacted_settings_json())
    return bundle_path
