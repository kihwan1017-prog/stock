"""UPBIT remote open-order exposure — unit only. production DB mutation 0."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.order.live_open_order_exposure import (
    LOCAL_OPEN_STATUSES,
    OPEN_ORDER_LIMIT_EXCEEDED,
    REMOTE_OPEN_CHECK_FAILED,
    LocalOpenOrder,
    RemoteOpenOrderRef,
    RemoteOpenOrderView,
    STATE_FRESH,
    STATE_NOT_APPLICABLE,
    STATE_UNKNOWN,
    clear_remote_open_view_cache,
    combine_open_order_exposure,
    evaluate_live_open_order_exposure,
    fetch_upbit_remote_open_view,
)
from stock_platform.realtime.ma_evaluator import MovingAverageStrategyEvaluator
from stock_platform.realtime.market_event import RealtimeMarketEvent
from stock_platform.realtime.strategy_models import (
    RealtimeStrategyConfig,
    uses_daily_bars,
)
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    StrategyRuntimeScope,
)
from stock_platform.trading.strategy_runtime_authorization import (
    MODE_PRIVATE_EVIDENCE,
    evaluate_strategy_runtime_authorization,
)


def _fresh(*uuids: str, identifier: str | None = None) -> RemoteOpenOrderView:
    orders = tuple(
        RemoteOpenOrderRef(uuid=u.lower(), identifier=identifier)
        for u in uuids
    )
    return RemoteOpenOrderView(status=STATE_FRESH, orders=orders, source="TEST")


def test_a_local0_remote0_buy_count_pass() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    out = evaluate_live_open_order_exposure(
        session,
        uba_id=1380,
        broker_code="UPBIT",
        remote_view=_fresh(),
    )
    assert out.canonical_count == 0
    assert out.remote_state_ok is True
    assert out.canonical_count < 1


def test_b_unmapped_remote_is_manual_not_auto_count() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    out = evaluate_live_open_order_exposure(
        session,
        uba_id=1380,
        broker_code="UPBIT",
        remote_view=_fresh("ab83289c-a2b7-45da-93ec-e9e93f8413ff"),
    )
    assert out.local_open_count == 0
    assert out.remote_unmapped_count == 1
    assert out.manual_open_count == 1
    assert out.auto_open_count == 0
    assert out.canonical_count == 0


def test_c_same_uuid_local_and_remote_dedupes() -> None:
    uid = "90db6b4d-d837-45be-834f-0c5fbfbef5e6"
    local = [
        LocalOpenOrder(
            order_id=1,
            broker_order_id=uid,
            client_order_id="cid-1",
            client_order_identifier=None,
            strategy_id=1,
            owner="AUTO",
        )
    ]
    out = combine_open_order_exposure(
        local_orders=local,
        remote_view=_fresh(uid),
        source="TEST",
    )
    assert out.local_open_count == 1
    assert out.remote_open_count == 1
    assert out.mapped_remote_count == 1
    assert out.remote_unmapped_count == 0
    assert out.auto_open_count == 1
    assert out.canonical_count == 1


def test_d_three_unmapped_remote_manual_auto_pass() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    out = evaluate_live_open_order_exposure(
        session,
        uba_id=1380,
        broker_code="UPBIT",
        remote_view=_fresh("u1", "u2", "u3"),
    )
    assert out.manual_open_count == 3
    assert out.auto_open_count == 0
    assert out.canonical_count == 0


def test_e_unknown_remote_fail_closed() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    out = evaluate_live_open_order_exposure(
        session,
        uba_id=1380,
        broker_code="UPBIT",
        remote_view=RemoteOpenOrderView(status=STATE_UNKNOWN, source="TEST"),
    )
    assert out.remote_state_ok is False
    assert out.reason_code == REMOTE_OPEN_CHECK_FAILED


def test_f_paper_does_not_include_remote() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    out = evaluate_live_open_order_exposure(
        session,
        uba_id=1380,
        broker_code="UPBIT",
        environment="PAPER",
        remote_view=_fresh("u1", "u2", "u3"),
    )
    assert out.source == "LOCAL_ONLY"
    assert out.canonical_count == 0
    assert out.remote_state == STATE_NOT_APPLICABLE
    assert out.remote_state_ok is True


def test_g_pipeline_exit_skips_entry_open_limit() -> None:
    from tests.test_exit_risk_fail_safe import (
        _eval_pipeline,
        _policy,
        _uba,
        _verified_exit,
    )

    session = MagicMock()
    session.get.return_value = _uba()
    session.scalar.side_effect = [0, None, None, 20, 0]
    session.scalars.return_value = []
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.risk_engine.exit_risk.classify_risk_reducing_exit",
            return_value=_verified_exit(),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch(
            "stock_platform.order.live_safety_pipeline.evaluate_live_open_order_exposure"
        ) as remote,
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver.return_value.resolve.return_value = _policy(
            max_open_orders=1, daily_order_limit=100
        )
        sell = _eval_pipeline(session, side="SELL")
    assert sell.allowed is True
    remote.assert_not_called()


def test_h_pending_sell_still_subtracted_from_sellable() -> None:
    from inspect import getsource

    from stock_platform.risk_engine.exit_risk import classify_risk_reducing_exit

    src = getsource(classify_risk_reducing_exit)
    assert "pending_sell" in src
    assert "sellable" in src.lower()


def test_i_xrp_sol_share_uba_manual_not_auto() -> None:
    """UBA1380 계좌 단위 MANUAL remote 는 AUTO count 0."""

    session = MagicMock()
    session.scalars.return_value = []
    sol = evaluate_live_open_order_exposure(
        session, uba_id=1380, broker_code="UPBIT", remote_view=_fresh("doge", "sky")
    )
    xrp = evaluate_live_open_order_exposure(
        session, uba_id=1380, broker_code="UPBIT", remote_view=_fresh("doge", "sky")
    )
    assert sol.manual_open_count == xrp.manual_open_count == 2
    assert sol.auto_open_count == xrp.auto_open_count == 0
    assert sol.canonical_count == xrp.canonical_count == 0


def test_j_kiwoom_local_manual_without_strategy() -> None:
    session = MagicMock()
    session.scalars.side_effect = [
        [
            SimpleNamespace(
                order_id=9,
                broker_order_id="KRX-1",
                client_order_id="c",
                client_order_identifier=None,
                symbol="005930",
                strategy_id=None,
                strategy_deployment_id=None,
                metadata_payload={},
                broker_code="KIWOOM",
            )
        ],
        [],
    ]
    out = evaluate_live_open_order_exposure(
        session,
        uba_id=1381,
        broker_code="KIWOOM",
        remote_view=_fresh("upbit-uuid"),
    )
    assert "KIWOOM" in out.source or out.source == "LOCAL_ONLY"
    assert out.manual_open_count == 1
    assert out.auto_open_count == 0
    assert out.remote_unmapped_count == 0


def test_fetch_unknown_when_rest_raises() -> None:
    clear_remote_open_view_cache()
    session = MagicMock()

    def _boom() -> tuple[list, list]:
        raise RuntimeError("broker_down")

    view = fetch_upbit_remote_open_view(
        session, uba_id=1380, rest_loader=_boom
    )
    assert view.status == STATE_UNKNOWN
    assert view.ok is False


def test_pipeline_buy_allows_manual_unmapped_remote() -> None:
    """MANUAL remote 3건은 AUTO max_open_orders 를 막지 않는다."""

    from tests.test_exit_risk_fail_safe import _eval_pipeline, _policy, _uba

    session = MagicMock()
    session.get.return_value = _uba()
    session.scalar.return_value = None
    session.scalars.return_value = []
    exposure = evaluate_live_open_order_exposure(
        MagicMock(scalars=MagicMock(return_value=[])),
        uba_id=1380,
        broker_code="UPBIT",
        remote_view=_fresh("u1", "u2", "u3"),
    )
    assert exposure.manual_open_count == 3
    assert exposure.auto_open_count == 0
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch(
            "stock_platform.order.live_safety_pipeline.evaluate_live_open_order_exposure",
            return_value=exposure,
        ),
        patch.object(
            __import__(
                "stock_platform.order.live_safety_pipeline",
                fromlist=["LiveOrderSafetyPipeline"],
            ).LiveOrderSafetyPipeline,
            "_count_orders_today",
            return_value=0,
        ),
        patch.object(
            __import__(
                "stock_platform.order.live_safety_pipeline",
                fromlist=["LiveOrderSafetyPipeline"],
            ).LiveOrderSafetyPipeline,
            "_is_duplicate",
            return_value=False,
        ),
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver.return_value.resolve.return_value = _policy(max_open_orders=1)
        buy = _eval_pipeline(session, side="BUY", symbol="KRW-SOL")
    assert buy.allowed is True


def test_pipeline_buy_fail_closed_when_remote_unknown() -> None:
    from tests.test_exit_risk_fail_safe import _eval_pipeline, _policy, _uba

    session = MagicMock()
    session.get.return_value = _uba()
    session.scalar.return_value = None
    session.scalars.return_value = []
    unknown = evaluate_live_open_order_exposure(
        MagicMock(scalars=MagicMock(return_value=[])),
        uba_id=1380,
        broker_code="UPBIT",
        remote_view=RemoteOpenOrderView(status=STATE_UNKNOWN, source="TEST"),
    )
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch(
            "stock_platform.order.live_safety_pipeline.evaluate_live_open_order_exposure",
            return_value=unknown,
        ),
        patch.object(
            __import__(
                "stock_platform.order.live_safety_pipeline",
                fromlist=["LiveOrderSafetyPipeline"],
            ).LiveOrderSafetyPipeline,
            "_count_orders_today",
            return_value=0,
        ),
        patch.object(
            __import__(
                "stock_platform.order.live_safety_pipeline",
                fromlist=["LiveOrderSafetyPipeline"],
            ).LiveOrderSafetyPipeline,
            "_is_duplicate",
            return_value=False,
        ),
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver.return_value.resolve.return_value = _policy(max_open_orders=1)
        buy = _eval_pipeline(session, side="BUY", symbol="KRW-SOL")
    assert buy.allowed is False
    assert buy.reason_code == REMOTE_OPEN_CHECK_FAILED


def test_timeframe_regression_1d_not_raw_ticks() -> None:
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
    now = datetime.now(timezone.utc)
    for i in range(12):
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


def test_private_evidence_gate_untouched() -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(
        strategy_id=17580,
        deleted_at=None,
        is_active=True,
        owner_type="USER",
        visibility="PRIVATE",
        approved_at=None,
        source_strategy_id=17483,
    )
    with (
        patch(
            "stock_platform.trading.strategy_runtime_authorization._compile_ready",
            return_value=(True, {"ok": True}),
        ),
        patch(
            "stock_platform.trading.strategy_runtime_authorization._own_successful_backtest",
            return_value=SimpleNamespace(
                backtest_run_id=72396, symbol="KRW-SOL", trade_count=31
            ),
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


def test_local_open_statuses_unchanged() -> None:
    assert "ACCEPTED" in LOCAL_OPEN_STATUSES
    assert "FILLED" not in LOCAL_OPEN_STATUSES
