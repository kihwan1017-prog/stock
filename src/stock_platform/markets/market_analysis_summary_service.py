"""시장 분석 사용자 Summary — UI projection only (NOT a trading gate)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.markets.user_friendly_reasons import friendly_reason
from stock_platform.markets.collection_status_service import (
    MarketDataCollectionStatusService,
)
from stock_platform.operation.calendar_repository import TradingCalendarRepository
from stock_platform.operation.calendar_service import TradingCalendarService
from stock_platform.operation.upbit_market_context.snapshot_service import (
    MarketContextSnapshotService,
)
from stock_platform.trading.market_hours_authorization import (
    krx_market_hours_state,
)

_KST = ZoneInfo("Asia/Seoul")

class MarketAnalysisSummaryService:
    """읽기 전용 시장 요약. REAL gate/policy에 연결하지 않는다."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._quality = MarketDataCollectionStatusService(session)
        self._calendar = TradingCalendarService(TradingCalendarRepository(session))
        self._ctx = MarketContextSnapshotService(session)

    def summary(self) -> dict[str, Any]:
        now = datetime.now(_KST)
        quality_items = [asdict(q) for q in self._quality.quality_dashboard()]
        kiwoom = self._kiwoom_block(now, quality_items)
        upbit = self._upbit_block(now, quality_items)
        entry_env = self._entry_environment_projection(kiwoom, upbit)
        return {
            "generated_at": now.isoformat(),
            "disclaimer": (
                "사용자 설명용 projection입니다. REAL 주문/진입 게이트가 아닙니다."
            ),
            "kiwoom": kiwoom,
            "upbit": upbit,
            "autotrading_projection": entry_env,
            "data_trust": self._data_trust(quality_items),
            "autotrading_context": self._autotrading_context(),
        }

    def _kiwoom_block(self, now: datetime, quality: list[dict]) -> dict[str, Any]:
        hours = krx_market_hours_state(self._session)
        is_td = bool(hours.get("is_trading_day"))
        in_session = bool(hours.get("in_regular_session"))
        past_close = bool(hours.get("past_close"))

        if not is_td:
            session_status = "CLOSED"
            session_label = "⚪ 장 마감(휴장)"
        elif in_session:
            session_status = "OPEN"
            session_label = "🟢 장중"
        elif past_close:
            session_status = "CLOSED"
            session_label = "⚪ 장 마감"
        else:
            session_status = "PREOPEN"
            session_label = "🟡 장 시작 전"

        breadth = self._krx_breadth()
        up_ratio = breadth.get("up_ratio")
        direction = "혼조"
        tone = "MIXED"
        if up_ratio is not None:
            if up_ratio >= 0.58:
                direction, tone = "상승 종목 우세", "BULLISH"
            elif up_ratio <= 0.42:
                direction, tone = "하락 종목 우세", "BEARISH"

        vol = breadth.get("volatility_hint") or "보통"
        narrative = (
            f"현재 코스피/코스닥 시장은 {direction}이며 변동성은 {vol}입니다."
            if is_td
            else "오늘은 국내 주식 휴장일로 정규 거래가 없습니다."
        )

        daily_q = next(
            (q for q in quality if q["exchange_code"] == "KRX" and q["data_kind"] == "DAILY"),
            None,
        )
        return {
            "market": "KIWOOM",
            "session_status": session_status,
            "session_label": session_label,
            "direction": direction,
            "tone": tone,
            "volatility": vol,
            "trade_mood": breadth.get("trade_mood") or "보통",
            "breadth": breadth,
            "narrative": narrative,
            "user_status": (
                "CLOSED"
                if session_status == "CLOSED"
                else ("CAUTION" if tone == "BEARISH" else "OK")
            ),
            "user_status_label": (
                "⚪ 장 마감"
                if session_status == "CLOSED"
                else ("🟠 혼조/약세" if tone != "BULLISH" else "🟢 정상")
            ),
            "data_source": {
                "basis": "일봉(+세션)",
                "last_collect": daily_q.get("latest_date") if daily_q else None,
                "quality": daily_q.get("status_label") if daily_q else "—",
            },
        }

    def _upbit_block(self, now: datetime, quality: list[dict]) -> dict[str, Any]:
        fear = self._latest_feature("fear_greed")
        adv = self._latest_feature("advancing_asset_ratio")
        turn = self._latest_feature("24h_turnover")
        mret = self._latest_feature("market_return")

        fng_val = None
        if fear and isinstance(fear.get("value_json"), dict):
            fng_val = fear["value_json"].get("value")

        up_ratio = None
        if adv and isinstance(adv.get("value_json"), dict):
            raw = adv["value_json"].get("ratio") or adv["value_json"].get("value")
            try:
                up_ratio = float(raw)
                if up_ratio > 1:
                    up_ratio = up_ratio / 100.0
            except (TypeError, ValueError):
                up_ratio = None

        direction = "혼조"
        tone = "MIXED"
        if up_ratio is not None:
            if up_ratio >= 0.55:
                direction, tone = "상승 종목 우세", "BULLISH"
            elif up_ratio <= 0.45:
                direction, tone = "하락 종목 우세", "BEARISH"

        vol = "보통"
        if mret and isinstance(mret.get("value_json"), dict):
            try:
                abs_ret = abs(float(mret["value_json"].get("value") or 0))
                vol = "높음" if abs_ret >= 0.03 else ("낮음" if abs_ret < 0.01 else "보통")
            except (TypeError, ValueError):
                pass

        turnover_hint = "보통"
        if turn and isinstance(turn.get("value_json"), dict):
            turnover_hint = str(turn["value_json"].get("trend") or "보통")

        narrative = (
            f"{direction} 상태입니다. "
            + (
                f"Fear & Greed {fng_val}, "
                if fng_val is not None
                else ""
            )
            + f"변동성은 {vol}입니다."
        )
        if vol == "높음":
            narrative += " 진입 후 가격 변동에 주의가 필요합니다."

        daily_q = next(
            (
                q
                for q in quality
                if q["exchange_code"] == "UPBIT" and q["data_kind"] == "DAILY"
            ),
            None,
        )
        minute_q = next(
            (
                q
                for q in quality
                if q["exchange_code"] == "UPBIT" and q["data_kind"] == "MINUTE"
            ),
            None,
        )

        user_status = "OK"
        user_label = "🟢 정상"
        if vol == "높음" or tone == "MIXED":
            user_status, user_label = "VOLATILE", "🟠 변동성 높음/혼조"
        if tone == "BEARISH":
            user_status, user_label = "CAUTION", "🟡 주의"

        return {
            "market": "UPBIT",
            "direction": direction,
            "tone": tone,
            "fear_greed": fng_val,
            "up_ratio": round(up_ratio, 3) if up_ratio is not None else None,
            "up_ratio_pct": round(up_ratio * 100, 1) if up_ratio is not None else None,
            "turnover": turnover_hint,
            "volatility": vol,
            "btc_eth_direction": self._btc_eth_direction(),
            "narrative": narrative,
            "user_status": user_status,
            "user_status_label": user_label,
            "data_source": {
                "basis": "실시간/연구 스냅샷",
                "last_collect": (
                    (minute_q or daily_q or {}).get("latest_date")
                    if (minute_q or daily_q)
                    else None
                ),
                "quality": (minute_q or daily_q or {}).get("status_label") or "—",
            },
            "charts": {
                "breadth": [
                    {
                        "name": "상승",
                        "value": round((up_ratio or 0.5) * 100, 1),
                    },
                    {
                        "name": "하락",
                        "value": round((1 - (up_ratio or 0.5)) * 100, 1),
                    },
                ]
            },
        }

    def _entry_environment_projection(
        self,
        kiwoom: dict[str, Any],
        upbit: dict[str, Any],
    ) -> dict[str, Any]:
        """자동매매 관점 설명용 — gate 아님."""

        scores = []
        for block in (kiwoom, upbit):
            tone = block.get("tone")
            if tone == "BULLISH":
                scores.append(2)
            elif tone == "MIXED":
                scores.append(1)
            else:
                scores.append(0)
            if block.get("volatility") == "높음":
                scores.append(0)
        avg = sum(scores) / max(len(scores), 1)
        if avg >= 1.5:
            level, label = "GOOD", "좋음"
        elif avg >= 0.8:
            level, label = "NEUTRAL", "보통"
        else:
            level, label = "CAUTION", "주의"
        return {
            "entry_environment": level,
            "entry_environment_label": label,
            "note": "설명용 projection — REAL trading gate 아님",
        }

    def _data_trust(self, quality: list[dict]) -> dict[str, Any]:
        by = {
            (q["exchange_code"], q["data_kind"]): q for q in quality
        }
        stale_daily = any(
            by.get(k, {}).get("status") in {"STALE", "BROKEN", "DEGRADED"}
            for k in (("UPBIT", "DAILY"), ("KRX", "DAILY"))
        )
        return {
            "realtime": {
                "UPBIT": by.get(("UPBIT", "MINUTE"), {}).get("status_label"),
                "KIWOOM": by.get(("KRX", "MINUTE"), {}).get("status_label")
                or "⚪ 미수집 정책",
            },
            "historical_daily": {
                "UPBIT": by.get(("UPBIT", "DAILY"), {}).get("status_label"),
                "KIWOOM": by.get(("KRX", "DAILY"), {}).get("status_label"),
            },
            "stale_warning": (
                "일봉 데이터 일부 보정 중" if stale_daily else None
            ),
        }

    def _autotrading_context(self) -> dict[str, Any]:
        # 요약만 — Process Map 중복 최소화 · READ ONLY
        upbit_ctx: dict[str, Any] = {"uba_id": 1380}
        kiwoom_ctx: dict[str, Any] = {"uba_id": 1381}
        try:
            from stock_platform.trading.upbit_funnel_observability import (
                build_upbit_funnel_snapshot,
            )

            snap = build_upbit_funnel_snapshot(
                self._session, user_broker_account_id=1380
            )
            stages = snap.get("stages") or {}
            raw_reason = snap.get("top_entry_block_reason") or snap.get(
                "first_zero_reason"
            )
            upbit_ctx.update(
                {
                    "candidates": stages.get("SELECTION"),
                    "waiting": stages.get("WAITING"),
                    "open": snap.get("open_positions"),
                    "first_zero": snap.get("first_zero_stage"),
                    "no_trade_reason_code": raw_reason,
                    "no_trade_reason": friendly_reason(
                        str(raw_reason) if raw_reason else None
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001 — summary soft-fail
            upbit_ctx["error"] = type(exc).__name__

        try:
            from stock_platform.trading.kiwoom_funnel_observability import (
                build_kiwoom_funnel_snapshot,
            )

            snap = build_kiwoom_funnel_snapshot(
                self._session, user_broker_account_id=1381
            )
            funnel = snap.get("funnel") or {}
            reasons = snap.get("FIRST_ZERO_REASONS") or []
            raw_reason = reasons[0] if reasons else None
            kiwoom_ctx.update(
                {
                    "universe": funnel.get("UNIVERSE") or funnel.get("universe"),
                    "scanner": funnel.get("SCANNER") or funnel.get("scanner"),
                    "candidates": funnel.get("CANDIDATE") or funnel.get("candidate"),
                    "signal": funnel.get("SIGNAL") or funnel.get("signal"),
                    "first_zero": snap.get("FIRST_ZERO_STAGE"),
                    "no_trade_reason_code": raw_reason,
                    "no_trade_reason": friendly_reason(
                        str(raw_reason) if raw_reason else None
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001 — summary soft-fail
            kiwoom_ctx["error"] = type(exc).__name__

        return {
            "UPBIT": upbit_ctx,
            "KIWOOM": kiwoom_ctx,
            "process_map_href": "/admin/autotrading/process",
        }

    def _krx_breadth(self) -> dict[str, Any]:
        row = self._session.execute(
            text(
                """
                SELECT
                  COUNT(*) FILTER (WHERE p.change_rate > 0) AS up_n,
                  COUNT(*) FILTER (WHERE p.change_rate < 0) AS down_n,
                  COUNT(*) FILTER (WHERE p.change_rate = 0 OR p.change_rate IS NULL) AS flat_n,
                  COUNT(*) AS total,
                  AVG(ABS(COALESCE(p.change_rate, 0))) AS avg_abs
                FROM market.price_daily p
                JOIN market.instrument i ON i.instrument_id = p.instrument_id
                WHERE i.exchange_code = 'KRX'
                  AND i.is_active = TRUE
                  AND p.trade_date = (
                    SELECT MAX(p2.trade_date) FROM market.price_daily p2
                    JOIN market.instrument i2 ON i2.instrument_id = p2.instrument_id
                    WHERE i2.exchange_code = 'KRX'
                  )
                """
            )
        ).mappings().first()
        if not row or not row["total"]:
            return {"up_ratio": None, "charts": []}
        total = int(row["total"])
        up_n = int(row["up_n"] or 0)
        down_n = int(row["down_n"] or 0)
        flat_n = int(row["flat_n"] or 0)
        avg_abs = float(row["avg_abs"] or 0)
        vol = "높음" if avg_abs >= 3 else ("낮음" if avg_abs < 1 else "보통")
        return {
            "up": up_n,
            "down": down_n,
            "flat": flat_n,
            "total": total,
            "up_ratio": round(up_n / total, 3),
            "volatility_hint": vol,
            "trade_mood": "보통",
            "charts": [
                {"name": "상승", "value": up_n},
                {"name": "하락", "value": down_n},
                {"name": "보합", "value": flat_n},
            ],
        }

    def _latest_feature(self, feature_key: str) -> dict[str, Any] | None:
        rows = self._ctx.list_market_feature(feature_key, limit=1)
        return rows[0] if rows else None

    def _btc_eth_direction(self) -> str:
        row = self._session.execute(
            text(
                """
                SELECT i.symbol, p.change_rate
                FROM market.price_daily p
                JOIN market.instrument i ON i.instrument_id = p.instrument_id
                WHERE i.exchange_code = 'UPBIT'
                  AND i.symbol IN ('KRW-BTC', 'KRW-ETH')
                  AND p.trade_date = (
                    SELECT MAX(p2.trade_date)
                    FROM market.price_daily p2
                    JOIN market.instrument i2 ON i2.instrument_id = p2.instrument_id
                    WHERE i2.symbol = i.symbol
                  )
                """
            )
        ).mappings().all()
        if not row:
            return "데이터 부족"
        ups = sum(1 for r in row if (r["change_rate"] or 0) > 0)
        if ups == len(row):
            return "BTC/ETH 상승"
        if ups == 0:
            return "BTC/ETH 하락"
        return "BTC/ETH 혼조"
