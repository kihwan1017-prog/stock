"""STEP 8-9 — Upbit Live Smoke 단위 테스트 (실주문 금지)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.trading.upbit_live_smoke_constants import (
    CONFIRMATION_TEXT,
    MAX_SMOKE_AMOUNT,
)
from stock_platform.trading.upbit_live_preflight_service import (
    UpbitLivePreflightService,
)
from stock_platform.trading.upbit_live_smoke_service import (
    UpbitLiveSmokeError,
    UpbitLiveSmokeService,
)


def _uba(**overrides):
    base = dict(
        user_broker_account_id=7,
        user_id=1,
        broker_code="UPBIT",
        is_active=True,
        live_order_enabled=True,
        live_armed=True,
        arm_token_hash="x",
        arm_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        arm_armed_by="admin",
        arm_armed_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _policy(**overrides):
    from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicy

    base = dict(
        max_order_amount=Decimal("10000"),
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
        max_order_quantity=Decimal("100"),
        daily_order_limit=20,
        duplicate_order_window_seconds=5,
        max_open_orders=20,
        max_slippage_rate=Decimal("0.05"),
        anomaly_orders_per_minute=10,
        loop_detect_window_seconds=60,
        arm_ttl_seconds=300,
        source_layers=("system",),
    )
    base.update(overrides)
    return ResolvedRiskPolicy(**base)


def _preflight_ctx(
    *,
    uba=None,
    policy=None,
    kill_active: bool = False,
    open_orders: int = 0,
    arm_ok: bool = True,
    arm_token_ok: bool = True,
):
    from stock_platform.risk_engine.kill_switch_models import (
        KillSwitchState,
        KillSwitchStatus,
    )

    uba = uba or _uba()
    policy = policy or _policy()
    return (
        uba,
        policy,
        (
            patch(
                "stock_platform.trading.upbit_live_preflight_service.KillSwitchService"
            ),
            patch(
                "stock_platform.trading.upbit_live_preflight_service.LiveArmService"
            ),
            patch(
                "stock_platform.trading.upbit_live_preflight_service.ResolvedRiskPolicyResolver"
            ),
            patch(
                "stock_platform.trading.upbit_live_preflight_service.emit_live_safety_audit"
            ),
            patch.object(
                UpbitLivePreflightService,
                "_check_credential",
                return_value=(True, "ok"),
            ),
            patch.object(
                UpbitLivePreflightService,
                "_check_broker_health",
                return_value=(True, "ok"),
            ),
            patch.object(
                UpbitLivePreflightService,
                "_open_order_count",
                return_value=open_orders,
            ),
            patch.object(
                UpbitLivePreflightService,
                "_daily_order_count",
                return_value=0,
            ),
        ),
        KillSwitchState(
            status=(
                KillSwitchStatus.ACTIVE
                if kill_active
                else KillSwitchStatus.INACTIVE
            ),
            reason=None,
            activated_by=None,
            activated_at=None,
            deactivated_by=None,
            deactivated_at=None,
        ),
        arm_ok,
        arm_token_ok,
    )


def _run_preflight(
    session,
    *,
    market="KRW-XRP",
    side="BUY",
    amount=Decimal("5000"),
    limit_price=Decimal("500"),
    arm_token=None,
    kill_active=False,
    open_orders=0,
    uba=None,
    policy=None,
    broker_ok=True,
    cred_ok=True,
):
    uba, policy, patches, ks, arm_ok, arm_token_ok = _preflight_ctx(
        uba=uba,
        policy=policy,
        kill_active=kill_active,
        open_orders=open_orders,
    )
    session.get.return_value = uba
    with patches[0] as KS, patches[1] as ARM, patches[2] as R, patches[3], \
            patches[4], patches[5], patches[6], patches[7]:
        if not broker_ok:
            patches[5].return_value = (False, "down")  # won't work - already applied
        KS.return_value.get_state.return_value = ks
        ARM.return_value.expire_if_needed.return_value = False
        ARM.return_value.get_arm_status.return_value = {
            "live_armed": arm_ok and bool(uba.live_armed),
            "arm_expires_at": (
                uba.arm_expires_at.isoformat()
                if uba.arm_expires_at
                else None
            ),
        }
        ARM.return_value.validate_arm_token.return_value = (
            (True, "ARM_OK") if arm_token_ok else (False, "ARM_TOKEN_INVALID")
        )
        ARM.return_value.validate_arm_authorization.return_value = (
            (True, "ARM_OK") if arm_token_ok else (False, "ARM_TOKEN_INVALID")
        )
        R.return_value.resolve.return_value = policy
        if not broker_ok:
            with patch.object(
                UpbitLivePreflightService,
                "_check_broker_health",
                return_value=(False, "down"),
            ):
                return UpbitLivePreflightService(session).run(
                    user_broker_account_id=7,
                    market=market,
                    side=side,
                    amount=amount,
                    limit_price=limit_price,
                    arm_token=arm_token,
                    skip_live_network=True,
                )
        if not cred_ok:
            with patch.object(
                UpbitLivePreflightService,
                "_check_credential",
                return_value=(False, "missing"),
            ):
                return UpbitLivePreflightService(session).run(
                    user_broker_account_id=7,
                    market=market,
                    side=side,
                    amount=amount,
                    limit_price=limit_price,
                    arm_token=arm_token,
                    skip_live_network=True,
                )
        return UpbitLivePreflightService(session).run(
            user_broker_account_id=7,
            market=market,
            side=side,
            amount=amount,
            limit_price=limit_price,
            arm_token=arm_token,
            skip_live_network=True,
        )


def test_confirmation_text_must_exact() -> None:
    assert CONFIRMATION_TEXT == "UPBIT-LIVE-ONE-ORDER"
    session = MagicMock()
    svc = UpbitLiveSmokeService(session)
    with pytest.raises(UpbitLiveSmokeError, match="CONFIRMATION"):
        svc.execute(
            user_broker_account_id=7,
            market="KRW-XRP",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=Decimal("500"),
            actor="t",
            arm_token="tok",
            execute_live=True,
            confirmation_text="upbit-live-one-order",
            skip_live_network=True,
        )


def test_execute_live_requires_arm_token() -> None:
    session = MagicMock()
    svc = UpbitLiveSmokeService(session)
    with pytest.raises(UpbitLiveSmokeError, match="ARM_TOKEN"):
        svc.execute(
            user_broker_account_id=7,
            market="KRW-XRP",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=Decimal("500"),
            actor="t",
            arm_token=None,
            execute_live=True,
            confirmation_text=CONFIRMATION_TEXT,
            skip_live_network=True,
        )


def test_execute_live_flag_missing_goes_dry() -> None:
    session = MagicMock()
    svc = UpbitLiveSmokeService(session)
    with patch.object(svc, "dry_run", return_value={"execute_live": False}) as dry:
        out = svc.execute(
            user_broker_account_id=7,
            market="KRW-XRP",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=Decimal("500"),
            actor="t",
            arm_token="tok",
            execute_live=False,
            confirmation_text=CONFIRMATION_TEXT,
        )
    assert out["execute_live"] is False
    dry.assert_called_once()


def test_amount_over_max_rejected_in_constant() -> None:
    assert MAX_SMOKE_AMOUNT == Decimal("10000")
    assert Decimal("10001") > MAX_SMOKE_AMOUNT


def test_amount_over_max_execute_rejects() -> None:
    session = MagicMock()
    with pytest.raises(UpbitLiveSmokeError, match="AMOUNT_EXCEEDS_MAX"):
        UpbitLiveSmokeService(session).execute(
            user_broker_account_id=7,
            market="KRW-XRP",
            side="BUY",
            amount=Decimal("10001"),
            limit_price=Decimal("500"),
            actor="t",
            arm_token="tok",
            execute_live=True,
            confirmation_text=CONFIRMATION_TEXT,
            skip_live_network=True,
        )


def test_dry_run_does_not_call_execution_service() -> None:
    session = MagicMock()
    uba = _uba()
    session.get.return_value = uba
    session.scalar.return_value = None
    session.add = MagicMock()
    session.flush = MagicMock()

    from stock_platform.risk_engine.kill_switch_models import (
        KillSwitchState,
        KillSwitchStatus,
    )

    with (
        patch(
            "stock_platform.trading.upbit_live_preflight_service.KillSwitchService"
        ) as KS,
        patch(
            "stock_platform.trading.upbit_live_preflight_service.LiveArmService"
        ) as ARM,
        patch(
            "stock_platform.trading.upbit_live_preflight_service.ResolvedRiskPolicyResolver"
        ) as R,
        patch(
            "stock_platform.trading.upbit_live_preflight_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.upbit_live_smoke_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.upbit_live_smoke_service.emit_live_order_telegram"
        ),
        patch.object(
            UpbitLivePreflightService,
            "_check_credential",
            return_value=(True, "ok"),
        ),
        patch.object(
            UpbitLivePreflightService,
            "_check_broker_health",
            return_value=(True, "ok"),
        ),
        patch.object(
            UpbitLivePreflightService,
            "_open_order_count",
            return_value=0,
        ),
        patch.object(
            UpbitLivePreflightService,
            "_daily_order_count",
            return_value=0,
        ),
        patch(
            "stock_platform.order.execution_service.OrderExecutionService"
        ) as Exec,
    ):
        KS.return_value.get_state.return_value = KillSwitchState(
            status=KillSwitchStatus.INACTIVE,
            reason=None,
            activated_by=None,
            activated_at=None,
            deactivated_by=None,
            deactivated_at=None,
        )
        ARM.return_value.expire_if_needed.return_value = False
        ARM.return_value.get_arm_status.return_value = {
            "live_armed": True,
            "arm_expires_at": datetime.now(timezone.utc).isoformat(),
        }
        ARM.return_value.validate_arm_token.return_value = (True, "ARM_OK")
        R.return_value.resolve.return_value = _policy()
        result = UpbitLiveSmokeService(session).dry_run(
            user_broker_account_id=7,
            market="KRW-XRP",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=Decimal("500"),
            actor="test",
            skip_live_network=True,
        )
    assert result["execute_live"] is False
    assert "DRY_RUN" in result["message"]
    Exec.assert_not_called()


def test_market_not_in_allowlist_blocks() -> None:
    session = MagicMock()
    result = _run_preflight(session, market="KRW-DOGE")
    assert result.ready is False
    assert any("MARKET_ALLOWLIST" in b for b in result.blockers)


def test_live_off_blocks() -> None:
    session = MagicMock()
    result = _run_preflight(session, uba=_uba(live_order_enabled=False))
    assert result.ready is False
    assert result.live_execution_ready is False
    assert any("LIVE" in b for b in (result.blockers + result.live_blockers))


def test_live_off_expected_for_dry_run() -> None:
    session = MagicMock()
    uba, policy, patches, ks, arm_ok, arm_token_ok = _preflight_ctx(
        uba=_uba(live_order_enabled=False, live_armed=False),
    )
    session.get.return_value = uba
    with patches[0] as KS, patches[1] as ARM, patches[2] as R, patches[3], \
            patches[4], patches[5], patches[6], patches[7]:
        KS.return_value.get_state.return_value = ks
        ARM.return_value.expire_if_needed.return_value = False
        ARM.return_value.get_arm_status.return_value = {
            "live_armed": False,
            "arm_expires_at": None,
        }
        R.return_value.resolve.return_value = policy
        result = UpbitLivePreflightService(session).run(
            user_broker_account_id=7,
            market="KRW-XRP",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=Decimal("500"),
            skip_live_network=True,
            purpose="dry_run",
        )
    assert result.dry_run_ready is True
    assert result.live_execution_ready is False
    assert result.ready is True
    assert any("EXPECTED_OFF" in (c.get("status") or "") for c in result.checks)


def test_kill_switch_blocks() -> None:
    session = MagicMock()
    result = _run_preflight(session, kill_active=True)
    assert result.ready is False
    assert any("KILL" in b for b in result.blockers)


def test_open_orders_block() -> None:
    session = MagicMock()
    result = _run_preflight(
        session,
        open_orders=1,
        policy=_policy(max_open_orders=1),
    )
    assert result.ready is False
    assert any("OPEN_ORDER" in b for b in result.blockers)


def test_broker_health_down_blocks() -> None:
    session = MagicMock()
    result = _run_preflight(session, broker_ok=False)
    assert result.ready is False
    assert any("BROKER" in b for b in result.blockers)


def test_credential_missing_blocks() -> None:
    session = MagicMock()
    result = _run_preflight(session, cred_ok=False)
    assert result.ready is False
    assert any("CREDENTIAL" in b for b in result.blockers)


def test_risk_limit_tighter_than_smoke_max() -> None:
    session = MagicMock()
    result = _run_preflight(
        session,
        amount=Decimal("8000"),
        policy=_policy(max_order_amount=Decimal("6000")),
    )
    assert result.ready is False
    assert any("AMOUNT" in b or "LIMIT" in b for b in result.blockers)


def test_amount_over_10000_preflight() -> None:
    session = MagicMock()
    result = _run_preflight(session, amount=Decimal("15000"))
    assert result.ready is False


def test_slippage_exceeded() -> None:
    session = MagicMock()
    # skip_live_network skips live price — force slippage fail via patch
    uba = _uba()
    session.get.return_value = uba
    from stock_platform.risk_engine.kill_switch_models import (
        KillSwitchState,
        KillSwitchStatus,
    )

    with (
        patch(
            "stock_platform.trading.upbit_live_preflight_service.KillSwitchService"
        ) as KS,
        patch(
            "stock_platform.trading.upbit_live_preflight_service.LiveArmService"
        ) as ARM,
        patch(
            "stock_platform.trading.upbit_live_preflight_service.ResolvedRiskPolicyResolver"
        ) as R,
        patch(
            "stock_platform.trading.upbit_live_preflight_service.emit_live_safety_audit"
        ),
        patch.object(
            UpbitLivePreflightService,
            "_check_credential",
            return_value=(True, "ok"),
        ),
        patch.object(
            UpbitLivePreflightService,
            "_check_broker_health",
            return_value=(True, "ok"),
        ),
        patch.object(
            UpbitLivePreflightService,
            "_open_order_count",
            return_value=0,
        ),
        patch.object(
            UpbitLivePreflightService,
            "_daily_order_count",
            return_value=0,
        ),
        patch.object(
            UpbitLivePreflightService,
            "_fetch_price_book",
            return_value={
                "ref_price": Decimal("100"),
                "ticker_ok": True,
                "book_ok": True,
                "ticker_msg": "ok",
                "book_msg": "ok",
            },
        ),
    ):
        KS.return_value.get_state.return_value = KillSwitchState(
            status=KillSwitchStatus.INACTIVE,
            reason=None,
            activated_by=None,
            activated_at=None,
            deactivated_by=None,
            deactivated_at=None,
        )
        ARM.return_value.expire_if_needed.return_value = False
        ARM.return_value.get_arm_status.return_value = {
            "live_armed": True,
            "arm_expires_at": None,
        }
        R.return_value.resolve.return_value = _policy(
            max_slippage_rate=Decimal("0.01")
        )
        result = UpbitLivePreflightService(session).run(
            user_broker_account_id=7,
            market="KRW-XRP",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=Decimal("200"),  # 100% 위
            skip_live_network=False,
            purpose="live_execution",
        )
    assert result.ready is False
    assert any("SLIPPAGE" in b for b in result.blockers)


def test_preflight_expired() -> None:
    session = MagicMock()
    svc = UpbitLiveSmokeService(session)
    stored = SimpleNamespace(
        preflight_result={
            "ready": True,
            "expires_at": (
                datetime.now(timezone.utc) - timedelta(seconds=5)
            ).isoformat(),
            "requested_amount": "5000",
            "limit_price": "500",
        },
        request_fingerprint="abc",
        user_broker_account_id=7,
        market="KRW-XRP",
        side_code="BUY",
        amount=Decimal("5000"),
        limit_price=Decimal("500"),
    )
    with pytest.raises(UpbitLiveSmokeError, match="PREFLIGHT_EXPIRED"):
        svc._assert_preflight_still_valid(
            stored,  # type: ignore[arg-type]
            user_broker_account_id=7,
            market="KRW-XRP",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=Decimal("500"),
        )


def test_preflight_price_change() -> None:
    session = MagicMock()
    svc = UpbitLiveSmokeService(session)
    stored = SimpleNamespace(
        preflight_result={
            "ready": True,
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(seconds=30)
            ).isoformat(),
            "requested_amount": "5000",
            "limit_price": "500",
        },
        request_fingerprint="abc",
        user_broker_account_id=7,
        market="KRW-XRP",
        side_code="BUY",
        amount=Decimal("5000"),
        limit_price=Decimal("500"),
    )
    with pytest.raises(UpbitLiveSmokeError, match="PREFLIGHT_PARAMS_CHANGED"):
        svc._assert_preflight_still_valid(
            stored,  # type: ignore[arg-type]
            user_broker_account_id=7,
            market="KRW-XRP",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=Decimal("600"),
        )


def test_finally_disarm_and_live_off() -> None:
    session = MagicMock()
    run = SimpleNamespace(
        run_id="r1",
        status_code="ORDER_SUBMITTED",
        internal_status="BROKER_TRACKING",
        broker_order_status="OPEN",
        user_id=1,
        order_id=99,
        execute_live=True,
        detail={},
        completed_at=None,
    )
    with (
        patch(
            "stock_platform.trading.upbit_live_smoke_service.LiveArmService"
        ) as ARM,
        patch(
            "stock_platform.trading.upbit_live_smoke_service.emit_live_order_telegram"
        ),
        patch(
            "stock_platform.trading.upbit_live_smoke_service.emit_live_safety_audit"
        ),
        patch.object(UpbitLiveSmokeService, "_pause_uba_scope"),
        patch.object(UpbitLiveSmokeService, "_transition"),
    ):
        UpbitLiveSmokeService(session)._finalize_protect(
            user_broker_account_id=7,
            run=run,  # type: ignore[arg-type]
            actor="t",
        )
        ARM.return_value.disarm.assert_called_once()
        kwargs = ARM.return_value.disarm.call_args.kwargs
        assert kwargs.get("turn_live_off") is True


def test_audit_detail_excludes_secrets() -> None:
    from stock_platform.order.live_safety_audit import emit_live_safety_audit

    session = MagicMock()
    emit_live_safety_audit(
        session,
        event_type="UPBIT_LIVE_SMOKE_COMPLETED",
        actor="t",
        run_id="r",
        user_id=1,
        account_id=7,
        strategy_id=None,
        detail={
            "arm_token": "SECRET",
            "access_key": "AK",
            "run_id": "r",
        },
        commit=False,
    )
    added = session.add.call_args[0][0]
    detail = added.detail
    assert "arm_token" not in detail
    assert "access_key" not in detail
    assert detail.get("run_id") == "r"


def test_invalid_status_transition() -> None:
    session = MagicMock()
    run = SimpleNamespace(
        status_code="COMPLETED",
        detail={},
        updated_at=None,
    )
    with pytest.raises(UpbitLiveSmokeError, match="INVALID_TRANSITION"):
        UpbitLiveSmokeService(session)._transition(
            run,  # type: ignore[arg-type]
            "CREATED",
            actor="t",
        )


def test_arm_token_invalid_in_preflight() -> None:
    session = MagicMock()
    result = _run_preflight(
        session,
        arm_token="bad",
        uba=_uba(),
    )
    # arm_token 검증은 토큰이 있을 때만 — invalid면 FAIL
    # validate mocked as True in helper — override:
    uba = _uba()
    session.get.return_value = uba
    from stock_platform.risk_engine.kill_switch_models import (
        KillSwitchState,
        KillSwitchStatus,
    )

    with (
        patch(
            "stock_platform.trading.upbit_live_preflight_service.KillSwitchService"
        ) as KS,
        patch(
            "stock_platform.trading.upbit_live_preflight_service.LiveArmService"
        ) as ARM,
        patch(
            "stock_platform.trading.upbit_live_preflight_service.ResolvedRiskPolicyResolver"
        ) as R,
        patch(
            "stock_platform.trading.upbit_live_preflight_service.emit_live_safety_audit"
        ),
        patch.object(
            UpbitLivePreflightService,
            "_check_credential",
            return_value=(True, "ok"),
        ),
        patch.object(
            UpbitLivePreflightService,
            "_check_broker_health",
            return_value=(True, "ok"),
        ),
        patch.object(
            UpbitLivePreflightService,
            "_open_order_count",
            return_value=0,
        ),
        patch.object(
            UpbitLivePreflightService,
            "_daily_order_count",
            return_value=0,
        ),
    ):
        KS.return_value.get_state.return_value = KillSwitchState(
            status=KillSwitchStatus.INACTIVE,
            reason=None,
            activated_by=None,
            activated_at=None,
            deactivated_by=None,
            deactivated_at=None,
        )
        ARM.return_value.expire_if_needed.return_value = False
        ARM.return_value.get_arm_status.return_value = {
            "live_armed": True,
            "arm_expires_at": None,
        }
        ARM.return_value.validate_arm_token.return_value = (
            False,
            "ARM_TOKEN_INVALID",
        )
        R.return_value.resolve.return_value = _policy()
        result = UpbitLivePreflightService(session).run(
            user_broker_account_id=7,
            market="KRW-XRP",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=Decimal("500"),
            arm_token="bad",
            skip_live_network=True,
        )
    assert result.ready is False
    assert any("ARM" in b for b in result.blockers)
