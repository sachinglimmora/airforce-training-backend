import hashlib
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import bcrypt
import jwt

from app.config import get_settings

settings = get_settings()


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _load_private_key() -> str:
    path = Path(settings.JWT_PRIVATE_KEY_PATH)
    if path.exists():
        return path.read_text()
    # Dev fallback: generate ephemeral key (NOT for production)
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _ephemeral_store["private"] = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    _ephemeral_store["public"] = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return _ephemeral_store["private"]


def _load_public_key() -> str:
    path = Path(settings.JWT_PUBLIC_KEY_PATH)
    if path.exists():
        return path.read_text()
    if "public" not in _ephemeral_store:
        _load_private_key()
    return _ephemeral_store["public"]


_ephemeral_store: dict[str, str] = {}


def create_access_token(user_id: str, roles: list[str]) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "roles": roles,
        "iat": now,
        "exp": now + timedelta(seconds=settings.JWT_ACCESS_TTL_SECONDS),
        "jti": str(uuid.uuid4()),
        "iss": settings.JWT_ISSUER,
    }
    return jwt.encode(payload, _load_private_key(), algorithm="RS256")


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token,
        _load_public_key(),
        algorithms=["RS256"],
        options={"verify_exp": True},
    )


def generate_refresh_token() -> str:
    return f"rt_{secrets.token_urlsafe(48)}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_jwks() -> dict:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    import base64

    pub_pem = _load_public_key().encode()
    pub_key = load_pem_public_key(pub_pem)
    pub_numbers = pub_key.public_key().public_numbers() if hasattr(pub_key, "public_key") else pub_key.public_numbers()

    def int_to_base64url(n: int) -> str:
        length = (n.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()

    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "n": int_to_base64url(pub_numbers.n),
                "e": int_to_base64url(pub_numbers.e),
            }
        ]
    }
