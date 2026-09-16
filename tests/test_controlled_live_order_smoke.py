"""UBA-scoped Pre-flight + Controlled Live Order Smoke (주문 API 0)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.operation.runtime_preflight_service import (
    PREFLIGHT_TTL_SECONDS,
    RuntimePreflightService,
    evaluate_preflight_freshness,
)
from stock_platform.trading.controlled_live_order_smoke_service import (
    ControlledLiveOrderSmokeError,
    ControlledLiveOrderSmokeService,
)
from stock_platform.trading.upbit_live_smoke_constants import (
    confirmation_text_for_side,
)


def _uba(
    *,
    uba_id: int = 1380,
    user_id: int = 1,
    broker: str = "UPBIT",
    live: bool = False,
    arm: bool = False,
    conn: str = "CONNECTED",
):
    return SimpleNamespace(
        user_broker_account_id=uba_id,
        user_id=user_id,
        broker_code=broker,
        is_active=True,
        deleted_at=None,
        live_order_enabled=live,
        live_armed=arm,
        connection_status=conn,
        masked_account_number="****1234",
        last_synced_at=datetime.now(timezone.utc),
        arm_expires_at=None,
    )


def test_confirmation_texts() -> None:
    assert confirmation_text_for_side("BUY") == "UPBIT LIVE BUY CONFIRM"
    assert confirmation_text_for_side("SELL") == "UPBIT LIVE SELL CONFIRM"


def test_uba_preflight_fail_closed_non_upbit() -> None:
    session = MagicMock()
    session.get.return_value = _uba(broker="KIWOOM")
    out = RuntimePreflightService(session).run_for_uba(
        user_broker_account_id=99, mode="LIVE_ON", owner_user_id=1
    )
    assert out["overall_status"] == "BLOCKED"
    assert out["user_broker_account_id"] == 99
    assert out["live_on_allowed"] is False


def test_uba_preflight_idor() -> None:
    session = MagicMock()
    session.get.return_value = _uba(user_id=7)
    out = RuntimePreflightService(session).run_for_uba(
        user_broker_account_id=1380, mode="LIVE_ON", owner_user_id=1
    )
    assert out["overall_status"] == "BLOCKED"
    assert any(b["code"] == "OWNERSHIP" for b in out["blockers"])


def test_other_account_failure_does_not_block_uba() -> None:
    """전역 Kiwoom 장애와 무관 — UBA 스코프만 검사."""
    session = MagicMock()
    uba = _uba()
    session.get.return_value = uba

    # recovery / conflict / risk scalar 경로
    session.scalar.side_effect = [
        None,  # recovery
        0,  # conflicts
        SimpleNamespace(account_paused=False),  # risk
        1,  # strategy links
    ]

    class FakeVault:
        def __init__(self, *_a, **_k):
            pass

        def status(self, _id: int):
            return SimpleNamespace(verification_status="VERIFIED")

    class FakeKill:
        def __init__(self, *_a, **_k):
            pass

        def is_active(self):
            return False

    with (
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService",
            FakeVault,
        ),
        patch(
            "stock_platform.risk_engine.kill_switch_service.KillSwitchService",
            FakeKill,
        ),
        patch(
            "stock_platform.operation.runtime_preflight_service._check_database",
            return_value={
                "code": "DATABASE",
                "name": "Database",
                "status": "PASS",
                "blocking": False,
                "message": "ok",
                "detail": {},
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "remediation": None,
            },
        ),
        patch(
            "stock_platform.trading.upbit_scheduler_readiness.collect_scheduler_readiness",
            return_value=SimpleNamespace(
                trading_scheduler_desired_state="PAUSE",
                trading_scheduler_actual_state="PAUSE",
            ),
        ),
        patch(
            "stock_platform.realtime.runtime.realtime_strategy_runner.status",
            return_value={"active_scopes": 0},
        ),
    ):
        # link count via scalar after risk — simplify: patch strategy block
        session.scalar.side_effect = [
            None,
            0,
            SimpleNamespace(account_paused=False),
            1,
        ]
        out = RuntimePreflightService(session).run_for_uba(
            user_broker_account_id=1380, mode="LIVE_ON", owner_user_id=1
        )

    assert out["broker_code"] == "UPBIT"
    assert out["scope"] == "UBA"
    assert "checks" in out
    # 타 계좌 상태가 없으므로 전역 FAIL 주입 없음
    assert out["user_broker_account_id"] == 1380


def test_stale_blocks_freshness() -> None:
    now = datetime(2026, 8, 3, 15, 0, tzinfo=timezone.utc)
    checked = (now - timedelta(seconds=PREFLIGHT_TTL_SECONDS + 5)).isoformat()
    fr = evaluate_preflight_freshness(checked, now=now)
    assert fr["fresh"] is False


def test_preview_never_calls_adapter() -> None:
    session = MagicMock()
    session.get.return_value = _uba()
    svc = ControlledLiveOrderSmokeService(session)

    with (
        patch.object(
            RuntimePreflightService,
            "run_for_uba",
            return_value={
                "overall_status": "READY_FOR_LIVE",
                "live_on_allowed": True,
                "manual_order_allowed": False,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "checks": [],
                "blockers": [],
                "warnings": [],
            },
        ),
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.UpbitLivePreflightService.run",
            return_value=SimpleNamespace(
                to_dict=lambda: {"ready": True},
                live_execution_ready=False,
            ),
        ),
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.emit_live_safety_audit"
        ),
    ):
        out = svc.preview(
            uba_id=1380,
            user_id=1,
            actor="tester",
            market="KRW-BTC",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=None,
            order_type="MARKET",
            reference_price=Decimal("100000000"),
        )
    assert out["adapter_create_order_calls"] == 0
    assert out["broker_order_id"] is None
    assert out["stage"] in {"PRE_SUBMIT_READY", "PREFLIGHT_BLOCKED", "PREFLIGHT_STALE"}
    # 5000 / 100_000_000 = 0.00005 (현재가 기준, 가격=금액 혼동 없음)
    assert Decimal(out["quantity"]) == Decimal("0.00005")
    assert out["upbit_ord_type"] == "price"
    assert out["broker_body"]["price"] == "5000"
    assert "volume" not in out["broker_body"]


def test_preview_qty_matches_upbit_four_paths() -> None:
    from stock_platform.trading.controlled_live_order_smoke_service import (
        compute_upbit_order_preview,
    )

    ref = Decimal("100000000")
    amount = Decimal("5000")

    market_buy = compute_upbit_order_preview(
        market="KRW-BTC",
        side="BUY",
        order_type="MARKET",
        amount=amount,
        limit_price=None,
        reference_price=ref,
    )
    assert market_buy["quantity"] == Decimal("0.00005")
    assert market_buy["upbit_ord_type"] == "price"
    assert market_buy["broker_body"]["price"] == "5000"
    assert "volume" not in market_buy["broker_body"]

    limit_buy = compute_upbit_order_preview(
        market="KRW-BTC",
        side="BUY",
        order_type="LIMIT",
        amount=amount,
        limit_price=ref,
        reference_price=ref,
    )
    assert limit_buy["quantity"] == Decimal("0.00005")
    assert limit_buy["upbit_ord_type"] == "limit"
    assert Decimal(limit_buy["broker_body"]["volume"]) == Decimal("0.00005")
    assert limit_buy["broker_body"]["price"] == "100000000"

    market_sell = compute_upbit_order_preview(
        market="KRW-BTC",
        side="SELL",
        order_type="MARKET",
        amount=amount,
        limit_price=None,
        reference_price=ref,
    )
    assert market_sell["quantity"] == Decimal("0.00005")
    assert market_sell["upbit_ord_type"] == "market"
    assert Decimal(market_sell["broker_body"]["volume"]) == Decimal("0.00005")
    assert "price" not in market_sell["broker_body"]

    limit_sell = compute_upbit_order_preview(
        market="KRW-BTC",
        side="SELL",
        order_type="LIMIT",
        amount=amount,
        limit_price=ref,
        reference_price=ref,
    )
    assert limit_sell["quantity"] == Decimal("0.00005")
    assert limit_sell["broker_body"]["ord_type"] == "limit"


def test_preview_market_buy_ignores_fake_limit_price_5000() -> None:
    """UI에서 금액 5000을 가격란에 넣어도 MARKET면 현재가로 산출."""
    session = MagicMock()
    session.get.return_value = _uba()
    svc = ControlledLiveOrderSmokeService(session)
    with (
        patch.object(
            RuntimePreflightService,
            "run_for_uba",
            return_value={
                "overall_status": "READY_FOR_LIVE",
                "live_on_allowed": True,
                "manual_order_allowed": False,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "checks": [],
                "blockers": [],
                "warnings": [],
            },
        ),
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.UpbitLivePreflightService.run",
            return_value=SimpleNamespace(
                to_dict=lambda: {"ready": True},
                live_execution_ready=False,
            ),
        ),
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.emit_live_safety_audit"
        ),
    ):
        out = svc.preview(
            uba_id=1380,
            user_id=1,
            actor="tester",
            market="KRW-BTC",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=Decimal("5000"),  # 잘못된 가격 입력
            order_type="MARKET",
            reference_price=Decimal("160000000"),
        )
    assert out["adapter_create_order_calls"] == 0
    assert Decimal(out["quantity"]) == Decimal("0.00003125")  # 5000/160000000
    assert out["quantity"] != "1"
    assert out["reference_price"] == "160000000"


def test_confirm_mismatch_zero_orders() -> None:
    session = MagicMock()
    session.get.return_value = _uba()
    svc = ControlledLiveOrderSmokeService(session)
    with (
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.UpbitLiveSmokeService.execute"
        ) as execute,
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.UpbitLiveSmokeService.dry_run"
        ) as dry,
    ):
        try:
            svc.confirm(
                uba_id=1380,
                user_id=1,
                actor="t",
                market="KRW-BTC",
                side="BUY",
                amount=Decimal("5000"),
                limit_price=Decimal("1"),
                confirmation_text="WRONG",
                arm_token=None,
                execute_live=True,
            )
            raised = False
        except ControlledLiveOrderSmokeError as exc:
            raised = True
            assert str(exc) == "CONFIRMATION_TEXT_MISMATCH"
    assert raised
    execute.assert_not_called()
    dry.assert_not_called()


def test_confirm_dry_run_zero_adapter() -> None:
    session = MagicMock()
    session.get.return_value = _uba()
    svc = ControlledLiveOrderSmokeService(session)
    with (
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.UpbitLiveSmokeService.dry_run",
            return_value={
                "run_id": "r1",
                "adapter_create_order_calls": 0,
                "status": "DRY_RUN_COMPLETED",
            },
        ) as dry,
        patch(
            "stock_platform.trading.controlled_live_order_smoke_service.UpbitLiveSmokeService.execute"
        ) as execute,
    ):
        out = svc.confirm(
            uba_id=1380,
            user_id=1,
            actor="t",
            market="KRW-BTC",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=Decimal("100000000"),
            confirmation_text="UPBIT LIVE BUY CONFIRM",
            arm_token=None,
            execute_live=False,
        )
    dry.assert_called_once()
    execute.assert_not_called()
    assert out["adapter_create_order_calls"] == 0
