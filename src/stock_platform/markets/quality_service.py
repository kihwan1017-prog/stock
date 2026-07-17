from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.markets.models import Instrument, PriceDaily
from stock_platform.markets.repository import (
    InstrumentRepository,
    PriceDailyRepository,
)


@dataclass(frozen=True, slots=True)
class QualityIssue:
    exchange_code: str
    symbol: str
    issue_type: str
    severity: str
    message: str
    trade_date: date | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class QualityReport:
    checked_at: datetime
    exchange_code: str | None
    instrument_count: int
    issue_count: int
    issues: list[QualityIssue]
    latest_by_exchange: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at.isoformat(),
            "exchange_code": self.exchange_code,
            "instrument_count": self.instrument_count,
            "issue_count": self.issue_count,
            "issues": [asdict(item) for item in self.issues],
            "latest_by_exchange": self.latest_by_exchange,
        }


class MarketDataQualityService:
    """일봉/분봉 데이터 품질 검증 및 최신 수집 시각 요약."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._instruments = InstrumentRepository(session)
        self._prices = PriceDailyRepository(session)

    def run(
        self,
        *,
        exchange_code: str | None = None,
        lookback_days: int = 90,
        max_gap_days: int | None = None,
        symbol_limit: int = 500,
    ) -> QualityReport:
        if lookback_days <= 0:
            raise ValueError("lookback_days must be > 0")

        instruments = self._instruments.list(
            exchange_code=exchange_code,
            active_only=True,
            limit=symbol_limit,
        )

        end_date = date.today()
        start_date = end_date - timedelta(days=lookback_days)
        # 암호화폐는 주말 포함, 주식은 평일 위주 → 기본 gap은 거래소별
        issues: list[QualityIssue] = []

        for instrument in instruments:
            rows = self._prices.find_between(
                instrument.instrument_id,
                start_date,
                end_date,
            )
            issues.extend(
                self._check_price_rows(
                    instrument,
                    rows,
                    default_max_gap_days=(
                        max_gap_days
                        if max_gap_days is not None
                        else (
                            3
                            if instrument.exchange_code == "UPBIT"
                            else 5
                        )
                    ),
                )
            )

        issues.extend(self._check_duplicates(exchange_code))

        return QualityReport(
            checked_at=datetime.now(timezone.utc),
            exchange_code=exchange_code,
            instrument_count=len(instruments),
            issue_count=len(issues),
            issues=issues,
            latest_by_exchange=self.latest_collection_dashboard(),
        )

    def latest_collection_dashboard(self) -> list[dict[str, Any]]:
        """시장별 최신 수집 시각 요약."""

        daily_rows = self._session.execute(
            text(
                """
                SELECT
                    i.exchange_code,
                    MAX(p.trade_date) AS latest_trade_date,
                    MAX(p.updated_at) AS latest_daily_updated_at,
                    COUNT(*) AS daily_row_count
                FROM market.price_daily p
                JOIN market.instrument i
                  ON i.instrument_id = p.instrument_id
                GROUP BY i.exchange_code
                ORDER BY i.exchange_code
                """
            )
        ).mappings().all()

        minute_rows = self._session.execute(
            text(
                """
                SELECT
                    i.exchange_code,
                    MAX(c.candle_at) AS latest_candle_at,
                    COUNT(*) AS minute_row_count
                FROM market.candle_minute c
                JOIN market.instrument i
                  ON i.instrument_id = c.instrument_id
                GROUP BY i.exchange_code
                ORDER BY i.exchange_code
                """
            )
        ).mappings().all()

        quote_rows = self._session.execute(
            text(
                """
                SELECT
                    i.exchange_code,
                    MAX(q.quoted_at) AS latest_quoted_at,
                    COUNT(*) AS quote_row_count
                FROM market.quote_snapshot q
                JOIN market.instrument i
                  ON i.instrument_id = q.instrument_id
                GROUP BY i.exchange_code
                ORDER BY i.exchange_code
                """
            )
        ).mappings().all()

        minute_by_ex = {
            row["exchange_code"]: row for row in minute_rows
        }
        quote_by_ex = {
            row["exchange_code"]: row for row in quote_rows
        }

        result: list[dict[str, Any]] = []
        exchanges = {
            row["exchange_code"] for row in daily_rows
        } | set(minute_by_ex) | set(quote_by_ex)

        for exchange in sorted(exchanges):
            daily = next(
                (
                    row
                    for row in daily_rows
                    if row["exchange_code"] == exchange
                ),
                None,
            )
            minute = minute_by_ex.get(exchange)
            quote = quote_by_ex.get(exchange)
            result.append(
                {
                    "exchange_code": exchange,
                    "latest_trade_date": (
                        daily["latest_trade_date"].isoformat()
                        if daily and daily["latest_trade_date"]
                        else None
                    ),
                    "latest_daily_updated_at": (
                        daily["latest_daily_updated_at"].isoformat()
                        if daily and daily["latest_daily_updated_at"]
                        else None
                    ),
                    "daily_row_count": (
                        int(daily["daily_row_count"]) if daily else 0
                    ),
                    "latest_candle_at": (
                        minute["latest_candle_at"].isoformat()
                        if minute and minute["latest_candle_at"]
                        else None
                    ),
                    "minute_row_count": (
                        int(minute["minute_row_count"])
                        if minute
                        else 0
                    ),
                    "latest_quoted_at": (
                        quote["latest_quoted_at"].isoformat()
                        if quote and quote["latest_quoted_at"]
                        else None
                    ),
                    "quote_row_count": (
                        int(quote["quote_row_count"])
                        if quote
                        else 0
                    ),
                }
            )

        return result

    def _check_price_rows(
        self,
        instrument: Instrument,
        rows: list[PriceDaily],
        *,
        default_max_gap_days: int,
    ) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        previous: PriceDaily | None = None

        for row in rows:
            # 음수 가격·거래량
            for field_name, value in (
                ("open_price", row.open_price),
                ("high_price", row.high_price),
                ("low_price", row.low_price),
                ("close_price", row.close_price),
                ("volume", row.volume),
                ("trade_value", row.trade_value),
            ):
                if value is not None and Decimal(value) < 0:
                    issues.append(
                        QualityIssue(
                            exchange_code=instrument.exchange_code,
                            symbol=instrument.symbol,
                            issue_type="NEGATIVE_VALUE",
                            severity="ERROR",
                            message=f"{field_name} is negative",
                            trade_date=row.trade_date,
                            details={"field": field_name, "value": str(value)},
                        )
                    )

            # OHLC 논리
            if row.high_price < row.low_price:
                issues.append(
                    QualityIssue(
                        exchange_code=instrument.exchange_code,
                        symbol=instrument.symbol,
                        issue_type="OHLC_LOGIC",
                        severity="ERROR",
                        message="high_price < low_price",
                        trade_date=row.trade_date,
                    )
                )

            if not (
                row.low_price
                <= row.open_price
                <= row.high_price
            ) or not (
                row.low_price
                <= row.close_price
                <= row.high_price
            ):
                issues.append(
                    QualityIssue(
                        exchange_code=instrument.exchange_code,
                        symbol=instrument.symbol,
                        issue_type="OHLC_LOGIC",
                        severity="WARNING",
                        message="open/close outside high-low range",
                        trade_date=row.trade_date,
                    )
                )

            if previous is not None:
                gap = (row.trade_date - previous.trade_date).days
                if gap > default_max_gap_days:
                    issues.append(
                        QualityIssue(
                            exchange_code=instrument.exchange_code,
                            symbol=instrument.symbol,
                            issue_type="MISSING_DAYS",
                            severity="WARNING",
                            message=(
                                f"gap of {gap} days between "
                                f"{previous.trade_date} and {row.trade_date}"
                            ),
                            trade_date=row.trade_date,
                            details={
                                "previous_date": previous.trade_date.isoformat(),
                                "gap_days": gap,
                            },
                        )
                    )

            previous = row

        return issues

    def _check_duplicates(
        self,
        exchange_code: str | None,
    ) -> list[QualityIssue]:
        # PK로 막히지만 방어적 탐지(조인 후 그룹)
        params: dict[str, Any] = {}
        exchange_filter = ""
        if exchange_code:
            exchange_filter = "AND i.exchange_code = :exchange_code"
            params["exchange_code"] = exchange_code.upper()

        rows = self._session.execute(
            text(
                f"""
                SELECT
                    i.exchange_code,
                    i.symbol,
                    p.trade_date,
                    COUNT(*) AS cnt
                FROM market.price_daily p
                JOIN market.instrument i
                  ON i.instrument_id = p.instrument_id
                WHERE 1=1
                {exchange_filter}
                GROUP BY i.exchange_code, i.symbol, p.trade_date
                HAVING COUNT(*) > 1
                LIMIT 100
                """
            ),
            params,
        ).mappings().all()

        return [
            QualityIssue(
                exchange_code=row["exchange_code"],
                symbol=row["symbol"],
                issue_type="DUPLICATE_CANDLE",
                severity="ERROR",
                message="duplicate daily candle detected",
                trade_date=row["trade_date"],
                details={"count": int(row["cnt"])},
            )
            for row in rows
        ]
