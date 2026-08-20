"""Portfolio capital allocator — Risk 우회 금지, clamp provenance 필수."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from stock_platform.broker.upbit.rules import UPBIT_MIN_NOTIONAL_KRW


ZERO = Decimal("0")


@dataclass
class AllocationInput:
    portfolio_capital_limit_krw: Decimal
    available_krw: Decimal
    min_cash_reserve_pct: float
    per_position_target_pct: float
    max_symbol_exposure_pct: float
    max_total_exposure_pct: float
    current_strategy_exposure_krw: Decimal
    pending_reserved_krw: Decimal
    current_symbol_exposure_krw: Decimal
    account_max_order_amount: Decimal
    account_max_position_amount: Decimal | None = None
    activation_max_order_amount: Decimal | None = None
    scanner_score: float | None = None
    ai_confidence: float | None = None
    volatility: str | None = None  # LOW/MEDIUM/HIGH
    min_notional_krw: Decimal = UPBIT_MIN_NOTIONAL_KRW


@dataclass
class AllocationResult:
    recommended_amount_krw: Decimal
    approved_amount_krw: Decimal
    skipped: bool
    skip_reason: str | None = None
    clamp_reasons: list[str] = field(default_factory=list)
    quality_multiplier: float = 1.0
    detail: dict[str, Any] = field(default_factory=dict)


def _d(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except Exception:  # noqa: BLE001
        return ZERO


def quality_multiplier(
    *,
    scanner_score: float | None,
    ai_confidence: float | None,
    volatility: str | None,
) -> float:
    """품질 배수 — 강하게 clamp (0.5~1.25)."""

    mult = 1.0
    if scanner_score is not None:
        # score 0~100 가정 → 0.85~1.15
        s = max(0.0, min(100.0, float(scanner_score)))
        mult *= 0.85 + (s / 100.0) * 0.30
    if ai_confidence is not None:
        c = max(0.0, min(1.0, float(ai_confidence)))
        mult *= 0.85 + c * 0.30
    vol = str(volatility or "").upper()
    if vol in {"HIGH", "VERY_HIGH"}:
        mult *= 0.75
    elif vol == "MEDIUM":
        mult *= 0.90
    return max(0.5, min(1.25, mult))


def allocate_entry_amount(inp: AllocationInput) -> AllocationResult:
    """base × quality → Risk/exposure/cash clamp. 최소주문 미만이면 SKIP."""

    reasons: list[str] = []
    capital = max(ZERO, _d(inp.portfolio_capital_limit_krw))
    if capital <= ZERO:
        return AllocationResult(
            recommended_amount_krw=ZERO,
            approved_amount_krw=ZERO,
            skipped=True,
            skip_reason="PORTFOLIO_CAPITAL_ZERO",
            clamp_reasons=["PORTFOLIO_CAPITAL_ZERO"],
        )

    q = quality_multiplier(
        scanner_score=inp.scanner_score,
        ai_confidence=inp.ai_confidence,
        volatility=inp.volatility,
    )
    base = capital * _d(inp.per_position_target_pct)
    recommended = (base * _d(q)).quantize(Decimal("1"))
    approved = recommended
    reasons.append(f"BASE_TARGET={base}")
    reasons.append(f"QUALITY_MULT={q:.3f}")

    # cash reserve
    avail = max(ZERO, _d(inp.available_krw))
    reserve = avail * _d(inp.min_cash_reserve_pct)
    spendable = max(ZERO, avail - reserve - max(ZERO, _d(inp.pending_reserved_krw)))
    if approved > spendable:
        approved = spendable
        reasons.append("CASH_RESERVE_OR_PENDING")

    # total exposure
    max_total = capital * _d(inp.max_total_exposure_pct)
    used = max(ZERO, _d(inp.current_strategy_exposure_krw)) + max(
        ZERO, _d(inp.pending_reserved_krw)
    )
    remaining_total = max(ZERO, max_total - used)
    if approved > remaining_total:
        approved = remaining_total
        reasons.append("TOTAL_EXPOSURE_LIMIT")

    # symbol exposure
    max_sym = capital * _d(inp.max_symbol_exposure_pct)
    sym_used = max(ZERO, _d(inp.current_symbol_exposure_krw))
    remaining_sym = max(ZERO, max_sym - sym_used)
    if approved > remaining_sym:
        approved = remaining_sym
        reasons.append("SYMBOL_EXPOSURE_LIMIT")

    # account max order (더 엄격한 쪽)
    caps = [_d(inp.account_max_order_amount)]
    if inp.activation_max_order_amount is not None:
        caps.append(_d(inp.activation_max_order_amount))
    if inp.account_max_position_amount is not None:
        caps.append(_d(inp.account_max_position_amount))
    hard_cap = min((c for c in caps if c > ZERO), default=ZERO)
    if hard_cap > ZERO and approved > hard_cap:
        approved = hard_cap
        reasons.append("ACCOUNT_MAX_ORDER")

    if approved < ZERO:
        approved = ZERO

    min_n = _d(inp.min_notional_krw)
    if approved < min_n:
        return AllocationResult(
            recommended_amount_krw=recommended,
            approved_amount_krw=ZERO,
            skipped=True,
            skip_reason="BELOW_MIN_NOTIONAL",
            clamp_reasons=reasons + ["BELOW_MIN_NOTIONAL"],
            quality_multiplier=q,
            detail={
                "spendable": str(spendable),
                "remaining_total": str(remaining_total),
                "remaining_symbol": str(remaining_sym),
                "hard_cap": str(hard_cap),
                "min_notional": str(min_n),
            },
        )

    return AllocationResult(
        recommended_amount_krw=recommended,
        approved_amount_krw=approved.quantize(Decimal("1")),
        skipped=False,
        clamp_reasons=reasons,
        quality_multiplier=q,
        detail={
            "spendable": str(spendable),
            "remaining_total": str(remaining_total),
            "remaining_symbol": str(remaining_sym),
            "hard_cap": str(hard_cap),
        },
    )
