"""Push notifications for IMMDeviceEnumerator endpoint changes.

Wraps `IMMDeviceEnumerator::RegisterEndpointNotificationCallback` so callers
react immediately when the user switches the default playback device,
plugs/unplugs an endpoint, or toggles a device state in Windows Sound
Settings — without waiting for a polling tick.

All callbacks fire on a Windows-managed thread; consumers MUST marshal
events to their UI thread before touching widgets.
"""
from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from enum import Enum
from typing import Any

from xtray.core import app_logging

from ._com_runtime import (
    _GUID,
    _PROPERTYKEY,
    _check_hr,
    _com_method,
    _guid,
    _release,
)
from ._mmdevice import _create_mm_device_enumerator
from ._volume_notifications import _guid_equals

_IID_IMM_NOTIFICATION_CLIENT = "{7991EEC9-7E89-4D85-8390-6C703CEC60C0}"
_IID_IUNKNOWN = "{00000000-0000-0000-C000-000000000046}"
_E_NOINTERFACE = 0x80004002
_ORPHANED_CALLBACKS: list[tuple[Any, Any, ctypes.c_void_p, Any]] = []


class EndpointChangeKind(str, Enum):
    DEFAULT_CHANGED = "default_changed"
    DEVICE_STATE_CHANGED = "device_state_changed"
    DEVICE_ADDED = "device_added"
    DEVICE_REMOVED = "device_removed"
    PROPERTY_CHANGED = "property_changed"


@dataclass(frozen=True)
class EndpointChangeEvent:
    kind: EndpointChangeKind
    endpoint_id: str | None = None
    flow: int | None = None
    role: int | None = None
    new_state: int | None = None


@dataclass
class _CallbackState:
    on_change: Callable[[EndpointChangeEvent], None] | None
    callback_pointer: ctypes.c_void_p | None = None
    active: bool = True


_QUERY_INTERFACE_FN = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    ctypes.c_void_p,
    ctypes.POINTER(_GUID),
    ctypes.POINTER(ctypes.c_void_p),
)
_REFCOUNT_FN = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
_ON_DEVICE_STATE_FN = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR, wintypes.DWORD
)
_ON_DEVICE_ID_FN = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR
)
_ON_DEFAULT_CHANGED_FN = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.LPCWSTR,
)
_ON_PROPERTY_FN = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR, _PROPERTYKEY
)


class _Vtable(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", _QUERY_INTERFACE_FN),
        ("AddRef", _REFCOUNT_FN),
        ("Release", _REFCOUNT_FN),
        ("OnDeviceStateChanged", _ON_DEVICE_STATE_FN),
        ("OnDeviceAdded", _ON_DEVICE_ID_FN),
        ("OnDeviceRemoved", _ON_DEVICE_ID_FN),
        ("OnDefaultDeviceChanged", _ON_DEFAULT_CHANGED_FN),
        ("OnPropertyValueChanged", _ON_PROPERTY_FN),
    ]


class _CallbackObject(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(_Vtable))]


class EndpointChangeListener:
    """Subscribe to MMDevice enumerator-level notifications.

    `start`/`stop` are idempotent. Multiple events may fire in quick
    succession (e.g. plug-in fires both DeviceAdded and DefaultDeviceChanged);
    the consumer is expected to debounce.
    """

    def __init__(self, on_change: Callable[[EndpointChangeEvent], None]) -> None:
        self._on_change = on_change
        self._lock = threading.Lock()
        self._enumerator: ctypes.c_void_p | None = None
        self._com_initialized = False
        self._uninitialize = False
        self._vtable: _Vtable | None = None
        self._callback_object: _CallbackObject | None = None
        self._callback_pointer: ctypes.c_void_p | None = None
        self._callback_state: _CallbackState | None = None
        self._log = app_logging.get_logger("audio.endpoint_notify")

    def start(self) -> bool:
        with self._lock:
            if self._enumerator is not None:
                return True
            try:
                self._activate_locked()
                self._register_locked()
            except Exception:
                self._log.exception("failed to start endpoint listener")
                self._teardown_locked()
                return False
            return True

    def stop(self) -> None:
        with self._lock:
            self._teardown_locked()

    def _activate_locked(self) -> None:
        from ._com_runtime import _RPC_E_CHANGED_MODE, _ole32

        hr = _ole32().CoInitializeEx(None, 0)
        normalized = hr & 0xFFFFFFFF
        if normalized in (0, 1):
            self._uninitialize = True
        elif normalized != _RPC_E_CHANGED_MODE:
            _check_hr(hr, "CoInitializeEx failed")
        self._com_initialized = True
        self._enumerator = _create_mm_device_enumerator()

    def _register_locked(self) -> None:
        callback_iid = _guid(_IID_IMM_NOTIFICATION_CLIENT)
        unknown_iid = _guid(_IID_IUNKNOWN)
        callback_state = _CallbackState(on_change=self._on_change)

        def query_interface(_this, riid_ptr, ppv_ptr):
            requested = riid_ptr.contents
            if _guid_equals(requested, callback_iid) or _guid_equals(requested, unknown_iid):
                ppv_ptr[0] = callback_state.callback_pointer
                return 0
            ppv_ptr[0] = None
            return _E_NOINTERFACE

        def add_ref(_this):
            return 1

        def release(_this):
            return 1

        def on_device_state_changed(_this, device_id, new_state):
            if not callback_state.active:
                return 0
            self._emit(
                callback_state,
                EndpointChangeEvent(
                    kind=EndpointChangeKind.DEVICE_STATE_CHANGED,
                    endpoint_id=device_id,
                    new_state=int(new_state),
                )
            )
            return 0

        def on_device_added(_this, device_id):
            if not callback_state.active:
                return 0
            self._emit(
                callback_state,
                EndpointChangeEvent(
                    kind=EndpointChangeKind.DEVICE_ADDED,
                    endpoint_id=device_id,
                )
            )
            return 0

        def on_device_removed(_this, device_id):
            if not callback_state.active:
                return 0
            self._emit(
                callback_state,
                EndpointChangeEvent(
                    kind=EndpointChangeKind.DEVICE_REMOVED,
                    endpoint_id=device_id,
                )
            )
            return 0

        def on_default_changed(_this, flow, role, device_id):
            if not callback_state.active:
                return 0
            self._emit(
                callback_state,
                EndpointChangeEvent(
                    kind=EndpointChangeKind.DEFAULT_CHANGED,
                    endpoint_id=device_id,
                    flow=int(flow),
                    role=int(role),
                )
            )
            return 0

        def on_property_value_changed(_this, device_id, _key):
            if not callback_state.active:
                return 0
            # Property changes fire frequently (e.g. format, channel layout);
            # we forward them so the consumer can debounce, but the kind is
            # rarely useful enough to act on without filtering.
            self._emit(
                callback_state,
                EndpointChangeEvent(
                    kind=EndpointChangeKind.PROPERTY_CHANGED,
                    endpoint_id=device_id,
                )
            )
            return 0

        vtable = _Vtable(
            QueryInterface=_QUERY_INTERFACE_FN(query_interface),
            AddRef=_REFCOUNT_FN(add_ref),
            Release=_REFCOUNT_FN(release),
            OnDeviceStateChanged=_ON_DEVICE_STATE_FN(on_device_state_changed),
            OnDeviceAdded=_ON_DEVICE_ID_FN(on_device_added),
            OnDeviceRemoved=_ON_DEVICE_ID_FN(on_device_removed),
            OnDefaultDeviceChanged=_ON_DEFAULT_CHANGED_FN(on_default_changed),
            OnPropertyValueChanged=_ON_PROPERTY_FN(on_property_value_changed),
        )
        callback_object = _CallbackObject(lpVtbl=ctypes.pointer(vtable))
        self._vtable = vtable
        self._callback_object = callback_object
        self._callback_pointer = ctypes.cast(
            ctypes.pointer(callback_object), ctypes.c_void_p
        )
        callback_state.callback_pointer = self._callback_pointer
        self._callback_state = callback_state

        register = _com_method(
            self._enumerator,
            6,
            ctypes.c_long,
            ctypes.c_void_p,
        )
        _check_hr(
            register(self._enumerator, self._callback_pointer),
            "IMMDeviceEnumerator.RegisterEndpointNotificationCallback failed",
        )
        self._log.info(
            "registered endpoint listener callback=%s",
            _pointer_label(self._callback_pointer),
        )

    def _emit(self, callback_state: _CallbackState, event: EndpointChangeEvent) -> None:
        try:
            self._log.debug(
                "endpoint notification kind=%s endpoint=%s flow=%s role=%s state=%s",
                getattr(event.kind, "value", event.kind),
                event.endpoint_id,
                event.flow,
                event.role,
                event.new_state,
            )
            handler = callback_state.on_change
            if handler is not None:
                handler(event)
        except Exception:
            self._log.exception("endpoint notification callback raised")

    def _teardown_locked(self) -> None:
        enumerator = self._enumerator
        callback_pointer = self._callback_pointer
        callback_state = self._callback_state
        unregistered = callback_pointer is None
        if callback_state is not None:
            callback_state.active = False
            callback_state.on_change = None
        if enumerator is not None and self._callback_pointer is not None:
            try:
                unregister = _com_method(
                    enumerator,
                    7,
                    ctypes.c_long,
                    ctypes.c_void_p,
                )
                _check_hr(
                    unregister(enumerator, self._callback_pointer),
                    "IMMDeviceEnumerator.UnregisterEndpointNotificationCallback failed",
                )
                unregistered = True
            except Exception:
                self._log.exception("unregister endpoint callback failed")
        if enumerator is not None:
            try:
                _release(enumerator)
            except Exception:
                self._log.exception("release enumerator failed")
        if self._com_initialized and self._uninitialize:
            try:
                from ._com_runtime import _ole32

                _ole32().CoUninitialize()
            except Exception:
                self._log.exception("CoUninitialize failed")
        if not unregistered:
            _ORPHANED_CALLBACKS.append(
                (self._vtable, self._callback_object, callback_pointer, callback_state)
            )
            self._log.warning(
                "kept orphaned inactive endpoint callback alive after unregister failure: %s",
                _pointer_label(callback_pointer),
            )

        self._enumerator = None
        self._callback_pointer = None
        self._callback_object = None
        self._vtable = None
        self._callback_state = None
        self._com_initialized = False
        self._uninitialize = False


def _pointer_label(pointer: ctypes.c_void_p | None) -> str:
    value = getattr(pointer, "value", None)
    return f"0x{value:x}" if value else "<null>"
