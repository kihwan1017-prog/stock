"""STEP 8-5-12 — Upbit Ambiguous Order Resolver (Identifier Lookup)."""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from stock_platform.broker.upbit.ambiguous_constants import (
    RemoteLookupStatus,
    SubmissionAttemptResult,
)
from stock_platform.broker.upbit.exceptions import (
    UpbitAmbiguousOrderResultError,
    UpbitAuthenticationError,
    UpbitBanOrBlockError,
    UpbitError,
    UpbitOrderNotFoundError,
    UpbitRateLimitError,
    UpbitTemporaryUnavailableError,
)
from stock_platform.broker.upbit.order_client import UpbitOrderRestClient
from stock_platform.common.settings import get_settings
from stock_platform.order.entities import (
    TradingOrderEntity,
    TradingOrderStatusHistoryEntity,
)
from stock_platform.order.models import OrderStatus
from stock_platform.order.repository import TradingOrderRepository
from stock_platform.order.state_machine import OrderStateMachine

logger = logging.getLogger(__name__)


def _capped_backoff_seconds(
    base_seconds: float,
    *,
    max_seconds: float,
    jitter_ratio: float = 0.15,
) -> float:
    """지수 백오프 결과를 max_interval로 제한하고 소량 Jitter를 더한다.

    Thundering herd 방지 — 다수 주문이 동시에 next_remote_lookup_at에
    도달해 스케줄러 폴링 시점에 몰리는 상황을 완화한다.
    """

    capped = min(max(0.0, float(base_seconds)), float(max_seconds))
    jitter = capped * float(jitter_ratio) * random.random()
    return round(capped + jitter, 3)


class UpbitAmbiguousOrderResolver:
    """Identifier 기반 원격 조회 → 로컬 주문 연결."""

    def __init__(
        self,
        session: Session,
        *,
        order_client: UpbitOrderRestClient | None = None,
    ) -> None:
        self._session = session
        self._repo = TradingOrderRepository(session)
        self._client = order_client
        self._settings = get_settings()

    def list_ambiguous(
        self, *, limit: int = 100
    ) -> list[TradingOrderEntity]:
        statuses = {
            OrderStatus.AMBIGUOUS_SUBMISSION.value,
            OrderStatus.REMOTE_LOOKUP_PENDING.value,
            OrderStatus.IDENTITY_CONFLICT.value,
            OrderStatus.MANUAL_REVIEW_REQUIRED.value,
        }
        stmt = (
            select(TradingOrderEntity)
            .where(
                TradingOrderEntity.broker_code == "UPBIT",
                TradingOrderEntity.status_code.in_(
                    list(statuses)
                ),
            )
            .order_by(
                TradingOrderEntity.ambiguous_since.asc().nulls_last(),
                TradingOrderEntity.order_id.asc(),
            )
            .limit(limit)
        )
        return list(self._session.scalars(stmt))

    def mark_ambiguous(
        self,
        order: TradingOrderEntity,
        *,
        reason: str,
        attempt_result: str,
        actor: str = "SYSTEM",
    ) -> TradingOrderEntity:
        now = datetime.now(timezone.utc)
        delay = int(
            self._settings.upbit_ambiguous_lookup_initial_delay_seconds
        )
        current = OrderStatus(order.status_code)
        target = OrderStatus.AMBIGUOUS_SUBMISSION
        if OrderStateMachine.can_transition(current, target):
            self._repo.change_status(
                entity=order,
                new_status=target,
                actor=actor,
                reason_code="AMBIGUOUS_SUBMISSION",
                message=reason[:500],
                commit=False,
            )
        elif current not in {
            OrderStatus.AMBIGUOUS_SUBMISSION,
            OrderStatus.REMOTE_LOOKUP_PENDING,
        }:
            # SUBMITTING 등에서 직접 전이 불가 시 강제 메타만
            order.status_code = target.value
        order.ambiguous_since = order.ambiguous_since or now
        order.ambiguity_reason = reason[:200]
        order.remote_lookup_status = RemoteLookupStatus.PENDING.value
        order.next_remote_lookup_at = now + timedelta(seconds=delay)
        order.last_submission_attempt_at = now
        order.submission_attempt_count = int(
            order.submission_attempt_count or 0
        ) + 1
        self._record_attempt(
            order,
            result_type=attempt_result,
            ambiguous=True,
            correlation_note=reason[:200],
        )
        self._audit(
            "UPBIT_ORDER_AMBIGUOUS",
            order,
            {"reason": reason[:200], "attempt_result": attempt_result},
        )
        self._session.flush()
        return order

    def resolve_one(
        self,
        order_id: int,
        *,
        actor: str = "RESOLVER",
        force: bool = False,
    ) -> dict[str, Any]:
        order = self._repo.get(order_id)
        if order is None:
            return {"status": "NOT_FOUND", "order_id": order_id}
        if (order.broker_code or "").upper() != "UPBIT":
            return {"status": "SKIPPED_NOT_UPBIT", "order_id": order_id}

        identifier = (order.client_order_identifier or "").strip()
        if not identifier:
            return {
                "status": "NO_IDENTIFIER",
                "order_id": order_id,
                "message": "Cannot lookup without identifier",
            }

        now = datetime.now(timezone.utc)
        if (
            not force
            and order.next_remote_lookup_at
            and order.next_remote_lookup_at > now
        ):
            return {
                "status": "DEFERRED",
                "order_id": order_id,
                "next_remote_lookup_at": (
                    order.next_remote_lookup_at.isoformat()
                ),
            }

        max_attempts = int(
            self._settings.upbit_ambiguous_lookup_max_attempts
        )
        max_age = int(
            self._settings.upbit_ambiguous_lookup_max_age_seconds
        )
        attempts = int(order.remote_lookup_attempt_count or 0)
        if attempts >= max_attempts:
            return self._to_manual_review(
                order,
                reason="MAX_LOOKUP_ATTEMPTS",
                actor=actor,
            )
        if order.ambiguous_since:
            age = (now - order.ambiguous_since).total_seconds()
            if age >= max_age and attempts >= 2:
                # 최종 미발견 후보 — 한 번 더 조회 후 판단
                pass

        # 상태 REMOTE_LOOKUP_PENDING
        current = OrderStatus(order.status_code)
        if OrderStateMachine.can_transition(
            current, OrderStatus.REMOTE_LOOKUP_PENDING
        ):
            self._repo.change_status(
                entity=order,
                new_status=OrderStatus.REMOTE_LOOKUP_PENDING,
                actor=actor,
                reason_code="REMOTE_LOOKUP_START",
                commit=False,
            )

        client = self._client or UpbitOrderRestClient(
            user_broker_account_id=order.user_broker_account_id
        )

        # STEP 8-5-14 — Attempt는 실제 외부 API 호출 직전에만 증가시킨다.
        # (Scheduler pre-check에서 defer 되는 경우 Attempt를 소모하지 않기 위함)
        order.remote_lookup_attempt_count = attempts + 1
        order.last_remote_lookup_at = now
        self._audit(
            "UPBIT_IDENTIFIER_LOOKUP_START",
            order,
            {"identifier": identifier, "attempt": attempts + 1},
        )
        try:
            payload = client.get_order(identifier=identifier)
        except UpbitOrderNotFoundError:
            return self._handle_not_found(order, actor=actor, now=now)
        except UpbitRateLimitError as exc:
            order.remote_lookup_status = (
                RemoteLookupStatus.RATE_LIMITED.value
            )
            retry_after = float(exc.retry_after_seconds or 10)
            order.next_remote_lookup_at = now + timedelta(
                seconds=max(retry_after, 2)
            )
            self._session.flush()
            return {
                "status": RemoteLookupStatus.RATE_LIMITED.value,
                "order_id": order_id,
                "defer_seconds": retry_after,
            }
        except UpbitBanOrBlockError:
            order.remote_lookup_status = RemoteLookupStatus.BLOCKED.value
            return self._to_manual_review(
                order, reason="UPBIT_418_BLOCKED", actor=actor
            )
        except UpbitAuthenticationError:
            order.remote_lookup_status = (
                RemoteLookupStatus.AUTH_FAILED.value
            )
            return self._to_manual_review(
                order, reason="AUTH_FAILED", actor=actor
            )
        except UpbitTemporaryUnavailableError:
            order.remote_lookup_status = (
                RemoteLookupStatus.TEMPORARY_UNAVAILABLE.value
            )
            backoff = int(
                self._settings.upbit_ambiguous_lookup_backoff_seconds
            )
            delay = _capped_backoff_seconds(
                backoff * max(1, attempts + 1),
                max_seconds=(
                    self._settings.upbit_ambiguous_lookup_max_interval_seconds
                ),
            )
            order.next_remote_lookup_at = now + timedelta(seconds=delay)
            self._session.flush()
            return {
                "status": (
                    RemoteLookupStatus.TEMPORARY_UNAVAILABLE.value
                ),
                "order_id": order_id,
            }
        except UpbitAmbiguousOrderResultError:
            backoff = int(
                self._settings.upbit_ambiguous_lookup_backoff_seconds
            )
            order.next_remote_lookup_at = now + timedelta(
                seconds=backoff
            )
            self._session.flush()
            return {"status": "LOOKUP_AMBIGUOUS", "order_id": order_id}
        except UpbitError as exc:
            order.next_remote_lookup_at = now + timedelta(seconds=5)
            self._session.flush()
            return {
                "status": "LOOKUP_ERROR",
                "order_id": order_id,
                "message": str(exc)[:200],
            }

        return self._match_and_link(
            order, payload=payload, actor=actor
        )

    def _handle_not_found(
        self,
        order: TradingOrderEntity,
        *,
        actor: str,
        now: datetime,
    ) -> dict[str, Any]:
        attempts = int(order.remote_lookup_attempt_count or 0)
        max_attempts = int(
            self._settings.upbit_ambiguous_lookup_max_attempts
        )
        max_age = int(
            self._settings.upbit_ambiguous_lookup_max_age_seconds
        )
        age_ok = False
        if order.ambiguous_since:
            age_ok = (
                now - order.ambiguous_since
            ).total_seconds() >= max_age

        if attempts < max_attempts and not age_ok:
            order.remote_lookup_status = (
                RemoteLookupStatus.NOT_FOUND_TRANSIENT.value
            )
            backoff = int(
                self._settings.upbit_ambiguous_lookup_backoff_seconds
            )
            delay = _capped_backoff_seconds(
                backoff * max(1, attempts),
                max_seconds=(
                    self._settings.upbit_ambiguous_lookup_max_interval_seconds
                ),
            )
            order.next_remote_lookup_at = now + timedelta(seconds=delay)
            self._audit(
                "UPBIT_REMOTE_ORDER_NOT_FOUND_TRANSIENT",
                order,
                {"attempt": attempts},
            )
            self._session.flush()
            return {
                "status": RemoteLookupStatus.NOT_FOUND_TRANSIENT.value,
                "order_id": int(order.order_id),
            }

        order.remote_lookup_status = (
            RemoteLookupStatus.NOT_FOUND_FINAL.value
        )
        self._audit(
            "UPBIT_REMOTE_ORDER_NOT_FOUND_FINAL",
            order,
            {"attempt": attempts},
        )
        # 자동 재제출 금지 — Manual Review
        return self._to_manual_review(
            order,
            reason="NOT_FOUND_FINAL",
            actor=actor,
        )

    def _match_and_link(
        self,
        order: TradingOrderEntity,
        *,
        payload: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        uuid = str(
            payload.get("uuid")
            or payload.get("order_id")
            or ""
        ).strip()
        remote_id = str(payload.get("identifier") or "").strip()
        local_id = (order.client_order_identifier or "").strip()

        mismatches: list[str] = []
        if remote_id and local_id and remote_id != local_id:
            mismatches.append("identifier")

        market = str(payload.get("market") or "").upper()
        local_market = self._local_market(order)
        if market and local_market and market != local_market:
            mismatches.append("market")

        side = str(payload.get("side") or "").lower()
        local_side = "bid" if order.side_code == "BUY" else "ask"
        if side and side != local_side:
            mismatches.append("side")

        if mismatches:
            order.remote_lookup_status = (
                RemoteLookupStatus.FOUND_MISMATCHED.value
            )
            self._audit(
                "UPBIT_REMOTE_MATCH_MISMATCH",
                order,
                {"mismatches": mismatches, "uuid": uuid[:50]},
            )
            return self._to_identity_conflict(
                order,
                reason=f"MATCH_MISMATCH:{','.join(mismatches)}",
                actor=actor,
            )

        if uuid:
            other = self._repo.get_by_broker_order_id(
                broker_code="UPBIT",
                broker_order_id=uuid,
            )
            if (
                other is not None
                and int(other.order_id) != int(order.order_id)
            ):
                order.remote_lookup_status = (
                    RemoteLookupStatus.CONFLICT.value
                )
                return self._to_identity_conflict(
                    order,
                    reason="UUID_LINKED_TO_OTHER_ORDER",
                    actor=actor,
                )

        # volume/price soft check
        self._soft_compare_qty_price(order, payload)

        order.broker_order_id = uuid or order.broker_order_id
        order.remote_lookup_status = (
            RemoteLookupStatus.FOUND_MATCHED.value
        )
        order.next_remote_lookup_at = None
        current = OrderStatus(order.status_code)
        # ACCEPTED로 정규화
        for target in (
            OrderStatus.SENT,
            OrderStatus.ACCEPTED,
        ):
            if OrderStateMachine.can_transition(current, target):
                self._repo.change_status(
                    entity=order,
                    new_status=target,
                    actor=actor,
                    reason_code="REMOTE_ORDER_FOUND",
                    commit=False,
                )
                current = target
        if current == OrderStatus.REMOTE_LOOKUP_PENDING:
            # 전이 테이블에 ACCEPTED 직접 허용
            if OrderStateMachine.can_transition(
                current, OrderStatus.ACCEPTED
            ):
                self._repo.change_status(
                    entity=order,
                    new_status=OrderStatus.ACCEPTED,
                    actor=actor,
                    reason_code="REMOTE_ORDER_FOUND",
                    commit=False,
                )
            else:
                order.status_code = OrderStatus.ACCEPTED.value
                order.accepted_at = datetime.now(timezone.utc)

        self._record_attempt(
            order,
            result_type=SubmissionAttemptResult.REMOTE_ORDER_FOUND.value,
            ambiguous=False,
            external_uuid=uuid,
        )
        self._audit(
            "UPBIT_REMOTE_ORDER_FOUND",
            order,
            {"uuid": uuid[:50], "identifier": local_id},
        )
        self._session.flush()
        return {
            "status": RemoteLookupStatus.FOUND_MATCHED.value,
            "order_id": int(order.order_id),
            "broker_order_id": uuid,
        }

    def _to_manual_review(
        self,
        order: TradingOrderEntity,
        *,
        reason: str,
        actor: str,
    ) -> dict[str, Any]:
        current = OrderStatus(order.status_code)
        target = OrderStatus.MANUAL_REVIEW_REQUIRED
        if OrderStateMachine.can_transition(current, target):
            self._repo.change_status(
                entity=order,
                new_status=target,
                actor=actor,
                reason_code=reason,
                commit=False,
            )
        else:
            order.status_code = target.value
        order.ambiguity_reason = reason[:200]
        self._audit(
            "UPBIT_MANUAL_REVIEW_REQUIRED",
            order,
            {"reason": reason},
        )
        self._session.flush()
        return {
            "status": "MANUAL_REVIEW_REQUIRED",
            "order_id": int(order.order_id),
            "reason": reason,
        }

    def _to_identity_conflict(
        self,
        order: TradingOrderEntity,
        *,
        reason: str,
        actor: str,
    ) -> dict[str, Any]:
        current = OrderStatus(order.status_code)
        target = OrderStatus.IDENTITY_CONFLICT
        if OrderStateMachine.can_transition(current, target):
            self._repo.change_status(
                entity=order,
                new_status=target,
                actor=actor,
                reason_code=reason,
                commit=False,
            )
        else:
            order.status_code = target.value
        # 해당 계좌만 pause 시도
        self._pause_uba(order)
        self._audit(
            "UPBIT_ORDER_IDENTITY_CONFLICT",
            order,
            {"reason": reason},
        )
        self._session.flush()
        return {
            "status": RemoteLookupStatus.CONFLICT.value,
            "order_id": int(order.order_id),
            "reason": reason,
        }

    def _pause_uba(self, order: TradingOrderEntity) -> None:
        uba_id = order.user_broker_account_id
        if not uba_id:
            return
        try:
            from stock_platform.broker.recovery_account_state import (
                BrokerRecoveryAccountStateEntity,
            )

            row = self._session.scalar(
                select(BrokerRecoveryAccountStateEntity).where(
                    BrokerRecoveryAccountStateEntity.broker_code
                    == "UPBIT",
                    BrokerRecoveryAccountStateEntity.user_broker_account_id
                    == int(uba_id),
                )
            )
            if row is None:
                row = BrokerRecoveryAccountStateEntity(
                    broker_code="UPBIT",
                    user_id=0,
                    user_broker_account_id=int(uba_id),
                    trading_paused=True,
                    recovery_status="MANUAL_REVIEW",
                )
                self._session.add(row)
            else:
                row.trading_paused = True
                row.last_error_summary = (
                    "UPBIT_ORDER_IDENTITY_CONFLICT"
                )[:500]
            self._session.flush()
        except Exception:  # noqa: BLE001
            logger.warning(
                "upbit_identity_conflict_pause_failed uba=%s",
                uba_id,
            )

    def claim_submitting(
        self, order_id: int
    ) -> TradingOrderEntity | None:
        """원자적 PENDING/CREATED → SUBMITTING."""

        stmt = (
            update(TradingOrderEntity)
            .where(
                TradingOrderEntity.order_id == order_id,
                TradingOrderEntity.status_code.in_(
                    [
                        OrderStatus.CREATED.value,
                        OrderStatus.PENDING.value,
                    ]
                ),
            )
            .values(
                status_code=OrderStatus.SUBMITTING.value,
                updated_at=datetime.now(timezone.utc),
            )
            .returning(TradingOrderEntity.order_id)
        )
        row = self._session.execute(stmt).first()
        if row is None:
            return None
        self._session.flush()
        return self._repo.get(order_id)

    def ensure_identifier(
        self, order: TradingOrderEntity
    ) -> str:
        """Submit 전 Identifier 확정. 이미 있으면 변경 금지."""

        existing = (order.client_order_identifier or "").strip()
        if existing:
            return existing
        if (order.broker_code or "").upper() != "UPBIT":
            raise ValueError("Identifier only for UPBIT")
        uba = order.user_broker_account_id
        if not uba:
            raise ValueError(
                "user_broker_account_id required for Upbit identifier"
            )
        from stock_platform.broker.upbit.client_order_identifier import (
            UpbitClientOrderIdentifierFactory,
        )

        gen = int(order.submission_generation or 1)
        identifier = UpbitClientOrderIdentifierFactory.build(
            broker_code="UPBIT",
            user_broker_account_id=int(uba),
            local_order_id=int(order.order_id),
            submission_generation=gen,
        )
        order.client_order_identifier = identifier
        order.submission_generation = gen
        fp = UpbitClientOrderIdentifierFactory.order_fingerprint(
            user_broker_account_id=int(uba),
            strategy_id=order.strategy_code,
            signal_id=order.source_signal_id,
            market=self._local_market(order),
            side=order.side_code,
            order_type=order.order_type_code,
            price=(
                str(order.order_price)
                if order.order_price is not None
                else None
            ),
            volume=str(order.order_quantity),
            generation=gen,
        )
        order.order_fingerprint = fp
        self._audit(
            "UPBIT_IDENTIFIER_CREATED",
            order,
            {"identifier": identifier, "generation": gen},
        )
        self._session.flush()
        return identifier

    def approve_resubmit(
        self,
        order_id: int,
        *,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        """관리자 승인 재제출 — 새 Generation + 새 Identifier (자동 전송 아님)."""

        if self._settings.upbit_order_auto_resubmit_enabled:
            # 설정이 true여도 이 API는 준비만 — 실제 전송은 별도
            pass
        order = self._repo.get(order_id)
        if order is None:
            return {"status": "NOT_FOUND"}
        if order.status_code not in {
            OrderStatus.MANUAL_REVIEW_REQUIRED.value,
            OrderStatus.AMBIGUOUS_SUBMISSION.value,
            RemoteLookupStatus.NOT_FOUND_FINAL.value,
        } and order.remote_lookup_status != (
            RemoteLookupStatus.NOT_FOUND_FINAL.value
        ):
            if order.status_code != (
                OrderStatus.MANUAL_REVIEW_REQUIRED.value
            ):
                return {
                    "status": "INVALID_STATE",
                    "message": "Resubmit only after final not-found/manual",
                }
        if order.order_type_code == "MARKET":
            # 오래된 시장가 자동 재제출 차단 — 승인만 기록
            age = 0.0
            if order.ambiguous_since:
                age = (
                    datetime.now(timezone.utc) - order.ambiguous_since
                ).total_seconds()
            if age > 30:
                return {
                    "status": "MARKET_ORDER_STALE",
                    "message": "Stale market order resubmit blocked",
                }

        old_id = order.client_order_identifier
        old_gen = int(order.submission_generation or 1)
        order.submission_generation = old_gen + 1
        order.client_order_identifier = None  # ensure rebuild
        new_id = self.ensure_identifier(order)
        order.status_code = OrderStatus.CREATED.value
        order.ambiguous_since = None
        order.remote_lookup_status = RemoteLookupStatus.NONE.value
        order.remote_lookup_attempt_count = 0
        order.next_remote_lookup_at = None
        order.broker_order_id = None
        self._audit(
            "UPBIT_RESUBMIT_APPROVED",
            order,
            {
                "reason": reason[:200],
                "old_identifier": old_id,
                "old_generation": old_gen,
                "new_identifier": new_id,
                "new_generation": order.submission_generation,
                "actor": actor,
            },
        )
        self._session.flush()
        return {
            "status": "RESUBMIT_PREPARED",
            "order_id": int(order.order_id),
            "new_identifier": new_id,
            "submission_generation": int(order.submission_generation),
            "auto_submit": False,
        }

    def reject_resubmit(
        self, order_id: int, *, actor: str, reason: str
    ) -> dict[str, Any]:
        order = self._repo.get(order_id)
        if order is None:
            return {"status": "NOT_FOUND"}
        current = OrderStatus(order.status_code)
        if OrderStateMachine.can_transition(
            current, OrderStatus.FAILED
        ):
            self._repo.change_status(
                entity=order,
                new_status=OrderStatus.FAILED,
                actor=actor,
                reason_code="RESUBMIT_REJECTED",
                message=reason[:500],
                commit=False,
            )
        else:
            order.status_code = OrderStatus.FAILED.value
            order.failure_code = "RESUBMIT_REJECTED"
            order.failure_message = reason[:500]
        self._audit(
            "UPBIT_RESUBMIT_REJECTED",
            order,
            {"reason": reason[:200], "actor": actor},
        )
        self._session.flush()
        return {"status": "REJECTED", "order_id": order_id}

    def health_summary(self) -> dict[str, Any]:
        from sqlalchemy import func as sa_func

        def _count(status: str) -> int:
            return int(
                self._session.scalar(
                    select(sa_func.count()).select_from(
                        TradingOrderEntity
                    ).where(
                        TradingOrderEntity.broker_code == "UPBIT",
                        TradingOrderEntity.status_code == status,
                    )
                )
                or 0
            )

        oldest = self._session.scalar(
            select(TradingOrderEntity.ambiguous_since)
            .where(
                TradingOrderEntity.broker_code == "UPBIT",
                TradingOrderEntity.status_code.in_(
                    [
                        OrderStatus.AMBIGUOUS_SUBMISSION.value,
                        OrderStatus.REMOTE_LOOKUP_PENDING.value,
                    ]
                ),
                TradingOrderEntity.ambiguous_since.is_not(None),
            )
            .order_by(TradingOrderEntity.ambiguous_since.asc())
            .limit(1)
        )
        return {
            "ambiguous_count": _count(
                OrderStatus.AMBIGUOUS_SUBMISSION.value
            ),
            "lookup_pending_count": _count(
                OrderStatus.REMOTE_LOOKUP_PENDING.value
            ),
            "identity_conflict_count": _count(
                OrderStatus.IDENTITY_CONFLICT.value
            ),
            "manual_review_count": _count(
                OrderStatus.MANUAL_REVIEW_REQUIRED.value
            ),
            "oldest_ambiguous_since": (
                oldest.isoformat() if oldest else None
            ),
        }

    @staticmethod
    def _local_market(order: TradingOrderEntity) -> str:
        symbol = (order.symbol or "").upper()
        if "-" in symbol:
            return symbol
        return f"KRW-{symbol}"

    def _soft_compare_qty_price(
        self,
        order: TradingOrderEntity,
        payload: dict[str, Any],
    ) -> None:
        try:
            remote_vol = payload.get("volume")
            if remote_vol is not None and order.order_quantity is not None:
                rv = Decimal(str(remote_vol))
                if abs(rv - Decimal(str(order.order_quantity))) > Decimal(
                    "0.00000001"
                ):
                    # soft — mismatch는 conflict로 올리지 않고 audit만
                    self._audit(
                        "UPBIT_REMOTE_QTY_SOFT_DIFF",
                        order,
                        {
                            "local": str(order.order_quantity),
                            "remote": str(rv),
                        },
                    )
        except Exception:  # noqa: BLE001
            pass

    def _record_attempt(
        self,
        order: TradingOrderEntity,
        *,
        result_type: str,
        ambiguous: bool,
        external_uuid: str | None = None,
        correlation_note: str | None = None,
    ) -> None:
        from stock_platform.order.entities import (
            OrderSubmissionAttemptEntity,
        )

        row = OrderSubmissionAttemptEntity(
            order_id=int(order.order_id),
            client_order_identifier=order.client_order_identifier,
            attempt_number=int(
                order.submission_attempt_count or 1
            ),
            result_type=result_type,
            external_order_uuid=external_uuid,
            ambiguous=ambiguous,
            correlation_id=correlation_note,
        )
        self._session.add(row)

    def _audit(
        self,
        event: str,
        order: TradingOrderEntity,
        detail: dict[str, Any],
    ) -> None:
        try:
            from stock_platform.operation.calendar_audit import (
                audit_calendar_event,
            )

            # 범용 audit helper 재사용 (민감정보 없음)
            audit_calendar_event(
                event,
                actor="upbit_resolver",
                detail={
                    "order_id": int(order.order_id),
                    "uba": order.user_broker_account_id,
                    **detail,
                },
            )
        except Exception:  # noqa: BLE001
            pass
        self._session.add(
            TradingOrderStatusHistoryEntity(
                order_id=int(order.order_id),
                previous_status_code=order.status_code,
                current_status_code=order.status_code,
                reason_code=event[:100],
                message=event,
                actor="UPBIT_RESOLVER",
                detail_payload=detail,
            )
        )
