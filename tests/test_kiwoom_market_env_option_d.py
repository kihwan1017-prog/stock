"""Option D — KIWOOM MARKET_ENV mode-aware + 로컬 KRX tick (broker network 없음)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.broker.credential_adapter_factory import (
    build_kiwoom_order_config_from_vault,
)
from stock_platform.broker.credential_vault_service import ResolvedBrokerCredential
from stock_platform.broker.factory import BrokerAdapterFactory
from stock_platform.broker.kiwoom.execution_env import (
    KIWOOM_MOCK_EXECUTION_BASE,
    KIWOOM_REAL_EXECUTION_BASE,
    kiwoom_global_mock_blocks_live_execution,
)
from stock_platform.broker.kiwoom.live_preflight_service import (
    KiwoomLivePreflightService,
    KiwoomPreflightSnapshot,
)
from stock_platform.broker.models import BrokerEnvironment
from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.live_safety_pipeline import LiveOrderSafetyPipeline
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.position.lot_rounding import is_krx_tick_aligned, krx_tick_size
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicy


def _now() -> datetime:
    return datetime(2026, 8, 18, 2, 0, tzinfo=timezone.utc)  # 11:00 KST


def _healthy(**kwargs: object) -> KiwoomPreflightSnapshot:
    base = dict(
        uba_id=1381,
        user_id=61,
        is_active=True,
        broker_code="KIWOOM",
        connection_status="CONNECTED",
        live_order_enabled=False,
        live_armed=False,
        credential_present=True,
        credential_verified=True,
        credential_is_mock=False,
        recovery_status="SUCCESS",
        trading_paused=False,
        active_high_conflicts=0,
        active_conflicts=0,
        snapshot_id=2,
        snapshot_status="ACTIVE",
        snapshot_uba_id=1381,
        snapshot_synchronized_at=_now(),
        position_count=12,
        unbound_or_cross_uba_positions=0,
        uba_risk_present=True,
        user_risk_present=False,
        risk_account_paused=False,
        kill_active=False,
        scheduler_desired="PAUSE",
        scheduler_actual="PAUSED",
        krx_is_trading_day=True,
        krx_session_type="REGULAR",
        krx_in_regular_session=True,
        env_global_live=False,
        env_kiwoom_live=False,
        env_kiwoom_use_mock=True,
        strategy_link_count=0,
        blocking_orders={"db_open": 0, "submission_unknown": 0},
        pending_count=0,
        now=_now(),
    )
    base.update(kwargs)
    return KiwoomPreflightSnapshot(**base)  # type: ignore[arg-type]


def _order_ready(**kwargs: object) -> KiwoomPreflightSnapshot:
    defaults = dict(
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=_now() + timedelta(minutes=4),
        env_global_live=True,
        env_kiwoom_live=True,
        arm_precondition_ok=True,
    )
    defaults.update(kwargs)
    return _healthy(**defaults)


def _eval(snap: KiwoomPreflightSnapshot, mode: str = "LIVE_ON") -> dict:
    return KiwoomLivePreflightService(MagicMock()).evaluate(snap, mode=mode)


def _check_status(report: dict, code: str) -> str:
    for row in report.get("checks") or []:
        if row.get("code") == code:
            return str(row.get("status"))
    return "MISSING"


def _codes(report: dict, status: str | None = None) -> set[str]:
    rows = report.get("checks") or []
    if status is None:
        return {str(c.get("code")) for c in rows}
    return {str(c.get("code")) for c in rows if c.get("status") == status}


def _real_resolved(*, is_mock: bool = False) -> ResolvedBrokerCredential:
    return ResolvedBrokerCredential(
        user_broker_account_id=1381,
        broker_code="KIWOOM",
        credential_id=1,
        key_version=1,
        payload={
            "app_key": "k",
            "secret_key": "s",
            "account_number": "1234145",
            "is_mock": is_mock,
        },
        verification_status="VERIFIED",
    )


def _policy(**overrides) -> ResolvedRiskPolicy:
    base = dict(
        max_order_amount=Decimal("50000"),
        daily_max_order_amount=Decimal("200000"),
        max_total_investment_amount=Decimal("1000000"),
        max_position_amount=Decimal("200000"),
        max_position_count=5,
        max_position_weight=Decimal("0.2"),
        max_investment_ratio=Decimal("0.70"),
        allow_duplicate_buy=True,
        daily_max_loss_amount=Decimal("30000"),
        daily_max_loss_rate=Decimal("0.05"),
        stop_loss_rate=Decimal("0.05"),
        take_profit_rate=Decimal("0.1"),
        trailing_stop_rate=Decimal("0.03"),
        auto_trading_enabled=True,
        buy_enabled=True,
        sell_enabled=True,
        sell_only=False,
        account_paused=False,
        max_order_quantity=Decimal("1"),
        daily_order_limit=20,
        duplicate_order_window_seconds=5,
        max_open_orders=20,
        max_slippage_rate=Decimal("0.01"),
        anomaly_orders_per_minute=10,
        loop_detect_window_seconds=60,
        arm_ttl_seconds=300,
        source_layers=("system",),
    )
    base.update(overrides)
    return ResolvedRiskPolicy(**base)


def _uba(*, live: bool = True, broker: str = "KIWOOM"):
    return SimpleNamespace(
        user_broker_account_id=1381,
        user_id=61,
        broker_code=broker,
        account_alias="k",
        masked_account_number="***145",
        is_active=True,
        live_order_enabled=live,
        live_armed=True,
        arm_token_hash=None,
        arm_expires_at=None,
    )


def _pipeline_session(uba):
    session = MagicMock()
    session.get.return_value = uba
    session.scalar.side_effect = [0, None, None, 0, 0]
    session.scalars.return_value = []
    return session


def _eval_pipeline(
    *,
    price: Decimal,
    quantity: Decimal = Decimal("1"),
    order_type: str | None = "LIMIT",
    broker: str = "KIWOOM",
    exchange: str = "KRX",
    live: bool = True,
    reference_price: Decimal | None = None,
    policy: ResolvedRiskPolicy | None = None,
):
    session = _pipeline_session(_uba(live=live, broker=broker))
    with (
        patch(
            "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
        ) as resolver_cls,
        patch(
            "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
        ) as ks,
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="LIVE_SAFE_DEFAULTS"),
        ),
    ):
        ks.return_value.require_order_allowed.return_value = None
        resolver_cls.return_value.resolve.return_value = policy or _policy()
        return LiveOrderSafetyPipeline(session).evaluate(
            user_id=61,
            user_broker_account_id=1381,
            broker_code=broker,
            exchange_code=exchange,
            symbol="005930",
            side="BUY",
            quantity=quantity,
            price=price,
            order_type=order_type,
            reference_price=reference_price,
            emit_side_effects=False,
            require_arm=False,
            skip_market_hours=True,
        )


# --- A–E: MARKET_ENV Option D ---


def test_a_real_cred_global_mock_manual_limit_market_env_pass() -> None:
    report = _eval(_order_ready(env_kiwoom_use_mock=True), "ORDER")
    assert _check_status(report, "KIWOOM_MARKET_ENV") == "PASS"
    assert _check_status(report, "KIWOOM_REAL_ENV") == "PASS"
    assert report["overall_status"] == "READY_FOR_ORDER"
    assert report["manual_order_allowed"] is True


def test_b_missing_credential_market_env_fail() -> None:
    report = _eval(
        _order_ready(
            credential_present=False,
            credential_verified=False,
            credential_is_mock=None,
        ),
        "ORDER",
    )
    assert _check_status(report, "KIWOOM_CREDENTIAL") == "FAIL"
    assert _check_status(report, "KIWOOM_MARKET_ENV") == "FAIL"
    assert report["overall_status"] == "BLOCKED"


def test_c_mock_credential_real_manual_path_fail() -> None:
    report = _eval(_order_ready(credential_is_mock=True), "ORDER")
    assert _check_status(report, "KIWOOM_REAL_ENV") == "FAIL"
    assert _check_status(report, "KIWOOM_MARKET_ENV") == "FAIL"
    assert report["overall_status"] == "BLOCKED"


def test_d_shared_ws_mock_manual_allowed() -> None:
    report = _eval(_order_ready(env_kiwoom_use_mock=True), "ORDER")
    row = next(
        c for c in report["checks"] if c.get("code") == "KIWOOM_MARKET_ENV"
    )
    assert row["status"] == "PASS"
    assert row["detail"].get("shared_ws_mock") is True


def test_e_shared_market_mock_manual_allowed() -> None:
    report = _eval(_order_ready(env_kiwoom_use_mock=True), "ORDER")
    row = next(
        c for c in report["checks"] if c.get("code") == "KIWOOM_MARKET_ENV"
    )
    assert row["status"] == "PASS"
    assert row["detail"].get("market_use_mock") is True
    assert row["detail"].get("path") == "MANUAL"


# --- F–H: current price / tick ---


def test_f_limit_without_current_price_allowed() -> None:
    decision = _eval_pipeline(
        price=Decimal("1000"),
        reference_price=None,
        order_type="LIMIT",
    )
    assert decision.allowed is True
    assert decision.reason_code == "LIVE_SAFETY_PASS"


def test_g_valid_local_krx_tick_pass() -> None:
    assert is_krx_tick_aligned(Decimal("1000")) is True
    assert krx_tick_size(Decimal("2010")) == Decimal("5")
    decision = _eval_pipeline(price=Decimal("2010"), order_type="LIMIT")
    assert decision.allowed is True
    assert decision.reason_code == "LIVE_SAFETY_PASS"


def test_h_invalid_krx_tick_rejected_before_persist() -> None:
    assert is_krx_tick_aligned(Decimal("2001")) is False
    decision = _eval_pipeline(price=Decimal("2001"), order_type="LIMIT")
    assert decision.allowed is False
    assert decision.reason_code == "INVALID_KRX_TICK_SIZE"

    session = MagicMock()
    service = OrderExecutionService(session)
    create = MagicMock()
    service._order_service.create = create
    with (
        patch.object(
            service,
            "_resolve_account_ownership",
            return_value=(None, 1381),
        ),
        patch.object(
            service,
            "_resolve_size",
            return_value=(Decimal("1"), Decimal("2001"), None),
        ),
        patch(
            "stock_platform.trading.upbit_24x7_control.live_outbox_queue_block_reason",
            return_value=None,
        ),
        patch(
            "stock_platform.order.live_safety_pipeline.LiveOrderSafetyPipeline"
        ) as pipe,
    ):
        pipe.return_value.evaluate.return_value = SimpleNamespace(
            allowed=False,
            reason_code="INVALID_KRX_TICK_SIZE",
        )
        result = service.submit(
            OrderExecutionCommand(
                account_id=1,
                broker_code="KIWOOM",
                exchange_code="KRX",
                symbol="005930",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                price=Decimal("2001"),
                quantity=Decimal("1"),
                environment="LIVE",
                user_broker_account_id=1381,
                user_id=61,
                external_account_ref="UBA:1381",
            )
        )
    assert result.allowed is False
    assert result.reason_code == "INVALID_KRX_TICK_SIZE"
    create.assert_not_called()
    assert pipe.return_value.evaluate.call_args.kwargs["order_type"] == "LIMIT"


def test_h2_upbit_and_market_skip_krx_tick() -> None:
    upbit = _eval_pipeline(
        price=Decimal("2001"),
        order_type="LIMIT",
        broker="UPBIT",
        exchange="UPBIT",
    )
    assert upbit.reason_code != "INVALID_KRX_TICK_SIZE"
    market = _eval_pipeline(
        price=Decimal("2001"),
        order_type="MARKET",
        broker="KIWOOM",
    )
    assert market.reason_code != "INVALID_KRX_TICK_SIZE"


# --- I–M: 기존 gate 보존 ---


def test_i_krx_closed_session_fail_independent_of_market_env() -> None:
    report = _eval(
        _order_ready(
            krx_is_trading_day=False,
            krx_session_type="CLOSED",
            krx_in_regular_session=False,
            env_kiwoom_use_mock=True,
        ),
        "ORDER",
    )
    assert _check_status(report, "KIWOOM_MARKET_ENV") == "PASS"
    assert _check_status(report, "KIWOOM_MARKET_SESSION") == "FAIL"
    assert report["overall_status"] == "BLOCKED"


def test_j_live_off_gate_preserved() -> None:
    report = _eval(_order_ready(live_order_enabled=False), "ORDER")
    assert "ARM_LIVE_REQUIRED" in _codes(report, "FAIL")
    decision = _eval_pipeline(price=Decimal("1000"), live=False)
    assert decision.reason_code == "LIVE_ORDER_DISABLED"


def test_k_arm_off_gate_preserved() -> None:
    report = _eval(_order_ready(live_armed=False), "ORDER")
    assert "ARM_TOKEN" in _codes(report, "FAIL")
    assert report["overall_status"] == "BLOCKED"


def test_l_expired_arm_gate_preserved() -> None:
    report = _eval(
        _order_ready(arm_expires_at=_now() - timedelta(minutes=1)),
        "ORDER",
    )
    assert "ARM_TOKEN" in _codes(report, "FAIL")
    assert report["overall_status"] == "BLOCKED"


def test_m_risk_qty_amount_exceeded() -> None:
    amount = _eval_pipeline(
        price=Decimal("1000"),
        quantity=Decimal("1"),
        policy=_policy(max_order_amount=Decimal("500")),
    )
    assert amount.reason_code == "ORDER_AMOUNT_EXCEEDED"
    qty = _eval_pipeline(
        price=Decimal("1000"),
        quantity=Decimal("2"),
        policy=_policy(max_order_quantity=Decimal("1")),
    )
    assert qty.reason_code == "ORDER_QTY_EXCEEDED"


# --- N–P: host / SYSTEM_SHARED ---


def test_n_adapter_execution_host_real_credential_scoped(monkeypatch) -> None:
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    session = MagicMock()
    fake = SimpleNamespace(
        config=SimpleNamespace(
            base_url=KIWOOM_REAL_EXECUTION_BASE, use_mock=False
        )
    )
    try:
        with (
            patch(
                "stock_platform.broker.factory.LiveTradingTransitionGuard.require_active",
            ),
            patch(
                "stock_platform.broker.factory.build_kiwoom_adapter_for_uba",
                return_value=fake,
            ) as build_mock,
            patch(
                "stock_platform.broker.kiwoom.execution_env.kiwoom_global_mock_blocks_live_execution",
                return_value=False,
            ),
        ):
            adapter = BrokerAdapterFactory.create(
                BrokerEnvironment.LIVE,
                "KIWOOM",
                session=session,
                user_broker_account_id=1381,
            )
        build_mock.assert_called_once_with(session, 1381)
        assert adapter.config.base_url == KIWOOM_REAL_EXECUTION_BASE
    finally:
        get_settings.cache_clear()


def test_o_inquiry_host_real_credential_scoped(monkeypatch) -> None:
    monkeypatch.setattr(
        "stock_platform.broker.credential_adapter_factory.get_settings",
        lambda: SimpleNamespace(
            kiwoom_use_mock=True,
            kiwoom_live_order_enabled=False,
            kiwoom_http_timeout_seconds=10.0,
            kiwoom_max_requests_per_second=5,
        ),
    )
    cfg = build_kiwoom_order_config_from_vault(_real_resolved(is_mock=False))
    assert cfg.base_url == KIWOOM_REAL_EXECUTION_BASE
    assert cfg.use_mock is False

    session = MagicMock()
    with (
        patch(
            "stock_platform.broker.credential_adapter_factory.resolve_uba_credential",
            return_value=_real_resolved(is_mock=False),
        ),
        patch(
            "stock_platform.broker.credential_adapter_factory.KiwoomTokenClient",
        ),
        patch(
            "stock_platform.broker.credential_adapter_factory.KiwoomOrderRestClient",
        ) as rest_cls,
        patch(
            "stock_platform.broker.kiwoom.inquiry_client.KiwoomOrderInquiryClient",
        ) as inq_cls,
    ):
        from stock_platform.broker.credential_adapter_factory import (
            build_kiwoom_order_inquiry_client_for_uba,
        )

        rest_cls.return_value = MagicMock()
        build_kiwoom_order_inquiry_client_for_uba(session, 1381)
    rest_cfg = rest_cls.call_args.kwargs.get("config") or rest_cls.call_args[0][0]
    assert rest_cfg.base_url == KIWOOM_REAL_EXECUTION_BASE
    inq_cls.assert_called_once()


def test_p_system_shared_remains_mock_blocked(monkeypatch) -> None:
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "true")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    try:
        assert kiwoom_global_mock_blocks_live_execution(
            None,
            user_broker_account_id=None,
            uses_system_shared_credential=True,
        )
        assert get_settings().kiwoom_use_mock is True
    finally:
        get_settings.cache_clear()


# --- Q–S: isolation / Upbit / no network ---


def test_q_other_kiwoom_uba_unaffected() -> None:
    one = _eval(_order_ready(uba_id=1381), "ORDER")
    other = _eval(
        _order_ready(
            uba_id=1399,
            credential_present=False,
            credential_verified=False,
            credential_is_mock=None,
        ),
        "ORDER",
    )
    again = _eval(_order_ready(uba_id=1381), "ORDER")
    assert _check_status(one, "KIWOOM_MARKET_ENV") == "PASS"
    assert _check_status(other, "KIWOOM_MARKET_ENV") == "FAIL"
    assert _check_status(again, "KIWOOM_MARKET_ENV") == "PASS"
    assert again["user_broker_account_id"] == 1381


def test_r_upbit_dispatch_does_not_use_kiwoom() -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(
        user_id=61,
        broker_code="UPBIT",
        deleted_at=None,
        is_active=True,
    )
    with patch(
        "stock_platform.broker.kiwoom.live_preflight_service.KiwoomLivePreflightService.run"
    ) as krun:
        from stock_platform.operation.runtime_preflight_service import (
            RuntimePreflightService,
        )

        try:
            RuntimePreflightService(session).run_for_uba(
                user_broker_account_id=1380
            )
        except Exception:
            pass
    krun.assert_not_called()


def test_s_evaluate_makes_no_broker_network_call() -> None:
    with (
        patch("stock_platform.broker.kiwoom.client.KiwoomRestClient") as rest,
        patch(
            "stock_platform.broker.kiwoom.http_client.KiwoomRestClient"
        ) as order_rest,
    ):
        report = _eval(_order_ready(), "ORDER")
    rest.assert_not_called()
    order_rest.assert_not_called()
    assert _check_status(report, "KIWOOM_MARKET_ENV") == "PASS"


# --- T–U: AUTO must not inherit MANUAL PASS ---


def test_t_scheduler_shared_mock_market_env_fail() -> None:
    report = _eval(_order_ready(env_kiwoom_use_mock=True), "SCHEDULER_RUN")
    assert _check_status(report, "KIWOOM_MARKET_ENV") == "FAIL"
    assert report["overall_status"] == "BLOCKED"
    row = next(
        c for c in report["checks"] if c.get("code") == "KIWOOM_MARKET_ENV"
    )
    assert row["detail"].get("path") == "AUTO"


def test_u_manual_pass_does_not_propagate_to_auto() -> None:
    snap = _order_ready(env_kiwoom_use_mock=True)
    manual = _eval(snap, "ORDER")
    auto = _eval(snap, "SCHEDULER_RUN")
    assert _check_status(manual, "KIWOOM_MARKET_ENV") == "PASS"
    assert _check_status(auto, "KIWOOM_MARKET_ENV") == "FAIL"
    assert manual["overall_status"] == "READY_FOR_ORDER"
    assert auto["overall_status"] == "BLOCKED"


def test_g17_pre_live_regression_ready() -> None:
    report = _eval(
        _healthy(
            credential_is_mock=False,
            env_kiwoom_use_mock=True,
            trading_paused=False,
        ),
        "LIVE_ON",
    )
    assert _check_status(report, "KIWOOM_REAL_ENV") == "PASS"
    assert _check_status(report, "KIWOOM_MARKET_ENV") == "WARN"
    assert _check_status(report, "KIWOOM_RISK") == "PASS"
    assert _check_status(report, "TRADING_PAUSED") == "PASS"
    assert report["overall_status"] == "READY_FOR_LIVE"
    assert report["live_on_allowed"] is True


def test_mock_host_constant_unchanged() -> None:
    assert KIWOOM_MOCK_EXECUTION_BASE == "https://mockapi.kiwoom.com"
    assert KIWOOM_REAL_EXECUTION_BASE == "https://api.kiwoom.com"
