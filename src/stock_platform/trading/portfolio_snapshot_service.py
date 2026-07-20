"""포트폴리오 스냅샷·이력·요약 서비스 — STEP66."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.markets.repository import PriceDailyRepository
from stock_platform.markets.service import (
    InstrumentNotFoundError,
    PriceDailyService,
)
from stock_platform.trading.account_models import (
    PaperAccount,
    PaperPosition,
)
from stock_platform.trading.portfolio_snapshot_models import (
    PortfolioSnapshot,
)
from stock_platform.trading.portfolio_snapshot_repository import (
    PortfolioSnapshotRepository,
)


ZERO = Decimal("0")
PeriodCode = Literal["7d", "30d", "90d", "1y", "all"]


def compute_max_drawdown(equities: list[Decimal]) -> Decimal:
    """기간 내 Maximum Drawdown (비율, 0~1)."""

    if not equities:
        return ZERO
    peak = equities[0]
    max_dd = ZERO
    for equity in equities:
        if equity > peak:
            peak = equity
        if peak > ZERO:
            drawdown = (peak - equity) / peak
            if drawdown > max_dd:
                max_dd = drawdown
    return max_dd.quantize(Decimal("0.000001"))


def compute_period_return(
    first: Decimal | None,
    last: Decimal | None,
) -> Decimal:
    """기간 수익률 (%)."""

    if first is None or last is None or first <= ZERO:
        return ZERO
    return ((last - first) / first * Decimal("100")).quantize(
        Decimal("0.0001")
    )


def resolve_period_range(
    period: str | None,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    today: date | None = None,
) -> tuple[date | None, date | None]:
    """period / from / to → (from, to)."""

    end = date_to or today or date.today()
    if date_from is not None:
        return date_from, end

    code = (period or "30d").strip().lower()
    if code in {"all", "전체"}:
        return None, end
    mapping = {
        "7d": 7,
        "30d": 30,
        "90d": 90,
        "1y": 365,
        "week": 7,
        "month": 30,
        "year": 365,
    }
    days = mapping.get(code, 30)
    return end - timedelta(days=days - 1), end


class PortfolioSnapshotService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = PortfolioSnapshotRepository(session)
        self._prices = PriceDailyService(
            PriceDailyRepository(session)
        )

    def capture_account(
        self,
        *,
        account_id: int,
        snapshot_date: date | None = None,
        mode_code: str = "PAPER",
        force_user_id: int | None = None,
    ) -> PortfolioSnapshot:
        """단일 계좌 스냅샷 upsert (account+date 중복 방지)."""

        account = self._session.get(PaperAccount, account_id)
        if account is None:
            raise LookupError(f"Paper account not found: {account_id}")
        user_id = force_user_id or account.user_id
        if user_id is None:
            raise ValueError(
                f"Paper account {account_id} has no user_id"
            )

        as_of = snapshot_date or date.today()
        valuation = self._value_account(account)
        previous = self._previous_snapshot(
            account_id, as_of, mode_code=mode_code
        )
        daily_profit = (
            valuation["total_asset"] - previous
            if previous is not None
            else ZERO
        ).quantize(Decimal("0.01"))
        if previous is not None and previous > ZERO:
            daily_rate = (
                daily_profit / previous * Decimal("100")
            ).quantize(Decimal("0.0001"))
        else:
            daily_rate = ZERO

        initial = Decimal(account.initial_cash)
        if initial > ZERO:
            total_return = (
                (valuation["total_asset"] - initial)
                / initial
                * Decimal("100")
            ).quantize(Decimal("0.0001"))
        else:
            total_return = ZERO

        row = PortfolioSnapshot(
            user_id=int(user_id),
            account_id=int(account_id),
            snapshot_date=as_of,
            snapshot_time=datetime.now(timezone.utc),
            cash=valuation["cash"],
            market_value=valuation["market_value"],
            total_asset=valuation["total_asset"],
            invested_amount=valuation["invested_amount"],
            realized_profit=valuation["realized_profit"],
            unrealized_profit=valuation["unrealized_profit"],
            daily_profit=daily_profit,
            daily_profit_rate=daily_rate,
            total_return_rate=total_return,
            position_count=valuation["position_count"],
            mode_code=(mode_code or "PAPER").upper(),
            valuation_mode=valuation["valuation_mode"],
        )
        return self._repo.upsert(row)

    def capture_all_active(
        self,
        *,
        snapshot_date: date | None = None,
        mode_code: str = "PAPER",
    ) -> dict[str, Any]:
        """활성·소유자 있는 Paper 계좌 전부 스냅샷 (스케줄러용)."""

        as_of = snapshot_date or date.today()
        accounts = list(
            self._session.scalars(
                select(PaperAccount).where(
                    PaperAccount.user_id.is_not(None),
                    PaperAccount.is_active.is_(True),
                )
            )
        )
        created = 0
        updated = 0
        errors: list[dict[str, Any]] = []
        for account in accounts:
            try:
                before = self._repo.get_by_account_date(
                    account_id=int(account.account_id),
                    snapshot_date=as_of,
                    mode_code=mode_code,
                )
                self.capture_account(
                    account_id=int(account.account_id),
                    snapshot_date=as_of,
                    mode_code=mode_code,
                )
                if before is None:
                    created += 1
                else:
                    updated += 1
            except Exception as exc:  # noqa: BLE001 — 배치 계속
                errors.append(
                    {
                        "account_id": int(account.account_id),
                        "error": str(exc),
                    }
                )
        return {
            "snapshot_date": as_of.isoformat(),
            "mode_code": mode_code.upper(),
            "account_count": len(accounts),
            "created": created,
            "updated": updated,
            "error_count": len(errors),
            "errors": errors[:20],
        }

    def history(
        self,
        *,
        user_id: int,
        account_id: int,
        period: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, Any]:
        start, end = resolve_period_range(
            period, date_from=date_from, date_to=date_to
        )
        rows = self._repo.list_history(
            user_id=user_id,
            account_id=account_id,
            date_from=start,
            date_to=end,
            mode_code="PAPER",
        )
        items = [self._row_dict(row) for row in rows]
        return {
            "account_id": account_id,
            "period": period or "custom",
            "from": start.isoformat() if start else None,
            "to": end.isoformat() if end else None,
            "items": items,
            "total": len(items),
        }

    def summary(
        self,
        *,
        user_id: int,
        account_id: int,
        period: str | None = "30d",
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, Any]:
        start, end = resolve_period_range(
            period, date_from=date_from, date_to=date_to
        )
        rows = self._repo.list_history(
            user_id=user_id,
            account_id=account_id,
            date_from=start,
            date_to=end,
            mode_code="PAPER",
        )
        equities = [Decimal(row.total_asset) for row in rows]
        mdd = compute_max_drawdown(equities)
        peak = max(equities) if equities else ZERO
        trough = min(equities) if equities else ZERO
        first = equities[0] if equities else None
        last = equities[-1] if equities else None
        period_return = compute_period_return(first, last)

        # 현재 평가 (스냅샷과 별도 실시간)
        account = self._session.get(PaperAccount, account_id)
        current = (
            self._value_account(account)
            if account is not None
            else None
        )
        today_row = self._repo.get_by_account_date(
            account_id=account_id,
            snapshot_date=date.today(),
            mode_code="PAPER",
        )
        today_profit = (
            Decimal(today_row.daily_profit)
            if today_row is not None
            else (current["daily_proxy"] if current else ZERO)
        )
        cumulative = ZERO
        if current is not None and account is not None:
            initial = Decimal(account.initial_cash)
            cumulative = (
                current["total_asset"] - initial
            ).quantize(Decimal("0.01"))

        # 주간/월간 구간 수익률 (history 기반)
        weekly = self._segment_return(rows, days=7)
        monthly = self._segment_return(rows, days=30)

        return {
            "account_id": account_id,
            "period": period or "custom",
            "from": start.isoformat() if start else None,
            "to": end.isoformat() if end else None,
            "current_total_asset": (
                str(current["total_asset"]) if current else None
            ),
            "current_cash": (
                str(current["cash"]) if current else None
            ),
            "current_market_value": (
                str(current["market_value"]) if current else None
            ),
            "today_profit": str(today_profit),
            "cumulative_profit": str(cumulative),
            "peak_asset": str(peak.quantize(Decimal("0.01"))),
            "trough_asset": str(trough.quantize(Decimal("0.01"))),
            "max_drawdown": str(mdd),
            "max_drawdown_pct": str(
                (mdd * Decimal("100")).quantize(Decimal("0.0001"))
            ),
            "period_return_rate": str(period_return),
            "daily_return_rate": (
                str(rows[-1].daily_profit_rate) if rows else "0"
            ),
            "weekly_return_rate": str(weekly),
            "monthly_return_rate": str(monthly),
            "total_return_rate": (
                str(current["total_return_rate"])
                if current
                else "0"
            ),
            "realized_profit": (
                str(current["realized_profit"]) if current else None
            ),
            "unrealized_profit": (
                str(current["unrealized_profit"]) if current else None
            ),
            "position_count": (
                current["position_count"] if current else 0
            ),
            "snapshot_count": len(rows),
            "valuation_mode": (
                current["valuation_mode"] if current else None
            ),
        }

    def _segment_return(
        self,
        rows: list[PortfolioSnapshot],
        *,
        days: int,
    ) -> Decimal:
        if not rows:
            return ZERO
        end_date = rows[-1].snapshot_date
        start_date = end_date - timedelta(days=days - 1)
        segment = [
            row
            for row in rows
            if row.snapshot_date >= start_date
        ]
        if not segment:
            return ZERO
        return compute_period_return(
            Decimal(segment[0].total_asset),
            Decimal(segment[-1].total_asset),
        )

    def _previous_snapshot(
        self,
        account_id: int,
        as_of: date,
        *,
        mode_code: str = "PAPER",
    ) -> Decimal | None:
        stmt = (
            select(PortfolioSnapshot)
            .where(
                PortfolioSnapshot.account_id == account_id,
                PortfolioSnapshot.snapshot_date < as_of,
                PortfolioSnapshot.mode_code == mode_code.upper(),
            )
            .order_by(PortfolioSnapshot.snapshot_date.desc())
            .limit(1)
        )
        prev = self._session.scalar(stmt)
        if prev is None:
            return None
        return Decimal(prev.total_asset)

    def _value_account(
        self,
        account: PaperAccount,
    ) -> dict[str, Any]:
        positions = list(
            self._session.scalars(
                select(PaperPosition).where(
                    PaperPosition.account_id == account.account_id,
                    PaperPosition.quantity > 0,
                )
            )
        )
        valuation_mode = "mark_to_market"
        market_value = ZERO
        unrealized = ZERO
        invested = ZERO
        missing = 0
        for position in positions:
            cost = (
                Decimal(position.quantity)
                * Decimal(position.average_entry_price)
            ).quantize(Decimal("0.01"))
            invested += cost
            price = self._latest_close(
                exchange_code=position.exchange_code,
                symbol=position.symbol,
            )
            if price is None:
                missing += 1
                market_value += cost
                continue
            mv = (
                Decimal(position.quantity) * price
            ).quantize(Decimal("0.01"))
            market_value += mv
            unrealized += (mv - cost).quantize(Decimal("0.01"))

        if positions and missing == len(positions):
            valuation_mode = "cost_basis"
            unrealized = ZERO
        elif missing:
            valuation_mode = "partial_mark_to_market"

        cash = Decimal(account.available_cash)
        total = (cash + market_value).quantize(Decimal("0.01"))
        initial = Decimal(account.initial_cash)
        total_return = ZERO
        if initial > ZERO:
            total_return = (
                (total - initial) / initial * Decimal("100")
            ).quantize(Decimal("0.0001"))

        # 오늘 스냅샷 없을 때 summary용 근사 일손익
        prev = self._previous_snapshot(
            int(account.account_id), date.today()
        )
        daily_proxy = (
            (total - prev).quantize(Decimal("0.01"))
            if prev is not None
            else ZERO
        )

        return {
            "cash": cash.quantize(Decimal("0.01")),
            "market_value": market_value.quantize(Decimal("0.01")),
            "total_asset": total,
            "invested_amount": invested.quantize(Decimal("0.01")),
            "realized_profit": Decimal(
                account.realized_profit_loss
            ).quantize(Decimal("0.01")),
            "unrealized_profit": unrealized.quantize(
                Decimal("0.01")
            ),
            "position_count": len(positions),
            "valuation_mode": valuation_mode,
            "total_return_rate": total_return,
            "daily_proxy": daily_proxy,
        }

    def _latest_close(
        self,
        *,
        exchange_code: str,
        symbol: str,
    ) -> Decimal | None:
        try:
            row = self._prices.get_latest(exchange_code, symbol)
        except InstrumentNotFoundError:
            return None
        except Exception:  # noqa: BLE001
            return None
        if row is None:
            return None
        close = getattr(row, "close_price", None)
        if close is None:
            return None
        return Decimal(str(close))

    @staticmethod
    def _row_dict(row: PortfolioSnapshot) -> dict[str, Any]:
        return {
            "snapshot_id": row.snapshot_id,
            "account_id": row.account_id,
            "snapshot_date": row.snapshot_date.isoformat(),
            "snapshot_time": (
                row.snapshot_time.isoformat()
                if row.snapshot_time
                else None
            ),
            "cash": str(row.cash),
            "market_value": str(row.market_value),
            "total_asset": str(row.total_asset),
            "invested_amount": str(row.invested_amount),
            "realized_profit": str(row.realized_profit),
            "unrealized_profit": str(row.unrealized_profit),
            "daily_profit": str(row.daily_profit),
            "daily_profit_rate": str(row.daily_profit_rate),
            "total_return_rate": str(row.total_return_rate),
            "position_count": row.position_count,
            "mode_code": row.mode_code,
            "valuation_mode": row.valuation_mode,
        }
