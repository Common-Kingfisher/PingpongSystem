"""D2 A2.2：密码与 Session Token 安全基础。"""

from __future__ import annotations

import hashlib

import pytest

from app.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    validate_password_strength,
    verify_password,
)


def test_password_hash_uses_random_salt_and_verifies():
    first = hash_password("StrongPassword123", iterations=1000)
    second = hash_password("StrongPassword123", iterations=1000)

    assert first != second
    assert verify_password("StrongPassword123", first)
    assert not verify_password("WrongPassword123", first)


@pytest.mark.parametrize(
    "encoded",
    [
        None,
        "",
        "not-a-hash",
        "argon2$1$c2FsdA==$aGFzaA==",
        "pbkdf2_sha256$0$c2FsdA==$aGFzaA==",
        "pbkdf2_sha256$1$not-base64$not-base64",
    ],
)
def test_verify_password_rejects_invalid_hashes(encoded):
    assert not verify_password("StrongPassword123", encoded)


def test_session_token_is_random_and_only_hash_is_stable():
    token = generate_session_token()
    other = generate_session_token()

    assert token != other
    assert hash_session_token(token) == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert hash_session_token(token) != token


@pytest.mark.parametrize(
    ("password", "valid"),
    [
        ("StrongPassword123", True),
        ("Short123", False),
        ("OnlyLettersLong", False),
        ("1234567890123", False),
    ],
)
def test_password_strength_rules(password, valid):
    if valid:
        validate_password_strength(password)
        return
    with pytest.raises(ValueError):
        validate_password_strength(password)
