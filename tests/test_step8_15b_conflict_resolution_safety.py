"""Safe conflict resolution / resume-check / external history tests.

실제 UBA 1380 Conflict·Resume는 실행하지 않는다. Mock 세션 중심.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.external_order_history_service import (
    ExternalOrderHistoryService,
)
from stock_platform.broker.recovery_conflict_constants import (
    RecoveryConflictReviewStatus,
)
from stock_platform.broker.recovery_conflict_service import (
    BrokerRecoveryConflictService,
    RecoveryConflictError,
)
from stock_platform.broker.recovery_resolution_constants import (
    AdminConflictResolution,
)
from stock_platform.broker.recovery_resolution_service import (
    RecoveryResolutionService,
)
from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultService,
)


def _conflict(
    *,
    cid: int = 66,
    uba_id: int = 1380,
    status: str = "PENDING_REVIEW",
    external_status: str = "cancel",
    executed: str = "0",
    remaining: str = "10",
    ctype: str = "REMOTE_ORDER_NOT_FOUND_LOCALLY",
    uuid: str = "uuid-66",
    linked: int | None = None,
) -> MagicMock:
    row = MagicMock()
    row.broker_recovery_conflict_id = cid
    row.user_broker_account_id = uba_id
    row.user_id = 61
    row.broker_code = "UPBIT"
    row.conflict_type = ctype
    row.review_status = status
    row.external_status = external_status
    row.executed_quantity = Decimal(executed)
    row.remaining_quantity = Decimal(remaining)
    row.requested_quantity = Decimal(remaining)
    row.external_order_id = uuid
    row.external_order_id_masked = "uuid…0066"
    row.linked_internal_order_id = linked
    row.market_code = "KRW-SKY"
    row.side_code = "SELL"
    row.order_type_code = "LIMIT"
    row.order_price = Decimal("125")
    row.paid_fee = None
    row.external_created_at = None
    row.detected_at = datetime.now(timezone.utc)
    row.remote_snapshot = {
        "uuid": uuid,
        "state": external_status,
        "market": "KRW-SKY",
        "executed_volume": executed,
        "remaining_volume": remaining,
        "trades": (
            [
                {
                    "uuid": f"t-{cid}",
                    "price": "1",
                    "volume": "0.01",
                    "secret_key": "NOPE",
                }
            ]
            if Decimal(executed) > 0
            else []
        ),
    }
    row.resolution_type = None
    row.resolved_by = None
    row.resolved_at = None
    return row


def test_verified_connected_sync_heals_pending() -> None:
    session = MagicMock()
    uba = MagicMock()
    uba.connection_status = "CREDENTIAL_PENDING"
    entity = MagicMock()
    entity.verification_status = "VERIFIED"
    svc = BrokerCredentialVaultService(session)
    svc.get_uba = MagicMock(return_value=uba)  # type: ignore[method-assign]
    svc.get_active_entity = MagicMock(return_value=entity)  # type: ignore[method-assign]
    assert svc.sync_uba_connection_status(1) == "CONNECTED"
    assert uba.connection_status == "CONNECTED"


def test_ignore_dry_run_cancel_executed_zero_eligible() -> None:
    session = MagicMock()
    row = _conflict(cid=66, executed="0", remaining="100")
    session.get.side_effect = lambda model, key: (
        MagicMock(user_id=61, broker_code="UPBIT")
        if key == 1380
        else row
        if key == 66
        else None
    )
    # scalar count for dup uuid = 0
    session.scalar.return_value = 0
    svc = RecoveryResolutionService(session)
    with patch.object(svc._conflicts, "count_active_for_uba", return_value=40):
        out = svc.dry_run_resolve(
            1380,
            conflict_ids=[66],
            resolution=AdminConflictResolution.IGNORE_WITH_AUDIT,
            reason="검증용",
            expected_status="PENDING_REVIEW",
        )
    assert out["eligible"] == [66]
    assert out["ineligible"] == []
    assert out["db_mutated"] is False
    assert out["would_resume_account"] is False


def test_ignore_rejects_done_with_fills() -> None:
    session = MagicMock()
    row = _conflict(
        cid=45,
        external_status="done",
        executed="1.5",
        remaining="0",
        uuid="uuid-45",
    )
    session.get.side_effect = lambda model, key: (
        MagicMock() if key == 1380 else row if key == 45 else None
    )
    session.scalar.return_value = 0
    svc = RecoveryResolutionService(session)
    with patch.object(svc._conflicts, "count_active_for_uba", return_value=40):
        out = svc.dry_run_resolve(
            1380,
            conflict_ids=[45],
            resolution=AdminConflictResolution.IGNORE_WITH_AUDIT,
            reason="검증용",
        )
    assert out["eligible"] == []
    assert out["ineligible"][0]["reason_code"] == "REMOTE_NOT_CANCEL"


def test_ignore_rejects_partial_fill_cancel() -> None:
    session = MagicMock()
    row = _conflict(
        cid=65,
        external_status="cancel",
        executed="0.00005254",
        remaining="0",
    )
    session.get.side_effect = lambda model, key: (
        MagicMock() if key == 1380 else row if key == 65 else None
    )
    session.scalar.return_value = 0
    svc = RecoveryResolutionService(session)
    with patch.object(svc._conflicts, "count_active_for_uba", return_value=40):
        out = svc.dry_run_resolve(
            1380,
            conflict_ids=[65],
            resolution=AdminConflictResolution.IGNORE_WITH_AUDIT,
            reason="검증용",
        )
    assert out["ineligible"][0]["reason_code"] == "EXECUTED_VOLUME_EXISTS"


def test_other_uba_conflict_rejected() -> None:
    session = MagicMock()
    row = _conflict(cid=66, uba_id=999)
    session.get.side_effect = lambda model, key: (
        MagicMock() if key == 1380 else row if key == 66 else None
    )
    svc = RecoveryResolutionService(session)
    with patch.object(svc._conflicts, "count_active_for_uba", return_value=1):
        out = svc.dry_run_resolve(
            1380,
            conflict_ids=[66],
            resolution=AdminConflictResolution.IGNORE_WITH_AUDIT,
            reason="검증용",
        )
    assert out["ineligible"][0]["reason_code"] == "UBA_MISMATCH"


def test_already_resolved_rejected() -> None:
    session = MagicMock()
    row = _conflict(cid=66, status="IGNORED")
    session.get.side_effect = lambda model, key: (
        MagicMock() if key == 1380 else row if key == 66 else None
    )
    svc = RecoveryResolutionService(session)
    with patch.object(svc._conflicts, "count_active_for_uba", return_value=0):
        out = svc.dry_run_resolve(
            1380,
            conflict_ids=[66],
            resolution=AdminConflictResolution.IGNORE_WITH_AUDIT,
            reason="검증용",
        )
    assert out["ineligible"][0]["reason_code"] == "ALREADY_RESOLVED"


def test_reason_required() -> None:
    svc = RecoveryResolutionService(MagicMock())
    with pytest.raises(RecoveryConflictError) as exc:
        svc.dry_run_resolve(
            1380,
            conflict_ids=[66],
            resolution=AdminConflictResolution.IGNORE_WITH_AUDIT,
            reason="  ",
        )
    assert exc.value.code == "reason_required"


def test_bulk_clear_disabled() -> None:
    svc = BrokerRecoveryConflictService(MagicMock())
    with pytest.raises(RecoveryConflictError) as exc:
        svc.clear_active_conflicts_for_uba(
            1380, actor="admin:1", note="x"
        )
    assert exc.value.code == "bulk_clear_disabled"


def test_resolve_execute_disabled() -> None:
    session = MagicMock()
    session.get.return_value = MagicMock()
    svc = RecoveryResolutionService(session)
    with patch.object(
        svc,
        "dry_run_resolve",
        return_value={"eligible": [66], "ineligible": []},
    ):
        with pytest.raises(RecoveryConflictError) as exc:
            svc.resolve_selected(
                1380,
                conflict_ids=[66],
                resolution=AdminConflictResolution.IGNORE_WITH_AUDIT,
                reason="x",
                actor="admin:1",
                execute_enabled=False,
            )
    assert exc.value.code == "execute_disabled"


def test_external_history_idempotent_no_trading_order() -> None:
    session = MagicMock()
    session.scalar.return_value = None  # no existing
    conflict = _conflict(cid=45, executed="1", external_status="done")
    conflict.remote_snapshot["trades"] = [
        {"uuid": "trade-1", "price": "10", "volume": "1", "secret_key": "X"}
    ]
    svc = ExternalOrderHistoryService(session)
    first = svc.upsert_from_conflict(conflict, actor="admin:1")
    assert first["trading_order_created"] is False
    assert first["order_created"] is True
    assert first["source_conflict_id"] == 45
    # 두 번째: existing 반환
    existing = MagicMock()
    session.scalar.return_value = existing
    second = svc.upsert_from_conflict(conflict, actor="admin:1")
    assert second["order_created"] is False
    assert second["trading_order_created"] is False
    # secret 미저장
    assert existing.raw_snapshot.get("secret_key") is None


def test_resume_blocked_with_conflicts() -> None:
    session = MagicMock()
    uba = MagicMock()
    uba.is_active = True
    uba.connection_status = "CONNECTED"
    uba.broker_code = "UPBIT"
    uba.live_order_enabled = False
    uba.live_armed = False
    uba.last_synced_at = datetime.now(timezone.utc)
    session.get.return_value = uba
    svc = RecoveryResolutionService(session)
    with (
        patch.object(svc._conflicts, "count_active_for_uba", return_value=40),
        patch.object(
            svc._conflicts,
            "count_blocking_orders_for_uba",
            return_value={
                "db_open": 0,
                "submission_unknown": 0,
                "cancel_pending": 0,
                "replace_pending": 0,
            },
        ),
        patch.object(
            BrokerCredentialVaultService,
            "get_active_entity",
            return_value=SimpleNamespace(verification_status="VERIFIED"),
        ),
        patch.object(
            BrokerCredentialVaultService,
            "assert_live_order_allowed",
            return_value=None,
        ),
        patch.object(svc, "_count_remote_open_orders", return_value=0),
    ):
        # scalar used for pending counts / mismatch counts / state
        session.scalar.side_effect = [
            40,  # pending review
            None,  # state
            40,  # remote only
            0,
            0,
            0,
        ]
        out = svc.resume_check(1380, kill_switch_active=False)
    assert out["resumable"] is False
    codes = {b["code"] for b in out["blockers"]}
    assert "UNRESOLVED_CONFLICTS" in codes


def test_resume_blocked_when_kill_switch() -> None:
    session = MagicMock()
    uba = MagicMock()
    uba.is_active = True
    uba.connection_status = "CONNECTED"
    uba.broker_code = "UPBIT"
    uba.live_order_enabled = False
    uba.live_armed = False
    uba.last_synced_at = datetime.now(timezone.utc)
    session.get.return_value = uba
    session.scalar.return_value = 0
    svc = RecoveryResolutionService(session)
    with (
        patch.object(svc._conflicts, "count_active_for_uba", return_value=0),
        patch.object(
            svc._conflicts,
            "count_blocking_orders_for_uba",
            return_value={
                "db_open": 0,
                "submission_unknown": 0,
                "cancel_pending": 0,
                "replace_pending": 0,
            },
        ),
        patch.object(
            BrokerCredentialVaultService,
            "get_active_entity",
            return_value=SimpleNamespace(verification_status="VERIFIED"),
        ),
        patch.object(
            BrokerCredentialVaultService,
            "assert_live_order_allowed",
            return_value=None,
        ),
        patch.object(svc, "_count_remote_open_orders", return_value=0),
    ):
        out = svc.resume_check(1380, kill_switch_active=True)
    assert out["resumable"] is False
    assert any(b["code"] == "KILL_SWITCH_ACTIVE" for b in out["blockers"])


def test_resume_possible_when_clean() -> None:
    session = MagicMock()
    uba = MagicMock()
    uba.is_active = True
    uba.connection_status = "CONNECTED"
    uba.broker_code = "UPBIT"
    uba.live_order_enabled = False
    uba.live_armed = False
    uba.last_synced_at = datetime.now(timezone.utc)
    session.get.return_value = uba
    state = MagicMock()
    state.recovery_status = "SUCCESS"
    state.trading_paused = True
    state.lock_holder = None
    state.lock_expires_at = None
    # pending=0, state, mismatch counts 0
    session.scalar.side_effect = [0, state, 0, 0, 0, 0]
    svc = RecoveryResolutionService(session)
    with (
        patch.object(svc._conflicts, "count_active_for_uba", return_value=0),
        patch.object(
            svc._conflicts,
            "count_blocking_orders_for_uba",
            return_value={
                "db_open": 0,
                "submission_unknown": 0,
                "cancel_pending": 0,
                "replace_pending": 0,
            },
        ),
        patch.object(
            BrokerCredentialVaultService,
            "get_active_entity",
            return_value=SimpleNamespace(verification_status="VERIFIED"),
        ),
        patch.object(
            BrokerCredentialVaultService,
            "assert_live_order_allowed",
            return_value=None,
        ),
        patch.object(svc, "_count_remote_open_orders", return_value=0),
    ):
        out = svc.resume_check(1380, kill_switch_active=False)
    assert out["resumable"] is True
    assert out["live"] is False
    assert out["arm"] is False


def test_resume_does_not_flip_live_arm() -> None:
    session = MagicMock()
    uba = MagicMock()
    uba.is_active = True
    uba.broker_code = "UPBIT"
    uba.live_order_enabled = False
    uba.live_armed = False
    state = MagicMock()
    state.trading_paused = True
    state.recovery_status = "MANUAL_REVIEW"
    session.get.return_value = uba
    session.scalar.return_value = state
    svc = BrokerRecoveryConflictService(session)
    svc.count_active_for_uba = MagicMock(return_value=0)
    svc.count_blocking_orders_for_uba = MagicMock(
        return_value={
            "db_open": 0,
            "submission_unknown": 0,
            "cancel_pending": 0,
            "replace_pending": 0,
        }
    )
    with patch(
        "stock_platform.broker.recovery_conflict_service."
        "BrokerCredentialVaultService.assert_live_order_allowed",
        return_value=None,
    ):
        result = svc.resume_account(
            1,
            actor="admin:1",
            reason="ok",
            correlation_id="c1",
        )
    assert result["live_arm_unchanged"] is True
    assert result["live_order_enabled"] is False
    assert result["live_armed"] is False
    assert uba.live_order_enabled is False
    assert uba.live_armed is False


def test_user_pause_message_hides_conflict_ids() -> None:
    """사용자 메시지는 내부 Conflict ID/UUID를 포함하지 않는다."""
    from stock_platform.api.v1.user_accounts import _enrich_recovery_status

    session = MagicMock()
    state = MagicMock()
    state.trading_paused = True
    state.recovery_status = "MANUAL_REVIEW"
    state.auto_retry_enabled = False
    state.next_retry_reason = None
    session.scalar.side_effect = [state, 40]
    item = {
        "account_id": 1380,
        "account_type": "UPBIT",
        "connection_status": "CONNECTED",
    }
    with patch(
        "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService.sync_uba_connection_status",
        return_value="CONNECTED",
    ):
        out = _enrich_recovery_status(session, item)
    msg = out.get("recovery_user_message") or ""
    assert "1380" not in msg or "계좌" in msg  # account id may appear as id - check conflict
    assert "Conflict ID" not in msg
    assert "uuid" not in msg.lower()
    assert "PENDING_REVIEW" not in msg
