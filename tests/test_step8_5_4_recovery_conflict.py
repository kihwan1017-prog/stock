"""STEP 8-5-4 — Upbit remote-only recovery conflict tests."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from stock_platform.broker.recovery_conflict_constants import (
    ORDER_ORIGIN_RECOVERY_IMPORT,
    RecoveryConflictReviewStatus,
    RecoveryConflictType,
)
from stock_platform.broker.recovery_conflict_service import (
    BrokerRecoveryConflictService,
    RecoveryConflictError,
)
from stock_platform.broker.upbit.order_reconcile_service import (
    mask_external_uuid,
    sanitize_upbit_order_snapshot,
)


def test_sanitize_strips_secrets() -> None:
    remote = {
        "uuid": "abcd-1234-efgh-5678",
        "market": "KRW-BTC",
        "side": "bid",
        "ord_type": "limit",
        "state": "wait",
        "volume": "0.1",
        "executed_volume": "0",
        "price": "100000000",
        "access_key": "SECRET",
        "secret_key": "SECRET",
        "Authorization": "Bearer xxx",
        "trades": [
            {
                "uuid": "t1",
                "price": "1",
                "volume": "0.01",
                "secret": "nope",
            }
        ],
    }
    out = sanitize_upbit_order_snapshot(remote)
    assert "access_key" not in out
    assert "secret_key" not in out
    assert "Authorization" not in out
    assert out["uuid"] == remote["uuid"]
    assert out["trades"][0]["uuid"] == "t1"
    assert "secret" not in out["trades"][0]


def test_mask_external_uuid() -> None:
    assert mask_external_uuid("abcdefghijklmnop") == "abcd…mnop"
    assert mask_external_uuid("short") == "****"


def test_upsert_skips_when_local_order_exists() -> None:
    session = MagicMock()
    repo_order = MagicMock()
    repo_order.get_by_broker_order_id.return_value = MagicMock(
        order_id=99
    )

    svc = BrokerRecoveryConflictService(session)
    # TradingOrderRepository 생성 경로를 패치
    import stock_platform.broker.recovery_conflict_service as mod

    original = mod.TradingOrderRepository
    mod.TradingOrderRepository = lambda _s: repo_order  # type: ignore[misc,assignment]
    try:
        result = svc.upsert_remote_only(
            remote={"uuid": "ext-1", "market": "KRW-BTC", "side": "bid"},
            user_id=1,
            user_broker_account_id=10,
            recovery_run_id=None,
        )
    finally:
        mod.TradingOrderRepository = original

    assert result is None


def test_approve_import_never_calls_create_order() -> None:
    """Import는 get_order만 사용 — create_order 호출 금지."""

    session = MagicMock()
    conflict = MagicMock()
    conflict.broker_recovery_conflict_id = 1
    conflict.review_status = RecoveryConflictReviewStatus.PENDING_REVIEW
    conflict.broker_code = "UPBIT"
    conflict.user_broker_account_id = 10
    conflict.external_order_id = "ext-uuid-1"
    conflict.side_code = "BUY"
    conflict.order_type_code = "LIMIT"
    conflict.market_code = "KRW-BTC"
    conflict.requested_quantity = Decimal("0.1")
    conflict.executed_quantity = Decimal("0")
    conflict.remaining_quantity = Decimal("0.1")
    conflict.order_price = Decimal("100")
    conflict.average_execution_price = None
    conflict.paid_fee = None
    conflict.remote_snapshot = {
        "uuid": "ext-uuid-1",
        "state": "wait",
        "volume": "0.1",
        "executed_volume": "0",
        "ord_type": "limit",
        "side": "bid",
        "market": "KRW-BTC",
        "price": "100",
        "trades": [],
    }

    uba = MagicMock()
    uba.is_active = True
    uba.user_id = 7

    paper = MagicMock()
    paper.account_id = 55

    created_order = MagicMock()
    created_order.order_id = 501

    order_client = MagicMock()
    order_client.get_order.return_value = dict(conflict.remote_snapshot)
    order_client.create_order = MagicMock(
        side_effect=AssertionError("create_order must not be called")
    )

    svc = BrokerRecoveryConflictService(session)
    svc.get = MagicMock(return_value=conflict)  # type: ignore[method-assign]
    svc._vault_order_client = MagicMock(return_value=order_client)  # noqa: SLF001
    svc._resolve_account_id = MagicMock(return_value=55)  # noqa: SLF001

    session.get.return_value = uba
    session.scalar.side_effect = [
        None,  # duplicate order check via repo — patched below
        None,  # execution exists check
    ]

    import stock_platform.broker.recovery_conflict_service as mod

    vault = MagicMock()
    vault.assert_live_order_allowed = MagicMock()
    orig_vault = mod.BrokerCredentialVaultService
    orig_repo = mod.TradingOrderRepository
    orig_order_svc = mod.TradingOrderService

    repo = MagicMock()
    repo.get_by_broker_order_id.return_value = None

    order_svc = MagicMock()
    order_svc.create.return_value = created_order

    mod.BrokerCredentialVaultService = lambda _s: vault  # type: ignore[misc,assignment]
    mod.TradingOrderRepository = lambda _s: repo  # type: ignore[misc,assignment]
    mod.TradingOrderService = lambda _s: order_svc  # type: ignore[misc,assignment]
    try:
        # refresh_from_remote 내부에서도 get 사용
        result = svc.approve_import(1, actor="admin:1", note="ok")
    finally:
        mod.BrokerCredentialVaultService = orig_vault
        mod.TradingOrderRepository = orig_repo
        mod.TradingOrderService = orig_order_svc

    order_client.create_order.assert_not_called()
    order_client.get_order.assert_called()
    order_svc.create.assert_called_once()
    meta = order_svc.create.call_args.args[0].metadata_payload
    assert meta["order_origin"] == ORDER_ORIGIN_RECOVERY_IMPORT
    assert meta["broker_submit"] is False
    assert result["broker_submit"] is False
    assert result["internal_order_id"] == 501
    assert (
        conflict.review_status
        == RecoveryConflictReviewStatus.APPROVED_IMPORT
    )


def test_ignore_requires_note() -> None:
    session = MagicMock()
    svc = BrokerRecoveryConflictService(session)
    with pytest.raises(RecoveryConflictError) as exc:
        svc.ignore(1, actor="admin:1", note="  ")
    assert exc.value.code == "note_required"


def test_upsert_skips_new_conflict_for_terminal_remote_only() -> None:
    """done/cancel remote-only는 신규 HIGH Conflict를 만들지 않는다."""

    session = MagicMock()
    repo_order = MagicMock()
    repo_order.get_by_broker_order_id.return_value = None
    # terminal 기존 행 없음 + active 행 없음
    session.scalar.side_effect = [None, None]

    svc = BrokerRecoveryConflictService(session)
    import stock_platform.broker.recovery_conflict_service as mod

    original = mod.TradingOrderRepository
    mod.TradingOrderRepository = lambda _s: repo_order  # type: ignore[misc,assignment]
    try:
        for state in ("done", "cancel"):
            session.scalar.side_effect = [None, None]
            session.add.reset_mock()
            result = svc.upsert_remote_only(
                remote={
                    "uuid": f"ext-terminal-{state}",
                    "market": "KRW-ETH",
                    "side": "ask",
                    "state": state,
                    "volume": "1",
                    "executed_volume": "1" if state == "done" else "0",
                    "remaining_volume": "0" if state == "done" else "1",
                },
                user_id=1,
                user_broker_account_id=10,
                recovery_run_id=None,
            )
            assert result is None
            session.add.assert_not_called()
    finally:
        mod.TradingOrderRepository = original


def test_upsert_still_creates_for_wait_remote_only() -> None:
    """wait remote-only는 기존처럼 HIGH PENDING Conflict를 생성한다."""

    session = MagicMock()
    repo_order = MagicMock()
    repo_order.get_by_broker_order_id.return_value = None
    session.scalar.side_effect = [None, None]

    def _flush_assign_id() -> None:
        # Identity 미할당 mock 환경에서 audit detail 직렬화 가능하도록
        for args in session.add.call_args_list:
            obj = args[0][0]
            if getattr(obj, "broker_recovery_conflict_id", None) is None:
                obj.broker_recovery_conflict_id = 999

    session.flush.side_effect = _flush_assign_id

    svc = BrokerRecoveryConflictService(session)
    import stock_platform.broker.recovery_conflict_service as mod

    original = mod.TradingOrderRepository
    mod.TradingOrderRepository = lambda _s: repo_order  # type: ignore[misc,assignment]
    try:
        result = svc.upsert_remote_only(
            remote={
                "uuid": "ext-wait-1",
                "market": "KRW-BTC",
                "side": "bid",
                "state": "wait",
                "volume": "0.01",
                "executed_volume": "0",
                "remaining_volume": "0.01",
                "price": "100000000",
            },
            user_id=1,
            user_broker_account_id=10,
            recovery_run_id=None,
        )
    finally:
        mod.TradingOrderRepository = original

    assert result is not None
    session.add.assert_called()
    assert (
        result.review_status
        == RecoveryConflictReviewStatus.PENDING_REVIEW
    )
    assert result.risk_level == "HIGH"


def test_conflict_type_constant() -> None:
    assert (
        RecoveryConflictType.REMOTE_ORDER_NOT_FOUND_LOCALLY
        == "REMOTE_ORDER_NOT_FOUND_LOCALLY"
    )
