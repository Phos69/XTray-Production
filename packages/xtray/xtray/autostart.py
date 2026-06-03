"""Per-user Windows autostart integration for the tray app."""
from __future__ import annotations

import os
import sys
from typing import Any

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "XTray"
LEGACY_RUN_VALUE_NAME = "DisplayManagerTray"


class AutostartError(Exception):
    """Raised when Windows autostart settings cannot be read or changed."""


def startup_command() -> str:
    if getattr(sys, "frozen", False):
        return _quote(sys.executable)
    launcher = tray_launcher_runtime()
    if launcher is not None:
        return _quote(launcher)
    return f"{_quote(consoleless_python_runtime())} -m xtray.tray"


def tray_launcher_runtime() -> str | None:
    """Return the installed tray launcher when it is available.

    Launching through the generated ``xtray-tray.exe`` gives Task Manager a
    tray-specific process name instead of the generic ``python.exe``.
    """
    if os.name != "nt":
        return None
    executable = sys.executable
    base, name = os.path.split(executable)
    if name.lower() == "xtray-tray.exe":
        return executable

    candidates = [
        os.path.join(base, "xtray-tray.exe"),
        os.path.join(base, "Scripts", "xtray-tray.exe"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


def consoleless_python_runtime() -> str:
    """Prefer pythonw.exe on Windows so autostart does not allocate a console."""
    executable = sys.executable
    if os.name != "nt":
        return executable
    base, name = os.path.split(executable)
    candidate = os.path.join(base, "pythonw.exe")
    if name.lower() != "pythonw.exe" and os.path.exists(candidate):
        return candidate
    return executable


def _python_runtime() -> str:
    return consoleless_python_runtime()


def migrate_legacy_autostart() -> bool:
    """Remove the old DisplayManagerTray entry and refresh the XTray command."""
    legacy_removed = _remove_legacy_value_if_applicable()
    changed = legacy_removed
    desired = startup_command()
    current = _stored_value()
    if current is None:
        if legacy_removed:
            enable(desired)
            changed = True
    elif current != desired:
        enable(desired)
        changed = True
    return changed


def is_enabled() -> bool:
    return _stored_value() is not None


def enable(command: str | None = None) -> None:
    winreg = _winreg()
    value = command or startup_command()
    try:
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        )
    except OSError as exc:
        raise AutostartError(str(exc)) from exc
    try:
        winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, value)
    except OSError as exc:
        raise AutostartError(str(exc)) from exc
    finally:
        winreg.CloseKey(key)


def disable() -> None:
    winreg = _winreg()
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        )
    except FileNotFoundError:
        return
    except OSError as exc:
        raise AutostartError(str(exc)) from exc
    try:
        try:
            winreg.DeleteValue(key, RUN_VALUE_NAME)
        except FileNotFoundError:
            return
    except OSError as exc:
        raise AutostartError(str(exc)) from exc
    finally:
        winreg.CloseKey(key)


def _stored_value() -> str | None:
    winreg = _winreg()
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise AutostartError(str(exc)) from exc
    try:
        try:
            value, _kind = winreg.QueryValueEx(key, RUN_VALUE_NAME)
        except FileNotFoundError:
            return None
        return str(value)
    except OSError as exc:
        raise AutostartError(str(exc)) from exc
    finally:
        winreg.CloseKey(key)


def _remove_legacy_value_if_applicable() -> bool:
    winreg = _winreg()
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_READ | winreg.KEY_SET_VALUE,
        )
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise AutostartError(str(exc)) from exc
    try:
        try:
            value, _kind = winreg.QueryValueEx(key, LEGACY_RUN_VALUE_NAME)
        except FileNotFoundError:
            return False
        text = str(value)
        if "displaymanager.tray" not in text and "DisplayManagerTray" not in text:
            return False
        try:
            winreg.DeleteValue(key, LEGACY_RUN_VALUE_NAME)
        except FileNotFoundError:
            return False
        return True
    except OSError as exc:
        raise AutostartError(str(exc)) from exc
    finally:
        winreg.CloseKey(key)


def _winreg() -> Any:
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError as exc:
        raise AutostartError("Windows registry is not available on this platform") from exc
    return winreg


def _quote(value: str) -> str:
    escaped = value.replace('"', r'\"')
    return f'"{escaped}"'
