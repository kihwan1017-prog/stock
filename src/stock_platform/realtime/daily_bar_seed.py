"""1D LIVE warmup seed — completed daily bars + optional current-day REST bootstrap.

REST는 restart bootstrap 전용이다. LIVE 신호 SoT가 아니다.
price_daily persist는 collector 책임이며 여기서 쓰지 않는다.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable
from zoneinfo import ZoneInfo

import structlog

from stock_platform.realtime.ma_evaluator import MovingAverageStrategyEvaluator
from stock_platform.realtime.strategy_models import uses_daily_bars


logger = structlog.get_logger(__name__)
_KST = ZoneInfo("Asia/Seoul")
_UPBIT_DAY_CANDLE_URL = "https://api.upbit.com/v1/candles/days"


def today_kst(now: datetime | None = None) -> date:
    moment = now or datetime.now(_KST)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_KST)
    return moment.astimezone(_KST).date()


def required_completed_bars(long_window: int) -> int:
    """LIVE deque maxlen=long_window+1 과 Backtest index>=long_window 정렬."""

    return max(1, int(long_window) + 1)


def price_daily_exchange_code(
    *,
    broker_code: str | None,
    market_type: str | None = None,
) -> str:
    """broker_code → market.price_daily.instrument.exchange_code 매핑.

    Kiwoom 실행 스코프는 broker_code=KIWOOM 이지만 일봉 instrument는 KRX다.
    UPBIT/CRYPTO는 UPBIT. PAPER는 레거시 Upbit 시세 가정.
    """

    bc = str(broker_code or "").strip().upper()
    mt = str(market_type or "").strip().upper()
    if mt in {"CRYPTO", "UPBIT"} or bc in {"UPBIT", "PAPER"}:
        return "UPBIT"
    if mt in {"STOCK", "KRX", "KOSPI", "KOSDAQ", "KR_STOCK"} or bc in {
        "KIWOOM",
        "KRX",
    }:
        return "KRX"
    return bc or "UPBIT"


def load_completed_daily_closes(
    session: Any,
    *,
    exchange_code: str,
    symbol: str,
    required: int,
    today: date | None = None,
) -> list[tuple[date, Decimal]]:
    """오늘 KST incomplete bar를 제외한 completed daily close."""

    from stock_platform.markets.repository import PriceDailyRepository

    cutoff = today or today_kst()
    repo = PriceDailyRepository(session)
    instrument = repo.find_instrument(exchange_code.upper(), symbol.upper())
    if instrument is None:
        return []
    # 오늘 행이 섞여 있을 수 있어 여유분 조회 후 필터
    rows = repo.list_recent(
        int(instrument.instrument_id),
        limit=max(required + 5, required),
    )
    closes: list[tuple[date, Decimal]] = []
    for row in rows:
        trade_date = row.trade_date
        if trade_date >= cutoff:
            continue
        closes.append((trade_date, Decimal(str(row.close_price))))
    if len(closes) > required:
        return closes[-required:]
    return closes


def fetch_upbit_current_day_close(
    market: str,
    *,
    today: date | None = None,
    http_get: Callable[[str], list[dict[str, Any]]] | None = None,
) -> tuple[date, Decimal] | None:
    """공개 /v1/candles/days count=1. LIVE 신호 SoT가 아님."""

    cutoff = today or today_kst()
    symbol = str(market or "").strip().upper()
    if not symbol:
        return None
    rows = http_get(symbol) if http_get is not None else _http_get_day_candles(symbol)
    if not rows:
        return None
    first = rows[0]
    raw_kst = str(first.get("candle_date_time_kst") or "")
    trade_date = _parse_candle_date(raw_kst)
    if trade_date is None or trade_date != cutoff:
        return None
    price = first.get("trade_price")
    if price is None:
        return None
    return trade_date, Decimal(str(price))


def _parse_candle_date(raw_kst: str) -> date | None:
    text = str(raw_kst or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _http_get_day_candles(market: str) -> list[dict[str, Any]]:
    url = f"{_UPBIT_DAY_CANDLE_URL}?market={market}&count=1"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "stock-platform-bootstrap"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []
    if not isinstance(payload, list):
        return []
    return payload


def _allow_rest_bootstrap() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    if str(os.environ.get("STOCK_PLATFORM_DISABLE_UPBIT_DAILY_BOOTSTRAP") or "").strip() == "1":
        return False
    try:
        from stock_platform.common.settings import get_settings

        if bool(getattr(get_settings(), "upbit_use_mock", False)):
            return False
    except Exception:  # noqa: BLE001
        return False
    return True


def seed_evaluator_daily_bars(
    evaluator: MovingAverageStrategyEvaluator,
    *,
    symbols: list[str] | set[str],
    exchange_code: str,
    bootstrap_current_day: bool = True,
    session: Any | None = None,
    today: date | None = None,
    current_day_close: tuple[date, Decimal] | None = None,
) -> dict[str, Any]:
    """completed history seed + optional current-day bootstrap. 신호 없음."""

    if not evaluator.config.uses_daily_bars():
        return {"seeded": False, "reason": "not_daily"}

    cutoff = today or today_kst()
    required = required_completed_bars(evaluator.config.long_window)
    own_session = session is None
    opened = session
    per_symbol: dict[str, Any] = {}
    try:
        if opened is None:
            from stock_platform.database.session import get_session_factory

            opened = get_session_factory()()
        for symbol in sorted({str(s).upper().strip() for s in symbols if str(s).strip()}):
            closes = load_completed_daily_closes(
                opened,
                exchange_code=exchange_code,
                symbol=symbol,
                required=required,
                today=cutoff,
            )
            seeded = evaluator.seed_completed_closes(symbol, closes)
            latest = closes[-1][0].isoformat() if closes else None
            bootstrap: dict[str, Any] | None = None
            rolling = current_day_close
            if rolling is None and bootstrap_current_day and _allow_rest_bootstrap():
                try:
                    rolling = fetch_upbit_current_day_close(symbol, today=cutoff)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "daily_bar_current_day_bootstrap_failed",
                        symbol=symbol,
                        error_type=exc.__class__.__name__,
                    )
                    rolling = None
            if rolling is not None:
                evaluator.prime_current_day_bar(
                    symbol,
                    trade_date=rolling[0],
                    close=rolling[1],
                )
                bootstrap = {
                    "source": "rest_or_injected",
                    "trade_date": rolling[0].isoformat(),
                    "note": "restart_bootstrap_only",
                }
            per_symbol[symbol] = {
                "seeded_bars": seeded,
                "required_bars": required,
                "latest_completed_date": latest,
                "today_kst": cutoff.isoformat(),
                "bootstrap": bootstrap,
                "warmup": evaluator.warmup_status(symbol).value,
            }
    finally:
        if own_session and opened is not None:
            opened.close()

    return {
        "seeded": True,
        "source": "market.price_daily",
        "today_kst": cutoff.isoformat(),
        "symbols": per_symbol,
    }


def seed_registered_consumer(
    consumer: Any,
    *,
    force: bool = False,
    bootstrap_current_day: bool = True,
    session: Any | None = None,
) -> dict[str, Any]:
    """Hub consumer 등록/rewarm 후 1D seed. persist/주문 없음."""

    evaluator = consumer.evaluator
    if not uses_daily_bars(evaluator.config.timeframe):
        return {"seeded": False, "reason": "not_daily"}
    if not force:
        already = any(
            len(evaluator.get_state(sym).prices) > 0 for sym in consumer.symbols
        )
        if already:
            return {"seeded": False, "reason": "already_warmed"}
    scope = getattr(consumer, "scope", None)
    exchange = price_daily_exchange_code(
        broker_code=getattr(scope, "broker_code", None),
        market_type=getattr(scope, "market_type", None),
    )
    return seed_evaluator_daily_bars(
        evaluator,
        symbols=list(consumer.symbols),
        exchange_code=exchange,
        bootstrap_current_day=bootstrap_current_day,
        session=session,
    )
