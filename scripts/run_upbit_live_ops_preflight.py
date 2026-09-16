"""scripts/run_upbit_live_ops_preflight.py — STEP 8-9B 운영 점검 CLI.

조회 전용. --execute-live / create_order / cancel_order / ARM 금지.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_upbit_live_ops_preflight",
        description="Upbit 5,000원 LIVE 직전 운영 점검 (조회 전용)",
    )
    p.add_argument("--amount", type=str, default="5000")
    p.add_argument("--actor", type=str, default="STEP8_9B_OPS")
    p.add_argument(
        "--run-dry-run",
        action="store_true",
        help="운영자가 지정한 UBA/market/price로 dry-run 실행",
    )
    p.add_argument("--uba-id", type=int, default=None)
    p.add_argument("--market", type=str, default=None)
    p.add_argument("--limit-price", type=str, default=None)
    p.add_argument(
        "--no-report",
        action="store_true",
        help="마크다운 보고서 생략",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # 실주문 플래그 실수 방지
    joined = " ".join(argv or sys.argv[1:]).lower()
    if "--execute-live" in joined or "execute-live" in joined:
        print("REJECT: STEP 8-9B forbids --execute-live")
        return 2

    from stock_platform.database.session import get_session_factory
    from stock_platform.trading.upbit_live_ops_inspection_service import (
        UpbitLiveOpsInspectionService,
    )
    from stock_platform.trading.upbit_live_smoke_constants import (
        MAX_SMOKE_AMOUNT,
    )

    amount = Decimal(str(args.amount))
    if amount > MAX_SMOKE_AMOUNT:
        print(f"REJECT: amount {amount} > {MAX_SMOKE_AMOUNT}")
        return 2

    session = get_session_factory()()
    try:
        svc = UpbitLiveOpsInspectionService(session)
        payload = svc.inspect(
            amount=amount,
            actor=args.actor,
            write_report=not bool(args.no_report),
        )

        dry_results: list[dict] = []
        if args.run_dry_run:
            if not args.uba_id or not args.market or not args.limit_price:
                print(
                    "REJECT: --run-dry-run requires "
                    "--uba-id --market --limit-price"
                )
                return 2
            dry = svc.run_dry_runs(
                uba_id=int(args.uba_id),
                market=str(args.market).upper(),
                limit_price=Decimal(str(args.limit_price)),
                amount=amount,
                actor=args.actor,
            )
            dry_results.append(dry)
            payload["dry_run_results"] = dry_results
            # 보고서 재기록
            if not args.no_report:
                from datetime import datetime, timezone

                path = svc._write_report(
                    payload,
                    report_dir=None,
                    now=datetime.now(timezone.utc),
                )
                payload["report_path"] = str(path)
            session.commit()
        else:
            session.commit()

        # 민감 키 제거 후 요약 출력
        safe = json.loads(json.dumps(payload, default=str))
        if isinstance(safe, dict):
            for key in ("arm_token", "access_key", "secret_key"):
                safe.pop(key, None)
            # 상세 UBA id는 운영자용이지만 콘솔에는 마스킹 위주
            detail = safe.get("uba_candidates_detail")
            if isinstance(detail, list):
                for row in detail:
                    if isinstance(row, dict) and "uba_id" in row:
                        row["uba_id"] = row.get("uba_id_masked")

        print("=== STEP 8-9B Ops Preflight ===")
        print(f"verdict              : {safe.get('verdict')}")
        print(f"execute_live_ran     : {safe.get('execute_live_ran')}")
        print(f"uba_candidates       : {safe.get('uba_candidate_count')}")
        print(f"release_blockers     : {safe.get('release_blocker_count')}")
        print(f"report_path          : {safe.get('report_path')}")
        print("blockers:")
        for b in safe.get("blockers") or []:
            print(f"  - {b}")
        print("warnings:")
        for w in safe.get("warnings") or []:
            print(f"  - {w}")
        print("===============================")
        print(json.dumps(safe, ensure_ascii=False, indent=2))
        return 0 if safe.get("verdict") == "READY" else 1
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
