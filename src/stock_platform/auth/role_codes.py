"""Role 코드 정규화 — ADMIN / USER 두 권한만 허용.

DB·API 코드값은 소문자 `admin` / `user`.
레거시 입력(viewer, operator, trader)은 alias로 매핑한다.
"""

from __future__ import annotations

ALLOWED_ROLES = frozenset({"admin", "user"})

# 입력/레거시 JWT·JSONB → 정식 코드
_ROLE_ALIASES: dict[str, str] = {
    "viewer": "user",
    "operator": "admin",
    "trader": "user",
}


def normalize_role_code(code: str) -> str:
    cleaned = str(code).strip().lower()
    return _ROLE_ALIASES.get(cleaned, cleaned)


def normalize_role_codes(roles: list[str] | None) -> list[str]:
    """중복 제거·순서 유지한 정규화 목록."""

    unique: list[str] = []
    for role in roles or []:
        normalized = normalize_role_code(role)
        if normalized and normalized not in unique:
            unique.append(normalized)
    return unique


def has_valid_app_role(roles: list[str] | None) -> bool:
    """ADMIN 또는 USER 중 하나라도 있으면 True."""

    return bool(ALLOWED_ROLES.intersection(normalize_role_codes(roles)))
