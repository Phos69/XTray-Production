"""Adapter from XTray UI surfaces to NetworkManager device functionality."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from network_manager import device_manager as devices
except ImportError:
    devices = None


DEVICE_KIND_NETWORK = "network"
DEVICE_KINDS = ("network", "iot", "media", "personal")


@dataclass(frozen=True)
class _FallbackNetworkDevice:
    id: str
    name: str
    ip: str
    mac: str | None = None
    url: str | None = None
    icon: str | None = None
    kind: str = DEVICE_KIND_NETWORK
    offline: bool = False

    def web_url(self) -> str:
        return self.url or f"http://{self.ip}"


@dataclass(frozen=True)
class _FallbackNetworkStatus:
    device: _FallbackNetworkDevice
    online: bool
    latency_ms: int | None = None
    detail: str | None = None


class _FallbackDevices:
    DEVICE_KIND_NETWORK = DEVICE_KIND_NETWORK
    DEVICE_KINDS = DEVICE_KINDS
    NetworkDevice = _FallbackNetworkDevice
    NetworkStatus = _FallbackNetworkStatus

    @staticmethod
    def list_devices() -> list[_FallbackNetworkDevice]:
        return []

    @staticmethod
    def ping_device(device: _FallbackNetworkDevice) -> _FallbackNetworkStatus:
        return _FallbackNetworkStatus(
            device=device,
            online=False,
            detail="network_manager is not installed",
        )

    @staticmethod
    def local_adapter_mac() -> str | None:
        return None

    @staticmethod
    def normalize_mac(value: str | None) -> str | None:
        return value

    @staticmethod
    def normalize_kind(value: str | None) -> str:
        text = str(value or "").casefold().replace("-", "_").replace(" ", "_")
        return text if text in DEVICE_KINDS else DEVICE_KIND_NETWORK


if devices is None:
    devices = _FallbackDevices()


class NetworkService:
    def list_devices(self) -> list[Any]:
        return devices.list_devices()

    def ping_device(self, device: Any) -> Any:
        return devices.ping_device(device)

    def local_adapter_mac(self) -> str | None:
        return devices.local_adapter_mac()
