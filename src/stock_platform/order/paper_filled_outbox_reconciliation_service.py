"""PAPER 체결완료 잔존 Outbox — 승인형 안전 정리 (CLASS_B).

배경(MINIPC-PAPER-OUTBOX-RECON-01/02 감사):
linked order가 이미 FILLED(PAPER, 체결수량=주문수량 정확 일치)로 완결되었으나,
SUBMIT_ORDER outbox만 PENDING으로 잔존한 3건. `unsubmitted_live_order_retire_service`는
order.status==PENDING만 대상으로 하므로 FILLED 주문에는 적용되지 않는다(설계상 정상).
`historical_test_outbox_resolution_service`는 payload.test=true 전용이라 실제 체결
주문에는 적용되지 않는다(fill_or_execution_present 블로커).

이 서비스는 위 두 서비스가 다루지 않는 정확히 그 간극 — "주문은 이미 성공적으로
종결됐지만 outbox만 뒤에 남은 PAPER 케이스" — 만을, 명시적 allowlist + approval
phrase 하에서 outbox만 DONE으로 정리한다.

Terminal status로 DONE을 선택한 근거: OutboxStatus.DONE은 "이 outbox가 담당한
작업(주문 제출)의 목적이 달성되어 더 이상 조치가 필요 없음"을 뜻한다. 본 3건은
주문이 FILLED(수량 정확 일치)로 실제 완결되었으므로 outbox가 지향하던 최종
결과(성공적 주문 처리)에 이미 도달한 상태다. FAILED는 "제출이 좌절/포기됨"을
뜻해 이미 성공한 주문에 쓰면 사실과 반대로 기록되므로 사용하지 않는다.
AMBIGUOUS/MANUAL_REVIEW는 "미해결"을 뜻하므로 이미 해소된 이 케이스에는
부적합하다. RETRY/PROCESSING/PENDING은 non-terminal이라 목적에 맞지 않는다.

브로커 API 호출 없음. order/execution/position은 절대 변경하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
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

# 이번 STEP 고정 대상 — 다른 row 자동 수정 금지 (MINIPC-PAPER-OUTBOX-RECON-CODE-02)
ALLOWED_OUTBOX_IDS: frozenset[int] = frozenset({1138, 1139, 1140})
ALLOWED_ORDER_IDS: frozenset[int] = frozenset({1701, 1702, 1703})
_ALLOWED_PAIRS: frozenset[tuple[int, int]] = frozenset(
    {
        (1138, 1701),
        (1139, 1702),
        (1140, 1703),
    }
)

APPROVAL_PHRASE = "RESOLVE PAPER FILLED OUTBOX"
RESOLUTION = "PAPER_FILLED_OUTBOX_ORPHANED"
REASON_CODE = "PAPER_ORDER_ALREADY_FILLED"
CONFIRMATION_STATUS = "CONFIRMED_FILLED_OUT_OF_BAND"
AUDIT_EVENT = "ADMIN_PAPER_FILLED_OUTBOX_RESOLVED"
OUTBOX_NOTE_PREFIX = "PAPER_FILLED_OUTBOX_RESOLVED"

_BROKER_SUBMIT_AUDIT_TYPES = frozenset(
    {
        "BROKER_ORDER_SUBMITTED",
        "UPBIT_ORDER_CREATED",
        "LIVE_ORDER_SUBMITTED",
        "KIWOOM_ORDER_SUBMITTED",
        "OUTBOX_DISPATCHED",
    }
)


class PaperFilledOutboxReconciliationError(Exception):
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
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _resolve_environment(
    order: TradingOrderEntity, outbox: OrderOutbox | None
) -> str:
    meta = dict(getattr(order, "metadata_payload", None) or {})
    env = str(meta.get("environment") or "").upper()
    if env:
        return env
    if outbox is not None:
        payload = dict(getattr(outbox, "payload_json", None) or {})
        env = str(payload.get("environment") or "").upper()
        if env:
            return env
    return ""


@dataclass
class PaperFilledOutboxPreview:
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
    environment: str | None = None
    broker_code: str | None = None
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
            "environment": self.environment,
            "broker_code": self.broker_code,
            "evidence": dict(self.evidence),
        }


class PaperFilledOutboxReconciliationService:
    """PAPER 체결완료 잔존 outbox(PENDING) → DONE 정리. order/execution 불변."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def preview(
        self, *, outbox_id: int, order_id: int
    ) -> PaperFilledOutboxPreview:
        order, outbox, blockers, evidence = self._evaluate(
            outbox_id=int(outbox_id), order_id=int(order_id)
        )
        if self._is_already_resolved(order, outbox):
            fp_body = self._fingerprint_body(order, outbox, evidence)
            return PaperFilledOutboxPreview(
                resolvable=True,
                blockers=[],
                fingerprint=_fingerprint(fp_body),
                resolution=RESOLUTION,
                reason_code=REASON_CODE,
                outbox_id=int(outbox.outbox_id) if outbox else int(outbox_id),
                order_id=int(order.order_id) if order else int(order_id),
                outbox_status=outbox.status_code if outbox else None,
                order_status=order.status_code if order else None,
                environment=(
                    _resolve_environment(order, outbox) if order else None
                ),
                broker_code=str(order.broker_code) if order else None,
                evidence={**evidence, "already_resolved": True},
            )

        fp = None
        if order is not None and outbox is not None and not blockers:
            fp = _fingerprint(self._fingerprint_body(order, outbox, evidence))
        return PaperFilledOutboxPreview(
            resolvable=not blockers and order is not None and outbox is not None,
            blockers=blockers,
            fingerprint=fp,
            resolution=RESOLUTION if not blockers else None,
            reason_code=REASON_CODE if not blockers else None,
            outbox_id=int(outbox.outbox_id) if outbox else int(outbox_id),
            order_id=int(order.order_id) if order else int(order_id),
            outbox_status=outbox.status_code if outbox else None,
            order_status=order.status_code if order else None,
            environment=_resolve_environment(order, outbox) if order else None,
            broker_code=str(order.broker_code) if order else None,
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
            raise PaperFilledOutboxReconciliationError(
                "approval_phrase_mismatch",
                f"approval_phrase must be exactly {APPROVAL_PHRASE!r}",
                blockers=["approval_phrase_mismatch"],
                http_status=400,
            )
        reason_clean = (reason or "").strip()
        if not reason_clean:
            raise PaperFilledOutboxReconciliationError(
                "reason_required",
                "reason is required",
                http_status=400,
            )

        order, outbox, blockers, evidence = self._evaluate(
            outbox_id=int(outbox_id), order_id=int(order_id)
        )
        if order is None or outbox is None:
            raise PaperFilledOutboxReconciliationError(
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
            }

        if blockers:
            raise PaperFilledOutboxReconciliationError(
                blockers[0],
                f"resolution blocked: {','.join(blockers)}",
                blockers=blockers,
            )

        expected_fp = _fingerprint(
            self._fingerprint_body(order, outbox, evidence)
        )
        if (fingerprint or "").strip() != expected_fp:
            raise PaperFilledOutboxReconciliationError(
                "fingerprint_mismatch",
                "preview fingerprint mismatch — re-run preview",
                blockers=["fingerprint_mismatch"],
                http_status=409,
            )

        prev_outbox = outbox.status_code
        prev_order = order.status_code  # 기록용 — 이 서비스는 order를 변경하지 않음

        # order/execution/position 절대 변경 없음 — outbox만 전이
        outbox.status_code = OutboxStatus.DONE.value
        outbox.confirmation_status = CONFIRMATION_STATUS
        outbox.confirmation_checked_at = _utcnow()
        outbox.last_error = (
            f"{OUTBOX_NOTE_PREFIX}:{REASON_CODE}:{reason_clean[:300]}"
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
            "previous_outbox_status": prev_outbox,
            "order_status_unchanged": prev_order,
            "final_outbox_status": OutboxStatus.DONE.value,
            "confirmation_status": CONFIRMATION_STATUS,
            "evidence": evidence,
            "admin_reason": reason_clean[:2000],
            "actor": actor,
            "fingerprint": expected_fp,
            "broker_api_calls": 0,
            "order_execution_position_modified": False,
            "resolved_at": _utcnow().isoformat(),
        }
        emit_live_safety_audit(
            self._session,
            event_type=AUDIT_EVENT,
            actor=actor,
            run_id=None,
            user_id=None,
            account_id=(
                int(order.account_id) if order.account_id is not None else None
            ),
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
            "order_status": prev_order,
            "outbox_status": OutboxStatus.DONE.value,
            "confirmation_status": CONFIRMATION_STATUS,
            "fingerprint": expected_fp,
            "broker_api_calls": 0,
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
            "broker_order_id": order.broker_order_id,
            "filled_quantity": str(order.filled_quantity),
            "order_quantity": str(order.order_quantity),
            "evidence": {
                "attempt_rows_present": evidence.get("attempt_rows_present"),
                "broker_submit_audit_count": evidence.get(
                    "broker_submit_audit_count"
                ),
            },
        }

    def _is_already_resolved(
        self,
        order: TradingOrderEntity | None,
        outbox: OrderOutbox | None,
    ) -> bool:
        if order is None or outbox is None:
            return False
        if outbox.status_code != OutboxStatus.DONE.value:
            return False
        if outbox.confirmation_status != CONFIRMATION_STATUS:
            return False
        err = str(outbox.last_error or "")
        if OUTBOX_NOTE_PREFIX not in err and REASON_CODE not in err:
            return False
        return order.status_code == OrderStatus.FILLED.value

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
        if (int(outbox_id), int(order_id)) not in _ALLOWED_PAIRS:
            blockers.append("pair_not_allowlisted")

        outbox = self._session.get(OrderOutbox, int(outbox_id))
        order = self._session.get(TradingOrderEntity, int(order_id))
        if outbox is None:
            blockers.append("outbox_not_found")
        if order is None:
            blockers.append("order_not_found")
        if outbox is None or order is None:
            return order, outbox, blockers, evidence

        if int(outbox.order_id) != int(order.order_id):
            blockers.append("outbox_order_mismatch")

        env = _resolve_environment(order, outbox)
        evidence["environment"] = env
        if env != "PAPER":
            blockers.append("environment_not_paper")

        order_broker = str(order.broker_code or "").upper()
        outbox_broker = str(outbox.broker_code or "").upper()
        if order_broker != "PAPER":
            blockers.append("order_broker_not_paper")
        if outbox_broker != "PAPER":
            blockers.append("outbox_broker_not_paper")

        # 이미 해석된 경우는 terminal 상태 블로커를 idempotent 경로에서 제외
        if not self._is_already_resolved(order, outbox):
            if outbox.status_code != OutboxStatus.PENDING.value:
                blockers.append("outbox_not_pending")
            if order.status_code != OrderStatus.FILLED.value:
                blockers.append("order_not_filled")

        if order.broker_order_id not in (None, ""):
            blockers.append("broker_order_id_present")

        fill_qty = order.filled_quantity
        order_qty = order.order_quantity
        evidence["filled_quantity"] = str(fill_qty)
        evidence["order_quantity"] = str(order_qty)
        try:
            qty_match = fill_qty is not None and order_qty is not None and (
                Decimal(str(fill_qty)) == Decimal(str(order_qty))
            )
        except Exception:  # noqa: BLE001
            qty_match = False
        evidence["fill_quantity_matches_order_quantity"] = qty_match
        if not qty_match:
            blockers.append("fill_quantity_mismatch")
        if fill_qty is None or Decimal(str(fill_qty)) <= 0:
            blockers.append("no_fill_evidence")

        attempt_count = int(getattr(order, "submission_attempt_count", 0) or 0)
        attempt_row_found = (
            self._session.scalar(
                select(OrderSubmissionAttemptEntity.attempt_id)
                .where(
                    OrderSubmissionAttemptEntity.order_id == int(order.order_id)
                )
                .limit(1)
            )
            is not None
        )
        evidence["submission_attempt_count"] = attempt_count
        evidence["attempt_rows_present"] = attempt_row_found
        if attempt_count > 0:
            blockers.append("submission_attempt_not_zero")
        if attempt_row_found:
            blockers.append("submission_attempt_row_exists")

        if outbox.dispatch_intent_at is not None:
            blockers.append("dispatch_intent_present")
        if outbox.locked_at is not None or outbox.locked_by:
            blockers.append("outbox_claimed")
        if outbox.processed_at is not None:
            blockers.append("outbox_processed")

        broker_submit_audits = self._count_broker_submit_audits(
            order_id=int(order.order_id)
        )
        evidence["broker_submit_audit_count"] = broker_submit_audits
        if broker_submit_audits > 0:
            blockers.append("broker_submit_audit_present")

        blockers = sorted(set(blockers))
        return order, outbox, blockers, evidence

    def _count_broker_submit_audits(self, *, order_id: int) -> int:
        try:
            from stock_platform.operation.audit_models import AuditEvent

            return int(
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
        except Exception:  # noqa: BLE001
            return 0
