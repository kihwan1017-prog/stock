"""Historical test AMBIGUOUS outbox — 승인형 안전 정리.

일반 AMBIGUOUS(intent 후 브로커 결과 불명) retire 게이트는 완화하지 않는다.
payload.test=true + 미전송 증거가 명확한 테스트 fixture만 대상.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.order.entities import (
    OrderSubmissionAttemptEntity,
    TradingOrderEntity,
)
from stock_platform.order.models import OrderStatus
from stock_platform.order.outbox_entities import OrderOutbox
from stock_platform.order.outbox_models import OutboxStatus
from stock_platform.order.repository import TradingOrderRepository

# 이번 STEP 고정 대상 — 다른 row 자동 수정 금지
ALLOWED_OUTBOX_IDS: frozenset[int] = frozenset({205})
ALLOWED_ORDER_IDS: frozenset[int] = frozenset({396})

APPROVAL_PHRASE = "RESOLVE HISTORICAL TEST OUTBOX"
RESOLUTION = "HISTORICAL_TEST_ARTIFACT_NOT_SUBMITTED"
REASON_CODE = "HISTORICAL_TEST_ARTIFACT"
CONFIRMATION_STATUS = "CONFIRMED_ABSENT"
AUDIT_EVENT = "ADMIN_HISTORICAL_TEST_OUTBOX_RESOLVED"
OUTBOX_ERROR_PREFIX = "HISTORICAL_TEST_RESOLVED"

_BROKER_SUBMIT_AUDIT_TYPES = frozenset(
    {
        "BROKER_ORDER_SUBMITTED",
        "UPBIT_ORDER_CREATED",
        "LIVE_ORDER_SUBMITTED",
        "KIWOOM_ORDER_SUBMITTED",
    }
)


class HistoricalTestOutboxResolutionError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        blockers: list[str] | None = None,
        http_status: int = 409,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.blockers = list(blockers or [code])
        self.http_status = int(http_status)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _payload_is_test(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    value = payload.get("test")
    return value is True or value == "true" or value == 1


@dataclass
class HistoricalTestPreview:
    resolvable: bool
    blockers: list[str] = field(default_factory=list)
    fingerprint: str | None = None
    approval_phrase: str = APPROVAL_PHRASE
    resolution: str | None = None
    reason_code: str | None = None
    outbox_id: int | None = None
    order_id: int | None = None
    outbox_status: str | None = None
    order_status: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "resolvable": self.resolvable,
            "blockers": list(self.blockers),
            "fingerprint": self.fingerprint,
            "approval_phrase_required": self.approval_phrase,
            "resolution": self.resolution,
            "reason_code": self.reason_code,
            "outbox_id": self.outbox_id,
            "order_id": self.order_id,
            "outbox_status": self.outbox_status,
            "order_status": self.order_status,
            "evidence": dict(self.evidence),
        }


def _ensure_trading_order_fk_metadata() -> None:
    """flush 시 TradingOrder FK 대상 테이블 mapper 로드 (script/standalone 경로)."""

    from stock_platform.strategy_deployment.definition_entities import (  # noqa: F401
        AccountStrategyLinkEntity,
        StrategyDefinitionEntity,
    )
    from stock_platform.strategy_deployment.entities import (  # noqa: F401
        StrategyDeploymentEntity,
    )
    from stock_platform.trading.account_models import (  # noqa: F401
        UserBrokerAccount,
    )


class HistoricalTestOutboxResolutionService:
    """테스트 fixture AMBIGUOUS → FAILED / order CREATED → FAILED."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._orders = TradingOrderRepository(session)
        _ensure_trading_order_fk_metadata()

    def preview(self, *, outbox_id: int, order_id: int) -> HistoricalTestPreview:
        order, outbox, blockers, evidence = self._evaluate(
            outbox_id=int(outbox_id), order_id=int(order_id)
        )
        if self._is_already_resolved(order, outbox):
            fp_body = self._fingerprint_body(order, outbox, evidence)
            return HistoricalTestPreview(
                resolvable=True,
                blockers=[],
                fingerprint=_fingerprint(fp_body),
                resolution=RESOLUTION,
                reason_code=REASON_CODE,
                outbox_id=int(outbox.outbox_id) if outbox else int(outbox_id),
                order_id=int(order.order_id) if order else int(order_id),
                outbox_status=outbox.status_code if outbox else None,
                order_status=order.status_code if order else None,
                evidence={**evidence, "already_resolved": True},
            )

        fp = None
        if order is not None and outbox is not None and not blockers:
            fp = _fingerprint(self._fingerprint_body(order, outbox, evidence))
        return HistoricalTestPreview(
            resolvable=not blockers and order is not None and outbox is not None,
            blockers=blockers,
            fingerprint=fp,
            resolution=RESOLUTION if not blockers else None,
            reason_code=REASON_CODE if not blockers else None,
            outbox_id=int(outbox.outbox_id) if outbox else int(outbox_id),
            order_id=int(order.order_id) if order else int(order_id),
            outbox_status=outbox.status_code if outbox else None,
            order_status=order.status_code if order else None,
            evidence=evidence,
        )

    def resolve(
        self,
        *,
        outbox_id: int,
        order_id: int,
        approval_phrase: str,
        fingerprint: str,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        phrase = (approval_phrase or "").strip()
        if phrase != APPROVAL_PHRASE:
            raise HistoricalTestOutboxResolutionError(
                "approval_phrase_mismatch",
                f"approval_phrase must be exactly {APPROVAL_PHRASE!r}",
                blockers=["approval_phrase_mismatch"],
                http_status=400,
            )
        reason_clean = (reason or "").strip()
        if not reason_clean:
            raise HistoricalTestOutboxResolutionError(
                "reason_required",
                "reason is required",
                http_status=400,
            )

        order, outbox, blockers, evidence = self._evaluate(
            outbox_id=int(outbox_id), order_id=int(order_id)
        )
        if order is None or outbox is None:
            raise HistoricalTestOutboxResolutionError(
                blockers[0] if blockers else "not_found",
                "outbox/order not found",
                blockers=blockers or ["not_found"],
            )

        if self._is_already_resolved(order, outbox):
            return {
                "ok": True,
                "idempotent": True,
                "code": "ALREADY_RESOLVED",
                "resolution": RESOLUTION,
                "reason_code": REASON_CODE,
                "outbox_id": int(outbox.outbox_id),
                "order_id": int(order.order_id),
                "outbox_status": outbox.status_code,
                "order_status": order.status_code,
                "broker_api_calls": 0,
                "create_order_calls": 0,
            }

        if blockers:
            raise HistoricalTestOutboxResolutionError(
                blockers[0],
                f"resolution blocked: {','.join(blockers)}",
                blockers=blockers,
            )

        expected_fp = _fingerprint(
            self._fingerprint_body(order, outbox, evidence)
        )
        if (fingerprint or "").strip() != expected_fp:
            raise HistoricalTestOutboxResolutionError(
                "fingerprint_mismatch",
                "preview fingerprint mismatch — re-run preview",
                blockers=["fingerprint_mismatch"],
                http_status=409,
            )

        prev_order = order.status_code
        prev_outbox = outbox.status_code

        # CREATED → CANCELLED 는 state machine 미허용 → FAILED terminal
        self._orders.change_status(
            entity=order,
            new_status=OrderStatus.FAILED,
            actor=actor,
            reason_code=REASON_CODE,
            message=f"{RESOLUTION}:{reason_clean[:400]}",
            detail_payload={
                "resolution": RESOLUTION,
                "reason_code": REASON_CODE,
                "outbox_id": int(outbox.outbox_id),
                "payload_test": True,
                "evidence": evidence,
            },
            commit=False,
        )

        outbox.status_code = OutboxStatus.FAILED.value
        outbox.confirmation_status = CONFIRMATION_STATUS
        outbox.confirmation_checked_at = _utcnow()
        outbox.manual_review_reason = (
            f"{REASON_CODE}:test_fixture_not_submitted"
        )[:200]
        outbox.last_error = (
            f"{OUTBOX_ERROR_PREFIX}:{REASON_CODE}:{reason_clean[:300]}"
        )
        outbox.next_retry_at = None
        outbox.locked_at = None
        outbox.locked_by = None
        outbox.lease_expires_at = None
        outbox.processed_at = _utcnow()
        self._session.flush()

        from stock_platform.order.live_safety_audit import (
            emit_live_safety_audit,
        )

        detail = {
            "resolution": RESOLUTION,
            "reason_code": REASON_CODE,
            "outbox_id": int(outbox.outbox_id),
            "order_id": int(order.order_id),
            "payload_test": True,
            "previous_outbox_status": prev_outbox,
            "previous_order_status": prev_order,
            "final_outbox_status": OutboxStatus.FAILED.value,
            "final_order_status": OrderStatus.FAILED.value,
            "confirmation_status": CONFIRMATION_STATUS,
            "evidence": evidence,
            "admin_reason": reason_clean[:2000],
            "actor": actor,
            "fingerprint": expected_fp,
            "broker_api_calls": 0,
            "create_order_calls": 0,
            "resolved_at": _utcnow().isoformat(),
        }
        emit_live_safety_audit(
            self._session,
            event_type=AUDIT_EVENT,
            actor=actor,
            run_id=None,
            user_id=None,
            account_id=None,
            strategy_id=None,
            symbol=str(order.symbol),
            order_id=int(order.order_id),
            client_order_id=str(order.client_order_id),
            detail=detail,
            commit=False,
        )
        self._session.flush()

        return {
            "ok": True,
            "idempotent": False,
            "code": "RESOLVED",
            "resolution": RESOLUTION,
            "reason_code": REASON_CODE,
            "outbox_id": int(outbox.outbox_id),
            "order_id": int(order.order_id),
            "previous_outbox_status": prev_outbox,
            "previous_order_status": prev_order,
            "outbox_status": OutboxStatus.FAILED.value,
            "order_status": OrderStatus.FAILED.value,
            "confirmation_status": CONFIRMATION_STATUS,
            "fingerprint": expected_fp,
            "evidence": evidence,
            "broker_api_calls": 0,
            "create_order_calls": 0,
        }

    def _fingerprint_body(
        self,
        order: TradingOrderEntity,
        outbox: OrderOutbox,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "outbox_id": int(outbox.outbox_id),
            "order_id": int(order.order_id),
            "outbox_status": outbox.status_code,
            "order_status": order.status_code,
            "payload_test": True,
            "broker_order_id": order.broker_order_id,
            "submission_attempt_count": int(
                order.submission_attempt_count or 0
            ),
            "user_broker_account_id": order.user_broker_account_id,
            "idempotency_key": outbox.idempotency_key,
            "request_hash": outbox.request_hash,
            "evidence": {
                "attempt_rows": evidence.get("attempt_rows"),
                "broker_submit_audit_count": evidence.get(
                    "broker_submit_audit_count"
                ),
                "fill_quantity": evidence.get("fill_quantity"),
            },
        }

    def _is_already_resolved(
        self,
        order: TradingOrderEntity | None,
        outbox: OrderOutbox | None,
    ) -> bool:
        if order is None or outbox is None:
            return False
        if outbox.status_code != OutboxStatus.FAILED.value:
            return False
        if outbox.confirmation_status != CONFIRMATION_STATUS:
            return False
        err = str(outbox.last_error or "")
        if OUTBOX_ERROR_PREFIX not in err and REASON_CODE not in err:
            return False
        return order.status_code in {
            OrderStatus.FAILED.value,
            OrderStatus.CANCELLED.value,
        }

    def _evaluate(
        self, *, outbox_id: int, order_id: int
    ) -> tuple[
        TradingOrderEntity | None,
        OrderOutbox | None,
        list[str],
        dict[str, Any],
    ]:
        blockers: list[str] = []
        evidence: dict[str, Any] = {
            "allowlist_outbox_ids": sorted(ALLOWED_OUTBOX_IDS),
            "allowlist_order_ids": sorted(ALLOWED_ORDER_IDS),
        }

        if int(outbox_id) not in ALLOWED_OUTBOX_IDS:
            blockers.append("outbox_not_allowlisted")
        if int(order_id) not in ALLOWED_ORDER_IDS:
            blockers.append("order_not_allowlisted")

        outbox = self._session.get(OrderOutbox, int(outbox_id))
        order = self._session.get(TradingOrderEntity, int(order_id))
        if outbox is None:
            blockers.append("outbox_not_found")
        if order is None:
            blockers.append("order_not_found")
        if outbox is None or order is None:
            return order, outbox, blockers, evidence

        evidence.update(
            {
                "payload_json": outbox.payload_json,
                "event_type": outbox.event_type,
                "idempotency_key": outbox.idempotency_key,
                "client_order_id": order.client_order_id,
                "broker_code_order": order.broker_code,
                "broker_code_outbox": outbox.broker_code,
                "account_id": order.account_id,
                "user_broker_account_id": order.user_broker_account_id,
                "strategy_id": order.strategy_id,
                "strategy_deployment_id": order.strategy_deployment_id,
                "account_strategy_link_id": order.account_strategy_link_id,
                "runtime_scope_hash": order.runtime_scope_hash,
                "dispatch_intent_at": (
                    outbox.dispatch_intent_at.isoformat()
                    if outbox.dispatch_intent_at
                    else None
                ),
                "last_error": outbox.last_error,
            }
        )

        if int(outbox.order_id) != int(order.order_id):
            blockers.append("outbox_order_mismatch")
        if outbox.status_code not in {
            OutboxStatus.AMBIGUOUS.value,
            OutboxStatus.FAILED.value,
        }:
            blockers.append("outbox_status_not_ambiguous")
        if order.status_code not in {
            OrderStatus.CREATED.value,
            OrderStatus.FAILED.value,
            OrderStatus.CANCELLED.value,
        }:
            blockers.append("order_status_not_created_or_terminal")

        if not _payload_is_test(outbox.payload_json):
            blockers.append("payload_test_not_true")

        if order.broker_order_id:
            blockers.append("broker_order_id_present")
        if outbox.client_order_id:
            blockers.append("outbox_client_order_id_present")

        attempt_count = int(order.submission_attempt_count or 0)
        attempt_rows = int(
            self._session.scalar(
                select(func.count())
                .select_from(OrderSubmissionAttemptEntity)
                .where(
                    OrderSubmissionAttemptEntity.order_id == int(order.order_id)
                )
            )
            or 0
        )
        evidence["submission_attempt_count"] = attempt_count
        evidence["attempt_rows"] = attempt_rows
        if attempt_count > 0 or attempt_rows > 0:
            blockers.append("submission_attempt_present")

        if order.first_submitted_at is not None:
            blockers.append("first_submitted_at_present")
        if order.sent_at is not None or order.accepted_at is not None:
            blockers.append("sent_or_accepted_present")

        fill_qty = float(order.filled_quantity or 0)
        evidence["fill_quantity"] = fill_qty
        if fill_qty > 0 or order.filled_at is not None:
            blockers.append("fill_or_execution_present")

        if order.user_broker_account_id is not None:
            blockers.append("production_uba_binding")
        if outbox.user_broker_account_id is not None:
            blockers.append("outbox_uba_binding")
        if order.strategy_id is not None or order.strategy_deployment_id is not None:
            blockers.append("strategy_binding_present")
        if order.account_strategy_link_id is not None:
            blockers.append("link_binding_present")
        if order.runtime_scope_hash:
            blockers.append("runtime_scope_present")

        # 테스트 race fixture 표식 (idempotency/client_order_id)
        cid = str(order.client_order_id or "")
        ikey = str(outbox.idempotency_key or "")
        evidence["race_marker"] = cid.startswith("race-") or ikey.startswith(
            "race-"
        )
        if not evidence["race_marker"]:
            blockers.append("race_fixture_marker_missing")

        broker_submit_audits = self._count_broker_submit_audits(
            order_id=int(order.order_id), outbox_id=int(outbox.outbox_id)
        )
        evidence["broker_submit_audit_count"] = broker_submit_audits
        if broker_submit_audits > 0:
            blockers.append("broker_submit_audit_present")

        # 이미 해석된 경우는 blocker로 두지 않음 (idempotent 경로)
        if self._is_already_resolved(order, outbox):
            blockers = [
                b
                for b in blockers
                if b
                not in {
                    "outbox_status_not_ambiguous",
                    "order_status_not_created_or_terminal",
                }
            ]

        # 중복 제거·안정 정렬
        blockers = sorted(set(blockers))
        return order, outbox, blockers, evidence

    def _count_broker_submit_audits(
        self, *, order_id: int, outbox_id: int
    ) -> int:
        try:
            from stock_platform.operation.audit_models import AuditEvent

            by_order = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.order_id == int(order_id),
                        AuditEvent.event_type.in_(
                            list(_BROKER_SUBMIT_AUDIT_TYPES)
                        ),
                    )
                )
                or 0
            )
            # order_id 없는 outbox 연계 이벤트는 text 검색으로 보수적 확인
            rows = list(
                self._session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.event_type.in_(
                            list(_BROKER_SUBMIT_AUDIT_TYPES)
                        )
                    ).limit(500)
                )
            )
            by_outbox = 0
            needle = f'"outbox_id": {int(outbox_id)}'
            needle2 = f'"outbox_id":{int(outbox_id)}'
            for row in rows:
                detail = row.detail if isinstance(row.detail, dict) else {}
                raw = json.dumps(detail, ensure_ascii=False)
                if needle in raw or needle2 in raw:
                    by_outbox += 1
            return by_order + by_outbox
        except Exception:
            return 0
