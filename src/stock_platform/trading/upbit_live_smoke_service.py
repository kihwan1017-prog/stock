"""STEP 8-9 — Upbit 소액 LIVE Smoke 실행 서비스 (기본 DRY-RUN)."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.upbit.rules import (
    round_upbit_price,
    round_upbit_volume,
)
from stock_platform.common.settings import get_settings
from stock_platform.order.live_safety_audit import (
    emit_live_order_telegram,
    emit_live_safety_audit,
)
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.live_arm_service import LiveArmService
from stock_platform.trading.live_validation_entities import (
    LiveValidationRunEntity,
)
from stock_platform.trading.upbit_live_preflight_service import (
    UpbitLivePreflightService,
)
from stock_platform.trading.upbit_live_smoke_constants import (
    ALLOWED_TRANSITIONS,
    BrokerOrderStatus,
    CONFIRMATION_TEXT,
    LiveValidationRunStatus,
    MAX_SMOKE_AMOUNT,
    TERMINAL_INTERNAL_STATUSES,
    UPBIT_LIVE_SMOKE_COMPLETED,
    UPBIT_LIVE_SMOKE_EXECUTION_REQUESTED,
    UPBIT_LIVE_SMOKE_FAILED_CLOSED,
    UPBIT_LIVE_SMOKE_ONE_SHOT_GRANT_ISSUED,
    UPBIT_LIVE_SMOKE_ORDER_REJECTED,
    UPBIT_LIVE_SMOKE_ORDER_SUBMITTED,
    UPBIT_LIVE_SMOKE_ORDER_UNKNOWN,
)

logger = logging.getLogger(__name__)


def _session_identity_class_names(session: Session) -> dict[str, list[str]]:
    """세션 객체 클래스명만 (SQL/시크릿 미포함)."""

    def _names(objects: Any) -> list[str]:
        out: list[str] = []
        try:
            for obj in objects:
                out.append(type(obj).__name__)
        except Exception:  # noqa: BLE001
            return out
        return out

    return {
        "new": _names(getattr(session, "new", ()) or ()),
        "dirty": _names(getattr(session, "dirty", ()) or ()),
        "deleted": _names(getattr(session, "deleted", ()) or ()),
    }


def _extract_pg_sqlstate(exc: BaseException) -> str | None:
    orig = getattr(exc, "orig", None)
    if orig is None:
        return None
    for attr in ("pgcode", "sqlstate"):
        value = getattr(orig, attr, None)
        if value:
            return str(value)
    return None


def _extract_db_constraint_hint(exc: BaseException) -> str | None:
    """constraint/table/column 힌트만 — SQL 전문 금지."""

    parts: list[str] = []
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    if diag is not None:
        for attr in (
            "constraint_name",
            "table_name",
            "column_name",
            "schema_name",
        ):
            value = getattr(diag, attr, None)
            if value:
                parts.append(f"{attr}={value}")
    text = str(getattr(exc, "orig", None) or exc)
    # 긴 SQL 본문 절단
    if "unique" in text.lower() and "constraint" in text.lower():
        parts.append("hint=unique_violation")
    if "stringdatarighttruncation" in text.lower() or "value too long" in text.lower():
        parts.append("hint=value_too_long")
    return ";".join(parts) if parts else None


def log_live_smoke_db_error(
    *,
    exc: BaseException,
    stage: str,
    last_ok_stage: str | None,
    run_id: str | None,
    uba_id: int | None,
    order_id_present: bool,
    session: Session | None,
) -> None:
    """DB 예외 sanitized 로그 — 시크릿/SQL 파라미터 금지."""

    identity = (
        _session_identity_class_names(session) if session is not None else {}
    )
    logger.error(
        "live_smoke_db_error class=%s sqlstate=%s constraint=%s "
        "stage=%s last_ok=%s run_id=%s uba_id=%s order_id_present=%s "
        "session=%s",
        type(exc).__name__,
        _extract_pg_sqlstate(exc),
        _extract_db_constraint_hint(exc),
        stage,
        last_ok_stage,
        run_id,
        uba_id,
        order_id_present,
        identity,
    )

from stock_platform.trading.failure_code_normalize import (
    apply_failure_fields,
    classify_risk_blocked_reason,
    normalize_failure_code,
)


class UpbitLiveSmokeError(ValueError):
    """스모크 실행 거부 (비즈니스 거절 포함)."""

    def __init__(
        self,
        code: str,
        *,
        message: str | None = None,
        details: list[str] | None = None,
        http_status: int = 400,
        order_submitted: bool = False,
        create_order_calls: int = 0,
        run_id: str | None = None,
        correlation_id: str | None = None,
        status_code: str | None = None,
    ) -> None:
        raw = str(code or "").strip()
        # INVALID_TRANSITION:A->B 등 레거시 진단 코드는 정규화로 깨지므로 보존
        if ":" in raw or "->" in raw:
            self.code = raw[:200]
        else:
            self.code = normalize_failure_code(raw, fallback="UNKNOWN_FAILURE")
        self.message = message or self.code
        self.details = list(details or [])
        self.http_status = int(http_status)
        self.order_submitted = bool(order_submitted)
        self.create_order_calls = int(create_order_calls)
        self.run_id = run_id
        self.correlation_id = correlation_id or run_id
        self.status_code = status_code
        super().__init__(self.code)

class UpbitLiveSmokeService:
    """수동 1건 검증. 실주문은 명시적 플래그 3종 모두 필요."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def dry_run(
        self,
        *,
        user_broker_account_id: int,
        market: str,
        side: str,
        amount: Decimal,
        limit_price: Decimal,
        actor: str,
        arm_token: str | None = None,
        skip_live_network: bool = False,
    ) -> dict[str, Any]:
        preflight = UpbitLivePreflightService(self._session).run(
            user_broker_account_id=user_broker_account_id,
            market=market,
            side=side,
            amount=amount,
            limit_price=limit_price,
            arm_token=arm_token,
            actor=actor,
            skip_live_network=skip_live_network,
            purpose="dry_run",
        )
        run = self._create_run(
            preflight=preflight.to_dict(),
            execute_live=False,
            actor=actor,
        )
        self._transition(
            run, LiveValidationRunStatus.READY.value, actor=actor
        )
        self._transition(
            run,
            LiveValidationRunStatus.DRY_RUN_COMPLETED.value,
            actor=actor,
        )
        run.completed_at = datetime.now(timezone.utc)
        self._session.flush()
        payload = {
            "run_id": run.run_id,
            "execute_live": False,
            "ready": preflight.ready,
            "dry_run_ready": preflight.dry_run_ready,
            "live_execution_ready": preflight.live_execution_ready,
            "preflight": preflight.to_dict(),
            "status": run.status_code,
            "message": "DRY_RUN — Adapter not called",
            "adapter_create_order_calls": 0,
        }
        self._telegram(
            title="Upbit LIVE Smoke Dry-run",
            message=(
                f"UBA {user_broker_account_id} {market} {side} "
                f"amount={amount} dry-run ready={preflight.ready}"
            ),
            detail={
                "run_id": run.run_id,
                "uba_id": user_broker_account_id,
                "market": market,
                "side": side,
                "estimated_amount": preflight.estimated_amount,
                "execute_live": False,
            },
            event_type=UPBIT_LIVE_SMOKE_COMPLETED,
        )
        return payload

    def execute(
        self,
        *,
        user_broker_account_id: int,
        market: str,
        side: str,
        amount: Decimal,
        limit_price: Decimal,
        actor: str,
        arm_token: str | None,
        execute_live: bool,
        confirmation_text: str | None,
        preflight_id: str | None = None,
        skip_live_network: bool = False,
    ) -> dict[str, Any]:
        """실주문은 execute_live + confirmation + arm_token 모두 필수."""

        if not execute_live:
            return self.dry_run(
                user_broker_account_id=user_broker_account_id,
                market=market,
                side=side,
                amount=amount,
                limit_price=limit_price,
                actor=actor,
                arm_token=arm_token,
                skip_live_network=skip_live_network,
            )

        if confirmation_text != CONFIRMATION_TEXT:
            raise UpbitLiveSmokeError("CONFIRMATION_TEXT_MISMATCH")
        if not arm_token:
            raise UpbitLiveSmokeError("ARM_TOKEN_REQUIRED")
        if Decimal(str(amount)) > MAX_SMOKE_AMOUNT:
            raise UpbitLiveSmokeError("AMOUNT_EXCEEDS_MAX")

        from stock_platform.trading.upbit_live_tracking_service import (
            UpbitLiveTrackingService,
        )

        if UpbitLiveTrackingService(self._session).blocks_new_order(
            int(user_broker_account_id)
        ):
            raise UpbitLiveSmokeError("NEW_ORDER_BLOCKED_UNKNOWN_OR_REVIEW")

        # Admin API 경로: 저장된 preflight_id 필수 검증
        stored: LiveValidationRunEntity | None = None
        if preflight_id:
            stored = self._session.scalar(
                select(LiveValidationRunEntity).where(
                    LiveValidationRunEntity.preflight_id == preflight_id
                )
            )
            if stored is None:
                raise UpbitLiveSmokeError("PREFLIGHT_NOT_FOUND")
            self._assert_preflight_still_valid(
                stored,
                user_broker_account_id=user_broker_account_id,
                market=market,
                side=side,
                amount=amount,
                limit_price=limit_price,
            )

        preflight = UpbitLivePreflightService(self._session).run(
            user_broker_account_id=user_broker_account_id,
            market=market,
            side=side,
            amount=amount,
            limit_price=limit_price,
            arm_token=arm_token,
            actor=actor,
            skip_live_network=skip_live_network,
            purpose="live_execution",
        )
        if not preflight.live_execution_ready:
            raise UpbitLiveSmokeError(
                f"PREFLIGHT_NOT_READY:{','.join((preflight.blockers + preflight.live_blockers)[:3])}"
            )
        if stored is not None:
            stored_fp = str(
                (stored.preflight_result or {}).get("request_fingerprint")
                or stored.request_fingerprint
                or ""
            )
            if (
                stored_fp
                and preflight.request_fingerprint
                and stored_fp != preflight.request_fingerprint
            ):
                raise UpbitLiveSmokeError("PREFLIGHT_PARAMS_CHANGED")

        # 시장가 금지 — LIMIT만
        order_type = OrderType.LIMIT
        side_enum = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL
        price = round_upbit_price(Decimal(str(limit_price)))
        qty = (
            Decimal(str(preflight.quantity))
            if preflight.quantity
            else round_upbit_volume(Decimal(str(amount)) / price)
        )

        run = self._create_run(
            preflight=preflight.to_dict(),
            execute_live=True,
            actor=actor,
        )
        result: dict[str, Any] = {
            "run_id": run.run_id,
            "execute_live": True,
            "preflight": preflight.to_dict(),
            "pipeline_markers": [],
            "order_submitted": False,
            "create_order_calls": 0,
            "broker_order_status": BrokerOrderStatus.NOT_SUBMITTED.value,
        }
        markers: list[str] = result["pipeline_markers"]  # type: ignore[assignment]
        stage = "AFTER_CREATE_RUN"
        last_ok_stage: str | None = "AFTER_CREATE_RUN"

        def _mark(name: str) -> None:
            markers.append(name)

        try:
            stage = "TRANSITION_EXECUTION_REQUESTED"
            self._transition(
                run,
                LiveValidationRunStatus.EXECUTION_REQUESTED.value,
                actor=actor,
            )
            last_ok_stage = stage

            stage = "EMIT_AUDIT"
            emit_live_safety_audit(
                self._session,
                event_type=UPBIT_LIVE_SMOKE_EXECUTION_REQUESTED,
                actor=actor,
                run_id=run.run_id,
                user_id=preflight.user_id,
                account_id=user_broker_account_id,
                strategy_id=None,
                detail={
                    "run_id": run.run_id,
                    "preflight_id": preflight.preflight_id,
                    "market": market,
                    "side": side,
                    "quantity": str(qty),
                    "limit_price": str(price),
                    "estimated_amount": preflight.estimated_amount,
                },
                commit=False,
            )
            last_ok_stage = stage

            stage = "PAUSE_UBA_SCOPE"
            self._pause_uba_scope(user_broker_account_id, actor=actor)
            last_ok_stage = stage

            # 실주문 — OrderExecutionService (Adapter 우회 금지)
            from stock_platform.order.execution_service import (
                OrderExecutionCommand,
                OrderExecutionService,
            )

            uba = self._session.get(
                UserBrokerAccount, int(user_broker_account_id)
            )
            if uba is None:
                raise UpbitLiveSmokeError("UBA_NOT_FOUND")

            cmd = OrderExecutionCommand(
                account_id=None,  # LIVE — Paper FK 슬롯 사용 금지
                broker_code="UPBIT",
                exchange_code="UPBIT",
                symbol=str(market).upper(),
                side=side_enum,
                order_type=order_type,
                price=price,
                quantity=qty,
                actor=actor,
                environment="LIVE",
                user_broker_account_id=int(user_broker_account_id),
                owner_user_id=int(uba.user_id),
                user_id=int(uba.user_id),
                arm_token=arm_token,
                reference_price=Decimal(str(preflight.limit_price)),
                order_source="UPBIT_LIVE_SMOKE",
                idempotency_key=f"smoke:{run.run_id}",
                metadata_payload={
                    "smoke_run_id": run.run_id,
                    "preflight_id": preflight.preflight_id,
                },
            )
            stage = "BEFORE_ORDER_EXECUTION_SUBMIT"
            _mark("BEFORE_ORDER_EXECUTION_SUBMIT")
            last_ok_stage = stage
            stage = "ORDER_EXECUTION_SUBMIT"
            exec_result = OrderExecutionService(self._session).submit(cmd)
            _mark("AFTER_ORDER_EXECUTION_SUBMIT")
            last_ok_stage = "AFTER_ORDER_EXECUTION_SUBMIT"

            if not exec_result.allowed:
                _mark("SUBMIT_BLOCKED")
                raw_code = str(exec_result.reason_code or "ORDER_REJECTED")
                plan = exec_result.position_plan or {}
                plan_msg = (
                    str(plan.get("message") or "").strip()
                    if isinstance(plan, dict)
                    else ""
                )
                # 긴 메시지는 summary/details, code는 짧은 안정값만
                if (
                    " " in raw_code
                    or ";" in raw_code
                    or plan_msg
                    or raw_code.startswith("RISK_")
                ):
                    source = plan_msg or raw_code
                    code, details, summary = classify_risk_blocked_reason(
                        source
                    )
                    if (
                        raw_code.startswith("RISK_")
                        and " " not in raw_code
                        and ";" not in raw_code
                    ):
                        code = normalize_failure_code(
                            raw_code, fallback="RISK_ENGINE_BLOCKED"
                        )
                else:
                    code, summary = apply_failure_fields(
                        failure_code=raw_code,
                        failure_summary=None,
                        fallback="ORDER_REJECTED",
                    )
                    details = [code]

                code, summary = apply_failure_fields(
                    failure_code=code,
                    failure_summary=summary or plan_msg or None,
                    fallback="RISK_ENGINE_BLOCKED",
                )
                if not details:
                    details = [summary] if summary else [code]

                stage = "REJECT_FLUSH"
                self._transition(
                    run,
                    LiveValidationRunStatus.REJECTED.value,
                    actor=actor,
                )
                run.failure_code = code
                run.failure_summary = summary
                detail = dict(run.detail or {})
                detail["risk_details"] = details
                detail["order_submitted"] = False
                detail["create_order_calls"] = 0
                detail["pipeline_markers"] = list(markers)
                run.detail = detail
                run.broker_order_status = (
                    BrokerOrderStatus.NOT_SUBMITTED.value
                )
                emit_live_safety_audit(
                    self._session,
                    event_type=UPBIT_LIVE_SMOKE_ORDER_REJECTED,
                    actor=actor,
                    run_id=run.run_id,
                    user_id=preflight.user_id,
                    account_id=user_broker_account_id,
                    strategy_id=None,
                    detail={
                        "run_id": run.run_id,
                        "reason_code": code,
                        "details": details,
                        "order_submitted": False,
                        "create_order_calls": 0,
                    },
                    commit=False,
                )
                self._session.flush()
                last_ok_stage = stage
                raise UpbitLiveSmokeError(
                    code,
                    message="Risk policy blocked this order.",
                    details=details,
                    http_status=409,
                    order_submitted=False,
                    create_order_calls=0,
                    run_id=run.run_id,
                    status_code=LiveValidationRunStatus.REJECTED.value,
                )

            # 실주문 큐 성공 = QUEUED + order_id + outbox_id (adapter 전송 전)
            if (
                str(exec_result.reason_code or "") != "QUEUED"
                or exec_result.order_id is None
                or exec_result.outbox_id is None
            ):
                _mark("SUBMIT_NOT_QUEUED")
                raise UpbitLiveSmokeError(
                    "LIVE_SMOKE_NOT_QUEUED",
                    message=(
                        "OrderExecution did not queue a live order "
                        f"(reason={exec_result.reason_code})"
                    ),
                    http_status=500,
                    order_submitted=False,
                    create_order_calls=0,
                    run_id=run.run_id,
                    status_code=LiveValidationRunStatus.FAILED.value,
                )

            _mark("SUBMIT_ALLOWED")
            stage = "BEFORE_QUEUE_COMMIT"
            _mark("BEFORE_QUEUE_COMMIT")
            # submit() 내부에서 이미 commit됨 — 마커만 기록
            _mark("AFTER_QUEUE_COMMIT")
            last_ok_stage = "AFTER_QUEUE_COMMIT"

            run.order_id = exec_result.order_id
            run.order_status = exec_result.status_code
            run.submitted_at = datetime.now(timezone.utc)
            self._transition(
                run,
                LiveValidationRunStatus.QUEUED.value,
                actor=actor,
            )
            # Outbox 대기 — Broker ACCEPTED로 오인 금지
            from stock_platform.trading.upbit_live_tracking_service import (
                UpbitLiveTrackingService,
            )

            tracker = UpbitLiveTrackingService(self._session)
            tracker.attach_after_execution(
                run,
                order_id=exec_result.order_id,
                actor=actor,
                outbox_pending=True,
            )
            # QUEUED 직후 finalize 가 LIVE OFF/DISARM 하므로
            # Worker 단건 전송용 one-shot grant 발급 (설계 B)
            grant = self._issue_one_shot_dispatch_grant(
                run=run,
                order_id=int(exec_result.order_id),
                outbox_id=int(exec_result.outbox_id),
                user_broker_account_id=int(user_broker_account_id),
                actor=actor,
            )
            emit_live_safety_audit(
                self._session,
                event_type=UPBIT_LIVE_SMOKE_ORDER_SUBMITTED,
                actor=actor,
                run_id=run.run_id,
                user_id=preflight.user_id,
                account_id=user_broker_account_id,
                strategy_id=None,
                order_id=exec_result.order_id,
                detail={
                    "run_id": run.run_id,
                    "order_id": exec_result.order_id,
                    "outbox_id": exec_result.outbox_id,
                    "status": "QUEUED",
                    "internal_status": run.internal_status,
                    "broker_order_status": run.broker_order_status,
                    "reason_code": "QUEUED",
                    "one_shot_grant": {
                        "status": grant.get("status"),
                        "outbox_id": grant.get("outbox_id"),
                        "arm_deadline_at": grant.get("arm_deadline_at"),
                    },
                },
                commit=False,
            )
            watch = self._watch_and_maybe_cancel(
                run=run,
                order_id=int(exec_result.order_id or 0),
                actor=actor,
            )
            detail = dict(run.detail or {})
            detail["pipeline_markers"] = list(markers)
            run.detail = detail
            result.update(watch)
            result["order_id"] = exec_result.order_id
            result["outbox_id"] = exec_result.outbox_id
            result["reason_code"] = "QUEUED"
            result["status"] = LiveValidationRunStatus.QUEUED.value
            result["internal_status"] = run.internal_status
            result["broker_order_status"] = (
                run.broker_order_status
                or BrokerOrderStatus.NOT_SUBMITTED.value
            )
            result["order_submitted"] = False  # 브로커 전송 전
            result["queued"] = True
            result["pipeline_markers"] = list(markers)
            return result
        except UpbitLiveSmokeError:
            raise
        except Exception as exc:  # noqa: BLE001
            from sqlalchemy.exc import SQLAlchemyError

            is_db_error = isinstance(exc, SQLAlchemyError)
            order_id_present = bool(getattr(run, "order_id", None))
            if is_db_error:
                log_live_smoke_db_error(
                    exc=exc,
                    stage=stage,
                    last_ok_stage=last_ok_stage,
                    run_id=getattr(run, "run_id", None),
                    uba_id=int(user_broker_account_id),
                    order_id_present=order_id_present,
                    session=self._session,
                )
                try:
                    self._session.rollback()
                except Exception:  # noqa: BLE001
                    pass
                # rollback 후 실패 audit 재시도 (성공 이벤트 금지)
                try:
                    emit_live_safety_audit(
                        self._session,
                        event_type=UPBIT_LIVE_SMOKE_FAILED_CLOSED,
                        actor=actor,
                        run_id=getattr(run, "run_id", None),
                        user_id=getattr(preflight, "user_id", None),
                        account_id=user_broker_account_id,
                        strategy_id=None,
                        detail={
                            "error_code": "LIVE_SMOKE_DB_ERROR",
                            "status": LiveValidationRunStatus.FAILED.value,
                            "broker_order_status": (
                                BrokerOrderStatus.NOT_SUBMITTED.value
                            ),
                            "order_submitted": False,
                            "create_order_calls": 0,
                            "stage": stage,
                            "last_ok_stage": last_ok_stage,
                            "exception_class": type(exc).__name__,
                            "sqlstate": _extract_pg_sqlstate(exc),
                            "pipeline_markers": list(markers),
                        },
                        commit=True,
                    )
                except Exception:  # noqa: BLE001
                    logger.error(
                        "live_smoke_db_error_audit_failed run_id=%s stage=%s",
                        getattr(run, "run_id", None),
                        stage,
                    )
                raise UpbitLiveSmokeError(
                    "LIVE_SMOKE_DB_ERROR",
                    message=(
                        "실주문 요청을 저장하지 못했습니다. "
                        "실제 주문 전송 없음."
                    ),
                    details=[
                        f"stage={stage}",
                        f"exception={type(exc).__name__}",
                    ],
                    http_status=500,
                    order_submitted=False,
                    create_order_calls=0,
                    run_id=getattr(run, "run_id", None),
                    status_code=LiveValidationRunStatus.FAILED.value,
                ) from exc

            current = str(getattr(run, "status_code", "") or "")
            if current in TERMINAL_INTERNAL_STATUSES:
                # terminal 유지 — UNKNOWN 덮어쓰기 금지
                code, summary = apply_failure_fields(
                    failure_code=type(exc).__name__,
                    failure_summary=str(exc)[:500],
                    fallback="UNKNOWN_FAILURE",
                )
                run.failure_code = code
                if summary and not run.failure_summary:
                    run.failure_summary = summary
                try:
                    self._safe_flush()
                except Exception:  # noqa: BLE001
                    pass
                raise UpbitLiveSmokeError(
                    code,
                    message=summary or code,
                    http_status=500,
                    order_submitted=False,
                    create_order_calls=0,
                    run_id=getattr(run, "run_id", None),
                    status_code=current,
                ) from exc

            correlation_id = (
                getattr(run, "correlation_id", None)
                or getattr(run, "run_id", None)
            )
            try:
                import structlog

                structlog.get_logger(__name__).exception(
                    "upbit_live_smoke_internal_error",
                    run_id=getattr(run, "run_id", None),
                    uba_id=int(user_broker_account_id),
                    stage=stage,
                    exception_type=type(exc).__name__,
                    correlation_id=correlation_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "upbit_live_smoke_internal_error run_id=%s uba_id=%s "
                    "stage=%s exception_type=%s",
                    getattr(run, "run_id", None),
                    user_broker_account_id,
                    stage,
                    type(exc).__name__,
                )
            try:
                self._transition(
                    run,
                    LiveValidationRunStatus.FAILED.value,
                    actor=actor,
                )
                code, summary = apply_failure_fields(
                    failure_code=type(exc).__name__,
                    failure_summary=str(exc)[:500],
                    fallback="UNKNOWN_FAILURE",
                )
                run.failure_code = code
                run.failure_summary = summary
                run.broker_order_status = (
                    BrokerOrderStatus.NOT_SUBMITTED.value
                )
                emit_live_safety_audit(
                    self._session,
                    event_type=UPBIT_LIVE_SMOKE_ORDER_UNKNOWN,
                    actor=actor,
                    run_id=run.run_id,
                    user_id=preflight.user_id,
                    account_id=user_broker_account_id,
                    strategy_id=None,
                    detail={
                        "run_id": run.run_id,
                        "correlation_id": correlation_id,
                        "error": code,
                        "status": LiveValidationRunStatus.FAILED.value,
                    },
                    commit=False,
                )
                self._safe_flush()
            except Exception:  # noqa: BLE001
                try:
                    self._session.rollback()
                except Exception:  # noqa: BLE001
                    pass
            # 사용자 응답: correlation_id만 (secret/traceback/예외명 미노출)
            raise UpbitLiveSmokeError(
                "LIVE_SMOKE_INTERNAL_ERROR",
                message="Live smoke internal error — order was not submitted.",
                details=[],
                http_status=500,
                order_submitted=False,
                create_order_calls=0,
                run_id=getattr(run, "run_id", None),
                correlation_id=correlation_id,
                status_code=LiveValidationRunStatus.FAILED.value,
            ) from exc
        finally:
            self._finalize_protect(
                user_broker_account_id=user_broker_account_id,
                run=run,
                actor=actor,
            )

    def list_runs(
        self, *, limit: int = 50, uba_id: int | None = None
    ) -> list[dict[str, Any]]:
        stmt = select(LiveValidationRunEntity).order_by(
            LiveValidationRunEntity.created_at.desc()
        )
        if uba_id is not None:
            stmt = stmt.where(
                LiveValidationRunEntity.user_broker_account_id == int(uba_id)
            )
        stmt = stmt.limit(limit)
        rows = list(self._session.scalars(stmt))
        return [self._row_dict(r) for r in rows]

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self._session.scalar(
            select(LiveValidationRunEntity).where(
                LiveValidationRunEntity.run_id == run_id
            )
        )
        if row is None:
            raise LookupError("run not found")
        return self._row_dict(row)

    def persist_preflight(
        self,
        *,
        preflight: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        """Admin Preflight API용 — TTL 내 execute 참조를 위해 READY로 저장."""

        run = self._create_run(
            preflight=preflight,
            execute_live=False,
            actor=actor,
        )
        if preflight.get("ready"):
            self._transition(
                run, LiveValidationRunStatus.READY.value, actor=actor
            )
        else:
            self._transition(
                run,
                LiveValidationRunStatus.PREFLIGHT_FAILED.value,
                actor=actor,
            )
        self._session.flush()
        return {
            **preflight,
            "run_id": run.run_id,
            "status": run.status_code,
        }

    def _assert_preflight_still_valid(
        self,
        stored: LiveValidationRunEntity,
        *,
        user_broker_account_id: int,
        market: str,
        side: str,
        amount: Decimal,
        limit_price: Decimal,
    ) -> None:
        pf = dict(stored.preflight_result or {})
        if not pf.get("ready"):
            raise UpbitLiveSmokeError("PREFLIGHT_NOT_READY")
        expires_raw = pf.get("expires_at")
        if expires_raw:
            try:
                expires = datetime.fromisoformat(str(expires_raw))
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > expires:
                    raise UpbitLiveSmokeError("PREFLIGHT_EXPIRED")
            except UpbitLiveSmokeError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise UpbitLiveSmokeError("PREFLIGHT_EXPIRED") from exc
        if int(stored.user_broker_account_id) != int(user_broker_account_id):
            raise UpbitLiveSmokeError("PREFLIGHT_PARAMS_CHANGED")
        if str(stored.market).upper() != str(market).upper():
            raise UpbitLiveSmokeError("PREFLIGHT_PARAMS_CHANGED")
        if str(stored.side_code).upper() != str(side).upper():
            raise UpbitLiveSmokeError("PREFLIGHT_PARAMS_CHANGED")
        # 금액·가격 비교 (Decimal)
        stored_price = Decimal(str(pf.get("limit_price") or stored.limit_price))
        req_amount = Decimal(str(amount))
        req_price = round_upbit_price(Decimal(str(limit_price)))
        if abs(stored_price - req_price) > Decimal("0"):
            raise UpbitLiveSmokeError("PREFLIGHT_PARAMS_CHANGED")
        raw_amount = pf.get("requested_amount")
        if raw_amount is not None and Decimal(str(raw_amount)) != req_amount:
            raise UpbitLiveSmokeError("PREFLIGHT_PARAMS_CHANGED")

    # --- internals ---

    def _create_run(
        self,
        *,
        preflight: dict[str, Any],
        execute_live: bool,
        actor: str,
    ) -> LiveValidationRunEntity:
        run_id = f"uvs-{uuid.uuid4().hex[:16]}"
        key = hashlib.sha256(
            f"{run_id}|{preflight.get('preflight_id')}".encode()
        ).hexdigest()[:40]
        row = LiveValidationRunEntity(
            run_id=run_id,
            preflight_id=preflight.get("preflight_id"),
            idempotency_key=f"smoke:{key}",
            user_id=int(preflight.get("user_id") or 0),
            user_broker_account_id=int(
                preflight.get("user_broker_account_id") or 0
            ),
            broker_code="UPBIT",
            market=str(preflight.get("market") or ""),
            side_code=str(preflight.get("side") or ""),
            amount=Decimal(str(preflight.get("estimated_amount") or 0)),
            quantity=(
                Decimal(str(preflight["quantity"]))
                if preflight.get("quantity")
                else None
            ),
            limit_price=Decimal(str(preflight.get("limit_price") or 0)),
            execute_live=execute_live,
            status_code=LiveValidationRunStatus.CREATED.value,
            internal_status=LiveValidationRunStatus.CREATED.value,
            broker_order_status="NOT_SUBMITTED",
            broker_identifier=None,
            preflight_result=preflight,
            request_fingerprint=str(
                preflight.get("request_fingerprint") or ""
            ),
            created_by=actor,
            detail={},
        )
        self._session.add(row)
        self._session.flush()
        return row

    def _transition(
        self,
        run: LiveValidationRunEntity,
        new_status: str,
        *,
        actor: str,
    ) -> None:
        current = run.status_code
        allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
        if new_status == current:
            return
        # terminal → UNKNOWN 금지 (예외 경로 보호)
        if (
            new_status == LiveValidationRunStatus.UNKNOWN.value
            and current in TERMINAL_INTERNAL_STATUSES
        ):
            raise UpbitLiveSmokeError(
                f"INVALID_TRANSITION:{current}->{new_status}"
            )
        if new_status not in allowed and current not in {
            LiveValidationRunStatus.CREATED.value
        }:
            # CREATED에서 READY 직행 허용 보정
            if not (
                current == LiveValidationRunStatus.CREATED.value
                and new_status
                in {
                    LiveValidationRunStatus.READY.value,
                    LiveValidationRunStatus.PREFLIGHT_FAILED.value,
                    LiveValidationRunStatus.EXECUTION_REQUESTED.value,
                }
            ):
                raise UpbitLiveSmokeError(
                    f"INVALID_TRANSITION:{current}->{new_status}"
                )
        run.status_code = new_status
        run.internal_status = new_status
        run.updated_at = datetime.now(timezone.utc)
        detail = dict(run.detail or {})
        hist = list(detail.get("transitions") or [])
        hist.append(
            {
                "from": current,
                "to": new_status,
                "actor": actor,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
        detail["transitions"] = hist[-20:]
        run.detail = detail
        self._session.flush()

    def _pause_uba_scope(self, uba_id: int, *, actor: str) -> None:
        """UBA runtime pause — sync 문맥에서 coroutine을 버리지 않는다."""

        try:
            import asyncio

            from stock_platform.strategy_deployment.runtime_manager import (
                dynamic_strategy_runtime_manager,
            )

            coro = dynamic_strategy_runtime_manager.pause_account_runtimes(
                user_broker_account_id=int(uba_id),
                reason=f"upbit_live_smoke:{actor}",
            )
            try:
                # 이미 running loop면 task로 스케줄 (중첩 asyncio.run 금지)
                loop = asyncio.get_running_loop()
                loop.create_task(coro)
            except RuntimeError:
                asyncio.run(coro)
        except Exception:  # noqa: BLE001
            pass

    def _issue_one_shot_dispatch_grant(
        self,
        *,
        run: LiveValidationRunEntity,
        order_id: int,
        outbox_id: int,
        user_broker_account_id: int,
        actor: str,
    ) -> dict[str, Any]:
        """QUEUED 성공 직후 — finalize DISARM 전에 단건 Worker 권한 발급."""

        from stock_platform.trading.smoke_one_shot_dispatch_grant import (
            issue_grant_on_run,
        )

        uba = self._session.get(
            UserBrokerAccount, int(user_broker_account_id)
        )
        if uba is None:
            raise UpbitLiveSmokeError("UBA_NOT_FOUND")
        if not bool(getattr(uba, "live_armed", False)):
            raise UpbitLiveSmokeError(
                "LIVE_NOT_ARMED",
                message="one-shot grant requires ARM before finalize",
            )
        deadline = getattr(uba, "arm_expires_at", None)
        if deadline is None:
            raise UpbitLiveSmokeError(
                "LIVE_ARM_EXPIRES_MISSING",
                message="arm_expires_at required for one-shot grant",
            )
        grant = issue_grant_on_run(
            run,
            order_id=int(order_id),
            outbox_id=int(outbox_id),
            uba_id=int(user_broker_account_id),
            owner_user_id=int(uba.user_id),
            arm_deadline_at=deadline,
            idempotency_key=f"smoke:{run.run_id}",
        )
        try:
            emit_live_safety_audit(
                self._session,
                event_type=UPBIT_LIVE_SMOKE_ONE_SHOT_GRANT_ISSUED,
                actor=actor,
                run_id=run.run_id,
                user_id=int(uba.user_id),
                account_id=int(user_broker_account_id),
                strategy_id=None,
                order_id=int(order_id),
                detail={
                    "run_id": run.run_id,
                    "order_id": int(order_id),
                    "outbox_id": int(outbox_id),
                    "arm_deadline_at": grant.get("arm_deadline_at"),
                    "status": grant.get("status"),
                },
                commit=False,
            )
        except Exception:  # noqa: BLE001
            pass
        self._safe_flush()
        return grant

    @staticmethod
    def finalize_after_smoke_dispatch(
        session: Session,
        *,
        order_id: int,
        outbox_id: int,
        actor: str,
        outcome: str,
    ) -> dict[str, Any]:
        """Worker terminal 이후 grant 소비 + LIVE OFF/DISARM 재확인."""

        from stock_platform.order.repository import TradingOrderRepository
        from stock_platform.trading.smoke_one_shot_dispatch_grant import (
            GRANT_DETAIL_KEY,
            consume_grant_on_run,
            read_grant_from_run_detail,
        )
        from stock_platform.trading.upbit_live_smoke_constants import (
            UPBIT_LIVE_SMOKE_ONE_SHOT_GRANT_CONSUMED,
        )

        order = TradingOrderRepository(session).get(int(order_id))
        if order is None:
            return {"applied": False, "reason": "order_not_found"}
        meta = dict(order.metadata_payload or {})
        smoke_run_id = str(meta.get("smoke_run_id") or "").strip()
        if not smoke_run_id:
            return {"applied": False, "reason": "not_smoke_order"}

        run = session.scalar(
            select(LiveValidationRunEntity).where(
                LiveValidationRunEntity.run_id == smoke_run_id,
                LiveValidationRunEntity.order_id == int(order_id),
            )
        )
        if run is None:
            return {"applied": False, "reason": "run_not_found"}

        grant = read_grant_from_run_detail(getattr(run, "detail", None))
        if grant is None:
            # grant 없는 레거시 queued — 그래도 LIVE OFF 보장
            pass
        elif int(grant.get("outbox_id") or 0) not in (0, int(outbox_id)):
            return {"applied": False, "reason": "outbox_mismatch"}
        else:
            consume_grant_on_run(run, outcome=str(outcome))

        uba_id = int(
            run.user_broker_account_id
            or order.user_broker_account_id
            or 0
        )
        if uba_id <= 0:
            return {"applied": False, "reason": "uba_missing"}

        try:
            LiveArmService(session).disarm(
                uba_id,
                actor=actor,
                reason=f"UPBIT_LIVE_SMOKE_DISPATCH_{outcome}",
                turn_live_off=True,
                run_id=str(run.run_id),
            )
        except Exception:  # noqa: BLE001
            # Scheduler 미PAUSE 등 — best effort; Worker는 계속
            pass

        try:
            emit_live_safety_audit(
                session,
                event_type=UPBIT_LIVE_SMOKE_ONE_SHOT_GRANT_CONSUMED,
                actor=actor,
                run_id=run.run_id,
                user_id=getattr(run, "user_id", None),
                account_id=uba_id,
                strategy_id=None,
                order_id=int(order_id),
                detail={
                    "run_id": run.run_id,
                    "order_id": int(order_id),
                    "outbox_id": int(outbox_id),
                    "outcome": str(outcome),
                    "grant": (run.detail or {}).get(GRANT_DETAIL_KEY),
                    "protect": "DISARM_LIVE_OFF",
                },
                commit=False,
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            session.flush()
        except Exception:  # noqa: BLE001
            pass
        return {
            "applied": True,
            "run_id": run.run_id,
            "uba_id": uba_id,
            "outcome": str(outcome),
        }

    def _watch_and_maybe_cancel(
        self,
        *,
        run: LiveValidationRunEntity,
        order_id: int,
        actor: str,
    ) -> dict[str, Any]:
        """관찰 — Outbox를 ACCEPTED로 오인하지 않음. 추적 Scheduler에 위임."""

        settings = get_settings()
        watch_seconds = int(
            getattr(settings, "upbit_live_smoke_order_watch_seconds", 60)
        )
        auto_cancel = bool(
            getattr(settings, "upbit_live_smoke_auto_cancel", True)
        )
        from stock_platform.trading.upbit_live_tracking_service import (
            UpbitLiveTrackingService,
        )

        # 즉시 1회 추적 시도 (Mock/테스트용). 실패해도 UNKNOWN 처리.
        track_view: dict[str, Any] = {}
        try:
            track_view = UpbitLiveTrackingService(self._session).track_once(
                run, actor=actor
            )
        except Exception as exc:  # noqa: BLE001
            track_view = {
                "track_error": type(exc).__name__,
                "internal_status": run.internal_status,
                "broker_order_status": run.broker_order_status,
            }
        return {
            "watch_seconds": watch_seconds,
            "auto_cancel": auto_cancel,
            "order_id": order_id,
            "internal_status": run.internal_status,
            "broker_order_status": run.broker_order_status,
            "note": (
                "OUTBOX_PENDING is not ORDER_ACCEPTED; "
                "broker tracker confirms status"
            ),
            "track": track_view,
        }

    def _safe_flush(self) -> bool:
        """failed transaction에서는 flush하지 않고 rollback."""

        from sqlalchemy.exc import SQLAlchemyError

        try:
            if not self._session.is_active:
                try:
                    self._session.rollback()
                except Exception:  # noqa: BLE001
                    pass
                return False
            self._session.flush()
            return True
        except SQLAlchemyError:
            try:
                self._session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return False
        except Exception:  # noqa: BLE001
            try:
                self._session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return False

    def _finalize_protect(
        self,
        *,
        user_broker_account_id: int,
        run: LiveValidationRunEntity,
        actor: str,
    ) -> None:
        """성공/실패/예외와 무관 — DISARM + LIVE OFF + Pause 유지.

        failed Session에서는 flush를 시도하지 않는다.
        REJECTED(비즈니스 거절)는 UNKNOWN/FAILED_CLOSED로 덮지 않는다.
        """

        session_ok = True
        try:
            if not self._session.is_active:
                try:
                    self._session.rollback()
                except Exception:  # noqa: BLE001
                    session_ok = False
                else:
                    session_ok = bool(self._session.is_active)
        except Exception:  # noqa: BLE001
            session_ok = False

        try:
            LiveArmService(self._session).disarm(
                int(user_broker_account_id),
                actor=actor,
                reason="UPBIT_LIVE_SMOKE_FINALLY",
                turn_live_off=True,
            )
        except Exception:  # noqa: BLE001
            pass
        self._pause_uba_scope(user_broker_account_id, actor=actor)

        if not session_ok:
            return

        from stock_platform.trading.upbit_live_smoke_constants import (
            BrokerOrderStatus,
            TERMINAL_BROKER_STATUSES,
        )

        broker_status = str(run.broker_order_status or "")
        terminal_ok = broker_status in TERMINAL_BROKER_STATUSES or (
            run.internal_status
            in {
                LiveValidationRunStatus.DRY_RUN_COMPLETED.value,
                LiveValidationRunStatus.VERIFIED.value,
            }
        )
        # REJECTED는 비즈니스 terminal — 상태 유지 + protect audit만
        if run.status_code == LiveValidationRunStatus.REJECTED.value:
            try:
                emit_live_safety_audit(
                    self._session,
                    event_type=UPBIT_LIVE_SMOKE_FAILED_CLOSED,
                    actor=actor,
                    run_id=run.run_id,
                    user_id=run.user_id,
                    account_id=user_broker_account_id,
                    strategy_id=None,
                    detail={
                        "run_id": run.run_id,
                        "status": run.status_code,
                        "broker_order_status": broker_status,
                        "protect": "DISARM_LIVE_OFF",
                        "status_preserved": "REJECTED",
                    },
                    commit=False,
                )
            except Exception:  # noqa: BLE001
                try:
                    self._session.rollback()
                except Exception:  # noqa: BLE001
                    pass
                return
        elif run.status_code not in {
            LiveValidationRunStatus.COMPLETED.value,
            LiveValidationRunStatus.DRY_RUN_COMPLETED.value,
            LiveValidationRunStatus.FAILED_CLOSED.value,
        }:
            try:
                if broker_status == BrokerOrderStatus.UNKNOWN.value:
                    if run.internal_status != (
                        LiveValidationRunStatus.FAILED_CLOSED.value
                    ):
                        self._transition(
                            run,
                            LiveValidationRunStatus.FAILED_CLOSED.value,
                            actor=actor,
                        )
                    emit_live_safety_audit(
                        self._session,
                        event_type=UPBIT_LIVE_SMOKE_FAILED_CLOSED,
                        actor=actor,
                        run_id=run.run_id,
                        user_id=run.user_id,
                        account_id=user_broker_account_id,
                        strategy_id=None,
                        detail={
                            "run_id": run.run_id,
                            "status": run.status_code,
                            "broker_order_status": broker_status,
                        },
                        commit=False,
                    )
                elif terminal_ok and run.internal_status in {
                    LiveValidationRunStatus.CANCELED.value,
                    LiveValidationRunStatus.VERIFIED.value,
                }:
                    self._transition(
                        run,
                        LiveValidationRunStatus.COMPLETED.value,
                        actor=actor,
                    )
            except UpbitLiveSmokeError:
                pass

        if terminal_ok and run.internal_status in {
            LiveValidationRunStatus.COMPLETED.value,
            LiveValidationRunStatus.FAILED_CLOSED.value,
            LiveValidationRunStatus.DRY_RUN_COMPLETED.value,
        }:
            run.completed_at = datetime.now(timezone.utc)
        if not self._safe_flush():
            return
        self._telegram(
            title="Upbit LIVE Smoke Finished (protect)",
            message=(
                f"run={run.run_id} internal={run.internal_status} "
                f"broker={broker_status} LIVE OFF + DISARM applied"
            ),
            detail={
                "run_id": run.run_id,
                "uba_id": user_broker_account_id,
                "status": run.internal_status,
                "broker_order_status": broker_status,
                "order_id": run.order_id,
                "execute_live": bool(run.execute_live),
            },
            event_type=UPBIT_LIVE_SMOKE_COMPLETED,
        )

    def _telegram(
        self,
        *,
        title: str,
        message: str,
        detail: dict[str, Any],
        event_type: str,
    ) -> None:
        safe = {
            k: v
            for k, v in detail.items()
            if k
            not in {
                "arm_token",
                "access_key",
                "secret_key",
                "token",
                "password",
            }
        }
        emit_live_order_telegram(
            event_type=event_type,
            title=title,
            message=message,
            detail=safe,
        )

    @staticmethod
    def _row_dict(row: LiveValidationRunEntity) -> dict[str, Any]:
        from stock_platform.trading.upbit_live_smoke_constants import (
            mask_broker_uuid,
        )

        return {
            "run_id": row.run_id,
            "preflight_id": row.preflight_id,
            "user_id": row.user_id,
            "user_broker_account_id": row.user_broker_account_id,
            "broker_code": row.broker_code,
            "market": row.market,
            "side": row.side_code,
            "amount": str(row.amount),
            "quantity": str(row.quantity) if row.quantity is not None else None,
            "limit_price": str(row.limit_price),
            "execute_live": bool(row.execute_live),
            "status": row.internal_status or row.status_code,
            "internal_status": row.internal_status or row.status_code,
            "broker_order_status": getattr(
                row, "broker_order_status", "NOT_SUBMITTED"
            ),
            "broker_identifier": getattr(row, "broker_identifier", None),
            "broker_uuid_masked": mask_broker_uuid(
                getattr(row, "broker_order_uuid", None)
            ),
            "order_id": row.order_id,
            "order_status": row.order_status,
            "manual_review_required": bool(
                getattr(row, "manual_review_required", False)
            ),
            "last_broker_query_at": (
                row.last_broker_query_at.isoformat()
                if getattr(row, "last_broker_query_at", None)
                else None
            ),
            "failure_code": row.failure_code,
            "started_at": (
                row.started_at.isoformat() if row.started_at else None
            ),
            "submitted_at": (
                row.submitted_at.isoformat() if row.submitted_at else None
            ),
            "completed_at": (
                row.completed_at.isoformat() if row.completed_at else None
            ),
            "post_fill_verification_id": row.post_fill_verification_id,
            "created_by": row.created_by,
        }
