"""CLI for Operation Rehearsal."""

from __future__ import annotations

import argparse
import sys

from stock_platform.operations.rehearsal.models import RehearsalOptions
from stock_platform.operations.rehearsal.runner import (
    run_operation_rehearsal,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="operation-rehearsal",
        description="Operation Rehearsal Automation (STEP 8-6-1A)",
    )
    parser.add_argument("--paper", action="store_true")
    parser.add_argument("--kiwoom", action="store_true")
    parser.add_argument("--upbit", action="store_true")
    parser.add_argument("--risk", action="store_true")
    parser.add_argument("--scheduler", action="store_true")
    parser.add_argument("--recovery", action="store_true")
    parser.add_argument(
        "--telegram",
        default="dry-run",
        choices=("dry-run", "off", "live"),
        help="Telegram mode (live is refused)",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help=(
            "Regenerate MD/HTML from latest (or --from-json) report; "
            "no broker/DB mutations"
        ),
    )
    parser.add_argument(
        "--from-json",
        default=None,
        help="Source JSON for --report-only",
    )
    parser.add_argument("--full", action="store_true")
    parser.add_argument(
        "--report-dir",
        default=None,
        help="Override report directory",
    )
    parser.add_argument(
        "--no-paper-mutation",
        action="store_true",
        help="Skip paper fill mutations",
    )
    return parser


def options_from_args(argv: list[str] | None = None) -> RehearsalOptions:
    args = build_parser().parse_args(argv)
    return RehearsalOptions(
        paper=bool(args.paper),
        kiwoom=bool(args.kiwoom),
        upbit=bool(args.upbit),
        risk=bool(args.risk),
        scheduler=bool(args.scheduler),
        recovery=bool(args.recovery),
        telegram=str(args.telegram),
        report_only=bool(args.report_only),
        full=bool(args.full),
        allow_paper_mutation=not bool(args.no_paper_mutation),
        report_dir=args.report_dir,
        report_source_json=args.from_json,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        options = options_from_args(argv)
    except SystemExit as exc:
        # argparse 잘못된 옵션 → non-zero
        code = exc.code
        if code is None:
            return 2
        return int(code) if not isinstance(code, bool) else (0 if code else 2)

    try:
        report = run_operation_rehearsal(options)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL_CLOSED: unexpected error: {type(exc).__name__}")
        return 2
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
