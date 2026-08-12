"""SHADOW_ONLY scanner + shadow evaluator automation — focused tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.operation.upbit_opportunity_scanner.policy import (
    SCANNER_MODE_SHADOW_ONLY,
    load_scanner_policy,
)
from stock_platform.operation.upbit_opportunity_scanner.scheduler import (
    UpbitOpportunityScannerScheduler,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_ACTIVE,
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.evaluator_scheduler import (
    UpbitOpportunityShadowEvaluatorScheduler,
)
from stock_platform.operation.upbit_opportunity_shadow.mismatch import (
    MISMATCH_CODE,
    ShadowEvaluationMismatchWatch,
)
from stock_platform.operation.upbit_opportunity_shadow.service import (
    UpbitOpportunityShadowService,
)
from stock_platform.operation.upbit_opportunity_shadow.stats import (
    COHORT_SAMPLE_INSUFFICIENT,
    compute_shadow_stats,
)


def _settings(**overrides):
    base = dict(
        upbit_opportunity_scanner_enabled=True,
        upbit_opportunity_scanner_mode="SHADOW_ONLY",
        upbit_opportunity_scanner_interval_seconds=900,
        upbit_scanner_min_24h_trade_value_krw=5_000_000_000,
        upbit_scanner_top_n=5,
        upbit_scanner_symbol_cooldown_seconds=1800,
        upbit_scanner_max_spike_pct=15,
        upbit_scanner_technical_candidate_limit=30,
        upbit_scanner_min_candles=30,
        upbit_scanner_candle_unit=1,
        upbit_scanner_ai_enabled=True,
        upbit_scanner_notify_hold=False,
        upbit_scanner_exclude_stablecoins=True,
        upbit_scanner_exclude_caution_markets=True,
        upbit_scanner_ai_backfill_enabled=True,
        upbit_scanner_stablecoin_base_assets="USDT,USDC",
        upbit_scanner_shadow_enabled=True,
        upbit_scanner_shadow_evaluator_enabled=True,
        upbit_scanner_shadow_evaluator_interval_seconds=180,
        upbit_scanner_shadow_mismatch_watch_enabled=True,
        upbit_scanner_shadow_mismatch_tolerance=5e-4,
        scheduler_timezone="UTC",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_shadow_only_mode_policy():
    p = load_scanner_policy(_settings())
    assert p.enabled is True
    assert p.mode == SCANNER_MODE_SHADOW_ONLY
    assert p.top_n == 5
    assert p.interval_seconds == 900


def test_scanner_scheduler_registration_and_duplicate_job(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.scheduler.get_settings",
        lambda: _settings(),
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.policy.get_settings",
        lambda: _settings(),
    )
    sched = UpbitOpportunityScannerScheduler()
    # AsyncIOScheduler.start는 이벤트 루프 필요 — configure만으로 job 등록 검증
    sched.configure(force=True)
    sched._started = True  # start()의 성공 경로 시뮬레이션
    jobs1 = [j.id for j in sched._scheduler.get_jobs()]
    assert UpbitOpportunityScannerScheduler.JOB_ID in jobs1
    sched.configure(force=True)
    jobs2 = [j.id for j in sched._scheduler.get_jobs()]
    assert jobs2.count(UpbitOpportunityScannerScheduler.JOB_ID) == 1
    status = sched.status()
    assert status["mode"] == "SHADOW_ONLY"
    assert status["live_order"] is False
    assert status["orders_created"] == 0
    assert sched.automation_allowed()[0] is True


def test_scanner_blocks_non_shadow_mode(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.scheduler.get_settings",
        lambda: _settings(upbit_opportunity_scanner_mode="LIVE"),
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.policy.get_settings",
        lambda: _settings(upbit_opportunity_scanner_mode="LIVE"),
    )
    sched = UpbitOpportunityScannerScheduler()
    sched.start()
    assert sched._started is False
    allowed, reason = sched.automation_allowed()
    assert allowed is False
    assert reason and "MODE_NOT_SHADOW_ONLY" in reason


@pytest.mark.asyncio
async def test_overlapping_scanner_skip(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.scheduler.get_settings",
        lambda: _settings(),
    )
    sched = UpbitOpportunityScannerScheduler()
    sched._tick_in_progress = True
    out = await sched._run_tick(notify=False)
    assert out["code"] == "OVERLAP_SKIP"
    assert out["orders_created"] == 0
    assert sched._overlap_skip_count == 1


def test_evaluator_scheduler_registration(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator_scheduler.get_settings",
        lambda: _settings(),
    )
    # policy import 제거됨 — scanner monkeypatch 불필요
    sched = UpbitOpportunityShadowEvaluatorScheduler()
    sched.configure(force=True)
    sched._started = True
    jobs = [j.id for j in sched._scheduler.get_jobs()]
    assert UpbitOpportunityShadowEvaluatorScheduler.JOB_ID in jobs
    assert sched.status()["interval_seconds"] == 180
    assert sched.status()["live_order"] is False


def test_restart_registration_idempotent(monkeypatch):
    """configure 두 번 = 중복 job 없이 재등록."""

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.scheduler.get_settings",
        lambda: _settings(),
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.policy.get_settings",
        lambda: _settings(),
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.evaluator_scheduler.get_settings",
        lambda: _settings(),
    )
    scanner = UpbitOpportunityScannerScheduler()
    evaluator = UpbitOpportunityShadowEvaluatorScheduler()
    scanner.configure(force=True)
    evaluator.configure(force=True)
    scanner.configure(force=True)
    evaluator.configure(force=True)
    assert (
        [j.id for j in scanner._scheduler.get_jobs()].count(
            UpbitOpportunityScannerScheduler.JOB_ID
        )
        == 1
    )
    assert (
        [j.id for j in evaluator._scheduler.get_jobs()].count(
            UpbitOpportunityShadowEvaluatorScheduler.JOB_ID
        )
        == 1
    )


def test_allow_reduce_hold_shadow_rules(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.service.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_enabled=True,
            upbit_scanner_shadow_assumed_amount_krw=5000,
            upbit_scanner_shadow_reduce_ratio=0.5,
            upbit_scanner_shadow_cooldown_seconds=3600,
        ),
    )
    session = MagicMock()
    session.scalar.return_value = None
    session.scalars.return_value = []
    session.add = MagicMock()
    session.flush = MagicMock()
    session.commit = MagicMock()

    created_entities: list = []
    next_id = {"n": 100}

    def _add(obj):
        if getattr(obj, "shadow_id", None) is None:
            obj.shadow_id = next_id["n"]
            next_id["n"] += 1
        created_entities.append(obj)

    session.add.side_effect = _add

    svc = UpbitOpportunityShadowService(
        session, now=datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)
    )
    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.service.publish_shadow_opened"
    ):
        out = svc.create_from_candidates(
            candidates=[
                {
                    "symbol": "KRW-AAA",
                    "recommendation": "ALLOW",
                    "price": 100,
                    "score": 80,
                    "rank": 1,
                    "confidence": 0.8,
                    "risk_level": "LOW",
                },
                {
                    "symbol": "KRW-BBB",
                    "recommendation": "REDUCE",
                    "price": 200,
                    "score": 70,
                    "rank": 2,
                    "confidence": 0.7,
                    "risk_level": "MED",
                },
                {
                    "symbol": "KRW-CCC",
                    "recommendation": "HOLD",
                    "price": 300,
                    "score": 60,
                    "rank": 3,
                    "confidence": 0.5,
                    "risk_level": "LOW",
                },
            ],
            scanner_run_id="run1",
            notify=False,
        )
    assert out["created"] == 2
    assert out["orders_created"] == 0
    symbols = {e.symbol for e in created_entities}
    assert "KRW-AAA" in symbols
    assert "KRW-BBB" in symbols
    assert "KRW-CCC" not in symbols
    hold_skips = [
        s for s in out["skipped"] if s.get("reason") == "NOT_ALLOW_REDUCE"
    ]
    assert len(hold_skips) == 1


def test_active_duplicate_skip(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.service.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_enabled=True,
            upbit_scanner_shadow_assumed_amount_krw=5000,
            upbit_scanner_shadow_reduce_ratio=0.5,
            upbit_scanner_shadow_cooldown_seconds=3600,
        ),
    )
    existing = UpbitOpportunityShadowEntity(
        shadow_id=10,
        scanner_run_id="old",
        symbol="KRW-AAA",
        recommendation="ALLOW",
        status=SHADOW_STATUS_ACTIVE,
        entry_price=Decimal("100"),
        assumed_amount_krw=Decimal("5000"),
        detected_at=datetime(2026, 8, 13, 5, 0, tzinfo=timezone.utc),
        live_auto_start=False,
    )
    session = MagicMock()
    session.scalar.return_value = existing
    session.scalars.return_value = [existing]
    session.add = MagicMock()
    svc = UpbitOpportunityShadowService(
        session, now=datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)
    )
    out = svc.create_from_candidates(
        candidates=[
            {
                "symbol": "KRW-AAA",
                "recommendation": "ALLOW",
                "price": 101,
                "score": 80,
                "rank": 1,
            }
        ],
        scanner_run_id="run2",
        notify=False,
    )
    assert out["created"] == 0
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_stored_vs_recompute_match_and_mismatch(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.mismatch.get_settings",
        lambda: _settings(),
    )
    t0 = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    row = UpbitOpportunityShadowEntity(
        shadow_id=50,
        scanner_run_id="r",
        symbol="KRW-X",
        recommendation="ALLOW",
        status=SHADOW_STATUS_COMPLETED,
        entry_price=Decimal("100"),
        assumed_amount_krw=Decimal("5000"),
        detected_at=t0,
        completed_at=t0 + timedelta(minutes=65),
        live_auto_start=False,
        return_5m_pct=1.0,
        return_15m_pct=2.0,
        return_30m_pct=3.0,
        return_60m_pct=4.0,
        mfe_pct=5.0,
        mae_pct=-1.0,
        tp_hit=False,
        sl_hit=False,
        evaluation_detail={},
    )
    session = MagicMock()
    session.get.return_value = row
    session.commit = MagicMock()

    async def fake_dry(self, shadow_id):
        return {
            "ok": True,
            "stored": {
                "return_5m_pct": 1.0,
                "return_15m_pct": 2.0,
                "return_30m_pct": 3.0,
                "return_60m_pct": 4.0,
                "mfe_pct": 5.0,
                "mae_pct": -1.0,
                "tp_hit": False,
                "sl_hit": False,
            },
            "recomputed": {
                "windows": {
                    "5": {"return_pct": 1.0, "status": "OK"},
                    "15": {"return_pct": 2.0, "status": "OK"},
                    "30": {"return_pct": 3.0, "status": "OK"},
                    "60": {"return_pct": 4.0, "status": "OK"},
                },
                "mfe_pct": 5.0,
                "mae_pct": -1.0,
                "tp_sl": {"tp_hit": False, "sl_hit": False},
            },
        }

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.mismatch."
        "UpbitOpportunityShadowEvaluator.dry_recompute",
        fake_dry,
    )
    watch = ShadowEvaluationMismatchWatch(session, allow_sync=False)
    with patch(
        "stock_platform.api.deps_admin.AuditLogService.record",
        return_value=MagicMock(),
    ):
        ok = await watch.verify_completed(row, notify=False)
    assert ok["ok"] is True
    assert ok["code"] == "MATCH"
    assert row.return_5m_pct == 1.0  # evaluation fields 불변

    async def fake_dry_bad(self, shadow_id):
        payload = await fake_dry(self, shadow_id)
        payload["recomputed"]["mfe_pct"] = 9.9
        return payload

    row.evaluation_detail = {}
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.mismatch."
        "UpbitOpportunityShadowEvaluator.dry_recompute",
        fake_dry_bad,
    )
    with (
        patch(
            "stock_platform.api.deps_admin.AuditLogService.record",
            return_value=MagicMock(),
        ) as audit,
        patch(
            "stock_platform.operation.upbit_opportunity_shadow.mismatch.publish_shadow_mismatch"
        ) as notify,
    ):
        bad = await watch.verify_completed(row, notify=True, force=True)
    assert bad["ok"] is False
    assert bad["code"] == MISMATCH_CODE
    assert bad["mutated_evaluation_fields"] is False
    audit.assert_called()
    notify.assert_called()


def test_cohort_status_sample_insufficient():
    session = MagicMock()
    rows = [
        UpbitOpportunityShadowEntity(
            shadow_id=i,
            scanner_run_id="r",
            symbol=f"KRW-X{i}",
            recommendation="ALLOW",
            status=SHADOW_STATUS_COMPLETED,
            entry_price=Decimal("1"),
            assumed_amount_krw=Decimal("5000"),
            detected_at=datetime.now(timezone.utc),
            live_auto_start=False,
            return_60m_pct=1.0 if i % 2 == 0 else -1.0,
            mfe_pct=0.5,
            mae_pct=-0.2,
            tp_hit=False,
            sl_hit=False,
            evaluation_detail={},
        )
        for i in range(2)
    ]
    session.scalars.return_value = rows
    stats = compute_shadow_stats(session)
    assert stats["cohort_n"] == 2
    assert stats["cohort_status"] == COHORT_SAMPLE_INSUFFICIENT
    assert stats["auto_threshold_tuning"] is False


@pytest.mark.asyncio
async def test_scanner_failure_isolation(monkeypatch):
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.scheduler.get_settings",
        lambda: _settings(),
    )
    sched = UpbitOpportunityScannerScheduler()

    class Boom:
        async def run(self, **kwargs):
            raise RuntimeError("boom")

    Session = MagicMock()
    session = MagicMock()
    Session.return_value.__enter__ = MagicMock(return_value=session)
    Session.return_value.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_scanner.scheduler.get_session_factory",
        lambda: Session,
    )
    sched._service_holder = Boom()
    with patch(
        "stock_platform.operation.upbit_opportunity_scanner.scheduler.publish_scanner_failure"
    ) as fail_notify:
        out = await sched._run_tick(notify=True)
    assert out["ok"] is False
    assert out["orders_created"] == 0
    fail_notify.assert_called()


@pytest.mark.asyncio
async def test_no_orders_outbox_on_paths():
    """자동화 경로 응답은 항상 orders_created=0."""

    sched = UpbitOpportunityScannerScheduler()
    sched._tick_in_progress = True
    out = await sched._run_tick(notify=False)
    assert out["orders_created"] == 0
    assert out.get("live_order") is False or out.get("shadow_only") is True
