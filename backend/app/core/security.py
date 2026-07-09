"""Security primitives: password hashing, JWT, and API-key generation.

Pure functions with no DB/Redis coupling so they're trivially unit-testable.
Services compose these with the datastores to implement auth flows.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import Settings
from app.core.exceptions import UnauthorizedError

# bcrypt hard-limits the input to 72 bytes; encode then truncate to stay within it.
_BCRYPT_MAX_BYTES = 72

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"

API_KEY_PREFIX = "sk_live_"


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(plain: str) -> str:
    pw = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    pw = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(pw, hashed.encode("utf-8"))
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def _encode(settings: Settings, payload: dict[str, Any], expires: timedelta) -> str:
    now = datetime.now(UTC)
    to_encode = {**payload, "iat": now, "exp": now + expires}
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    role: str,
) -> str:
    return _encode(
        settings,
        {
            "sub": str(user_id),
            "org": str(organization_id),
            "role": role,
            "type": ACCESS_TOKEN_TYPE,
        },
        timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(
    settings: Settings,
    *,
    user_id: uuid.UUID,
) -> tuple[str, str]:
    """Return (token, jti). The jti is stored in Redis to allow revocation."""
    jti = uuid.uuid4().hex
    token = _encode(
        settings,
        {"sub": str(user_id), "type": REFRESH_TOKEN_TYPE, "jti": jti},
        timedelta(days=settings.refresh_token_expire_days),
    )
    return token, jti


def decode_token(settings: Settings, token: str, *, expected_type: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Token has expired", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid token", code="invalid_token") from exc

    if payload.get("type") != expected_type:
        raise UnauthorizedError("Wrong token type", code="invalid_token")
    return payload


# --------------------------------------------------------------------------- #
# API keys
# --------------------------------------------------------------------------- #
def generate_api_key() -> tuple[str, str, str]:
    """Return (plaintext, prefix, sha256_hash).

    plaintext is shown to the user once; only prefix + hash are persisted.
    """
    secret = secrets.token_urlsafe(32)
    plaintext = f"{API_KEY_PREFIX}{secret}"
    prefix = plaintext[: len(API_KEY_PREFIX) + 6]
    return plaintext, prefix, hash_api_key(plaintext)


def hash_api_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
