"""키움 가격 필드 정규화.

키움 REST는 등락 방향을 가격 앞에 +/- 로 붙인다.
예: 하락 호가 `sel_fpr_bid=-40200` → 주문가격 40200.

수량·잔고·등락률·손익처럼 부호 자체가 의미인 필드에는 사용하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


ZERO = Decimal("0")

# ka10004 / ka10007 최우선 매도호가(가격) 별칭
KIWOOM_BEST_ASK_KEYS = (
    "sel_fpr_bid",
    "askp1",
    "ask_pric",
    "sel_bidp1",
    "sel_1bid",
    "ovtm_sel_fpr_bid",
    "best_ask",
)

# 최우선 매수호가(가격) 별칭
KIWOOM_BEST_BID_KEYS = (
    "buy_fpr_bid",
    "bidp1",
    "bid_pric",
    "buy_bidp1",
    "buy_1bid",
    "best_bid",
)

# 현재가(가격) 별칭
KIWOOM_CURRENT_PRICE_KEYS = (
    "cur_prc",
    "stck_prpr",
    "prpr",
    "now_prc",
    "exec_pric",
    "current_price",
)


def normalize_kiwoom_price(value: Any) -> Decimal | None:
    """키움 가격 필드 → 절댓값 Decimal.

    None / 빈 문자열 / 비숫자는 None (invalid).
    "0" / 0 은 Decimal("0") — 호출측에서 호가 유효성 판단.
    """
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text == "":
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return abs(parsed)


def pick_kiwoom_price_field(
    payload: dict[str, Any],
    keys: tuple[str, ...],
) -> tuple[str | None, Decimal | None]:
    """첫 유효 가격 필드의 raw 문자열과 정규화 값을 반환한다."""
    if not isinstance(payload, dict):
        return None, None
    for key in keys:
        if key not in payload:
            continue
        raw = payload.get(key)
        if raw in (None, ""):
            continue
        normalized = normalize_kiwoom_price(raw)
        if normalized is None:
            continue
        return str(raw).strip(), normalized
    return None, None


def _is_halted(payload: dict[str, Any]) -> bool:
    for key in ("trd_stop_yn", "halt_yn", "temp_stop_yn"):
        raw = str(payload.get(key) or "").upper()
        if raw in {"Y", "1", "HALT", "STOP"}:
            return True
    return False


@dataclass(frozen=True)
class KiwoomMarketConditionQuote:
    """ka10004/ka10007 호가 응답의 주문용 가격 추출 결과."""

    ok: bool
    name: str | None
    raw_best_ask: str | None
    best_ask: Decimal | None
    raw_best_bid: str | None
    best_bid: Decimal | None
    raw_current_price: str | None
    current_price: Decimal | None
    halted: bool
    api_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "name": self.name,
            "raw_best_ask": self.raw_best_ask,
            "best_ask": str(self.best_ask) if self.best_ask is not None else None,
            "raw_best_bid": self.raw_best_bid,
            "best_bid": str(self.best_bid) if self.best_bid is not None else None,
            "raw_current_price": self.raw_current_price,
            "current_price": (
                str(self.current_price) if self.current_price is not None else None
            ),
            "halted": self.halted,
            "api_id": self.api_id,
        }


def parse_kiwoom_mrkcond_quote(
    payload: dict[str, Any],
    *,
    api_id: str | None = None,
) -> KiwoomMarketConditionQuote:
    """시장조건(호가) 응답에서 최우선 매도호가 등 가격만 정규화한다."""
    if not isinstance(payload, dict):
        return KiwoomMarketConditionQuote(
            ok=False,
            name=None,
            raw_best_ask=None,
            best_ask=None,
            raw_best_bid=None,
            best_bid=None,
            raw_current_price=None,
            current_price=None,
            halted=False,
            api_id=api_id,
        )

    name = None
    for key in ("stk_nm", "name", "iss_nm"):
        if payload.get(key):
            name = str(payload[key])
            break

    raw_ask, best_ask = pick_kiwoom_price_field(payload, KIWOOM_BEST_ASK_KEYS)
    raw_bid, best_bid = pick_kiwoom_price_field(payload, KIWOOM_BEST_BID_KEYS)
    raw_cur, current = pick_kiwoom_price_field(payload, KIWOOM_CURRENT_PRICE_KEYS)
    halted = _is_halted(payload)
    ask_ok = best_ask is not None and best_ask > ZERO and not halted

    return KiwoomMarketConditionQuote(
        ok=ask_ok,
        name=name,
        raw_best_ask=raw_ask,
        best_ask=best_ask if best_ask is not None and best_ask > ZERO else None,
        raw_best_bid=raw_bid,
        best_bid=best_bid if best_bid is not None and best_bid > ZERO else None,
        raw_current_price=raw_cur,
        current_price=current if current is not None and current > ZERO else None,
        halted=halted,
        api_id=api_id,
    )
