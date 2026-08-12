"""UPBIT Opportunity Scanner Service — Alert-only DRY 경로.

Strategy/Deployment/Runtime/LIVE/ARM/Order 변경 금지.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

import structlog
from sqlalchemy.orm import Session

from stock_platform.broker.upbit.market.client import UpbitQuotationClient
from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_opportunity_scanner.indicators import (
    build_indicator_snapshot,
    is_abnormal_spike,
)
from stock_platform.operation.upbit_opportunity_scanner.notify import (
    publish_scanner_alerts,
)
from stock_platform.operation.upbit_opportunity_scanner.policy import (
    ScannerPolicy,
    load_scanner_policy,
    score_candidate,
)
from stock_platform.operation.upbit_opportunity_scanner.universe import (
    load_krw_universe,
)

logger = structlog.get_logger(__name__)


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class UpbitOpportunityScannerService:
    """DISCOVER → RANK → ANALYZE → NOTIFY. 주문/런타임 변경 없음."""

    def __init__(
        self,
        session: Session,
        *,
        quotation_client: UpbitQuotationClient | None = None,
        ai_runner: Callable[..., Awaitable[dict[str, Any]]] | None = None,
        now: datetime | None = None,
    ) -> None:
        self._session = session
        self._client = quotation_client
        self._ai_runner = ai_runner
        self._now = now or datetime.now(timezone.utc)
        # symbol -> last alert epoch (process memory)
        self._cooldown: dict[str, float] = {}
        self._last_alert_rec: dict[str, str] = {}

    async def run(
        self,
        *,
        policy: ScannerPolicy | None = None,
        notify: bool = True,
        force_ai: bool = False,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        policy = policy or load_scanner_policy(get_settings())
        owns_client = self._client is None
        client = self._client or UpbitQuotationClient()

        result: dict[str, Any] = {
            "ok": False,
            "alert_only": True,
            "live_auto_start": False,
            "orders_created": 0,
            "runtime_mutated": False,
            "strategy_mutated": False,
            "deployment_mutated": False,
            "policy": {
                "min_24h_trade_value_krw": policy.min_24h_trade_value_krw,
                "top_n": policy.top_n,
                "max_spike_pct": policy.max_spike_pct,
                "technical_candidate_limit": policy.technical_candidate_limit,
                "ai_enabled": policy.ai_enabled,
                "cooldown_seconds": policy.cooldown_seconds,
            },
            "universe_count": 0,
            "liquidity_pass_count": 0,
            "technical_candidate_count": 0,
            "ai_calls": 0,
            "candidates": [],
            "notifications": None,
            "errors": [],
        }

        try:
            universe = load_krw_universe(self._session)
            result["universe_count"] = len(universe)
            if not universe:
                result["ok"] = True
                result["skip_reason"] = "EMPTY_UNIVERSE"
                return result

            symbols = [u["symbol"] for u in universe]
            tickers = await self._fetch_tickers(client, symbols, policy)
            liquid = self._liquidity_filter(tickers, policy)
            result["liquidity_pass_count"] = len(liquid)

            # 거래대금 상위만 기술분석 (API 폭주 방지)
            liquid_sorted = sorted(
                liquid,
                key=lambda x: float(x.get("trade_value_24h") or 0),
                reverse=True,
            )[: policy.technical_candidate_limit]

            ranked: list[dict[str, Any]] = []
            for item in liquid_sorted:
                symbol = item["symbol"]
                try:
                    candle_rows = await client.list_minute_candles(
                        market=symbol,
                        unit=policy.candle_unit,
                        count=max(policy.min_candles, 50),
                    )
                except Exception as exc:  # noqa: BLE001
                    result["errors"].append(
                        {"symbol": symbol, "stage": "candle", "error": type(exc).__name__}
                    )
                    continue

                snap = build_indicator_snapshot(candle_rows)
                if str(snap.get("status") or "") == "INSUFFICIENT":
                    continue
                if len(candle_rows) < policy.min_candles:
                    continue

                r5 = _f(snap.get("return_5m_pct"))
                r1 = _f(snap.get("return_1m_pct"))
                vol = _f(snap.get("volatility_20m_pct"))
                if is_abnormal_spike(
                    max_spike_pct=policy.max_spike_pct,
                    return_5m_pct=r5,
                    return_1m_pct=r1,
                    volatility_20m_pct=vol,
                ):
                    continue

                surge = None
                vol_now = _f(snap.get("volume"))
                vol_ma = _f(snap.get("volume_ma20"))
                if vol_now is not None and vol_ma and vol_ma > 0:
                    surge = vol_now / vol_ma

                score, parts = score_candidate(
                    policy=policy,
                    trade_value_24h=float(item.get("trade_value_24h") or 0),
                    volume_surge=surge,
                    ma_spread_pct=_f(snap.get("ma_spread_pct")),
                    momentum_5m_pct=_f(snap.get("momentum_5m_pct")),
                    macd_histogram=_f(snap.get("macd_histogram")),
                    rsi14=_f(snap.get("rsi14")),
                    volatility_20m_pct=vol,
                )
                ranked.append(
                    {
                        "symbol": symbol,
                        "score": score,
                        "score_parts": parts,
                        "price": _f(snap.get("price"))
                        or _f(item.get("trade_price")),
                        "trade_value_24h": item.get("trade_value_24h"),
                        "ma5": _f(snap.get("ma5")),
                        "ma20": _f(snap.get("ma20")),
                        "ma_spread_pct": _f(snap.get("ma_spread_pct")),
                        "momentum_5m_pct": _f(snap.get("momentum_5m_pct")),
                        "rsi14": _f(snap.get("rsi14")),
                        "macd": _f(snap.get("macd")),
                        "macd_histogram": _f(snap.get("macd_histogram")),
                        "atr14": _f(snap.get("atr14")),
                        "volatility_20m_pct": vol,
                        "volume_surge": surge,
                        "recommendation": None,
                        "confidence": None,
                        "risk_level": None,
                        "analysis_id": None,
                        "analyzed_at": None,
                        "ai_error": None,
                    }
                )

            ranked.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
            result["technical_candidate_count"] = len(ranked)
            top = ranked[: policy.top_n]
            for index, row in enumerate(top, start=1):
                row["rank"] = index

            if policy.ai_enabled:
                await self._analyze_top(
                    top,
                    result,
                    force=force_ai,
                )
            else:
                for row in top:
                    row["recommendation"] = "HOLD"
                    row["ai_skipped"] = True

            now_ts = self._now.timestamp()
            for row in top:
                sym = str(row["symbol"])
                rec = str(row.get("recommendation") or "HOLD").upper()
                row["cooldown_suppressed"] = self._is_cooldown_suppressed(
                    symbol=sym,
                    recommendation=rec,
                    now_ts=now_ts,
                    cooldown_seconds=policy.cooldown_seconds,
                )

            result["candidates"] = top
            if notify:
                result["notifications"] = publish_scanner_alerts(
                    candidates=top,
                    notify_hold=policy.notify_hold,
                    run_meta=result,
                )
                # cooldown 갱신 — 개별 emit 또는 HOLD Top-N 요약
                summary_emitted = bool(
                    (result.get("notifications") or {}).get("summary_emitted")
                )
                for row in top:
                    if row.get("cooldown_suppressed"):
                        continue
                    rec = str(row.get("recommendation") or "HOLD").upper()
                    if rec in {"ALLOW", "REDUCE"} or policy.notify_hold:
                        self._cooldown[str(row["symbol"])] = now_ts
                        self._last_alert_rec[str(row["symbol"])] = rec
                    elif summary_emitted and rec == "HOLD":
                        # HOLD 요약 반복 방지
                        self._cooldown[str(row["symbol"])] = now_ts
                        self._last_alert_rec[str(row["symbol"])] = rec

            result["ok"] = True
            return result
        except Exception as exc:  # noqa: BLE001
            logger.exception("upbit_opportunity_scanner_failed")
            result["errors"].append(
                {"stage": "run", "error": type(exc).__name__, "message": str(exc)[:200]}
            )
            return result
        finally:
            result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
            if owns_client and self._client is None:
                await client.aclose()

    def _is_cooldown_suppressed(
        self,
        *,
        symbol: str,
        recommendation: str,
        now_ts: float,
        cooldown_seconds: float,
    ) -> bool:
        last = self._cooldown.get(symbol)
        if last is None:
            return False
        if (now_ts - last) >= float(cooldown_seconds):
            return False
        prev = self._last_alert_rec.get(symbol)
        # HOLD→ALLOW/REDUCE 는 재알림 허용
        if prev == "HOLD" and recommendation in {"ALLOW", "REDUCE"}:
            return False
        if prev != recommendation and recommendation in {"ALLOW", "REDUCE"}:
            return False
        return True

    async def _fetch_tickers(
        self,
        client: UpbitQuotationClient,
        symbols: list[str],
        policy: ScannerPolicy,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        batch = max(1, int(policy.ticker_batch_size))
        for i in range(0, len(symbols), batch):
            chunk = symbols[i : i + batch]
            try:
                rows = await client.list_tickers(markets=chunk)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "upbit_scanner_ticker_batch_failed",
                    error=type(exc).__name__,
                    size=len(chunk),
                )
                continue
            for row in rows:
                market = str(row.get("market") or "").upper()
                if not market.startswith("KRW-"):
                    continue
                out.append(
                    {
                        "symbol": market,
                        "trade_price": _f(row.get("trade_price")),
                        "trade_value_24h": _f(
                            row.get("acc_trade_price_24h")
                        )
                        or 0.0,
                        "change_rate": _f(row.get("signed_change_rate")),
                    }
                )
        return out

    def _liquidity_filter(
        self,
        tickers: list[dict[str, Any]],
        policy: ScannerPolicy,
    ) -> list[dict[str, Any]]:
        min_tv = float(policy.min_24h_trade_value_krw)
        max_spike = float(policy.max_spike_pct) / 100.0
        passed: list[dict[str, Any]] = []
        for row in tickers:
            tv = float(row.get("trade_value_24h") or 0)
            if tv < min_tv:
                continue
            if row.get("trade_price") is None:
                continue
            # 24h signed change가 과도하면 1차 제외
            chg = abs(float(row.get("change_rate") or 0))
            if chg >= max_spike:
                continue
            passed.append(row)
        return passed

    async def _analyze_top(
        self,
        top: list[dict[str, Any]],
        result: dict[str, Any],
        *,
        force: bool,
    ) -> None:
        runner = self._ai_runner
        if runner is None:

            async def _default(symbol: str) -> dict[str, Any]:
                from stock_platform.ai.market_analysis.autotrading_periodic import (
                    UpbitAutotradingAiAnalysisJob,
                )

                job = UpbitAutotradingAiAnalysisJob(self._session)
                return await job.run_once(symbol=symbol, force=force)

            runner = _default

        for row in top:
            symbol = str(row["symbol"])
            try:
                ai_out = await runner(symbol)
                result["ai_calls"] = int(result.get("ai_calls") or 0) + 1
                if ai_out.get("skipped") and ai_out.get("recommendation"):
                    row["recommendation"] = str(
                        ai_out.get("recommendation")
                    ).upper()
                else:
                    row["recommendation"] = str(
                        ai_out.get("recommendation") or "HOLD"
                    ).upper()
                row["confidence"] = ai_out.get("confidence")
                row["risk_level"] = ai_out.get("risk_level")
                row["analysis_id"] = ai_out.get("market_analysis_id")
                row["analyzed_at"] = ai_out.get("analysis_at")
                row["analysis_status"] = ai_out.get("analysis_status")
                row["trend"] = ai_out.get("trend")
                row["momentum"] = ai_out.get("momentum")
                row["volatility"] = ai_out.get("volatility")
                # Fail Closed — 검증 실패/차단 시 HOLD + 원인 보존
                if not ai_out.get("ok"):
                    if not ai_out.get("recommendation"):
                        row["recommendation"] = "HOLD"
                    row["ai_error"] = (
                        ai_out.get("error")
                        or ai_out.get("skip_reason")
                        or (
                            f"ANALYSIS_NOT_VALIDATED:{ai_out.get('analysis_status')}"
                            if ai_out.get("analysis_status")
                            else "AI_NOT_OK"
                        )
                    )
                    row["fail_closed"] = True
            except Exception as exc:  # noqa: BLE001
                result["ai_calls"] = int(result.get("ai_calls") or 0) + 1
                row["recommendation"] = "HOLD"
                row["ai_error"] = type(exc).__name__
                row["fail_closed"] = True
                result["errors"].append(
                    {
                        "symbol": symbol,
                        "stage": "ai",
                        "error": type(exc).__name__,
                    }
                )
                logger.warning(
                    "upbit_scanner_ai_failed",
                    symbol=symbol,
                    error=type(exc).__name__,
                )
