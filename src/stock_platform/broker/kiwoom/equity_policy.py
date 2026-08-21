"""Kiwoom Daily Loss용 settlement-aware account equity.

입출금(external cash flow) 자동 보정은 신뢰할 수 있는 원장이 없어
이번 범위에서는 구조만 두고 적용하지 않는다 (GAP).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


ZERO = Decimal("0")
QUANT = Decimal("0.01")

# Policy versions — opening/current 동일 정의·mid-day mixing 방지용
KIWOOM_EQUITY_V1_IMMEDIATE_CASH = "KIWOOM_EQUITY_V1_IMMEDIATE_CASH"
KIWOOM_EQUITY_V2_SETTLEMENT_AWARE = "KIWOOM_EQUITY_V2_SETTLEMENT_AWARE"

# Equity source provenance (additive)
SOURCE_ESTIMATED_ASSET = "KIWOOM_ESTIMATED_ASSET"
SOURCE_D2_PLUS_STOCK = "KIWOOM_D2_CASH_PLUS_STOCK_EVALUATION"
SOURCE_D1_PLUS_STOCK = "KIWOOM_D1_CASH_PLUS_STOCK_EVALUATION"
SOURCE_IMMEDIATE_PLUS_STOCK = "KIWOOM_IMMEDIATE_CASH_PLUS_STOCK_EVALUATION"

# 입출금 보정 — future-ready, 현재 미적용
EXTERNAL_CASH_FLOW_ADJUSTMENT_SUPPORTED = False
EXTERNAL_CASH_FLOW_GAP = (
    "No reliable Kiwoom deposit/withdraw ledger wired; "
    "do not auto-adjust daily loss for external cash flow"
)


@dataclass(frozen=True, slots=True)
class KiwoomEquityBreakdown:
    """정산 인지 equity 계산 결과 + provenance."""

    cash_immediate: Decimal
    cash_d1: Decimal
    cash_d2: Decimal
    stock_evaluation: Decimal
    estimated_asset: Decimal | None
    pending_settlement_cash: Decimal
    equity_for_risk: Decimal
    equity_source: str
    equity_policy_version: str
    legacy_equity: Decimal
    external_cash_flow_adjustment: Decimal
    external_cash_flow_gap: str | None

    def to_raw_dict(self) -> dict[str, Any]:
        return {
            "cash_immediate": str(self.cash_immediate),
            "cash_d1": str(self.cash_d1),
            "cash_d2": str(self.cash_d2),
            "stock_evaluation": str(self.stock_evaluation),
            "estimated_asset": (
                str(self.estimated_asset)
                if self.estimated_asset is not None
                else None
            ),
            "pending_settlement_cash": str(self.pending_settlement_cash),
            "equity_for_risk": str(self.equity_for_risk),
            "equity_source": self.equity_source,
            "equity_policy_version": self.equity_policy_version,
            "legacy_equity": str(self.legacy_equity),
            "external_cash_flow_adjustment": str(
                self.external_cash_flow_adjustment
            ),
            "external_cash_flow_gap": self.external_cash_flow_gap,
            "external_cash_flow_adjustment_supported": (
                EXTERNAL_CASH_FLOW_ADJUSTMENT_SUPPORTED
            ),
        }


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        cleaned = str(value).replace(",", "").replace("%", "").strip()
        if not cleaned:
            return None
        return Decimal(cleaned)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _pick_number(payload: dict[str, Any], *keys: str) -> Decimal | None:
    for key in keys:
        parsed = _as_decimal(payload.get(key))
        if parsed is not None:
            return parsed
    return None


def extract_kiwoom_components(account: Any) -> dict[str, Decimal | None]:
    """스냅샷/DTO에서 Kiwoom cash·평가 필드를 추출한다."""

    raw = getattr(account, "raw_data", None) or {}
    if not isinstance(raw, dict):
        raw = {}
    deposit = raw.get("deposit") if isinstance(raw.get("deposit"), dict) else {}
    balance = raw.get("balance") if isinstance(raw.get("balance"), dict) else {}
    # mapper가 평탄하게 넣은 equity_for_risk 캐시가 있어도 원본 필드를 우선
    cash_immediate = _pick_number(
        deposit, "entr", "deposit", "deposit_amount"
    )
    if cash_immediate is None:
        cash_immediate = _as_decimal(getattr(account, "deposit_amount", None))

    cash_d1 = _pick_number(deposit, "d1_entra", "d1_deposit")
    cash_d2 = _pick_number(deposit, "d2_entra", "d2_deposit")
    estimated = _pick_number(
        deposit,
        "prsm_dpst_aset_amt",
        "estimated_deposit_asset",
        "estimated_asset",
    )
    stock_eval = _pick_number(
        balance, "tot_evlt_amt", "total_evaluation_amount"
    )
    if stock_eval is None:
        stock_eval = _as_decimal(
            getattr(account, "total_evaluation_amount", None)
        )

    return {
        "cash_immediate": cash_immediate if cash_immediate is not None else ZERO,
        "cash_d1": cash_d1,
        "cash_d2": cash_d2,
        "stock_evaluation": stock_eval if stock_eval is not None else ZERO,
        "estimated_asset": estimated,
    }


def _is_usable_estimated(
    estimated: Decimal | None,
    *,
    stock_evaluation: Decimal,
    settlement_cash: Decimal,
) -> bool:
    """추정예탁자산이 평가/정산현금과 모순되지 않는지 느슨히 검증."""

    if estimated is None or estimated <= ZERO:
        return False
    # 주식 평가만으로도 추정자산보다 크게 크면 필드 오인 가능
    if stock_evaluation > ZERO and estimated < (stock_evaluation * Decimal("0.85")):
        return False
    # fallback(정산현금+주식)과 극단적으로 어긋나면 거부
    fallback = (settlement_cash + stock_evaluation).quantize(QUANT)
    if fallback > ZERO:
        delta = abs(estimated - fallback)
        # 절대 50만원 또는 상대 15% 초과 시 의심 → fallback 사용
        if delta > max(Decimal("500000"), fallback * Decimal("0.15")):
            return False
    return True


def _settlement_aware_cash(
    *,
    cash_immediate: Decimal,
    cash_d1: Decimal | None,
    cash_d2: Decimal | None,
) -> tuple[Decimal, str]:
    """정산을 반영한 현금성 자산. d2 > d1 > entr 우선."""

    if cash_d2 is not None and cash_d2 >= ZERO:
        return cash_d2, SOURCE_D2_PLUS_STOCK
    if cash_d1 is not None and cash_d1 >= ZERO:
        # d1만 있고 entr보다 크면 정산 대기 반영
        if cash_d1 >= cash_immediate:
            return cash_d1, SOURCE_D1_PLUS_STOCK
    return cash_immediate, SOURCE_IMMEDIATE_PLUS_STOCK


def compute_kiwoom_equity_for_risk(
    account: Any,
    *,
    policy_version: str | None = None,
) -> KiwoomEquityBreakdown:
    """
    Daily Loss용 Kiwoom equity.

    V1: entr + tot_evlt_amt (immediate cash — settlement false loss 가능)
    V2: settlement-aware
         PRIMARY validated prsm_dpst_aset_amt
         FALLBACK d2/d1/entr + tot_evlt_amt
    """

    comps = extract_kiwoom_components(account)
    cash_immediate = Decimal(str(comps["cash_immediate"] or ZERO))
    cash_d1 = comps["cash_d1"]
    cash_d2 = comps["cash_d2"]
    stock_evaluation = Decimal(str(comps["stock_evaluation"] or ZERO))
    estimated_asset = comps["estimated_asset"]

    legacy_equity = (cash_immediate + stock_evaluation).quantize(QUANT)
    settlement_cash, settlement_source = _settlement_aware_cash(
        cash_immediate=cash_immediate,
        cash_d1=cash_d1,
        cash_d2=cash_d2,
    )
    pending = max(settlement_cash - cash_immediate, ZERO).quantize(QUANT)

    version = (policy_version or KIWOOM_EQUITY_V2_SETTLEMENT_AWARE).strip()
    if version == KIWOOM_EQUITY_V1_IMMEDIATE_CASH:
        return KiwoomEquityBreakdown(
            cash_immediate=cash_immediate.quantize(QUANT),
            cash_d1=(
                Decimal(str(cash_d1)).quantize(QUANT)
                if cash_d1 is not None
                else ZERO
            ),
            cash_d2=(
                Decimal(str(cash_d2)).quantize(QUANT)
                if cash_d2 is not None
                else ZERO
            ),
            stock_evaluation=stock_evaluation.quantize(QUANT),
            estimated_asset=(
                Decimal(str(estimated_asset)).quantize(QUANT)
                if estimated_asset is not None
                else None
            ),
            pending_settlement_cash=pending,
            equity_for_risk=legacy_equity,
            equity_source=SOURCE_IMMEDIATE_PLUS_STOCK,
            equity_policy_version=KIWOOM_EQUITY_V1_IMMEDIATE_CASH,
            legacy_equity=legacy_equity,
            external_cash_flow_adjustment=ZERO,
            external_cash_flow_gap=EXTERNAL_CASH_FLOW_GAP,
        )

    # V2 settlement-aware
    if _is_usable_estimated(
        estimated_asset,
        stock_evaluation=stock_evaluation,
        settlement_cash=settlement_cash,
    ):
        equity = Decimal(str(estimated_asset)).quantize(QUANT)
        source = SOURCE_ESTIMATED_ASSET
    else:
        equity = (settlement_cash + stock_evaluation).quantize(QUANT)
        source = settlement_source

    return KiwoomEquityBreakdown(
        cash_immediate=cash_immediate.quantize(QUANT),
        cash_d1=(
            Decimal(str(cash_d1)).quantize(QUANT)
            if cash_d1 is not None
            else ZERO
        ),
        cash_d2=(
            Decimal(str(cash_d2)).quantize(QUANT)
            if cash_d2 is not None
            else ZERO
        ),
        stock_evaluation=stock_evaluation.quantize(QUANT),
        estimated_asset=(
            Decimal(str(estimated_asset)).quantize(QUANT)
            if estimated_asset is not None
            else None
        ),
        pending_settlement_cash=pending,
        equity_for_risk=equity,
        equity_source=source,
        equity_policy_version=KIWOOM_EQUITY_V2_SETTLEMENT_AWARE,
        legacy_equity=legacy_equity,
        external_cash_flow_adjustment=ZERO,
        external_cash_flow_gap=EXTERNAL_CASH_FLOW_GAP,
    )


def resolve_kiwoom_policy_for_baseline(
    baseline_policy_version: str | None,
) -> str:
    """
    기존 baseline이 V1/미표기면 당일 내내 V1 유지 (mid-day mixing 방지).
    신규 baseline만 V2.
    """

    if not baseline_policy_version:
        return KIWOOM_EQUITY_V1_IMMEDIATE_CASH
    version = str(baseline_policy_version).strip()
    if version == KIWOOM_EQUITY_V2_SETTLEMENT_AWARE:
        return KIWOOM_EQUITY_V2_SETTLEMENT_AWARE
    return KIWOOM_EQUITY_V1_IMMEDIATE_CASH


def default_policy_for_new_kiwoom_baseline() -> str:
    return KIWOOM_EQUITY_V2_SETTLEMENT_AWARE
