"""Post-fill kill UBA scope isolation + WAITING_SNAPSHOT TTL defer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.post_fill_verification_constants import (
    POSITION_SYNC_PENDING,
    PostFillVerifyStatus,
)
from stock_platform.order.post_fill_verification_service import (
    PostFillVerificationService,
)
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.trading.account_identity import uba_kill_switch_scope


def _row(
    *,
    uba_id: int = 1380,
    broker: str = "UPBIT",
    retry_count: int = 0,
    max_attempts: int = 5,
    expires_in: int = 60,
    status: str = PostFillVerifyStatus.WAITING_SNAPSHOT.value,
    detail: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        verification_id=973,
        order_id=2435,
        execution_id=None,
        user_id=61,
        user_broker_account_id=uba_id,
        broker_code=broker,
        symbol="KRW-SUI",
        status_code=status,
        retry_count=retry_count,
        max_attempts=max_attempts,
        next_retry_at=None,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        last_error_code=POSITION_SYNC_PENDING,
        last_error_summary=None,
        detail=detail
        or {
            "deferred_kill": True,
            "sync_pending": True,
            "broker_qty": "0E-8",
            "db_qty": "10.03",
        },
        run_id="pfv-test",
        correlation_id="corr-test",
        claimed_by="w1",
        claim_expires_at=None,
        broker_down_notified=False,
        verified_at=None,
        updated_at=None,
        expected_position=[{"symbol": "KRW-SUI", "quantity": "10.03"}],
        expected_cash_delta=None,
    )


def test_fail_closed_kill_uses_uba_scope_not_global() -> None:
    session = MagicMock()
    row = _row(uba_id=1380)
    svc = PostFillVerificationService(session)
    ks = MagicMock()
    with (
        patch(
            "stock_platform.risk_engine.kill_switch_service.KillSwitchService",
            return_value=ks,
        ),
        patch(
            "stock_platform.trading.live_arm_service.LiveArmService"
        ) as arm_cls,
        patch(
            "stock_platform.strategy_deployment.runtime_manager.dynamic_strategy_runtime_manager"
        ) as runtime,
    ):
        arm = MagicMock()
        arm_cls.return_value = arm
        runtime.pause_account_runtimes = MagicMock(return_value=[])
        # asyncio.run path
        svc._fail_closed_kill(row, actor="TEST", reason="TTL_EXPIRED")

    ks.activate_scope.assert_called_once()
    call_kw = ks.activate_scope.call_args.kwargs
    assert call_kw["scope_code"] == uba_kill_switch_scope(1380)
    assert "POST_FILL_TTL_EXPIRED" in call_kw["reason"]
    ks.activate.assert_not_called()
    arm.disarm.assert_called_once()
    assert arm.disarm.call_args.args[0] == 1380


def test_uba_scope_isolation_codes_differ() -> None:
    assert uba_kill_switch_scope(1380) != uba_kill_switch_scope(1381)
    assert uba_kill_switch_scope(1380) == "UBA:1380"
    assert KillSwitchService.GLOBAL_SCOPE == "GLOBAL"


def test_waiting_snapshot_ttl_deferred_no_immediate_kill() -> None:
    session = MagicMock()
    row = _row(expires_in=-1)  # already expired
    order = SimpleNamespace(
        order_id=2435,
        status_code="FILLED",
        broker_order_id="b48e9d0c-ee44-40fa-98ef-8434b558c2a4",
    )
    session.get = MagicMock(return_value=order)
    svc = PostFillVerificationService(session)
    with (
        patch.object(svc, "_audit"),
        patch.object(
            svc,
            "_next_retry_at",
            return_value=datetime.now(timezone.utc) + timedelta(seconds=2),
        ),
        patch.object(svc, "_mark_expired") as expired_mock,
        patch(
            "stock_platform.order.post_fill_verification_service.get_settings"
        ) as gs,
    ):
        gs.return_value = SimpleNamespace(
            post_fill_verify_max_snapshot_defers=3,
            post_fill_verify_snapshot_defer_seconds=120,
            post_fill_verify_retry_delays_seconds="2,5,10,20",
        )
        deferred = svc._try_defer_waiting_snapshot_ttl(row, actor="TEST")
    assert deferred is True
    assert row.detail["snapshot_defer_count"] == 1
    assert row.status_code == PostFillVerifyStatus.WAITING_SNAPSHOT.value
    expired_mock.assert_not_called()


def test_waiting_snapshot_defer_exhausted_returns_false() -> None:
    session = MagicMock()
    row = _row(
        expires_in=-1,
        detail={
            "deferred_kill": True,
            "sync_pending": True,
            "snapshot_defer_count": 3,
            "broker_qty": "0",
            "db_qty": "10",
        },
    )
    svc = PostFillVerificationService(session)
    with patch(
        "stock_platform.order.post_fill_verification_service.get_settings"
    ) as gs:
        gs.return_value = SimpleNamespace(
            post_fill_verify_max_snapshot_defers=3,
            post_fill_verify_snapshot_defer_seconds=120,
        )
        assert svc._try_defer_waiting_snapshot_ttl(row, actor="TEST") is False


def test_contradictory_qty_blocks_defer() -> None:
    session = MagicMock()
    svc = PostFillVerificationService(session)
    assert (
        svc._has_contradictory_position_evidence(
            {"broker_qty": "5", "db_qty": "10"}
        )
        is True
    )
    assert (
        svc._has_contradictory_position_evidence(
            {"broker_qty": "0", "db_qty": "10"}
        )
        is False
    )


def test_process_claimed_defers_before_expire_kill() -> None:
    session = MagicMock()
    row = _row(expires_in=-1)
    order = SimpleNamespace(
        order_id=2435,
        status_code="FILLED",
        broker_order_id="uuid-1",
    )
    session.get = MagicMock(return_value=order)
    svc = PostFillVerificationService(session)
    with (
        patch.object(svc, "_audit"),
        patch.object(
            svc,
            "_next_retry_at",
            return_value=datetime.now(timezone.utc) + timedelta(seconds=2),
        ),
        patch.object(svc, "_mark_expired") as expired_mock,
        patch.object(
            svc,
            "_reverify",
            return_value={"status": "WAITING_SNAPSHOT"},
        ) as reverify,
        patch(
            "stock_platform.order.post_fill_verification_service.sync_broker_snapshot_for_uba"
        ),
        patch(
            "stock_platform.order.post_fill_verification_service.get_settings"
        ) as gs,
    ):
        gs.return_value = SimpleNamespace(
            post_fill_verify_max_snapshot_defers=3,
            post_fill_verify_snapshot_defer_seconds=120,
            post_fill_verify_retry_delays_seconds="2,5,10,20",
            post_fill_verify_max_attempts=5,
        )
        out = svc.process_claimed(row)
    expired_mock.assert_not_called()
    reverify.assert_called_once()
    assert out["status"] == "WAITING_SNAPSHOT"


def test_paper_telegram_prefix_not_kiwoom() -> None:
    from stock_platform.notification.telegram_policy import (
        ensure_market_title_prefix,
        resolve_telegram_market,
    )

    market = resolve_telegram_market(
        event_type="KILL_SWITCH",
        detail={"broker_code": "PAPER", "account_id": 5153},
    )
    assert str(market) == "PAPER"
    title = ensure_market_title_prefix("Kill Switch 작동", market=market)
    assert title.startswith("[모의]")
    assert "[키움]" not in title


def test_upbit_kiwoom_prefixes_correct() -> None:
    from stock_platform.notification.telegram_policy import (
        ensure_market_title_prefix,
        resolve_telegram_market,
    )

    up = resolve_telegram_market(
        event_type="ORDER_FILLED", detail={"broker_code": "UPBIT"}
    )
    kw = resolve_telegram_market(
        event_type="ORDER_FILLED", detail={"broker_code": "KIWOOM"}
    )
    assert ensure_market_title_prefix("체결", market=up).startswith("[업비트]")
    assert ensure_market_title_prefix("체결", market=kw).startswith("[키움]")
