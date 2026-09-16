"""scripts/run_upbit_live_smoke_test.py — Upbit 소액 LIVE 스모크 CLI.

기본: DRY-RUN. 실주문은 다음이 모두 있을 때만 가능.
  --execute-live
  --confirmation-text UPBIT-LIVE-ONE-ORDER
  --arm-token <ONE_TIME_TOKEN>
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


CHECKLIST = [
    "업비트 실계좌 UBA 1개만 선택",
    "주문금액 10,000원 이하",
    "지정가 주문",
    "자동매매 Scheduler Pause",
    "Strategy Runtime Pause",
    "Open Order 0",
    "Kill Switch OFF",
    "Telegram 정상",
    "Post-fill Scheduler 정상",
    "ARM 만료시간 확인",
    "실행 후 자동 DISARM",
    "실행 후 LIVE OFF",
]


def _print_checklist() -> None:
    print("=== Upbit Small LIVE Checklist ===")
    for item in CHECKLIST:
        print(f"[ ] {item}")
    print("==================================")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_upbit_live_smoke_test",
        description="Upbit 소액 LIVE 사전점검/수동 1건 검증 (기본 dry-run)",
    )
    p.add_argument("--uba-id", type=int, required=True)
    p.add_argument("--market", type=str, required=True)
    p.add_argument("--side", type=str, choices=["BUY", "SELL"], required=True)
    p.add_argument("--amount", type=str, default="5000")
    p.add_argument("--limit-price", type=str, required=True)
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="기본값. Adapter 주문 미호출",
    )
    p.add_argument(
        "--execute-live",
        action="store_true",
        default=False,
        help="실주문 (confirmation + arm-token 필수)",
    )
    p.add_argument("--confirmation-text", type=str, default="")
    p.add_argument("--arm-token", type=str, default="")
    p.add_argument(
        "--skip-network",
        action="store_true",
        help="시세/인증 네트워크 생략 (로컬 점검용)",
    )
    p.add_argument("--actor", type=str, default="CLI_OPERATOR")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _print_checklist()

    execute_live = bool(args.execute_live)
    # --execute-live가 없으면 항상 dry-run
    if execute_live:
        print(
            "WARNING: --execute-live requested. "
            "This STEP development must not run live orders without approval."
        )

    from stock_platform.database.session import get_session_factory
    from stock_platform.trading.upbit_live_smoke_constants import (
        CONFIRMATION_TEXT,
        MAX_SMOKE_AMOUNT,
    )
    from stock_platform.trading.upbit_live_smoke_service import (
        UpbitLiveSmokeError,
        UpbitLiveSmokeService,
    )

    amount = Decimal(str(args.amount))
    price = Decimal(str(args.limit_price))
    if amount > MAX_SMOKE_AMOUNT:
        print(f"REJECT: amount {amount} > {MAX_SMOKE_AMOUNT}")
        return 2

    session = get_session_factory()()
    try:
        svc = UpbitLiveSmokeService(session)
        if execute_live:
            # 개발 에이전트/기본 운영은 여기서도 추가 가드
            if args.confirmation_text != CONFIRMATION_TEXT:
                print("REJECT: confirmation-text mismatch")
                return 2
            if not args.arm_token:
                print("REJECT: arm-token required")
                return 2
            result = svc.execute(
                user_broker_account_id=int(args.uba_id),
                market=str(args.market).upper(),
                side=str(args.side).upper(),
                amount=amount,
                limit_price=price,
                actor=args.actor,
                arm_token=args.arm_token,
                execute_live=True,
                confirmation_text=args.confirmation_text,
                skip_live_network=bool(args.skip_network),
            )
        else:
            result = svc.dry_run(
                user_broker_account_id=int(args.uba_id),
                market=str(args.market).upper(),
                side=str(args.side).upper(),
                amount=amount,
                limit_price=price,
                actor=args.actor,
                arm_token=args.arm_token or None,
                skip_live_network=bool(args.skip_network),
            )
        session.commit()
        # 민감정보 제거 후 출력
        safe = json.loads(json.dumps(result, default=str))
        if isinstance(safe, dict):
            safe.pop("arm_token", None)
            pf = safe.get("preflight")
            if isinstance(pf, dict):
                pf.pop("arm_token", None)
            # 상태 구분 요약 (오인 방지)
            print("=== Status Summary ===")
            print(f"internal_status     : {safe.get('internal_status') or safe.get('status')}")
            print(f"broker_order_status : {safe.get('broker_order_status')}")
            print(f"order_id            : {safe.get('order_id')}")
            print(f"broker_uuid_masked  : {safe.get('broker_uuid_masked')}")
            print(f"manual_review       : {safe.get('manual_review_required')}")
            print(
                "NOTE: OUTBOX_PENDING ≠ ORDER_ACCEPTED; "
                "CANCEL_REQUESTED ≠ CANCELED"
            )
            print("======================")
        print(json.dumps(safe, ensure_ascii=False, indent=2))
        if execute_live:
            return 0 if safe.get("status") else 1
        ready = bool((safe.get("preflight") or {}).get("ready"))
        return 0 if ready or not execute_live else 1
    except UpbitLiveSmokeError as exc:
        session.rollback()
        print(f"REJECT: {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
