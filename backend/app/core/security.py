"""Password hashing and JWT issuance/verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import UTC, datetime, timedelta

from app.core.config import settings

try:  # Prefer a KDF; fall back to PBKDF2 from the stdlib if unavailable.
    from passlib.context import CryptContext

    _pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    _HAVE_PASSLIB = True
except Exception:  # pragma: no cover
    _pwd_context = None
    _HAVE_PASSLIB = False

_PBKDF2_ROUNDS = 260_000


def hash_password(password: str) -> str:
    if _HAVE_PASSLIB:
        return _pwd_context.hash(password)
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(plain: str, hashed: str) -> bool:
    try:
        if hashed.startswith("pbkdf2_sha256$"):
            _, rounds, salt_hex, dk_hex = hashed.split("$")
            dk = hashlib.pbkdf2_hmac(
                "sha256", plain.encode(), bytes.fromhex(salt_hex), int(rounds)
            )
            return hmac.compare_digest(dk.hex(), dk_hex)
        if _HAVE_PASSLIB:
            return _pwd_context.verify(plain, hashed)
        return False
    except Exception:
        return False


# --------------------------------------------------------------------------
# JWT (HS256, implemented with the stdlib to avoid a hard dependency)
# --------------------------------------------------------------------------
def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": subject, "exp": int(exp.timestamp()), "iat": int(now.timestamp())}
    segments = [
        _b64e(json.dumps(header).encode()),
        _b64e(json.dumps(payload).encode()),
    ]
    signing_input = ".".join(segments).encode()
    signature = hmac.new(
        settings.secret_key.encode(), signing_input, hashlib.sha256
    ).digest()
    segments.append(_b64e(signature))
    return ".".join(segments)


def decode_access_token(token: str) -> str | None:
    """Return the subject if the token is valid and unexpired, else None."""
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}".encode()
        expected = hmac.new(settings.secret_key.encode(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64d(sig_b64), expected):
            return None
        payload = json.loads(_b64d(payload_b64))
        if datetime.fromtimestamp(payload["exp"], tz=UTC) < datetime.now(UTC):
            return None
        return payload["sub"]
    except Exception:
        return None


def generate_demo_password() -> str:
    return secrets.token_urlsafe(12)
