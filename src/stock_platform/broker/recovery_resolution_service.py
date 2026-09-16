"""선택 Conflict Resolution · Dry-run · Resume 사전점검."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.broker.external_order_history_service import (
    ExternalOrderHistoryService,
)
from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.broker.recovery_conflict_constants import (
    ACTIVE_REVIEW_STATUSES,
    RecoveryConflictResolution,
    RecoveryConflictReviewStatus,
    RecoveryConflictType,
)
from stock_platform.broker.recovery_conflict_entities import (
    BrokerRecoveryConflictEntity,
)
from stock_platform.broker.recovery_conflict_service import (
    BrokerRecoveryConflictService,
    RecoveryConflictError,
)
from stock_platform.broker.recovery_resolution_constants import (
    OPEN_REMOTE_STATUSES,
    TERMINAL_REMOTE_STATUSES,
    AdminConflictResolution,
    IGNORE_ELIGIBLE_TYPES,
)
from stock_platform.trading.account_models import UserBrokerAccount


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _qty(value: Decimal | None) -> Decimal:
    return value if value is not None else Decimal("0")


class RecoveryResolutionService:
    """일괄 Clear 대신 선택 Resolution / Dry-run / Resume-check."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._conflicts = BrokerRecoveryConflictService(session)
        self._history = ExternalOrderHistoryService(session)

    def classify_recommendation(
        self, row: BrokerRecoveryConflictEntity
    ) -> dict[str, Any]:
        """관리자 UI용 Resolution 권고."""

        ignore = self.evaluate_ignore_eligibility(row)
        if ignore["eligible"]:
            return {
                "recommended_resolution": (
                    AdminConflictResolution.IGNORE_WITH_AUDIT.value
                ),
                "eligible_for_ignore": True,
                "needs_remote_history_preserve": False,
                "blocked": False,
                "reason_code": None,
                "message": "체결 0 · 원격 취소 종료 — Ignore 후보",
            }
        executed = _qty(row.executed_quantity)
        status = str(row.external_status or "").lower()
        if executed > 0 or status == "done":
            return {
                "recommended_resolution": (
                    AdminConflictResolution.PRESERVE_REMOTE_HISTORY.value
                ),
                "eligible_for_ignore": False,
                "needs_remote_history_preserve": True,
                "blocked": False,
                "reason_code": "EXECUTED_VOLUME_EXISTS",
                "message": "체결 이력이 있어 원격 이력 보존이 필요합니다.",
            }
        return {
            "recommended_resolution": (
                AdminConflictResolution.REJECT_RESOLUTION.value
            ),
            "eligible_for_ignore": False,
            "needs_remote_history_preserve": False,
            "blocked": True,
            "reason_code": ignore.get("reason_code") or "NOT_ELIGIBLE",
            "message": ignore.get("message") or "처리 조건을 만족하지 않습니다.",
        }

    def evaluate_ignore_eligibility(
        self, row: BrokerRecoveryConflictEntity
    ) -> dict[str, Any]:
        """IGNORE_WITH_AUDIT 조건 전부 검사."""

        ctype = str(row.conflict_type or "")
        if ctype not in IGNORE_ELIGIBLE_TYPES:
            return {
                "eligible": False,
                "reason_code": "UNSUPPORTED_CONFLICT_TYPE",
                "message": f"Ignore 불가 유형: {ctype}",
            }
        status = str(row.external_status or "").lower()
        if status in OPEN_REMOTE_STATUSES:
            return {
                "eligible": False,
                "reason_code": "REMOTE_ORDER_OPEN",
                "message": "원격 미체결(wait/watch) 상태입니다.",
            }
        if status != "cancel":
            return {
                "eligible": False,
                "reason_code": "REMOTE_NOT_CANCEL",
                "message": "원격 상태가 cancel이 아닙니다.",
            }
        if status not in TERMINAL_REMOTE_STATUSES:
            return {
                "eligible": False,
                "reason_code": "REMOTE_NOT_TERMINAL",
                "message": "원격 주문이 종료 상태가 아닙니다.",
            }
        if _qty(row.executed_quantity) > 0:
            return {
                "eligible": False,
                "reason_code": "EXECUTED_VOLUME_EXISTS",
                "message": "체결 수량이 존재하므로 Ignore할 수 없습니다.",
            }
        # cancel 종료 주문은 remaining이 요청수량과 같을 수 있음(미체결 취소).
        # wait/watch가 아니면 잔여 미체결로 보지 않는다.
        if status not in {"cancel", "cancelled", "canceled"} and _qty(
            row.remaining_quantity
        ) > 0:
            return {
                "eligible": False,
                "reason_code": "REMAINING_VOLUME_EXISTS",
                "message": "잔여 수량이 0이 아닙니다.",
            }
        if row.linked_internal_order_id is not None:
            return {
                "eligible": False,
                "reason_code": "LOCAL_ORDER_LINKED",
                "message": "연결된 로컬 주문이 있습니다.",
            }
        # 동일 UUID 다른 활성 Conflict
        dup = int(
            self._session.scalar(
                select(func.count())
                .select_from(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.external_order_id
                    == row.external_order_id,
                    BrokerRecoveryConflictEntity.review_status.in_(
                        list(ACTIVE_REVIEW_STATUSES)
                    ),
                    BrokerRecoveryConflictEntity.broker_recovery_conflict_id
                    != int(row.broker_recovery_conflict_id),
                )
            )
            or 0
        )
        if dup > 0:
            return {
                "eligible": False,
                "reason_code": "DUPLICATE_ACTIVE_UUID",
                "message": "동일 원격 UUID의 다른 활성 Conflict가 있습니다.",
            }
        return {
            "eligible": True,
            "reason_code": None,
            "message": "Ignore 가능",
        }

    def evaluate_preserve_eligibility(
        self, row: BrokerRecoveryConflictEntity
    ) -> dict[str, Any]:
        if row.review_status not in ACTIVE_REVIEW_STATUSES:
            return {
                "eligible": False,
                "reason_code": "ALREADY_RESOLVED",
                "message": "이미 처리된 Conflict입니다.",
            }
        if _qty(row.executed_quantity) <= 0 and str(
            row.external_status or ""
        ).lower() != "done":
            return {
                "eligible": False,
                "reason_code": "NO_FILL_TO_PRESERVE",
                "message": "보존할 체결 이력이 없습니다. Ignore를 검토하세요.",
            }
        return {
            "eligible": True,
            "reason_code": None,
            "message": "원격 이력 보존 가능",
        }

    def dry_run_resolve(
        self,
        uba_id: int,
        *,
        conflict_ids: list[int],
        resolution: str,
        reason: str,
        expected_status: str | None = None,
    ) -> dict[str, Any]:
        """상태 변경 없이 선택 Conflict 처리 가능 여부만 반환."""

        if not (reason or "").strip():
            raise RecoveryConflictError(
                "reason_required", "Resolution reason is required"
            )
        try:
            res = AdminConflictResolution(str(resolution).strip())
        except ValueError as exc:
            raise RecoveryConflictError(
                "invalid_resolution",
                f"Unsupported resolution: {resolution}",
            ) from exc

        uba = self._session.get(UserBrokerAccount, int(uba_id))
        if uba is None:
            raise RecoveryConflictError(
                "uba_not_found", "User broker account not found"
            )

        eligible: list[int] = []
        ineligible: list[dict[str, Any]] = []
        for cid in conflict_ids:
            row = self._session.get(
                BrokerRecoveryConflictEntity, int(cid)
            )
            if row is None:
                ineligible.append(
                    {
                        "conflict_id": int(cid),
                        "reason_code": "NOT_FOUND",
                        "message": "Conflict를 찾을 수 없습니다.",
                    }
                )
                continue
            if int(row.user_broker_account_id or 0) != int(uba_id):
                ineligible.append(
                    {
                        "conflict_id": int(cid),
                        "reason_code": "UBA_MISMATCH",
                        "message": "해당 UBA 소유 Conflict가 아닙니다.",
                    }
                )
                continue
            if row.review_status not in ACTIVE_REVIEW_STATUSES:
                ineligible.append(
                    {
                        "conflict_id": int(cid),
                        "reason_code": "ALREADY_RESOLVED",
                        "message": (
                            f"이미 처리됨: {row.review_status}"
                        ),
                    }
                )
                continue
            if expected_status and str(row.review_status) != str(
                expected_status
            ):
                ineligible.append(
                    {
                        "conflict_id": int(cid),
                        "reason_code": "STATUS_MISMATCH",
                        "message": (
                            f"expected_status={expected_status}, "
                            f"actual={row.review_status}"
                        ),
                    }
                )
                continue

            if res == AdminConflictResolution.IGNORE_WITH_AUDIT:
                check = self.evaluate_ignore_eligibility(row)
            elif res == AdminConflictResolution.PRESERVE_REMOTE_HISTORY:
                check = self.evaluate_preserve_eligibility(row)
            elif res == AdminConflictResolution.APPROVE_IMPORT:
                check = {
                    "eligible": False,
                    "reason_code": "USE_APPROVE_IMPORT_API",
                    "message": (
                        "Approve Import는 "
                        "/conflicts/{id}/approve-import 전용입니다."
                    ),
                }
            elif res == AdminConflictResolution.REJECT_RESOLUTION:
                check = {
                    "eligible": True,
                    "reason_code": None,
                    "message": "거절(상태 유지) — dry-run만 가능",
                }
            else:
                check = {
                    "eligible": False,
                    "reason_code": "INVALID_RESOLUTION",
                    "message": "지원하지 않는 resolution",
                }

            if check.get("eligible"):
                eligible.append(int(cid))
            else:
                ineligible.append(
                    {
                        "conflict_id": int(cid),
                        "reason_code": check.get("reason_code"),
                        "message": check.get("message"),
                    }
                )

        active_after = self._conflicts.count_active_for_uba(uba_id)
        # dry-run: eligible만큼 줄인 가정
        assumed_remaining = max(0, active_after - len(eligible))
        return {
            "uba_id": int(uba_id),
            "resolution": res.value,
            "eligible": eligible,
            "ineligible": ineligible,
            "active_conflict_count": active_after,
            "would_resume_account": assumed_remaining == 0,
            "db_mutated": False,
        }

    def resolve_selected(
        self,
        uba_id: int,
        *,
        conflict_ids: list[int],
        resolution: str,
        reason: str,
        actor: str,
        expected_status: str | None = None,
        execute_enabled: bool = True,
    ) -> dict[str, Any]:
        """선택 Conflict 실제 처리. execute_enabled=False면 거부."""

        if not execute_enabled:
            raise RecoveryConflictError(
                "execute_disabled",
                "Conflict resolve execute is disabled "
                "(dry-run only mode). Use resolve-dry-run.",
            )
        dry = self.dry_run_resolve(
            uba_id,
            conflict_ids=conflict_ids,
            resolution=resolution,
            reason=reason,
            expected_status=expected_status,
        )
        if dry["ineligible"]:
            raise RecoveryConflictError(
                "resolve_ineligible",
                "One or more conflicts are not eligible",
                detail={"dry_run": dry},
            )
        res = AdminConflictResolution(resolution)
        if res == AdminConflictResolution.REJECT_RESOLUTION:
            return {
                **dry,
                "processed": [],
                "message": "REJECT_RESOLUTION — 상태 변경 없음",
                "db_mutated": False,
            }

        processed: list[dict[str, Any]] = []
        for cid in dry["eligible"]:
            # 동시성: FOR UPDATE
            row = self._session.scalar(
                select(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.broker_recovery_conflict_id
                    == int(cid)
                )
                .with_for_update()
                .limit(1)
            )
            if row is None:
                raise RecoveryConflictError(
                    "conflict_not_found", f"Conflict {cid} not found"
                )
            before = {
                "review_status": row.review_status,
                "resolution_type": row.resolution_type,
                "resolved_by": row.resolved_by,
            }
            if row.review_status not in ACTIVE_REVIEW_STATUSES:
                raise RecoveryConflictError(
                    "already_resolved",
                    f"Conflict {cid} already resolved "
                    f"({row.review_status})",
                )
            history_result = None
            if res == AdminConflictResolution.IGNORE_WITH_AUDIT:
                check = self.evaluate_ignore_eligibility(row)
                if not check["eligible"]:
                    raise RecoveryConflictError(
                        check["reason_code"] or "not_eligible",
                        check["message"] or "Not eligible",
                    )
                row.review_status = RecoveryConflictReviewStatus.IGNORED
                row.resolution_type = (
                    RecoveryConflictResolution.IGNORE_EXTERNAL_ORDER
                )
            elif res == AdminConflictResolution.PRESERVE_REMOTE_HISTORY:
                check = self.evaluate_preserve_eligibility(row)
                if not check["eligible"]:
                    raise RecoveryConflictError(
                        check["reason_code"] or "not_eligible",
                        check["message"] or "Not eligible",
                    )
                history_result = self._history.upsert_from_conflict(
                    row,
                    actor=actor,
                    import_policy=(
                        AdminConflictResolution.PRESERVE_REMOTE_HISTORY.value
                    ),
                )
                row.review_status = (
                    RecoveryConflictReviewStatus.HISTORICAL_PRESERVED
                )
                row.resolution_type = (
                    RecoveryConflictResolution.PRESERVE_HISTORY
                )
            else:
                raise RecoveryConflictError(
                    "invalid_resolution",
                    f"Cannot execute resolution: {res}",
                )

            row.resolved_by = actor
            row.resolved_at = _utcnow()
            row.resolution_note = reason.strip()[:2000]
            row.updated_at = _utcnow()
            self._session.flush()
            after = {
                "review_status": row.review_status,
                "resolution_type": row.resolution_type,
                "resolved_by": row.resolved_by,
                "resolved_at": (
                    row.resolved_at.isoformat() if row.resolved_at else None
                ),
            }
            processed.append(
                {
                    "conflict_id": int(cid),
                    "before": before,
                    "after": after,
                    "history": history_result,
                }
            )

        return {
            "uba_id": int(uba_id),
            "resolution": res.value,
            "processed": processed,
            "eligible": dry["eligible"],
            "ineligible": [],
            "active_conflict_count": self._conflicts.count_active_for_uba(
                uba_id
            ),
            "db_mutated": True,
            "hard_deleted": False,
        }

    def resolve_one(
        self,
        conflict_id: int,
        *,
        resolution: str,
        reason: str,
        actor: str,
        expected_status: str | None = None,
        execute_enabled: bool = True,
    ) -> dict[str, Any]:
        row = self._conflicts.get(conflict_id)
        if row.user_broker_account_id is None:
            raise RecoveryConflictError(
                "uba_required", "Conflict missing UBA"
            )
        return self.resolve_selected(
            int(row.user_broker_account_id),
            conflict_ids=[int(conflict_id)],
            resolution=resolution,
            reason=reason,
            actor=actor,
            expected_status=expected_status,
            execute_enabled=execute_enabled,
        )

    def build_conflict_summary(self, uba_id: int) -> dict[str, Any]:
        rows = self._conflicts.list_conflicts(
            user_broker_account_id=int(uba_id),
            resolved=False,
            limit=200,
            offset=0,
        )
        by_type: dict[str, int] = {}
        by_status: dict[str, int] = {}
        ignore_candidates = 0
        preserve_needed = 0
        blocked = 0
        items: list[dict[str, Any]] = []
        for row in rows:
            by_type[row.conflict_type] = by_type.get(row.conflict_type, 0) + 1
            by_status[row.review_status] = (
                by_status.get(row.review_status, 0) + 1
            )
            rec = self.classify_recommendation(row)
            if rec["eligible_for_ignore"]:
                ignore_candidates += 1
            elif rec["needs_remote_history_preserve"]:
                preserve_needed += 1
            else:
                blocked += 1
            items.append(
                {
                    "conflict_id": int(row.broker_recovery_conflict_id),
                    "conflict_type": row.conflict_type,
                    "review_status": row.review_status,
                    "external_order_id_masked": row.external_order_id_masked,
                    "market_code": row.market_code,
                    "external_status": row.external_status,
                    "executed_quantity": (
                        str(row.executed_quantity)
                        if row.executed_quantity is not None
                        else None
                    ),
                    "remaining_quantity": (
                        str(row.remaining_quantity)
                        if row.remaining_quantity is not None
                        else None
                    ),
                    "detected_at": (
                        row.detected_at.isoformat()
                        if row.detected_at
                        else None
                    ),
                    **rec,
                }
            )
        return {
            "active_conflict_count": len(rows),
            "ignore_candidates": ignore_candidates,
            "preserve_remote_history_needed": preserve_needed,
            "blocked_count": blocked,
            "by_type": by_type,
            "by_status": by_status,
            "items": items,
        }

    def resume_check(
        self,
        uba_id: int,
        *,
        kill_switch_active: bool = False,
        check_remote_open_orders: bool = True,
    ) -> dict[str, Any]:
        """조회 전용 Resume 가능 여부 — 상태 변경 없음."""

        blockers: list[dict[str, Any]] = []
        uba = self._session.get(UserBrokerAccount, int(uba_id))
        if uba is None:
            return {
                "uba_id": int(uba_id),
                "resumable": False,
                "blockers": [
                    {
                        "code": "UBA_NOT_FOUND",
                        "message": "계좌를 찾을 수 없습니다.",
                    }
                ],
            }

        cred_status = None
        connection = str(getattr(uba, "connection_status", None) or "")
        broker_code = str(getattr(uba, "broker_code", "UPBIT") or "UPBIT")
        try:
            from stock_platform.broker.credential_vault_service import (
                BrokerCredentialVaultService,
            )

            # 읽기 전용: sync/heal 호출 없이 active credential만 조회
            entity = BrokerCredentialVaultService(
                self._session
            ).get_active_entity(int(uba_id))
            cred_status = (
                entity.verification_status if entity is not None else None
            )
            if entity is not None:
                try:
                    BrokerCredentialVaultService(
                        self._session
                    ).assert_live_order_allowed(
                        int(uba_id), broker_code=broker_code
                    )
                except Exception as exc:  # noqa: BLE001
                    blockers.append(
                        {
                            "code": "CREDENTIAL_DECRYPT_BLOCKED",
                            "message": (
                                "Credential 사용 불가: "
                                f"{exc.__class__.__name__}"
                            ),
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            blockers.append(
                {
                    "code": "CREDENTIAL_CHECK_FAILED",
                    "message": (
                        f"Credential 확인 실패: {exc.__class__.__name__}"
                    ),
                }
            )
        if not bool(getattr(uba, "is_active", False)):
            blockers.append(
                {
                    "code": "UBA_INACTIVE",
                    "message": "계좌가 비활성입니다.",
                }
            )
        if str(cred_status or "").upper() != "VERIFIED":
            blockers.append(
                {
                    "code": "CREDENTIAL_NOT_VERIFIED",
                    "message": "Credential이 VERIFIED가 아닙니다.",
                    "credential_status": cred_status,
                }
            )
        if str(connection).upper() != "CONNECTED":
            blockers.append(
                {
                    "code": "CONNECTION_NOT_CONNECTED",
                    "message": "connection_status가 CONNECTED가 아닙니다.",
                    "connection_status": connection,
                }
            )

        active = self._conflicts.count_active_for_uba(uba_id)
        if active > 0:
            blockers.append(
                {
                    "code": "UNRESOLVED_CONFLICTS",
                    "count": active,
                    "message": "미해결 Recovery Conflict가 존재합니다.",
                }
            )

        pending = int(
            self._session.scalar(
                select(func.count())
                .select_from(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.user_broker_account_id
                    == int(uba_id),
                    BrokerRecoveryConflictEntity.review_status
                    == RecoveryConflictReviewStatus.PENDING_REVIEW,
                )
            )
            or 0
        )
        if pending > 0:
            blockers.append(
                {
                    "code": "PENDING_REVIEW_EXISTS",
                    "count": pending,
                    "message": "PENDING_REVIEW Conflict가 존재합니다.",
                }
            )

        state = self._session.scalar(
            select(BrokerRecoveryAccountStateEntity)
            .where(
                BrokerRecoveryAccountStateEntity.user_broker_account_id
                == int(uba_id),
                BrokerRecoveryAccountStateEntity.broker_code
                == str(getattr(uba, "broker_code", "UPBIT") or "UPBIT").upper(),
            )
            .limit(1)
        )
        recovery_status = state.recovery_status if state else None
        trading_paused = bool(state.trading_paused) if state else False
        lock_held = bool(
            state
            and state.lock_holder
            and (
                state.lock_expires_at is None
                or state.lock_expires_at > _utcnow()
            )
        )
        if recovery_status and str(recovery_status).upper() == "RUNNING":
            blockers.append(
                {
                    "code": "RECOVERY_RUNNING",
                    "message": "Recovery가 진행 중입니다.",
                }
            )
        # MANUAL_REVIEW 자체는 Resume로 SUCCESS 전환 대상 — Conflict=0일 때 차단하지 않음
        if (
            recovery_status
            and str(recovery_status).upper() == "MANUAL_REVIEW"
            and active > 0
        ):
            blockers.append(
                {
                    "code": "RECOVERY_MANUAL_REVIEW",
                    "message": (
                        "recovery_status=MANUAL_REVIEW 이며 "
                        "미해결 Conflict가 남아 있습니다."
                    ),
                }
            )
        if lock_held:
            blockers.append(
                {
                    "code": "RECOVERY_LOCK_HELD",
                    "message": "Recovery lock이 존재합니다.",
                    "lock_holder": state.lock_holder if state else None,
                }
            )

        blocking_orders = self._conflicts.count_blocking_orders_for_uba(
            uba_id
        )
        for key, code in (
            ("db_open", "DB_OPEN_ORDERS"),
            ("submission_unknown", "SUBMISSION_UNKNOWN"),
            ("cancel_pending", "CANCEL_PENDING"),
            ("replace_pending", "REPLACE_PENDING"),
        ):
            if blocking_orders.get(key, 0) > 0:
                blockers.append(
                    {
                        "code": code,
                        "count": blocking_orders[key],
                        "message": f"{key} 주문이 남아 있습니다.",
                    }
                )

        # mismatch 유형 활성 Conflict
        for ctype, code in (
            (
                RecoveryConflictType.BALANCE_MISMATCH.value,
                "BALANCE_MISMATCH",
            ),
            (
                RecoveryConflictType.EXECUTION_MISMATCH.value,
                "FILL_MISMATCH",
            ),
            (
                RecoveryConflictType.ORDER_QUANTITY_MISMATCH.value,
                "ORDER_STATUS_MISMATCH",
            ),
            (
                RecoveryConflictType.REMOTE_ORDER_NOT_FOUND_LOCALLY.value,
                "REMOTE_ONLY_UNRESOLVED",
            ),
        ):
            cnt = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(BrokerRecoveryConflictEntity)
                    .where(
                        BrokerRecoveryConflictEntity.user_broker_account_id
                        == int(uba_id),
                        BrokerRecoveryConflictEntity.conflict_type == ctype,
                        BrokerRecoveryConflictEntity.review_status.in_(
                            list(ACTIVE_REVIEW_STATUSES)
                        ),
                    )
                )
                or 0
            )
            if cnt > 0:
                blockers.append(
                    {
                        "code": code,
                        "count": cnt,
                        "message": f"미해결 {ctype} Conflict가 있습니다.",
                    }
                )

        remote_open = None
        if check_remote_open_orders and str(
            getattr(uba, "broker_code", "UPBIT") or "UPBIT"
        ).upper() == "UPBIT":
            try:
                remote_open = self._count_remote_open_orders(int(uba_id))
                if remote_open > 0:
                    blockers.append(
                        {
                            "code": "REMOTE_OPEN_ORDERS",
                            "count": remote_open,
                            "message": "업비트 미체결 주문이 존재합니다.",
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                blockers.append(
                    {
                        "code": "REMOTE_OPEN_CHECK_FAILED",
                        "message": (
                            "원격 미체결 조회 실패: "
                            f"{exc.__class__.__name__}"
                        ),
                    }
                )

        account_paused = False
        try:
            from stock_platform.risk_engine.user_risk_service import (
                UserRiskSettingService,
            )

            snap = UserRiskSettingService(self._session).snapshot_account(
                int(uba_id)
            )
            if isinstance(snap, dict) and snap.get("account_paused"):
                account_paused = True
                blockers.append(
                    {
                        "code": "ACCOUNT_PAUSED",
                        "message": "Risk account_paused=true 입니다.",
                    }
                )
        except Exception:  # noqa: BLE001
            pass

        if kill_switch_active:
            blockers.append(
                {
                    "code": "KILL_SWITCH_ACTIVE",
                    "message": "Kill switch가 활성입니다.",
                }
            )

        balance_sync_ok = uba.last_synced_at is not None
        if not balance_sync_ok:
            blockers.append(
                {
                    "code": "BALANCE_SYNC_MISSING",
                    "message": "마지막 잔고 동기화 기록이 없습니다.",
                }
            )

        # 로컬 주문이 없으면 fill sync는 N/A로 통과, 있으면 blocking 없음이면 OK
        local_order_count = blocking_orders.get("db_open", 0)
        fill_sync_status = (
            "N/A_NO_OPEN_ORDERS"
            if local_order_count == 0
            else "OK"
        )

        # 중복 코드 제거
        seen: set[str] = set()
        uniq_blockers: list[dict[str, Any]] = []
        for b in blockers:
            code = str(b.get("code") or "")
            if code in seen:
                continue
            seen.add(code)
            uniq_blockers.append(b)

        return {
            "uba_id": int(uba_id),
            "resumable": len(uniq_blockers) == 0,
            "credential_status": cred_status,
            "connection_status": connection,
            "trading_paused": trading_paused,
            "recovery_status": recovery_status,
            "active_conflict_count": active,
            "blocking_conflict_count": active,
            "pending_review_count": pending,
            "remote_open_order_count": remote_open,
            "recovery_lock": lock_held,
            "kill_switch": bool(kill_switch_active),
            "account_paused": account_paused,
            "balance_sync_ok": balance_sync_ok,
            "fill_sync_status": fill_sync_status,
            "live": bool(getattr(uba, "live_order_enabled", False)),
            "arm": bool(getattr(uba, "live_armed", False)),
            "is_active": bool(uba.is_active),
            "blocking_orders": blocking_orders,
            "blockers": uniq_blockers,
            "note": (
                "Resume는 LIVE/ARM/Scheduler를 변경하지 않습니다."
            ),
        }

    def _count_remote_open_orders(self, uba_id: int) -> int:
        from stock_platform.broker.credential_adapter_factory import (
            build_upbit_settings_from_vault,
        )
        from stock_platform.broker.credential_vault_service import (
            BrokerCredentialVaultService,
        )
        from stock_platform.broker.upbit.order_client import (
            UpbitOrderRestClient,
        )

        resolved = BrokerCredentialVaultService(
            self._session
        ).resolve_for_runtime(
            uba_id,
            expected_broker="UPBIT",
            require_verified=True,
            touch_last_used=False,
        )
        client = UpbitOrderRestClient(
            settings=build_upbit_settings_from_vault(resolved),
            user_broker_account_id=int(uba_id),
        )
        wait = client.list_orders(state="wait", limit=100)
        watch = client.list_orders(state="watch", limit=100)
        return len(wait) + len(watch)
