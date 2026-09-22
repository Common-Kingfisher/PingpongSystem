"""认证安全基础：密码哈希、Token 生成与 Token 哈希。

D2 只使用 Python 标准库，不引入 ORM、JWT 或第三方密码库。数据库只保存
服务端 Session Token 的 SHA-256 哈希，明文 Token 仅在一次响应中返回。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets


PBKDF2_ALGORITHM = "pbkdf2_sha256"
DEFAULT_PBKDF2_ITERATIONS = 600_000
PASSWORD_MIN_LENGTH = 12
_PASSWORD_HAS_LETTER = re.compile(r"[A-Za-z]")
_PASSWORD_HAS_DIGIT = re.compile(r"\d")


def pbkdf2_iterations() -> int:
    """返回本次哈希使用的迭代次数，测试或部署可通过环境变量覆盖。"""
    raw = os.environ.get("AUTH_PBKDF2_ITERATIONS")
    if raw is None:
        return DEFAULT_PBKDF2_ITERATIONS
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("AUTH_PBKDF2_ITERATIONS 必须是整数") from exc
    if value < 1:
        raise ValueError("AUTH_PBKDF2_ITERATIONS 必须大于 0")
    return value


def validate_password_strength(password: str) -> None:
    """校验新密码强度；错误信息不包含密码本身。"""
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"密码至少需要 {PASSWORD_MIN_LENGTH} 个字符")
    if not _PASSWORD_HAS_LETTER.search(password):
        raise ValueError("密码必须至少包含一个字母")
    if not _PASSWORD_HAS_DIGIT.search(password):
        raise ValueError("密码必须至少包含一个数字")


def hash_password(password: str, iterations: int | None = None) -> str:
    """生成 ``pbkdf2_sha256$迭代次数$盐$哈希`` 格式的密码哈希。"""
    if not password:
        raise ValueError("密码不能为空")
    rounds = pbkdf2_iterations() if iterations is None else iterations
    if rounds < 1:
        raise ValueError("PBKDF2 迭代次数必须大于 0")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    salt_b64 = base64.b64encode(salt).decode("ascii")
    digest_b64 = base64.b64encode(digest).decode("ascii")
    return f"{PBKDF2_ALGORITHM}${rounds}${salt_b64}${digest_b64}"


def verify_password(password: str, encoded: str | None) -> bool:
    """校验密码；损坏哈希、未知算法或非法 Base64 一律返回 False。"""
    if not password or not encoded:
        return False
    try:
        algorithm, rounds_text, salt_b64, digest_b64 = encoded.split("$", 3)
        if algorithm != PBKDF2_ALGORITHM:
            return False
        rounds = int(rounds_text)
        if rounds < 1:
            return False
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(digest_b64, validate=True)
    except (TypeError, ValueError):
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, rounds
    )
    return hmac.compare_digest(candidate, expected)


def generate_session_token() -> str:
    """生成不可预测的服务端 Session Token。"""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Token 入库前统一转为 SHA-256 十六进制哈希。"""
    if not token:
        raise ValueError("Session Token 不能为空")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
