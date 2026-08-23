"""MA_DEAD_CROSS 전략 청산 anti-churn 정책.

보호 청산(STOP_LOSS / TAKE_PROFIT / TRAILING_STOP / KILL)에는 적용하지 않는다.
PnL 음수여도 confirmed dead-cross + min-hold 충족 시 SELL 허용 (profit-only 금지).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

ZERO = Decimal("0")
HUNDRED = Decimal("100")

# 보호 청산 — min-hold / separation gate 적용 금지
PROTECTIVE_EXIT_REASONS = frozenset(
    {
        "STOP_LOSS",
        "TAKE_PROFIT",
        "TRAILING_STOP",
        "KILL_SWITCH",
        "PROTECTIVE_EXIT",
        "KILL",
    }
)

DEFAULT_EXIT_MIN_MA_SEPARATION_PCT = 0.03
DEFAULT_MA_EXIT_MIN_HOLDING_SECONDS = 180
DEFAULT_ESTIMATED_FEE_RATE = 0.0005  # Upbit 약 0.05%


@dataclass(frozen=True, slots=True)
class MaExitThresholds:
    """전략 MA exit 임계값 — settings + risk_group_policy_json."""

    exit_min_ma_separation_pct: float = DEFAULT_EXIT_MIN_MA_SEPARATION_PCT
    ma_exit_min_holding_seconds: int = DEFAULT_MA_EXIT_MIN_HOLDING_SECONDS
    estimated_fee_rate: float = DEFAULT_ESTIMATED_FEE_RATE


def is_protective_exit_reason(reason: str | None) -> bool:
    """보호 청산 사유 여부."""

    return str(reason or "").strip().upper() in PROTECTIVE_EXIT_REASONS


def ma_separation_pct(
    short_ma: Decimal | None, long_ma: Decimal | None
) -> float | None:
    """(short - long) / long * 100. long<=0 이면 None."""

    if short_ma is None or long_ma is None:
        return None
    if long_ma <= ZERO:
        return None
    try:
        return float((short_ma - long_ma) / long_ma * HUNDRED)
    except Exception:  # noqa: BLE001
        return None


def is_dead_cross_confirmed(
    *,
    short_ma: Decimal | None,
    long_ma: Decimal | None,
    exit_min_ma_separation_pct: float,
) -> bool:
    """short < long 이고 역전폭이 임계 이상이면 confirmed."""

    if short_ma is None or long_ma is None:
        return False
    if short_ma >= long_ma:
        return False
    sep = ma_separation_pct(short_ma, long_ma)
    if sep is None:
        return False
    # sep 음수: (short-long)/long*100 <= -exit_min
    return sep <= -abs(float(exit_min_ma_separation_pct))


def holding_seconds(
    *,
    opened_at: datetime | None,
    now: datetime | None = None,
) -> float | None:
    """포지션 보유 초. opened_at 없으면 None."""

    if opened_at is None:
        return None
    ref = now or datetime.now(timezone.utc)
    oa = opened_at
    if oa.tzinfo is None:
        oa = oa.replace(tzinfo=timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return max(0.0, (ref - oa).total_seconds())


def is_min_holding_satisfied(
    *,
    opened_at: datetime | None,
    min_holding_seconds: int,
    now: datetime | None = None,
) -> bool:
    """min holding 충족 여부.

    opened_at 없으면 min-hold를 스킵(분리 confirmation만 적용) —
    binding 미동기화 시 전략청산 영구 차단 방지.
    """

    if int(min_holding_seconds) <= 0:
        return True
    held = holding_seconds(opened_at=opened_at, now=now)
    if held is None:
        return True
    return held >= float(min_holding_seconds)


def estimate_fee_aware_exit(
    *,
    entry_price: Decimal | None,
    quantity: Decimal | None,
    current_price: Decimal | None,
    buy_fee: Decimal | None = None,
    fee_rate: float = DEFAULT_ESTIMATED_FEE_RATE,
) -> dict[str, Any]:
    """관측용 fee-aware 추정. SELL hard-block에 쓰지 않는다."""

    out: dict[str, Any] = {
        "entry_price": str(entry_price) if entry_price is not None else None,
        "current_price": (
            str(current_price) if current_price is not None else None
        ),
        "quantity": str(quantity) if quantity is not None else None,
        "buy_fee": str(buy_fee) if buy_fee is not None else None,
        "estimated_sell_fee": None,
        "entry_cost": None,
        "current_exit_value": None,
        "estimated_net_pnl": None,
        "break_even_price": None,
        "estimated_net_return_pct": None,
        "fee_rate": float(fee_rate),
    }
    if (
        entry_price is None
        or quantity is None
        or current_price is None
        or entry_price <= ZERO
        or quantity <= ZERO
        or current_price <= ZERO
    ):
        return out

    rate = Decimal(str(fee_rate))
    notional_entry = entry_price * quantity
    buy_f = buy_fee if buy_fee is not None else (notional_entry * rate)
    exit_value = current_price * quantity
    sell_f = exit_value * rate
    entry_cost = notional_entry + buy_f
    net = exit_value - sell_f - entry_cost
    be: Decimal | None
    try:
        be = entry_price * (Decimal("1") + rate) / (Decimal("1") - rate)
    except Exception:  # noqa: BLE001
        be = None
    ret_pct = (
        float(net / entry_cost * HUNDRED) if entry_cost > ZERO else None
    )
    out.update(
        {
            "buy_fee": str(buy_f),
            "estimated_sell_fee": str(sell_f),
            "entry_cost": str(entry_cost),
            "current_exit_value": str(exit_value),
            "estimated_net_pnl": str(net),
            "break_even_price": str(be) if be is not None else None,
            "estimated_net_return_pct": ret_pct,
        }
    )
    return out


def load_ma_exit_thresholds_from_settings(settings: Any) -> MaExitThresholds:
    """환경 기본값."""

    return MaExitThresholds(
        exit_min_ma_separation_pct=float(
            getattr(
                settings,
                "upbit_portfolio_exit_min_ma_separation_pct",
                DEFAULT_EXIT_MIN_MA_SEPARATION_PCT,
            )
            or DEFAULT_EXIT_MIN_MA_SEPARATION_PCT
        ),
        ma_exit_min_holding_seconds=int(
            getattr(
                settings,
                "upbit_portfolio_ma_exit_min_holding_seconds",
                DEFAULT_MA_EXIT_MIN_HOLDING_SECONDS,
            )
            or DEFAULT_MA_EXIT_MIN_HOLDING_SECONDS
        ),
        estimated_fee_rate=float(
            getattr(
                settings,
                "upbit_portfolio_estimated_fee_rate",
                DEFAULT_ESTIMATED_FEE_RATE,
            )
            or DEFAULT_ESTIMATED_FEE_RATE
        ),
    )


def load_ma_exit_thresholds(
    *,
    settings: Any,
    risk_group_policy_json: dict[str, Any] | None = None,
) -> MaExitThresholds:
    """settings 기본 + risk_group_policy_json 우선."""

    base = load_ma_exit_thresholds_from_settings(settings)
    blob = dict(risk_group_policy_json or {})

    def _float(key: str, default: float) -> float:
        raw = blob.get(key)
        if raw is None:
            return default
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    def _int(key: str, default: int) -> int:
        raw = blob.get(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    return MaExitThresholds(
        exit_min_ma_separation_pct=max(
            0.0,
            _float(
                "exit_min_ma_separation_pct",
                base.exit_min_ma_separation_pct,
            ),
        ),
        ma_exit_min_holding_seconds=max(
            0,
            _int(
                "ma_exit_min_holding_seconds",
                base.ma_exit_min_holding_seconds,
            ),
        ),
        estimated_fee_rate=max(
            0.0,
            _float("estimated_fee_rate", base.estimated_fee_rate),
        ),
    )


def evaluate_ma_dead_cross_gate(
    *,
    raw_dead_cross_event: bool,
    confirming: bool,
    short_ma: Decimal | None,
    long_ma: Decimal | None,
    opened_at: datetime | None,
    thresholds: MaExitThresholds,
    now: datetime | None = None,
    entry_price: Decimal | None = None,
    quantity: Decimal | None = None,
    current_price: Decimal | None = None,
    buy_fee: Decimal | None = None,
) -> dict[str, Any]:
    """MA_DEAD_CROSS emit 여부 판정.

    Returns dict:
      decision: EMIT | CONFIRMING | HOLD | RESET
    Profit-only gate 없음 — net loss여도 EMIT 가능.
    """

    now_ref = now or datetime.now(timezone.utc)
    sep = ma_separation_pct(short_ma, long_ma)
    held = holding_seconds(opened_at=opened_at, now=now_ref)
    fee_snap = estimate_fee_aware_exit(
        entry_price=entry_price,
        quantity=quantity,
        current_price=current_price,
        buy_fee=buy_fee,
        fee_rate=thresholds.estimated_fee_rate,
    )

    # 보유 중 bullish 복귀 → confirmation 해제
    if confirming and short_ma is not None and long_ma is not None:
        if short_ma > long_ma:
            return {
                "decision": "RESET",
                "confirmed": False,
                "holding_ok": False,
                "ma_separation_pct": sep,
                "holding_seconds": held,
                "confirmation_status": "RESET_BULLISH",
                "fee_aware": fee_snap,
                "block_reason": "BULLISH_RECOVERY",
            }

    still_bearish = (
        short_ma is not None
        and long_ma is not None
        and short_ma < long_ma
    )
    active = bool(confirming or raw_dead_cross_event) and still_bearish
    if not active:
        return {
            "decision": "HOLD",
            "confirmed": False,
            "holding_ok": False,
            "ma_separation_pct": sep,
            "holding_seconds": held,
            "confirmation_status": "IDLE",
            "fee_aware": fee_snap,
            "block_reason": None,
        }

    confirmed = is_dead_cross_confirmed(
        short_ma=short_ma,
        long_ma=long_ma,
        exit_min_ma_separation_pct=thresholds.exit_min_ma_separation_pct,
    )
    holding_ok = is_min_holding_satisfied(
        opened_at=opened_at,
        min_holding_seconds=thresholds.ma_exit_min_holding_seconds,
        now=now_ref,
    )

    if confirmed and holding_ok:
        return {
            "decision": "EMIT",
            "confirmed": True,
            "holding_ok": True,
            "ma_separation_pct": sep,
            "holding_seconds": held,
            "confirmation_status": "CONFIRMED",
            "fee_aware": fee_snap,
            "block_reason": None,
        }

    block = None
    if not confirmed:
        block = "MA_EXIT_SEPARATION_NOT_CONFIRMED"
    elif not holding_ok:
        block = "MA_EXIT_MIN_HOLDING"

    return {
        "decision": "CONFIRMING",
        "confirmed": confirmed,
        "holding_ok": holding_ok,
        "ma_separation_pct": sep,
        "holding_seconds": held,
        "confirmation_status": "MA_EXIT_CONFIRMING",
        "fee_aware": fee_snap,
        "block_reason": block,
    }
