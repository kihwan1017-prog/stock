from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from stock_platform.markets.models import Instrument, PriceDaily
from stock_platform.markets.repository import InstrumentRepository
from stock_platform.operation.calendar_repository import TradingCalendarRepository
from stock_platform.operation.calendar_service import TradingCalendarService
from stock_platform.operation.job_models import JobRunHistory
from stock_platform.operation.job_repository import JobRunRepository

_KST = ZoneInfo("Asia/Seoul")

UPBIT_DAILY_JOB_NAME = "upbit_krw_daily_sync"
KIWOOM_DAILY_JOB_NAME = "kiwoom_krx_daily_sync"

QUALITY_HEALTHY = "HEALTHY"
QUALITY_DEGRADED = "DEGRADED"
QUALITY_STALE = "STALE"
QUALITY_BROKEN = "BROKEN"
QUALITY_NOT_COLLECTED = "NOT_COLLECTED"


@dataclass(frozen=True, slots=True)
class MarketDataRootCause:
    exchange_code: str
    first_failure_stage: str
    first_failure_at: str | None
    root_cause: str
    classification: str
    collector_implemented: bool
    scheduler_registered: bool
    scheduler_running: bool
    last_success: str | None
    last_failure: str | None
    failure_reason: str | None
    expected_interval: str
    actual_last_data_at: str | None


@dataclass(slots=True)
class DataKindQuality:
    exchange_code: str
    data_kind: str
    status: str
    status_label: str
    latest_date: str | None
    expected_latest_date: str | None
    lag_days: int | None
    symbol_count: int
    fresh_symbol_count: int
    stale_symbol_count: int
    missing_date_count: int
    duplicate_count: int
    invalid_ohlc_count: int
    last_collect_success: str | None
    collection_policy: str


@dataclass(slots=True)
class CollectionJobHeartbeat:
    job_name: str
    collector: str
    scheduler_registered: bool
    scheduler_running: bool
    last_started_at: str | None
    last_completed_at: str | None
    last_success_at: str | None
    last_failure_at: str | None
    rows_inserted: int | None
    rows_updated: int | None
    symbols_processed: int | None
    duration_ms: int | None
    next_run_hint: str | None
    status: str


@dataclass(slots=True)
class IntradayPolicyReport:
    current: str
    recommended: str
    estimated_storage: dict[str, Any]
    options: list[dict[str, Any]]


def today_kst() -> date:
    return datetime.now(_KST).date()


def _status_label(status: str) -> str:
    return {
        QUALITY_HEALTHY: "🟢 정상",
        QUALITY_DEGRADED: "🟡 일부 지연",
        QUALITY_STALE: "🟠 오래됨",
        QUALITY_BROKEN: "🔴 수집 장애",
        QUALITY_NOT_COLLECTED: "⚪ 미수집 정책",
    }.get(status, status)


def _classify_daily_quality(
    *,
    lag_days: int | None,
    stale_ratio: float,
    scheduler_running: bool,
    has_recent_failure: bool,
) -> str:
    if lag_days is None:
        return QUALITY_BROKEN
    if lag_days <= 1 and stale_ratio < 0.05:
        return QUALITY_HEALTHY
    if lag_days <= 3 and stale_ratio < 0.25:
        return QUALITY_DEGRADED
    if lag_days <= 7:
        return QUALITY_STALE
    if not scheduler_running or has_recent_failure:
        return QUALITY_BROKEN
    return QUALITY_STALE


class MarketDataCollectionStatusService:
    """시장별 수집 상태·품질·root cause 요약."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._instruments = InstrumentRepository(session)
        self._jobs = JobRunRepository(session)
        self._calendar = TradingCalendarService(TradingCalendarRepository(session))

    def root_cause_report(self) -> dict[str, MarketDataRootCause]:
        return {
            "UPBIT": self._root_cause_upbit(),
            "KRX": self._root_cause_kiwoom(),
        }

    def _root_cause_upbit(self) -> MarketDataRootCause:
        last_success = self._last_job_run(UPBIT_DAILY_JOB_NAME, "SUCCESS")
        last_failure = self._last_job_run(UPBIT_DAILY_JOB_NAME, "FAILED")
        latest_daily = self._exchange_latest_daily("UPBIT")
        running = self._scheduler_has_recent_execution(UPBIT_DAILY_JOB_NAME)
        return MarketDataRootCause(
            exchange_code="UPBIT",
            first_failure_stage=(
                "SCHEDULER_NOT_IN_AUTOMATIC_CRON"
                if not running
                else "COLLECTOR_EXECUTION"
            ),
            first_failure_at=(
                (last_failure.started_at.isoformat() if last_failure.started_at else None)
                if last_failure
                else "2026-08-02T00:00:00+09:00"
            ),
            root_cause=(
                "upbit_krw_daily_sync는 JobRegistry에만 등록되어 있고 "
                "AutomaticScheduler cron에 없음. 2026-08-01 이후 batch 실행 없음. "
                "자동매매 관심 ~11종목만 per-symbol resume 동기화(2026-08-18), "
                "나머지 ~269종목은 2026-07-31에서 정지."
            ),
            classification="SCHEDULER_GAP + PARTIAL_MANUAL_SYMBOL_SYNC",
            collector_implemented=True,
            scheduler_registered=True,
            scheduler_running=running,
            last_success=(
                last_success.started_at.isoformat()
                if last_success and last_success.started_at
                else None
            ),
            last_failure=(
                last_failure.started_at.isoformat()
                if last_failure and last_failure.started_at
                else None
            ),
            failure_reason=last_failure.error_message if last_failure else None,
            expected_interval="1d (02:10 KST)",
            actual_last_data_at=(
                latest_daily.isoformat() if latest_daily else None
            ),
        )

    def _root_cause_kiwoom(self) -> MarketDataRootCause:
        last_success = self._last_job_run(KIWOOM_DAILY_JOB_NAME, "SUCCESS")
        latest_daily = self._exchange_latest_daily("KRX")
        return MarketDataRootCause(
            exchange_code="KRX",
            first_failure_stage="SCHEDULER_NOT_REGISTERED",
            first_failure_at="2026-08-19T00:00:00+09:00",
            root_cause=(
                "KiwoomDailyBatchSyncService가 수동 API만 있었고 scheduler 미등록이었음. "
                "이번 STEP에서 JobRegistry + AutomaticScheduler cron 등록. "
                "2026-08-18 이후 자동 batch 없어 STALE."
            ),
            classification="NO_SCHEDULER + MANUAL_BATCH_ONLY (FIXED_IN_THIS_STEP)",
            collector_implemented=True,
            scheduler_registered=True,
            scheduler_running=False,
            last_success=(
                last_success.started_at.isoformat()
                if last_success and last_success.started_at
                else None
            ),
            last_failure=None,
            failure_reason=None,
            expected_interval="1 trading day (18:30 KST)",
            actual_last_data_at=(
                latest_daily.isoformat() if latest_daily else None
            ),
        )

    def collection_status(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for exchange, job_name, collector, cron_hint in (
            ("UPBIT", UPBIT_DAILY_JOB_NAME, "UpbitKrwDailyBatchSyncService", "02:10 KST daily"),
            ("KRX", KIWOOM_DAILY_JOB_NAME, "KiwoomDailyBatchSyncService", "18:30 KST weekdays"),
        ):
            hb = self._job_heartbeat(job_name, collector, cron_hint)
            for kind in ("DAILY", "MINUTE", "TICK"):
                row = asdict(hb)
                row.update(
                    {
                        "market": exchange,
                        "data_kind": kind,
                        "collector": collector if kind == "DAILY" else None,
                        "scheduler": job_name if kind == "DAILY" else None,
                    }
                )
                items.append(row)
        return items

    def quality_dashboard(self) -> list[DataKindQuality]:
        today = today_kst()
        expected_krx = self._expected_latest_krx(today)
        result: list[DataKindQuality] = []
        for exchange in ("UPBIT", "KRX"):
            expected = today if exchange == "UPBIT" else expected_krx
            result.append(self._daily_quality(exchange, expected))
            result.extend(self._intraday_quality(exchange))
        return result

    def intraday_policy(self) -> IntradayPolicyReport:
        krx_active = len(
            self._instruments.list(exchange_code="KRX", active_only=True, limit=50_000)
        )
        symbols = max(krx_active, 4243)
        minutes_per_day = 390
        ticks_per_symbol_day = 5000
        row_bytes = 120

        day_minute = symbols * minutes_per_day
        day_tick = symbols * ticks_per_symbol_day
        year_minute = day_minute * 252
        year_tick = day_tick * 252

        def mb(rows: int) -> float:
            return round(rows * row_bytes / (1024 * 1024), 1)

        options = [
            {
                "id": "A",
                "label": "전체 KRX tick 저장",
                "cons": f"~{mb(day_tick)}MB/일, ~{mb(year_tick)/1024:.1f}GB/년",
            },
            {
                "id": "B",
                "label": "전체 KRX minute 저장",
                "cons": f"~{mb(day_minute)}MB/일, ~{mb(year_minute)/1024:.1f}GB/년",
            },
            {"id": "C", "label": "trading universe만 minute/tick"},
            {"id": "D", "label": "후보/관심종목만 minute"},
            {"id": "E", "label": "실시간 memory + selected persistence"},
        ]
        return IntradayPolicyReport(
            current="KRX minute/tick=0 — historical intraday 미수집 정책",
            recommended="Option C + E: trading universe minute + realtime feed",
            estimated_storage={
                "krx_symbol_count": symbols,
                "minute_1d_rows": day_minute,
                "minute_1y_rows": year_minute,
                "minute_1y_gb": round(mb(year_minute) / 1024, 2),
                "tick_1d_rows": day_tick,
                "tick_1y_gb": round(mb(year_tick) / 1024, 2),
            },
            options=options,
        )

    def symbol_coverage(self, exchange_code: str, symbol: str) -> dict[str, Any]:
        instrument = self._instruments.find(exchange_code, symbol.upper())
        if instrument is None:
            raise LookupError(f"Instrument not found: {exchange_code}/{symbol}")

        daily_count = self._session.scalar(
            select(func.count())
            .select_from(PriceDaily)
            .where(PriceDaily.instrument_id == instrument.instrument_id)
        )
        minute_count = self._session.scalar(
            text("SELECT COUNT(*) FROM market.candle_minute WHERE instrument_id = :iid"),
            {"iid": instrument.instrument_id},
        )
        tick_count = self._session.scalar(
            text("SELECT COUNT(*) FROM market.trade_tick WHERE instrument_id = :iid"),
            {"iid": instrument.instrument_id},
        )
        bounds = self._session.execute(
            text(
                """
                SELECT MIN(trade_date) AS first_daily, MAX(trade_date) AS last_daily
                FROM market.price_daily WHERE instrument_id = :iid
                """
            ),
            {"iid": instrument.instrument_id},
        ).mappings().first()

        return {
            "market": instrument.exchange_code,
            "symbol": instrument.symbol,
            "name": instrument.name,
            "english_name": (instrument.extra_data or {}).get("english_name"),
            "active": instrument.is_active,
            "first_daily": (
                bounds["first_daily"].isoformat()
                if bounds and bounds["first_daily"]
                else None
            ),
            "last_daily": (
                bounds["last_daily"].isoformat()
                if bounds and bounds["last_daily"]
                else None
            ),
            "daily_count": int(daily_count or 0),
            "minute_count": int(minute_count or 0),
            "tick_count": int(tick_count or 0),
        }

    def _daily_quality(self, exchange_code: str, expected_latest: date) -> DataKindQuality:
        latest_date = self._exchange_latest_daily(exchange_code)
        lag_days = (
            (expected_latest - latest_date).days if latest_date is not None else None
        )

        per_symbol = self._session.execute(
            text(
                """
                SELECT MAX(p.trade_date) AS last_date
                FROM market.instrument i
                LEFT JOIN market.price_daily p
                  ON p.instrument_id = i.instrument_id
                WHERE i.exchange_code = :ex AND i.is_active = TRUE
                GROUP BY i.symbol
                """
            ),
            {"ex": exchange_code},
        ).mappings().all()

        symbol_count = len(per_symbol)
        stale = sum(
            1
            for row in per_symbol
            if row["last_date"] is None
            or row["last_date"] < expected_latest - timedelta(days=1)
        )
        fresh = symbol_count - stale
        stale_ratio = stale / symbol_count if symbol_count else 1.0

        job_name = (
            UPBIT_DAILY_JOB_NAME if exchange_code == "UPBIT" else KIWOOM_DAILY_JOB_NAME
        )
        last_success = self._last_job_run(job_name, "SUCCESS")
        running = self._scheduler_has_recent_execution(job_name)

        status = _classify_daily_quality(
            lag_days=lag_days,
            stale_ratio=stale_ratio,
            scheduler_running=running,
            has_recent_failure=False,
        )

        return DataKindQuality(
            exchange_code=exchange_code,
            data_kind="DAILY",
            status=status,
            status_label=_status_label(status),
            latest_date=latest_date.isoformat() if latest_date else None,
            expected_latest_date=expected_latest.isoformat(),
            lag_days=lag_days,
            symbol_count=symbol_count,
            fresh_symbol_count=fresh,
            stale_symbol_count=stale,
            missing_date_count=stale,
            duplicate_count=self._count_duplicates(exchange_code),
            invalid_ohlc_count=self._count_invalid_ohlc(exchange_code),
            last_collect_success=(
                last_success.started_at.isoformat()
                if last_success and last_success.started_at
                else None
            ),
            collection_policy="ACTIVE",
        )

    def _intraday_quality(self, exchange_code: str) -> list[DataKindQuality]:
        rows = self._session.execute(
            text(
                """
                SELECT 'MINUTE' AS kind, COUNT(*) AS cnt, MAX(c.candle_at) AS latest_at
                FROM market.candle_minute c
                JOIN market.instrument i ON i.instrument_id = c.instrument_id
                WHERE i.exchange_code = :ex
                UNION ALL
                SELECT 'TICK', COUNT(*), MAX(t.traded_at)
                FROM market.trade_tick t
                JOIN market.instrument i ON i.instrument_id = t.instrument_id
                WHERE i.exchange_code = :ex
                """
            ),
            {"ex": exchange_code},
        ).mappings().all()

        result: list[DataKindQuality] = []
        for row in rows:
            cnt = int(row["cnt"] or 0)
            if exchange_code == "KRX" and cnt == 0:
                status = QUALITY_NOT_COLLECTED
            elif cnt == 0:
                status = QUALITY_NOT_COLLECTED
            else:
                status = QUALITY_HEALTHY
            result.append(
                DataKindQuality(
                    exchange_code=exchange_code,
                    data_kind=str(row["kind"]),
                    status=status,
                    status_label=_status_label(status),
                    latest_date=(
                        row["latest_at"].date().isoformat()
                        if row["latest_at"]
                        else None
                    ),
                    expected_latest_date=today_kst().isoformat(),
                    lag_days=None,
                    symbol_count=0,
                    fresh_symbol_count=0,
                    stale_symbol_count=0,
                    missing_date_count=0,
                    duplicate_count=0,
                    invalid_ohlc_count=0,
                    last_collect_success=None,
                    collection_policy=(
                        "NOT_COLLECTED"
                        if exchange_code == "KRX" and cnt == 0
                        else "ACTIVE"
                    ),
                )
            )
        return result

    def _job_heartbeat(
        self,
        job_name: str,
        collector: str,
        cron_hint: str,
    ) -> CollectionJobHeartbeat:
        recent = self._jobs.list_recent(job_name=job_name, limit=5)
        last_any = recent[0] if recent else None
        last_success = next((r for r in recent if r.status_code == "SUCCESS"), None)
        last_failure = next((r for r in recent if r.status_code == "FAILED"), None)
        payload = (last_success.result_payload if last_success else {}) or {}
        running = self._scheduler_has_recent_execution(job_name)
        status = "HEALTHY" if running else "STALE"

        return CollectionJobHeartbeat(
            job_name=job_name,
            collector=collector,
            scheduler_registered=True,
            scheduler_running=running,
            last_started_at=(
                last_any.started_at.isoformat()
                if last_any and last_any.started_at
                else None
            ),
            last_completed_at=(
                last_any.finished_at.isoformat()
                if last_any and last_any.finished_at
                else None
            ),
            last_success_at=(
                last_success.started_at.isoformat()
                if last_success and last_success.started_at
                else None
            ),
            last_failure_at=(
                last_failure.started_at.isoformat()
                if last_failure and last_failure.started_at
                else None
            ),
            rows_inserted=payload.get("total_saved"),
            rows_updated=None,
            symbols_processed=(
                payload.get("market_count") or payload.get("completed_symbols")
            ),
            duration_ms=last_success.duration_ms if last_success else None,
            next_run_hint=cron_hint,
            status=status,
        )

    def _scheduler_has_recent_execution(self, job_name: str) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        recent = self._jobs.list_recent(job_name=job_name, limit=1)
        if not recent:
            return False
        row = recent[0]
        return bool(
            row.status_code == "SUCCESS"
            and row.started_at
            and row.started_at >= cutoff
        )

    def _last_job_run(
        self,
        job_name: str,
        status_code: str,
    ) -> JobRunHistory | None:
        rows = self._jobs.list_recent(
            job_name=job_name,
            status_code=status_code,
            limit=1,
        )
        return rows[0] if rows else None

    def _exchange_latest_daily(self, exchange_code: str) -> date | None:
        return self._session.scalar(
            select(func.max(PriceDaily.trade_date))
            .join(Instrument, Instrument.instrument_id == PriceDaily.instrument_id)
            .where(Instrument.exchange_code == exchange_code)
        )

    def _expected_latest_krx(self, today: date) -> date:
        probe = today
        for _ in range(14):
            if self._calendar.is_trading_day("KRX", probe):
                return probe
            probe -= timedelta(days=1)
        return today

    def _count_invalid_ohlc(self, exchange_code: str) -> int:
        row = self._session.execute(
            text(
                """
                SELECT COUNT(*) AS cnt
                FROM market.price_daily p
                JOIN market.instrument i ON i.instrument_id = p.instrument_id
                WHERE i.exchange_code = :ex
                  AND (
                    p.high_price < p.low_price
                    OR p.open_price < p.low_price OR p.open_price > p.high_price
                    OR p.close_price < p.low_price OR p.close_price > p.high_price
                    OR p.volume < 0
                  )
                """
            ),
            {"ex": exchange_code},
        ).mappings().first()
        return int(row["cnt"] or 0)

    def _count_duplicates(self, exchange_code: str) -> int:
        row = self._session.scalar(
            text(
                """
                SELECT COUNT(*) FROM (
                    SELECT p.instrument_id, p.trade_date
                    FROM market.price_daily p
                    JOIN market.instrument i ON i.instrument_id = p.instrument_id
                    WHERE i.exchange_code = :ex
                    GROUP BY p.instrument_id, p.trade_date
                    HAVING COUNT(*) > 1
                ) d
                """
            ),
            {"ex": exchange_code},
        )
        return int(row or 0)
