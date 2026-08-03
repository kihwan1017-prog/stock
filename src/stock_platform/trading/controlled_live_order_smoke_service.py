"""Controlled Upbit Live Order Smoke — Preview/Confirm (실주문은 명시 승인만)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.upbit.rules import (
    UPBIT_MIN_NOTIONAL_KRW,
    round_upbit_price,
    round_upbit_volume,
)
from stock_platform.common.settings import get_settings
from stock_platform.operation.runtime_preflight_service import (
    RuntimePreflightService,
    evaluate_preflight_freshness,
    sanitize_preflight_payload,
)
from stock_platform.order.live_safety_audit import emit_live_safety_audit
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.upbit_live_preflight_service import (
    UpbitLivePreflightService,
)
from stock_platform.trading.upbit_live_smoke_constants import (
    DEFAULT_ALLOWLIST,
    LIVE_ORDER_SMOKE_CONFIRMED,
    LIVE_ORDER_SMOKE_FAILED,
    LIVE_ORDER_SMOKE_PREFLIGHTED,
    LIVE_ORDER_SMOKE_PREVIEWED,
    LIVE_ORDER_SMOKE_SUBMITTED,
    MAX_SMOKE_AMOUNT,
    confirmation_text_for_side,
)
from stock_platform.trading.upbit_live_smoke_service import (
    UpbitLiveSmokeError,
    UpbitLiveSmokeService,
)


class ControlledLiveOrderSmokeError(ValueError):
    """Controlled smoke 거부."""


class ControlledLiveOrderSmokeService:
    """사용자 Guided Live Smoke — Preview는 주문 API 0, Confirm만 실경로."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _load_owned_upbit(
        self, *, uba_id: int, user_id: int
    ) -> UserBrokerAccount:
        uba = self._session.get(UserBrokerAccount, int(uba_id))
        if uba is None or getattr(uba, "deleted_at", None) is not None:
            raise ControlledLiveOrderSmokeError("UBA_NOT_FOUND")
        if int(uba.user_id) != int(user_id):
            raise ControlledLiveOrderSmokeError("FORBIDDEN")
        if str(uba.broker_code or "").upper() != "UPBIT":
            raise ControlledLiveOrderSmokeError("BROKER_NOT_UPBIT")
        return uba

    def preflight(
        self, *, uba_id: int, user_id: int, actor: str
    ) -> dict[str, Any]:
        self._load_owned_upbit(uba_id=uba_id, user_id=user_id)
        report = RuntimePreflightService(self._session).run_for_uba(
            user_broker_account_id=int(uba_id),
            mode="LIVE_ON",
            owner_user_id=int(user_id),
        )
        emit_live_safety_audit(
            self._session,
            event_type=LIVE_ORDER_SMOKE_PREFLIGHTED,
            actor=actor,
            run_id=None,
            user_id=int(user_id),
            account_id=int(uba_id),
            strategy_id=None,
            detail={
                "overall_status": report.get("overall_status"),
                "live_on_allowed": report.get("live_on_allowed"),
                "manual_order_allowed": report.get("manual_order_allowed"),
            },
            commit=False,
        )
        return report

    def preview(
        self,
        *,
        uba_id: int,
        user_id: int,
        actor: str,
        market: str,
        side: str,
        amount: Decimal | None,
        limit_price: Decimal | None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """주문 Adapter 호출 0 — Dry-run Preview + Risk 요약."""

        uba = self._load_owned_upbit(uba_id=uba_id, user_id=user_id)
        market_u = str(market or "").strip().upper()
        side_u = str(side or "").strip().upper()
        if side_u not in {"BUY", "SELL"}:
            raise ControlledLiveOrderSmokeError("INVALID_SIDE")

        settings = get_settings()
        allowlist_raw = str(
            getattr(settings, "upbit_live_smoke_allowlist", "") or ""
        )
        allowlist = {
            x.strip().upper()
            for x in allowlist_raw.split(",")
            if x.strip()
        } or set(DEFAULT_ALLOWLIST)
        if market_u not in allowlist:
            raise ControlledLiveOrderSmokeError("MARKET_NOT_ALLOWED")

        amount_d = Decimal(str(amount or UPBIT_MIN_NOTIONAL_KRW))
        if amount_d < UPBIT_MIN_NOTIONAL_KRW:
            raise ControlledLiveOrderSmokeError("BELOW_MIN_NOTIONAL")
        if amount_d > MAX_SMOKE_AMOUNT:
            raise ControlledLiveOrderSmokeError("AMOUNT_EXCEEDS_MAX")

        # 가격: 요청값 없으면 최소금액 기준 더미 LIMIT (네트워크 없이 static)
        price_d = (
            Decimal(str(limit_price))
            if limit_price is not None and Decimal(str(limit_price)) > 0
            else Decimal("1000000")
        )
        price_d = round_upbit_price(price_d)
        qty = round_upbit_volume(amount_d / price_d)
        fee_est = (amount_d * Decimal("0.0005")).quantize(Decimal("0.01"))

        uba_pf = RuntimePreflightService(self._session).run_for_uba(
            user_broker_account_id=int(uba_id),
            mode="LIVE_ON",
            owner_user_id=int(user_id),
        )
        freshness = evaluate_preflight_freshness(uba_pf.get("checked_at"))
        if uba_pf.get("overall_status") != "READY_FOR_LIVE":
            stage = "PREFLIGHT_BLOCKED"
        elif not freshness.get("fresh"):
            stage = "PREFLIGHT_STALE"
        else:
            stage = "PRE_SUBMIT_READY"

        order_preflight = UpbitLivePreflightService(self._session).run(
            user_broker_account_id=int(uba_id),
            market=market_u,
            side=side_u,
            amount=amount_d,
            limit_price=price_d,
            actor=actor,
            skip_live_network=True,
            purpose="dry_run",
        )

        preview_id = f"pv-{uuid.uuid4().hex[:16]}"
        idem = (
            str(idempotency_key).strip()
            if idempotency_key
            else f"preview:{preview_id}"
        )
        payload = sanitize_preflight_payload(
            {
                "stage": stage,
                "preview_id": preview_id,
                "idempotency_key": idem,
                "adapter_create_order_calls": 0,
                "broker_order_id": None,
                "user_broker_account_id": int(uba_id),
                "broker_code": "UPBIT",
                "masked_account": uba.masked_account_number,
                "market": market_u,
                "side": side_u,
                "order_type": "LIMIT",
                "quantity": str(qty),
                "limit_price": str(price_d),
                "estimated_amount": str(amount_d),
                "estimated_fee": str(fee_est),
                "min_notional_krw": str(UPBIT_MIN_NOTIONAL_KRW),
                "max_smoke_amount": str(MAX_SMOKE_AMOUNT),
                "confirmation_text_required": confirmation_text_for_side(
                    side_u
                ),
                "uba_preflight": uba_pf,
                "order_preflight": order_preflight.to_dict(),
                "risk_preview": {
                    "kill_switch": next(
                        (
                            c
                            for c in (uba_pf.get("checks") or [])
                            if c.get("code") == "RISK"
                        ),
                        {},
                    ),
                    "max_loss_hint": str(amount_d),
                },
                "gates": {
                    "live_on": bool(uba.live_order_enabled),
                    "arm_on": bool(uba.live_armed),
                    "arm_expires_at": (
                        uba.arm_expires_at.isoformat()
                        if uba.arm_expires_at
                        else None
                    ),
                    "shadow_mode": bool(
                        getattr(settings, "upbit_shadow_mode", False)
                    ),
                    "dry_run_mode": bool(
                        getattr(settings, "live_order_dry_run_enabled", False)
                    ),
                    "manual_order_allowed": bool(
                        uba_pf.get("manual_order_allowed")
                    ),
                    "freshness": freshness,
                },
                "execute_live_possible": (
                    stage == "PRE_SUBMIT_READY"
                    and bool(uba_pf.get("manual_order_allowed"))
                    and bool(order_preflight.live_execution_ready)
                ),
            }
        )
        emit_live_safety_audit(
            self._session,
            event_type=LIVE_ORDER_SMOKE_PREVIEWED,
            actor=actor,
            run_id=preview_id,
            user_id=int(user_id),
            account_id=int(uba_id),
            strategy_id=None,
            symbol=market_u,
            detail={
                "stage": stage,
                "side": side_u,
                "estimated_amount": str(amount_d),
                "adapter_create_order_calls": 0,
            },
            commit=False,
        )
        return payload

    def confirm(
        self,
        *,
        uba_id: int,
        user_id: int,
        actor: str,
        market: str,
        side: str,
        amount: Decimal,
        limit_price: Decimal,
        confirmation_text: str,
        arm_token: str | None,
        execute_live: bool,
        idempotency_key: str | None = None,
        preview_id: str | None = None,
    ) -> dict[str, Any]:
        """확인문구 필수. execute_live=False 이면 Dry-run만 (주문 API 0)."""

        self._load_owned_upbit(uba_id=uba_id, user_id=user_id)
        side_u = str(side or "").upper()
        required = confirmation_text_for_side(side_u)
        if str(confirmation_text or "").strip() != required:
            emit_live_safety_audit(
                self._session,
                event_type=LIVE_ORDER_SMOKE_FAILED,
                actor=actor,
                run_id=preview_id,
                user_id=int(user_id),
                account_id=int(uba_id),
                strategy_id=None,
                symbol=str(market).upper(),
                detail={"reason": "CONFIRMATION_TEXT_MISMATCH"},
                commit=False,
            )
            raise ControlledLiveOrderSmokeError("CONFIRMATION_TEXT_MISMATCH")

        # idempotency: 동일 키로 이미 SUBMITTED 이면 차단
        if idempotency_key:
            from stock_platform.trading.live_validation_entities import (
                LiveValidationRunEntity,
            )

            existing = self._session.scalar(
                select(LiveValidationRunEntity).where(
                    LiveValidationRunEntity.request_fingerprint
                    == hashlib.sha256(
                        str(idempotency_key).encode("utf-8")
                    ).hexdigest()
                )
            )
            if existing is not None and bool(existing.execute_live):
                raise ControlledLiveOrderSmokeError("DUPLICATE_IDEMPOTENCY_KEY")

        emit_live_safety_audit(
            self._session,
            event_type=LIVE_ORDER_SMOKE_CONFIRMED,
            actor=actor,
            run_id=preview_id,
            user_id=int(user_id),
            account_id=int(uba_id),
            strategy_id=None,
            symbol=str(market).upper(),
            detail={
                "side": side_u,
                "execute_live": bool(execute_live),
                "confirmation_matched": True,
            },
            commit=False,
        )

        if not execute_live:
            # Dry-run — Adapter 미호출
            result = UpbitLiveSmokeService(self._session).dry_run(
                user_broker_account_id=int(uba_id),
                market=str(market).upper(),
                side=side_u,
                amount=Decimal(str(amount)),
                limit_price=Decimal(str(limit_price)),
                actor=actor,
                arm_token=arm_token,
                skip_live_network=True,
            )
            result["adapter_create_order_calls"] = 0
            result["broker_order_id"] = None
            result["stage"] = "PRE_SUBMIT_READY"
            return sanitize_preflight_payload(result)

        # 실주문 경로 — 서버 Gate 재검증 후 기존 smoke execute 위임
        uba_pf = RuntimePreflightService(self._session).run_for_uba(
            user_broker_account_id=int(uba_id),
            mode="LIVE_ON",
            owner_user_id=int(user_id),
        )
        if not uba_pf.get("manual_order_allowed"):
            raise ControlledLiveOrderSmokeError("MANUAL_ORDER_NOT_ALLOWED")
        freshness = evaluate_preflight_freshness(uba_pf.get("checked_at"))
        if not freshness.get("fresh"):
            raise ControlledLiveOrderSmokeError("PREFLIGHT_STALE")

        # 기존 smoke는 CONFIRMATION_TEXT(레거시)를 검사하므로
        # 여기서는 confirmation 통과 후 레거시 텍스트를 내부 전달
        from stock_platform.trading.upbit_live_smoke_constants import (
            CONFIRMATION_TEXT,
        )

        try:
            result = UpbitLiveSmokeService(self._session).execute(
                user_broker_account_id=int(uba_id),
                market=str(market).upper(),
                side=side_u,
                amount=Decimal(str(amount)),
                limit_price=Decimal(str(limit_price)),
                actor=actor,
                arm_token=arm_token,
                execute_live=True,
                confirmation_text=CONFIRMATION_TEXT,
                skip_live_network=False,
            )
        except UpbitLiveSmokeError as exc:
            emit_live_safety_audit(
                self._session,
                event_type=LIVE_ORDER_SMOKE_FAILED,
                actor=actor,
                run_id=preview_id,
                user_id=int(user_id),
                account_id=int(uba_id),
                strategy_id=None,
                detail={"reason": str(exc)},
                commit=False,
            )
            raise ControlledLiveOrderSmokeError(str(exc)) from exc

        emit_live_safety_audit(
            self._session,
            event_type=LIVE_ORDER_SMOKE_SUBMITTED,
            actor=actor,
            run_id=str(result.get("run_id") or preview_id),
            user_id=int(user_id),
            account_id=int(uba_id),
            strategy_id=None,
            symbol=str(market).upper(),
            detail={"execute_live": True},
            commit=False,
        )
        return sanitize_preflight_payload(result)

    def get_run(
        self, *, uba_id: int, user_id: int, run_id: str
    ) -> dict[str, Any]:
        self._load_owned_upbit(uba_id=uba_id, user_id=user_id)
        row = UpbitLiveSmokeService(self._session).get_run(run_id)
        if int(row["user_broker_account_id"]) != int(uba_id):
            raise ControlledLiveOrderSmokeError("FORBIDDEN")
        return sanitize_preflight_payload({**row, "readonly": True})
