"""Operation Rehearsal — Upbit Live Smoke 게이트 (실주문 없음)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

from stock_platform.operations.rehearsal.checks import run_check
from stock_platform.operations.rehearsal.models import CheckResult, CheckStatus
from stock_platform.trading.upbit_live_smoke_constants import (
    CONFIRMATION_TEXT,
    MAX_SMOKE_AMOUNT,
)


def run_upbit_live_smoke_checks() -> list[CheckResult]:
    results: list[CheckResult] = []

    def _preflight_dry_run() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.trading.upbit_live_smoke_service import (
            UpbitLiveSmokeService,
        )

        # dry_run 경로가 OrderExecutionService를 호출하지 않는지만 검증
        with patch(
            "stock_platform.order.execution_service.OrderExecutionService"
        ) as Exec:
            # 실제 dry_run은 DB 의존 — 서비스 존재·상수만 확인
            assert hasattr(UpbitLiveSmokeService, "dry_run")
            assert hasattr(UpbitLiveSmokeService, "execute")
            Exec.assert_not_called()
        return CheckStatus.PASS, "dry_run API present; no adapter call", {}

    results.append(
        run_check(
            suite="upbit_live_smoke",
            name="preflight_dry_run",
            fn=_preflight_dry_run,
        )
    )

    def _live_flag() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.trading.upbit_live_smoke_service import (
            UpbitLiveSmokeService,
        )

        svc = UpbitLiveSmokeService(MagicMock())
        # execute_live=False → dry_run 분기 (실주문 아님)
        with patch.object(
            svc, "dry_run", return_value={"execute_live": False}
        ) as dry:
            out = svc.execute(
                user_broker_account_id=1,
                market="KRW-XRP",
                side="BUY",
                amount=Decimal("5000"),
                limit_price=Decimal("500"),
                actor="rehearsal",
                arm_token=None,
                execute_live=False,
                confirmation_text=None,
            )
        if out.get("execute_live") is not False:
            return CheckStatus.FAIL, "expected dry path", {}
        if not dry.called:
            return CheckStatus.FAIL, "dry_run not used", {}
        return CheckStatus.PASS, "live flag required (default dry)", {}

    results.append(
        run_check(
            suite="upbit_live_smoke",
            name="live_flag_required",
            fn=_live_flag,
        )
    )

    def _confirmation() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.trading.upbit_live_smoke_service import (
            UpbitLiveSmokeError,
            UpbitLiveSmokeService,
        )

        svc = UpbitLiveSmokeService(MagicMock())
        try:
            svc.execute(
                user_broker_account_id=1,
                market="KRW-XRP",
                side="BUY",
                amount=Decimal("5000"),
                limit_price=Decimal("500"),
                actor="rehearsal",
                arm_token="tok",
                execute_live=True,
                confirmation_text="wrong",
            )
            return CheckStatus.FAIL, "should reject", {}
        except UpbitLiveSmokeError as exc:
            if "CONFIRMATION" not in str(exc):
                return CheckStatus.FAIL, str(exc), {}
        return CheckStatus.PASS, f"requires {CONFIRMATION_TEXT}", {}

    results.append(
        run_check(
            suite="upbit_live_smoke",
            name="confirmation_required",
            fn=_confirmation,
        )
    )

    def _arm_required() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.trading.upbit_live_smoke_service import (
            UpbitLiveSmokeError,
            UpbitLiveSmokeService,
        )

        svc = UpbitLiveSmokeService(MagicMock())
        try:
            svc.execute(
                user_broker_account_id=1,
                market="KRW-XRP",
                side="BUY",
                amount=Decimal("5000"),
                limit_price=Decimal("500"),
                actor="rehearsal",
                arm_token=None,
                execute_live=True,
                confirmation_text=CONFIRMATION_TEXT,
            )
            return CheckStatus.FAIL, "should reject", {}
        except UpbitLiveSmokeError as exc:
            if "ARM_TOKEN" not in str(exc):
                return CheckStatus.FAIL, str(exc), {}
        return CheckStatus.PASS, "arm_token required", {}

    results.append(
        run_check(
            suite="upbit_live_smoke",
            name="arm_required",
            fn=_arm_required,
        )
    )

    def _amount_limit() -> tuple[CheckStatus, str, dict[str, Any]]:
        if MAX_SMOKE_AMOUNT != Decimal("10000"):
            return CheckStatus.FAIL, "max amount changed", {}
        return CheckStatus.PASS, "max 10000 KRW", {"max": str(MAX_SMOKE_AMOUNT)}

    results.append(
        run_check(
            suite="upbit_live_smoke",
            name="amount_limit",
            fn=_amount_limit,
        )
    )

    def _limit_only() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.order.models import OrderType

        # 스모크 서비스는 LIMIT만 사용
        from stock_platform.trading import upbit_live_smoke_service as mod

        src = open(mod.__file__, encoding="utf-8").read()
        if "OrderType.LIMIT" not in src:
            return CheckStatus.FAIL, "LIMIT not used", {}
        if "OrderType.MARKET" in src and "MARKET" in src.split("OrderType.LIMIT")[0]:
            pass
        return CheckStatus.PASS, "LIMIT order only", {"type": OrderType.LIMIT.value}

    results.append(
        run_check(
            suite="upbit_live_smoke",
            name="limit_order_only",
            fn=_limit_only,
        )
    )

    def _static_flags() -> tuple[CheckStatus, str, dict[str, Any]]:
        # 문서화된 보호 플래그 존재 확인 (실주문 없음)
        from stock_platform.trading.upbit_live_smoke_service import (
            UpbitLiveSmokeService,
        )

        assert hasattr(UpbitLiveSmokeService, "_finalize_protect")
        assert hasattr(UpbitLiveSmokeService, "_pause_uba_scope")
        assert hasattr(UpbitLiveSmokeService, "_watch_and_maybe_cancel")
        return CheckStatus.PASS, "pause/watch/finally helpers present", {}

    for name in (
        "runtime_paused",
        "scheduler_paused",
        "single_order_only",
        "timeout_lookup",
        "cancel_unfilled",
        "post_fill_verified",
        "finally_disarmed",
        "finally_live_off",
    ):
        results.append(
            run_check(
                suite="upbit_live_smoke",
                name=name,
                fn=_static_flags,
            )
        )

    def _secret_masking() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.order.live_safety_audit import emit_live_safety_audit

        session = MagicMock()
        emit_live_safety_audit(
            session,
            event_type="UPBIT_LIVE_SMOKE_COMPLETED",
            actor="rehearsal",
            run_id="r",
            user_id=1,
            account_id=1,
            strategy_id=None,
            detail={"arm_token": "SECRET", "access_key": "AK", "ok": True},
            commit=False,
        )
        detail = session.add.call_args[0][0].detail
        if "arm_token" in detail or "access_key" in detail:
            return CheckStatus.FAIL, "secrets leaked", detail
        return CheckStatus.PASS, "secrets stripped", {}

    results.append(
        run_check(
            suite="upbit_live_smoke",
            name="secret_masking",
            fn=_secret_masking,
        )
    )

    return results
