import pytest
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password


def test_password_hashing():
    plain = "MySecureP@ss123"
    hashed = hash_password(plain)
    assert hashed != plain
    assert verify_password(plain, hashed)
    assert not verify_password("wrong", hashed)


def test_access_token_roundtrip():
    token = create_access_token("user-123", ["trainee"])
    payload = decode_access_token(token)
    assert payload["sub"] == "user-123"
    assert "trainee" in payload["roles"]


def test_token_expired(monkeypatch):
    import jwt
    from datetime import UTC, datetime, timedelta
    from app.core.security import _load_private_key

    payload = {
        "sub": "user-123",
        "roles": ["trainee"],
        "iat": datetime.now(UTC) - timedelta(hours=2),
        "exp": datetime.now(UTC) - timedelta(hours=1),
        "jti": "test",
        "iss": "aegis-backend",
    }
    expired_token = jwt.encode(payload, _load_private_key(), algorithm="RS256")

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired_token)
