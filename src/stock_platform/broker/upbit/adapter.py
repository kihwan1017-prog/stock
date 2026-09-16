from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from stock_platform.broker.adapter import BrokerAdapter
from stock_platform.broker.idempotency import InMemoryIdempotencyStore
from stock_platform.broker.models import (
    BrokerOrderRequest,
    BrokerOrderResult,
    BrokerOrderStatus,
)
from stock_platform.broker.order_account_context import (
    require_user_broker_context_for_live,
)
from stock_platform.broker.upbit.order_client import UpbitOrderRestClient
from stock_platform.broker.upbit.order_mapper import UpbitOrderMapper
from stock_platform.broker.upbit.exceptions import (
    UpbitAmbiguousOrderResultError,
    UpbitError,
    UpbitRateLimitError,
)
from stock_platform.common.settings import Settings, get_settings


class UpbitBrokerAdapter(BrokerAdapter):
    """
    업비트 BrokerAdapter.

    - mock: 실호출 없이 수락 (UPBIT_USE_MOCK=true)
    - live: UPBIT_LIVE_ORDER_ENABLED + GLOBAL_LIVE_ORDER_ENABLED
    - 정정: 업비트 미지원 → 취소 후 신규 주문 (cancel+new)
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        order_client: UpbitOrderRestClient | None = None,
        idempotency_store: (
            InMemoryIdempotencyStore[BrokerOrderResult] | None
        ) = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = order_client or UpbitOrderRestClient(
            settings=self._settings
        )
        self._idempotency = (
            idempotency_store or InMemoryIdempotencyStore()
        )

    def submit_order(
        self,
        request: BrokerOrderRequest,
        **_kwargs,
    ) -> BrokerOrderResult:
        try:
            self._assert_order_allowed()
            self._assert_market_allowed(request)
            # LIVE 사용자 주문은 UBA 필수 — env 계좌를 사용자 계좌로 취급 금지
            require_user_broker_context_for_live(request)
        except PermissionError as exc:
            return BrokerOrderResult(
                accepted=False,
                status=BrokerOrderStatus.REJECTED,
                broker_order_id=None,
                submitted_at=datetime.now(timezone.utc),
                reject_code="LIVE_GATE_BLOCKED",
                reject_message=str(exc)[:500],
            )

        if self._settings.upbit_use_mock:
            # mock 재시도에도 동일 ID (client_order_id 기반)
            stable = "".join(
                ch
                for ch in request.client_order_id.upper()
                if ch.isalnum()
            )
            if len(stable) < 8:
                stable = f"{stable}{uuid4().hex}".upper()
            return self._mock_accept(
                broker_order_id=f"UPBIT-MOCK-{stable[:16]}"
            )

        try:
            body = UpbitOrderMapper.body(request)
            idempotency_key = str(
                _kwargs.get("idempotency_key")
                or f"SUBMIT:{request.client_order_id}"
            )

            def _send() -> BrokerOrderResult:
                payload = self._client.create_order(body)
                return self._to_result(payload)

            return self._idempotency.execute_once(
                key=idempotency_key,
                operation=_send,
            )
        except UpbitAmbiguousOrderResultError as exc:
            return BrokerOrderResult(
                accepted=False,
                status=BrokerOrderStatus.AMBIGUOUS,
                broker_order_id=None,
                submitted_at=datetime.now(timezone.utc),
                reject_code="AMBIGUOUS_ORDER_RESULT",
                reject_message=str(exc)[:500],
            )
        except UpbitRateLimitError as exc:
            # 429도 조회 우선 — Ambiguous로 분류
            return BrokerOrderResult(
                accepted=False,
                status=BrokerOrderStatus.AMBIGUOUS,
                broker_order_id=None,
                submitted_at=datetime.now(timezone.utc),
                reject_code="AMBIGUOUS_RATE_LIMITED",
                reject_message=str(exc)[:500],
            )
        except (ValueError, UpbitError) as exc:
            return BrokerOrderResult(
                accepted=False,
                status=BrokerOrderStatus.REJECTED,
                broker_order_id=None,
                submitted_at=datetime.now(timezone.utc),
                reject_code="UPBIT_REJECT",
                reject_message=str(exc)[:500],
            )

    def cancel_order(
        self,
        broker_order_id: str,
        **_kwargs,
    ) -> BrokerOrderResult:
        self._assert_order_allowed()
        idempotency_key = str(
            _kwargs.get("idempotency_key")
            or f"UPBIT-CANCEL:{broker_order_id}"
        )

        def _do() -> BrokerOrderResult:
            if self._settings.upbit_use_mock:
                return self._mock_accept(broker_order_id)
            try:
                payload = self._client.cancel_order(
                    uuid=broker_order_id
                )
                return self._to_result(payload)
            except UpbitError as exc:
                return BrokerOrderResult(
                    accepted=False,
                    status=BrokerOrderStatus.REJECTED,
                    broker_order_id=broker_order_id,
                    submitted_at=datetime.now(timezone.utc),
                    reject_code="UPBIT_CANCEL_REJECT",
                    reject_message=str(exc)[:500],
                )

        return self._idempotency.execute_once(
            key=idempotency_key,
            operation=_do,
        )

    def replace_order(
        self,
        broker_order_id: str,
        request: BrokerOrderRequest,
        **_kwargs,
    ) -> BrokerOrderResult:
        """업비트는 정정 API 없음 → 취소 후 신규 주문."""

        self._assert_order_allowed()
        key = str(
            _kwargs.get("idempotency_key")
            or f"UPBIT-REPLACE:{broker_order_id}:{request.client_order_id}"
        )

        def _do() -> BrokerOrderResult:
            cancel_result = self.cancel_order(
                broker_order_id,
                idempotency_key=f"{key}:cancel",
            )
            if not cancel_result.accepted:
                return cancel_result
            new_result = self.submit_order(request)
            if not new_result.accepted:
                return new_result
            # 호출측이 original/replaced 관계 저장
            return new_result

        return self._idempotency.execute_once(
            key=key,
            operation=_do,
        )

    def get_order(
        self,
        broker_order_id: str,
        **_kwargs,
    ) -> BrokerOrderResult:
        self._assert_order_allowed()
        if self._settings.upbit_use_mock:
            return self._mock_accept(broker_order_id)
        try:
            identifier = _kwargs.get("identifier")
            if identifier:
                payload = self._client.get_order(
                    identifier=str(identifier)
                )
            else:
                payload = self._client.get_order(
                    uuid=broker_order_id
                )
            return self._to_result(payload)
        except UpbitError as exc:
            return BrokerOrderResult(
                accepted=False,
                status=BrokerOrderStatus.FAILED,
                broker_order_id=broker_order_id,
                submitted_at=datetime.now(timezone.utc),
                reject_code="UPBIT_GET_FAIL",
                reject_message=str(exc)[:500],
            )

    def _assert_order_allowed(self) -> None:
        if self._settings.upbit_use_mock:
            return
        if not self._settings.global_live_order_enabled:
            raise PermissionError(
                "GLOBAL_LIVE_ORDER_ENABLED must be true"
            )
        if not self._settings.upbit_live_order_enabled:
            raise PermissionError(
                "UPBIT_LIVE_ORDER_ENABLED must be true"
            )

    def _assert_market_allowed(
        self,
        request: BrokerOrderRequest,
    ) -> None:
        allowed = self._settings.upbit_allowed_market_set()
        if not allowed:
            return
        market = UpbitOrderMapper.market(request)
        if market.upper() not in allowed:
            raise PermissionError(
                f"Market {market} is not in UPBIT_ALLOWED_MARKETS"
            )

    @staticmethod
    def _mock_accept(broker_order_id: str) -> BrokerOrderResult:
        return BrokerOrderResult(
            accepted=True,
            status=BrokerOrderStatus.ACCEPTED,
            broker_order_id=broker_order_id,
            submitted_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _to_result(payload: dict) -> BrokerOrderResult:
        uuid = (
            payload.get("uuid")
            or payload.get("order_id")
            or payload.get("identifier")
        )
        state = str(payload.get("state") or "").lower()
        # wait/watch/done/cancel 등
        rejected = state in {"cancel", "cancelled"} and not uuid
        accepted = uuid is not None and not rejected
        # create 응답에 state=wait 이면 수락
        if uuid and state in {"", "wait", "watch", "done", "cancel"}:
            accepted = True
        return BrokerOrderResult(
            accepted=accepted,
            status=(
                BrokerOrderStatus.ACCEPTED
                if accepted
                else BrokerOrderStatus.REJECTED
            ),
            broker_order_id=str(uuid) if uuid else None,
            submitted_at=datetime.now(timezone.utc),
            reject_code=None if accepted else "UPBIT_STATE",
            reject_message=(
                None
                if accepted
                else str(payload.get("state") or "rejected")
            ),
        )
