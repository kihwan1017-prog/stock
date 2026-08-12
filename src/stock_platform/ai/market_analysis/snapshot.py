"""STEP 11-7 — Snapshot builder (재현 가능 고정 Snapshot, Tick 미전송)."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.market_analysis.candle import (
    decimal_str,
    normalize_candle_row,
    to_decimal,
)
from stock_platform.ai.market_analysis.constants import (
    INDICATOR_VERSION,
    MAX_DAILY_CANDLES,
    MAX_MINUTE_CANDLES,
    MAX_SNAPSHOT_JSON_CHARS,
    MIN_DAILY_CANDLES,
    STALE_DAYS_KRX,
    STALE_DAYS_UPBIT,
)
from stock_platform.ai.market_analysis.minute_indicators import (
    compute_minute_chart_indicators,
)
from stock_platform.markets.models import (
    CandleMinute,
    IndicatorDaily,
    Instrument,
    PriceDaily,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class MarketSnapshotBuilder:
    def __init__(self, session: Session) -> None:
        self._session = session

    def resolve_instrument(
        self, *, exchange_code: str, symbol: str
    ) -> Instrument | None:
        return self._session.scalar(
            select(Instrument).where(
                Instrument.exchange_code == exchange_code.upper(),
                Instrument.symbol == symbol,
            )
        )

    def build_chart_snapshot(
        self,
        *,
        exchange_code: str,
        symbol: str,
        timeframe: str = "1D",
        data_from: date | None = None,
        data_to: date | None = None,
        include_incomplete_candle: bool = False,
        max_candles: int | None = None,
    ) -> dict[str, Any]:
        exchange = exchange_code.upper()
        inst = self.resolve_instrument(exchange_code=exchange, symbol=symbol)
        if inst is None:
            return {
                "ok": False,
                "code": "INSTRUMENT_NOT_FOUND",
                "message": f"{exchange}:{symbol} not found",
            }

        if timeframe == "1D":
            return self._daily_snapshot(
                inst,
                exchange=exchange,
                symbol=symbol,
                data_from=data_from,
                data_to=data_to,
                include_incomplete=include_incomplete_candle,
                max_candles=max_candles or MAX_DAILY_CANDLES,
            )
        if timeframe in {"1m", "3m", "5m", "15m"}:
            if exchange != "UPBIT":
                return {
                    "ok": False,
                    "code": "TIMEFRAME_UNSUPPORTED",
                    "message": "minute candles only for UPBIT",
                }
            return self._minute_snapshot(
                inst,
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                include_incomplete=include_incomplete_candle,
                max_candles=max_candles or MAX_MINUTE_CANDLES,
            )
        return {
            "ok": False,
            "code": "INVALID_TIMEFRAME",
            "message": f"unsupported timeframe {timeframe}",
        }

    def build_market_overview(
        self,
        *,
        exchange_code: str,
        symbol_limit: int = 20,
    ) -> dict[str, Any]:
        exchange = exchange_code.upper()
        instruments = list(
            self._session.scalars(
                select(Instrument)
                .where(
                    Instrument.exchange_code == exchange,
                    Instrument.is_active.is_(True),
                )
                .limit(min(symbol_limit, 50))
            )
        )
        if not instruments:
            return {
                "ok": False,
                "code": "NO_INSTRUMENTS",
                "message": "no active instruments",
            }

        summaries: list[dict[str, Any]] = []
        warnings: list[str] = []
        for inst in instruments:
            rows = list(
                self._session.scalars(
                    select(PriceDaily)
                    .where(PriceDaily.instrument_id == inst.instrument_id)
                    .order_by(PriceDaily.trade_date.desc())
                    .limit(5)
                )
            )
            if not rows:
                continue
            latest = rows[0]
            summaries.append(
                {
                    "symbol": inst.symbol,
                    "trade_date": latest.trade_date.isoformat(),
                    "close": decimal_str(latest.close_price),
                    "volume": decimal_str(latest.volume),
                    "change_rate": decimal_str(latest.change_rate)
                    if latest.change_rate is not None
                    else None,
                }
            )
        if len(summaries) < 3:
            return {
                "ok": False,
                "code": "DATA_INSUFFICIENT",
                "message": "need at least 3 symbols with prices",
            }

        body = {
            "analysis_type": "MARKET_OVERVIEW",
            "market_type": "CRYPTO" if exchange == "UPBIT" else "KR_STOCK",
            "exchange_code": exchange,
            "timezone": "Asia/Seoul",
            "snapshot_at": _now().isoformat(),
            "symbol_count": len(summaries),
            "symbols": summaries,
            "completed_candle_only": True,
            "indicator_version": INDICATOR_VERSION,
            "vision_used": False,
        }
        snapshot_hash = _hash_payload(body)
        quality = self._overview_quality(summaries, exchange)
        return {
            "ok": True,
            "snapshot": body,
            "snapshot_key": f"market:{exchange}:{snapshot_hash[:16]}",
            "snapshot_hash": snapshot_hash,
            "snapshot_version": "1",
            "data_quality_status": quality["status"],
            "quality_warnings": quality["warnings"] + warnings,
            "candle_count": 0,
            "downsampled": False,
        }

    def _daily_snapshot(
        self,
        inst: Instrument,
        *,
        exchange: str,
        symbol: str,
        data_from: date | None,
        data_to: date | None,
        include_incomplete: bool,
        max_candles: int,
    ) -> dict[str, Any]:
        end = data_to or date.today()
        start = data_from or (end - timedelta(days=max_candles * 2))
        rows = list(
            self._session.scalars(
                select(PriceDaily)
                .where(
                    PriceDaily.instrument_id == inst.instrument_id,
                    PriceDaily.trade_date >= start,
                    PriceDaily.trade_date <= end,
                )
                .order_by(PriceDaily.trade_date.asc())
            )
        )
        warnings: list[str] = []
        if len(rows) > max_candles:
            # 무음 절단 금지 — 명시적 downsampling (최근 N개 유지)
            dropped = len(rows) - max_candles
            rows = rows[-max_candles:]
            warnings.append(f"downsampled_drop_oldest:{dropped}")
            downsampled = True
        else:
            downsampled = False

        if len(rows) < MIN_DAILY_CANDLES:
            return {
                "ok": False,
                "code": "DATA_INSUFFICIENT",
                "message": f"need >= {MIN_DAILY_CANDLES} daily candles",
                "candle_count": len(rows),
            }

        candles: list[dict[str, Any]] = []
        quality_flags: list[str] = []
        seen_dates: set[date] = set()
        duplicates = 0
        for r in rows:
            if r.trade_date in seen_dates:
                duplicates += 1
                continue
            seen_dates.add(r.trade_date)
            # 일봉은 거래일 종가 기준 complete (당일 미완성 포함은 명시 플래그)
            is_complete = True
            if not include_incomplete and r.trade_date == date.today():
                # 당일 봉은 기본 제외
                warnings.append("excluded_today_incomplete_candle")
                continue
            if include_incomplete and r.trade_date == date.today():
                is_complete = False
            try:
                candle = normalize_candle_row(
                    {
                        "open_time": r.trade_date.isoformat(),
                        "close_time": r.trade_date.isoformat(),
                        "open": r.open_price,
                        "high": r.high_price,
                        "low": r.low_price,
                        "close": r.close_price,
                        "volume": r.volume,
                        "quote_volume": r.trade_value,
                        "is_complete": is_complete,
                        "source": r.source,
                        "adjusted": exchange == "KRX",
                    }
                )
            except ValueError as exc:
                return {
                    "ok": False,
                    "code": "INVALID_CANDLE",
                    "message": str(exc),
                }
            quality_flags.extend(candle["quality_flags"])
            candles.append(candle)

        if duplicates:
            warnings.append(f"duplicates_skipped:{duplicates}")
        if quality_flags:
            warnings.append("ohlc_quality_flags_present")

        indicators = self._latest_indicators(inst.instrument_id, candles)
        latest_close = candles[-1]["close"] if candles else None
        body = {
            "analysis_type": "SYMBOL_CHART",
            "market_type": "CRYPTO" if exchange == "UPBIT" else "KR_STOCK",
            "exchange_code": exchange,
            "symbol": symbol,
            "timeframe": "1D",
            "timezone": "Asia/Seoul",
            "snapshot_at": _now().isoformat(),
            "candle_from": candles[0]["open_time"] if candles else None,
            "candle_to": candles[-1]["close_time"] if candles else None,
            "candle_count": len(candles),
            "candles": candles,
            "indicators": indicators,
            "latest_price": latest_close,
            "completed_candle_only": not include_incomplete,
            "include_incomplete_candle": include_incomplete,
            "indicator_version": INDICATOR_VERSION,
            "vision_used": False,
            "downsampled": downsampled,
        }
        # 입력 크기 제한 — candles 과다 시 요약만 남김
        raw = json.dumps(body, ensure_ascii=False, default=str)
        if len(raw) > MAX_SNAPSHOT_JSON_CHARS:
            # 최근 60봉만 유지 + 통계 요약 (무음 절단 아님 — warning)
            keep = min(60, len(candles))
            body["candles"] = candles[-keep:]
            body["candle_count"] = keep
            body["full_candle_count_before_compact"] = len(candles)
            warnings.append("snapshot_compacted_for_token_budget")
            downsampled = True
            body["downsampled"] = True

        snapshot_hash = _hash_payload(body)
        quality = self._chart_quality(
            candles, exchange=exchange, duplicates=duplicates, flags=quality_flags
        )
        return {
            "ok": True,
            "snapshot": body,
            "snapshot_key": (
                f"chart:{exchange}:{symbol}:1D:{snapshot_hash[:16]}"
            ),
            "snapshot_hash": snapshot_hash,
            "snapshot_version": "1",
            "data_quality_status": quality["status"],
            "quality_warnings": quality["warnings"] + warnings,
            "candle_count": body["candle_count"],
            "downsampled": downsampled,
            "instrument_id": inst.instrument_id,
        }

    def _minute_snapshot(
        self,
        inst: Instrument,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        include_incomplete: bool,
        max_candles: int,
    ) -> dict[str, Any]:
        tf_min = int(timeframe.replace("m", ""))
        rows = list(
            self._session.scalars(
                select(CandleMinute)
                .where(
                    CandleMinute.instrument_id == inst.instrument_id,
                    CandleMinute.timeframe == tf_min,
                )
                .order_by(CandleMinute.candle_at.desc())
                .limit(max_candles + 5)
            )
        )
        rows = list(reversed(rows))
        warnings: list[str] = []
        downsampled = False
        if len(rows) > max_candles:
            dropped = len(rows) - max_candles
            rows = rows[-max_candles:]
            warnings.append(f"downsampled_drop_oldest:{dropped}")
            downsampled = True
        if len(rows) < 20:
            return {
                "ok": False,
                "code": "DATA_INSUFFICIENT",
                "message": "need >= 20 minute candles",
                "candle_count": len(rows),
            }

        candles = []
        for r in rows:
            is_complete = True
            if not include_incomplete:
                # 최신 1개는 미완성 가능 → 기본 제외
                if r is rows[-1]:
                    warnings.append("excluded_latest_incomplete_minute")
                    continue
            else:
                if r is rows[-1]:
                    is_complete = False
            try:
                candle = normalize_candle_row(
                    {
                        "open_time": r.candle_at.isoformat(),
                        "close_time": r.candle_at.isoformat(),
                        "open": r.open_price,
                        "high": r.high_price,
                        "low": r.low_price,
                        "close": r.close_price,
                        "volume": r.volume,
                        "quote_volume": r.trade_value,
                        "is_complete": is_complete,
                        "source": r.source,
                        "adjusted": False,
                    }
                )
            except ValueError as exc:
                return {"ok": False, "code": "INVALID_CANDLE", "message": str(exc)}
            candles.append(candle)

        if len(candles) < 20:
            return {
                "ok": False,
                "code": "DATA_INSUFFICIENT",
                "message": "need >= 20 complete minute candles",
                "candle_count": len(candles),
            }

        # 분봉 freshness — ticker HEALTHY와 별도로 stale면 분석 거부
        try:
            last_raw = str(candles[-1]["close_time"])
            last_at = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
            if last_at.tzinfo is None:
                last_at = last_at.replace(tzinfo=timezone.utc)
            candle_age = (
                _now() - last_at.astimezone(timezone.utc)
            ).total_seconds()
            if candle_age > 600.0:
                return {
                    "ok": False,
                    "code": "STALE_CANDLE",
                    "message": "latest minute candle older than 600s",
                    "age_seconds": candle_age,
                    "candle_count": len(candles),
                }
        except (TypeError, ValueError):
            warnings.append("candle_timestamp_parse_failed")

        body = {
            "analysis_type": "SYMBOL_CHART",
            "market_type": "CRYPTO",
            "exchange_code": exchange,
            "symbol": symbol,
            "timeframe": timeframe,
            "timezone": "UTC",
            "snapshot_at": _now().isoformat(),
            "candle_from": candles[0]["open_time"] if candles else None,
            "candle_to": candles[-1]["close_time"] if candles else None,
            "candle_count": len(candles),
            "candles": candles,
            "indicators": compute_minute_chart_indicators(candles),
            "latest_price": candles[-1]["close"] if candles else None,
            "completed_candle_only": not include_incomplete,
            "include_incomplete_candle": include_incomplete,
            "indicator_version": INDICATOR_VERSION,
            "vision_used": False,
            "downsampled": downsampled,
        }
        # 입력 크기 제한 — 1m 다봉은 execution MAX_INPUT(40k) 초과 가능
        # 일봉 compact 임계(60k)보다 낮게 유지
        raw = json.dumps(body, ensure_ascii=False, default=str)
        minute_budget = min(MAX_SNAPSHOT_JSON_CHARS, 28_000)
        if len(raw) > minute_budget:
            keep = min(45, len(candles))
            body["candles"] = candles[-keep:]
            body["candle_count"] = keep
            body["full_candle_count_before_compact"] = len(candles)
            warnings.append("snapshot_compacted_for_token_budget")
            downsampled = True
            body["downsampled"] = True

        snapshot_hash = _hash_payload(body)
        quality = self._chart_quality(candles, exchange=exchange, duplicates=0, flags=[])
        return {
            "ok": True,
            "snapshot": body,
            "snapshot_key": (
                f"chart:{exchange}:{symbol}:{timeframe}:{snapshot_hash[:16]}"
            ),
            "snapshot_hash": snapshot_hash,
            "snapshot_version": "1",
            "data_quality_status": quality["status"],
            "quality_warnings": quality["warnings"] + warnings,
            "candle_count": body["candle_count"],
            "downsampled": downsampled,
            "instrument_id": inst.instrument_id,
        }

    def _latest_indicators(
        self, instrument_id: int, candles: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if not candles:
            return {}
        last_date = date.fromisoformat(str(candles[-1]["close_time"])[:10])
        row = self._session.get(IndicatorDaily, (instrument_id, last_date))
        if row is None:
            # 최근 indicator 아무거나
            row = self._session.scalar(
                select(IndicatorDaily)
                .where(IndicatorDaily.instrument_id == instrument_id)
                .order_by(IndicatorDaily.trade_date.desc())
                .limit(1)
            )
        if row is None:
            return {"status": "MISSING", "version": INDICATOR_VERSION}
        return {
            "version": INDICATOR_VERSION,
            "trade_date": row.trade_date.isoformat(),
            "status_code": row.status_code,
            "ma5": decimal_str(row.ma5),
            "ma20": decimal_str(row.ma20),
            "ma60": decimal_str(row.ma60),
            "ema12": decimal_str(row.ema12),
            "ema26": decimal_str(row.ema26),
            "rsi14": decimal_str(row.rsi14),
            "macd": decimal_str(row.macd),
            "macd_signal": decimal_str(row.macd_signal),
            "macd_histogram": decimal_str(row.macd_histogram),
            "bollinger_upper": decimal_str(row.bollinger_upper),
            "bollinger_middle": decimal_str(row.bollinger_middle),
            "bollinger_lower": decimal_str(row.bollinger_lower),
            "atr14": decimal_str(row.atr14),
            "volume_ma20": decimal_str(getattr(row, "volume_ma20", None)),
        }

    def _chart_quality(
        self,
        candles: list[dict[str, Any]],
        *,
        exchange: str,
        duplicates: int,
        flags: list[str],
    ) -> dict[str, Any]:
        warnings: list[str] = []
        if not candles:
            return {"status": "INVALID", "warnings": ["no_candles"]}
        if any(f for f in flags if f.startswith("NEGATIVE") or "INCONSISTENT" in f):
            return {"status": "INVALID", "warnings": flags}
        if duplicates:
            warnings.append("DUPLICATE_DETECTED")
            status = "DUPLICATE_DETECTED"
        else:
            status = "GOOD"

        # gap: 일봉 날짜 간격 (주말 허용)
        if len(candles) >= 2 and candles[0]["open_time"] and "T" not in str(
            candles[0]["open_time"]
        ):
            dates = [date.fromisoformat(str(c["open_time"])[:10]) for c in candles]
            max_gap = 1 if exchange == "UPBIT" else 4
            for a, b in zip(dates, dates[1:]):
                if (b - a).days > max_gap:
                    warnings.append("GAP_DETECTED")
                    status = "GAP_DETECTED"
                    break

        # stale
        last = str(candles[-1]["close_time"])[:10]
        try:
            last_d = date.fromisoformat(last)
            stale_limit = (
                STALE_DAYS_UPBIT if exchange == "UPBIT" else STALE_DAYS_KRX
            )
            if (date.today() - last_d).days > stale_limit:
                warnings.append("STALE")
                status = "STALE"
        except ValueError:
            warnings.append("bad_last_date")

        incomplete = sum(1 for c in candles if not c.get("is_complete", True))
        if incomplete:
            warnings.append("INCOMPLETE")
            if status == "GOOD":
                status = "INCOMPLETE"

        if status == "GOOD" and warnings:
            status = "ACCEPTABLE"
        return {"status": status, "warnings": warnings}

    def _overview_quality(
        self, summaries: list[dict[str, Any]], exchange: str
    ) -> dict[str, Any]:
        warnings: list[str] = []
        status = "GOOD"
        stale_limit = STALE_DAYS_UPBIT if exchange == "UPBIT" else STALE_DAYS_KRX
        for s in summaries:
            try:
                d = date.fromisoformat(s["trade_date"])
                if (date.today() - d).days > stale_limit:
                    warnings.append(f"stale:{s['symbol']}")
                    status = "STALE"
            except ValueError:
                continue
        if status == "GOOD" and len(summaries) < 5:
            status = "ACCEPTABLE"
            warnings.append("few_symbols")
        return {"status": status, "warnings": warnings}


def validate_ai_numerics(
    *,
    snapshot: dict[str, Any],
    result_body: dict[str, Any],
) -> list[str]:
    """AI 수치를 내부 Snapshot과 대조 — mismatch는 warning."""

    warnings: list[str] = []
    # symbol/timeframe mismatch
    if snapshot.get("symbol") and result_body.get("symbol"):
        if str(result_body["symbol"]) != str(snapshot["symbol"]):
            warnings.append("AI_SYMBOL_MISMATCH")
    if snapshot.get("timeframe") and result_body.get("timeframe"):
        if str(result_body["timeframe"]) != str(snapshot["timeframe"]):
            warnings.append("AI_TIMEFRAME_MISMATCH")

    # support/resistance must be within candle range if numeric
    closes = []
    for c in snapshot.get("candles") or []:
        try:
            closes.append(to_decimal(c["close"]))
        except ValueError:
            continue
    if closes:
        lo = min(closes)
        hi = max(closes)
        span = hi - lo if hi > lo else Decimal("1")
        for key in ("support_levels", "resistance_levels"):
            for level in result_body.get(key) or []:
                try:
                    price = to_decimal(level)
                except ValueError:
                    continue
                # 가격이 범위의 5배 밖이면 mismatch
                if price < lo - span * 5 or price > hi + span * 5:
                    warnings.append("AI_NUMERIC_MISMATCH_LEVEL")
    return warnings
