"""Windows global hotkey detection for the tray."""
from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class HotkeyError(RuntimeError):
    """Raised when a hotkey cannot be parsed or registered."""


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

MODIFIER_ALIASES = {
    "alt": MOD_ALT,
    "ctl": MOD_CONTROL,
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "windows": MOD_WIN,
    "meta": MOD_WIN,
}

NAMED_KEYS = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "escape": 0x1B,
    "esc": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "ins": 0x2D,
    "delete": 0x2E,
    "del": 0x2E,
}


@dataclass(frozen=True)
class ParsedHotkey:
    sequence: str
    modifiers: int
    vk: int


def parse_hotkey(sequence: str) -> ParsedHotkey:
    parts = [part.strip() for part in str(sequence or "").replace("-", "+").split("+")]
    parts = [part for part in parts if part]
    if not parts:
        raise HotkeyError("hotkey cannot be empty")
    modifiers = 0
    key: str | None = None
    for part in parts:
        normalized = part.casefold().replace(" ", "")
        modifier = MODIFIER_ALIASES.get(normalized)
        if modifier is not None:
            modifiers |= modifier
            continue
        if key is not None:
            raise HotkeyError("hotkey must contain only one non-modifier key")
        key = normalized
    if key is None:
        raise HotkeyError("hotkey must include a key")
    vk = _virtual_key_for(key)
    display = _format_sequence(parts)
    return ParsedHotkey(display, modifiers, vk)


VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_SHIFT = 0x10
VK_LWIN = 0x5B
VK_RWIN = 0x5C

# Map RegisterHotKey-style modifier bits to the list of virtual-key codes
# `GetAsyncKeyState` needs to check. WIN matches either left or right Win key.
_MOD_TO_VKS: dict[int, tuple[int, ...]] = {
    MOD_CONTROL: (VK_CONTROL,),
    MOD_ALT: (VK_MENU,),
    MOD_SHIFT: (VK_SHIFT,),
    MOD_WIN: (VK_LWIN, VK_RWIN),
}


class GlobalHotkeyManager:  # pragma: no cover - depends on Windows runtime
    """Detects a global hotkey by polling GetAsyncKeyState in a worker thread.

    Why not RegisterHotKey: third-party software that installs a low-level
    keyboard hook (Logitech Options+, NVIDIA GeForce Experience, AutoHotkey,
    PowerToys Keyboard Manager, gaming overlays...) can swallow the keystroke
    before the system converts it into a WM_HOTKEY message. GetAsyncKeyState
    reads the physical state of each key directly from the input driver, so
    it is unaffected by any user-mode hook.

    The poller emits a Qt signal whose receiver lives on the main thread,
    which Qt delivers as a queued event — safe to call `toggle_panel()` from.
    """

    def __init__(self, app: Any, callback: Callable[[], None]) -> None:
        self._app = app
        self._callback = callback
        self._poller: Any | None = None
        # Kept for API/back-compat with code (and tests) that inspect them.
        self._registered_ids: set[int] = set()
        self._next_id = 0x5854
        self._window: Any | None = None
        self._hwnd: int | None = None

    def register_toggle_hotkey(self, sequence: str) -> ParsedHotkey:
        parsed = parse_hotkey(sequence)
        if sys.platform != "win32":
            raise HotkeyError("global hotkeys are only available on Windows")
        self._stop_poller()

        modifier_vks: list[tuple[int, ...]] = []
        for bit, vks in _MOD_TO_VKS.items():
            if parsed.modifiers & bit:
                modifier_vks.append(vks)

        from PySide6.QtCore import Qt, QThread, Signal  # type: ignore[import-not-found]

        callback = self._callback
        key_vk = parsed.vk

        class _Poller(QThread):
            triggered = Signal()

            def __init__(self) -> None:
                super().__init__()
                self._stop_requested = False
                self._was_combo_held = False

            def request_stop(self) -> None:
                self._stop_requested = True

            def run(self) -> None:
                import time as _time
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
                user32.GetAsyncKeyState.restype = ctypes.c_short
                # GetAsyncKeyState's high-order bit (0x8000) is set when the
                # key is currently down. We only fire on the leading edge of
                # the combo (i.e. when it goes from "not all held" to "all
                # held") so a long press only triggers once.
                while not self._stop_requested:
                    _time.sleep(0.04)
                    key_down = (user32.GetAsyncKeyState(key_vk) & 0x8000) != 0
                    mods_down = all(
                        any((user32.GetAsyncKeyState(vk) & 0x8000) != 0 for vk in group)
                        for group in modifier_vks
                    )
                    combo_held = key_down and mods_down
                    if combo_held and not self._was_combo_held:
                        self.triggered.emit()
                    self._was_combo_held = combo_held

        poller = _Poller()
        # QueuedConnection makes Qt deliver the callback on the receiving
        # object's thread (here the main GUI thread).
        poller.triggered.connect(lambda: callback(), Qt.ConnectionType.QueuedConnection)
        poller.start()
        self._poller = poller
        self._registered_ids.add(self._next_id)
        return parsed

    def clear(self) -> None:
        self._stop_poller()
        self._registered_ids.clear()

    def close(self) -> None:
        self.clear()

    def _stop_poller(self) -> None:
        poller = self._poller
        if poller is None:
            return
        poller.request_stop()
        poller.wait(500)
        self._poller = None


def _virtual_key_for(key: str) -> int:
    if len(key) == 1:
        char = key.upper()
        if "A" <= char <= "Z" or "0" <= char <= "9":
            return ord(char)
    if key.startswith("f"):
        try:
            number = int(key[1:])
        except ValueError:
            number = 0
        if 1 <= number <= 24:
            return 0x70 + number - 1
    vk = NAMED_KEYS.get(key)
    if vk is not None:
        return vk
    raise HotkeyError(f"unsupported hotkey key: {key}")


def _format_sequence(parts: list[str]) -> str:
    labels: list[str] = []
    for part in parts:
        normalized = part.casefold().replace(" ", "")
        if normalized in {"ctl", "ctrl", "control"}:
            labels.append("Ctrl")
        elif normalized == "alt":
            labels.append("Alt")
        elif normalized == "shift":
            labels.append("Shift")
        elif normalized in {"win", "windows", "meta"}:
            labels.append("Win")
        elif len(normalized) == 1:
            labels.append(normalized.upper())
        elif normalized.startswith("f") and normalized[1:].isdigit():
            labels.append("F" + normalized[1:])
        else:
            labels.append(part.strip())
    return "+".join(labels)
