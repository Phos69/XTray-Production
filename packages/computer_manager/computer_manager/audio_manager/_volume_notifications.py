"""Push notifications for IAudioEndpointVolume volume/mute changes.

Wraps `IAudioEndpointVolume::RegisterControlChangeNotify` so callers see
immediate volume/mute updates from Windows hotkeys, the volume OSD, and
external apps — instead of polling.

The callback fires on a Windows-managed thread. Consumers MUST marshal the
event to their UI thread; this module hands the raw payload to the user
callback without thread switching.
"""
from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

from xtray.core import app_logging

from ._com_runtime import (
    _GUID,
    _check_hr,
    _com_method,
    _guid,
    _release,
)
from ._endpoint_volume import _activate_audio_endpoint_volume
from ._mmdevice import _create_mm_device_enumerator

_IID_IAUDIO_ENDPOINT_VOLUME_CALLBACK = "{657804FA-D6AD-4496-8A60-352752AF4F89}"
_IID_IUNKNOWN = "{00000000-0000-0000-C000-000000000046}"
_E_NOINTERFACE = 0x80004002
_ORPHANED_CALLBACKS: list[tuple[Any, Any, ctypes.c_void_p, Any]] = []


class _AudioVolumeNotificationData(ctypes.Structure):
    _fields_ = [
        ("guidEventContext", _GUID),
        ("bMuted", wintypes.BOOL),
        ("fMasterVolume", ctypes.c_float),
        ("nChannels", wintypes.UINT),
        ("afChannelVolumes", ctypes.c_float * 1),  # variable-length tail; first only
    ]


_QUERY_INTERFACE_FN = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    ctypes.c_void_p,
    ctypes.POINTER(_GUID),
    ctypes.POINTER(ctypes.c_void_p),
)
_REFCOUNT_FN = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
_ON_NOTIFY_FN = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    ctypes.c_void_p,
    ctypes.POINTER(_AudioVolumeNotificationData),
)


class _Vtable(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", _QUERY_INTERFACE_FN),
        ("AddRef", _REFCOUNT_FN),
        ("Release", _REFCOUNT_FN),
        ("OnNotify", _ON_NOTIFY_FN),
    ]


class _CallbackObject(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(_Vtable))]


@dataclass(frozen=True)
class VolumeChangeEvent:
    """Snapshot from a Windows IAudioEndpointVolume notification."""

    volume_percent: int
    muted: bool
    channel_count: int


@dataclass
class _CallbackState:
    on_change: Callable[[VolumeChangeEvent], None] | None
    endpoint_id: str | None
    callback_pointer: ctypes.c_void_p | None = None
    active: bool = True


class VolumeChangeListener:
    """Subscribe to volume/mute notifications for a render endpoint.

    `endpoint_id` selects the device; pass ``None`` for the system default.
    The listener takes its own COM session; `start` and `stop` are idempotent.
    """

    def __init__(
        self,
        on_change: Callable[[VolumeChangeEvent], None],
        endpoint_id: str | None = None,
    ) -> None:
        self._on_change = on_change
        self._endpoint_id = endpoint_id
        self._lock = threading.Lock()
        self._enumerator: ctypes.c_void_p | None = None
        self._device: ctypes.c_void_p | None = None
        self._endpoint_volume: ctypes.c_void_p | None = None
        self._com_initialized = False
        self._uninitialize = False
        # Strong references kept alive while subscribed.
        self._vtable: _Vtable | None = None
        self._callback_object: _CallbackObject | None = None
        self._callback_pointer: ctypes.c_void_p | None = None
        self._callback_state: _CallbackState | None = None
        self._log = app_logging.get_logger("audio.volume_notify")

    @property
    def endpoint_id(self) -> str | None:
        return self._endpoint_id

    def start(self) -> bool:
        """Activate the endpoint and register the callback. Returns success."""
        with self._lock:
            if self._endpoint_volume is not None:
                return True
            try:
                self._activate_locked()
                self._register_locked()
            except Exception:
                self._log.exception("failed to start volume listener")
                self._teardown_locked()
                return False
            return True

    def stop(self) -> None:
        with self._lock:
            self._teardown_locked()

    def replace_endpoint(self, endpoint_id: str | None) -> bool:
        """Switch the subscription to a different endpoint id."""
        with self._lock:
            if endpoint_id == self._endpoint_id and self._endpoint_volume is not None:
                return True
            self._teardown_locked()
            self._endpoint_id = endpoint_id
            try:
                self._activate_locked()
                self._register_locked()
            except Exception:
                self._log.exception("failed to replace volume listener endpoint")
                self._teardown_locked()
                return False
            return True

    def _activate_locked(self) -> None:
        from ._com_runtime import _RPC_E_CHANGED_MODE, _ole32

        hr = _ole32().CoInitializeEx(None, 0)
        normalized = hr & 0xFFFFFFFF
        if normalized in (0, 1):
            self._uninitialize = True
        elif normalized != _RPC_E_CHANGED_MODE:
            _check_hr(hr, "CoInitializeEx failed")
        self._com_initialized = True

        enumerator = _create_mm_device_enumerator()
        self._enumerator = enumerator
        device = self._open_device_locked(enumerator)
        self._device = device
        self._endpoint_volume = _activate_audio_endpoint_volume(device)

    def _open_device_locked(self, enumerator: ctypes.c_void_p) -> ctypes.c_void_p:
        from .core import AudioEndpointNotFound

        device = ctypes.c_void_p()
        if self._endpoint_id is None:
            get_default = _com_method(
                enumerator,
                4,
                ctypes.c_long,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_void_p),
            )
            _check_hr(
                get_default(enumerator, 0, 1, ctypes.byref(device)),
                "GetDefaultAudioEndpoint failed",
            )
        else:
            get_device = _com_method(
                enumerator,
                5,
                ctypes.c_long,
                wintypes.LPCWSTR,
                ctypes.POINTER(ctypes.c_void_p),
            )
            _check_hr(
                get_device(enumerator, self._endpoint_id, ctypes.byref(device)),
                "IMMDeviceEnumerator.GetDevice failed",
            )
        if not device.value:
            raise AudioEndpointNotFound(self._endpoint_id or "default output")
        return device

    def _register_locked(self) -> None:
        callback_iid = _guid(_IID_IAUDIO_ENDPOINT_VOLUME_CALLBACK)
        unknown_iid = _guid(_IID_IUNKNOWN)
        callback_state = _CallbackState(
            on_change=self._on_change,
            endpoint_id=self._endpoint_id,
        )

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

        def on_notify(_this, data_ptr):
            if not callback_state.active:
                return 0
            try:
                data = data_ptr.contents
                scalar = max(0.0, min(1.0, float(data.fMasterVolume)))
                event = VolumeChangeEvent(
                    volume_percent=int(round(scalar * 100)),
                    muted=bool(data.bMuted),
                    channel_count=int(data.nChannels),
                )
                self._log.debug(
                    "volume notification endpoint=%s volume=%s muted=%s channels=%s",
                    callback_state.endpoint_id or "<default>",
                    event.volume_percent,
                    event.muted,
                    event.channel_count,
                )
                handler = callback_state.on_change
                if handler is not None:
                    handler(event)
            except Exception:
                self._log.exception("volume notification callback raised")
            return 0

        vtable = _Vtable(
            QueryInterface=_QUERY_INTERFACE_FN(query_interface),
            AddRef=_REFCOUNT_FN(add_ref),
            Release=_REFCOUNT_FN(release),
            OnNotify=_ON_NOTIFY_FN(on_notify),
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
            self._endpoint_volume,
            3,
            ctypes.c_long,
            ctypes.c_void_p,
        )
        _check_hr(
            register(self._endpoint_volume, self._callback_pointer),
            "IAudioEndpointVolume.RegisterControlChangeNotify failed",
        )
        self._log.info(
            "registered volume listener endpoint=%s callback=%s",
            self._endpoint_id or "<default>",
            _pointer_label(self._callback_pointer),
        )

    def _teardown_locked(self) -> None:
        endpoint_volume = self._endpoint_volume
        callback_pointer = self._callback_pointer
        callback_state = self._callback_state
        unregistered = callback_pointer is None
        if callback_state is not None:
            callback_state.active = False
            callback_state.on_change = None
        if endpoint_volume is not None and self._callback_pointer is not None:
            try:
                unregister = _com_method(
                    endpoint_volume,
                    4,
                    ctypes.c_long,
                    ctypes.c_void_p,
                )
                _check_hr(
                    unregister(endpoint_volume, self._callback_pointer),
                    "IAudioEndpointVolume.UnregisterControlChangeNotify failed",
                )
                unregistered = True
            except Exception:
                self._log.exception("unregister callback failed")
        if endpoint_volume is not None:
            try:
                _release(endpoint_volume)
            except Exception:
                self._log.exception("release endpoint volume failed")
        if self._device is not None:
            try:
                _release(self._device)
            except Exception:
                self._log.exception("release device failed")
        if self._enumerator is not None:
            try:
                _release(self._enumerator)
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
                "kept orphaned inactive volume callback alive after unregister failure: %s",
                _pointer_label(callback_pointer),
            )

        self._endpoint_volume = None
        self._device = None
        self._enumerator = None
        self._callback_pointer = None
        self._callback_object = None
        self._vtable = None
        self._callback_state = None
        self._com_initialized = False
        self._uninitialize = False


def _guid_equals(left: _GUID, right: _GUID) -> bool:
    if left.Data1 != right.Data1:
        return False
    if left.Data2 != right.Data2:
        return False
    if left.Data3 != right.Data3:
        return False
    return bytes(left.Data4) == bytes(right.Data4)


def _pointer_label(pointer: ctypes.c_void_p | None) -> str:
    value = getattr(pointer, "value", None)
    return f"0x{value:x}" if value else "<null>"


def read_current_volume(endpoint_id: str | None = None) -> VolumeChangeEvent | None:
    """One-shot read used to seed widgets before the first push event arrives."""
    from ._endpoint_volume import _get_master_volume_scalar, _get_mute, _with_audio_endpoint_volume

    class _SourceLike:
        def __init__(self, endpoint_id: str | None) -> None:
            self.endpoint_id = endpoint_id

        def label(self) -> str:
            return "default output" if self.endpoint_id is None else self.endpoint_id

    source = None if endpoint_id is None else _SourceLike(endpoint_id)

    def reader(endpoint_volume: Any) -> VolumeChangeEvent:
        scalar = _get_master_volume_scalar(endpoint_volume)
        muted = _get_mute(endpoint_volume)
        return VolumeChangeEvent(
            volume_percent=int(round(max(0.0, min(1.0, scalar)) * 100)),
            muted=muted,
            channel_count=0,
        )

    try:
        return _with_audio_endpoint_volume(source, reader)
    except Exception:
        app_logging.get_logger("audio.volume_notify").exception(
            "read_current_volume failed"
        )
        return None
