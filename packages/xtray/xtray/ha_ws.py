"""Home Assistant WebSocket state listener.

The REST client is still used for point reads/writes. This module keeps a
long-lived WebSocket subscription to ``state_changed`` events so media_player
volume attributes can update the tray as soon as Home Assistant publishes them.
It intentionally uses only the standard library to match ``ha_rest.py`` and to
avoid adding another runtime dependency to the tray package.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import select
import socket
import ssl
import struct
import threading
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import ha_rest
from .core import app_logging

_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class HaWebSocketError(Exception):
    """Raised when the Home Assistant WebSocket stream fails."""


@dataclass(frozen=True)
class HaMediaPlayerStateEvent:
    entity_id: str
    volume_percent: int | None = None
    muted: bool | None = None
    state: str | None = None


class HomeAssistantMediaPlayerListener:
    """Background listener for HA media_player audio attribute updates."""

    def __init__(
        self,
        event_handler: Callable[[HaMediaPlayerStateEvent], None],
        *,
        credentials_factory: Callable[[], tuple[str, str] | None] = ha_rest.credentials_from_settings,
        connection_factory: Callable[[str], Any] | None = None,
        retry_delay: float = 5.0,
    ) -> None:
        self._event_handler = event_handler
        self._credentials_factory = credentials_factory
        self._connection_factory = connection_factory
        self._retry_delay = max(0.1, float(retry_delay))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._connection: Any | None = None
        self._logger = app_logging.get_logger("ha_ws")

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
        if self._credentials_factory() is None:
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="XTrayHomeAssistantWebSocket",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        connection = self._connection
        if connection is not None:
            try:
                connection.close()
            except Exception:
                self._logger.debug("HA websocket close failed", exc_info=True)
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None
        self._connection = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            credentials = self._credentials_factory()
            if credentials is None:
                return
            url, token = credentials
            try:
                connection = self._open_connection(url)
                self._connection = connection
                self._authenticate_and_subscribe(connection, token)
                self._listen(connection)
            except Exception as exc:
                if not self._stop_event.is_set():
                    self._logger.warning("HA websocket listener disconnected: %s", exc)
            finally:
                connection = self._connection
                self._connection = None
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        self._logger.debug("HA websocket cleanup failed", exc_info=True)
            if not self._stop_event.wait(self._retry_delay):
                continue
            break

    def _open_connection(self, base_url: str) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory(base_url)
        return _StdlibWebSocketConnection.connect(base_url)

    def _authenticate_and_subscribe(self, connection: Any, token: str) -> None:
        auth_required = _recv_required(connection, self._stop_event)
        if auth_required.get("type") != "auth_required":
            raise HaWebSocketError("Home Assistant did not request WebSocket auth")

        connection.send_json({"type": "auth", "access_token": token})
        auth_result = _recv_required(connection, self._stop_event)
        auth_type = auth_result.get("type")
        if auth_type == "auth_invalid":
            message = auth_result.get("message") or "invalid Home Assistant token"
            raise HaWebSocketError(str(message))
        if auth_type != "auth_ok":
            raise HaWebSocketError(f"unexpected Home Assistant auth response: {auth_type!r}")

        connection.send_json(
            {"id": 1, "type": "subscribe_events", "event_type": "state_changed"}
        )
        subscribe_result = _recv_required(connection, self._stop_event)
        if subscribe_result.get("type") != "result" or not subscribe_result.get("success"):
            error = subscribe_result.get("error") or subscribe_result
            raise HaWebSocketError(f"Home Assistant event subscription failed: {error!r}")

    def _listen(self, connection: Any) -> None:
        while not self._stop_event.is_set():
            message = connection.recv_json(timeout=1.0)
            if message is None:
                continue
            event = media_player_state_event_from_message(message)
            if event is None:
                continue
            try:
                self._event_handler(event)
            except Exception:
                self._logger.exception("HA media player event handler failed")


def media_player_state_event_from_message(
    message: dict[str, Any],
) -> HaMediaPlayerStateEvent | None:
    if message.get("type") != "event":
        return None
    event = message.get("event")
    if not isinstance(event, dict) or event.get("event_type") != "state_changed":
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    entity_id = str(data.get("entity_id") or "").strip()
    if not entity_id.casefold().startswith("media_player."):
        return None
    new_state = data.get("new_state")
    if not isinstance(new_state, dict):
        return None
    attributes = new_state.get("attributes")
    if not isinstance(attributes, dict):
        return None

    volume_percent = _volume_level_to_percent(attributes.get("volume_level"))
    raw_muted = attributes.get("is_volume_muted")
    muted = raw_muted if isinstance(raw_muted, bool) else None
    if volume_percent is None and muted is None:
        return None
    raw_state = new_state.get("state")
    state = str(raw_state) if raw_state is not None else None
    return HaMediaPlayerStateEvent(
        entity_id=entity_id,
        volume_percent=volume_percent,
        muted=muted,
        state=state,
    )


def _recv_required(connection: Any, stop_event: threading.Event) -> dict[str, Any]:
    while not stop_event.is_set():
        message = connection.recv_json(timeout=1.0)
        if isinstance(message, dict):
            return message
    raise HaWebSocketError("Home Assistant WebSocket listener stopped")


def _volume_level_to_percent(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return max(0, min(100, int(round(float(value) * 100))))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class _WebSocketTarget:
    secure: bool
    host: str
    port: int
    host_header: str
    resource: str


class _StdlibWebSocketConnection:
    def __init__(self, sock: socket.socket, *, buffer: bytes = b"") -> None:
        self._sock = sock
        self._buffer = bytearray(buffer)
        self._send_lock = threading.Lock()
        self._closed = False

    @classmethod
    def connect(cls, base_url: str, *, timeout: float = 10.0) -> _StdlibWebSocketConnection:
        target = _websocket_target(base_url)
        raw_socket = socket.create_connection((target.host, target.port), timeout=timeout)
        if target.secure:
            context = ssl.create_default_context()
            sock = context.wrap_socket(raw_socket, server_hostname=target.host)
        else:
            sock = raw_socket
        sock.settimeout(timeout)
        try:
            buffer = _perform_handshake(sock, target)
        except Exception:
            sock.close()
            raise
        sock.settimeout(1.0)
        return cls(sock, buffer=buffer)

    def send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._send_frame(0x1, body)

    def recv_json(self, *, timeout: float = 1.0) -> dict[str, Any] | None:
        while not self._closed:
            frame = self._recv_frame(timeout=timeout)
            if frame is None:
                return None
            opcode, payload = frame
            if opcode == 0x8:
                self.close()
                raise HaWebSocketError("Home Assistant closed the WebSocket")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                try:
                    data = json.loads(payload.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise HaWebSocketError("invalid JSON frame from Home Assistant") from exc
                return data if isinstance(data, dict) else None
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self._closed:
            raise HaWebSocketError("WebSocket is closed")
        length = len(payload)
        header = bytearray([0x80 | (opcode & 0x0F)])
        if length < 126:
            header.append(0x80 | length)
        elif length <= 0xFFFF:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        with self._send_lock:
            self._sock.sendall(bytes(header) + mask + masked)

    def _recv_frame(self, *, timeout: float) -> tuple[int, bytes] | None:
        if not self._wait_readable(timeout):
            return None
        header = self._read_exact(2)
        first, second = header
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        mask = self._read_exact(4) if masked else b""
        payload = self._read_exact(length) if length else b""
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def _wait_readable(self, timeout: float) -> bool:
        if self._buffer:
            return True
        readable, _, _ = select.select([self._sock], [], [], timeout)
        return bool(readable)

    def _read_exact(self, size: int) -> bytes:
        if size <= 0:
            return b""
        chunks: list[bytes] = []
        if self._buffer:
            take = min(size, len(self._buffer))
            chunks.append(bytes(self._buffer[:take]))
            del self._buffer[:take]
        remaining = size - sum(len(chunk) for chunk in chunks)
        while remaining:
            try:
                chunk = self._sock.recv(remaining)
            except TimeoutError:
                continue
            if not chunk:
                raise HaWebSocketError("Home Assistant closed the WebSocket")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


def _websocket_target(base_url: str) -> _WebSocketTarget:
    parsed = urllib.parse.urlsplit(str(base_url or "").strip())
    if parsed.scheme not in {"http", "https", "ws", "wss"}:
        raise HaWebSocketError("Home Assistant URL must start with http:// or https://")
    host = parsed.hostname
    if not host:
        raise HaWebSocketError("Home Assistant URL is missing a host")
    secure = parsed.scheme in {"https", "wss"}
    port = parsed.port or (443 if secure else 80)
    path = (parsed.path or "").rstrip("/")
    resource = f"{path}/api/websocket" if path else "/api/websocket"
    return _WebSocketTarget(
        secure=secure,
        host=host,
        port=port,
        host_header=_host_header(parsed, host, port, secure),
        resource=resource,
    )


def _host_header(
    parsed: urllib.parse.SplitResult,
    host: str,
    port: int,
    secure: bool,
) -> str:
    host_text = f"[{host}]" if ":" in host and not host.startswith("[") else host
    default_port = 443 if secure else 80
    if parsed.port is None and port == default_port:
        return host_text
    return f"{host_text}:{port}"


def _perform_handshake(sock: socket.socket, target: _WebSocketTarget) -> bytes:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {target.resource} HTTP/1.1\r\n"
        f"Host: {target.host_header}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("ascii"))
    raw = bytearray()
    while b"\r\n\r\n" not in raw:
        chunk = sock.recv(4096)
        if not chunk:
            raise HaWebSocketError("Home Assistant closed during WebSocket handshake")
        raw.extend(chunk)
        if len(raw) > 65536:
            raise HaWebSocketError("Home Assistant WebSocket handshake response too large")
    header_raw, _, leftover = bytes(raw).partition(b"\r\n\r\n")
    header_text = header_raw.decode("iso-8859-1")
    lines = header_text.split("\r\n")
    status_line = lines[0] if lines else ""
    if " 101 " not in f" {status_line} ":
        raise HaWebSocketError(f"Home Assistant WebSocket handshake failed: {status_line}")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().casefold()] = value.strip()
    expected = base64.b64encode(
        hashlib.sha1((key + _WEBSOCKET_GUID).encode("ascii")).digest()
    ).decode("ascii")
    if headers.get("sec-websocket-accept") != expected:
        raise HaWebSocketError("Home Assistant WebSocket handshake accept key mismatch")
    return leftover
