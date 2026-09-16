"""PRIVATE USER Runtime 승인 게이트 정렬 — unit only. production DB mutation 0."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from inspect import getsource
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.realtime.ma_evaluator import MovingAverageStrategyEvaluator
from stock_platform.realtime.market_event import RealtimeMarketEvent
from stock_platform.realtime.strategy_models import (
    RealtimeStrategyConfig,
    uses_daily_bars,
)
from stock_platform.strategy_deployment.ownership import StrategyDefinitionService
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    StrategyRuntimeScope,
)
from stock_platform.trading.strategy_runtime_authorization import (
    CODE_EVIDENCE_NOT_READY,
    CODE_INACTIVE,
    CODE_NOT_APPROVED,
    MODE_PRIVATE_CATALOG_STAMP,
    MODE_PRIVATE_EVIDENCE,
    MODE_PUBLIC_CATALOG,
    MODE_SYSTEM,
    evaluate_strategy_runtime_authorization,
)
from stock_platform.trading.upbit_24x7_control import _strategy_ready


def _definition(**kwargs: object) -> SimpleNamespace:
    base: dict[str, object] = dict(
        strategy_id=17580,
        deleted_at=None,
        is_active=True,
        owner_type="USER",
        visibility="PRIVATE",
        approved_at=None,
        source_strategy_id=17483,
        strategy_code="SOL",
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_system_strategy_does_not_need_approved_at() -> None:
    session = MagicMock()
    session.get.return_value = _definition(
        strategy_id=1, owner_type="SYSTEM", approved_at=None
    )
    out = evaluate_strategy_runtime_authorization(session, strategy_id=1)
    assert out["ok"] is True
    assert out["mode"] == MODE_SYSTEM


def test_public_user_without_approved_at_is_not_approved() -> None:
    session = MagicMock()
    session.get.return_value = _definition(
        strategy_id=9, visibility="PUBLIC", approved_at=None
    )
    out = evaluate_strategy_runtime_authorization(session, strategy_id=9)
    assert out["ok"] is False
    assert out["code"] == CODE_NOT_APPROVED
    assert out["mode"] == MODE_PUBLIC_CATALOG


def test_public_user_with_approved_at_passes_catalog() -> None:
    session = MagicMock()
    session.get.return_value = _definition(
        strategy_id=9,
        visibility="PUBLIC",
        approved_at=datetime.now(timezone.utc),
    )
    out = evaluate_strategy_runtime_authorization(session, strategy_id=9)
    assert out["ok"] is True
    assert out["mode"] == MODE_PUBLIC_CATALOG


def test_private_17483_catalog_stamp_does_not_require_paper() -> None:
    session = MagicMock()
    session.get.return_value = _definition(
        strategy_id=17483,
        source_strategy_id=None,
        approved_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
    )
    out = evaluate_strategy_runtime_authorization(session, strategy_id=17483)
    assert out["ok"] is True
    assert out["mode"] == MODE_PRIVATE_CATALOG_STAMP


def test_private_without_stamp_requires_own_evidence() -> None:
    session = MagicMock()
    session.get.return_value = _definition()
    with (
        patch(
            "stock_platform.trading.strategy_runtime_authorization._compile_ready",
            return_value=(True, {"ok": True, "compilable": True}),
        ),
        patch(
            "stock_platform.trading.strategy_runtime_authorization._own_successful_backtest",
            return_value=None,
        ),
        patch(
            "stock_platform.trading.strategy_runtime_authorization._own_paper_pass",
            return_value=None,
        ),
    ):
        out = evaluate_strategy_runtime_authorization(session, strategy_id=17580)
    assert out["ok"] is False
    assert out["code"] == CODE_EVIDENCE_NOT_READY
    assert "OWN_BACKTEST_SUCCESS_REQUIRED" in out["blockers"]
    assert "OWN_PAPER_PASS_REQUIRED" in out["blockers"]


def test_private_17580_own_backtest_and_paper_pass() -> None:
    session = MagicMock()
    session.get.return_value = _definition()
    backtest = SimpleNamespace(
        backtest_run_id=72396, symbol="KRW-SOL", trade_count=31
    )
    with (
        patch(
            "stock_platform.trading.strategy_runtime_authorization._compile_ready",
            return_value=(True, {"ok": True, "compilable": True, "timeframe": "1D"}),
        ),
        patch(
            "stock_platform.trading.strategy_runtime_authorization._own_successful_backtest",
            return_value=backtest,
        ),
        patch(
            "stock_platform.trading.strategy_runtime_authorization._own_paper_pass",
            return_value={
                "run_id": 1528,
                "result": "PAPER_PASS",
                "integrity": "PASS",
                "symbol": "KRW-SOL",
            },
        ),
    ):
        out = evaluate_strategy_runtime_authorization(session, strategy_id=17580)
    assert out["ok"] is True
    assert out["mode"] == MODE_PRIVATE_EVIDENCE
    assert out["backtest_run_id"] == 72396
    assert out["paper_run_id"] == 1528
    assert out["evidence_inheritance_allowed"] is False


def test_xrp_paper_run_is_not_inherited_for_sol() -> None:
    session = MagicMock()
    session.get.return_value = _definition()
    with (
        patch(
            "stock_platform.trading.strategy_runtime_authorization._compile_ready",
            return_value=(True, {"ok": True}),
        ),
        patch(
            "stock_platform.trading.strategy_runtime_authorization._own_successful_backtest",
            return_value=SimpleNamespace(
                backtest_run_id=1, symbol="KRW-SOL", trade_count=20
            ),
        ),
        patch(
            "stock_platform.trading.strategy_runtime_authorization._own_paper_pass",
            return_value=None,
        ),
    ):
        out = evaluate_strategy_runtime_authorization(session, strategy_id=17580)
    assert out["ok"] is False
    assert "OWN_PAPER_PASS_REQUIRED" in out["blockers"]


def test_inactive_strategy_blocked() -> None:
    session = MagicMock()
    session.get.return_value = _definition(is_active=False)
    out = evaluate_strategy_runtime_authorization(session, strategy_id=17580)
    assert out["ok"] is False
    assert out["code"] == CODE_INACTIVE


def test_kiwoom_17579_same_private_evidence_path_without_mutation() -> None:
    session = MagicMock()
    session.get.return_value = _definition(
        strategy_id=17579,
        source_strategy_id=17486,
        approved_at=None,
    )
    with (
        patch(
            "stock_platform.trading.strategy_runtime_authorization._compile_ready",
            return_value=(True, {"ok": True}),
        ),
        patch(
            "stock_platform.trading.strategy_runtime_authorization._own_successful_backtest",
            return_value=SimpleNamespace(
                backtest_run_id=72395, symbol="034310", trade_count=7
            ),
        ),
        patch(
            "stock_platform.trading.strategy_runtime_authorization._own_paper_pass",
            return_value={
                "run_id": 1526,
                "result": "PAPER_PASS",
                "integrity": "PASS",
                "symbol": "034310",
            },
        ),
    ):
        out = evaluate_strategy_runtime_authorization(session, strategy_id=17579)
    assert out["ok"] is True
    assert out["mode"] == MODE_PRIVATE_EVIDENCE
    session.commit.assert_not_called()


def test_runtime_ready_uses_authorization_before_link() -> None:
    session = MagicMock()
    # 1) ACTIVE link  2) registry 행 없음 → enabled 기본 허용
    session.scalar.side_effect = [
        SimpleNamespace(account_strategy_link_id=2357),
        None,
    ]
    with patch(
        "stock_platform.trading.strategy_runtime_authorization.evaluate_strategy_runtime_authorization",
        return_value={
            "ok": True,
            "mode": MODE_PRIVATE_EVIDENCE,
            "backtest_run_id": 72396,
            "paper_run_id": 1528,
        },
    ):
        out = _strategy_ready(session, uba_id=1380, strategy_id=17580)
    assert out["ok"] is True
    assert out["approved"] is True
    assert out["authorization_mode"] == MODE_PRIVATE_EVIDENCE
    assert out["backtest_run_id"] == 72396
    assert out["paper_run_id"] == 1528


def test_runtime_ready_before_evidence_is_blocked() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.trading.strategy_runtime_authorization.evaluate_strategy_runtime_authorization",
        return_value={
            "ok": False,
            "code": CODE_EVIDENCE_NOT_READY,
            "approved": False,
        },
    ):
        out = _strategy_ready(session, uba_id=1380, strategy_id=17580)
    assert out["ok"] is False
    assert out["code"] == CODE_EVIDENCE_NOT_READY
    session.scalar.assert_not_called()


def test_authorization_helper_never_assigns_approved_at() -> None:
    from inspect import getsource

    from stock_platform.trading import strategy_runtime_authorization as mod

    src = getsource(mod)
    assert "approved_at =" not in src
    assert "approved_by =" not in src


def test_public_catalog_rule_retained_in_runtime_ready() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.trading.strategy_runtime_authorization.evaluate_strategy_runtime_authorization",
        return_value={
            "ok": False,
            "code": CODE_NOT_APPROVED,
            "approved": False,
            "mode": MODE_PUBLIC_CATALOG,
        },
    ):
        out = _strategy_ready(session, uba_id=1380, strategy_id=99)
    assert out["ok"] is False
    assert out["code"] == CODE_NOT_APPROVED


def test_catalog_activation_and_approval_do_not_start_live() -> None:
    src_active = getsource(StrategyDefinitionService.admin_set_active)
    src_approve = getsource(StrategyDefinitionService.admin_approve)
    for src in (src_active, src_approve):
        assert "live_order_enabled" not in src
        assert "Runtime START" not in src
        assert "LIVE ON" not in src


def test_timeframe_alignment_regression_1d_not_raw_ticks() -> None:
    assert uses_daily_bars("1D")
    ev = MovingAverageStrategyEvaluator(
        StrategyRuntimeScope(
            user_id=61,
            account_kind=AccountKind.USER_BROKER,
            account_id=1380,
            strategy_id=17580,
            strategy_version="1",
            market_type="CRYPTO",
            broker_code="UPBIT",
        ),
        RealtimeStrategyConfig(
            short_window=5, long_window=20, cooldown_seconds=0, timeframe="1D"
        ),
    )
    assert ev.config.uses_daily_bars()
    now = datetime.now(timezone.utc)
    for i in range(20):
        ev.evaluate(
            RealtimeMarketEvent(
                broker_code="UPBIT",
                market_type="CRYPTO",
                symbol="KRW-SOL",
                event_type="TRADE",
                event_time=now + timedelta(seconds=i),
                received_at=now,
                exchange_code="UPBIT",
                price=Decimal("100"),
                raw_sequence=i + 1,
            )
        )
    assert len(ev.get_state("KRW-SOL").prices) == 1
    assert ev.get_state("KRW-SOL").input_unit == "DAY"
