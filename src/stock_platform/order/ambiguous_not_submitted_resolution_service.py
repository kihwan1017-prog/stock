"""AMBIGUOUS Outbox — CONFIRMED_NOT_SUBMITTED 관리자 resolution.

일반 미전송 retire 게이트는 완화하지 않는다.
브로커 미전송이 시스템적으로 증명된 경우에만 retire lifecycle을 적용한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.order.entities import (
    OrderSubmissionAttemptEntity,
    TradingOrderEntity,
)
from stock_platform.order.models import (
    TERMINAL_ORDER_STATUSES,
    OrderStatus,
)
from stock_platform.order.outbox_entities import OrderOutbox
from stock_platform.order.outbox_models import (
    OutboxEventType,
    OutboxStatus,
)
from stock_platform.order.repository import TradingOrderRepository
from stock_platform.order.unsubmitted_live_order_retire_service import (
    OUTBOX_ERROR,
    REASON_CODE,
    UnsubmittedLiveOrderRetireService,
)

RESOLUTION = "CONFIRMED_NOT_SUBMITTED"
REASON_CODE_RESOLUTION = "BROKER_NOT_REACHED_LOCAL_VALIDATION_FAILURE"
AUDIT_RESOLUTION = "AMBIGUOUS_CONFIRMED_NOT_SUBMITTED"
ADMIN_AUDIT = "ADMIN_AMBIGUOUS_NOT_SUBMITTED_RESOLVED"

# Audit — 브로커 실전송 흔적 (사용자 필수 조건)
_BROKER_SUBMIT_AUDIT_TYPES = frozenset(
    {
        "BROKER_ORDER_SUBMITTED",
        "UPBIT_ORDER_CREATED",
    }
)

# intent 이후라도 HTTP 이전 deterministic 로컬 실패 증거
_LOCAL_PRE_SEND_MARKERS = (
    "upbit minimum order amount",
    "minimum order amount is",
    "validate_upbit_notional",
)


class AmbiguousNotSubmittedResolutionError(Exception):
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


@dataclass
class ResolutionPreview:
    resolvable: bool
    blockers: list[str] = field(default_factory=list)
    resolution: str | None = None
    reason_code: str | None = None
    order_id: int | None = None
    outbox_id: int | None = None
    run_id: str | None = None
    user_broker_account_id: int | None = None
    broker_code: str | None = None
    outbox_status: str | None = None
    order_status: str | None = None
    identifier: str | None = None
    local_failure_evidence: str | None = None
    broker_lookup_required: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "resolvable": self.resolvable,
            "blockers": list(self.blockers),
            "resolution": self.resolution,
            "reason_code": self.reason_code,
            "order_id": self.order_id,
            "outbox_id": self.outbox_id,
            "run_id": self.run_id,
            "user_broker_account_id": self.user_broker_account_id,
            "broker_code": self.broker_code,
            "outbox_status": self.outbox_status,
            "order_status": self.order_status,
            "identifier": self.identifier,
            "local_failure_evidence": self.local_failure_evidence,
            "broker_lookup_required": self.broker_lookup_required,
        }


class AmbiguousNotSubmittedResolutionService:
    """AMBIGUOUS + pre-send local failure → CONFIRMED_NOT_SUBMITTED → retire."""

    def __init__(
        self,
        session: Session,
        *,
        upbit_order_lookup: Callable[[str], dict[str, Any] | None]
        | None = None,
    ) -> None:
        self._session = session
        self._orders = TradingOrderRepository(session)
        self._upbit_order_lookup = upbit_order_lookup

    def preview(self, order_id: int) -> ResolutionPreview:
        order, outbox, blockers, evidence = self._evaluate_local(
            int(order_id)
        )
        return self._build_preview(order, outbox, blockers, evidence)

    def resolve_and_retire(
        self,
        order_id: int,
        *,
        reason: str,
        actor: str,
        skip_broker_lookup: bool = False,
    ) -> dict[str, Any]:
        """서버 재검증 → CONFIRMED_NOT_SUBMITTED → 내부 retire.

        skip_broker_lookup: 테스트 전용. 운영 API는 False.
        """

        reason_clean = (reason or "").strip()
        if not reason_clean:
            raise AmbiguousNotSubmittedResolutionError(
                "reason_required",
                "reason is required",
            )
        if len(reason_clean) > 2000:
            raise AmbiguousNotSubmittedResolutionError(
                "reason_too_long",
                "reason must be <= 2000 characters",
            )

        order, outbox, blockers, evidence = self._evaluate_local(
            int(order_id)
        )
        if self._is_already_resolved(order, outbox):
            synced = UnsubmittedLiveOrderRetireService(
                self._session
            )._sync_linked_validation_runs(
                order_id=int(order.order_id),  # type: ignore[union-attr]
                actor=actor,
                reason=reason_clean,
            )
            self._consume_grants(order_id=int(order.order_id), actor=actor)  # type: ignore[union-attr]
            return {
                "ok": True,
                "idempotent": True,
                "resolution": RESOLUTION,
                "reason_code": REASON_CODE_RESOLUTION,
                "order_id": int(order.order_id),  # type: ignore[union-attr]
                "outbox_id": int(outbox.outbox_id),  # type: ignore[union-attr]
                "order_status": order.status_code,  # type: ignore[union-attr]
                "outbox_status": outbox.status_code,  # type: ignore[union-attr]
                "synced_run_ids": synced,
                "broker_api_calls": 0,
                "create_order_calls": 0,
            }

        if blockers:
            raise AmbiguousNotSubmittedResolutionError(
                blockers[0],
                f"resolution blocked: {','.join(blockers)}",
                blockers=blockers,
            )

        assert order is not None and outbox is not None
        identifier = self._resolve_identifier(order, outbox)
        if not identifier:
            raise AmbiguousNotSubmittedResolutionError(
                "identifier_missing",
                "Upbit client_order_identifier required for broker proof",
                blockers=["identifier_missing"],
            )

        broker_lookup: dict[str, Any]
        if skip_broker_lookup:
            broker_lookup = {
                "status": "SKIPPED_TEST",
                "found": False,
                "identifier": identifier,
            }
        else:
            broker_lookup = self._verify_upbit_not_found(
                identifier, order_id=int(order.order_id)
            )

        # retire lifecycle (AMBIGUOUS 허용 — regular retire와 분리)
        prev_order = order.status_code
        prev_outbox = outbox.status_code
        uba_id = (
            int(order.user_broker_account_id)
            if order.user_broker_account_id is not None
            else None
        )
        run_ids = self._linked_run_ids(int(order.order_id))

        self._orders.change_status(
            entity=order,
            new_status=OrderStatus.CANCELLED,
            actor=actor,
            reason_code=REASON_CODE,
            message=f"{REASON_CODE_RESOLUTION}:{reason_clean[:400]}",
            detail_payload={
                "resolution": RESOLUTION,
                "reason_code": REASON_CODE_RESOLUTION,
                "outbox_id": int(outbox.outbox_id),
                "broker_order_id": None,
                "identifier": identifier,
                "local_failure_evidence": evidence,
                "broker_lookup": broker_lookup,
            },
            commit=False,
        )
        outbox.status_code = OutboxStatus.FAILED.value
        outbox.last_error = (
            f"{OUTBOX_ERROR}:{REASON_CODE_RESOLUTION}:{reason_clean[:350]}"
        )
        outbox.next_retry_at = None
        outbox.locked_at = None
        outbox.locked_by = None
        outbox.lease_expires_at = None
        outbox.confirmation_status = "CONFIRMED_ABSENT"
        outbox.ambiguous_at = outbox.ambiguous_at or datetime.now(
            timezone.utc
        )
        outbox.processed_at = datetime.now(timezone.utc)
        self._session.flush()

        synced = UnsubmittedLiveOrderRetireService(
            self._session
        )._sync_linked_validation_runs(
            order_id=int(order.order_id),
            actor=actor,
            reason=reason_clean,
        )
        self._consume_grants(order_id=int(order.order_id), actor=actor)

        from stock_platform.order.live_safety_audit import (
            emit_live_safety_audit,
        )

        detail = {
            "resolution": RESOLUTION,
            "reason_code": REASON_CODE_RESOLUTION,
            "order_id": int(order.order_id),
            "outbox_id": int(outbox.outbox_id),
            "run_ids": run_ids,
            "synced_run_ids": synced,
            "user_broker_account_id": uba_id,
            "identifier": identifier,
            "local_failure_evidence": evidence,
            "broker_lookup": broker_lookup,
            "previous_order_status": prev_order,
            "previous_outbox_status": prev_outbox,
            "admin_reason": reason_clean[:2000],
            "broker_order_id": None,
            "submission_attempt_count": 0,
            "broker_api_calls": 0,
            "create_order_calls": 0,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
        }
        emit_live_safety_audit(
            self._session,
            event_type=AUDIT_RESOLUTION,
            actor=actor,
            run_id=(synced[0] if synced else (run_ids[0] if run_ids else None)),
            user_id=None,
            account_id=uba_id,
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
            "resolution": RESOLUTION,
            "reason_code": REASON_CODE_RESOLUTION,
            "order_id": int(order.order_id),
            "outbox_id": int(outbox.outbox_id),
            "user_broker_account_id": uba_id,
            "order_status": OrderStatus.CANCELLED.value,
            "outbox_status": OutboxStatus.FAILED.value,
            "previous_order_status": prev_order,
            "previous_outbox_status": prev_outbox,
            "identifier": identifier,
            "local_failure_evidence": evidence,
            "broker_lookup": broker_lookup,
            "synced_run_ids": synced,
            "broker_api_calls": 0,
            "create_order_calls": 0,
        }

    def _verify_upbit_not_found(
        self,
        identifier: str,
        *,
        order_id: int | None = None,
    ) -> dict[str, Any]:
        from stock_platform.broker.upbit.exceptions import (
            UpbitOrderNotFoundError,
            UpbitError,
            UpbitNetworkError,
            UpbitTemporaryUnavailableError,
            UpbitAuthenticationError,
            UpbitRateLimitError,
        )

        if self._upbit_order_lookup is not None:
            lookup = self._upbit_order_lookup
        else:

            def lookup(ident: str) -> dict[str, Any] | None:
                return self._default_upbit_lookup(
                    ident, order_id=order_id
                )

        try:
            found = lookup(identifier)
        except UpbitOrderNotFoundError:
            return {
                "status": "NOT_FOUND",
                "found": False,
                "identifier": identifier,
            }
        except (
            UpbitNetworkError,
            UpbitTemporaryUnavailableError,
            UpbitRateLimitError,
            UpbitAuthenticationError,
            UpbitError,
            TimeoutError,
            OSError,
        ) as exc:
            raise AmbiguousNotSubmittedResolutionError(
                "STILL_AMBIGUOUS",
                f"broker lookup inconclusive: {type(exc).__name__}",
                blockers=["broker_lookup_inconclusive", "STILL_AMBIGUOUS"],
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise AmbiguousNotSubmittedResolutionError(
                "STILL_AMBIGUOUS",
                f"broker lookup failed: {type(exc).__name__}",
                blockers=["broker_lookup_error", "STILL_AMBIGUOUS"],
            ) from exc

        # None = 주입 lookup이 명시적 부재 신호 (테스트). 운영은 NotFound 예외.
        if found is None:
            return {
                "status": "NOT_FOUND",
                "found": False,
                "identifier": identifier,
            }
        if isinstance(found, dict) and found.get("uuid"):
            raise AmbiguousNotSubmittedResolutionError(
                "broker_order_found",
                "Upbit order exists — cannot confirm not-submitted",
                blockers=["broker_order_found"],
            )
        # uuid 없는 dict는 '없음' 증명으로 취급하지 않음 (Fail Closed)
        raise AmbiguousNotSubmittedResolutionError(
            "STILL_AMBIGUOUS",
            "broker lookup returned unexpected payload",
            blockers=["broker_lookup_unexpected", "STILL_AMBIGUOUS"],
        )

    def _default_upbit_lookup(
        self,
        identifier: str,
        *,
        order_id: int | None = None,
    ) -> dict[str, Any] | None:
        """READ-ONLY GET /v1/order — POST 금지. last_used touch 금지."""

        from stock_platform.broker.credential_adapter_factory import (
            build_upbit_settings_from_vault,
        )
        from stock_platform.broker.credential_vault_service import (
            BrokerCredentialVaultService,
        )
        from stock_platform.broker.upbit.exceptions import (
            UpbitOrderNotFoundError,
        )
        from stock_platform.broker.upbit.order_client import (
            UpbitOrderRestClient,
        )

        order = None
        if order_id is not None:
            order = self._orders.get(int(order_id))
        if order is None:
            order = self._session.scalar(
                select(TradingOrderEntity).where(
                    TradingOrderEntity.client_order_identifier
                    == identifier
                )
            )
        if order is None or order.user_broker_account_id is None:
            raise AmbiguousNotSubmittedResolutionError(
                "identifier_uba_missing",
                "cannot resolve UBA for Upbit lookup",
            )
        uba_id = int(order.user_broker_account_id)
        resolved = BrokerCredentialVaultService(
            self._session
        ).resolve_for_runtime(
            uba_id,
            expected_broker="UPBIT",
            require_verified=True,
            touch_last_used=False,
        )
        settings = build_upbit_settings_from_vault(resolved)
        client = UpbitOrderRestClient(
            settings=settings,
            user_broker_account_id=uba_id,
        )
        try:
            return client.get_order(identifier=identifier)
        except UpbitOrderNotFoundError:
            raise
        finally:
            client.close()

    def _evaluate_local(
        self, order_id: int
    ) -> tuple[
        TradingOrderEntity | None,
        OrderOutbox | None,
        list[str],
        str | None,
    ]:
        blockers: list[str] = []
        evidence: str | None = None
        order = self._orders.get(order_id)
        if order is None:
            return None, None, ["order_not_found"], None

        outbox = self._find_submit_outbox(int(order.order_id))
        broker = str(order.broker_code or "").upper()

        try:
            status = OrderStatus(str(order.status_code))
        except ValueError:
            status = None
            blockers.append("invalid_order_status")

        if status in TERMINAL_ORDER_STATUSES:
            blockers.append("order_already_terminal")
        if status is not None and status != OrderStatus.PENDING:
            if "order_already_terminal" not in blockers:
                blockers.append("order_not_pending")

        if broker != "UPBIT":
            blockers.append("broker_not_upbit")

        env = self._resolve_environment(order, outbox)
        if env != "LIVE":
            blockers.append("environment_not_live")

        if order.broker_order_id not in (None, ""):
            blockers.append("broker_order_id_present")

        if int(order.submission_attempt_count or 0) != 0:
            blockers.append("submission_attempt_not_zero")

        has_attempt = (
            self._session.scalar(
                select(OrderSubmissionAttemptEntity.attempt_id)
                .where(
                    OrderSubmissionAttemptEntity.order_id
                    == int(order.order_id)
                )
                .limit(1)
            )
            is not None
        )
        if has_attempt:
            blockers.append("submission_attempt_row_exists")

        if outbox is None:
            blockers.append("submit_outbox_missing")
        else:
            if outbox.status_code not in {
                OutboxStatus.AMBIGUOUS.value,
                OutboxStatus.MANUAL_REVIEW.value,
            }:
                blockers.append("outbox_not_ambiguous_or_review")
            if outbox.dispatch_intent_at is None:
                blockers.append("dispatch_intent_missing")
            payload = dict(outbox.payload_json or {})
            if str(payload.get("broker_order_id") or "").strip():
                blockers.append("outbox_payload_broker_id")

        if self._has_broker_submit_audit(int(order.order_id)):
            blockers.append("broker_submit_audit_present")

        identifier = self._resolve_identifier(order, outbox)
        if not identifier:
            blockers.append("identifier_missing")

        evidence = self._local_failure_evidence(order, outbox)
        if not evidence:
            blockers.append("local_pre_send_failure_not_proven")

        seen: set[str] = set()
        uniq: list[str] = []
        for b in blockers:
            if b not in seen:
                seen.add(b)
                uniq.append(b)
        return order, outbox, uniq, evidence

    def _resolve_identifier(
        self,
        order: TradingOrderEntity,
        outbox: OrderOutbox | None,
    ) -> str | None:
        """주문/outbox/결정적 factory 순으로 Upbit identifier 확보.

        mapper 로컬 실패로 identifier 전 rollback 된 경우에도
        generation 기반 factory 값으로 READ-ONLY 조회가 가능하다.
        """

        existing = str(order.client_order_identifier or "").strip()
        if existing:
            return existing
        if outbox is not None:
            payload = dict(outbox.payload_json or {})
            for key in (
                "upbit_client_identifier",
                "client_order_identifier",
                "identifier",
            ):
                raw = str(payload.get(key) or "").strip()
                if raw:
                    return raw
        if str(order.broker_code or "").upper() != "UPBIT":
            return None
        uba = order.user_broker_account_id
        if uba is None:
            return None
        try:
            from stock_platform.broker.upbit.client_order_identifier import (
                UpbitClientOrderIdentifierFactory,
            )

            gen = int(order.submission_generation or 1)
            return UpbitClientOrderIdentifierFactory.build(
                broker_code="UPBIT",
                user_broker_account_id=int(uba),
                local_order_id=int(order.order_id),
                submission_generation=gen,
            )
        except Exception:  # noqa: BLE001
            return None

    def _local_failure_evidence(
        self,
        order: TradingOrderEntity,
        outbox: OrderOutbox | None,
    ) -> str | None:
        texts: list[str] = []
        if outbox is not None:
            texts.append(str(outbox.last_error or ""))
            texts.append(str(outbox.manual_review_reason or ""))
        try:
            from stock_platform.operation.audit_models import AuditEvent

            rows = list(
                self._session.scalars(
                    select(AuditEvent)
                    .where(
                        AuditEvent.event_type
                        == "OUTBOX_DISPATCH_AMBIGUOUS",
                    )
                    .order_by(AuditEvent.audit_event_id.desc())
                    .limit(50)
                )
            )
        except Exception:  # noqa: BLE001
            rows = []
        outbox_id = int(getattr(outbox, "outbox_id", 0) or 0)
        for row in rows:
            detail = getattr(row, "detail", None) or {}
            if not isinstance(detail, dict):
                continue
            if int(detail.get("outbox_id") or 0) != outbox_id:
                continue
            texts.append(str(detail.get("reason") or ""))

        blob = " | ".join(texts).lower()
        for marker in _LOCAL_PRE_SEND_MARKERS:
            if marker.lower() in blob:
                for t in texts:
                    if marker.lower() in t.lower():
                        return t[:500]
                return marker
        return None

    def _has_broker_submit_audit(self, order_id: int) -> bool:
        try:
            from stock_platform.operation.audit_models import AuditEvent
        except Exception:  # noqa: BLE001
            return True
        row = self._session.scalar(
            select(AuditEvent.audit_event_id)
            .where(
                AuditEvent.event_type.in_(list(_BROKER_SUBMIT_AUDIT_TYPES)),
                AuditEvent.order_id == int(order_id),
            )
            .limit(1)
        )
        return row is not None

    def _find_submit_outbox(self, order_id: int) -> OrderOutbox | None:
        rows = list(
            self._session.scalars(
                select(OrderOutbox)
                .where(
                    OrderOutbox.order_id == int(order_id),
                    OrderOutbox.event_type
                    == OutboxEventType.SUBMIT_ORDER.value,
                )
                .order_by(OrderOutbox.outbox_id.desc())
            )
        )
        return rows[0] if rows else None

    @staticmethod
    def _resolve_environment(
        order: TradingOrderEntity,
        outbox: OrderOutbox | None,
    ) -> str:
        meta = dict(order.metadata_payload or {})
        env = str(meta.get("environment") or "").upper()
        if env:
            return env
        if outbox is not None:
            payload = dict(outbox.payload_json or {})
            env = str(payload.get("environment") or "").upper()
            if env:
                return env
            if payload.get("account_type"):
                return str(payload.get("account_type")).upper()
        if order.user_broker_account_id is not None and order.account_id is None:
            return "LIVE"
        return "PAPER"

    def _linked_run_ids(self, order_id: int) -> list[str]:
        from stock_platform.trading.live_validation_entities import (
            LiveValidationRunEntity,
        )

        rows = list(
            self._session.scalars(
                select(LiveValidationRunEntity.run_id).where(
                    LiveValidationRunEntity.order_id == int(order_id)
                )
            )
        )
        return [str(r) for r in rows]

    def _consume_grants(self, *, order_id: int, actor: str) -> None:
        from stock_platform.trading.live_validation_entities import (
            LiveValidationRunEntity,
        )
        from stock_platform.trading.smoke_one_shot_dispatch_grant import (
            consume_grant_on_run,
            read_grant_from_run_detail,
        )

        rows = list(
            self._session.scalars(
                select(LiveValidationRunEntity).where(
                    LiveValidationRunEntity.order_id == int(order_id)
                )
            )
        )
        for run in rows:
            grant = read_grant_from_run_detail(getattr(run, "detail", None))
            if grant is None:
                continue
            consume_grant_on_run(
                run, outcome=f"{RESOLUTION}:{actor}"[:64]
            )
        self._session.flush()

    @staticmethod
    def _is_already_resolved(
        order: TradingOrderEntity | None,
        outbox: OrderOutbox | None,
    ) -> bool:
        if order is None or outbox is None:
            return False
        return (
            order.status_code == OrderStatus.CANCELLED.value
            and outbox.status_code == OutboxStatus.FAILED.value
            and REASON_CODE_RESOLUTION
            in str(outbox.last_error or "")
        )

    def _build_preview(
        self,
        order: TradingOrderEntity | None,
        outbox: OrderOutbox | None,
        blockers: list[str],
        evidence: str | None,
    ) -> ResolutionPreview:
        if order is None:
            return ResolutionPreview(
                resolvable=False,
                blockers=blockers or ["order_not_found"],
            )
        run_ids = self._linked_run_ids(int(order.order_id))
        return ResolutionPreview(
            resolvable=len(blockers) == 0,
            blockers=blockers,
            resolution=RESOLUTION if not blockers else None,
            reason_code=REASON_CODE_RESOLUTION if not blockers else None,
            order_id=int(order.order_id),
            outbox_id=int(outbox.outbox_id) if outbox else None,
            run_id=run_ids[0] if run_ids else None,
            user_broker_account_id=(
                int(order.user_broker_account_id)
                if order.user_broker_account_id is not None
                else None
            ),
            broker_code=str(order.broker_code or "").upper(),
            outbox_status=outbox.status_code if outbox else None,
            order_status=order.status_code,
            identifier=self._resolve_identifier(order, outbox),
            local_failure_evidence=evidence,
            broker_lookup_required=True,
        )
