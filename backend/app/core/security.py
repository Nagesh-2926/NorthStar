from datetime import datetime, timedelta, timezone
from typing import Any
import jwt
from pwdlib import PasswordHash

password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password, password_hash)
    except Exception:
        return False


def create_access_token(subject: str, role: str, secret: str, expires_minutes: int,
                        algorithm: str = "HS256", token_version: int = 0) -> str:
    now = datetime.now(timezone.utc)
    claims: dict[str, Any] = {"sub": subject, "role": role, "iat": now,
        "exp": now + timedelta(minutes=expires_minutes), "type": "access",
        "ver": token_version}
    return jwt.encode(claims, secret, algorithm=algorithm)
