"""Waiting Lifecycle Forward Shadow Lab V1 — focused research tests.

REAL waiting policy / entry / exit / reentry shadows must remain unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from stock_platform.database.base import Base
from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.epoch import (
    ResearchFeatureEpochEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.constants import (
    COHORT_PREEXISTING,
    COHORT_PRIMARY_FORWARD,
    EVT_ABSOLUTE_EXPIRED,
    EVT_BUY_FILLED,
    EVT_REAL_LATER_BOUGHT,
    R1_ABSOLUTE_EXPIRY_SECONDS,
    R1_SOFT_STALE_SECONDS,
    R2_ABSOLUTE_EXPIRY_SECONDS,
    R2_SOFT_STALE_SECONDS,
    R3_REPLACEMENT_SCORE_MARGIN,
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_REPLACED,
    STATUS_STALE,
    STATUS_SUCCESS_TERMINAL,
    VARIANT_R0,
    VARIANT_R1,
    VARIANT_R2,
    VARIANT_R3,
)
from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.entities import (
    UpbitWaitingLifecycleShadowEventEntity,
    UpbitWaitingLifecycleShadowObservationEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.policy import (
    policy_for,
)
from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.service import (
    compare_variants,
    enroll_waiting_opportunity,
    list_observations,
    observe_evaluation,
    observe_full_slot_block,
    observe_real_stage,
    shadow_age_seconds,
    summarize_waiting_lifecycle_lab,
    tick_active_observations,
)
from stock_platform.operation.upbit_full_market.waiting_lifecycle_policy import (
    WaitingLifecyclePolicy,
)


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # SQLite: drop schema from tables for in-memory tests
    tables = [
        ResearchFeatureEpochEntity.__table__,
        UpbitWaitingLifecycleShadowObservationEntity.__table__,
        UpbitWaitingLifecycleShadowEventEntity.__table__,
    ]
    for t in tables:
        t.schema = None
    Base.metadata.create_all(engine, tables=tables)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
        for t in tables:
            t.schema = "operation"


def _enroll(
    session: Session,
    *,
    selection_id: int,
    symbol: str = "KRW-TEST",
    score: float = 60.0,
    at: datetime | None = None,
    variants: tuple[str, ...] | None = None,
    cohort: str | None = None,
) -> dict:
    now = at or datetime.now(timezone.utc)
    return enroll_waiting_opportunity(
        session,
        user_broker_account_id=1380,
        symbol=symbol,
        selection_id=selection_id,
        waiting_created_at=now,
        candidate_id=selection_id,
        initial_score=score,
        cohort=cohort or COHORT_PRIMARY_FORWARD,
        variants=variants,
        now=now,
    )


def test_a_real_waiting_policy_unchanged() -> None:
    """A — REAL WaitingLifecyclePolicy defaults untouched."""

    pol = WaitingLifecyclePolicy()
    assert pol.soft_stale_seconds == 1800.0
    assert pol.hard_expire_no_signal_seconds == 5400.0
    assert pol.consecutive_no_signal_threshold == 3


def test_b_c_d_r1_stale_absolute_and_technical_pass_no_ttl_reset(
    session: Session,
) -> None:
    """B/C/D — R1 30m stale, 90m absolute; TECHNICAL_PASS does not reset TTL."""

    t0 = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
    _enroll(session, selection_id=1001, at=t0, variants=(VARIANT_R1,))
    row = session.scalar(
        select(UpbitWaitingLifecycleShadowObservationEntity).where(
            UpbitWaitingLifecycleShadowObservationEntity.variant == VARIANT_R1
        )
    )
    assert row is not None
    observe_evaluation(
        session,
        user_broker_account_id=1380,
        symbol="KRW-TEST",
        selection_id=1001,
        decision="TECHNICAL_PASS",
        now=t0 + timedelta(minutes=45),
    )
    session.refresh(row)
    assert shadow_age_seconds(row, now=t0 + timedelta(minutes=45)) >= 45 * 60
    assert _aware_cmp(row.ttl_anchor_at) == t0
    # TECHNICAL_PASS 이후에도 absolute TTL 진행
    later = t0 + timedelta(seconds=R1_ABSOLUTE_EXPIRY_SECONDS + 5)
    assert shadow_age_seconds(row, now=later) >= R1_ABSOLUTE_EXPIRY_SECONDS
    tick_active_observations(session, now=later)
    session.refresh(row)
    assert row.status == STATUS_EXPIRED
    assert row.expired_at is not None


def _aware_cmp(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def test_e_f_r2_20m_60m(session: Session) -> None:
    """E/F — R2 soft 20m / absolute 60m."""

    t0 = datetime(2026, 8, 31, 11, 0, tzinfo=timezone.utc)
    _enroll(session, selection_id=1002, at=t0, variants=(VARIANT_R2,))
    row = session.scalar(
        select(UpbitWaitingLifecycleShadowObservationEntity).where(
            UpbitWaitingLifecycleShadowObservationEntity.variant == VARIANT_R2
        )
    )
    assert policy_for(VARIANT_R2).soft_stale_seconds == R2_SOFT_STALE_SECONDS
    assert (
        policy_for(VARIANT_R2).absolute_expiry_seconds == R2_ABSOLUTE_EXPIRY_SECONDS
    )
    soft_at = t0 + timedelta(seconds=R2_SOFT_STALE_SECONDS + 5)
    assert shadow_age_seconds(row, now=soft_at) >= R2_SOFT_STALE_SECONDS
    tick_active_observations(session, now=soft_at)
    session.refresh(row)
    assert row.status in {STATUS_STALE, STATUS_EXPIRED}
    abs_at = t0 + timedelta(seconds=R2_ABSOLUTE_EXPIRY_SECONDS + 5)
    tick_active_observations(session, now=abs_at)
    session.refresh(row)
    assert row.status == STATUS_EXPIRED


def test_g_h_r3_score_replacement_margin(session: Session) -> None:
    """G/H — R3 +10 margin replace / insufficient margin no replace."""

    t0 = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
    # fill capacity with stale low-score rows
    for i in range(10):
        _enroll(
            session,
            selection_id=2000 + i,
            symbol=f"KRW-S{i}",
            score=50.0 + i,
            at=t0,
            variants=(VARIANT_R3,),
        )
    # age all to soft stale
    tick_active_observations(
        session, now=t0 + timedelta(seconds=R1_SOFT_STALE_SECONDS + 1)
    )
    # insufficient margin
    bad = enroll_waiting_opportunity(
        session,
        user_broker_account_id=1380,
        symbol="KRW-NEW",
        selection_id=3001,
        waiting_created_at=t0 + timedelta(hours=1),
        initial_score=50.0 + R3_REPLACEMENT_SCORE_MARGIN - 0.1,
        cohort=COHORT_PRIMARY_FORWARD,
        variants=(VARIANT_R3,),
        now=t0 + timedelta(hours=1),
    )
    assert bad["variants"][VARIANT_R3].get("would_replace") is False
    # sufficient margin vs lowest (50.0)
    good = enroll_waiting_opportunity(
        session,
        user_broker_account_id=1380,
        symbol="KRW-NEW2",
        selection_id=3002,
        waiting_created_at=t0 + timedelta(hours=1),
        initial_score=50.0 + R3_REPLACEMENT_SCORE_MARGIN,
        cohort=COHORT_PRIMARY_FORWARD,
        variants=(VARIANT_R3,),
        now=t0 + timedelta(hours=1),
    )
    assert good["variants"][VARIANT_R3].get("would_replace") is True
    replaced = session.scalar(
        select(UpbitWaitingLifecycleShadowObservationEntity).where(
            UpbitWaitingLifecycleShadowObservationEntity.status == STATUS_REPLACED,
            UpbitWaitingLifecycleShadowObservationEntity.variant == VARIANT_R3,
        )
    )
    assert replaced is not None


def test_i_variant_state_isolation(session: Session) -> None:
    """I — R1/R2 absolute clocks are independent."""

    t0 = datetime(2026, 8, 31, 13, 0, tzinfo=timezone.utc)
    _enroll(session, selection_id=4001, at=t0)
    tick_active_observations(
        session, now=t0 + timedelta(seconds=R2_ABSOLUTE_EXPIRY_SECONDS + 1)
    )
    r1 = session.scalar(
        select(UpbitWaitingLifecycleShadowObservationEntity).where(
            UpbitWaitingLifecycleShadowObservationEntity.selection_id == 4001,
            UpbitWaitingLifecycleShadowObservationEntity.variant == VARIANT_R1,
        )
    )
    r2 = session.scalar(
        select(UpbitWaitingLifecycleShadowObservationEntity).where(
            UpbitWaitingLifecycleShadowObservationEntity.selection_id == 4001,
            UpbitWaitingLifecycleShadowObservationEntity.variant == VARIANT_R2,
        )
    )
    assert r2 is not None and r2.status == STATUS_EXPIRED
    assert r1 is not None and r1.status != STATUS_EXPIRED


def test_j_same_symbol_new_selection_isolation(session: Session) -> None:
    """J — same symbol, new selection_id → separate observation."""

    t0 = datetime.now(timezone.utc)
    _enroll(session, selection_id=5001, symbol="KRW-AAA", at=t0)
    _enroll(session, selection_id=5002, symbol="KRW-AAA", at=t0)
    n = session.scalars(
        select(UpbitWaitingLifecycleShadowObservationEntity).where(
            UpbitWaitingLifecycleShadowObservationEntity.symbol == "KRW-AAA",
            UpbitWaitingLifecycleShadowObservationEntity.variant == VARIANT_R1,
        )
    ).all()
    assert len(list(n)) == 2


def test_k_l_restart_and_refresh_do_not_reset_ttl(session: Session) -> None:
    """K/L — re-enroll same selection is ALREADY_ENROLLED; ttl_anchor stable."""

    t0 = datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc)
    _enroll(session, selection_id=6001, at=t0, variants=(VARIANT_R1,))
    row = session.scalar(
        select(UpbitWaitingLifecycleShadowObservationEntity).where(
            UpbitWaitingLifecycleShadowObservationEntity.selection_id == 6001,
            UpbitWaitingLifecycleShadowObservationEntity.variant == VARIANT_R1,
        )
    )
    anchor = row.ttl_anchor_at
    again = _enroll(
        session,
        selection_id=6001,
        at=t0 + timedelta(hours=2),
        variants=(VARIANT_R1,),
    )
    assert again["variants"][VARIANT_R1]["reason"] == "ALREADY_ENROLLED"
    session.refresh(row)
    assert row.ttl_anchor_at == anchor
    observe_evaluation(
        session,
        user_broker_account_id=1380,
        symbol="KRW-TEST",
        selection_id=6001,
        decision="BLOCK",
        block_reason="SHORT_MA_NOT_ABOVE_LONG_MA",
        now=t0 + timedelta(hours=1),
    )
    session.refresh(row)
    assert row.ttl_anchor_at == anchor


def test_m_n_o_buy_filled_and_later_bought(session: Session) -> None:
    """M/N/O — BUY_FILLED success; shadow expiry never blocks REAL later buy metric."""

    t0 = datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc)
    _enroll(session, selection_id=7001, at=t0, variants=(VARIANT_R1,))
    # success path
    observe_real_stage(
        session,
        user_broker_account_id=1380,
        symbol="KRW-TEST",
        selection_id=7001,
        stage="BUY_FILLED",
        now=t0 + timedelta(minutes=10),
    )
    row = session.scalar(
        select(UpbitWaitingLifecycleShadowObservationEntity).where(
            UpbitWaitingLifecycleShadowObservationEntity.selection_id == 7001,
            UpbitWaitingLifecycleShadowObservationEntity.variant == VARIANT_R1,
        )
    )
    assert row.status == STATUS_SUCCESS_TERMINAL
    assert row.real_buy_filled is True

    # later-bought path
    _enroll(session, selection_id=7002, at=t0, variants=(VARIANT_R1,))
    tick_active_observations(
        session, now=t0 + timedelta(seconds=R1_ABSOLUTE_EXPIRY_SECONDS)
    )
    observe_real_stage(
        session,
        user_broker_account_id=1380,
        symbol="KRW-TEST",
        selection_id=7002,
        stage="BUY_FILLED",
        now=t0 + timedelta(seconds=R1_ABSOLUTE_EXPIRY_SECONDS + 60),
    )
    row2 = session.scalar(
        select(UpbitWaitingLifecycleShadowObservationEntity).where(
            UpbitWaitingLifecycleShadowObservationEntity.selection_id == 7002,
            UpbitWaitingLifecycleShadowObservationEntity.variant == VARIANT_R1,
        )
    )
    assert row2.status == STATUS_EXPIRED
    assert row2.shadow_expired_but_real_later_bought is True
    evt = session.scalar(
        select(UpbitWaitingLifecycleShadowEventEntity).where(
            UpbitWaitingLifecycleShadowEventEntity.event_type
            == EVT_REAL_LATER_BOUGHT
        )
    )
    assert evt is not None


def test_p_q_full_slot_and_unobservable(session: Session) -> None:
    """P/Q — full slot capture + counterfactual unobservable."""

    out = observe_full_slot_block(
        session,
        user_broker_account_id=1380,
        symbol="KRW-FULL",
        selection_id=None,
        score=None,
        reason_code="FULL_MARKET_NO_WAITING_SIGNAL_SLOT",
    )
    assert out.get("unobservable") is True
    observe_full_slot_block(
        session,
        user_broker_account_id=1380,
        symbol="KRW-FULL2",
        selection_id=8001,
        score=77.0,
        reason_code="FULL_MARKET_NO_WAITING_SIGNAL_SLOT",
    )
    n = session.scalar(
        select(UpbitWaitingLifecycleShadowObservationEntity).where(
            UpbitWaitingLifecycleShadowObservationEntity.selection_id == 8001,
            UpbitWaitingLifecycleShadowObservationEntity.variant == VARIANT_R1,
        )
    )
    assert n is not None


def test_r_s_no_historical_primary_backfill_preexisting_excluded(
    session: Session,
) -> None:
    """R/S — preexisting cohort excluded from primary metrics."""

    past = datetime(2026, 8, 1, tzinfo=timezone.utc)
    _enroll(
        session,
        selection_id=9001,
        at=past,
        cohort=COHORT_PREEXISTING,
        variants=(VARIANT_R1,),
    )
    summary = summarize_waiting_lifecycle_lab(session, user_broker_account_id=1380)
    assert summary["preexisting_cohort_n"] >= 1
    assert summary["variants"][VARIANT_R1]["forward_n"] == 0


def test_t_event_dedupe(session: Session) -> None:
    """T — repeated EVALUATION coalesced."""

    t0 = datetime.now(timezone.utc)
    _enroll(session, selection_id=9101, at=t0, variants=(VARIANT_R1,))
    for _ in range(5):
        observe_evaluation(
            session,
            user_broker_account_id=1380,
            symbol="KRW-TEST",
            selection_id=9101,
            decision="BLOCK",
            block_reason="SHORT_MA_NOT_ABOVE_LONG_MA",
            now=t0 + timedelta(seconds=1),
        )
    n = session.scalar(
        select(UpbitWaitingLifecycleShadowEventEntity).where(
            UpbitWaitingLifecycleShadowEventEntity.selection_id == 9101,
            UpbitWaitingLifecycleShadowEventEntity.event_type
            == "TECHNICAL_BLOCK",
            UpbitWaitingLifecycleShadowEventEntity.variant == VARIANT_R1,
        )
    )
    # count
    from sqlalchemy import func

    cnt = session.scalar(
        select(func.count()).select_from(UpbitWaitingLifecycleShadowEventEntity).where(
            UpbitWaitingLifecycleShadowEventEntity.selection_id == 9101,
            UpbitWaitingLifecycleShadowEventEntity.event_type
            == "TECHNICAL_BLOCK",
            UpbitWaitingLifecycleShadowEventEntity.variant == VARIANT_R1,
        )
    )
    assert int(cnt or 0) == 1


def test_u_fail_open_hook() -> None:
    """U — hook swallows DB failure."""

    from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.hooks import (
        on_waiting_slot_assigned,
    )

    bad = MagicMock()
    bad.add.side_effect = RuntimeError("boom")
    out = on_waiting_slot_assigned(
        bad,
        user_broker_account_id=1380,
        symbol="KRW-X",
        selection_id=1,
    )
    assert out.get("ok") is False


def test_v_api_list_pagination(session: Session) -> None:
    """V — list_observations pagination/filter."""

    t0 = datetime.now(timezone.utc)
    for i in range(5):
        _enroll(session, selection_id=9200 + i, at=t0, variants=(VARIANT_R0,))
    page = list_observations(
        session,
        user_broker_account_id=1380,
        variant=VARIANT_R0,
        limit=2,
        offset=0,
    )
    assert page["total"] == 5
    assert len(page["items"]) == 2
    page2 = list_observations(
        session,
        user_broker_account_id=1380,
        variant=VARIANT_R0,
        limit=2,
        offset=2,
    )
    assert len(page2["items"]) == 2


def test_w_ui_status_rendering_summary_keys(session: Session) -> None:
    """W — summary exposes UI required keys (no promote language)."""

    summary = summarize_waiting_lifecycle_lab(session, user_broker_account_id=1380)
    assert summary["real_waiting_policy_unchanged"] is True
    assert "승격 권장" not in str(summary)
    assert "정책 변경 권장" not in str(summary)
    cmp = compare_variants(session, user_broker_account_id=1380)
    assert "승격 권장" not in str(cmp)
    assert cmp.get("note", "").startswith("Observation")


def test_x_shadow_does_not_call_order_path() -> None:
    """X — shadow modules never import order create helpers at module level."""

    import stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.service as svc

    src = open(svc.__file__, encoding="utf-8").read()
    assert "create_order" not in src
    assert "submit_order" not in src


def test_y_z_exit_lab_and_reentry_constants_untouched() -> None:
    """Y/Z — Exit Lab T5–T8 and reentry R1–R3 constants regression."""

    from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow import (
        constants as tc,
    )
    from stock_platform.operation.upbit_opportunity_shadow.reentry_cooldown_shadow import (
        constants as rc,
    )

    assert tc.VARIANT_T5 == "T5"
    assert tc.VARIANT_T6 == "T6"
    assert tc.VARIANT_T7 == "T7"
    assert tc.VARIANT_T8 == "T8"
    assert hasattr(rc, "VARIANT_R1") or "R1" in str(rc.__dict__)
