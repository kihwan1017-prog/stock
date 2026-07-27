"""STEP 8-10 — 조회 전용 Preflight (실주문/ARM/LIVE ON 금지)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

from stock_platform.broker.account_repository import BrokerAccountSnapshotRepository
from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultService,
)
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
OPENISH = {
    "NEW",
    "CREATED",
    "PENDING",
    "SENT",
    "ACCEPTED",
    "OPEN",
    "PARTIAL",
    "PARTIALLY_FILLED",
    "SUBMITTED",
    "UNKNOWN",
    "SUBMISSION_UNKNOWN",
    "CANCEL_PENDING",
}


def main() -> int:
    uba_id = 58
    session = get_session_factory()()
    out: dict = {
        "uba_id": uba_id,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "execute_live": False,
        "arm_attempted": False,
        "live_on_attempted": False,
    }
    try:
        settings = get_settings()
        out["upbit_use_mock"] = bool(getattr(settings, "upbit_use_mock", True))
        out["recovery_scheduler_enabled"] = bool(
            getattr(settings, "recovery_scheduler_enabled", True)
        )

        uba = session.get(UserBrokerAccount, uba_id)
        if uba is None:
            print(json.dumps({"error": "UBA_NOT_FOUND"}, ensure_ascii=False))
            return 2
        out["broker_code"] = str(uba.broker_code).upper()
        out["is_active"] = bool(uba.is_active)
        out["live_order_enabled"] = bool(uba.live_order_enabled)
        out["live_armed"] = bool(uba.live_armed)
        out["arm_expires_at"] = (
            uba.arm_expires_at.isoformat() if uba.arm_expires_at else None
        )

        cred_view = BrokerCredentialVaultService(session).status(uba_id)
        out["credential"] = cred_view.as_dict()

        snap, positions = BrokerAccountSnapshotRepository(session).get_active_by_uba(
            uba_id
        )
        out["broker_snapshot"] = (
            None
            if snap is None
            else {
                "deposit_amount": str(snap.deposit_amount),
                "total_evaluation_amount": str(snap.total_evaluation_amount),
                "position_count": len(positions or []),
            }
        )

        today = datetime.now(_KST).date()
        loss_row = session.scalar(
            select(AccountDailyLossEntity).where(
                AccountDailyLossEntity.user_broker_account_id == uba_id,
                AccountDailyLossEntity.trading_date == today,
            )
        )
        limit = Decimal(str(loss_row.loss_limit_amount if loss_row else "300000"))
        diag = UbaDailyLossService(session).diagnose(
            user_broker_account_id=uba_id,
            loss_limit=limit,
            trading_date=today,
        )
        out["daily_loss"] = diag.to_dict()

        out["kill_switch"] = {}
        for scope in ("GLOBAL", f"UBA:{uba_id}"):
            ks = session.scalar(
                select(KillSwitchEntity).where(KillSwitchEntity.scope_code == scope)
            )
            out["kill_switch"][scope] = {"active": bool(ks.active) if ks else False}

        orders = list(
            session.scalars(
                select(TradingOrderEntity).where(
                    TradingOrderEntity.user_broker_account_id == uba_id
                )
            )
        )
        open_orders = [
            {
                "order_id": getattr(o, "order_id", None),
                "status": str(getattr(o, "status_code", "") or "").upper(),
            }
            for o in orders
            if str(getattr(o, "status_code", "") or "").upper() in OPENISH
        ]
        out["db_orders_total"] = len(orders)
        out["db_open_order_count"] = len(open_orders)
        out["db_open_orders"] = open_orders
        out["scheduler"] = collect_scheduler_readiness(settings).to_dict()

        # 시세 후보 — 자동 확정 금지
        market = "KRW-XRP"
        quote: dict = {
            "market_candidate": market,
            "operator_confirmed": False,
            "note": "기본 후보일 뿐. Market/Limit Price는 운영자가 확정해야 함",
        }
        try:
            t = httpx.get(
                "https://api.upbit.com/v1/ticker",
                params={"markets": market},
                timeout=10.0,
            ).json()[0]
            ob = httpx.get(
                "https://api.upbit.com/v1/orderbook",
                params={"markets": market},
                timeout=10.0,
            ).json()[0]
            unit = (ob.get("orderbook_units") or [{}])[0]
            trade = Decimal(str(t.get("trade_price")))
            bid = Decimal(str(unit.get("bid_price")))
            ask = Decimal(str(unit.get("ask_price")))
            tick = Decimal("1")
            candidate = ask.quantize(tick)
            amount = Decimal("5000")
            qty = (amount / candidate).quantize(Decimal("0.00000001"))
            fee = (amount * Decimal("0.0005")).quantize(Decimal("0.01"))
            quote.update(
                {
                    "trade_price": str(trade),
                    "bid1": str(bid),
                    "ask1": str(ask),
                    "tick_size_broker_typical": str(tick),
                    "display_candidate_limit_price": str(candidate),
                    "estimated_qty_at_display_candidate": str(qty),
                    "estimated_amount": str(amount),
                    "estimated_fee_approx_0_05pct": str(fee),
                    "requested_vs_effective_note": (
                        "운영자 선택가 → Broker tick 유효가 재확인 필요"
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001
            quote["error"] = f"{type(exc).__name__}: {exc}"
        out["quote_candidate"] = quote

        # Broker 잔고/미체결 — private 조회만 (주문 생성 금지)
        try:
            import asyncio

            from stock_platform.broker.credential_adapter_factory import (
                build_upbit_private_client_for_uba,
            )

            client = build_upbit_private_client_for_uba(session, uba_id)

            async def _fetch() -> tuple[list, list]:
                accounts = await client.list_accounts()
                open_orders: list = []
                if hasattr(client, "list_orders"):
                    try:
                        open_orders = await client.list_orders(state="wait")  # type: ignore[misc]
                    except TypeError:
                        open_orders = []
                return list(accounts or []), list(open_orders or [])

            accounts, open_broker = asyncio.run(_fetch())
            krw = None
            for row in accounts:
                cur = str(
                    row.get("currency") if isinstance(row, dict) else ""
                ).upper()
                if cur == "KRW":
                    bal = Decimal(str(row.get("balance") or 0))
                    locked = Decimal(str(row.get("locked") or 0))
                    krw = {
                        "balance": str(bal),
                        "locked": str(locked),
                        "orderable_approx": str(bal - locked),
                    }
            out["broker_krw"] = krw
            out["broker_open_order_count"] = len(open_broker)
            out["broker_health"] = "HEALTHY"
        except Exception as exc:  # noqa: BLE001
            out["broker_krw"] = None
            out["broker_open_order_count"] = None
            out["broker_health"] = f"CHECK_FAILED:{type(exc).__name__}"
            out["broker_health_detail"] = str(exc)[:240]

        allow = str(
            getattr(settings, "upbit_live_smoke_allowlist", "") or ""
        )
        out["allowlist"] = [x.strip().upper() for x in allow.split(",") if x.strip()]

        blockers: list[str] = []
        if out["credential"].get("verification_status") != "VERIFIED":
            blockers.append("CREDENTIAL_NOT_VERIFIED")
        if out["upbit_use_mock"]:
            blockers.append("UPBIT_USE_MOCK_TRUE")
        if out["live_order_enabled"]:
            blockers.append("LIVE_ALREADY_ON")
        if out["live_armed"]:
            blockers.append("ALREADY_ARMED")
        if out["db_open_order_count"]:
            blockers.append("DB_OPEN_ORDERS")
        if out.get("broker_open_order_count"):
            blockers.append("BROKER_OPEN_ORDERS")
        if out["kill_switch"]["GLOBAL"]["active"] or out["kill_switch"][
            f"UBA:{uba_id}"
        ]["active"]:
            blockers.append("KILL_SWITCH_ACTIVE")
        if Decimal(str(diag.current_daily_loss)) >= limit:
            blockers.append("DAILY_LOSS_LIMIT")
        krw_info = out.get("broker_krw") or {}
        try:
            orderable = Decimal(str(krw_info.get("orderable_approx") or "0"))
        except Exception:  # noqa: BLE001
            orderable = Decimal("0")
        if orderable < Decimal("5000"):
            blockers.append(
                f"INSUFFICIENT_KRW_ORDERABLE:{orderable}"
            )
        if not out["scheduler"].get("trading_scheduler_paused"):
            # CLI 프로세스 밖이면 UNKNOWN일 수 있음 — 경고만
            if out["scheduler"].get("trading_scheduler_actual_state") == "RUNNING":
                blockers.append("TRADING_SCHEDULER_RUNNING")
        out["gate_blockers_before_approval"] = blockers
        out["ready_for_operator_decision"] = len(blockers) == 0
        out["release_blocker"] = blockers[:]
        out["operator_approval_phrase_required"] = (
            "UPBIT 5000원 LIVE 1건 실행 승인"
        )
        out["operator_must_confirm"] = [
            "market",
            "limit_price",
            "execute_yes_no",
        ]
        out["next_action"] = (
            "RESOLVE_BLOCKERS"
            if blockers
            else "AWAIT_OPERATOR_MARKET_PRICE_AND_APPROVAL"
        )

        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0 if out["ready_for_operator_decision"] else 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
