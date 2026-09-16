"""STEP 8-10 — 실행 직후 조회 전용 확인 (추가 주문/ARM/LIVE ON 금지)."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.daily_loss_entities import AccountDailyLossEntity
from stock_platform.risk_engine.kill_switch_entities import KillSwitchEntity
from stock_platform.risk_engine.uba_daily_loss_service import UbaDailyLossService
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.upbit_scheduler_readiness import (
    collect_scheduler_readiness,
)


_KST = ZoneInfo("Asia/Seoul")


def _mask(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value)
    if len(text) <= 8:
        return "***"
    return f"{text[:4]}…{text[-4:]}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="step8_10_post_execution_verify")
    p.add_argument("--uba-id", type=int, default=58)
    p.add_argument("--run-id", type=str, default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # 실주문 플래그 실수 방지
    joined = " ".join(argv or []).lower()
    if "execute-live" in joined or "--arm-token" in joined:
        print("REJECT: post-verify forbids live/arm flags")
        return 2

    uba_id = int(args.uba_id)
    session = get_session_factory()()
    out: dict = {
        "uba_id": uba_id,
        "run_id_filter": args.run_id,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        uba = session.get(UserBrokerAccount, uba_id)
        if uba is None:
            print(json.dumps({"error": "UBA_NOT_FOUND"}))
            return 2
        out["live_order_enabled"] = bool(uba.live_order_enabled)
        out["live_armed"] = bool(uba.live_armed)
        out["arm_expires_at"] = (
            uba.arm_expires_at.isoformat() if uba.arm_expires_at else None
        )
        out["live_off"] = not bool(uba.live_order_enabled)
        out["disarmed"] = not bool(uba.live_armed)

        q = select(TradingOrderEntity).where(
            TradingOrderEntity.user_broker_account_id == uba_id
        )
        orders = list(session.scalars(q.order_by(TradingOrderEntity.created_at.desc())))
        if args.run_id:
            filtered = []
            for o in orders:
                meta = getattr(o, "metadata_json", None) or getattr(
                    o, "client_order_id", None
                )
                blob = f"{meta}|{getattr(o, 'client_order_id', '')}|{getattr(o, 'idempotency_key', '')}"
                if args.run_id in str(blob):
                    filtered.append(o)
            orders = filtered or orders[:5]

        order_rows = []
        for o in orders[:10]:
            order_rows.append(
                {
                    "order_id": getattr(o, "order_id", None),
                    "internal_status": getattr(o, "status_code", None),
                    "broker_order_status": getattr(o, "broker_status_code", None)
                    or getattr(o, "exchange_status", None),
                    "broker_uuid_masked": _mask(
                        getattr(o, "broker_order_id", None)
                        or getattr(o, "exchange_order_id", None)
                    ),
                    "limit_price": str(getattr(o, "limit_price", None)),
                    "filled_qty": str(getattr(o, "filled_quantity", None)),
                    "avg_price": str(getattr(o, "average_fill_price", None)),
                    "side": getattr(o, "side_code", None),
                    "client_order_id": getattr(o, "client_order_id", None),
                }
            )
        out["orders"] = order_rows

        today = datetime.now(_KST).date()
        loss_row = session.scalar(
            select(AccountDailyLossEntity).where(
                AccountDailyLossEntity.user_broker_account_id == uba_id,
                AccountDailyLossEntity.trading_date == today,
            )
        )
        limit = Decimal(str(loss_row.loss_limit_amount if loss_row else "300000"))
        out["daily_loss"] = UbaDailyLossService(session).diagnose(
            user_broker_account_id=uba_id,
            loss_limit=limit,
            trading_date=today,
        ).to_dict()

        out["kill_switch"] = {}
        for scope in ("GLOBAL", f"UBA:{uba_id}"):
            ks = session.scalar(
                select(KillSwitchEntity).where(KillSwitchEntity.scope_code == scope)
            )
            out["kill_switch"][scope] = {"active": bool(ks.active) if ks else False}

        out["scheduler"] = collect_scheduler_readiness(get_settings()).to_dict()
        out["manual_review_required"] = any(
            str(r.get("internal_status") or "").upper()
            in {
                "UNKNOWN",
                "SUBMISSION_UNKNOWN",
                "CANCEL_PENDING",
                "CANCEL_FAILED",
            }
            for r in order_rows
        )
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
