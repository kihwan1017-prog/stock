"""CLI: Sync KRX trading calendar into DB.

Usage:
  python -m stock_platform.operation.sync_krx_calendar_cli
  python -m stock_platform.operation.sync_krx_calendar_cli --no-verify
"""

from __future__ import annotations

import argparse
from datetime import date

from stock_platform.database.session import get_session_factory
from stock_platform.operation.calendar_sync_service import (
    TradingCalendarSyncService,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sync KRX trading calendar (curated holidays)"
    )
    parser.add_argument("--from-date", type=date.fromisoformat, default=None)
    parser.add_argument("--to-date", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Leave rows as UNVERIFIED",
    )
    parser.add_argument("--past-years", type=int, default=1)
    args = parser.parse_args(argv)

    session = get_session_factory()()
    try:
        result = TradingCalendarSyncService(session).sync_krx(
            from_date=args.from_date,
            to_date=args.to_date,
            trigger_type="CLI",
            requested_by="cli:sync_krx_calendar",
            mark_verified=not args.no_verify,
            past_years=args.past_years,
        )
        print(result)
        coverage = TradingCalendarSyncService(session).check_coverage()
        print(coverage)
        return 0 if result.get("status") == "SUCCESS" else 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
