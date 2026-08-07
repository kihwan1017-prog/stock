from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
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
from stock_platform.broker.live_transition_validators import (
    APPROVAL_PHRASE_BY_BROKER,
    approval_phrase_for_broker,
    build_validator,
    resolve_broker_for_transition,
)
from stock_platform.common.settings import get_settings


class LiveTradingTransitionService:
    """실거래 전환 — broker-aware validate/request/approve."""

    # 레거시 호환 (KIWOOM)
    REQUIRED_APPROVAL_PHRASE = APPROVAL_PHRASE_BY_BROKER["KIWOOM"]

    def __init__(self, session: Session) -> None:
        self._session = session

    def validate(
        self,
        *,
        max_order_amount: Decimal,
        max_daily_loss: Decimal,
        paper_validation_approved: bool,
        scope: str = "BROKER",
        broker_code: str | None = None,
        user_broker_account_id: int | None = None,
    ) -> LiveTransitionPlan:
        try:
            resolved_broker, resolved_scope, uba_id = (
                resolve_broker_for_transition(
                    self._session,
                    scope=scope,
                    broker_code=broker_code,
                    user_broker_account_id=user_broker_account_id,
                )
            )
        except PermissionError as exc:
            checks = [
                LiveTransitionCheckResult(
                    code=LiveTransitionCheckCode.UNSUPPORTED_BROKER,
                    status=LiveTransitionCheckStatus.FAIL,
                    message=str(exc),
                    detail={},
                )
            ]
            return LiveTransitionPlan(
                ready=False,
                generated_at=datetime.now(timezone.utc),
                max_order_amount=max_order_amount,
                max_daily_loss=max_daily_loss,
                checks=checks,
                broker_code=str(broker_code or "UNKNOWN").upper(),
                scope=str(scope or "BROKER").upper(),
                user_broker_account_id=user_broker_account_id,
            )

        validator = build_validator(self._session, resolved_broker)
        return validator.validate(
            max_order_amount=max_order_amount,
            max_daily_loss=max_daily_loss,
            paper_validation_approved=paper_validation_approved,
            scope=resolved_scope,
            user_broker_account_id=uba_id,
        )

    def request_transition(
        self,
        *,
        requested_by: str,
        max_order_amount: Decimal,
        max_daily_loss: Decimal,
        paper_validation_approved: bool,
        scope: str = "BROKER",
        broker_code: str | None = None,
        user_broker_account_id: int | None = None,
    ) -> LiveTradingTransitionEntity:
        plan = self.validate(
            max_order_amount=max_order_amount,
            max_daily_loss=max_daily_loss,
            paper_validation_approved=paper_validation_approved,
            scope=scope,
            broker_code=broker_code,
            user_broker_account_id=user_broker_account_id,
        )

        entity = LiveTradingTransitionEntity(
            requested_by=requested_by,
            max_order_amount=max_order_amount,
            max_daily_loss=max_daily_loss,
            validation_payload={
                "ready": plan.ready,
                "broker_code": plan.broker_code,
                "scope": plan.scope,
                "user_broker_account_id": plan.user_broker_account_id,
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
            environment_code=plan.broker_code,
            broker_code=plan.broker_code,
            scope=plan.scope,
            user_broker_account_id=plan.user_broker_account_id,
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
        reason: str | None = None,
        ttl_hours: int | None = None,
        scope: str | None = None,
        broker_code: str | None = None,
        user_broker_account_id: int | None = None,
    ) -> LiveTradingTransitionEntity:
        entity = self._session.get(
            LiveTradingTransitionEntity,
            transition_id,
        )
        if entity is None:
            raise LookupError("Live trading transition not found")

        if not entity.validation_payload.get("ready"):
            raise PermissionError(
                "Live transition validation has failures"
            )

        # 승인 시 scope/UBA는 request 스냅샷을 기본으로 하고,
        # 클라이언트가 넘기면 재해석(UBA DB broker 신뢰)
        payload = dict(entity.validation_payload or {})
        scope_u = str(
            scope
            or payload.get("scope")
            or entity.scope
            or "BROKER"
        ).strip().upper()
        uba_raw = (
            user_broker_account_id
            if user_broker_account_id is not None
            else payload.get("user_broker_account_id")
            if payload.get("user_broker_account_id") is not None
            else entity.user_broker_account_id
        )
        client_broker = (
            broker_code
            or payload.get("broker_code")
            or entity.broker_code
            or "KIWOOM"
        )
        resolved_broker, resolved_scope, uba_id = (
            resolve_broker_for_transition(
                self._session,
                scope=scope_u,
                broker_code=str(client_broker),
                user_broker_account_id=(
                    int(uba_raw) if uba_raw is not None else None
                ),
            )
        )

        required_phrase = approval_phrase_for_broker(resolved_broker)
        if not secrets.compare_digest(approval_phrase, required_phrase):
            raise PermissionError("Live approval phrase is invalid")

        # UPBIT ACCOUNT: 승인 직전 재검증 (Fail Closed)
        if resolved_broker == "UPBIT":
            replan = self.validate(
                max_order_amount=entity.max_order_amount,
                max_daily_loss=entity.max_daily_loss,
                paper_validation_approved=True,
                scope=resolved_scope,
                broker_code=resolved_broker,
                user_broker_account_id=uba_id,
            )
            if not replan.ready:
                raise PermissionError(
                    "UPBIT live transition re-validation failed"
                )

        settings = get_settings()
        hours = int(
            ttl_hours
            if ttl_hours is not None
            else settings.live_activation_ttl_hours
        )
        if hours < 1:
            raise PermissionError(
                "LIVE activation TTL must be >= 1 hour (no indefinite)"
            )
        now = datetime.now(timezone.utc)

        entity.approved_by = approved_by
        entity.approval_phrase_hash = hashlib.sha256(
            approval_phrase.encode("utf-8")
        ).hexdigest()
        entity.approved_at = now
        entity.expires_at = now + timedelta(hours=hours)
        entity.enabled = True
        entity.activation_status = "ACTIVE"
        entity.reason = (reason or "").strip() or None
        entity.scope = resolved_scope
        entity.broker_code = resolved_broker
        entity.environment_code = resolved_broker
        entity.user_broker_account_id = uba_id
        payload["approved_broker_code"] = resolved_broker
        payload["approved_scope"] = resolved_scope
        payload["approved_user_broker_account_id"] = uba_id
        entity.validation_payload = payload

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
            raise LookupError("Live trading transition not found")

        entity.enabled = False
        entity.disabled_at = datetime.now(timezone.utc)
        entity.disable_reason = reason
        entity.activation_status = "DISABLED"

        self._session.commit()
        self._session.refresh(entity)
        return entity

    @staticmethod
    def transition_matches_dispatch(
        entity: LiveTradingTransitionEntity,
        *,
        broker_code: str | None,
        user_broker_account_id: int | None,
    ) -> bool:
        """UBA/broker scope 격리 — 타 UBA Activation으로 dispatch 금지."""

        want_broker = str(broker_code or "").strip().upper()
        if not want_broker:
            return False
        got_broker = str(entity.broker_code or "").strip().upper()
        if got_broker != want_broker:
            return False

        scope = str(entity.scope or "BROKER").strip().upper()
        if scope == "ACCOUNT":
            if user_broker_account_id is None:
                return False
            return int(entity.user_broker_account_id or 0) == int(
                user_broker_account_id
            )
        if scope == "BROKER":
            # UPBIT BROKER-wide 금지 (ACCOUNT만 허용)
            if want_broker == "UPBIT":
                return False
            # KIWOOM 레거시: BROKER scope는 uba 무관 허용
            return True
        return False

    def get_active(
        self,
        *,
        broker_code: str | None = None,
        user_broker_account_id: int | None = None,
    ) -> LiveTradingTransitionEntity | None:
        """활성·미만료 Activation. broker/UBA 지정 시 scope 일치 필수."""

        rows = list(
            self._session.scalars(
                select(LiveTradingTransitionEntity)
                .where(LiveTradingTransitionEntity.enabled.is_(True))
                .order_by(
                    LiveTradingTransitionEntity.approved_at.desc()
                )
            )
        )
        now = datetime.now(timezone.utc)
        for entity in rows:
            expires = entity.expires_at
            if expires is None:
                entity.enabled = False
                entity.activation_status = "EXPIRED"
                entity.disabled_at = now
                entity.disable_reason = (
                    "Activation missing expires_at (indefinite forbidden)"
                )
                self._session.commit()
                continue
            exp = expires
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp <= now:
                entity.enabled = False
                entity.activation_status = "EXPIRED"
                entity.disabled_at = now
                entity.disable_reason = "Activation expired"
                self._session.commit()
                continue

            if broker_code is None and user_broker_account_id is None:
                # 레거시 무필터: 첫 유효 ACTIVE (KIWOOM 호환)
                return entity

            if self.transition_matches_dispatch(
                entity,
                broker_code=broker_code,
                user_broker_account_id=user_broker_account_id,
            ):
                return entity
        return None

    def list_history(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[LiveTradingTransitionEntity]:
        stmt = (
            select(LiveTradingTransitionEntity)
            .order_by(
                LiveTradingTransitionEntity.requested_at.desc()
            )
            .offset(max(0, offset))
            .limit(max(1, min(limit, 100)))
        )
        return list(self._session.scalars(stmt))

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
