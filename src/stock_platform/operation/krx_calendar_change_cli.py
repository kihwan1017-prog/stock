"""STEP 8-5-11 — KRX Calendar Change CLI (DB 직접 수정 금지).

예:
  python -m stock_platform.operation.krx_calendar_change_cli pending
  python -m stock_platform.operation.krx_calendar_change_cli special
  python -m stock_platform.operation.krx_calendar_change_cli preview-import --file changes.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path


def _session():
    from stock_platform.database.session import get_session_factory

    return get_session_factory()()


def cmd_pending(_: argparse.Namespace) -> int:
    from stock_platform.operation.calendar_change_constants import (
        CalendarChangeStatus,
    )
    from stock_platform.operation.calendar_change_service import (
        TradingCalendarChangeService,
        request_as_dict,
    )

    session = _session()
    try:
        svc = TradingCalendarChangeService(session)
        rows = svc.list_requests(
            status=CalendarChangeStatus.PENDING_REVIEW.value
        )
        conflicts = svc.list_requests(
            status=CalendarChangeStatus.CONFLICT.value
        )
        print(
            json.dumps(
                {
                    "pending": [request_as_dict(r) for r in rows],
                    "conflicts": [request_as_dict(r) for r in conflicts],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        session.close()


def cmd_special(_: argparse.Namespace) -> int:
    from datetime import timedelta

    from stock_platform.operation.calendar_constants import (
        CalendarSessionType,
    )
    from stock_platform.operation.calendar_repository import (
        TradingCalendarRepository,
    )

    session = _session()
    try:
        repo = TradingCalendarRepository(session)
        today = date.today()
        rows = repo.list_between(
            exchange_code="KRX",
            start_date=today,
            end_date=today + timedelta(days=60),
        )
        special = [
            {
                "calendar_date": r.calendar_date.isoformat(),
                "session_type": r.session_type,
                "is_trading_day": r.is_trading_day,
                "regular_open_at": (
                    r.regular_open_at.isoformat()
                    if r.regular_open_at
                    else None
                ),
                "regular_close_at": (
                    r.regular_close_at.isoformat()
                    if r.regular_close_at
                    else None
                ),
                "revision": int(getattr(r, "revision", 1) or 1),
            }
            for r in rows
            if r.session_type
            in {
                CalendarSessionType.DELAYED_OPEN.value,
                CalendarSessionType.EARLY_CLOSE.value,
                CalendarSessionType.SPECIAL_SESSION.value,
                CalendarSessionType.CLOSED.value,
            }
            or not r.is_trading_day
        ]
        print(json.dumps({"items": special}, ensure_ascii=False, indent=2))
        return 0
    finally:
        session.close()


def cmd_day(args: argparse.Namespace) -> int:
    from stock_platform.operation.calendar_repository import (
        TradingCalendarRepository,
    )
    from stock_platform.operation.calendar_service import (
        TradingCalendarService,
    )

    session = _session()
    try:
        d = date.fromisoformat(args.date)
        repo = TradingCalendarRepository(session)
        row = repo.get_day(exchange_code="KRX", calendar_date=d)
        decision = TradingCalendarService(repo).evaluate(
            exchange_code="KRX", calendar_date=d
        )
        print(
            json.dumps(
                {
                    "stored": None
                    if row is None
                    else {
                        "session_type": row.session_type,
                        "is_trading_day": row.is_trading_day,
                        "revision": int(
                            getattr(row, "revision", 1) or 1
                        ),
                        "regular_open_at": (
                            row.regular_open_at.isoformat()
                            if row.regular_open_at
                            else None
                        ),
                        "regular_close_at": (
                            row.regular_close_at.isoformat()
                            if row.regular_close_at
                            else None
                        ),
                    },
                    "decision": {
                        "reason_code": decision.reason_code,
                        "live_allowed": decision.live_allowed,
                        "session_type": decision.session_type,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        session.close()


def cmd_preview_import(args: argparse.Namespace) -> int:
    """JSON Import Preview — Change Request만 생성 (즉시 Apply 금지)."""

    path = Path(args.file)
    if not path.is_file():
        print(f"file not found: {path}", file=sys.stderr)
        return 2
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload if isinstance(payload, list) else payload.get("items", [])
    from stock_platform.operation.calendar_change_constants import (
        CalendarChangeType,
        CalendarSourceType,
    )
    from stock_platform.operation.calendar_change_service import (
        CalendarChangeError,
        TradingCalendarChangeService,
        request_as_dict,
    )

    session = _session()
    created = []
    errors = []
    try:
        svc = TradingCalendarChangeService(session)
        for raw in items:
            try:
                md = date.fromisoformat(str(raw["market_date"]))
                row = svc.create_request(
                    exchange_code=str(raw.get("exchange_code", "KRX")),
                    market_date=md,
                    change_type=str(
                        raw.get(
                            "change_type",
                            CalendarChangeType.SPECIAL_SESSION.value,
                        )
                    ),
                    requested_values=dict(raw.get("requested_values") or {}),
                    reason=str(raw.get("reason") or "import preview"),
                    source_type=str(
                        raw.get(
                            "source_type",
                            CalendarSourceType.KRX_OFFICIAL_NOTICE.value,
                        )
                    ),
                    source_reference=raw.get("source_reference"),
                    emergency=False,
                    requested_by=str(raw.get("requested_by") or "cli-import"),
                )
                created.append(request_as_dict(row))
            except (CalendarChangeError, KeyError, ValueError) as exc:
                errors.append({"raw": raw, "error": str(exc)})
        if args.commit and not errors:
            session.commit()
        else:
            session.rollback()
        print(
            json.dumps(
                {
                    "preview_only": not bool(args.commit),
                    "created_count": len(created),
                    "error_count": len(errors),
                    "created": created,
                    "errors": errors,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if errors else 0
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="krx_calendar_change_cli",
        description="KRX Calendar Change Request CLI (no direct DB update)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_pending = sub.add_parser("pending", help="Pending/Conflict 요청")
    p_pending.set_defaults(func=cmd_pending)

    p_special = sub.add_parser("special", help="특별 Session 목록")
    p_special.set_defaults(func=cmd_special)

    p_day = sub.add_parser("day", help="날짜 조회")
    p_day.add_argument("--date", required=True)
    p_day.set_defaults(func=cmd_day)

    p_imp = sub.add_parser(
        "preview-import", help="JSON → Change Request Preview"
    )
    p_imp.add_argument("--file", required=True)
    p_imp.add_argument(
        "--commit",
        action="store_true",
        help="DRAFT 요청 커밋 (Apply는 하지 않음)",
    )
    p_imp.set_defaults(func=cmd_preview_import)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
