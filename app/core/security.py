import hashlib
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


_ephemeral_store: dict[str, str] = {}

import threading
_key_lock = threading.Lock()


def _load_private_key() -> str:
    priv_path = Path(settings.JWT_PRIVATE_KEY_PATH)
    if priv_path.exists():
        return priv_path.read_text()

    with _key_lock:
        # Re-check inside lock in case another thread just wrote it
        if priv_path.exists():
            return priv_path.read_text()
        if "private" in _ephemeral_store:
            return _ephemeral_store["private"]

        import warnings
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        warnings.warn(
            f"JWT key file not found at {priv_path}. Generating and persisting an ephemeral "
            "key pair. This is safe for dev but MUST be replaced with a real key in production.",
            stacklevel=2,
        )

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        priv_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()
        pub_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

        # Persist to the configured paths so all workers share the same key pair
        try:
            priv_path.parent.mkdir(parents=True, exist_ok=True)
            priv_path.write_text(priv_pem)
            Path(settings.JWT_PUBLIC_KEY_PATH).write_text(pub_pem)
        except OSError:
            # Read-only filesystem (e.g. some container setups) — fall back to in-memory
            pass

        _ephemeral_store["private"] = priv_pem
        _ephemeral_store["public"] = pub_pem
        return priv_pem


def _load_public_key() -> str:
    pub_path = Path(settings.JWT_PUBLIC_KEY_PATH)
    if pub_path.exists():
        return pub_path.read_text()
    if "public" not in _ephemeral_store:
        _load_private_key()
    return _ephemeral_store["public"]


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
