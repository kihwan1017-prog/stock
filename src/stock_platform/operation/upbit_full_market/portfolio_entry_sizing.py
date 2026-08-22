"""Portfolio entry sizing — ResolvedRiskPolicy SoT와 capital allocator 정렬."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.broker.upbit.rules import UPBIT_MIN_NOTIONAL_KRW
from stock_platform.operation.upbit_full_market.capital_allocator import (
    AllocationInput,
    AllocationResult,
    allocate_entry_amount,
)
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicyResolver

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class PortfolioEntryRiskLimits:
    """실행 가능 주문금액 상한 — system → user → UBA 병합."""

    max_order_amount: Decimal
    max_position_amount: Decimal
    source_layers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_order_amount": str(self.max_order_amount),
            "max_position_amount": str(self.max_position_amount),
            "source_layers": list(self.source_layers),
        }


def resolve_portfolio_entry_risk_limits(
    session: Session,
    *,
    user_broker_account_id: int,
    user_id: int | None = None,
) -> PortfolioEntryRiskLimits:
    """Canonical Risk SoT — UBA1380 등 하드코딩 금지."""

    resolved = ResolvedRiskPolicyResolver(session).resolve(
        user_id=user_id,
        user_broker_account_id=int(user_broker_account_id),
    )
    return PortfolioEntryRiskLimits(
        max_order_amount=Decimal(str(resolved.max_order_amount)),
        max_position_amount=Decimal(str(resolved.max_position_amount)),
        source_layers=tuple(resolved.source_layers),
    )


def effective_max_order_cap(
    limits: PortfolioEntryRiskLimits,
    *,
    activation_max_order_amount: Decimal | None = None,
    legacy_explicit_cap: Decimal | None = None,
) -> Decimal:
    """Risk max_order_amount가 천장. activation/legacy는 더 낮을 때만 추가 clamp."""

    caps = [limits.max_order_amount]
    if activation_max_order_amount is not None and activation_max_order_amount > ZERO:
        caps.append(Decimal(str(activation_max_order_amount)))
    if legacy_explicit_cap is not None and legacy_explicit_cap > ZERO:
        caps.append(Decimal(str(legacy_explicit_cap)))
    return min(caps)


def allocate_portfolio_entry_amount(
    inp: AllocationInput,
    *,
    risk_limits: PortfolioEntryRiskLimits,
    activation_max_order_amount: Decimal | None = None,
    legacy_explicit_cap: Decimal | None = None,
) -> AllocationResult:
    """Portfolio desired allocation → Risk-compatible executable amount."""

    cap = effective_max_order_cap(
        risk_limits,
        activation_max_order_amount=activation_max_order_amount,
        legacy_explicit_cap=legacy_explicit_cap,
    )
    # account_max_order_amount 필드에 canonical risk cap 주입
    merged = AllocationInput(
        portfolio_capital_limit_krw=inp.portfolio_capital_limit_krw,
        available_krw=inp.available_krw,
        min_cash_reserve_pct=inp.min_cash_reserve_pct,
        per_position_target_pct=inp.per_position_target_pct,
        max_symbol_exposure_pct=inp.max_symbol_exposure_pct,
        max_total_exposure_pct=inp.max_total_exposure_pct,
        current_strategy_exposure_krw=inp.current_strategy_exposure_krw,
        pending_reserved_krw=inp.pending_reserved_krw,
        current_symbol_exposure_krw=inp.current_symbol_exposure_krw,
        account_max_order_amount=cap,
        account_max_position_amount=risk_limits.max_position_amount,
        activation_max_order_amount=activation_max_order_amount,
        scanner_score=inp.scanner_score,
        ai_confidence=inp.ai_confidence,
        volatility=inp.volatility,
        min_notional_krw=inp.min_notional_krw,
    )
    return allocate_entry_amount(merged)


def build_sizing_telemetry(
    alloc: AllocationResult,
    *,
    risk_limits: PortfolioEntryRiskLimits,
    effective_cap: Decimal,
) -> dict[str, Any]:
    """begin_entry / Admin observability용."""

    clamped_by: list[str] = []
    if float(alloc.recommended_amount_krw) > float(alloc.approved_amount_krw):
        if "ACCOUNT_MAX_ORDER" in alloc.clamp_reasons:
            clamped_by.append("MAX_ORDER_AMOUNT")
        for reason in alloc.clamp_reasons:
            if reason not in {"ACCOUNT_MAX_ORDER"} and reason not in clamped_by:
                clamped_by.append(reason)

    return {
        "requested_amount_krw": float(alloc.recommended_amount_krw),
        "portfolio_amount_krw": float(alloc.recommended_amount_krw),
        "approved_amount_krw": float(alloc.approved_amount_krw),
        "final_order_amount_krw": float(alloc.approved_amount_krw),
        "reservation_amount_krw": float(alloc.approved_amount_krw),
        "effective_max_order_amount_krw": float(effective_cap),
        "risk_max_order_amount_krw": float(risk_limits.max_order_amount),
        "risk_source_layers": list(risk_limits.source_layers),
        "clamped_by": clamped_by,
        "clamp_reasons": list(alloc.clamp_reasons),
        "allocation_detail": dict(alloc.detail),
    }


def portfolio_sizing_readiness_hint(
    session: Session,
    *,
    user_broker_account_id: int,
    user_id: int | None = None,
) -> dict[str, Any]:
    """effective max < broker minimum이면 구조적 주문 불가 warning."""

    limits = resolve_portfolio_entry_risk_limits(
        session,
        user_broker_account_id=int(user_broker_account_id),
        user_id=user_id,
    )
    min_n = UPBIT_MIN_NOTIONAL_KRW
    if limits.max_order_amount < min_n:
        return {
            "ok": False,
            "warning": "SIZING_NO_EXECUTABLE_AMOUNT",
            "effective_max_order_amount_krw": str(limits.max_order_amount),
            "broker_min_notional_krw": str(min_n),
            "detail": (
                "Resolved max_order_amount is below Upbit minimum notional; "
                "AUTO BUY cannot execute until risk or broker minimum aligns."
            ),
        }
    return {
        "ok": True,
        "effective_max_order_amount_krw": str(limits.max_order_amount),
        "broker_min_notional_krw": str(min_n),
    }


__all__ = [
    "PortfolioEntryRiskLimits",
    "allocate_portfolio_entry_amount",
    "build_sizing_telemetry",
    "effective_max_order_cap",
    "portfolio_sizing_readiness_hint",
    "resolve_portfolio_entry_risk_limits",
]
