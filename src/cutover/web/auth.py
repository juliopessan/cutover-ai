from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime, timedelta

ITERATIONS = 600_000
SESSION_DAYS = 7
MIN_PASSWORD_LENGTH = 10
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 300


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), expected)


def new_session_token() -> tuple[str, str, str]:
    """Return (token for the cookie, hash to store, expiry). Only the hash is persisted."""
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(UTC) + timedelta(days=SESSION_DAYS)).isoformat()
    return token, hash_token(token), expires


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_is_valid(expires_at: str) -> bool:
    return datetime.fromisoformat(expires_at) > datetime.now(UTC)


class LoginThrottle:
    """In-memory brute-force guard keyed by (client, email). Per process, resets on restart."""

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str) -> list[float]:
        cutoff = time.monotonic() - LOCKOUT_SECONDS
        recent = [t for t in self._failures.get(key, []) if t > cutoff]
        self._failures[key] = recent
        return recent

    def blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= MAX_FAILED_ATTEMPTS

    def record_failure(self, key: str) -> None:
        self._recent(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
