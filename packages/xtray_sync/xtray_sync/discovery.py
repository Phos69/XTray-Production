"""UDP broadcast discovery for XTray LAN sync peers."""
from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any

from . import __version__
from . import config as sync_config

PROTOCOL = "xtray-sync"
DISCOVERY_VERSION = 1
CAPABILITIES = (
    "network_manager_settings",
    "network_devices",
    "network_passwords",
    "display_profiles",
)


@dataclass(frozen=True)
class Peer:
    instance_id: str
    peer_name: str
    hostname: str
    host: str
    port: int
    discovery_port: int
    version: str
    capabilities: tuple[str, ...]
    last_seen: float

    @property
    def label(self) -> str:
        return f"{self.peer_name} ({self.host}:{self.port})"

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "peer_name": self.peer_name,
            "hostname": self.hostname,
            "host": self.host,
            "port": self.port,
            "discovery_port": self.discovery_port,
            "version": self.version,
            "capabilities": list(self.capabilities),
            "last_seen": self.last_seen,
        }


def announcement(settings: sync_config.SyncSettings | None = None) -> dict[str, Any]:
    settings = settings or sync_config.load_sync_settings()
    return {
        "protocol": PROTOCOL,
        "discovery_version": DISCOVERY_VERSION,
        "xtray_sync_version": __version__,
        "instance_id": settings.instance_id,
        "peer_name": settings.peer_name,
        "hostname": socket.gethostname(),
        "port": settings.port,
        "discovery_port": settings.discovery_port,
        "capabilities": list(CAPABILITIES),
    }


def parse_peer(data: dict[str, Any], host: str, last_seen: float | None = None) -> Peer | None:
    if data.get("protocol") != PROTOCOL or data.get("discovery_version") != DISCOVERY_VERSION:
        return None
    try:
        port = int(data.get("port"))
        discovery_port = int(data.get("discovery_port") or sync_config.DEFAULT_DISCOVERY_PORT)
    except (TypeError, ValueError):
        return None
    instance_id = str(data.get("instance_id") or "").strip()
    if not instance_id:
        return None
    capabilities = data.get("capabilities")
    if not isinstance(capabilities, list):
        capabilities = []
    return Peer(
        instance_id=instance_id,
        peer_name=str(data.get("peer_name") or data.get("hostname") or host),
        hostname=str(data.get("hostname") or ""),
        host=host,
        port=port,
        discovery_port=discovery_port,
        version=str(data.get("xtray_sync_version") or ""),
        capabilities=tuple(str(item) for item in capabilities),
        last_seen=last_seen or time.time(),
    )


def discover_peers(
    *,
    timeout: float = 2.0,
    discovery_port: int | None = None,
    include_self: bool = False,
) -> list[Peer]:
    settings = sync_config.load_sync_settings()
    port = discovery_port or settings.discovery_port
    deadline = time.monotonic() + max(0.1, float(timeout))
    peers: dict[str, Peer] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.2)
        try:
            sock.bind(("", port))
        except OSError:
            sock.bind(("0.0.0.0", 0))
        while time.monotonic() < deadline:
            try:
                packet, address = sock.recvfrom(8192)
            except TimeoutError:
                continue
            except OSError:
                break
            try:
                data = json.loads(packet.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            peer = parse_peer(data, address[0], time.time())
            if peer is None:
                continue
            if not include_self and peer.instance_id == settings.instance_id:
                continue
            peers[peer.instance_id] = peer
    return sorted(peers.values(), key=lambda peer: (peer.peer_name.casefold(), peer.host))


def send_announcement(
    *,
    settings: sync_config.SyncSettings | None = None,
    target_host: str = "<broadcast>",
) -> None:
    settings = settings or sync_config.load_sync_settings()
    payload = json.dumps(announcement(settings), sort_keys=True).encode("utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(payload, (target_host, settings.discovery_port))


class DiscoveryAnnouncer:
    """Background UDP broadcaster used by the tray sync runtime."""

    def __init__(self, *, interval_seconds: float = 5.0) -> None:
        self.interval_seconds = max(1.0, float(interval_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="xtray-sync-discovery",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                settings = sync_config.load_sync_settings()
                if settings.enabled and sync_config.password_available():
                    send_announcement(settings=settings)
            except Exception:
                pass
            self._stop.wait(self.interval_seconds)
