from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.live_transition_entities import (
    LiveTradingTransitionEntity,
)
from stock_platform.broker.live_transition_models import (
    LiveTransitionCheckCode,
    LiveTransitionCheckResult,
    LiveTransitionCheckStatus,
    LiveTransitionPlan,
)
from stock_platform.common.settings import get_settings


class LiveTradingTransitionService:
    """
    실거래 전환 전에 환경변수와 위험한도를 검사하고
    별도의 수동 승인 기록을 요구한다.
    """

    REQUIRED_APPROVAL_PHRASE = (
        "ENABLE KIWOOM LIVE TRADING"
    )

    def __init__(self, session: Session) -> None:
        self._session = session

    def validate(
        self,
        *,
        max_order_amount: Decimal,
        max_daily_loss: Decimal,
        paper_validation_approved: bool,
    ) -> LiveTransitionPlan:
        settings = get_settings()
        checks: list[LiveTransitionCheckResult] = []

        self._add_bool_check(
            checks,
            LiveTransitionCheckCode.MOCK_MODE_DISABLED,
            settings.kiwoom_use_mock is False,
            "KIWOOM_USE_MOCK=false",
        )
        self._add_bool_check(
            checks,
            LiveTransitionCheckCode.LIVE_ORDER_ENABLED,
            settings.kiwoom_live_order_enabled is True,
            "KIWOOM_LIVE_ORDER_ENABLED=true",
        )
        self._add_bool_check(
            checks,
            LiveTransitionCheckCode.ACCOUNT_NUMBER_PRESENT,
            bool(settings.kiwoom_account_number.strip()),
            "KIWOOM_ACCOUNT_NUMBER configured",
        )
        self._add_bool_check(
            checks,
            LiveTransitionCheckCode.APP_CREDENTIALS_PRESENT,
            bool(settings.kiwoom_app_key.strip())
            and bool(settings.kiwoom_secret_key.strip()),
            "Kiwoom application credentials configured",
        )
        self._add_bool_check(
            checks,
            LiveTransitionCheckCode.WEBSOCKET_CONFIGURED,
            bool(settings.kiwoom_order_ws_subscribe_json.strip()),
            "Kiwoom order WebSocket subscription configured",
        )
        self._add_bool_check(
            checks,
            LiveTransitionCheckCode.RECOVERY_TRADING_DISABLED,
            settings.kiwoom_recovery_start_trading is False,
            (
                "Automatic strategy/order start remains disabled "
                "during initial live validation"
            ),
        )
        self._add_bool_check(
            checks,
            LiveTransitionCheckCode.PAPER_VALIDATION_APPROVED,
            paper_validation_approved,
            "Paper validation explicitly approved",
        )

        order_limit_ok = (
            max_order_amount > 0
            and max_order_amount <= Decimal("100000")
        )
        checks.append(
            LiveTransitionCheckResult(
                code=(
                    LiveTransitionCheckCode
                    .MAX_ORDER_LIMIT_VALID
                ),
                status=(
                    LiveTransitionCheckStatus.PASS
                    if order_limit_ok
                    else LiveTransitionCheckStatus.FAIL
                ),
                message=(
                    "Initial live order limit must be "
                    "between 1 and 100,000 KRW"
                ),
                detail={
                    "max_order_amount": str(
                        max_order_amount
                    )
                },
            )
        )

        daily_loss_ok = (
            max_daily_loss > 0
            and max_daily_loss <= Decimal("300000")
        )
        checks.append(
            LiveTransitionCheckResult(
                code=(
                    LiveTransitionCheckCode
                    .DAILY_LOSS_LIMIT_VALID
                ),
                status=(
                    LiveTransitionCheckStatus.PASS
                    if daily_loss_ok
                    else LiveTransitionCheckStatus.FAIL
                ),
                message=(
                    "Initial live daily loss limit must be "
                    "between 1 and 300,000 KRW"
                ),
                detail={
                    "max_daily_loss": str(
                        max_daily_loss
                    )
                },
            )
        )

        checks.append(
            LiveTransitionCheckResult(
                code=(
                    LiveTransitionCheckCode
                    .MANUAL_APPROVAL_REQUIRED
                ),
                status=LiveTransitionCheckStatus.WARNING,
                message=(
                    "Validation alone never enables live trading. "
                    "A separate approval phrase is required."
                ),
                detail={},
            )
        )

        ready = all(
            item.status != LiveTransitionCheckStatus.FAIL
            for item in checks
        )

        return LiveTransitionPlan(
            ready=ready,
            generated_at=datetime.now(timezone.utc),
            max_order_amount=max_order_amount,
            max_daily_loss=max_daily_loss,
            checks=checks,
        )

    def request_transition(
        self,
        *,
        requested_by: str,
        max_order_amount: Decimal,
        max_daily_loss: Decimal,
        paper_validation_approved: bool,
    ) -> LiveTradingTransitionEntity:
        plan = self.validate(
            max_order_amount=max_order_amount,
            max_daily_loss=max_daily_loss,
            paper_validation_approved=(
                paper_validation_approved
            ),
        )

        entity = LiveTradingTransitionEntity(
            requested_by=requested_by,
            max_order_amount=max_order_amount,
            max_daily_loss=max_daily_loss,
            validation_payload={
                "ready": plan.ready,
                "checks": [
                    {
                        "code": item.code.value,
                        "status": item.status.value,
                        "message": item.message,
                        "detail": item.detail,
                    }
                    for item in plan.checks
                ],
            },
            enabled=False,
        )
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def approve_transition(
        self,
        *,
        transition_id: int,
        approved_by: str,
        approval_phrase: str,
    ) -> LiveTradingTransitionEntity:
        entity = self._session.get(
            LiveTradingTransitionEntity,
            transition_id,
        )
        if entity is None:
            raise LookupError(
                "Live trading transition not found"
            )

        if not entity.validation_payload.get("ready"):
            raise PermissionError(
                "Live transition validation has failures"
            )

        if not secrets.compare_digest(
            approval_phrase,
            self.REQUIRED_APPROVAL_PHRASE,
        ):
            raise PermissionError(
                "Live approval phrase is invalid"
            )

        entity.approved_by = approved_by
        entity.approval_phrase_hash = hashlib.sha256(
            approval_phrase.encode("utf-8")
        ).hexdigest()
        entity.approved_at = datetime.now(timezone.utc)
        entity.enabled = True

        self._session.commit()
        self._session.refresh(entity)
        return entity

    def disable_transition(
        self,
        *,
        transition_id: int,
        reason: str,
    ) -> LiveTradingTransitionEntity:
        entity = self._session.get(
            LiveTradingTransitionEntity,
            transition_id,
        )
        if entity is None:
            raise LookupError(
                "Live trading transition not found"
            )

        entity.enabled = False
        entity.disabled_at = datetime.now(timezone.utc)
        entity.disable_reason = reason

        self._session.commit()
        self._session.refresh(entity)
        return entity

    def get_active(
        self,
    ) -> LiveTradingTransitionEntity | None:
        return self._session.scalar(
            select(LiveTradingTransitionEntity)
            .where(
                LiveTradingTransitionEntity.enabled.is_(
                    True
                )
            )
            .order_by(
                LiveTradingTransitionEntity.approved_at.desc()
            )
            .limit(1)
        )

    @staticmethod
    def _add_bool_check(
        checks: list[LiveTransitionCheckResult],
        code: LiveTransitionCheckCode,
        passed: bool,
        message: str,
    ) -> None:
        checks.append(
            LiveTransitionCheckResult(
                code=code,
                status=(
                    LiveTransitionCheckStatus.PASS
                    if passed
                    else LiveTransitionCheckStatus.FAIL
                ),
                message=message,
                detail={},
            )
        )
