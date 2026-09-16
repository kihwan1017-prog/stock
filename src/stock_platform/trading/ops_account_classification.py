"""운영 계좌 분류 — 관리자 UI/목록 필터용 (추측 최소화).

REAL_OPERATION: 명시적으로 운영 대상으로 판별되는 계좌만.
TEST/MOCK: alias·username 마커로 확실한 경우만.
그 외는 UNKNOWN (기본 UI에서 숨김, 삭제 금지).
"""

from __future__ import annotations

import re
from typing import Any

# 단일 운영자 SoT — 환경변수로 덮어쓸 수 있으나 코드 기본 보호 집합
DEFAULT_PROTECTED_UBA_IDS: frozenset[int] = frozenset({1380, 1381})

_TEST_ALIAS_RE = re.compile(
    r"(?i)(^|[_-])(test|mock|fixture|dummy|sandbox|kmock)([_-]|$)|"
    r"^test-|kmock_|fixture_"
)
_TEST_USER_RE = re.compile(r"(?i)^(legadopt_|test|pytest|fixture)")


def classify_uba_ops_class(
    *,
    uba_id: int,
    broker_code: str | None,
    account_alias: str | None,
    username: str | None = None,
    live_order_enabled: bool = False,
    last_synced_at: Any = None,
    deleted_at: Any = None,
    is_mock_credential: bool | None = None,
    environment_code: str | None = None,
    protected_uba_ids: frozenset[int] | None = None,
) -> str:
    """반환: REAL_OPERATION | TEST | PAPER | MOCK | LEGACY | UNKNOWN"""

    protected = protected_uba_ids or DEFAULT_PROTECTED_UBA_IDS
    alias = (account_alias or "").strip()
    user = (username or "").strip()
    env = (environment_code or "").strip().upper()

    if deleted_at is not None:
        return "LEGACY"

    if is_mock_credential is True or env in {"MOCK", "DEMO"}:
        return "MOCK"
    if env in {"TEST", "PAPER"}:
        return "TEST" if env == "TEST" else "PAPER"

    if "PAPER" in alias.upper() or "PAPER" in user.upper():
        return "PAPER"

    if _TEST_ALIAS_RE.search(alias) or _TEST_USER_RE.search(user):
        return "TEST"

    if int(uba_id) in protected:
        return "REAL_OPERATION"

    if live_order_enabled:
        return "REAL_OPERATION"

    # 실동기화 이력이 있는 활성 운영자 계좌 (예: KIWOOM 1381 LIVE OFF 상태)
    if last_synced_at is not None and user.lower() in {"kikicom", "admin"}:
        return "REAL_OPERATION"

    return "UNKNOWN"


def is_ops_visible(ops_class: str, *, include_test_accounts: bool) -> bool:
    if include_test_accounts:
        return ops_class != "LEGACY"
    return ops_class == "REAL_OPERATION"


def is_safe_to_soft_delete_candidate(
    *,
    ops_class: str,
    uba_id: int,
    order_count: int,
    outbox_count: int,
    position_snap_count: int,
    protected_uba_ids: frozenset[int] | None = None,
) -> bool:
    """하드 조건: TEST/MOCK + 거래 이력 0 + 보호 집합 제외."""

    protected = protected_uba_ids or DEFAULT_PROTECTED_UBA_IDS
    if int(uba_id) in protected:
        return False
    if ops_class not in {"TEST", "MOCK"}:
        return False
    if order_count != 0 or outbox_count != 0 or position_snap_count != 0:
        return False
    return True
