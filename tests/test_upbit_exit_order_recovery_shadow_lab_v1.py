"""Exit Order Recovery Shadow Lab V1 — focused research tests.

REAL cancel/reprice/market fallback must never run.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from stock_platform.database.base import Base
from stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.constants import (
    ACTION_MARKET_FALLBACK,
    ACTION_NO_ACTION,
    ACTION_REPRICE_BEST_BID,
    COHORT_HISTORICAL_CONTEXT,
    COHORT_PRIMARY_FORWARD,
    FEATURE_DEPLOY_EPOCH,
    R1_TRIGGER_AGE_SECONDS,
    R2_TRIGGER_AGE_SECONDS,
    R3_TRIGGER_AGE_SECONDS,
    STATUS_ACTIVE,
    STATUS_PAIRED,
    STATUS_TRIGGERED,
    VARIANT_R0,
    VARIANT_R1,
    VARIANT_R2,
    VARIANT_R3,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.entities import (
    UpbitExitOrderRecoveryShadowObservationEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.hooks import (
    on_exit_order_submitted,
)
from stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.service import (
    _apply_trigger,
    _is_auto_strategy_owned_exit,
    compare_variants,
    enroll_exit_order,
    list_observations,
    summarize_exit_order_recovery_lab,
    tick_active_observations,
)
from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.epoch import (
    ResearchFeatureEpochEntity,
)
from stock_platform.order.entities import TradingOrderEntity


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        ResearchFeatureEpochEntity.__table__,
        UpbitExitOrderRecoveryShadowObservationEntity.__table__,
    ]
    saved_schemas = {t.name: t.schema for t in tables}
    for t in tables:
        t.schema = None
    Base.metadata.create_all(engine, tables=tables)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    # order stub 저장소 — TradingOrderEntity 테이블 없이 session.get 패치
    s._test_orders: dict[int, SimpleNamespace] = {}  # type: ignore[attr-defined]
    real_get = s.get

    def _get(model, ident, **kwargs):  # noqa: ANN001
        if model is TradingOrderEntity:
            return s._test_orders.get(int(ident))  # type: ignore[attr-defined]
        return real_get(model, ident, **kwargs)

    s.get = _get  # type: ignore[method-assign]
    try:
        yield s
    finally:
        s.close()
        for t in tables:
            t.schema = saved_schemas[t.name]


def _make_order(
    session: Session,
    *,
    order_id: int = 1,
    side: str = "SELL",
    source: str = "POSITION_EXIT_MONITOR",
    order_source: str = "EXIT",
    strategy_id: int | None = 10,
    status: str = "ACCEPTED",
    created_at: datetime | None = None,
    price: str = "1000",
    qty: str = "1",
    filled: str = "0",
    remaining: str | None = None,
    binding_id: int | None = None,
) -> SimpleNamespace:
    created = created_at or (FEATURE_DEPLOY_EPOCH + timedelta(hours=1))
    rem = remaining if remaining is not None else qty
    meta: dict = {
        "source": source,
        "order_source": order_source,
        "exit_reason": "TRAILING_STOP",
    }
    if strategy_id is not None:
        meta["strategy_id"] = strategy_id
    if binding_id is not None:
        meta["binding_id"] = binding_id
    order = SimpleNamespace(
        order_id=order_id,
        client_order_id=f"C{order_id}",
        broker_order_id=None,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        exchange_code="UPBIT",
        symbol="KRW-SUI",
        side_code=side,
        order_type_code="LIMIT",
        order_quantity=Decimal(qty),
        order_price=Decimal(price),
        filled_quantity=Decimal(filled),
        remaining_quantity=Decimal(rem),
        average_fill_price=None,
        status_code=status,
        strategy_id=strategy_id,
        metadata_payload=meta,
        created_at=created,
        updated_at=created,
        filled_at=None,
        cancelled_at=None,
    )
    session._test_orders[order_id] = order  # type: ignore[attr-defined]
    return order


def test_a_real_order_never_cancelled_by_shadow(session: Session) -> None:
    """A: shadow tick은 REAL cancel 경로를 호출하지 않는다."""

    order = _make_order(session)
    enroll_exit_order(session, order_id=int(order.order_id))
    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.service._fetch_book",
        return_value={
            "trade_price": Decimal("1005"),
            "best_bid": Decimal("1004"),
            "best_ask": Decimal("1006"),
        },
    ):
        for row in session.scalars(
            select(UpbitExitOrderRecoveryShadowObservationEntity)
        ).all():
            row.enrolled_at = datetime.now(timezone.utc) - timedelta(
                seconds=R1_TRIGGER_AGE_SECONDS + 10
            )
        tick_active_observations(session, user_broker_account_id=1380)
    assert order.status_code == "ACCEPTED"
    assert order.order_price == Decimal("1000")


def test_b_r1_30m_trigger(session: Session) -> None:
    _make_order(session, order_id=2)
    enroll_exit_order(session, order_id=2)
    row = session.scalar(
        select(UpbitExitOrderRecoveryShadowObservationEntity).where(
            UpbitExitOrderRecoveryShadowObservationEntity.variant == VARIANT_R1,
            UpbitExitOrderRecoveryShadowObservationEntity.real_order_id == 2,
        )
    )
    assert row is not None
    row.enrolled_at = datetime.now(timezone.utc) - timedelta(
        seconds=R1_TRIGGER_AGE_SECONDS + 5
    )
    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.service._fetch_book",
        return_value={
            "trade_price": Decimal("999"),
            "best_bid": Decimal("998"),
            "best_ask": Decimal("1001"),
        },
    ):
        tick_active_observations(session, user_broker_account_id=1380)
    session.refresh(row)
    assert row.status == STATUS_TRIGGERED
    assert row.shadow_action == ACTION_REPRICE_BEST_BID
    assert row.shadow_reference_price == Decimal("998")


def test_c_r2_60m_trigger(session: Session) -> None:
    _make_order(session, order_id=3)
    enroll_exit_order(session, order_id=3)
    row = session.scalar(
        select(UpbitExitOrderRecoveryShadowObservationEntity).where(
            UpbitExitOrderRecoveryShadowObservationEntity.variant == VARIANT_R2,
            UpbitExitOrderRecoveryShadowObservationEntity.real_order_id == 3,
        )
    )
    assert row is not None
    row.enrolled_at = datetime.now(timezone.utc) - timedelta(
        seconds=R2_TRIGGER_AGE_SECONDS + 5
    )
    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.service._fetch_book",
        return_value={
            "trade_price": Decimal("999"),
            "best_bid": Decimal("997"),
            "best_ask": Decimal("1001"),
        },
    ):
        tick_active_observations(session, user_broker_account_id=1380)
    session.refresh(row)
    assert row.status == STATUS_TRIGGERED
    assert row.shadow_action == ACTION_REPRICE_BEST_BID


def test_d_r3_market_fallback_and_risk_ref(session: Session) -> None:
    """D+L: R3 market fallback + 962a502-style risk reference (trade/bid)."""

    _make_order(session, order_id=4)
    enroll_exit_order(session, order_id=4)
    row = session.scalar(
        select(UpbitExitOrderRecoveryShadowObservationEntity).where(
            UpbitExitOrderRecoveryShadowObservationEntity.variant == VARIANT_R3,
            UpbitExitOrderRecoveryShadowObservationEntity.real_order_id == 4,
        )
    )
    assert row is not None
    row.enrolled_at = datetime.now(timezone.utc) - timedelta(
        seconds=R3_TRIGGER_AGE_SECONDS + 5
    )
    book = {
        "trade_price": Decimal("1005"),
        "best_bid": Decimal("1004"),
        "best_ask": Decimal("1006"),
    }
    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.service._fetch_book",
        return_value=book,
    ):
        tick_active_observations(session, user_broker_account_id=1380)
    session.refresh(row)
    assert row.status == STATUS_TRIGGERED
    assert row.shadow_action == ACTION_MARKET_FALLBACK
    assert row.shadow_reference_price == Decimal("1005")
    assert (row.meta_json or {}).get("broker_price_semantics") == (
        "UPBIT_MARKET_SELL_VOLUME_ONLY"
    )
    assert row.shadow_fill_status == "EST_FILLED"
    assert row.evidence_quality in {"HIGH", "MEDIUM"}


def test_e_manual_excluded(session: Session) -> None:
    order = _make_order(
        session, order_id=5, source="MANUAL", order_source="MANUAL"
    )
    assert _is_auto_strategy_owned_exit(order, session) is False  # type: ignore[arg-type]
    res = enroll_exit_order(session, order_id=5)
    assert res.get("ok") is False


def test_f_buy_excluded(session: Session) -> None:
    order = _make_order(session, order_id=6, side="BUY")
    assert _is_auto_strategy_owned_exit(order, session) is False  # type: ignore[arg-type]


def test_g_strategy_owned_required(session: Session) -> None:
    order = _make_order(session, order_id=7, strategy_id=None)
    order.metadata_payload = {
        "source": "POSITION_EXIT_MONITOR",
        "order_source": "EXIT",
        "exit_reason": "TRAILING_STOP",
    }
    assert _is_auto_strategy_owned_exit(order, session) is False  # type: ignore[arg-type]


def test_h_partial_fill_remaining_qty(session: Session) -> None:
    _make_order(
        session,
        order_id=8,
        qty="10",
        filled="4",
        remaining="6",
        status="PARTIALLY_FILLED",
    )
    enroll_exit_order(session, order_id=8)
    row = session.scalar(
        select(UpbitExitOrderRecoveryShadowObservationEntity).where(
            UpbitExitOrderRecoveryShadowObservationEntity.variant == VARIANT_R1,
            UpbitExitOrderRecoveryShadowObservationEntity.real_order_id == 8,
        )
    )
    assert row is not None
    row.enrolled_at = datetime.now(timezone.utc) - timedelta(
        seconds=R1_TRIGGER_AGE_SECONDS + 5
    )
    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.service._fetch_book",
        return_value={
            "trade_price": Decimal("1000"),
            "best_bid": Decimal("999"),
            "best_ask": Decimal("1001"),
        },
    ):
        tick_active_observations(session, user_broker_account_id=1380)
    session.refresh(row)
    assert row.remaining_qty_at_trigger == Decimal("6")


def test_i_terminal_pairing(session: Session) -> None:
    order = _make_order(session, order_id=9, status="ACCEPTED")
    enroll_exit_order(session, order_id=9)
    order.status_code = "FILLED"
    order.average_fill_price = Decimal("1001")
    order.filled_quantity = Decimal("1")
    order.filled_at = datetime.now(timezone.utc)
    tick_active_observations(session, user_broker_account_id=1380)
    r0 = session.scalar(
        select(UpbitExitOrderRecoveryShadowObservationEntity).where(
            UpbitExitOrderRecoveryShadowObservationEntity.variant == VARIANT_R0,
            UpbitExitOrderRecoveryShadowObservationEntity.real_order_id == 9,
        )
    )
    assert r0 is not None
    assert r0.status == STATUS_PAIRED
    assert r0.real_terminal_state == "FILLED"
    assert r0.shadow_action == ACTION_NO_ACTION


def test_j_no_fake_historical_backfill_trigger(session: Session) -> None:
    """J: historical cohort는 tick 대상이 아니며 소급 trigger 없음."""

    old = FEATURE_DEPLOY_EPOCH - timedelta(days=1)
    _make_order(session, order_id=10, created_at=old)
    res = enroll_exit_order(session, order_id=10)
    assert res.get("cohort") == COHORT_HISTORICAL_CONTEXT
    row = session.scalar(
        select(UpbitExitOrderRecoveryShadowObservationEntity).where(
            UpbitExitOrderRecoveryShadowObservationEntity.variant == VARIANT_R1,
            UpbitExitOrderRecoveryShadowObservationEntity.real_order_id == 10,
        )
    )
    assert row is not None
    row.enrolled_at = datetime.now(timezone.utc) - timedelta(hours=2)
    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.service._fetch_book",
        return_value={
            "trade_price": Decimal("1"),
            "best_bid": Decimal("1"),
            "best_ask": Decimal("1"),
        },
    ):
        tick_active_observations(session, user_broker_account_id=1380)
    session.refresh(row)
    assert row.status == STATUS_ACTIVE
    assert row.shadow_action == ACTION_NO_ACTION


def test_k_research_failure_fail_open() -> None:
    """K: hook 예외가 REAL trading을 block하지 않음."""

    bad_session = MagicMock()
    bad_session.get.side_effect = RuntimeError("boom")
    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow.hooks.shadow_enabled",
        return_value=True,
    ):
        out = on_exit_order_submitted(
            bad_session, order_id=99, user_broker_account_id=1380
        )
    assert out.get("REAL_TRADING_BLOCKED") is False
    assert out.get("ok") is False


def test_m_duplicate_enroll_idempotent(session: Session) -> None:
    _make_order(session, order_id=11)
    a = enroll_exit_order(session, order_id=11)
    b = enroll_exit_order(session, order_id=11)
    assert a.get("enrolled") == 4
    assert b.get("skipped") == 4
    count = len(
        list(
            session.scalars(
                select(UpbitExitOrderRecoveryShadowObservationEntity).where(
                    UpbitExitOrderRecoveryShadowObservationEntity.real_order_id == 11
                )
            ).all()
        )
    )
    assert count == 4


def test_n_summary_api_flags(session: Session) -> None:
    _make_order(session, order_id=12)
    enroll_exit_order(session, order_id=12)
    summary = summarize_exit_order_recovery_lab(session, user_broker_account_id=1380)
    assert summary["REAL_POLICY_CHANGED"] is False
    assert summary["SHADOW_ONLY"] is True
    assert summary["AUTO_PROMOTION"] is False
    assert "R0" in summary["VARIANTS"]
    cmp = compare_variants(session, user_broker_account_id=1380)
    assert cmp["REAL_POLICY_CHANGED"] is False
    listed = list_observations(session, user_broker_account_id=1380, limit=10)
    assert listed["SHADOW_ONLY"] is True
    assert listed["count"] >= 4


def test_o_migration_revision_chain() -> None:
    """O: alembic revision 파일 down_revision 체인 확인."""

    from pathlib import Path

    path = Path("database/alembic/versions/eorlabv1a2b3_exit_order_recovery_shadow_lab_v1.py")
    text = path.read_text(encoding="utf-8")
    assert 'revision: str = "eorlabv1a2b3"' in text
    assert 'down_revision' in text and "wlshlabv1a2b3" in text


def test_apply_trigger_market_ref_semantics() -> None:
    """L unit: MARKET fallback reference = trade or bid (broker price None)."""

    row = UpbitExitOrderRecoveryShadowObservationEntity(
        user_broker_account_id=1380,
        variant=VARIANT_R3,
        cohort=COHORT_PRIMARY_FORWARD,
        symbol="KRW-X",
        real_order_id=99,
        real_created_at=datetime.now(timezone.utc),
        enrolled_at=datetime.now(timezone.utc),
        status=STATUS_ACTIVE,
        shadow_action=ACTION_NO_ACTION,
        meta_json={},
    )
    _apply_trigger(
        row,
        age_sec=3600,
        book={
            "trade_price": Decimal("159"),
            "best_bid": Decimal("158"),
            "best_ask": Decimal("160"),
        },
        remaining=Decimal("10"),
    )
    assert row.shadow_reference_price == Decimal("159")
    assert row.meta_json["broker_price_semantics"] == "UPBIT_MARKET_SELL_VOLUME_ONLY"


def test_primary_forward_cohort(session: Session) -> None:
    _make_order(
        session,
        order_id=13,
        created_at=FEATURE_DEPLOY_EPOCH + timedelta(minutes=5),
    )
    res = enroll_exit_order(session, order_id=13)
    assert res.get("cohort") == COHORT_PRIMARY_FORWARD
