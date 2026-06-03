"""HTTP server for authenticated encrypted sync bundle export."""
from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from xtray.core import app_logging

from . import __version__, bundle, crypto, discovery
from . import config as sync_config

CHALLENGE_TTL_SECONDS = 60
MAX_CHALLENGES_PER_MINUTE = 12


@dataclass
class Challenge:
    challenge_id: str
    client_nonce: str
    server_nonce: str
    created_at: float
    remote_ip: str


class ChallengeStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._challenges: dict[str, Challenge] = {}
        self._attempts: dict[str, list[float]] = {}

    def create(self, *, client_nonce: str, remote_ip: str) -> Challenge:
        now = time.time()
        with self._lock:
            self._prune(now)
            attempts = [ts for ts in self._attempts.get(remote_ip, []) if now - ts < 60]
            if len(attempts) >= MAX_CHALLENGES_PER_MINUTE:
                raise PermissionError("too many sync challenge attempts")
            attempts.append(now)
            self._attempts[remote_ip] = attempts
            challenge = Challenge(
                challenge_id=secrets.token_urlsafe(24),
                client_nonce=client_nonce,
                server_nonce=crypto.random_b64(32),
                created_at=now,
                remote_ip=remote_ip,
            )
            self._challenges[challenge.challenge_id] = challenge
            return challenge

    def pop(self, challenge_id: str, remote_ip: str) -> Challenge | None:
        now = time.time()
        with self._lock:
            self._prune(now)
            challenge = self._challenges.pop(challenge_id, None)
        if challenge is None:
            return None
        if challenge.remote_ip != remote_ip:
            return None
        if now - challenge.created_at > CHALLENGE_TTL_SECONDS:
            return None
        return challenge

    def _prune(self, now: float) -> None:
        expired = [
            challenge_id
            for challenge_id, challenge in self._challenges.items()
            if now - challenge.created_at > CHALLENGE_TTL_SECONDS
        ]
        for challenge_id in expired:
            self._challenges.pop(challenge_id, None)
        for remote_ip, attempts in list(self._attempts.items()):
            fresh = [ts for ts in attempts if now - ts < 60]
            if fresh:
                self._attempts[remote_ip] = fresh
            else:
                self._attempts.pop(remote_ip, None)


class SyncHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int]) -> None:
        self.challenge_store = ChallengeStore()
        super().__init__(server_address, SyncRequestHandler)


class SyncRequestHandler(BaseHTTPRequestHandler):
    server: SyncHTTPServer

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        app_logging.get_logger("sync").debug("HTTP " + format, *args)

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        if self.path == "/sync/v1/metadata":
            self._write_json(self._metadata())
            return
        if self.path == "/sync/v1/preview":
            self._write_json(bundle.create_preview())
            return
        self._write_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        if self.path == "/sync/v1/challenge":
            self._handle_challenge()
            return
        if self.path == "/sync/v1/bundle":
            self._handle_bundle()
            return
        self._write_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def _handle_challenge(self) -> None:
        if not _server_ready():
            self._write_json({"error": "sync is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
            return
        request = self._read_json()
        client_nonce = str(request.get("client_nonce") or "")
        if not client_nonce:
            self._write_json({"error": "client_nonce is required"}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            challenge = self.server.challenge_store.create(
                client_nonce=client_nonce,
                remote_ip=self.client_address[0],
            )
        except PermissionError as exc:
            self._write_json({"error": str(exc)}, status=HTTPStatus.TOO_MANY_REQUESTS)
            return
        self._write_json(
            {
                "challenge_id": challenge.challenge_id,
                "server_nonce": challenge.server_nonce,
                "expires_in": CHALLENGE_TTL_SECONDS,
            }
        )

    def _handle_bundle(self) -> None:
        if not _server_ready():
            self._write_json({"error": "sync is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
            return
        request = self._read_json()
        challenge_id = str(request.get("challenge_id") or "")
        proof = str(request.get("proof") or "")
        challenge = self.server.challenge_store.pop(challenge_id, self.client_address[0])
        if challenge is None:
            self._write_json({"error": "invalid or expired challenge"}, status=HTTPStatus.UNAUTHORIZED)
            return
        password = sync_config.get_password()
        settings = sync_config.load_sync_settings()
        if not password:
            self._write_json({"error": "sync password is not configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
            return
        try:
            base_key = crypto.derive_base_key(password, settings.salt)
        except Exception as exc:
            self._write_json({"error": str(exc)}, status=HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if not crypto.verify_client_proof(
            base_key,
            challenge_id=challenge.challenge_id,
            client_nonce=challenge.client_nonce,
            server_nonce=challenge.server_nonce,
            proof=proof,
        ):
            self._write_json({"error": "invalid sync password"}, status=HTTPStatus.UNAUTHORIZED)
            return
        session_key = crypto.derive_session_key(
            base_key,
            challenge_id=challenge.challenge_id,
            client_nonce=challenge.client_nonce,
            server_nonce=challenge.server_nonce,
        )
        encrypted = crypto.encrypt_json(bundle.create_bundle(), session_key)
        self._write_json({"schema": "xtray.sync.encrypted.v1", **encrypted})

    def _metadata(self) -> dict[str, Any]:
        settings = sync_config.load_sync_settings()
        return {
            "protocol": discovery.PROTOCOL,
            "api_version": 1,
            "xtray_sync_version": __version__,
            "instance_id": settings.instance_id,
            "peer_name": settings.peer_name,
            "hostname": discovery.announcement(settings)["hostname"],
            "port": settings.port,
            "discovery_port": settings.discovery_port,
            "salt": settings.salt,
            "capabilities": list(discovery.CAPABILITIES),
            "ready": _server_ready(),
        }

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(min(length, 1024 * 1024))
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _server_ready() -> bool:
    settings = sync_config.load_sync_settings()
    return bool(settings.enabled and sync_config.password_available())


class ServerThread:
    def __init__(self, *, host: str = "0.0.0.0", port: int | None = None) -> None:
        settings = sync_config.load_sync_settings()
        self.host = host
        self.port = settings.port if port is None else int(port)
        self.server: SyncHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self.server = SyncHTTPServer((self.host, self.port))
        self.port = int(self.server.server_address[1])
        self._thread = threading.Thread(
            target=self.server.serve_forever,
            name="xtray-sync-http",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
