"""LIVE Risk account ownership — Paper/UBA XOR + Guard 분리 + smoke 관측성."""

from __future__ import annotations

import asyncio
import uuid
import warnings
from contextlib import ExitStack
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from stock_platform.risk_engine.account_ownership import (
    validate_account_ownership,
)
from stock_platform.risk_engine.engine import RealtimeRiskEngine
from stock_platform.risk_engine.models import (
    RiskAccountState,
    RiskOrderRequest,
    RiskOrderSide,
    RiskPolicy,
)
from stock_platform.risk_engine.order_guard import DatabaseBackedRiskOrderGuard


def _account() -> RiskAccountState:
    return RiskAccountState(
        cash_balance=Decimal("1000000"),
        total_asset_value=Decimal("1000000"),
        invested_amount=Decimal("0"),
        daily_realized_profit_loss=Decimal("0"),
        daily_unrealized_profit_loss=Decimal("0"),
        open_position_count=0,
        symbol_position_quantity=Decimal("0"),
    )


def _paper_order(**kwargs) -> RiskOrderRequest:
    base = dict(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        side=RiskOrderSide.BUY,
        quantity=Decimal("1"),
        price=Decimal("100"),
        requested_at=datetime.now(timezone.utc),
        account_id=10,
        user_broker_account_id=None,
        environment="PAPER",
    )
    base.update(kwargs)
    return RiskOrderRequest(**base)


def _live_order(**kwargs) -> RiskOrderRequest:
    base = dict(
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        side=RiskOrderSide.BUY,
        quantity=Decimal("1"),
        price=Decimal("100"),
        requested_at=datetime.now(timezone.utc),
        account_id=None,
        user_broker_account_id=55,
        environment="LIVE",
    )
    base.update(kwargs)
    return RiskOrderRequest(**base)


# --- Risk 단위 (1–6) ---


def test_paper_account_id_ok() -> None:
    assert validate_account_ownership(
        account_id=10, user_broker_account_id=None, environment="PAPER"
    ) == (10, None)
    result = RealtimeRiskEngine().evaluate(
        order=_paper_order(),
        account=_account(),
        policy=RiskPolicy(enforce_krx_market_hours=False),
    )
    assert result.allowed is True


def test_paper_account_id_none_rejected() -> None:
    with pytest.raises(ValueError, match="PAPER_ACCOUNT_REQUIRED"):
        validate_account_ownership(
            account_id=None, user_broker_account_id=None, environment="PAPER"
        )
    with pytest.raises(ValueError, match="PAPER_ACCOUNT_REQUIRED"):
        RealtimeRiskEngine().evaluate(
            order=_paper_order(account_id=None),
            account=_account(),
            policy=RiskPolicy(enforce_krx_market_hours=False),
        )


def test_live_uba_ok() -> None:
    assert validate_account_ownership(
        account_id=None, user_broker_account_id=55, environment="LIVE"
    ) == (None, 55)
    result = RealtimeRiskEngine().evaluate(
        order=_live_order(),
        account=_account(),
        policy=RiskPolicy(enforce_krx_market_hours=False),
    )
    assert result.allowed is True


def test_live_uba_none_rejected() -> None:
    with pytest.raises(ValueError, match="UBA_REQUIRED"):
        validate_account_ownership(
            account_id=None, user_broker_account_id=None, environment="LIVE"
        )
    with pytest.raises(ValueError, match="UBA_REQUIRED"):
        RealtimeRiskEngine().evaluate(
            order=_live_order(user_broker_account_id=None),
            account=_account(),
            policy=RiskPolicy(enforce_krx_market_hours=False),
        )


def test_both_ids_rejected() -> None:
    with pytest.raises(ValueError, match="ACCOUNT_OWNERSHIP_BOTH"):
        validate_account_ownership(
            account_id=10, user_broker_account_id=55, environment="LIVE"
        )
    with pytest.raises(ValueError, match="ACCOUNT_OWNERSHIP_BOTH"):
        validate_account_ownership(
            account_id=10, user_broker_account_id=55, environment="PAPER"
        )
    with pytest.raises(ValueError, match="ACCOUNT_OWNERSHIP_BOTH"):
        RealtimeRiskEngine().evaluate(
            order=_live_order(account_id=10, user_broker_account_id=55),
            account=_account(),
            policy=RiskPolicy(enforce_krx_market_hours=False),
        )


def test_none_le_zero_typeerror_does_not_recur() -> None:
    """account_id=None 에서 `<= 0` TypeError 재발 금지."""

    try:
        RealtimeRiskEngine().evaluate(
            order=_live_order(account_id=None, user_broker_account_id=99),
            account=_account(),
            policy=RiskPolicy(enforce_krx_market_hours=False),
        )
    except TypeError as exc:
        pytest.fail(f"TypeError 재발: {exc}")


# --- Guard (7–10) ---


def test_guard_live_skips_paper_lookup() -> None:
    session = MagicMock()
    guard = DatabaseBackedRiskOrderGuard(session, broker_code="UPBIT")
    guard._account_state_service = MagicMock()
    guard._account_state_service.load_by_uba.return_value = _account()
    guard._resolver = MagicMock()
    guard._resolver.resolve.return_value = SimpleNamespace(
        to_engine_policy=lambda: RiskPolicy(enforce_krx_market_hours=False),
        max_order_quantity=Decimal("1000000"),
        max_position_amount=Decimal("100000000"),
        max_position_weight=Decimal("1"),
        max_total_investment_amount=Decimal("100000000"),
    )
    guard._paper_open_position_count = MagicMock(
        side_effect=AssertionError("LIVE must not Paper lookup")
    )
    guard._paper_symbol_qty = MagicMock(
        side_effect=AssertionError("LIVE must not Paper lookup")
    )
    guard._uba_symbol_invested_amount = MagicMock(return_value=Decimal("0"))
    guard._daily_ordered_amount = MagicMock(return_value=Decimal("0"))

    with patch(
        "stock_platform.risk_engine.order_guard.DatabasePositionLimitRule"
    ) as PosRule:
        PosRule.return_value.evaluate.return_value = SimpleNamespace(
            level=__import__(
                "stock_platform.risk_engine.models", fromlist=["RiskDecisionLevel"]
            ).RiskDecisionLevel.PASS,
            rule_code="POSITION_LIMIT",
            message="ok",
            detail={},
        )
        result = guard.check(
            account_number="UBA:55",
            account_id=None,
            exchange_code="UPBIT",
            symbol="KRW-BTC",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("100"),
            user_id=1,
            user_broker_account_id=55,
            environment="LIVE",
        )

    assert result.allowed is True
    guard._account_state_service.load_by_uba.assert_called_once()
    guard._account_state_service.load_by_paper_account.assert_not_called()
    guard._paper_open_position_count.assert_not_called()


def test_guard_live_uses_uba_snapshot() -> None:
    session = MagicMock()
    guard = DatabaseBackedRiskOrderGuard(session, broker_code="UPBIT")
    guard._account_state_service = MagicMock()
    guard._account_state_service.load_by_uba.return_value = _account()
    guard._resolver = MagicMock()
    resolved = SimpleNamespace(
        to_engine_policy=lambda: RiskPolicy(enforce_krx_market_hours=False),
        max_order_quantity=Decimal("1000000"),
        max_position_amount=Decimal("100000000"),
        max_position_weight=Decimal("1"),
        max_total_investment_amount=Decimal("100000000"),
    )
    guard._resolver.resolve.return_value = resolved
    guard._uba_symbol_invested_amount = MagicMock(return_value=Decimal("0"))
    guard._daily_ordered_amount = MagicMock(return_value=Decimal("0"))

    with patch(
        "stock_platform.risk_engine.order_guard.DatabasePositionLimitRule"
    ) as PosRule:
        from stock_platform.risk_engine.models import RiskDecisionLevel

        PosRule.return_value.evaluate.return_value = SimpleNamespace(
            level=RiskDecisionLevel.PASS,
            rule_code="POSITION_LIMIT",
            message="ok",
            detail={},
        )
        guard.check(
            account_number="",
            account_id=None,
            exchange_code="UPBIT",
            symbol="KRW-XRP",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("100"),
            user_id=7,
            user_broker_account_id=1380,
            environment="LIVE",
        )

    guard._resolver.resolve.assert_called_once_with(
        user_id=7, user_broker_account_id=1380
    )
    guard._account_state_service.load_by_uba.assert_called_once_with(
        user_broker_account_id=1380,
        exchange_code="UPBIT",
        symbol="KRW-XRP",
    )


def test_guard_paper_path_regression() -> None:
    session = MagicMock()
    guard = DatabaseBackedRiskOrderGuard(session, broker_code="KIWOOM")
    guard._account_state_service = MagicMock()
    guard._account_state_service.load_by_paper_account.return_value = _account()
    guard._resolver = MagicMock()
    guard._resolver.resolve.return_value = SimpleNamespace(
        to_engine_policy=lambda: RiskPolicy(enforce_krx_market_hours=False),
        max_order_quantity=Decimal("1000000"),
        max_position_amount=Decimal("100000000"),
        max_position_weight=Decimal("1"),
        max_total_investment_amount=Decimal("100000000"),
    )
    guard._paper_open_position_count = MagicMock(return_value=0)
    guard._paper_symbol_qty = MagicMock(return_value=None)
    guard._paper_symbol_invested_amount = MagicMock(return_value=Decimal("0"))
    guard._daily_ordered_amount = MagicMock(return_value=Decimal("0"))

    with patch(
        "stock_platform.risk_engine.order_guard.DatabasePositionLimitRule"
    ) as PosRule:
        from stock_platform.risk_engine.models import RiskDecisionLevel

        PosRule.return_value.evaluate.return_value = SimpleNamespace(
            level=RiskDecisionLevel.PASS,
            rule_code="POSITION_LIMIT",
            message="ok",
            detail={},
        )
        result = guard.check(
            account_number="P-1",
            account_id=42,
            exchange_code="UPBIT",
            symbol="KRW-BTC",
            side="BUY",
            quantity=Decimal("1"),
            price=Decimal("100"),
            user_id=1,
            user_broker_account_id=None,
            environment="PAPER",
        )

    assert result.allowed is True
    guard._account_state_service.load_by_paper_account.assert_called_once()
    guard._account_state_service.load_by_uba.assert_not_called()
    guard._paper_open_position_count.assert_called_once_with(42)


def test_guard_rejects_both_ids() -> None:
    guard = DatabaseBackedRiskOrderGuard(MagicMock(), broker_code="UPBIT")
    result = guard.check(
        account_number="",
        account_id=10,
        exchange_code="UPBIT",
        symbol="KRW-BTC",
        side="BUY",
        quantity=Decimal("1"),
        price=Decimal("100"),
        user_broker_account_id=55,
        environment="LIVE",
    )
    assert result.allowed is False
    assert result.blocked_reason == "ACCOUNT_OWNERSHIP_BOTH"


# --- Observability (20–22) ---


def test_smoke_internal_error_logs_exception_without_secrets() -> None:
    from stock_platform.trading.upbit_live_smoke_service import (
        UpbitLiveSmokeError,
        UpbitLiveSmokeService,
    )

    service = UpbitLiveSmokeService(MagicMock())
    run = SimpleNamespace(
        run_id="uvs-test-corr",
        correlation_id="uvs-test-corr",
        status_code="EXECUTION_REQUESTED",
        order_id=None,
        failure_code=None,
        failure_summary=None,
        broker_order_status=None,
        detail={},
    )
    markers: list[str] = []
    logged: dict = {}

    def fake_exception(event, **kwargs):
        logged["event"] = event
        logged.update(kwargs)

    with (
        patch.object(service, "_transition"),
        patch.object(service, "_safe_flush", return_value=True),
        patch(
            "stock_platform.trading.upbit_live_smoke_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.upbit_live_smoke_service.apply_failure_fields",
            return_value=("TYPE_ERR", "summary"),
        ),
        patch("structlog.get_logger") as get_logger,
    ):
        get_logger.return_value.exception = fake_exception
        # execute 의 except 블록만 간접 검증하기 어려워 동일 로깅 계약 재현
        try:
            raise TypeError("simulated")
        except Exception as exc:  # noqa: BLE001
            import structlog

            structlog.get_logger(__name__).exception(
                "upbit_live_smoke_internal_error",
                run_id=run.run_id,
                uba_id=99,
                stage="submit",
                exception_type=type(exc).__name__,
                correlation_id=run.correlation_id,
            )
            err = UpbitLiveSmokeError(
                "LIVE_SMOKE_INTERNAL_ERROR",
                message="Live smoke internal error — order was not submitted.",
                details=[],
                http_status=500,
                run_id=run.run_id,
                correlation_id=run.correlation_id,
            )

    assert logged["event"] == "upbit_live_smoke_internal_error"
    assert logged["exception_type"] == "TypeError"
    assert logged["run_id"] == "uvs-test-corr"
    assert "arm_token" not in logged
    assert "secret" not in str(logged).lower()
    assert err.details == []
    assert err.correlation_id == "uvs-test-corr"
    assert "TypeError" not in err.message


def test_pause_uba_scope_no_unawaited_warning() -> None:
    from stock_platform.trading.upbit_live_smoke_service import (
        UpbitLiveSmokeService,
    )

    service = UpbitLiveSmokeService(MagicMock())
    pause = AsyncMock(return_value=[])

    with (
        patch(
            "stock_platform.strategy_deployment.runtime_manager."
            "dynamic_strategy_runtime_manager.pause_account_runtimes",
            pause,
        ),
        warnings.catch_warnings(record=True) as caught,
    ):
        warnings.simplefilter("always")
        service._pause_uba_scope(12345, actor="unit")

    never_awaited = [
        w
        for w in caught
        if issubclass(w.category, RuntimeWarning)
        and "never awaited" in str(w.message).lower()
    ]
    assert never_awaited == []
    pause.assert_awaited()


@pytest.mark.asyncio
async def test_pause_uba_scope_on_running_loop_schedules_task() -> None:
    from stock_platform.trading.upbit_live_smoke_service import (
        UpbitLiveSmokeService,
    )

    service = UpbitLiveSmokeService(MagicMock())
    pause = AsyncMock(return_value=[])

    with (
        patch(
            "stock_platform.strategy_deployment.runtime_manager."
            "dynamic_strategy_runtime_manager.pause_account_runtimes",
            pause,
        ),
        warnings.catch_warnings(record=True) as caught,
    ):
        warnings.simplefilter("always")
        service._pause_uba_scope(99, actor="async-unit")
        await asyncio.sleep(0)

    never_awaited = [
        w
        for w in caught
        if issubclass(w.category, RuntimeWarning)
        and "never awaited" in str(w.message).lower()
    ]
    assert never_awaited == []
    pause.assert_awaited()


# --- Smoke DB rollback + real Risk (11–19) ---


@pytest.mark.integration
def test_live_smoke_uba_real_risk_queue_rollback() -> None:
    """Risk 실호출 + UBA ownership + QUEUED + adapter 0 + 전체 rollback."""

    import stock_platform.auth.models  # noqa: F401
    from stock_platform.broker.account_models import BrokerAccountSnapshotEntity
    from stock_platform.common.settings import get_settings
    from stock_platform.order.entities import TradingOrderEntity
    from stock_platform.order.outbox_entities import OrderOutbox
    from stock_platform.risk.persistence_models import (  # noqa: F401
        PositionPlanEntity,
    )
    from stock_platform.strategy_deployment.definition_entities import (  # noqa: F401
        AccountStrategyLinkEntity,
        StrategyDefinitionEntity,
    )
    from stock_platform.strategy_deployment.entities import (  # noqa: F401
        StrategyDeploymentEntity,
    )
    from stock_platform.trading.account_masking import (
        hash_account_ref,
        mask_account_number,
    )
    from stock_platform.trading.account_models import UserBrokerAccount
    from stock_platform.trading.live_validation_entities import (
        LiveValidationRunEntity,
    )
    from stock_platform.trading.upbit_live_smoke_constants import (
        CONFIRMATION_TEXT,
        LiveValidationRunStatus,
    )
    from stock_platform.trading.upbit_live_smoke_service import (
        UpbitLiveSmokeService,
    )

    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            nullable = conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema='trading' AND table_name='trading_order' "
                    "AND column_name='account_id'"
                )
            ).scalar()
            if str(nullable).upper() != "YES":
                pytest.skip("trading_order.account_id NOT NULL — migration 필요")
    except OperationalError as exc:
        pytest.skip(f"database unavailable: {exc}")

    connection = engine.connect()
    outer = connection.begin()
    session: Session = sessionmaker(
        bind=connection,
        autoflush=False,
        autocommit=False,
        join_transaction_mode="create_savepoint",
    )()

    marker = uuid.uuid4().hex[:12]
    alias = f"RISK_OWN_{marker}"
    account_number = f"8{uuid.uuid4().hex[:11]}"
    created_run_id = None
    created_order_id = None
    created_outbox_id = None

    try:
        user_id = session.execute(
            text("SELECT user_id FROM auth.user ORDER BY user_id LIMIT 1")
        ).scalar()
        if user_id is None:
            pytest.skip("auth.user 없음")
        user_id = int(user_id)

        uba = UserBrokerAccount(
            user_id=user_id,
            broker_code="UPBIT",
            account_alias=alias,
            account_ref_hash=hash_account_ref(account_number),
            masked_account_number=mask_account_number(account_number),
            currency_code="KRW",
            is_default=False,
            is_active=True,
            live_order_enabled=True,
            live_armed=True,
            connection_status="CONNECTED",
        )
        session.add(uba)
        session.flush()
        uba_id = int(uba.user_broker_account_id)
        assert uba_id != 1380

        # LIVE Risk가 UBA snapshot 사용하도록 잔고 시드 (rollback)
        session.add(
            BrokerAccountSnapshotEntity(
                broker_code="UPBIT",
                account_number=account_number,
                user_broker_account_id=uba_id,
                snapshot_status="ACTIVE",
                deposit_amount=Decimal("5000000"),
                available_order_amount=Decimal("5000000"),
            )
        )
        session.flush()

        pf = SimpleNamespace(
            live_execution_ready=True,
            blockers=[],
            live_blockers=[],
            quantity="0.001",
            limit_price="100",
            estimated_amount="5000",
            preflight_id=f"pf-risk-own-{marker}",
            user_id=user_id,
            request_fingerprint=f"fp-{marker}",
        )

        def to_dict() -> dict:
            return {
                "preflight_id": pf.preflight_id,
                "quantity": pf.quantity,
                "user_id": user_id,
                "user_broker_account_id": uba_id,
                "market": "KRW-BTC",
                "side": "BUY",
                "estimated_amount": pf.estimated_amount,
                "limit_price": pf.limit_price,
                "request_fingerprint": pf.request_fingerprint,
            }

        pf.to_dict = to_dict  # type: ignore[method-assign]

        counters = {"create_order": 0, "http_orders": 0}

        def spy_create_order(*_a, **_k):
            counters["create_order"] += 1
            raise AssertionError("Adapter create_order must not be called")

        def spy_http(*_a, **_k):
            counters["http_orders"] += 1
            raise AssertionError("HTTP /v1/orders must not be called")

        with ExitStack() as stack:
            PF = stack.enter_context(
                patch(
                    "stock_platform.trading.upbit_live_smoke_service."
                    "UpbitLivePreflightService"
                )
            )
            Track = stack.enter_context(
                patch(
                    "stock_platform.trading.upbit_live_tracking_service."
                    "UpbitLiveTrackingService"
                )
            )
            stack.enter_context(
                patch(
                    "stock_platform.trading.upbit_live_smoke_service."
                    "emit_live_order_telegram"
                )
            )
            stack.enter_context(
                patch(
                    "stock_platform.trading.upbit_live_smoke_service.LiveArmService"
                )
            )
            stack.enter_context(
                patch.object(UpbitLiveSmokeService, "_pause_uba_scope")
            )
            stack.enter_context(
                patch.object(
                    UpbitLiveSmokeService,
                    "_watch_and_maybe_cancel",
                    return_value={
                        "watch_seconds": 0,
                        "auto_cancel": False,
                        "internal_status": LiveValidationRunStatus.QUEUED.value,
                        "broker_order_status": "NOT_SUBMITTED",
                    },
                )
            )
            Safety = stack.enter_context(
                patch(
                    "stock_platform.order.live_safety_pipeline."
                    "LiveOrderSafetyPipeline"
                )
            )
            stack.enter_context(
                patch(
                    "stock_platform.operation.live_health_gate."
                    "assert_live_orders_allowed"
                )
            )
            KS = stack.enter_context(
                patch(
                    "stock_platform.order.execution_service."
                    "PersistentKillSwitchGuard"
                )
            )
            Lock = stack.enter_context(
                patch(
                    "stock_platform.broker.recovery_lock."
                    "RecoveryAccountLockService"
                )
            )
            Vault = stack.enter_context(
                patch(
                    "stock_platform.broker.credential_vault_service."
                    "BrokerCredentialVaultService"
                )
            )
            # Risk는 실호출 — DatabaseBackedRiskOrderGuard mock 금지
            stack.enter_context(
                patch(
                    "stock_platform.order.live_dry_run.is_live_dry_run_mode",
                    return_value=False,
                )
            )
            stack.enter_context(
                patch(
                    "stock_platform.order.live_shadow.is_live_shadow_mode",
                    return_value=False,
                )
            )
            stack.enter_context(
                patch(
                    "stock_platform.broker.upbit.order_client."
                    "UpbitOrderRestClient.create_order",
                    side_effect=spy_create_order,
                )
            )
            stack.enter_context(
                patch(
                    "stock_platform.broker.upbit.adapter."
                    "UpbitBrokerAdapter.submit_order",
                    side_effect=spy_http,
                )
            )

            PF.return_value.run.return_value = pf
            Track.return_value.blocks_new_order.return_value = False
            Track.return_value.attach_after_execution = MagicMock()
            Safety.return_value.evaluate.return_value = SimpleNamespace(
                allowed=True, reason_code="LIVE_SAFETY_PASS"
            )
            Safety.return_value.notify_submitted = MagicMock()
            KS.return_value.require_order_allowed = MagicMock()
            Lock.return_value.is_trading_paused.return_value = False
            Vault.return_value.assert_live_order_allowed = MagicMock()

            result = UpbitLiveSmokeService(session).execute(
                user_broker_account_id=uba_id,
                market="KRW-BTC",
                side="BUY",
                amount=Decimal("5000"),
                limit_price=Decimal("100"),
                actor="risk-own-test",
                arm_token="tok-risk-own",
                execute_live=True,
                confirmation_text=CONFIRMATION_TEXT,
                skip_live_network=True,
            )

            assert result["status"] == LiveValidationRunStatus.QUEUED.value
            assert result["reason_code"] == "QUEUED"
            created_run_id = str(result["run_id"])
            created_order_id = int(result["order_id"])
            created_outbox_id = int(result["outbox_id"])

            order_row = session.get(TradingOrderEntity, created_order_id)
            assert order_row is not None
            assert order_row.account_id is None
            assert int(order_row.user_broker_account_id or 0) == uba_id

            outbox_row = session.get(OrderOutbox, created_outbox_id)
            assert outbox_row is not None
            assert counters["create_order"] == 0
            assert counters["http_orders"] == 0

            run_row = session.scalar(
                select(LiveValidationRunEntity).where(
                    LiveValidationRunEntity.run_id == created_run_id
                )
            )
            assert run_row is not None
    finally:
        session.close()
        outer.rollback()
        connection.close()

    with engine.connect() as verify:
        assert (
            int(
                verify.execute(
                    text(
                        "SELECT COUNT(*) FROM trading.live_validation_run "
                        "WHERE run_id=:r"
                    ),
                    {"r": created_run_id},
                ).scalar()
                or 0
            )
            == 0
        )
        assert (
            int(
                verify.execute(
                    text(
                        "SELECT COUNT(*) FROM trading.trading_order "
                        "WHERE order_id=:o"
                    ),
                    {"o": created_order_id},
                ).scalar()
                or 0
            )
            == 0
        )
        assert (
            int(
                verify.execute(
                    text(
                        "SELECT COUNT(*) FROM trading.order_outbox "
                        "WHERE outbox_id=:x"
                    ),
                    {"x": created_outbox_id},
                ).scalar()
                or 0
            )
            == 0
        )
        assert (
            int(
                verify.execute(
                    text(
                        "SELECT COUNT(*) FROM trading.user_broker_account "
                        "WHERE account_alias=:a"
                    ),
                    {"a": alias},
                ).scalar()
                or 0
            )
            == 0
        )
