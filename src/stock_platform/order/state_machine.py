from __future__ import annotations

from stock_platform.order.models import OrderStatus
from stock_platform.order.state_models import InvalidOrderStateTransition


class OrderStateMachine:
    _TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
        OrderStatus.CREATED: {
            OrderStatus.PENDING,
            OrderStatus.SUBMITTING,
            OrderStatus.FAILED,
        },
        OrderStatus.PENDING: {
            OrderStatus.SUBMITTING,
            OrderStatus.SENT,
            OrderStatus.CANCEL_REQUESTED,
            # intent 이후 outbox AMBIGUOUS — 원격 조회로 전환
            OrderStatus.AMBIGUOUS_SUBMISSION,
            # 미전송 LIVE 내부 폐기 — 브로커 미호출 terminal
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED,
        },
        OrderStatus.SUBMITTING: {
            OrderStatus.SENT,
            OrderStatus.ACCEPTED,
            OrderStatus.AMBIGUOUS_SUBMISSION,
            OrderStatus.REJECTED,
            OrderStatus.FAILED,
        },
        OrderStatus.SENT: {
            OrderStatus.ACCEPTED,
            OrderStatus.CANCEL_REQUESTED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED,
            OrderStatus.AMBIGUOUS_SUBMISSION,
        },
        OrderStatus.ACCEPTED: {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_REQUESTED,
            OrderStatus.REPLACE_REQUESTED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED,
        },
        OrderStatus.PARTIALLY_FILLED: {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_REQUESTED,
            OrderStatus.REPLACE_REQUESTED,
            OrderStatus.FAILED,
        },
        OrderStatus.CANCEL_REQUESTED: {
            OrderStatus.CANCELLED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.FAILED,
        },
        OrderStatus.REPLACE_REQUESTED: {
            OrderStatus.REPLACED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_REQUESTED,
            OrderStatus.FAILED,
        },
        OrderStatus.AMBIGUOUS_SUBMISSION: {
            OrderStatus.REMOTE_LOOKUP_PENDING,
            OrderStatus.MANUAL_REVIEW_REQUIRED,
            OrderStatus.IDENTITY_CONFLICT,
            OrderStatus.ACCEPTED,
            OrderStatus.SENT,
            OrderStatus.FAILED,
        },
        OrderStatus.REMOTE_LOOKUP_PENDING: {
            OrderStatus.ACCEPTED,
            OrderStatus.SENT,
            OrderStatus.MANUAL_REVIEW_REQUIRED,
            OrderStatus.IDENTITY_CONFLICT,
            OrderStatus.AMBIGUOUS_SUBMISSION,
            OrderStatus.FAILED,
        },
        OrderStatus.IDENTITY_CONFLICT: {
            OrderStatus.MANUAL_REVIEW_REQUIRED,
            OrderStatus.FAILED,
        },
        OrderStatus.MANUAL_REVIEW_REQUIRED: {
            OrderStatus.FAILED,
            OrderStatus.CREATED,  # 재제출 준비
            OrderStatus.REMOTE_LOOKUP_PENDING,
        },
        OrderStatus.FILLED: set(),
        OrderStatus.CANCELLED: set(),
        OrderStatus.REPLACED: set(),
        OrderStatus.REJECTED: set(),
        # FAILED는 운영상 terminal이지만, 브로커 체결/취소 증거가 있으면
        # fill-sync·reconcile 복구 전이를 허용한다 (오분류 FAILED 복구).
        OrderStatus.FAILED: {
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
        },
    }

    @classmethod
    def can_transition(cls, current: OrderStatus, target: OrderStatus) -> bool:
        return target in cls._TRANSITIONS.get(current, set())

    @classmethod
    def validate_transition(cls, *, current: OrderStatus, target: OrderStatus) -> None:
        # 명시적 recovery edge(FAILED→FILLED 등)는 TERMINAL 여부와 무관하게 허용
        if cls.can_transition(current, target):
            return
        raise InvalidOrderStateTransition(current=current, target=target)

    @classmethod
    def transition(cls, *, current: OrderStatus, target: OrderStatus) -> OrderStatus:
        cls.validate_transition(current=current, target=target)
        return target

    @classmethod
    def allowed_targets(cls, current: OrderStatus) -> set[OrderStatus]:
        return set(cls._TRANSITIONS.get(current, set()))
