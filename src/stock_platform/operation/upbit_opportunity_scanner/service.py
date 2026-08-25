"""UPBIT Opportunity Scanner Service — Alert-only DRY 경로.

Strategy/Deployment/Runtime/LIVE/ARM/Order 변경 금지.
성능: ticker batch + candle bounded concurrency + AI 제한 병렬(세션 분리).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

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


def _ms_since(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


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
        persist_shadow: bool = True,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        policy = policy or load_scanner_policy(get_settings())
        owns_client = self._client is None
        client = self._client or UpbitQuotationClient()
        stage: dict[str, int] = {}
        api_calls: dict[str, int] = {
            "ticker_batches": 0,
            "minute_candles": 0,
            "ai_jobs": 0,
            "candle_prefetch": 0,
        }

        result: dict[str, Any] = {
            "ok": False,
            "alert_only": True,
            "live_auto_start": False,
            "orders_created": 0,
            "runtime_mutated": False,
            "strategy_mutated": False,
            "deployment_mutated": False,
            "scanner_run_id": uuid.uuid4().hex[:32],
            "policy": {
                "min_24h_trade_value_krw": policy.min_24h_trade_value_krw,
                "top_n": policy.top_n,
                "max_spike_pct": policy.max_spike_pct,
                "technical_candidate_limit": policy.technical_candidate_limit,
                "ai_enabled": policy.ai_enabled,
                "cooldown_seconds": policy.cooldown_seconds,
                "exclude_stablecoins": policy.exclude_stablecoins,
                "exclude_caution_markets": policy.exclude_caution_markets,
                "ai_backfill_enabled": policy.ai_backfill_enabled,
                "candle_concurrency": policy.candle_concurrency,
                "ai_concurrency": policy.ai_concurrency,
                "candle_timeout_seconds": policy.candle_timeout_seconds,
            },
            "universe_count": 0,
            "liquidity_pass_count": 0,
            "technical_candidate_count": 0,
            "ai_calls": 0,
            "ai_failed_skipped": 0,
            "candidates": [],
            "notifications": None,
            "shadow": None,
            "errors": [],
            "stage_timings_ms": stage,
            "api_call_counts": api_calls,
            "http_429_count": 0,
            "timeout_count": 0,
            "failed_symbol_count": 0,
        }

        try:
            t0 = time.perf_counter()
            universe = load_krw_universe(
                self._session,
                exclude_caution=policy.exclude_caution_markets,
                exclude_stablecoins=policy.exclude_stablecoins,
                stable_bases=policy.stablecoin_base_assets,
            )
            stage["UNIVERSE_LOAD_MS"] = _ms_since(t0)
            result["universe_count"] = len(universe)
            if not universe:
                result["ok"] = True
                result["skip_reason"] = "EMPTY_UNIVERSE"
                return result

            symbols = [u["symbol"] for u in universe]
            t1 = time.perf_counter()
            tickers = await self._fetch_tickers(
                client, symbols, policy, api_calls
            )
            stage["MARKET_DATA_FETCH_MS"] = _ms_since(t1)

            t2 = time.perf_counter()
            liquid = self._liquidity_filter(tickers, policy)
            stage["TECHNICAL_FILTER_MS"] = _ms_since(t2)
            result["liquidity_pass_count"] = len(liquid)

            # Stage A: 유동성 상위만 Stage B(분봉/지표) — 기존 조건만 사용
            liquid_sorted = sorted(
                liquid,
                key=lambda x: float(x.get("trade_value_24h") or 0),
                reverse=True,
            )[: policy.technical_candidate_limit]

            t3 = time.perf_counter()
            candle_map, candle_stats = await self._fetch_candles_bounded(
                client,
                [str(x["symbol"]) for x in liquid_sorted],
                policy,
                api_calls,
            )
            result["timeout_count"] = int(candle_stats.get("timeouts") or 0)
            result["http_429_count"] = int(candle_stats.get("rate_limits") or 0)
            result["failed_symbol_count"] = int(
                candle_stats.get("failed_symbols") or 0
            )
            for err in candle_stats.get("errors") or []:
                result["errors"].append(err)

            ranked: list[dict[str, Any]] = []
            for item in liquid_sorted:
                symbol = item["symbol"]
                candle_rows = candle_map.get(symbol)
                if not candle_rows:
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
            stage["CANDIDATE_RANK_MS"] = _ms_since(t3)
            result["technical_candidate_count"] = len(ranked)

            if policy.ai_enabled:
                # AI 경로 ensure_minute_candles 재호출 비용 완화 — top pool만 prefetch
                # (주입된 ai_runner=unit test 경로에서는 DB sync 생략)
                if self._ai_runner is None:
                    pool_n = max(
                        policy.top_n,
                        min(len(ranked), policy.top_n + 5),
                    )
                    prefetch_syms = [
                        str(r["symbol"]) for r in ranked[:pool_n]
                    ]
                    t_pf = time.perf_counter()
                    await self._prefetch_ai_candles(
                        prefetch_syms, policy, api_calls
                    )
                    stage["CANDLE_PREFETCH_MS"] = _ms_since(t_pf)
                else:
                    stage["CANDLE_PREFETCH_MS"] = 0

                t4 = time.perf_counter()
                top = await self._analyze_ranked(
                    ranked,
                    result,
                    top_n=policy.top_n,
                    backfill=policy.ai_backfill_enabled,
                    force=force_ai,
                    ai_concurrency=policy.ai_concurrency,
                    api_calls=api_calls,
                )
                stage["AI_GATE_MS"] = _ms_since(t4)
            else:
                top = ranked[: policy.top_n]
                for row in top:
                    row["recommendation"] = "HOLD"
                    row["ai_skipped"] = True
                stage["AI_GATE_MS"] = 0

            for index, row in enumerate(top, start=1):
                row["rank"] = index

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
                        self._cooldown[str(row["symbol"])] = now_ts
                        self._last_alert_rec[str(row["symbol"])] = rec

            t5 = time.perf_counter()
            if persist_shadow:
                try:
                    from stock_platform.operation.upbit_opportunity_shadow import (
                        UpbitOpportunityShadowEvaluator,
                        UpbitOpportunityShadowService,
                    )

                    shadow_svc = UpbitOpportunityShadowService(
                        self._session, now=self._now
                    )
                    result["shadow"] = shadow_svc.create_from_candidates(
                        candidates=top,
                        scanner_run_id=str(result["scanner_run_id"]),
                        notify=notify,
                    )
                    eval_out = await UpbitOpportunityShadowEvaluator(
                        self._session,
                        now=self._now,
                    ).evaluate_pending(notify=notify)
                    if isinstance(result["shadow"], dict):
                        result["shadow"]["evaluation"] = {
                            "evaluated": eval_out.get("evaluated"),
                            "completed": eval_out.get("completed"),
                        }
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "upbit_scanner_shadow_failed",
                        error=type(exc).__name__,
                    )
                    result["errors"].append(
                        {
                            "stage": "shadow",
                            "error": type(exc).__name__,
                            "message": str(exc)[:200],
                        }
                    )
            stage["PERSIST_MS"] = _ms_since(t5)
            # LIVE selection은 scheduler consume hook — 여기선 시간만 placeholder
            stage.setdefault("LIVE_SELECTION_MS", 0)

            result["ok"] = True
            return result
        except Exception as exc:  # noqa: BLE001
            logger.exception("upbit_opportunity_scanner_failed")
            result["errors"].append(
                {
                    "stage": "run",
                    "error": type(exc).__name__,
                    "message": str(exc)[:200],
                }
            )
            return result
        finally:
            result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
            result["stage_timings_ms"] = stage
            result["api_call_counts"] = api_calls
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
        api_calls: dict[str, int],
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        batch = max(1, int(policy.ticker_batch_size))
        for i in range(0, len(symbols), batch):
            chunk = symbols[i : i + batch]
            try:
                api_calls["ticker_batches"] = (
                    int(api_calls.get("ticker_batches") or 0) + 1
                )
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
                        "trade_value_24h": _f(row.get("acc_trade_price_24h"))
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
            chg = abs(float(row.get("change_rate") or 0))
            if chg >= max_spike:
                continue
            passed.append(row)
        return passed

    async def _fetch_candles_bounded(
        self,
        client: UpbitQuotationClient,
        symbols: list[str],
        policy: ScannerPolicy,
        api_calls: dict[str, int],
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
        """Stage B — technical pool 분봉을 bounded concurrency로 수집."""

        sem = asyncio.Semaphore(max(1, int(policy.candle_concurrency)))
        timeout = float(policy.candle_timeout_seconds)
        out: dict[str, list[dict[str, Any]]] = {}
        errors: list[dict[str, Any]] = []
        timeouts = 0
        rate_limits = 0
        lock = asyncio.Lock()

        async def _one(symbol: str) -> None:
            nonlocal timeouts, rate_limits
            async with sem:
                try:
                    api_calls["minute_candles"] = (
                        int(api_calls.get("minute_candles") or 0) + 1
                    )
                    rows = await asyncio.wait_for(
                        client.list_minute_candles(
                            market=symbol,
                            unit=policy.candle_unit,
                            count=max(policy.min_candles, 50),
                        ),
                        timeout=timeout,
                    )
                    async with lock:
                        out[symbol] = rows
                except TimeoutError:
                    timeouts += 1
                    async with lock:
                        errors.append(
                            {
                                "symbol": symbol,
                                "stage": "candle",
                                "error": "TimeoutError",
                            }
                        )
                except Exception as exc:  # noqa: BLE001
                    name = type(exc).__name__
                    if "429" in name or "RateLimit" in name:
                        rate_limits += 1
                    async with lock:
                        errors.append(
                            {
                                "symbol": symbol,
                                "stage": "candle",
                                "error": name,
                            }
                        )

        await asyncio.gather(*[_one(s) for s in symbols])
        return out, {
            "timeouts": timeouts,
            "rate_limits": rate_limits,
            "failed_symbols": len(errors),
            "errors": errors,
        }

    async def _prefetch_ai_candles(
        self,
        symbols: list[str],
        policy: ScannerPolicy,
        api_calls: dict[str, int],
    ) -> None:
        """AI job의 ensure_minute_candles가 REST를 다시 치지 않도록 DB 워밍."""

        if not symbols:
            return
        from stock_platform.ai.market_analysis.autotrading_periodic import (
            ensure_minute_candles,
        )
        from stock_platform.database.session import get_session_factory

        sem = asyncio.Semaphore(max(1, min(4, int(policy.candle_concurrency))))
        Session = get_session_factory()

        async def _one(symbol: str) -> None:
            async with sem:
                session = Session()
                try:
                    api_calls["candle_prefetch"] = (
                        int(api_calls.get("candle_prefetch") or 0) + 1
                    )
                    await ensure_minute_candles(
                        session,
                        symbol=symbol,
                        timeframe=int(policy.candle_unit),
                        min_count=max(policy.min_candles, 30),
                        stale_seconds=120.0,
                    )
                    session.commit()
                except Exception as exc:  # noqa: BLE001
                    try:
                        session.rollback()
                    except Exception:  # noqa: BLE001
                        pass
                    logger.debug(
                        "upbit_scanner_candle_prefetch_failed",
                        symbol=symbol,
                        error=type(exc).__name__,
                    )
                finally:
                    session.close()

        await asyncio.gather(*[_one(s) for s in symbols])

    async def _analyze_ranked(
        self,
        ranked: list[dict[str, Any]],
        result: dict[str, Any],
        *,
        top_n: int,
        backfill: bool,
        force: bool,
        ai_concurrency: int = 1,
        api_calls: dict[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        """Top-N 슬롯을 검증된 AI로 채움. 순위 순회 semantics 유지 + 제한 병렬."""

        api_calls = api_calls if api_calls is not None else {}
        # 성공 가정 시 Top-N만 선분석. backfill 실패분은 아래에서 on-demand.
        pool_size = min(len(ranked), top_n)
        pool = ranked[:pool_size]
        ai_by_symbol: dict[str, dict[str, Any]] = {}

        runner = self._ai_runner
        if runner is None:
            from stock_platform.database.session import get_session_factory

            SessionFactory = get_session_factory()

            async def _default(symbol: str) -> dict[str, Any]:
                # 공유 Session 동시 사용 금지 — 호출마다 독립 세션
                from stock_platform.ai.market_analysis.autotrading_periodic import (
                    UpbitAutotradingAiAnalysisJob,
                )

                session = SessionFactory()
                try:
                    job = UpbitAutotradingAiAnalysisJob(session)
                    out = await job.run_once(symbol=symbol, force=force)
                    session.commit()
                    return out
                except Exception:
                    try:
                        session.rollback()
                    except Exception:  # noqa: BLE001
                        pass
                    raise
                finally:
                    session.close()

            runner = _default

        sem = asyncio.Semaphore(max(1, int(ai_concurrency)))

        async def _run_one(symbol: str) -> tuple[str, dict[str, Any]]:
            async with sem:
                api_calls["ai_jobs"] = int(api_calls.get("ai_jobs") or 0) + 1
                try:
                    out = await runner(symbol)
                    return symbol, out
                except Exception as exc:  # noqa: BLE001
                    return symbol, {
                        "ok": False,
                        "error": type(exc).__name__,
                        "recommendation": "HOLD",
                    }

        if pool:
            pairs = await asyncio.gather(
                *[_run_one(str(r["symbol"])) for r in pool]
            )
            for sym, out in pairs:
                ai_by_symbol[sym] = out
                result["ai_calls"] = int(result.get("ai_calls") or 0) + 1

        selected: list[dict[str, Any]] = []
        failed_budget = 0

        for row in ranked:
            if len(selected) >= top_n:
                break
            if not backfill and failed_budget + len(selected) >= top_n:
                break

            symbol = str(row["symbol"])
            if symbol in ai_by_symbol:
                ai_out = ai_by_symbol[symbol]
            else:
                # pool 밖은 필요 시에만 직렬 추가 호출 (드묾)
                try:
                    api_calls["ai_jobs"] = int(api_calls.get("ai_jobs") or 0) + 1
                    ai_out = await runner(symbol)
                    result["ai_calls"] = int(result.get("ai_calls") or 0) + 1
                except Exception as exc:  # noqa: BLE001
                    result["ai_calls"] = int(result.get("ai_calls") or 0) + 1
                    ai_out = {
                        "ok": False,
                        "error": type(exc).__name__,
                        "recommendation": "HOLD",
                    }

            if ai_out.get("error") and not ai_out.get("ok"):
                row["recommendation"] = "HOLD"
                row["ai_error"] = ai_out.get("error")
                row["fail_closed"] = True
                result["errors"].append(
                    {
                        "symbol": symbol,
                        "stage": "ai",
                        "error": str(ai_out.get("error")),
                    }
                )
            else:
                self._apply_ai_result(row, ai_out)

            if row.get("fail_closed"):
                result["ai_failed_skipped"] = (
                    int(result.get("ai_failed_skipped") or 0) + 1
                )
                if backfill:
                    failed_budget += 1
                    continue
            selected.append(row)

        if len(selected) < top_n:
            selected_syms = {str(r["symbol"]) for r in selected}
            for row in ranked:
                if len(selected) >= top_n:
                    break
                if str(row["symbol"]) in selected_syms:
                    continue
                if row.get("recommendation") is None:
                    row["recommendation"] = "HOLD"
                    row["ai_skipped"] = True
                selected.append(row)

        return selected

    def _apply_ai_result(self, row: dict[str, Any], ai_out: dict[str, Any]) -> None:
        # 캐시 hit(FRESH)은 판정 재사용 — fail-closed로 Top-N을 비우지 않음
        skip_reason = str(ai_out.get("skip_reason") or "")
        if ai_out.get("skipped") and skip_reason in {
            "FRESH_RESULT_EXISTS",
            "DUPLICATE_TIME_BUCKET",
        }:
            ai_out = {**ai_out, "ok": True}

        if ai_out.get("skipped") and ai_out.get("recommendation"):
            row["recommendation"] = str(ai_out.get("recommendation")).upper()
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