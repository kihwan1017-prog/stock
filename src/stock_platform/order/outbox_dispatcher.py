from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.broker.adapter import BrokerAdapter
from stock_platform.broker.models import (
    BrokerOrderRequest,
    BrokerOrderSide,
    BrokerOrderType,
)
from stock_platform.broker.paper.adapter import PaperBrokerAdapter
from stock_platform.order.outbox_adapter_resolver import (
    resolve_outbox_adapter,
)
from stock_platform.order.outbox_models import (
    OutboxEventType,
)


class OrderOutboxDispatcher:
    def __init__(
        self,
        adapter: BrokerAdapter | None = None,
        *,
        session: Session | None = None,
    ) -> None:
        # 하위 호환: 고정 어댑터를 넘기면 라우팅 없이 사용
        self._fixed_adapter = adapter
        self._session = session

    def dispatch(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        session: Session | None = None,
    ) -> dict[str, Any]:
        event = OutboxEventType(event_type)
        active_session = session or self._session

        # LIVE Shadow — Adapter resolve / Broker HTTP 이전 차단
        from stock_platform.order.live_shadow import (
            shadow_block_dispatch_result,
            should_block_live_broker_call,
        )

        if should_block_live_broker_call(payload):
            return shadow_block_dispatch_result(event_type=event.value)

        adapter = (
            self._fixed_adapter
            if self._fixed_adapter is not None
            and "broker_code" not in payload
            and "environment" not in payload
            else resolve_outbox_adapter(
                payload,
                session=active_session,
                default_adapter=(
                    self._fixed_adapter
                    or PaperBrokerAdapter()
                ),
            )
        )

        if event == OutboxEventType.SUBMIT_ORDER:
            # KI-TRD-02 완화 — 이미 broker_order_id 있으면 재전송 금지
            existing_broker_id = str(
                payload.get("broker_order_id") or ""
            ).strip()
            if existing_broker_id:
                return {
                    "accepted": True,
                    "status": "ALREADY_SUBMITTED",
                    "broker_order_id": existing_broker_id,
                    "reject_code": None,
                    "reject_message": None,
                    "submitted_at": None,
                    "duplicate_suppressed": True,
                }
            # LIVE Outbox는 session+Factory 게이트 필수
            env = str(payload.get("environment") or "PAPER").upper()
            if env == "LIVE" and active_session is None:
                raise PermissionError(
                    "LIVE outbox SUBMIT requires DB session"
                )
            request = self._to_order_request(payload)
            # STEP 8-5-12 — Upbit Identifier를 전송 전 DB에 확정
            if (
                active_session is not None
                and str(payload.get("broker_code", "")).upper()
                == "UPBIT"
                and get_settings_safe_identifier_enabled()
            ):
                request = self._ensure_upbit_identifier(
                    active_session, payload, request
                )
            submit = adapter.submit_order
            try:
                result = submit(
                    request,
                    idempotency_key=idempotency_key,
                )
            except TypeError:
                result = submit(request)
        elif event == OutboxEventType.CANCEL_ORDER:
            result = adapter.cancel_order(
                str(payload["broker_order_id"]),
                exchange_code=str(
                    payload.get(
                        "exchange_code",
                        "KRX",
                    )
                ),
                symbol=str(payload["symbol"]),
                cancel_quantity=Decimal(
                    str(payload["cancel_quantity"])
                ),
                idempotency_key=idempotency_key,
            )
        elif event == OutboxEventType.REPLACE_ORDER:
            result = adapter.replace_order(
                str(payload["broker_order_id"]),
                self._to_order_request(payload),
                idempotency_key=idempotency_key,
            )
        else:
            raise ValueError(
                f"Unsupported outbox event: {event_type}"
            )

        return {
            "accepted": result.accepted,
            "status": result.status.value,
            "broker_order_id": (
                result.broker_order_id
            ),
            "reject_code": result.reject_code,
            "reject_message": result.reject_message,
            "submitted_at": (
                result.submitted_at.isoformat()
            ),
        }

    @staticmethod
    def _to_order_request(
        payload: dict[str, Any],
    ) -> BrokerOrderRequest:
        price = payload.get("price")
        side_raw = str(payload["side"]).upper()
        type_raw = str(payload["order_type"]).upper()
        uba_raw = payload.get("user_broker_account_id")
        owner_raw = payload.get("owner_user_id")
        return BrokerOrderRequest(
            client_order_id=str(
                payload["client_order_id"]
            ),
            account_id=int(payload["account_id"]),
            exchange_code=str(
                payload.get("exchange_code", "KRX")
            ),
            symbol=str(payload["symbol"]),
            side=BrokerOrderSide(side_raw),
            order_type=BrokerOrderType(type_raw),
            quantity=Decimal(
                str(payload["quantity"])
            ),
            price=(
                None
                if price in (None, "")
                else Decimal(str(price))
            ),
            time_in_force=str(
                payload.get("time_in_force", "DAY")
            ),
            user_broker_account_id=(
                None if uba_raw in (None, "") else int(uba_raw)
            ),
            broker_code=(
                str(payload["broker_code"]).upper()
                if payload.get("broker_code")
                else None
            ),
            account_type=str(
                payload.get("account_type")
                or payload.get("environment")
                or "PAPER"
            ).upper(),
            external_account_ref=(
                None
                if payload.get("external_account_ref") in (None, "")
                else str(payload.get("external_account_ref"))
            ),
            credential_ref=(
                None
                if payload.get("credential_ref") in (None, "")
                else str(payload.get("credential_ref"))
            ),
            owner_user_id=(
                None if owner_raw in (None, "") else int(owner_raw)
            ),
            uses_system_shared_credential=bool(
                payload.get("uses_system_shared_credential")
            ),
            upbit_client_identifier=(
                None
                if payload.get("upbit_client_identifier") in (None, "")
                else str(payload.get("upbit_client_identifier"))
            ),
        )

    def _ensure_upbit_identifier(
        self,
        session: Session,
        payload: dict[str, Any],
        request: BrokerOrderRequest,
    ) -> BrokerOrderRequest:
        from stock_platform.broker.upbit.ambiguous_resolver import (
            UpbitAmbiguousOrderResolver,
        )

        order_id = int(payload["order_id"])
        resolver = UpbitAmbiguousOrderResolver(session)
        claimed = resolver.claim_submitting(order_id)
        order = claimed or resolver._repo.get(order_id)
        if order is None:
            return request
        identifier = resolver.ensure_identifier(order)
        if order.first_submitted_at is None:
            from datetime import datetime, timezone

            order.first_submitted_at = datetime.now(timezone.utc)
        session.flush()
        # payload에도 반영 (재시도 시 동일 identifier)
        payload["upbit_client_identifier"] = identifier
        return BrokerOrderRequest(
            client_order_id=request.client_order_id,
            exchange_code=request.exchange_code,
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            quantity=request.quantity,
            price=request.price,
            account_id=request.account_id,
            time_in_force=request.time_in_force,
            user_broker_account_id=request.user_broker_account_id,
            broker_code=request.broker_code,
            account_type=request.account_type,
            external_account_ref=request.external_account_ref,
            credential_ref=request.credential_ref,
            owner_user_id=request.owner_user_id,
            uses_system_shared_credential=(
                request.uses_system_shared_credential
            ),
            upbit_client_identifier=identifier,
        )


def get_settings_safe_identifier_enabled() -> bool:
    try:
        from stock_platform.common.settings import get_settings

        return bool(
            get_settings().upbit_client_order_identifier_enabled
        )
    except Exception:  # noqa: BLE001
        return True
