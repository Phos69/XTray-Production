"""HTTP client for encrypted XTray LAN sync imports."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from . import bundle, crypto, discovery


@dataclass(frozen=True)
class SyncPeer:
    host: str
    port: int
    instance_id: str | None = None
    peer_name: str | None = None

    @classmethod
    def from_peer(cls, peer: discovery.Peer) -> SyncPeer:
        return cls(
            host=peer.host,
            port=peer.port,
            instance_id=peer.instance_id,
            peer_name=peer.peer_name,
        )

    @classmethod
    def parse(cls, value: str) -> SyncPeer:
        text = str(value or "").strip()
        if not text:
            raise ValueError("peer target is required")
        if ":" in text:
            host, port_text = text.rsplit(":", 1)
            return cls(host=host.strip(), port=int(port_text))
        return cls(host=text, port=37665)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def metadata(peer: SyncPeer, *, timeout: float = 5.0) -> dict[str, Any]:
    return _get_json(f"{peer.base_url}/sync/v1/metadata", timeout=timeout)


def preview(peer: SyncPeer, *, timeout: float = 5.0) -> dict[str, Any]:
    return _get_json(f"{peer.base_url}/sync/v1/preview", timeout=timeout)


def fetch_bundle(peer: SyncPeer, password: str, *, timeout: float = 15.0) -> dict[str, Any]:
    meta = metadata(peer, timeout=timeout)
    if not meta.get("ready"):
        raise RuntimeError("peer sync is not ready")
    salt = str(meta.get("salt") or "")
    client_nonce = crypto.random_b64(32)
    challenge = _post_json(
        f"{peer.base_url}/sync/v1/challenge",
        {"client_nonce": client_nonce},
        timeout=timeout,
    )
    challenge_id = str(challenge.get("challenge_id") or "")
    server_nonce = str(challenge.get("server_nonce") or "")
    base_key = crypto.derive_base_key(password, salt)
    proof = crypto.client_proof(
        base_key,
        challenge_id=challenge_id,
        client_nonce=client_nonce,
        server_nonce=server_nonce,
    )
    encrypted = _post_json(
        f"{peer.base_url}/sync/v1/bundle",
        {"challenge_id": challenge_id, "proof": proof},
        timeout=timeout,
    )
    session_key = crypto.derive_session_key(
        base_key,
        challenge_id=challenge_id,
        client_nonce=client_nonce,
        server_nonce=server_nonce,
    )
    return crypto.decrypt_json(encrypted, session_key)


def import_from_peer(
    peer: SyncPeer,
    password: str,
    *,
    options: bundle.ImportOptions | None = None,
    timeout: float = 15.0,
) -> bundle.ImportResult:
    payload = fetch_bundle(peer, password, timeout=timeout)
    return bundle.import_bundle(payload, options=options)


def peer_from_discovery_target(target: str | None, peers: list[discovery.Peer]) -> SyncPeer:
    if target:
        needle = target.casefold()
        for peer in peers:
            if needle in {
                peer.instance_id.casefold(),
                peer.peer_name.casefold(),
                peer.hostname.casefold(),
                peer.host.casefold(),
                f"{peer.host}:{peer.port}".casefold(),
            }:
                return SyncPeer.from_peer(peer)
        return SyncPeer.parse(target)
    if len(peers) == 1:
        return SyncPeer.from_peer(peers[0])
    if not peers:
        raise RuntimeError("no XTray sync peers discovered")
    raise RuntimeError("multiple peers discovered; pass a peer name, id, or host:port")


def _get_json(url: str, *, timeout: float) -> dict[str, Any]:
    req = request.Request(url, method="GET")
    return _open_json(req, timeout=timeout)


def _post_json(url: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    return _open_json(req, timeout=timeout)


def _open_json(req: request.Request, *, timeout: float) -> dict[str, Any]:
    try:
        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - LAN peer URL
            raw = response.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(detail or str(exc)) from exc
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("sync response must be a JSON object")
    return data
