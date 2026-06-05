"""Password-based challenge/response and AES-GCM helpers."""
from __future__ import annotations

import base64
import hmac
import json
import os
from hashlib import sha256
from typing import Any

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
except ImportError as exc:  # pragma: no cover - dependency is declared
    InvalidTag = None  # type: ignore[assignment]
    AESGCM = None  # type: ignore[assignment]
    HKDF = None  # type: ignore[assignment]
    PBKDF2HMAC = None  # type: ignore[assignment]
    hashes = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


KDF_ITERATIONS = 120_000
PROTOCOL_CONTEXT = b"xtray-sync-v1"


class CryptoUnavailable(RuntimeError):
    """Raised when the cryptography dependency is not installed."""


class InvalidPassword(RuntimeError):
    """Raised when a password cannot decrypt or authenticate a bundle."""


def random_b64(size: int = 32) -> str:
    return _b64encode(os.urandom(size))


def derive_base_key(password: str, salt_b64: str) -> bytes:
    _ensure_crypto()
    password_bytes = str(password or "").encode("utf-8")
    salt = _b64decode(salt_b64)
    return PBKDF2HMAC(  # type: ignore[misc,operator]
        algorithm=hashes.SHA256(),  # type: ignore[union-attr]
        length=32,
        salt=salt,
        iterations=KDF_ITERATIONS,
    ).derive(password_bytes)


def client_proof(
    base_key: bytes,
    *,
    challenge_id: str,
    client_nonce: str,
    server_nonce: str,
) -> str:
    return _b64encode(
        hmac.new(
            base_key,
            b"|".join(
                (
                    PROTOCOL_CONTEXT,
                    b"client-proof",
                    challenge_id.encode("utf-8"),
                    client_nonce.encode("ascii"),
                    server_nonce.encode("ascii"),
                )
            ),
            sha256,
        ).digest()
    )


def verify_client_proof(
    base_key: bytes,
    *,
    challenge_id: str,
    client_nonce: str,
    server_nonce: str,
    proof: str,
) -> bool:
    expected = client_proof(
        base_key,
        challenge_id=challenge_id,
        client_nonce=client_nonce,
        server_nonce=server_nonce,
    )
    return hmac.compare_digest(expected, str(proof or ""))


def derive_session_key(
    base_key: bytes,
    *,
    challenge_id: str,
    client_nonce: str,
    server_nonce: str,
) -> bytes:
    _ensure_crypto()
    return HKDF(  # type: ignore[misc,operator]
        algorithm=hashes.SHA256(),  # type: ignore[union-attr]
        length=32,
        salt=_b64decode(client_nonce) + _b64decode(server_nonce),
        info=b"|".join(
            (
                PROTOCOL_CONTEXT,
                b"session",
                challenge_id.encode("utf-8"),
            )
        ),
    ).derive(base_key)


def encrypt_json(payload: dict[str, Any], session_key: bytes) -> dict[str, str]:
    _ensure_crypto()
    nonce = os.urandom(12)
    plaintext = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(session_key).encrypt(  # type: ignore[operator]
        nonce,
        plaintext,
        PROTOCOL_CONTEXT,
    )
    return {"nonce": _b64encode(nonce), "ciphertext": _b64encode(ciphertext)}


def decrypt_json(envelope: dict[str, Any], session_key: bytes) -> dict[str, Any]:
    _ensure_crypto()
    try:
        nonce = _b64decode(str(envelope.get("nonce") or ""))
        ciphertext = _b64decode(str(envelope.get("ciphertext") or ""))
        plaintext = AESGCM(session_key).decrypt(  # type: ignore[operator]
            nonce,
            ciphertext,
            PROTOCOL_CONTEXT,
        )
        payload = json.loads(plaintext.decode("utf-8"))
    except Exception as exc:
        if InvalidTag is not None and isinstance(exc, InvalidTag):
            raise InvalidPassword("invalid sync password") from exc
        raise InvalidPassword("could not decrypt sync payload") from exc
    if not isinstance(payload, dict):
        raise InvalidPassword("sync payload must be an object")
    return payload


def _ensure_crypto() -> None:
    if _IMPORT_ERROR is not None:
        raise CryptoUnavailable(
            "cryptography is not installed; install xtray-sync dependencies"
        ) from _IMPORT_ERROR


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))
