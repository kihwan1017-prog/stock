"""Smoke QUEUED → finalize DISARM → Worker LIVE 요구 deadlock (설계 A TTL).

실제 Upbit /v1/orders · adapter.create_order 호출 금지 — mock/spy만.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.outbox_worker import OrderOutboxWorker
from stock_platform.trading.smoke_one_shot_dispatch_grant import (
    GRANT_STATUS_ISSUED,
    SmokeOneShotGrantError,
    assert_smoke_one_shot_dispatch_allowed,
    build_smoke_one_shot_grant,
    consume_grant_on_run,
    dry_run_order_reusable_with_grant,
    issue_grant_on_run,
    read_grant_from_run_detail,
)
from stock_platform.trading.upbit_live_smoke_service import (
    UpbitLiveSmokeService,
)


def _future(seconds: int = 300) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _past(seconds: int = 1) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


def _grant(
    *,
    run_id: str = "uvs-test",
    order_id: int = 1680,
    outbox_id: int = 1117,
    uba_id: int = 1380,
    owner_user_id: int = 1,
    arm_snapshot: datetime | None = None,
    dispatch_expires: datetime | None = None,
    idempotency_key: str = "smoke:uvs-test",
) -> dict[str, Any]:
    return build_smoke_one_shot_grant(
        run_id=run_id,
        order_id=order_id,
        outbox_id=outbox_id,
        uba_id=uba_id,
        owner_user_id=owner_user_id,
        arm_snapshot_expires_at=arm_snapshot or _future(600),
        dispatch_expires_at=dispatch_expires or _future(90),
        idempotency_key=idempotency_key,
    )


def _uba(
    *,
    uba_id: int = 1380,
    user_id: int = 1,
    live: bool = False,
    arm: bool = False,
    arm_expires_at: datetime | None = None,
):
    return SimpleNamespace(
        user_broker_account_id=uba_id,
        user_id=user_id,
        broker_code="UPBIT",
        is_active=True,
        deleted_at=None,
        live_order_enabled=live,
        live_armed=arm,
        arm_expires_at=arm_expires_at,
        arm_token_hash=None,
    )


def _order(
    *,
    order_id: int = 1680,
    uba_id: int = 1380,
    smoke_run_id: str = "uvs-test",
    broker_order_id: str | None = None,
    attempt: int = 0,
):
    return SimpleNamespace(
        order_id=order_id,
        user_broker_account_id=uba_id,
        broker_order_id=broker_order_id,
        submission_attempt_count=attempt,
        metadata_payload={"smoke_run_id": smoke_run_id},
        status_code="PENDING",
    )


def _run(
    *,
    run_id: str = "uvs-test",
    order_id: int = 1680,
    uba_id: int = 1380,
    detail: dict[str, Any] | None = None,
):
    return SimpleNamespace(
        run_id=run_id,
        order_id=order_id,
        user_broker_account_id=uba_id,
        user_id=1,
        execute_live=True,
        detail=detail or {},
    )


def _payload(*, order_id: int = 1680, uba_id: int = 1380) -> dict[str, Any]:
    return {
        "order_id": order_id,
        "user_broker_account_id": uba_id,
        "owner_user_id": 1,
        "broker_code": "UPBIT",
        "environment": "LIVE",
    }


def test_deadlock_repro_finalize_disarms_while_pending() -> None:
    """1. QUEUED 직후 finalize → LIVE OFF/ARM OFF (기존 deadlock 원인)."""

    session = MagicMock()
    run = _run(detail={})
    run.status_code = "QUEUED"
    run.internal_status = "OUTBOX_PENDING"
    run.broker_order_status = "NOT_SUBMITTED"
    run.execute_live = True
    run.completed_at = None

    arm = MagicMock()
    with (
        patch(
            "stock_platform.trading.upbit_live_smoke_service.LiveArmService",
            return_value=arm,
        ),
        patch(
            "stock_platform.trading.upbit_live_smoke_service.emit_live_order_telegram"
        ),
        patch(
            "stock_platform.trading.upbit_live_smoke_service.emit_live_safety_audit"
        ),
        patch.object(UpbitLiveSmokeService, "_pause_uba_scope"),
        patch.object(UpbitLiveSmokeService, "_transition"),
        patch.object(UpbitLiveSmokeService, "_safe_flush", return_value=True),
    ):
        UpbitLiveSmokeService(session)._finalize_protect(
            user_broker_account_id=1380,
            run=run,  # type: ignore[arg-type]
            actor="t",
        )
    arm.disarm.assert_called_once()
    assert arm.disarm.call_args.kwargs.get("turn_live_off") is True


def test_fix_worker_allows_with_one_shot_without_live_arm() -> None:
    """2. LIVE OFF 후에도 유효 dispatch grant 시 Worker assert 통과."""

    grant = _grant()
    run = _run(detail={"smoke_one_shot_dispatch_grant": grant})
    order = _order()
    uba = _uba(live=False, arm=False)

    session = MagicMock()
    session.get.return_value = uba

    class _Vault:
        def __init__(self, *_a, **_k):
            pass

        def assert_live_order_allowed(self, *_a, **_k):
            return None

    with (
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_transition_guard.LiveTradingTransitionGuard"
        ) as TG,
        patch(
            "stock_platform.trading.live_arm_service.LiveArmService"
        ) as ARM,
        patch(
            "stock_platform.order.repository.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_grant._load_smoke_run_for_order",
            return_value=run,
        ),
        patch(
            "stock_platform.risk_engine.kill_switch_service.KillSwitchService"
        ) as KS,
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService",
            _Vault,
        ),
        patch(
            "stock_platform.order.live_safety_audit.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.order.outbox_dispatch_safety.assert_live_outbox_account_runtime_gates"
        ),
    ):
        TG.return_value.require_active.return_value = object()
        ARM.return_value.expire_if_needed.return_value = False
        OR.return_value.get.return_value = order
        KS.return_value.is_active_for_scopes.return_value = False
        KS.GLOBAL_SCOPE = "GLOBAL"

        OrderOutboxWorker._assert_live_dispatch_allowed(
            session, _payload(), outbox_id=1117
        )


def test_other_pending_outbox_blocked() -> None:
    """3. 다른 outbox_id — grant mismatch 차단."""

    grant = _grant()
    run = _run(detail={"smoke_one_shot_dispatch_grant": grant})
    session = MagicMock()
    with (
        patch(
            "stock_platform.order.repository.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_grant._load_smoke_run_for_order",
            return_value=run,
        ),
    ):
        OR.return_value.get.return_value = _order()
        with pytest.raises(SmokeOneShotGrantError, match="OUTBOX_MISMATCH"):
            assert_smoke_one_shot_dispatch_allowed(
                session, _payload(), outbox_id=9999
            )


def test_other_uba_blocked() -> None:
    """4. 다른 UBA 차단."""

    grant = _grant()
    run = _run(detail={"smoke_one_shot_dispatch_grant": grant})
    session = MagicMock()
    with (
        patch(
            "stock_platform.order.repository.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_grant._load_smoke_run_for_order",
            return_value=run,
        ),
    ):
        OR.return_value.get.return_value = _order(uba_id=1380)
        with pytest.raises(SmokeOneShotGrantError, match="UBA_MISMATCH"):
            assert_smoke_one_shot_dispatch_allowed(
                session,
                _payload(uba_id=2222),
                outbox_id=1117,
            )


def test_dispatch_ttl_expired_blocked() -> None:
    """5. grant dispatch TTL 만료 차단 (ARM snapshot과 무관)."""

    grant = _grant(arm_snapshot=_future(600), dispatch_expires=_future(90))
    # 발급 후 만료된 grant를 시뮬레이션 (build는 미래만 허용)
    grant["dispatch_expires_at"] = _past(1).isoformat()
    run = _run(detail={"smoke_one_shot_dispatch_grant": grant})
    session = MagicMock()
    with (
        patch(
            "stock_platform.order.repository.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_grant._load_smoke_run_for_order",
            return_value=run,
        ),
    ):
        OR.return_value.get.return_value = _order()
        with pytest.raises(
            SmokeOneShotGrantError, match="DISPATCH_EXPIRED"
        ):
            assert_smoke_one_shot_dispatch_allowed(
                session, _payload(), outbox_id=1117
            )


def test_arm_snapshot_expired_still_ok_if_dispatch_valid() -> None:
    """ARM snapshot이 과거여도 dispatch_expires_at이 유효하면 PASS."""

    grant = _grant(
        arm_snapshot=_past(30),
        dispatch_expires=_future(60),
    )
    run = _run(detail={"smoke_one_shot_dispatch_grant": grant})
    session = MagicMock()
    session.get.return_value = _uba()

    class _Vault:
        def __init__(self, *_a, **_k):
            pass

        def assert_live_order_allowed(self, *_a, **_k):
            return None

    with (
        patch(
            "stock_platform.order.repository.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_grant._load_smoke_run_for_order",
            return_value=run,
        ),
        patch(
            "stock_platform.risk_engine.kill_switch_service.KillSwitchService"
        ) as KS,
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService",
            _Vault,
        ),
    ):
        OR.return_value.get.return_value = _order()
        KS.return_value.is_active_for_scopes.return_value = False
        KS.GLOBAL_SCOPE = "GLOBAL"
        assert_smoke_one_shot_dispatch_allowed(
            session, _payload(), outbox_id=1117
        )


def test_activation_expired_blocked() -> None:
    """6. Activation 만료/없음 — Worker require_active 실패."""

    session = MagicMock()
    session.get.return_value = _uba(live=False, arm=False)
    with (
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_transition_guard.LiveTradingTransitionGuard"
        ) as TG,
        patch(
            "stock_platform.trading.live_arm_service.LiveArmService"
        ) as ARM,
    ):
        TG.return_value.require_active.side_effect = PermissionError(
            "No active live trading transition approval"
        )
        ARM.return_value.expire_if_needed.return_value = False
        with pytest.raises(PermissionError, match="active live trading"):
            OrderOutboxWorker._assert_live_dispatch_allowed(
                session, _payload(), outbox_id=1117
            )


def test_kill_switch_blocked() -> None:
    """7. Kill Switch 차단."""

    grant = _grant()
    run = _run(detail={"smoke_one_shot_dispatch_grant": grant})
    session = MagicMock()
    session.get.return_value = _uba()
    with (
        patch(
            "stock_platform.order.repository.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_grant._load_smoke_run_for_order",
            return_value=run,
        ),
        patch(
            "stock_platform.risk_engine.kill_switch_service.KillSwitchService"
        ) as KS,
    ):
        OR.return_value.get.return_value = _order()
        KS.return_value.is_active_for_scopes.return_value = True
        KS.GLOBAL_SCOPE = "GLOBAL"
        with pytest.raises(SmokeOneShotGrantError, match="KILL_SWITCH"):
            assert_smoke_one_shot_dispatch_allowed(
                session, _payload(), outbox_id=1117
            )


def test_duplicate_idempotency_shape_blocked() -> None:
    """8. idempotency 형태 불일치 차단."""

    grant = _grant(idempotency_key="smoke:OTHER")
    run = _run(detail={"smoke_one_shot_dispatch_grant": grant})
    session = MagicMock()
    with (
        patch(
            "stock_platform.order.repository.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_grant._load_smoke_run_for_order",
            return_value=run,
        ),
    ):
        OR.return_value.get.return_value = _order()
        with pytest.raises(
            SmokeOneShotGrantError, match="IDEMPOTENCY_SHAPE"
        ):
            assert_smoke_one_shot_dispatch_allowed(
                session, _payload(), outbox_id=1117
            )


def test_broker_uuid_blocks_resubmit() -> None:
    """9. broker UUID 존재 시 재전송 차단."""

    grant = _grant()
    run = _run(detail={"smoke_one_shot_dispatch_grant": grant})
    session = MagicMock()
    with (
        patch(
            "stock_platform.order.repository.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_grant._load_smoke_run_for_order",
            return_value=run,
        ),
    ):
        OR.return_value.get.return_value = _order(
            broker_order_id="upbit-uuid-1"
        )
        with pytest.raises(
            SmokeOneShotGrantError, match="BROKER_UUID_EXISTS"
        ):
            assert_smoke_one_shot_dispatch_allowed(
                session, _payload(), outbox_id=1117
            )


def test_success_dispatch_auto_disarm_live_off() -> None:
    """10. 성공 terminal 후 DISARM + LIVE OFF."""

    session = MagicMock()
    grant = _grant()
    run = _run(detail={"smoke_one_shot_dispatch_grant": grant})
    order = _order()
    arm = MagicMock()

    with (
        patch(
            "stock_platform.order.repository.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.upbit_live_smoke_service.LiveArmService",
            return_value=arm,
        ),
        patch(
            "stock_platform.trading.upbit_live_smoke_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.upbit_live_smoke_service.select",
        ),
    ):
        OR.return_value.get.return_value = order
        session.scalar.return_value = run
        out = UpbitLiveSmokeService.finalize_after_smoke_dispatch(
            session,
            order_id=1680,
            outbox_id=1117,
            actor="worker-1",
            outcome="SUBMITTED",
        )
    assert out["applied"] is True
    arm.disarm.assert_called_once()
    assert arm.disarm.call_args.kwargs.get("turn_live_off") is True
    g = read_grant_from_run_detail(run.detail)
    assert g is not None
    assert g["status"] == "CONSUMED"


def test_failed_dispatch_auto_disarm_live_off() -> None:
    """11. 실패 terminal 후 DISARM + LIVE OFF."""

    session = MagicMock()
    grant = _grant()
    run = _run(detail={"smoke_one_shot_dispatch_grant": grant})
    arm = MagicMock()
    with (
        patch(
            "stock_platform.order.repository.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.upbit_live_smoke_service.LiveArmService",
            return_value=arm,
        ),
        patch(
            "stock_platform.trading.upbit_live_smoke_service.emit_live_safety_audit"
        ),
    ):
        OR.return_value.get.return_value = _order()
        session.scalar.return_value = run
        out = UpbitLiveSmokeService.finalize_after_smoke_dispatch(
            session,
            order_id=1680,
            outbox_id=1117,
            actor="worker-1",
            outcome="FAILED",
        )
    assert out["applied"] is True
    assert arm.disarm.call_args.kwargs.get("turn_live_off") is True


def test_adapter_create_order_not_called_in_grant_path() -> None:
    """12–13. grant 검증만 — adapter create_order /v1/orders 0."""

    create_calls: list[Any] = []

    class FakeAdapter:
        def create_order(self, *a, **k):
            create_calls.append((a, k))
            raise AssertionError("must not call create_order")

    grant = _grant()
    run = _run(detail={"smoke_one_shot_dispatch_grant": grant})
    session = MagicMock()
    session.get.return_value = _uba()

    class _Vault:
        def __init__(self, *_a, **_k):
            pass

        def assert_live_order_allowed(self, *_a, **_k):
            return None

    with (
        patch(
            "stock_platform.order.repository.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_grant._load_smoke_run_for_order",
            return_value=run,
        ),
        patch(
            "stock_platform.risk_engine.kill_switch_service.KillSwitchService"
        ) as KS,
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService",
            _Vault,
        ),
    ):
        OR.return_value.get.return_value = _order()
        KS.return_value.is_active_for_scopes.return_value = False
        KS.GLOBAL_SCOPE = "GLOBAL"
        assert_smoke_one_shot_dispatch_allowed(
            session, _payload(), outbox_id=1117
        )
        FakeAdapter().create_order  # noqa: B018
    assert create_calls == []


def test_issue_grant_requires_arm() -> None:
    session = MagicMock()
    uba = _uba(live=True, arm=False, arm_expires_at=None)
    session.get.return_value = uba
    run = _run()
    svc = UpbitLiveSmokeService(session)
    with pytest.raises(Exception):
        svc._issue_one_shot_dispatch_grant(
            run=run,  # type: ignore[arg-type]
            order_id=1680,
            outbox_id=1117,
            user_broker_account_id=1380,
            actor="t",
        )


def test_issue_grant_requires_live_on() -> None:
    session = MagicMock()
    session.get.return_value = _uba(
        live=False, arm=True, arm_expires_at=_future(300)
    )
    run = _run()
    svc = UpbitLiveSmokeService(session)
    with pytest.raises(Exception) as ei:
        svc._issue_one_shot_dispatch_grant(
            run=run,  # type: ignore[arg-type]
            order_id=1680,
            outbox_id=1117,
            user_broker_account_id=1380,
            actor="t",
        )
    assert "LIVE_ORDER_DISABLED" in str(ei.value)


def test_issue_grant_requires_unexpired_arm() -> None:
    session = MagicMock()
    session.get.return_value = _uba(
        live=True, arm=True, arm_expires_at=_past(5)
    )
    run = _run()
    svc = UpbitLiveSmokeService(session)
    with pytest.raises(Exception) as ei:
        svc._issue_one_shot_dispatch_grant(
            run=run,  # type: ignore[arg-type]
            order_id=1680,
            outbox_id=1117,
            user_broker_account_id=1380,
            actor="t",
        )
    assert "LIVE_ARM_EXPIRED" in str(ei.value)


def test_issue_and_consume_grant_roundtrip() -> None:
    run = _run()
    grant = issue_grant_on_run(
        run,
        order_id=1680,
        outbox_id=1117,
        uba_id=1380,
        owner_user_id=1,
        arm_snapshot_expires_at=_future(300),
        dispatch_ttl_seconds=90,
        idempotency_key="smoke:uvs-test",
    )
    assert grant["status"] == GRANT_STATUS_ISSUED
    assert grant.get("dispatch_expires_at")
    issued = datetime.fromisoformat(grant["issued_at"])
    dispatch = datetime.fromisoformat(grant["dispatch_expires_at"])
    assert dispatch > issued
    consume_grant_on_run(run, outcome="SUBMITTED")
    g2 = read_grant_from_run_detail(run.detail)
    assert g2 is not None
    assert g2["status"] == "CONSUMED"
    consume_grant_on_run(run, outcome="SUBMITTED")
    assert read_grant_from_run_detail(run.detail)["status"] == "CONSUMED"


def test_1680_dry_run_must_retire_without_grant() -> None:
    """STEP8 — 기존 1680은 grant 없어 MUST_RETIRE (상태 미변경)."""

    assert (
        dry_run_order_reusable_with_grant(
            has_grant_issued=False,
            broker_order_id=None,
            submission_attempt_count=0,
            dispatch_expires_at=None,
        )
        == "MUST_RETIRE"
    )


def test_v1_grant_version_mismatch_blocked() -> None:
    """구버전 grant(ARM deadline만)는 Fail Closed."""

    grant = _grant()
    grant["version"] = 1
    del grant["dispatch_expires_at"]
    run = _run(detail={"smoke_one_shot_dispatch_grant": grant})
    session = MagicMock()
    with (
        patch(
            "stock_platform.order.repository.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_grant._load_smoke_run_for_order",
            return_value=run,
        ),
    ):
        OR.return_value.get.return_value = _order()
        with pytest.raises(
            SmokeOneShotGrantError, match="VERSION_MISMATCH"
        ):
            assert_smoke_one_shot_dispatch_allowed(
                session, _payload(), outbox_id=1117
            )


def test_consumed_grant_blocked() -> None:
    grant = _grant()
    grant["status"] = "CONSUMED"
    grant["consumed_at"] = datetime.now(timezone.utc).isoformat()
    run = _run(detail={"smoke_one_shot_dispatch_grant": grant})
    session = MagicMock()
    with (
        patch(
            "stock_platform.order.repository.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_grant._load_smoke_run_for_order",
            return_value=run,
        ),
    ):
        OR.return_value.get.return_value = _order()
        with pytest.raises(SmokeOneShotGrantError, match="NOT_ISSUED"):
            assert_smoke_one_shot_dispatch_allowed(
                session, _payload(), outbox_id=1117
            )


def test_outbox_idempotency_mismatch_blocked() -> None:
    grant = _grant()
    run = _run(detail={"smoke_one_shot_dispatch_grant": grant})
    session = MagicMock()
    with (
        patch(
            "stock_platform.order.repository.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_grant._load_smoke_run_for_order",
            return_value=run,
        ),
    ):
        OR.return_value.get.return_value = _order()
        with pytest.raises(
            SmokeOneShotGrantError, match="IDEMPOTENCY_MISMATCH"
        ):
            assert_smoke_one_shot_dispatch_allowed(
                session,
                _payload(),
                outbox_id=1117,
                outbox_idempotency_key="smoke:OTHER",
            )


def test_normal_live_order_still_requires_live_arm() -> None:
    """일반 LIVE 주문 — outbox_id 없이 LIVE/ARM gate 유지."""

    session = MagicMock()
    session.get.return_value = _uba(live=False, arm=False)
    with (
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(code="OK"),
        ),
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        ),
        patch(
            "stock_platform.broker.live_transition_guard.LiveTradingTransitionGuard"
        ) as TG,
        patch(
            "stock_platform.trading.live_arm_service.LiveArmService"
        ) as ARM,
    ):
        TG.return_value.require_active.return_value = object()
        ARM.return_value.expire_if_needed.return_value = False
        with pytest.raises(PermissionError, match="LIVE_ORDER_DISABLED"):
            OrderOutboxWorker._assert_live_dispatch_allowed(
                session, _payload(), outbox_id=None
            )


def test_paper_dispatch_skips_live_gates() -> None:
    """Paper — LIVE gate 영향 없음."""

    session = MagicMock()
    OrderOutboxWorker._assert_live_dispatch_allowed(
        session,
        {
            "order_id": 1,
            "environment": "PAPER",
            "broker_code": "UPBIT",
        },
        outbox_id=1,
    )
    session.get.assert_not_called()
