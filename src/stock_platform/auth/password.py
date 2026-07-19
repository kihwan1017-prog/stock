from __future__ import annotations

import bcrypt


class PasswordHasher:
    """bcrypt 비밀번호 해시."""

    @staticmethod
    def hash(password: str) -> str:
        if not password or len(password) < 8:
            raise ValueError(
                "비밀번호는 최소 8자 이상이어야 합니다."
            )
        hashed = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(rounds=12),
        )
        return hashed.decode("utf-8")

    @staticmethod
    def verify(password: str, password_hash: str) -> bool:
        if not password or not password_hash:
            return False
        try:
            return bcrypt.checkpw(
                password.encode("utf-8"),
                password_hash.encode("utf-8"),
            )
        except (ValueError, TypeError):
            return False
