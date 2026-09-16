"""일자별 일봉 수집 현황 캘린더 (READ ONLY)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.operation.calendar_repository import TradingCalendarRepository
from stock_platform.operation.calendar_service import TradingCalendarService
from stock_platform.operation.job_repository import JobRunRepository

_KST = ZoneInfo("Asia/Seoul")

UPBIT_JOB = "upbit_krw_daily_sync"
KIWOOM_JOB = "kiwoom_krx_daily_sync"


@dataclass(slots=True)
class DailyCollectionRow:
    trade_date: str
    market: str
    expected_symbols: int
    collected_symbols: int
    missing_symbols: int
    collection_rate: float
    last_run_at: str | None
    status: str
    status_label: str
    is_trading_day: bool
    job_name: str | None


def _label(status: str) -> str:
    return {
        "HEALTHY": "🟢 정상",
        "PARTIAL": "🟡 일부 누락",
        "DELAYED": "🟠 지연",
        "FAILED": "🔴 수집 실패",
        "CLOSED": "⚪ 휴장/미수집 정책",
    }.get(status, status)


class DailyCollectionCalendarService:
    """날짜별 expected vs collected 집계."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._calendar = TradingCalendarService(TradingCalendarRepository(session))
        self._jobs = JobRunRepository(session)

    def list_days(
        self,
        *,
        market: str | None,
        start_date: date,
        end_date: date,
        status_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        markets = (
            ["UPBIT", "KRX"]
            if market in (None, "", "ALL", "전체")
            else [self._norm(market)]
        )
        rows: list[dict[str, Any]] = []
        for exchange in markets:
            rows.extend(
                self._rows_for_exchange(
                    exchange=exchange,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        if status_filter and status_filter not in ("ALL", "전체", ""):
            key = status_filter.upper()
            mapping = {
                "정상": "HEALTHY",
                "누락": "PARTIAL",
                "실패": "FAILED",
                "HEALTHY": "HEALTHY",
                "PARTIAL": "PARTIAL",
                "FAILED": "FAILED",
                "DELAYED": "DELAYED",
                "CLOSED": "CLOSED",
            }
            want = mapping.get(key, key)
            rows = [r for r in rows if r["status"] == want]
        rows.sort(key=lambda r: (r["trade_date"], r["market"]), reverse=True)
        return rows

    def missing_symbols(
        self,
        *,
        market: str,
        trade_date: date,
        limit: int = 100,
    ) -> dict[str, Any]:
        exchange = self._norm(market)
        if exchange == "KRX" and not self._calendar.is_trading_day("KRX", trade_date):
            return {
                "trade_date": trade_date.isoformat(),
                "market": exchange,
                "is_trading_day": False,
                "items": [],
                "total": 0,
                "message": "휴장일 — 누락으로 집계하지 않습니다.",
            }

        items = self._session.execute(
            text(
                """
                SELECT i.symbol, i.name
                FROM market.instrument i
                WHERE i.exchange_code = :ex
                  AND i.is_active = TRUE
                  AND NOT EXISTS (
                    SELECT 1 FROM market.price_daily p
                    WHERE p.instrument_id = i.instrument_id
                      AND p.trade_date = :d
                  )
                ORDER BY i.symbol
                LIMIT :lim
                """
            ),
            {"ex": exchange, "d": trade_date, "lim": limit},
        ).mappings().all()

        job_name = UPBIT_JOB if exchange == "UPBIT" else KIWOOM_JOB
        last = self._jobs.list_recent(job_name=job_name, limit=1)
        last_job = None
        if last:
            h = last[0]
            last_job = {
                "job_run_id": h.job_run_id,
                "status_code": h.status_code,
                "started_at": h.started_at.isoformat() if h.started_at else None,
                "error_message": h.error_message,
            }

        return {
            "trade_date": trade_date.isoformat(),
            "market": exchange,
            "is_trading_day": True,
            "items": [{"symbol": r["symbol"], "name": r["name"]} for r in items],
            "total": len(items),
            "last_job": last_job,
        }

    def _rows_for_exchange(
        self,
        *,
        exchange: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        expected = int(
            self._session.scalar(
                text(
                    """
                    SELECT COUNT(*) FROM market.instrument
                    WHERE exchange_code = :ex AND is_active = TRUE
                    """
                ),
                {"ex": exchange},
            )
            or 0
        )
        collected_map = {
            row["d"]: int(row["cnt"])
            for row in self._session.execute(
                text(
                    """
                    SELECT p.trade_date::date AS d, COUNT(DISTINCT p.instrument_id) AS cnt
                    FROM market.price_daily p
                    JOIN market.instrument i ON i.instrument_id = p.instrument_id
                    WHERE i.exchange_code = :ex
                      AND p.trade_date >= :s
                      AND p.trade_date <= :e
                    GROUP BY p.trade_date::date
                    """
                ),
                {"ex": exchange, "s": start_date, "e": end_date},
            ).mappings()
        }

        job_name = UPBIT_JOB if exchange == "UPBIT" else KIWOOM_JOB
        job_by_day = self._job_success_by_day(job_name, start_date, end_date)

        out: list[dict[str, Any]] = []
        probe = start_date
        today = datetime.now(_KST).date()
        while probe <= end_date:
            is_td = (
                True
                if exchange == "UPBIT"
                else self._calendar.is_trading_day("KRX", probe)
            )
            collected = collected_map.get(probe, 0)
            if not is_td:
                status = "CLOSED"
                missing = 0
                rate = 0.0
                exp = 0
            else:
                exp = expected
                missing = max(exp - collected, 0)
                rate = round((collected / exp) * 100, 1) if exp else 0.0
                lag_days = (today - probe).days
                if collected == 0 and lag_days >= 1:
                    # 실패 job이 있으면 FAILED, 없으면 DELAYED
                    failed = self._had_failure_on_day(job_name, probe)
                    status = "FAILED" if failed else "DELAYED"
                elif missing == 0:
                    status = "HEALTHY"
                elif rate >= 95:
                    status = "PARTIAL"
                elif rate >= 50:
                    status = "PARTIAL"
                else:
                    status = "DELAYED"

            display_market = "KIWOOM" if exchange == "KRX" else exchange
            row = DailyCollectionRow(
                trade_date=probe.isoformat(),
                market=display_market,
                expected_symbols=exp if is_td else 0,
                collected_symbols=collected if is_td else 0,
                missing_symbols=missing,
                collection_rate=rate if is_td else 0.0,
                last_run_at=job_by_day.get(probe),
                status=status,
                status_label=_label(status),
                is_trading_day=is_td,
                job_name=job_name if is_td else None,
            )
            out.append(asdict(row))
            probe += timedelta(days=1)
        return out

    def _job_success_by_day(
        self,
        job_name: str,
        start_date: date,
        end_date: date,
    ) -> dict[date, str]:
        start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=_KST)
        end_dt = datetime(
            end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=_KST
        )
        rows = self._session.execute(
            text(
                """
                SELECT started_at, status_code
                FROM operation.job_run_history
                WHERE job_name = :jn
                  AND started_at >= :s
                  AND started_at <= :e
                  AND status_code = 'SUCCESS'
                ORDER BY started_at DESC
                """
            ),
            {"jn": job_name, "s": start_dt.astimezone(timezone.utc), "e": end_dt.astimezone(timezone.utc)},
        ).mappings().all()
        by_day: dict[date, str] = {}
        for r in rows:
            started = r["started_at"]
            if started is None:
                continue
            local = started.astimezone(_KST) if started.tzinfo else started.replace(tzinfo=_KST)
            d = local.date()
            if d not in by_day:
                by_day[d] = local.strftime("%H:%M")
        return by_day

    def _had_failure_on_day(self, job_name: str, day: date) -> bool:
        start_dt = datetime(day.year, day.month, day.day, tzinfo=_KST)
        end_dt = start_dt + timedelta(days=1)
        row = self._session.execute(
            text(
                """
                SELECT 1 FROM operation.job_run_history
                WHERE job_name = :jn
                  AND status_code = 'FAILED'
                  AND started_at >= :s AND started_at < :e
                LIMIT 1
                """
            ),
            {
                "jn": job_name,
                "s": start_dt.astimezone(timezone.utc),
                "e": end_dt.astimezone(timezone.utc),
            },
        ).first()
        return row is not None

    @staticmethod
    def _norm(market: str) -> str:
        raw = market.strip().upper()
        if raw in {"KIWOOM", "KRX", "STOCK"}:
            return "KRX"
        return "UPBIT" if raw in {"UPBIT", "CRYPTO"} else raw
