"""STEP 8-5-19 — Legacy account schema removal & skip recovery tests."""

from __future__ import annotations

import ast
from pathlib import Path

from tests.migration_helpers import (
    alembic_current_head,
    assert_revision_exists,
)


SRC = Path(__file__).resolve().parents[1] / "src" / "stock_platform"

# Adapter / masking / migration 경계만 허용
_ALLOWED_LOAD_ACCOUNT_NUMBER_FILES = frozenset(
    {
        # 명시적 제거 경로(raise only) — 호출 금지 검증용 파일은 AST에서 제외
    }
)


def test_step8_5_19_revision_head() -> None:
    assert_revision_exists("f9a0b1c2d3e4")
    assert_revision_exists("g0a1b2c3d4e5")
    head = alembic_current_head()
    assert_revision_exists(head)
    # 8-5-20에서 head 전진 — 본 revision 체인 존재만 검증


def test_no_operational_load_account_number_calls() -> None:
    """운영 코드에서 load(account_number=...) 호출 금지."""

    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith("broker/kiwoom/") or rel.startswith("broker/upbit/"):
            continue
        if "masking" in rel or "account_masking" in rel:
            continue
        text = path.read_text(encoding="utf-8")
        if "load(account_number=" not in text and "load(\n" not in text:
            # 빠른 필터
            if "account_number=" not in text or ".load(" not in text:
                continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # obj.load(...)
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "load":
                continue
            for kw in node.keywords:
                if kw.arg == "account_number":
                    offenders.append(f"{rel}:{node.lineno}")
    # account_state_service.load 정의는 **kwargs raise — 호출만 검사
    assert offenders == [], f"forbidden load(account_number=): {offenders}"


def test_position_limit_entity_has_no_account_number_column() -> None:
    from stock_platform.risk_engine.position_limit_entities import (
        PositionLimitEntity,
    )

    cols = {c.name for c in PositionLimitEntity.__table__.columns}
    assert "account_number" not in cols
    assert "user_broker_account_id" in cols
    assert "paper_account_id" in cols


def test_risk_event_entity_has_no_account_number_column() -> None:
    from stock_platform.risk_engine.risk_event_entities import RiskEventEntity

    cols = {c.name for c in RiskEventEntity.__table__.columns}
    assert "account_number" not in cols
    assert "user_broker_account_id" in cols
    assert "paper_account_id" in cols
    assert "masked_account_ref" in cols


def test_account_daily_loss_scope_constraint_exists() -> None:
    from stock_platform.risk_engine.daily_loss_entities import (
        AccountDailyLossEntity,
    )

    names = {
        c.name for c in AccountDailyLossEntity.__table__.constraints
    }
    assert any(
        "exactly_one_scope" in (n or "") for n in names
    )
