"""STEP 8-8 — LIVE 운영 보호 Operation Rehearsal 체크."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from stock_platform.operations.rehearsal.checks import run_check
from stock_platform.operations.rehearsal.models import (
    CheckResult,
    CheckStatus,
)
from stock_platform.order.live_safety_pipeline import LiveOrderSafetyPipeline
from stock_platform.order.post_fill_verifier import PostFillBalanceVerifier
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicy
from stock_platform.trading.broker_disconnect_protector import (
    BrokerDisconnectProtector,
)
from stock_platform.trading.live_arm_service import LiveArmService


def _policy(**overrides: Any) -> ResolvedRiskPolicy:
    base = dict(
        max_order_amount=Decimal("50000"),
        daily_max_order_amount=Decimal("200000"),
        max_total_investment_amount=Decimal("1000000"),
        max_position_amount=Decimal("200000"),
        max_position_count=5,
        max_position_weight=Decimal("0.2"),
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
        max_slippage_rate=Decimal("0.01"),
        anomaly_orders_per_minute=10,
        loop_detect_window_seconds=60,
        arm_ttl_seconds=300,
        source_layers=("system",),
    )
    base.update(overrides)
    return ResolvedRiskPolicy(**base)


def _uba(*, live: bool = True, armed: bool = False, token_hash: str | None = None, expires=None):
    return SimpleNamespace(
        user_broker_account_id=10,
        user_id=1,
        broker_code="KIWOOM",
        is_active=True,
        live_order_enabled=live,
        live_armed=armed,
        arm_token_hash=token_hash,
        arm_expires_at=expires,
        arm_armed_by="rehearsal",
        arm_armed_at=datetime.now(timezone.utc),
        live_approved_at=None,
        live_approved_by=None,
    )


def run_live_protection_checks() -> list[CheckResult]:
    """실주문 없이 ARM/만료/슬리피지/루프/브로커다운/미스매치 검증."""

    results: list[CheckResult] = []

    def _arm_then_expire() -> tuple[CheckStatus, str, dict[str, Any]]:
        session = MagicMock()
        uba = _uba(live=True)
        session.get.return_value = uba
        with (
            patch(
                "stock_platform.trading.live_arm_service.ResolvedRiskPolicyResolver"
            ) as R,
            patch(
                "stock_platform.trading.live_arm_service.emit_live_safety_audit"
            ),
            patch(
                "stock_platform.trading.live_arm_service.emit_live_order_telegram"
            ),
        ):
            R.return_value.resolve.return_value = _policy()
            armed = LiveArmService(session).arm(10, actor="rehearsal")
            token = armed["arm_token"]
            ok, _ = LiveArmService(session).validate_arm_token(10, token)
            if not ok:
                return CheckStatus.FAIL, "ARM validate failed", armed
            uba.arm_expires_at = datetime.now(timezone.utc) - timedelta(
                seconds=1
            )
            ok2, reason = LiveArmService(session).validate_arm_token(
                10, token
            )
            if ok2 or reason != "LIVE_ARM_EXPIRED":
                return (
                    CheckStatus.FAIL,
                    f"expected LIVE_ARM_EXPIRED got {reason}",
                    {"ok": ok2},
                )
            if uba.live_order_enabled or uba.live_armed:
                return (
                    CheckStatus.FAIL,
                    "expiry did not turn LIVE OFF",
                    {},
                )
        return (
            CheckStatus.PASS,
            "ARM → order window → expire → LIVE OFF",
            {"arm_ok": True, "expired": True},
        )

    results.append(
        run_check(
            suite="live_protection",
            name="arm_expire_rejects",
            fn=_arm_then_expire,
        )
    )

    def _slippage() -> tuple[CheckStatus, str, dict[str, Any]]:
        session = MagicMock()
        session.get.return_value = _uba(live=True)
        session.scalar.side_effect = [0, None, None, 0, 0]
        session.scalars.return_value = []
        with (
            patch(
                "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
            ) as R,
            patch(
                "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
            ) as KS,
            patch(
                "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
            ),
            patch(
                "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency"
            ) as F,
        ):
            KS.return_value.require_order_allowed.return_value = None
            R.return_value.resolve.return_value = _policy()
            F.return_value = SimpleNamespace(code="LIVE_SAFE_DEFAULTS")
            d = LiveOrderSafetyPipeline(session).evaluate(
                user_id=1,
                user_broker_account_id=10,
                broker_code="KIWOOM",
                exchange_code="KRX",
                symbol="005930",
                side="BUY",
                quantity=Decimal("1"),
                price=Decimal("10350"),
                reference_price=Decimal("10000"),
                emit_side_effects=False,
                require_arm=False,
                skip_market_hours=True,
            )
        if d.allowed or d.reason_code != "SLIPPAGE_EXCEEDED":
            return (
                CheckStatus.FAIL,
                f"slippage not rejected: {d.reason_code}",
                {},
            )
        return CheckStatus.PASS, "slippage reject ok", {"reason": d.reason_code}

    results.append(
        run_check(suite="live_protection", name="slippage_reject", fn=_slippage)
    )

    def _loop() -> tuple[CheckStatus, str, dict[str, Any]]:
        session = MagicMock()
        session.get.return_value = _uba(live=True)
        # daily, loss, dup, open, per_min — then loop sides via scalars
        session.scalar.side_effect = [0, None, None, 0, 0]
        # BUY SELL BUY SELL pattern
        session.scalars.return_value = [
            SimpleNamespace(side_code="SELL"),
            SimpleNamespace(side_code="BUY"),
            SimpleNamespace(side_code="SELL"),
        ]
        with (
            patch(
                "stock_platform.order.live_safety_pipeline.ResolvedRiskPolicyResolver"
            ) as R,
            patch(
                "stock_platform.order.live_safety_pipeline.PersistentKillSwitchGuard"
            ) as KS,
            patch(
                "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
            ),
            patch(
                "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency"
            ) as F,
        ):
            KS.return_value.require_order_allowed.return_value = None
            R.return_value.resolve.return_value = _policy()
            F.return_value = SimpleNamespace(code="LIVE_SAFE_DEFAULTS")
            d = LiveOrderSafetyPipeline(session).evaluate(
                user_id=1,
                user_broker_account_id=10,
                broker_code="KIWOOM",
                exchange_code="KRX",
                symbol="005930",
                side="BUY",
                quantity=Decimal("1"),
                price=Decimal("10000"),
                reference_price=Decimal("10000"),
                emit_side_effects=False,
                require_arm=False,
                skip_market_hours=True,
            )
        if d.allowed or "LOOP" not in str(d.reason_code):
            return (
                CheckStatus.FAIL,
                f"loop not rejected: {d.reason_code}",
                {},
            )
        return CheckStatus.PASS, "loop detect ok", {"reason": d.reason_code}

    results.append(
        run_check(suite="live_protection", name="loop_detect", fn=_loop)
    )

    def _broker_down() -> tuple[CheckStatus, str, dict[str, Any]]:
        session = MagicMock()
        uba = _uba(live=True, armed=True)
        session.scalars.return_value = [uba]
        with (
            patch(
                "stock_platform.trading.broker_disconnect_protector.LiveArmService"
            ) as ARM,
            patch(
                "stock_platform.trading.broker_disconnect_protector.emit_live_safety_audit"
            ),
            patch(
                "stock_platform.trading.broker_disconnect_protector.emit_live_order_telegram"
            ),
        ):
            ARM.return_value.disarm.return_value = {"live_armed": False}
            payload = BrokerDisconnectProtector(session).on_broker_down(
                broker_code="KIWOOM",
                actor="rehearsal",
            )
            recovered = BrokerDisconnectProtector(session).on_broker_up(
                broker_code="KIWOOM",
                actor="rehearsal",
            )
        if recovered.get("auto_live_on") is not False:
            return CheckStatus.FAIL, "auto LIVE ON not forbidden", recovered
        if recovered.get("requires_admin_arm") is not True:
            return CheckStatus.FAIL, "admin ARM not required", recovered
        return (
            CheckStatus.PASS,
            "broker down → LIVE OFF; recover needs ARM",
            {"down": payload, "up": recovered},
        )

    results.append(
        run_check(
            suite="live_protection",
            name="broker_disconnect",
            fn=_broker_down,
        )
    )

    def _position_mismatch() -> tuple[CheckStatus, str, dict[str, Any]]:
        session = MagicMock()
        with (
            patch(
                "stock_platform.risk_engine.kill_switch_service.KillSwitchService"
            ) as KS,
            patch(
                "stock_platform.trading.live_arm_service.LiveArmService"
            ) as ARM,
            patch(
                "stock_platform.order.post_fill_verifier.emit_live_safety_audit"
            ),
            patch(
                "stock_platform.order.post_fill_verifier.emit_live_order_telegram"
            ),
        ):
            KS.return_value.activate.return_value = None
            ARM.return_value.disarm.return_value = {}
            result = PostFillBalanceVerifier(session).verify(
                user_broker_account_id=10,
                user_id=1,
                broker_code="KIWOOM",
                broker_positions=[{"symbol": "005930", "quantity": "10"}],
                broker_cash=None,
                db_positions=[{"symbol": "005930", "quantity": "9"}],
                db_cash=None,
            )
        if result.ok or result.reason_code != "POSITION_MISMATCH":
            return CheckStatus.FAIL, "mismatch did not kill", {}
        if not KS.return_value.activate.called:
            return CheckStatus.FAIL, "kill switch not activated", {}
        return (
            CheckStatus.PASS,
            "position mismatch → Kill Switch",
            {"reason": result.reason_code},
        )

    results.append(
        run_check(
            suite="live_protection",
            name="position_mismatch_kill",
            fn=_position_mismatch,
        )
    )

    def _modules() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.trading.live_ops_dashboard import (
            LiveOpsDashboardService,
        )

        assert LiveArmService is not None
        assert LiveOpsDashboardService is not None
        return (
            CheckStatus.PASS,
            "live protection modules importable",
            {
                "arm": True,
                "dashboard": True,
                "pipeline": True,
                "post_fill": True,
            },
        )

    results.append(
        run_check(
            suite="live_protection",
            name="modules_available",
            fn=_modules,
        )
    )

    # --- STEP 8-8A post_fill ---
    def _pf_pending_retry() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.order.post_fill_verification_constants import (
            PostFillVerifyStatus,
        )
        from stock_platform.order.post_fill_verification_service import (
            PostFillVerificationService,
        )

        session = MagicMock()
        row = SimpleNamespace(
            verification_id=1,
            order_id=1,
            execution_id=1,
            user_id=1,
            user_broker_account_id=1,
            broker_code="KIWOOM",
            symbol="005930",
            status_code="PENDING",
            retry_count=0,
            max_attempts=5,
            next_retry_at=None,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
            last_error_code=None,
            last_error_summary=None,
            detail={},
            run_id="r",
            correlation_id="c",
            claimed_by=None,
            claim_expires_at=None,
            broker_down_notified=False,
            verified_at=None,
            updated_at=None,
            expected_position=[],
            expected_cash_delta=None,
        )
        svc = PostFillVerificationService(session)
        with (
            patch.object(svc, "_audit"),
            patch.object(svc, "_try_sync_best_effort"),
            patch.object(
                svc,
                "_next_retry_at",
                return_value=datetime.now(timezone.utc)
                + timedelta(seconds=2),
            ),
        ):
            svc.handle_immediate_result(
                row=row, reason_code="SNAPSHOT_STALE", actor="rehearsal"
            )
        if row.status_code != PostFillVerifyStatus.WAITING_SNAPSHOT.value:
            return CheckStatus.FAIL, "stale not WAITING_SNAPSHOT", {}
        return (
            CheckStatus.PASS,
            "stale → WAITING_SNAPSHOT",
            {"status": row.status_code},
        )

    results.append(
        run_check(
            suite="live_protection",
            name="post_fill.pending_retry",
            fn=_pf_pending_retry,
        )
    )

    def _pf_verified_after_sync() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.order.post_fill_verification_constants import (
            PostFillVerifyStatus,
        )
        from stock_platform.order.post_fill_verification_service import (
            PostFillVerificationService,
        )

        session = MagicMock()
        row = SimpleNamespace(
            verification_id=1,
            order_id=1,
            execution_id=1,
            user_id=1,
            user_broker_account_id=1,
            broker_code="KIWOOM",
            symbol="005930",
            status_code="WAITING_SNAPSHOT",
            retry_count=1,
            max_attempts=5,
            next_retry_at=None,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
            last_error_code=None,
            last_error_summary=None,
            detail={},
            run_id="r",
            correlation_id="c",
            claimed_by=None,
            claim_expires_at=None,
            broker_down_notified=False,
            verified_at=None,
            updated_at=None,
            expected_position=[{"symbol": "005930", "quantity": "1"}],
            expected_cash_delta=None,
        )
        svc = PostFillVerificationService(session)
        with (
            patch.object(svc, "_audit"),
            patch(
                "stock_platform.order.post_fill_verification_service.emit_live_order_telegram"
            ),
        ):
            svc._mark_verified(row, actor="rehearsal", detail={})
        if row.status_code != PostFillVerifyStatus.VERIFIED.value:
            return CheckStatus.FAIL, "not verified", {}
        return CheckStatus.PASS, "verified after sync", {}

    results.append(
        run_check(
            suite="live_protection",
            name="post_fill.verified_after_sync",
            fn=_pf_verified_after_sync,
        )
    )

    def _pf_mismatch_kill() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.order.post_fill_verification_constants import (
            PostFillVerifyStatus,
        )
        from stock_platform.order.post_fill_verification_service import (
            PostFillVerificationService,
        )

        session = MagicMock()
        row = SimpleNamespace(
            verification_id=1,
            order_id=1,
            execution_id=1,
            user_id=1,
            user_broker_account_id=1,
            broker_code="KIWOOM",
            symbol="005930",
            status_code="VERIFYING",
            retry_count=1,
            max_attempts=5,
            next_retry_at=None,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
            last_error_code=None,
            last_error_summary=None,
            detail={},
            run_id="r",
            correlation_id="c",
            claimed_by="w",
            claim_expires_at=None,
            broker_down_notified=False,
            verified_at=None,
            updated_at=None,
            expected_position=[],
            expected_cash_delta=None,
        )
        svc = PostFillVerificationService(session)
        with (
            patch.object(svc, "_audit"),
            patch(
                "stock_platform.order.post_fill_verification_service.emit_live_order_telegram"
            ),
            patch.object(svc, "_fail_closed_kill") as kill,
        ):
            svc._mark_mismatch(
                row, actor="rehearsal", reason="POSITION_MISMATCH"
            )
        if row.status_code != PostFillVerifyStatus.MISMATCH.value:
            return CheckStatus.FAIL, "not mismatch", {}
        if not kill.called:
            return CheckStatus.FAIL, "kill not called", {}
        return CheckStatus.PASS, "mismatch → kill", {}

    results.append(
        run_check(
            suite="live_protection",
            name="post_fill.mismatch_kill_switch",
            fn=_pf_mismatch_kill,
        )
    )

    def _pf_expired() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.order.post_fill_verification_constants import (
            PostFillVerifyStatus,
        )
        from stock_platform.order.post_fill_verification_service import (
            PostFillVerificationService,
        )

        session = MagicMock()
        row = SimpleNamespace(
            verification_id=1,
            order_id=1,
            execution_id=1,
            user_id=1,
            user_broker_account_id=1,
            broker_code="KIWOOM",
            symbol="005930",
            status_code="WAITING_SNAPSHOT",
            retry_count=5,
            max_attempts=5,
            next_retry_at=None,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            last_error_code=None,
            last_error_summary=None,
            detail={},
            run_id="r",
            correlation_id="c",
            claimed_by=None,
            claim_expires_at=None,
            broker_down_notified=False,
            verified_at=None,
            updated_at=None,
            expected_position=[],
            expected_cash_delta=None,
        )
        svc = PostFillVerificationService(session)
        with (
            patch.object(svc, "_audit"),
            patch(
                "stock_platform.order.post_fill_verification_service.emit_live_order_telegram"
            ),
            patch.object(svc, "_fail_closed_kill") as kill,
        ):
            svc._mark_expired(row, actor="rehearsal")
        if row.status_code != PostFillVerifyStatus.EXPIRED.value:
            return CheckStatus.FAIL, "not expired", {}
        if not kill.called:
            return CheckStatus.FAIL, "kill not called", {}
        return CheckStatus.PASS, "expired fail-closed", {}

    results.append(
        run_check(
            suite="live_protection",
            name="post_fill.expired_fail_closed",
            fn=_pf_expired,
        )
    )

    def _pf_idempotency() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.order.post_fill_verification_service import (
            make_idempotency_key,
        )

        a = make_idempotency_key(order_id=9, execution_id=3)
        b = make_idempotency_key(order_id=9, execution_id=3)
        if a != b:
            return CheckStatus.FAIL, "key unstable", {}
        return CheckStatus.PASS, "idempotency key stable", {"key": a}

    results.append(
        run_check(
            suite="live_protection",
            name="post_fill.idempotency",
            fn=_pf_idempotency,
        )
    )

    def _pf_restart_recovery() -> tuple[CheckStatus, str, dict[str, Any]]:
        # DB row가 Source of Truth — PENDING/WAITING은 재시작 후 due 조회 가능
        from stock_platform.order.post_fill_verification_constants import (
            ACTIVE_STATUSES,
        )
        from stock_platform.order.post_fill_verification_entities import (
            PostFillVerificationEntity,
        )

        assert "WAITING_SNAPSHOT" in ACTIVE_STATUSES
        assert PostFillVerificationEntity.__tablename__ == (
            "post_fill_verification"
        )
        return (
            CheckStatus.PASS,
            "pending rows recoverable after restart",
            {"active_statuses": sorted(ACTIVE_STATUSES)},
        )

    results.append(
        run_check(
            suite="live_protection",
            name="post_fill.restart_recovery",
            fn=_pf_restart_recovery,
        )
    )

    def _arm_token_masking() -> tuple[CheckStatus, str, dict[str, Any]]:
        session = MagicMock()
        uba = _uba(live=True)
        session.get.return_value = uba
        with (
            patch(
                "stock_platform.trading.live_arm_service.ResolvedRiskPolicyResolver"
            ) as R,
            patch(
                "stock_platform.trading.live_arm_service.emit_live_safety_audit"
            ) as audit,
            patch(
                "stock_platform.trading.live_arm_service.emit_live_order_telegram"
            ),
        ):
            R.return_value.resolve.return_value = _policy()
            armed = LiveArmService(session).arm(10, actor="rehearsal")
            token = armed["arm_token"]
            status = LiveArmService(session).get_arm_status(10)
        if "arm_token" in status:
            return CheckStatus.FAIL, "GET returns arm_token", status
        for call in audit.call_args_list:
            detail = call.kwargs.get("detail") or {}
            if token in str(detail):
                return CheckStatus.FAIL, "token leaked to audit", detail
        return (
            CheckStatus.PASS,
            "arm_token masked in status/audit",
            {"arm_token_present": status.get("arm_token_present")},
        )

    results.append(
        run_check(
            suite="live_protection",
            name="arm_token.secret_masking",
            fn=_arm_token_masking,
        )
    )
    return results
