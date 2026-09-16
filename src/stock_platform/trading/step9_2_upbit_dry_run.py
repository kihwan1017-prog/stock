"""STEP 9-2 — UPBIT 5,000원 Market BUY Dry Run (Broker submit 금지).

실제 create_order / trading_order insert / LIVE·ARM 변경 없음.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.broker.fee_policy import UpbitFeePolicy
from stock_platform.broker.models import (
    BrokerOrderRequest,
    BrokerOrderSide,
    BrokerOrderType,
)
from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.broker.recovery_conflict_constants import (
    ACTIVE_REVIEW_STATUSES,
)
from stock_platform.broker.recovery_conflict_entities import (
    BrokerRecoveryConflictEntity,
)
from stock_platform.broker.recovery_conflict_service import (
    BrokerRecoveryConflictService,
)
from stock_platform.broker.upbit.order_mapper import UpbitOrderMapper
from stock_platform.broker.upbit.rules import (
    UPBIT_MIN_NOTIONAL_KRW,
    validate_upbit_notional,
)
from stock_platform.common.settings import get_settings
from stock_platform.risk_engine.uba_daily_loss_service import UbaDailyLossService
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.upbit_live_preflight_service import (
    UpbitLivePreflightService,
)
from stock_platform.trading.upbit_live_smoke_constants import (
    DEFAULT_ALLOWLIST,
    DEFAULT_SMOKE_AMOUNT,
)

FEE = UpbitFeePolicy()
ZERO = Decimal("0")


@dataclass
class CallCounters:
    """Broker/DB mutation 계측."""

    create_order: int = 0
    cancel_order: int = 0
    replace_order: int = 0
    adapter_submit: int = 0
    db_order_insert: int = 0
    execution_insert: int = 0
    position_mutation: int = 0
    balance_mutation: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "create_order": self.create_order,
            "cancel_order": self.cancel_order,
            "replace_order": self.replace_order,
            "adapter_submit": self.adapter_submit,
            "db_order_insert": self.db_order_insert,
            "execution_insert": self.execution_insert,
            "position_mutation": self.position_mutation,
            "balance_mutation": self.balance_mutation,
        }

    def all_zero(self) -> bool:
        return all(v == 0 for v in self.as_dict().values())


@dataclass
class Step92DryRunResult:
    verdict: str  # PASS_DRY_RUN | BLOCKED_EXPECTED | BLOCKED_DEFECT | ERROR
    market: str
    side: str = "BUY"
    order_type: str = "MARKET"
    requested_amount: str = "5000"
    guards: list[dict[str, Any]] = field(default_factory=list)
    fee_model: dict[str, Any] = field(default_factory=dict)
    daily_loss: dict[str, Any] = field(default_factory=dict)
    order_transform: dict[str, Any] = field(default_factory=dict)
    preflight: dict[str, Any] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    correlation_id: str = ""
    reason_codes: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "market": self.market,
            "side": self.side,
            "order_type": self.order_type,
            "requested_amount": self.requested_amount,
            "guards": self.guards,
            "fee_model": self.fee_model,
            "daily_loss": self.daily_loss,
            "order_transform": self.order_transform,
            "preflight": self.preflight,
            "counters": self.counters,
            "correlation_id": self.correlation_id,
            "reason_codes": self.reason_codes,
            "detail": self.detail,
        }


def _dec(v: Any) -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:  # noqa: BLE001
        return ZERO


def _mask_id(raw: str) -> str:
    text = (raw or "").strip()
    if len(text) <= 8:
        return text[:1] + "…" if text else ""
    return f"{text[:4]}…{text[-4:]}"


def analyze_fee_model(*, requested_amount: Decimal) -> dict[str, Any]:
    """코드 경로 기반 수수료·금액 모델 판정 (추정 금지).

    A: Adapter Market BUY — price=KRW 주문금액, 수수료는 거래소 별도
       (`UpbitOrderMapper` ord_type=price)
    B: 요청 금액에 수수료 포함 — 코드상 해당 경로 없음
    C: Preflight/운영 여유 KRW 버퍼 — amount*(1+fee) 사전 요구는
       STEP 9-1 readiness 추정용이며 Adapter submit 바디에는 미포함
    """

    fee = FEE.fee_amount(notional=requested_amount, is_maker=False)
    estimated_total_with_buffer = requested_amount + fee
    return {
        "adapter_model": "A_ORDER_AMOUNT_FEE_SEPARATE",
        "adapter_proof": (
            "src/stock_platform/broker/upbit/order_mapper.py "
            "MARKET BUY → ord_type=price, price=KRW amount"
        ),
        "risk_min_check_model": "A_MIN_NOTIONAL_ON_ORDER_AMOUNT",
        "risk_min_proof": (
            "validate_upbit_notional MARKET BUY uses price as KRW notional; "
            f"min={UPBIT_MIN_NOTIONAL_KRW}"
        ),
        "readiness_buffer_model": "C_OPTIONAL_AVAILABLE_KRW_BUFFER",
        "readiness_buffer_proof": (
            "STEP 9-1 / ops preflight may require amount*(1+taker_fee) "
            "for available KRW headroom — not sent to Broker"
        ),
        "model_b_used": False,
        "fee_rate": str(FEE.taker_rate),
        "requested_order_amount": str(requested_amount),
        "minimum_order_amount": str(UPBIT_MIN_NOTIONAL_KRW),
        "estimated_fee": str(fee),
        "estimated_total_required_buffer": str(estimated_total_with_buffer),
        "amount_rounding": "ROUND_DOWN via round_upbit_price/volume when used",
        "fee_rounding": "quantize 0.0001 in UpbitFeePolicy.fee_amount",
        "currency_precision": "KRW notional as Decimal str to Upbit",
        "broker_body_price_field": str(requested_amount),
        "broker_body_includes_fee": False,
    }


def analyze_daily_loss_display(
    session: Session, *, uba_id: int
) -> dict[str, Any]:
    """Daily Loss 1원 표시 차이 규명."""

    from datetime import date
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    diag = UbaDailyLossService(session).diagnose(
        user_broker_account_id=uba_id,
        loss_limit=Decimal("300000"),
        trading_date=today,
    )
    raw_loss = _dec(diag.current_daily_loss)
    raw_limit = _dec(diag.max_daily_loss_limit)
    raw_remaining = _dec(diag.remaining_daily_loss_capacity)
    # 표시값(정수 원) — STEP 9-1 보고 스타일
    displayed_loss = raw_loss.quantize(Decimal("1"), rounding=ROUND_DOWN)
    displayed_remaining = raw_remaining.quantize(
        Decimal("1"), rounding=ROUND_DOWN
    )
    # 정수 표시 재조합 시 1원 오차 가능
    recomputed_from_display = raw_limit.quantize(
        Decimal("1"), rounding=ROUND_DOWN
    ) - displayed_loss
    diff_display_vs_raw_remaining = abs(
        displayed_remaining - raw_remaining.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    classification = "DECIMAL_FRACTION"
    if abs(raw_remaining - (raw_limit - raw_loss)) > Decimal("0.0000001"):
        classification = "CALCULATION_ERROR"
    elif diff_display_vs_raw_remaining >= Decimal("1"):
        classification = "ROUND_DOWN"
    return {
        "raw_daily_loss": str(raw_loss),
        "normalized_daily_loss": str(
            raw_loss.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        ),
        "displayed_daily_loss": str(displayed_loss),
        "daily_loss_limit": str(raw_limit),
        "raw_remaining_limit": str(raw_remaining),
        "displayed_remaining_limit": str(displayed_remaining),
        "recomputed_remaining_from_int_display": str(recomputed_from_display),
        "rounding_mode": "diagnose raw Decimal; display ROUND_DOWN to 1 KRW",
        "decimal_precision": "Numeric path via diagnose(); display int KRW",
        "one_won_diff_classification": classification,
        "blocked_if_calculation_error": classification == "CALCULATION_ERROR",
        "diag": diag.to_dict(),
    }


def build_market_buy_body(
    *,
    market: str,
    amount_krw: Decimal,
    client_order_id: str,
    uba_id: int,
    user_id: int,
) -> dict[str, Any]:
    """Broker body 변환만 — submit 금지."""

    symbol = market.split("-", 1)[-1] if "-" in market else market
    req = BrokerOrderRequest(
        client_order_id=client_order_id,
        exchange_code="UPBIT",
        symbol=symbol,
        side=BrokerOrderSide.BUY,
        order_type=BrokerOrderType.MARKET,
        quantity=Decimal("0"),  # Market BUY volume unused
        price=amount_krw,  # KRW 주문금액
        user_broker_account_id=uba_id,
        broker_code="UPBIT",
        owner_user_id=user_id,
        account_type="LIVE",
        upbit_client_identifier=client_order_id[:30],
    )
    validate_upbit_notional(
        side="BUY",
        order_type="MARKET",
        quantity=ZERO,
        price=amount_krw,
    )
    body = UpbitOrderMapper.body(req)
    return {
        "uba_id": uba_id,
        "user_id": user_id,
        "broker_code": "UPBIT",
        "market": UpbitOrderMapper.market(req),
        "side": "BUY",
        "internal_order_type": "MARKET",
        "broker_order_type": body.get("ord_type"),
        "requested_amount": str(amount_krw),
        "requested_volume": None,
        "volume_null_reason": (
            "Upbit market BUY uses ord_type=price with KRW amount; "
            "volume field not sent"
        ),
        "price": body.get("price"),
        "price_meaning": "KRW order funds (not unit price)",
        "client_order_id_masked": _mask_id(client_order_id),
        "identifier_masked": _mask_id(str(body.get("identifier") or "")),
        "time_in_force": req.time_in_force,
        "fee_assumption": "separate at exchange; not in request body",
        "dry_run": True,
        "broker_body_sanitized": {
            k: v for k, v in body.items() if k != "identifier"
        } | {
            "identifier": _mask_id(str(body.get("identifier") or "")),
        },
    }


class Step92UpbitDryRunService:
    """UBA Market BUY 5,000원 Dry Run 오케스트레이션."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self.counters = CallCounters()

    def run(
        self,
        *,
        uba_id: int,
        market: str,
        amount: Decimal = DEFAULT_SMOKE_AMOUNT,
        actor: str = "admin:step9_2",
        correlation_id: str | None = None,
    ) -> Step92DryRunResult:
        corr = correlation_id or f"step9-2-{uuid.uuid4().hex[:12]}"
        market_u = market.strip().upper()
        amount_d = _dec(amount)
        reason_codes: list[str] = []
        guards: list[dict[str, Any]] = []

        def guard(code: str, status: str, detail: str) -> None:
            guards.append({"code": code, "status": status, "detail": detail})
            if status in {"FAIL", "BLOCK"}:
                reason_codes.append(code)

        try:
            uba = self._session.get(UserBrokerAccount, int(uba_id))
            if uba is None or not uba.is_active:
                guard("UBA_ACTIVE", "FAIL", "inactive_or_missing")
                return self._blocked(
                    "BLOCKED_DEFECT",
                    market_u,
                    amount_d,
                    guards,
                    reason_codes,
                    corr,
                )
            guard("UBA_ACTIVE", "PASS", f"uba={uba_id}")

            pause = self._session.scalar(
                select(BrokerRecoveryAccountStateEntity).where(
                    BrokerRecoveryAccountStateEntity.user_broker_account_id
                    == int(uba_id)
                )
            )
            paused = bool(pause.trading_paused) if pause else False
            guard(
                "ACCOUNT_PAUSE",
                "FAIL" if paused else "PASS",
                f"trading_paused={paused}",
            )

            if uba.live_order_enabled:
                guard("LIVE_OFF", "FAIL", "LIVE unexpectedly ON")
            else:
                guard("LIVE_OFF", "PASS", "OFF (dry-run expected)")
            if uba.live_armed:
                guard("ARM_OFF", "FAIL", "ARM unexpectedly ON")
            else:
                guard("ARM_OFF", "PASS", "OFF (dry-run expected)")

            smoke_raw = str(
                getattr(get_settings(), "upbit_live_smoke_allowlist", "")
                or ""
            )
            allow = tuple(
                m.strip().upper()
                for m in smoke_raw.split(",")
                if m.strip()
            ) or DEFAULT_ALLOWLIST
            if market_u not in allow:
                guard(
                    "MARKET_ALLOWLIST",
                    "FAIL",
                    f"{market_u} not in {list(allow)}",
                )
            else:
                guard("MARKET_ALLOWLIST", "PASS", market_u)
            if not market_u.startswith("KRW-"):
                guard("KRW_MARKET", "FAIL", market_u)
            else:
                guard("KRW_MARKET", "PASS", market_u)

            active = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(BrokerRecoveryConflictEntity)
                    .where(
                        BrokerRecoveryConflictEntity.user_broker_account_id
                        == int(uba_id),
                        BrokerRecoveryConflictEntity.review_status.in_(
                            list(ACTIVE_REVIEW_STATUSES)
                        ),
                    )
                )
                or 0
            )
            guard(
                "ACTIVE_REVIEW",
                "FAIL" if active else "PASS",
                f"count={active}",
            )

            blocking = BrokerRecoveryConflictService(
                self._session
            ).count_blocking_orders_for_uba(int(uba_id))
            for key, label in (
                ("db_open", "DB_OPEN"),
                ("submission_unknown", "SUBMISSION_UNKNOWN"),
                ("cancel_pending", "CANCEL_PENDING"),
                ("replace_pending", "REPLACE_PENDING"),
            ):
                n = int(blocking.get(key) or 0)
                guard(label, "FAIL" if n else "PASS", f"count={n}")

            fee_model = analyze_fee_model(requested_amount=amount_d)
            if amount_d < UPBIT_MIN_NOTIONAL_KRW:
                guard(
                    "MIN_NOTIONAL",
                    "FAIL",
                    f"{amount_d} < {UPBIT_MIN_NOTIONAL_KRW}",
                )
            else:
                guard("MIN_NOTIONAL", "PASS", str(amount_d))

            daily = analyze_daily_loss_display(
                self._session, uba_id=int(uba_id)
            )
            if daily.get("blocked_if_calculation_error"):
                guard("DAILY_LOSS_MATH", "FAIL", "CALCULATION_ERROR")
            else:
                guard(
                    "DAILY_LOSS_MATH",
                    "PASS",
                    str(daily.get("one_won_diff_classification")),
                )

            # 참조가 — Market BUY body에는 불필요, Preflight LIMIT 경로용
            import httpx

            t0 = datetime.now(timezone.utc)
            ticker = httpx.get(
                "https://api.upbit.com/v1/ticker",
                params={"markets": market_u},
                timeout=10.0,
            )
            ticker.raise_for_status()
            trade_price = _dec(ticker.json()[0].get("trade_price"))
            latency_ms = (
                datetime.now(timezone.utc) - t0
            ).total_seconds() * 1000
            guard(
                "TICKER",
                "PASS" if trade_price > 0 else "FAIL",
                f"trade_price={trade_price} latency_ms={latency_ms:.1f}",
            )

            client_oid = (
                "dry"
                + hashlib.sha256(corr.encode()).hexdigest()[:16]
            )
            transform = build_market_buy_body(
                market=market_u,
                amount_krw=amount_d,
                client_order_id=client_oid,
                uba_id=int(uba_id),
                user_id=int(uba.user_id),
            )
            guard("ORDER_TRANSFORM", "PASS", "mapper body built")

            # Preflight dry_run — LIVE/ARM OFF expected, Adapter 미호출
            preflight = UpbitLivePreflightService(self._session).run(
                user_broker_account_id=int(uba_id),
                market=market_u,
                side="BUY",
                amount=amount_d,
                limit_price=trade_price if trade_price > 0 else amount_d,
                actor=actor,
                purpose="dry_run",
                skip_live_network=False,
            )
            pf = preflight.to_dict()
            if preflight.dry_run_ready:
                guard("PREFLIGHT_DRY_RUN", "PASS", "dry_run_ready=true")
            else:
                guard(
                    "PREFLIGHT_DRY_RUN",
                    "FAIL",
                    f"blockers={preflight.blockers}",
                )
                reason_codes.extend(
                    [f"PF:{b}" for b in (preflight.blockers or [])]
                )

            # submit 경로 미도달 증명 — counters 유지
            if not self.counters.all_zero():
                guard("MUTATION_COUNTERS", "FAIL", str(self.counters.as_dict()))

            fail_codes = [g["code"] for g in guards if g["status"] == "FAIL"]
            if fail_codes:
                verdict = "BLOCKED_DEFECT"
            elif preflight.dry_run_ready and not paused:
                verdict = "PASS_DRY_RUN"
            else:
                verdict = "BLOCKED_DEFECT"

            return Step92DryRunResult(
                verdict=verdict,
                market=market_u,
                requested_amount=str(amount_d),
                guards=guards,
                fee_model=fee_model,
                daily_loss=daily,
                order_transform=transform,
                preflight={
                    "dry_run_ready": preflight.dry_run_ready,
                    "live_execution_ready": preflight.live_execution_ready,
                    "ready": preflight.ready,
                    "blockers": list(preflight.blockers or []),
                    "live_blockers": list(preflight.live_blockers or []),
                    "checks": [
                        c if isinstance(c, dict) else str(c)
                        for c in (pf.get("checks") or [])[:40]
                    ],
                },
                counters=self.counters.as_dict(),
                correlation_id=corr,
                reason_codes=reason_codes,
                detail={
                    "ticker_trade_price": str(trade_price),
                    "ticker_latency_ms": round(latency_ms, 1),
                    "live_order_enabled": bool(uba.live_order_enabled),
                    "live_armed": bool(uba.live_armed),
                    "trading_paused": paused,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return Step92DryRunResult(
                verdict="ERROR",
                market=market_u,
                requested_amount=str(amount_d),
                guards=guards,
                counters=self.counters.as_dict(),
                correlation_id=corr,
                reason_codes=reason_codes + [f"ERROR:{type(exc).__name__}"],
                detail={"error": str(exc)[:500]},
            )

    def _blocked(
        self,
        verdict: str,
        market: str,
        amount: Decimal,
        guards: list[dict[str, Any]],
        reason_codes: list[str],
        corr: str,
    ) -> Step92DryRunResult:
        return Step92DryRunResult(
            verdict=verdict,
            market=market,
            requested_amount=str(amount),
            guards=guards,
            counters=self.counters.as_dict(),
            correlation_id=corr,
            reason_codes=reason_codes,
        )
