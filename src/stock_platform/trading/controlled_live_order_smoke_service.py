"""Controlled Upbit Live Order Smoke — Preview/Confirm (실주문은 명시 승인만)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.fee_policy import UpbitFeePolicy
from stock_platform.broker.upbit.auth import build_query_hash
from stock_platform.broker.upbit.market_snapshot import (
    UpbitMarketQuoteError,
    fetch_market_snapshots,
)
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
    LIVE_ORDER_SMOKE_ORDER_TESTED,
    LIVE_ORDER_SMOKE_PREFLIGHTED,
    LIVE_ORDER_SMOKE_PREVIEWED,
    LIVE_ORDER_SMOKE_SUBMITTED,
    MAX_SMOKE_AMOUNT,
    ORDER_TEST_TTL_SECONDS,
    confirmation_text_for_side,
)
from stock_platform.trading.upbit_live_smoke_service import (
    UpbitLiveSmokeError,
    UpbitLiveSmokeService,
)

class ControlledLiveOrderSmokeError(ValueError):
    """Controlled smoke 거부 (비즈니스 Risk 거절 포함)."""

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
        from stock_platform.trading.failure_code_normalize import (
            normalize_failure_code,
        )

        # INVALID_TRANSITION 등 콜론 포함 레거시 코드는 원문 유지(str)
        raw = str(code or "").strip()
        if ":" in raw or raw.startswith("PREFLIGHT_NOT_READY:"):
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

_FEE = UpbitFeePolicy()
ZERO = Decimal("0")


def build_order_test_request_diagnostics(body: dict[str, Any]) -> dict[str, Any]:
    """Order Test 요청 진단 (시크릿 미포함). Body/JWT/Header/URI 판정용."""

    items = [(str(k), str(v)) for k, v in body.items()]
    query_string = urlencode(items, doseq=True)
    query_bytes = query_string.encode("utf-8")
    qh, alg = build_query_hash(body)
    # 공식 시장가 매수 예제 (문서/샘플 키 순서)
    official_price_buy_keys = ("market", "side", "price", "ord_type")
    our_keys = tuple(body.keys())
    return {
        "uri": "POST /v1/orders/test",
        "create_order_uri": "POST /v1/orders",
        "request_body": dict(body),
        "query_string_for_hash": query_string,
        "query_string_utf8_bytes_hex": query_bytes.hex(),
        "query_string_utf8_len": len(query_bytes),
        "query_hash_sha512": qh,
        "query_hash_alg": alg,
        "jwt_claims_template": {
            "access_key": "<redacted>",
            "nonce": "<uuid>",
            "query_hash": qh,
            "query_hash_alg": alg,
        },
        "headers": {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Bearer <redacted JWT HS256>",
        },
        "body_keys_order": list(our_keys),
        "official_market_buy_key_order": list(official_price_buy_keys),
        "key_order_matches_official_market_buy": our_keys == official_price_buy_keys
        or (
            body.get("ord_type") == "price"
            and set(our_keys) == set(official_price_buy_keys)
            and "volume" not in body
        ),
        "volume_present": "volume" in body,
        "create_order_vs_test": {
            "auth_path_identical": True,
            "param_source": "same JSON body dict for JWT query_hash",
            "uri_diff_only": "/v1/orders vs /v1/orders/test",
        },
    }


def compute_upbit_order_preview(
    *,
    market: str,
    side: str,
    order_type: str,
    amount: Decimal,
    limit_price: Decimal | None,
    reference_price: Decimal,
) -> dict[str, Any]:
    """업비트 주문 바디와 동일한 Preview 수량·금액 산출 (create_order 없음).

    - MARKET BUY: ord_type=price, price=KRW 금액, volume 미전송
      → 표시 수량 = amount / 현재가 (ROUND_DOWN)
    - LIMIT BUY/SELL: ord_type=limit, volume=qty, price=지정가
      → qty = amount / limit_price
    - MARKET SELL: ord_type=market, volume만
      → qty = amount / 현재가 (금액→수량 환산)
    """

    market_u = str(market or "").strip().upper()
    side_u = str(side or "").strip().upper()
    type_u = str(order_type or "").strip().upper()
    if side_u not in {"BUY", "SELL"}:
        raise ControlledLiveOrderSmokeError("INVALID_SIDE")
    if type_u not in {"MARKET", "LIMIT"}:
        raise ControlledLiveOrderSmokeError("INVALID_ORDER_TYPE")

    amount_d = Decimal(str(amount))
    if amount_d <= ZERO:
        raise ControlledLiveOrderSmokeError("INVALID_AMOUNT")

    ref = Decimal(str(reference_price))
    if ref <= ZERO:
        raise ControlledLiveOrderSmokeError("TICKER_NO_PRICE")
    ref = round_upbit_price(ref)

    upbit_side = "bid" if side_u == "BUY" else "ask"
    fee_est = _FEE.fee_amount(notional=amount_d, is_maker=False)

    if type_u == "MARKET" and side_u == "BUY":
        # 실주문: price=KRW 주문금액, volume 없음
        # 공식 샘플 키 순서: market → side → price → ord_type
        qty = round_upbit_volume(amount_d / ref)
        estimated_notional = amount_d
        return {
            "order_type": "MARKET",
            "side": side_u,
            "market": market_u,
            "upbit_side": upbit_side,
            "upbit_ord_type": "price",
            "quantity": qty,
            "quantity_note": "estimated_from_trade_price",
            "limit_price": None,
            "reference_price": ref,
            "requested_amount": amount_d,
            "estimated_amount": estimated_notional,
            "estimated_fee": fee_est,
            "broker_body": {
                "market": market_u,
                "side": upbit_side,
                "price": str(amount_d),
                "ord_type": "price",
            },
            "volume_sent": False,
        }

    if type_u == "MARKET" and side_u == "SELL":
        qty = round_upbit_volume(amount_d / ref)
        if qty <= ZERO:
            raise ControlledLiveOrderSmokeError("QTY_TOO_SMALL")
        estimated_notional = (qty * ref).quantize(Decimal("0.01"))
        fee_est = _FEE.fee_amount(notional=estimated_notional, is_maker=False)
        return {
            "order_type": "MARKET",
            "side": side_u,
            "market": market_u,
            "upbit_side": upbit_side,
            "upbit_ord_type": "market",
            "quantity": qty,
            "quantity_note": "volume_from_krw_via_trade_price",
            "limit_price": None,
            "reference_price": ref,
            "requested_amount": amount_d,
            "estimated_amount": estimated_notional,
            "estimated_fee": fee_est,
            "broker_body": {
                "market": market_u,
                "side": upbit_side,
                "volume": str(qty),
                "ord_type": "market",
            },
            "volume_sent": True,
        }

    # LIMIT BUY / LIMIT SELL — 공식 샘플 키 순서: market→side→volume→price→ord_type
    if limit_price is not None and Decimal(str(limit_price)) > ZERO:
        price_d = round_upbit_price(Decimal(str(limit_price)))
    else:
        # 지정가 미입력 시 현재가로 미리보기 (주문 전송 전 참고)
        price_d = ref
    if price_d <= ZERO:
        raise ControlledLiveOrderSmokeError("INVALID_LIMIT_PRICE")

    qty = round_upbit_volume(amount_d / price_d)
    if qty <= ZERO:
        raise ControlledLiveOrderSmokeError("QTY_TOO_SMALL")
    estimated_notional = (qty * price_d).quantize(Decimal("0.01"))
    fee_est = _FEE.fee_amount(notional=estimated_notional, is_maker=True)
    return {
        "order_type": "LIMIT",
        "side": side_u,
        "market": market_u,
        "upbit_side": upbit_side,
        "upbit_ord_type": "limit",
        "quantity": qty,
        "quantity_note": "volume_equals_amount_div_limit_price",
        "limit_price": price_d,
        "reference_price": ref,
        "requested_amount": amount_d,
        "estimated_amount": estimated_notional,
        "estimated_fee": fee_est,
        "broker_body": {
            "market": market_u,
            "side": upbit_side,
            "volume": str(qty),
            "price": str(price_d),
            "ord_type": "limit",
        },
        "volume_sent": True,
    }


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

    @staticmethod
    def _assert_runtime_stopped() -> None:
        try:
            from stock_platform.realtime.runtime import (
                realtime_execution_runner,
                realtime_strategy_runner,
            )

            exec_running = bool(
                (realtime_execution_runner.status() or {}).get("running")
            )
            strat_running = bool(
                (realtime_strategy_runner.status() or {}).get("running")
            )
        except Exception:  # noqa: BLE001
            return
        if exec_running or strat_running:
            raise ControlledLiveOrderSmokeError("RUNTIME_RUNNING")

    @staticmethod
    def build_order_test_fingerprint(
        *,
        uba_id: int,
        market: str,
        side: str,
        ord_type: str,
        volume: str,
        price: str,
        amount: str,
    ) -> str:
        raw = "|".join(
            [
                str(int(uba_id)),
                str(market).upper(),
                str(side).upper(),
                str(ord_type).lower(),
                str(volume),
                str(price),
                str(amount),
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def order_test(
        self,
        *,
        uba_id: int,
        user_id: int,
        actor: str,
        market: str,
        side: str,
        amount: Decimal | None,
        limit_price: Decimal | None,
        order_type: str | None = None,
        identifier: str | None = None,
        skip_network: bool = False,
        smoke_buy_run_id: str | None = None,
        order_client: Any | None = None,
        reference_price: Decimal | None = None,
    ) -> dict[str, Any]:
        """공식 POST /v1/orders/test — 실주문·수수료 없음. create_order 미호출.

        Preview와 동일한 업비트 broker_body(ord_type=price|market|limit)를 사용한다.
        """

        uba = self._load_owned_upbit(uba_id=uba_id, user_id=user_id)
        self._assert_runtime_stopped()
        market_u = str(market or "").strip().upper()
        side_u = str(side or "").strip().upper()
        type_u = str(order_type or "MARKET").strip().upper()
        if side_u not in {"BUY", "SELL"}:
            raise ControlledLiveOrderSmokeError("INVALID_SIDE")
        if type_u not in {"MARKET", "LIMIT"}:
            raise ControlledLiveOrderSmokeError("INVALID_ORDER_TYPE")
        if side_u == "SELL" and not smoke_buy_run_id:
            raise ControlledLiveOrderSmokeError(
                "EXISTING_POSITION_SELL_BLOCKED"
            )

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

        amount_d = Decimal(str(amount)) if amount is not None else Decimal("0")
        tested_at = datetime.now(timezone.utc)
        expires_at = tested_at + timedelta(seconds=ORDER_TEST_TTL_SECONDS)
        validation_errors: list[str] = []
        chance: dict[str, Any] = {}
        test_response: dict[str, Any] = {}
        create_order_calls = 0
        test_order_calls = 0
        http_diag: dict[str, Any] = {}
        fault_layer = "UNKNOWN"

        client = order_client
        if client is None and not skip_network:
            from stock_platform.broker.credential_adapter_factory import (
                build_upbit_settings_from_vault,
            )
            from stock_platform.broker.credential_vault_service import (
                BrokerCredentialVaultService,
            )
            from stock_platform.broker.upbit.order_client import (
                UpbitOrderRestClient,
            )

            resolved = BrokerCredentialVaultService(
                self._session
            ).resolve_for_runtime(
                int(uba_id),
                expected_broker="UPBIT",
                require_verified=True,
                touch_last_used=False,
            )
            vault_settings = build_upbit_settings_from_vault(resolved)
            client = UpbitOrderRestClient(
                settings=vault_settings,
                user_broker_account_id=int(uba_id),
            )

        try:
            if client is not None:
                chance = client.get_order_chance(market=market_u) or {}
            elif skip_network:
                chance = {
                    "bid_fee": "0.0005",
                    "ask_fee": "0.0005",
                    "market": {
                        "id": market_u,
                        "bid": {
                            "currency": "KRW",
                            "min_total": str(UPBIT_MIN_NOTIONAL_KRW),
                        },
                        "ask": {"currency": market_u.split("-")[-1]},
                    },
                    "bid_account": {"balance": "1000000"},
                    "ask_account": {"balance": "0"},
                }
        except Exception as exc:  # noqa: BLE001
            validation_errors.append(f"chance:{exc.__class__.__name__}")

        # min_total — chance 응답 우선
        min_total = None
        try:
            market_meta = chance.get("market") if isinstance(chance, dict) else {}
            if isinstance(market_meta, dict):
                bid = market_meta.get("bid") or {}
                if isinstance(bid, dict) and bid.get("min_total") is not None:
                    min_total = Decimal(str(bid.get("min_total")))
        except Exception:  # noqa: BLE001
            min_total = None
        if min_total is None:
            min_total = UPBIT_MIN_NOTIONAL_KRW
            validation_errors.append("min_total_fallback_used")

        if amount_d <= 0:
            amount_d = min_total
        if amount_d < min_total:
            validation_errors.append("BELOW_MIN_NOTIONAL")
        if amount_d > MAX_SMOKE_AMOUNT:
            validation_errors.append("AMOUNT_EXCEEDS_MAX")

        # 현재가 (Preview와 동일)
        if reference_price is not None and Decimal(str(reference_price)) > ZERO:
            ref_price = Decimal(str(reference_price))
        else:
            try:
                ticker, _book = fetch_market_snapshots(market_u)
                ref_price = Decimal(str(ticker.trade_price))
            except Exception:  # noqa: BLE001
                # LIMIT이면 limit_price로 폴백
                if (
                    type_u == "LIMIT"
                    and limit_price is not None
                    and Decimal(str(limit_price)) > ZERO
                ):
                    ref_price = Decimal(str(limit_price))
                else:
                    raise ControlledLiveOrderSmokeError("TICKER_UNAVAILABLE")

        quote = compute_upbit_order_preview(
            market=market_u,
            side=side_u,
            order_type=type_u,
            amount=amount_d,
            limit_price=limit_price,
            reference_price=ref_price,
        )
        body = dict(quote["broker_body"])
        if identifier:
            body["identifier"] = str(identifier)[:36]
        upbit_ord_type = str(quote["upbit_ord_type"])
        volume_str = str(body.get("volume") or "")
        price_str = str(body.get("price") or "")
        request_diag = build_order_test_request_diagnostics(body)

        fee_rate = Decimal(
            str(
                (chance.get("bid_fee") if side_u == "BUY" else chance.get("ask_fee"))
                or "0.0005"
            )
        )
        estimated_fee = (amount_d * fee_rate).quantize(Decimal("0.01"))

        test_passed = False
        if validation_errors and any(
            e in {"BELOW_MIN_NOTIONAL", "AMOUNT_EXCEEDS_MAX"}
            for e in validation_errors
        ):
            test_passed = False
            fault_layer = "VALIDATION"
        elif skip_network and client is None:
            test_passed = not any(
                e.startswith("chance:") for e in validation_errors
            )
            test_response = {
                "uuid": f"test-mock-{uuid.uuid4().hex[:8]}",
                "side": body.get("side"),
                "ord_type": upbit_ord_type,
                "mock": True,
            }
            test_order_calls = 0
            fault_layer = "NONE" if test_passed else "VALIDATION"
        elif client is not None:
            try:
                if hasattr(client, "create_order"):
                    pass
                test_response = client.test_create_order(body) or {}
                test_order_calls = 1
                test_passed = True
                fault_layer = "NONE"
            except Exception as exc:  # noqa: BLE001
                validation_errors.append(f"order_test:{exc.__class__.__name__}")
                http_diag = {
                    "http_status": getattr(exc, "http_status", None),
                    "error_code": getattr(exc, "error_code", None),
                    "error_message": str(exc)[:800],
                    "raw_response_excerpt": str(
                        getattr(exc, "payload", None)
                        or getattr(exc, "detail", None)
                        or getattr(exc, "error_code", None)
                        or ""
                    )[:800],
                }
                detail = getattr(exc, "payload", None) or getattr(
                    exc, "detail", None
                )
                if isinstance(detail, dict):
                    err_name = str(
                        (detail.get("error") or {}).get("name")
                        or detail.get("error_code")
                        or ""
                    )
                    if err_name:
                        validation_errors.append(err_name)
                    http_diag["raw_response_body"] = detail
                # 400 InvalidRequest → Body 가능성 높음 (JWT면 보통 401)
                status_code = getattr(exc, "http_status", None)
                if status_code == 401:
                    fault_layer = "JWT"
                elif status_code == 404:
                    fault_layer = "URI"
                elif status_code == 400:
                    fault_layer = "BODY"
                elif status_code in {415, 406}:
                    fault_layer = "HEADER"
                else:
                    fault_layer = "BODY_OR_SERVER"
                test_passed = False
                test_order_calls = 1

        fingerprint = self.build_order_test_fingerprint(
            uba_id=int(uba_id),
            market=market_u,
            side=side_u,
            ord_type=upbit_ord_type,
            volume=volume_str,
            price=price_str,
            amount=str(amount_d),
        )
        status = "ORDER_TEST_PASSED" if test_passed else "ORDER_TEST_FAILED"
        available = None
        try:
            if side_u == "BUY":
                available = (chance.get("bid_account") or {}).get("balance")
            else:
                available = (chance.get("ask_account") or {}).get("balance")
        except Exception:  # noqa: BLE001
            available = None

        # 판정 요약
        if not test_passed and fault_layer == "UNKNOWN":
            if "volume" in body and upbit_ord_type == "price":
                fault_layer = "BODY"
            elif upbit_ord_type == "limit" and type_u == "MARKET":
                fault_layer = "BODY"

        payload = sanitize_preflight_payload(
            {
                "status": status,
                "test_passed": bool(test_passed),
                "validation_errors": validation_errors,
                "minimum_order_amount": str(min_total),
                "available_balance": available,
                "allowed_order_type": ["price", "market", "limit"],
                "order_type": type_u,
                "upbit_ord_type": upbit_ord_type,
                "reference_price": str(quote["reference_price"]),
                "price_unit": price_str or str(quote["reference_price"]),
                "estimated_fee": str(estimated_fee),
                "tested_at": tested_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "ttl_seconds": ORDER_TEST_TTL_SECONDS,
                "freshness_required": True,
                "order_test_fingerprint": fingerprint,
                "request": {
                    "market": market_u,
                    "side": side_u,
                    "order_type": type_u,
                    "ord_type": upbit_ord_type,
                    "volume": volume_str or None,
                    "price": price_str or None,
                    "amount": str(amount_d),
                    "identifier": body.get("identifier"),
                    "broker_body": body,
                },
                "diagnostics": {
                    **request_diag,
                    "http": http_diag,
                    "fault_layer": fault_layer,
                    "verdict": (
                        "BODY mismatch fixed path uses Preview-identical "
                        f"ord_type={upbit_ord_type}; fault_layer={fault_layer}"
                    ),
                },
                "chance_summary": {
                    "bid_fee": chance.get("bid_fee"),
                    "ask_fee": chance.get("ask_fee"),
                    "market_id": (
                        (chance.get("market") or {}).get("id")
                        if isinstance(chance.get("market"), dict)
                        else None
                    ),
                },
                "upbit_test_response": {
                    "uuid": test_response.get("uuid"),
                    "side": test_response.get("side"),
                    "ord_type": test_response.get("ord_type"),
                    "mock": bool(test_response.get("mock")),
                },
                "adapter_create_order_calls": create_order_calls,
                "adapter_test_order_calls": test_order_calls,
                "user_broker_account_id": int(uba_id),
                "masked_account": uba.masked_account_number,
                "endpoint": "POST /v1/orders/test",
                "real_order_endpoint": "POST /v1/orders",
                "separated_from_real_order": True,
            }
        )
        emit_live_safety_audit(
            self._session,
            event_type=LIVE_ORDER_SMOKE_ORDER_TESTED,
            actor=actor,
            run_id=fingerprint[:16],
            user_id=int(user_id),
            account_id=int(uba_id),
            strategy_id=None,
            symbol=market_u,
            detail={
                "status": status,
                "test_passed": test_passed,
                "adapter_create_order_calls": 0,
                "adapter_test_order_calls": test_order_calls,
            },
            commit=False,
        )
        return payload

    def _assert_order_test_fresh(
        self,
        *,
        uba_id: int,
        market: str,
        side: str,
        amount: Decimal,
        limit_price: Decimal,
        order_test_fingerprint: str | None,
        order_test_tested_at: str | None,
        order_type: str | None = None,
        reference_price: Decimal | None = None,
    ) -> None:
        if not order_test_fingerprint or not order_test_tested_at:
            raise ControlledLiveOrderSmokeError("ORDER_TEST_REQUIRED")
        type_u = str(order_type or "MARKET").strip().upper()
        amount_d = Decimal(str(amount))
        ref = (
            Decimal(str(reference_price))
            if reference_price is not None and Decimal(str(reference_price)) > ZERO
            else (
                Decimal(str(limit_price))
                if limit_price is not None and Decimal(str(limit_price)) > ZERO
                else Decimal("0")
            )
        )
        if ref <= ZERO:
            raise ControlledLiveOrderSmokeError("ORDER_TEST_STALE_INPUT_CHANGED")
        quote = compute_upbit_order_preview(
            market=str(market).upper(),
            side=str(side).upper(),
            order_type=type_u,
            amount=amount_d,
            limit_price=limit_price,
            reference_price=ref,
        )
        body = quote["broker_body"]
        expected = self.build_order_test_fingerprint(
            uba_id=int(uba_id),
            market=str(market).upper(),
            side=str(side).upper(),
            ord_type=str(quote["upbit_ord_type"]),
            volume=str(body.get("volume") or ""),
            price=str(body.get("price") or ""),
            amount=str(amount_d),
        )
        if expected != str(order_test_fingerprint):
            raise ControlledLiveOrderSmokeError("ORDER_TEST_STALE_INPUT_CHANGED")
        fr = evaluate_preflight_freshness(
            order_test_tested_at, ttl_seconds=ORDER_TEST_TTL_SECONDS
        )
        if not fr.get("fresh"):
            raise ControlledLiveOrderSmokeError("ORDER_TEST_STALE")

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
        order_type: str | None = None,
        idempotency_key: str | None = None,
        reference_price: Decimal | None = None,
    ) -> dict[str, Any]:
        """주문 Adapter 호출 0 — Dry-run Preview + Risk 요약.

        수량/금액은 업비트 주문 규약과 동일하게 산출한다.
        공개 ticker만 조회하며 create_order는 호출하지 않는다.
        """

        uba = self._load_owned_upbit(uba_id=uba_id, user_id=user_id)
        market_u = str(market or "").strip().upper()
        side_u = str(side or "").strip().upper()
        type_u = str(order_type or "MARKET").strip().upper()
        if side_u not in {"BUY", "SELL"}:
            raise ControlledLiveOrderSmokeError("INVALID_SIDE")
        if type_u not in {"MARKET", "LIMIT"}:
            raise ControlledLiveOrderSmokeError("INVALID_ORDER_TYPE")

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

        # 현재가: 공개 ticker (create_order 없음). 테스트용 reference_price 주입 가능.
        if reference_price is not None and Decimal(str(reference_price)) > ZERO:
            ref_price = Decimal(str(reference_price))
            ticker_meta: dict[str, Any] = {
                "source": "injected",
                "trade_price": str(ref_price),
            }
        else:
            try:
                ticker, _book = fetch_market_snapshots(market_u)
                ref_price = Decimal(str(ticker.trade_price))
                ticker_meta = {
                    "source": "upbit_public_ticker",
                    **ticker.to_dict(),
                }
            except UpbitMarketQuoteError as exc:
                raise ControlledLiveOrderSmokeError(
                    f"TICKER_UNAVAILABLE:{exc.reason_code}"
                ) from exc
            except Exception as exc:  # noqa: BLE001
                raise ControlledLiveOrderSmokeError(
                    "TICKER_UNAVAILABLE"
                ) from exc

        if ref_price <= ZERO:
            raise ControlledLiveOrderSmokeError("TICKER_NO_PRICE")

        quote = compute_upbit_order_preview(
            market=market_u,
            side=side_u,
            order_type=type_u,
            amount=amount_d,
            limit_price=limit_price,
            reference_price=ref_price,
        )
        qty = quote["quantity"]
        price_d = quote["limit_price"]
        fee_est = quote["estimated_fee"]
        amount_est = quote["estimated_amount"]

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

        # Risk/order preflight는 LIMIT 가격 또는 현재가 기준 참고값
        preflight_price = (
            Decimal(str(price_d))
            if price_d is not None
            else Decimal(str(ref_price))
        )
        order_preflight = UpbitLivePreflightService(self._session).run(
            user_broker_account_id=int(uba_id),
            market=market_u,
            side=side_u,
            amount=amount_d,
            limit_price=preflight_price,
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
                "order_type": type_u,
                "upbit_ord_type": quote["upbit_ord_type"],
                "quantity": str(qty),
                "quantity_note": quote["quantity_note"],
                "volume_sent": bool(quote["volume_sent"]),
                "limit_price": (
                    str(price_d) if price_d is not None else None
                ),
                "reference_price": str(quote["reference_price"]),
                "requested_amount": str(amount_d),
                "estimated_amount": str(amount_est),
                "estimated_fee": str(fee_est),
                "min_notional_krw": str(UPBIT_MIN_NOTIONAL_KRW),
                "max_smoke_amount": str(MAX_SMOKE_AMOUNT),
                "ticker": ticker_meta,
                "broker_body": quote["broker_body"],
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
                "order_type": type_u,
                "estimated_amount": str(amount_est),
                "quantity": str(qty),
                "reference_price": str(quote["reference_price"]),
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
        order_test_fingerprint: str | None = None,
        order_test_tested_at: str | None = None,
        smoke_buy_run_id: str | None = None,
    ) -> dict[str, Any]:
        """확인문구 필수. execute_live=False 이면 Dry-run만 (주문 API 0)."""

        self._load_owned_upbit(uba_id=uba_id, user_id=user_id)
        self._assert_runtime_stopped()
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

        if execute_live and side_u == "SELL" and not smoke_buy_run_id:
            raise ControlledLiveOrderSmokeError(
                "EXISTING_POSITION_SELL_BLOCKED"
            )

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
            # Dry-run — Adapter 미호출 (ORDER_TEST 없이도 Preview Confirm 가능)
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

        # 실주문 — ORDER_TEST_PASSED + FRESH 필수
        self._assert_order_test_fresh(
            uba_id=int(uba_id),
            market=str(market),
            side=side_u,
            amount=Decimal(str(amount)),
            limit_price=Decimal(str(limit_price)),
            order_test_fingerprint=order_test_fingerprint,
            order_test_tested_at=order_test_tested_at,
            order_type="MARKET",
            reference_price=Decimal(str(limit_price)),
        )

        # 서버 Gate 재검증 후 기존 smoke execute 위임
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
                run_id=getattr(exc, "run_id", None) or preview_id,
                user_id=int(user_id),
                account_id=int(uba_id),
                strategy_id=None,
                detail={
                    "reason": getattr(exc, "code", str(exc)),
                    "error_code": getattr(exc, "code", str(exc)),
                    "details": list(getattr(exc, "details", []) or []),
                    "order_submitted": bool(
                        getattr(exc, "order_submitted", False)
                    ),
                    "create_order_calls": int(
                        getattr(exc, "create_order_calls", 0) or 0
                    ),
                    "status": getattr(exc, "status_code", None) or "FAILED",
                    "broker_order_status": "NOT_SUBMITTED",
                },
                commit=False,
            )
            raise ControlledLiveOrderSmokeError(
                getattr(exc, "code", str(exc)),
                message=getattr(exc, "message", None),
                details=list(getattr(exc, "details", []) or []),
                http_status=int(getattr(exc, "http_status", 400) or 400),
                order_submitted=bool(
                    getattr(exc, "order_submitted", False)
                ),
                create_order_calls=int(
                    getattr(exc, "create_order_calls", 0) or 0
                ),
                run_id=getattr(exc, "run_id", None),
                correlation_id=getattr(exc, "correlation_id", None)
                or getattr(exc, "run_id", None),
                status_code=getattr(exc, "status_code", None),
            ) from exc

        # SUBMITTED audit = 실제 QUEUED 성공만 (false-success 금지)
        queued_ok = (
            bool(result.get("queued"))
            or str(result.get("reason_code") or "") == "QUEUED"
        ) and result.get("order_id") is not None and result.get(
            "outbox_id"
        ) is not None
        if not queued_ok:
            emit_live_safety_audit(
                self._session,
                event_type=LIVE_ORDER_SMOKE_FAILED,
                actor=actor,
                run_id=str(result.get("run_id") or preview_id),
                user_id=int(user_id),
                account_id=int(uba_id),
                strategy_id=None,
                detail={
                    "error_code": "LIVE_SMOKE_NOT_QUEUED",
                    "status": "FAILED",
                    "broker_order_status": "NOT_SUBMITTED",
                    "order_submitted": False,
                    "create_order_calls": 0,
                    "reason_code": result.get("reason_code"),
                    "order_id": result.get("order_id"),
                    "outbox_id": result.get("outbox_id"),
                },
                commit=False,
            )
            raise ControlledLiveOrderSmokeError(
                "LIVE_SMOKE_NOT_QUEUED",
                message="실주문 요청이 큐에 저장되지 않았습니다.",
                http_status=500,
                order_submitted=False,
                create_order_calls=0,
                run_id=str(result.get("run_id") or "") or None,
                status_code="FAILED",
            )

        emit_live_safety_audit(
            self._session,
            event_type=LIVE_ORDER_SMOKE_SUBMITTED,
            actor=actor,
            run_id=str(result.get("run_id") or preview_id),
            user_id=int(user_id),
            account_id=int(uba_id),
            strategy_id=None,
            symbol=str(market).upper(),
            detail={
                "execute_live": True,
                "order_test_required": True,
                "reason_code": "QUEUED",
                "order_id": result.get("order_id"),
                "outbox_id": result.get("outbox_id"),
                "status": "QUEUED",
                "broker_order_status": result.get("broker_order_status")
                or "NOT_SUBMITTED",
            },
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
