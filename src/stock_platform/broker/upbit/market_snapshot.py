"""Upbit 공개 시세/호가 Snapshot DTO 및 파서 (주문 API 미사용)."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Any

import httpx

from stock_platform.broker.upbit.rules import upbit_tick_size
from stock_platform.common.settings import Settings, get_settings

_logger = logging.getLogger(__name__)
ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class UpbitTickerSnapshot:
    market: str
    trade_price: Decimal
    timestamp: str | None
    raw_ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "trade_price": str(self.trade_price),
            "timestamp": self.timestamp,
            "raw_ok": self.raw_ok,
        }


@dataclass(frozen=True, slots=True)
class UpbitOrderbookSnapshot:
    market: str
    best_bid_price: Decimal
    best_ask_price: Decimal
    best_bid_size: Decimal
    best_ask_size: Decimal
    timestamp: str | None
    raw_ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "best_bid_price": str(self.best_bid_price),
            "best_ask_price": str(self.best_ask_price),
            "best_bid_size": str(self.best_bid_size),
            "best_ask_size": str(self.best_ask_size),
            "timestamp": self.timestamp,
            "raw_ok": self.raw_ok,
        }


class UpbitMarketQuoteError(ValueError):
    """시세/호가 파싱·조회 실패 (Fail Closed)."""

    def __init__(self, reason_code: str, message: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(message or reason_code)


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def _ts_iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        # Upbit ms epoch
        ms = int(value)
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
    except Exception:  # noqa: BLE001
        return str(value)


def parse_ticker_row(row: Any, *, expected_market: str | None = None) -> UpbitTickerSnapshot:
    """list/dict ticker raw → Snapshot. malformed → Fail Closed."""

    if isinstance(row, list):
        if not row:
            raise UpbitMarketQuoteError("TICKER_EMPTY", "empty ticker list")
        row = row[0]
    if not isinstance(row, dict):
        raise UpbitMarketQuoteError(
            "TICKER_MALFORMED",
            f"unexpected type={type(row).__name__}",
        )
    market = str(row.get("market") or "").strip().upper()
    if expected_market and market and market != expected_market.upper():
        raise UpbitMarketQuoteError(
            "TICKER_MARKET_MISMATCH",
            f"{market} != {expected_market}",
        )
    if not market and expected_market:
        market = expected_market.upper()
    if not market:
        raise UpbitMarketQuoteError("TICKER_NO_MARKET", "market missing")
    price = _dec(row.get("trade_price"))
    if price is None or price <= ZERO:
        raise UpbitMarketQuoteError("TICKER_NO_PRICE", "trade_price missing")
    return UpbitTickerSnapshot(
        market=market,
        trade_price=price,
        timestamp=_ts_iso(row.get("timestamp")),
        raw_ok=True,
    )


def parse_orderbook_row(
    row: Any, *, expected_market: str | None = None
) -> UpbitOrderbookSnapshot:
    """orderbook raw → Snapshot. 빈 units → Fail Closed."""

    if isinstance(row, list):
        if not row:
            raise UpbitMarketQuoteError("ORDERBOOK_EMPTY", "empty orderbook list")
        row = row[0]
    if not isinstance(row, dict):
        raise UpbitMarketQuoteError(
            "ORDERBOOK_MALFORMED",
            f"unexpected type={type(row).__name__}",
        )
    market = str(row.get("market") or "").strip().upper()
    if expected_market and market and market != expected_market.upper():
        raise UpbitMarketQuoteError(
            "ORDERBOOK_MARKET_MISMATCH",
            f"{market} != {expected_market}",
        )
    if not market and expected_market:
        market = expected_market.upper()
    if not market:
        raise UpbitMarketQuoteError("ORDERBOOK_NO_MARKET", "market missing")
    units = row.get("orderbook_units") or []
    if not isinstance(units, list) or not units:
        raise UpbitMarketQuoteError(
            "ORDERBOOK_UNITS_EMPTY", "orderbook_units empty"
        )
    first = units[0] if isinstance(units[0], dict) else None
    if not isinstance(first, dict):
        raise UpbitMarketQuoteError(
            "ORDERBOOK_UNIT_MALFORMED", "first unit not dict"
        )
    bid = _dec(first.get("bid_price"))
    ask = _dec(first.get("ask_price"))
    bid_sz = _dec(first.get("bid_size"))
    ask_sz = _dec(first.get("ask_size"))
    if bid is None or ask is None or bid <= ZERO or ask <= ZERO:
        raise UpbitMarketQuoteError(
            "ORDERBOOK_BEST_MISSING", "best bid/ask missing"
        )
    return UpbitOrderbookSnapshot(
        market=market,
        best_bid_price=bid,
        best_ask_price=ask,
        best_bid_size=bid_sz if bid_sz is not None else ZERO,
        best_ask_size=ask_sz if ask_sz is not None else ZERO,
        timestamp=_ts_iso(row.get("timestamp")),
        raw_ok=True,
    )


def mock_ticker(market: str, trade_price: Decimal) -> UpbitTickerSnapshot:
    return UpbitTickerSnapshot(
        market=market.upper(),
        trade_price=trade_price,
        timestamp=datetime.now(timezone.utc).isoformat(),
        raw_ok=True,
    )


def mock_orderbook(
    market: str, *, mid: Decimal, spread: Decimal = Decimal("1")
) -> UpbitOrderbookSnapshot:
    half = spread / Decimal("2")
    return UpbitOrderbookSnapshot(
        market=market.upper(),
        best_bid_price=mid - half,
        best_ask_price=mid + half,
        best_bid_size=Decimal("100"),
        best_ask_size=Decimal("100"),
        timestamp=datetime.now(timezone.utc).isoformat(),
        raw_ok=True,
    )


def fetch_broker_tick_size(
    market: str,
    *,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> Decimal | None:
    """GET /v1/orderbook/instruments — Broker tick 우선."""

    settings = settings or get_settings()
    base = (settings.upbit_base_url or "https://api.upbit.com").rstrip("/")
    owns = client is None
    http = client or httpx.Client(timeout=10.0)
    try:
        resp = http.get(
            f"{base}/v1/orderbook/instruments",
            params={"markets": market.upper()},
        )
        if resp.is_error:
            _logger.warning(
                "upbit_tick_instruments_http",
                extra={"reason_code": "TICK_HTTP", "status": resp.status_code},
            )
            return None
        body = resp.json()
        rows = body if isinstance(body, list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("market") or "").upper() != market.upper():
                continue
            tick = _dec(row.get("tick_size"))
            if tick is not None and tick > ZERO:
                return tick
        return None
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            "upbit_tick_instruments_error",
            extra={"reason_code": type(exc).__name__},
        )
        return None
    finally:
        if owns:
            http.close()


def round_price_to_tick(
    price: Decimal,
    tick: Decimal,
    *,
    side: str,
) -> Decimal:
    """BUY는 내림, SELL은 올림 방향 tick 정렬."""

    if price <= ZERO or tick <= ZERO:
        return ZERO
    units = (price / tick).to_integral_value(rounding=ROUND_DOWN)
    rounded = units * tick
    side_u = side.upper()
    if side_u == "SELL" and rounded < price:
        rounded = rounded + tick
    return rounded


def resolve_tick_and_price(
    *,
    market: str,
    requested_price: Decimal,
    side: str,
    settings: Settings | None = None,
    prefer_broker: bool = True,
    allow_static_fallback: bool = True,
) -> dict[str, Any]:
    """
    Broker instruments tick 우선, 실패 시 STATIC.
    allow_static_fallback=False 이면 tick 조회 실패 시 예외.
    """

    settings = settings or get_settings()
    tick: Decimal | None = None
    source = "STATIC"
    if prefer_broker and not bool(getattr(settings, "upbit_use_mock", False)):
        tick = fetch_broker_tick_size(market, settings=settings)
        if tick is not None:
            source = "BROKER"
    if tick is None:
        if not allow_static_fallback:
            raise UpbitMarketQuoteError(
                "TICK_UNAVAILABLE",
                "broker tick unavailable; static not allowed for live",
            )
        tick = upbit_tick_size(requested_price)
        source = "STATIC"
    effective = round_price_to_tick(requested_price, tick, side=side)
    reason = None
    if effective != requested_price:
        reason = (
            "ROUND_DOWN_FOR_BUY"
            if side.upper() == "BUY"
            else "ROUND_UP_FOR_SELL"
        )
    return {
        "requested_limit_price": str(requested_price),
        "effective_limit_price": str(effective),
        "tick_size": str(tick),
        "tick_source": source,
        "adjustment_reason": reason,
        "effective_price": effective,
        "tick": tick,
    }


def fetch_market_snapshots(
    market: str,
    *,
    settings: Settings | None = None,
    use_mock: bool | None = None,
    mock_mid: Decimal = Decimal("1600"),
) -> tuple[UpbitTickerSnapshot, UpbitOrderbookSnapshot]:
    """공개 ticker+orderbook 동기 조회 → 통일 DTO."""

    settings = settings or get_settings()
    market_u = market.strip().upper()
    mock = (
        bool(settings.upbit_use_mock) if use_mock is None else bool(use_mock)
    )
    if mock:
        return (
            mock_ticker(market_u, mock_mid),
            mock_orderbook(market_u, mid=mock_mid),
        )

    base = (settings.upbit_base_url or "https://api.upbit.com").rstrip("/")
    with httpx.Client(timeout=10.0) as client:
        t_resp = client.get(
            f"{base}/v1/ticker", params={"markets": market_u}
        )
        if t_resp.is_error:
            raise UpbitMarketQuoteError(
                "TICKER_HTTP",
                f"status={t_resp.status_code}",
            )
        try:
            t_body = t_resp.json()
        except ValueError as exc:
            raise UpbitMarketQuoteError("TICKER_JSON", "invalid json") from exc
        ticker = parse_ticker_row(t_body, expected_market=market_u)

        o_resp = client.get(
            f"{base}/v1/orderbook", params={"markets": market_u}
        )
        if o_resp.is_error:
            raise UpbitMarketQuoteError(
                "ORDERBOOK_HTTP",
                f"status={o_resp.status_code}",
            )
        try:
            o_body = o_resp.json()
        except ValueError as exc:
            raise UpbitMarketQuoteError(
                "ORDERBOOK_JSON", "invalid json"
            ) from exc
        book = parse_orderbook_row(o_body, expected_market=market_u)
    return ticker, book


def snapshots_as_dict(
    ticker: UpbitTickerSnapshot, book: UpbitOrderbookSnapshot
) -> dict[str, Any]:
    return {"ticker": ticker.to_dict(), "orderbook": book.to_dict()}
