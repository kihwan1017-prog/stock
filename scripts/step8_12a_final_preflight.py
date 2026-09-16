"""STEP 8-12A — 업비트 5,000원 LIVE 최종 사전검증 (실주문/ARM/Conflict 변경 금지).

운영자가 Market·Limit Price를 확정하기 전에는 Dry-run을 실행하지 않는다.
승인 문구·실주문 명령은 생성하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultService,
)
from stock_platform.broker.fee_policy import UpbitFeePolicy
from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.broker.recovery_conflict_entities import (
    BrokerRecoveryConflictEntity,
)
from stock_platform.broker.upbit.rules import (
    UPBIT_MIN_NOTIONAL_KRW,
    round_upbit_price,
    round_upbit_volume,
    upbit_tick_size,
)
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.daily_loss_entities import AccountDailyLossEntity
from stock_platform.risk_engine.kill_switch_entities import KillSwitchEntity
from stock_platform.risk_engine.uba_daily_loss_service import UbaDailyLossService
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.step8_12a_conflict_classifier import (
    CLASS_CURRENT_ACTIVE,
    CLASS_DUP,
    CLASS_HISTORICAL,
    CLASS_STATE_MISMATCH,
    CLASS_TEST,
    CLASS_UNKNOWN,
    classify_conflict,
    summarize_classifications,
)
from stock_platform.trading.upbit_live_smoke_constants import (
    DEFAULT_ALLOWLIST,
    DEFAULT_SMOKE_AMOUNT,
)
from stock_platform.trading.upbit_scheduler_readiness import (
    collect_scheduler_readiness,
)


_KST = ZoneInfo("Asia/Seoul")
_FEE = UpbitFeePolicy()
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


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return Decimal("0")


def _mask_uuid(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if len(raw) <= 8:
        return raw[0] + "…" + raw[-1]
    return f"{raw[:4]}…{raw[-4:]}"


def _qty_for_amount(amount: Decimal, price: Decimal) -> Decimal:
    if price <= 0:
        return Decimal("0")
    return round_upbit_volume(amount / price)


def build_limit_candidates(
    *,
    trade_price: Decimal,
    bid_1: Decimal | None,
    ask_1: Decimal | None,
    amount: Decimal,
    orderable_krw: Decimal | None,
) -> list[dict[str, Any]]:
    """매수 지정가 후보 (자동 확정 금지)."""

    tick = upbit_tick_size(ask_1 or trade_price or bid_1 or Decimal("1"))
    raw_candidates: list[tuple[str, Decimal]] = []
    if bid_1 and bid_1 > 0:
        raw_candidates.append(("best_bid", bid_1))
    if ask_1 and ask_1 > 0:
        raw_candidates.append(("best_ask", ask_1))
        raw_candidates.append(("best_ask_plus_1_tick", ask_1 + tick))
    if trade_price > 0:
        raw_candidates.append(("trade_price_normalized", trade_price))

    out: list[dict[str, Any]] = []
    for label, requested in raw_candidates:
        effective = round_upbit_price(requested)
        adjusted = effective != requested
        qty = _qty_for_amount(amount, effective) if effective > 0 else Decimal("0")
        est_amt = (qty * effective).quantize(Decimal("0.0001")) if effective > 0 else Decimal("0")
        fee = _FEE.fee_amount(notional=est_amt, is_maker=True)
        projected = None
        if orderable_krw is not None:
            projected = str(orderable_krw - est_amt - fee)
        out.append(
            {
                "label": label,
                "requested_price": str(requested),
                "effective_price": str(effective),
                "tick_size": str(tick),
                "price_adjusted": adjusted,
                "expected_quantity": str(qty),
                "expected_order_amount": str(est_amt),
                "min_notional_ok": est_amt >= UPBIT_MIN_NOTIONAL_KRW,
                "expected_fee": str(fee),
                "projected_remaining_krw": projected,
                "auto_selected": False,
            }
        )
    return out


def fetch_market_quotes(
    markets: list[str],
    *,
    amount: Decimal,
    orderable_krw: Decimal | None,
) -> list[dict[str, Any]]:
    checked_at = datetime.now(timezone.utc).isoformat()
    results: list[dict[str, Any]] = []
    with httpx.Client(timeout=15.0) as client:
        tickers = {
            row["market"]: row
            for row in client.get(
                "https://api.upbit.com/v1/ticker",
                params={"markets": ",".join(markets)},
            ).json()
        }
        books = {
            row["market"]: row
            for row in client.get(
                "https://api.upbit.com/v1/orderbook",
                params={"markets": ",".join(markets)},
            ).json()
        }

    for market in markets:
        ticker = tickers.get(market) or {}
        book = books.get(market) or {}
        units = book.get("orderbook_units") or []
        bid = ask = None
        if units:
            first = units[0] if isinstance(units[0], dict) else {}
            bid = _dec(first.get("bid_price"))
            ask = _dec(first.get("ask_price"))
        trade = _dec(ticker.get("trade_price"))
        if trade <= 0 and ask and ask > 0:
            trade = ask
        spread = (ask - bid) if bid and ask and ask > 0 and bid > 0 else None
        mid = ((ask + bid) / 2) if bid and ask and ask > 0 and bid > 0 else None
        spread_rate = (
            (spread / mid) if spread is not None and mid and mid > 0 else None
        )
        tick = upbit_tick_size(trade) if trade > 0 else None
        ref = ask if ask and ask > 0 else trade
        qty = _qty_for_amount(amount, ref) if ref and ref > 0 else None
        est = (qty * ref).quantize(Decimal("0.0001")) if qty and ref else None
        results.append(
            {
                "market": market,
                "trade_price": str(trade) if trade > 0 else None,
                "best_bid": str(bid) if bid else None,
                "best_ask": str(ask) if ask else None,
                "spread": str(spread) if spread is not None else None,
                "spread_rate": str(spread_rate) if spread_rate is not None else None,
                "tick_size": str(tick) if tick is not None else None,
                "qty_for_5000_at_ask_or_trade": str(qty) if qty is not None else None,
                "estimated_amount": str(est) if est is not None else None,
                "min_notional_ok": bool(
                    est is not None and est >= UPBIT_MIN_NOTIONAL_KRW
                ),
                "market_warning": False,
                "quote_checked_at": checked_at,
                "stale": False,
                "operator_auto_selected": False,
                "note": "시스템 추천이 아니라 파이프라인 검증용 후보. 운영자가 Market을 직접 확정해야 함.",
                "limit_candidates": build_limit_candidates(
                    trade_price=trade,
                    bid_1=bid,
                    ask_1=ask,
                    amount=amount,
                    orderable_krw=orderable_krw,
                ),
            }
        )
    return results


async def _broker_accounts(session: Any, uba_id: int) -> dict[str, Any]:
    from stock_platform.broker.credential_adapter_factory import (
        build_upbit_private_client_for_uba,
    )

    client = build_upbit_private_client_for_uba(session, uba_id)
    accounts = await client.list_accounts()
    krw = None
    for row in accounts or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("currency") or "").upper() != "KRW":
            continue
        bal = _dec(row.get("balance"))
        locked = _dec(row.get("locked"))
        krw = {
            "balance": str(bal),
            "locked": str(locked),
            "orderable_approx": str(bal - locked),
        }
    return {"broker_krw": krw, "broker_health": "HEALTHY"}


def _build_order_query_client(session: Any, uba_id: int) -> Any:
    """주문 생성/취소 없는 조회 전용 Order REST 클라이언트."""

    from stock_platform.broker.credential_adapter_factory import (
        build_upbit_settings_from_vault,
        resolve_uba_credential,
    )
    from stock_platform.broker.upbit.order_client import UpbitOrderRestClient

    resolved = resolve_uba_credential(
        session, uba_id, expected_broker="UPBIT"
    )
    vault_settings = build_upbit_settings_from_vault(resolved)
    return UpbitOrderRestClient(
        settings=vault_settings,
        user_broker_account_id=int(uba_id),
    )


def _list_broker_open_orders(order_client: Any) -> tuple[int, set[str]]:
    rows = order_client.list_orders(state="wait", limit=100)
    uuids: set[str] = set()
    for row in rows or []:
        if isinstance(row, dict) and row.get("uuid"):
            uuids.add(str(row["uuid"]))
    return len(rows or []), uuids


def _lookup_remote_status_sync(order_client: Any, uuid: str) -> str | None:
    try:
        row = order_client.get_order(uuid=uuid)
        if isinstance(row, dict):
            return str(row.get("state") or "").lower() or None
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "404" in msg or "not found" in msg or "not_found" in msg:
            return "not_found"
        return f"error:{type(exc).__name__}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="STEP 8-12A final preflight")
    parser.add_argument("--uba-id", type=int, default=58)
    parser.add_argument("--amount", type=str, default=str(DEFAULT_SMOKE_AMOUNT))
    parser.add_argument(
        "--market",
        type=str,
        default="",
        help="운영자 확정 Market. 없으면 Dry-run 미실행",
    )
    parser.add_argument(
        "--limit-price",
        type=str,
        default="",
        help="운영자 확정 Limit Price. 없으면 Dry-run 미실행",
    )
    parser.add_argument(
        "--lookup-wait-conflicts",
        action="store_true",
        default=True,
        help="wait 스냅샷 Conflict에 대해 조회 전용 get_order 수행",
    )
    parser.add_argument(
        "--no-lookup-wait-conflicts",
        action="store_true",
        help="단건 remote lookup 생략",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="",
        help="JSON 보고서 경로 (미지정 시 stdout만)",
    )
    args = parser.parse_args()
    do_lookup = bool(args.lookup_wait_conflicts) and not bool(
        args.no_lookup_wait_conflicts
    )

    uba_id = int(args.uba_id)
    amount = Decimal(str(args.amount))
    operator_market = (args.market or "").strip().upper()
    operator_price = (args.limit_price or "").strip()

    session = get_session_factory()()
    settings = get_settings()
    now = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "step": "8-12A",
        "checked_at": now.isoformat(),
        "uba_id": uba_id,
        "execute_live": False,
        "arm_attempted": False,
        "live_on_attempted": False,
        "conflict_mutations": 0,
        "approve_import_calls": 0,
        "ignore_calls": 0,
        "delete_calls": 0,
        "adapter_create_order_calls": 0,
        "cancel_calls": 0,
        "replace_calls": 0,
        "dry_run_executed": False,
        "operator_confirmed_market": operator_market or None,
        "operator_confirmed_limit_price": operator_price or None,
        "release_blockers": [],
        "warnings": [],
    }

    try:
        uba = session.get(UserBrokerAccount, uba_id)
        if uba is None:
            report["final_status"] = "BLOCKED"
            report["release_blockers"] = ["UBA_NOT_FOUND"]
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
            return 2

        report["broker_code"] = str(uba.broker_code).upper()
        report["live_order_enabled"] = bool(uba.live_order_enabled)
        report["live_armed"] = bool(uba.live_armed)
        report["arm_expires_at"] = (
            uba.arm_expires_at.isoformat() if uba.arm_expires_at else None
        )
        report["upbit_use_mock"] = bool(getattr(settings, "upbit_use_mock", True))

        cred = BrokerCredentialVaultService(session).status(uba_id)
        report["credential"] = cred.as_dict()

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
        report["daily_loss"] = diag.to_dict()

        ks: dict[str, Any] = {}
        for scope in ("GLOBAL", f"UBA:{uba_id}"):
            row = session.scalar(
                select(KillSwitchEntity).where(KillSwitchEntity.scope_code == scope)
            )
            ks[scope] = {"active": bool(row.active) if row else False}
        report["kill_switch"] = ks

        pause_row = session.scalar(
            select(BrokerRecoveryAccountStateEntity).where(
                BrokerRecoveryAccountStateEntity.user_broker_account_id
                == uba_id
            )
        )
        report["recovery_account"] = {
            "trading_paused": bool(pause_row.trading_paused) if pause_row else False,
            "recovery_status": (
                pause_row.recovery_status if pause_row else None
            ),
            "last_error_code": (
                pause_row.last_error_code if pause_row else None
            ),
        }

        orders = list(
            session.scalars(
                select(TradingOrderEntity).where(
                    TradingOrderEntity.user_broker_account_id == uba_id
                )
            )
        )
        open_db = [
            o
            for o in orders
            if str(getattr(o, "status_code", "") or "").upper() in OPENISH
        ]
        report["db_orders_total"] = len(orders)
        report["db_open_order_count"] = len(open_db)
        report["db_open_order_ids"] = [
            int(getattr(o, "order_id")) for o in open_db
        ]

        sched = collect_scheduler_readiness(settings)
        report["scheduler"] = sched.to_dict()
        # CLI 프로세스의 in-process Recovery singleton은 API 실상태와 무관 → Dashboard 조회
        report["recovery_scheduler"] = {
            "source": "unavailable",
            "actual_state": "UNKNOWN",
            "desired_state": (
                "RUNNING"
                if bool(getattr(settings, "recovery_scheduler_enabled", True))
                else "STOPPED"
            ),
        }
        try:
            import httpx as _httpx

            headers = {
                "X-Admin-API-Key": str(settings.admin_api_key or "").strip()
            }
            if headers["X-Admin-API-Key"]:
                ov = _httpx.get(
                    "http://127.0.0.1:8000/api/v1/admin/operations-dashboard/overview",
                    headers=headers,
                    timeout=30.0,
                )
                if ov.status_code == 200:
                    ov_data = ov.json()
                    rec = ((ov_data.get("schedulers") or {}).get("recovery")) or {}
                    report["recovery_scheduler"] = {
                        **rec,
                        "source": "operations_dashboard_overview",
                    }
                    report["dashboard_overview_snapshot"] = {
                        "overall_status": ov_data.get("overall_status"),
                        "warning_codes": ov_data.get("warning_codes"),
                        "kill_switch": ov_data.get("kill_switch"),
                        "alerts": ov_data.get("alerts"),
                    }
                else:
                    report["warnings"].append(
                        f"DASHBOARD_OVERVIEW_HTTP_{ov.status_code}"
                    )
        except Exception as exc:  # noqa: BLE001
            report["warnings"].append(
                f"recovery_status_lookup:{type(exc).__name__}"
            )

        # Broker private 조회 (주문 생성/취소 금지 — accounts + order query만)
        order_client = None
        open_uuids: set[str] = set()
        try:
            accounts_info = asyncio.run(_broker_accounts(session, uba_id))
            report["broker_krw"] = accounts_info.get("broker_krw")
            report["broker_health"] = accounts_info.get("broker_health")
        except Exception as exc:  # noqa: BLE001
            report["broker_krw"] = None
            report["broker_health"] = f"CHECK_FAILED:{type(exc).__name__}"
            report["release_blockers"].append("BROKER_STATUS_CHECK_FAILED")
            report["warnings"].append(f"broker_accounts:{type(exc).__name__}")

        try:
            order_client = _build_order_query_client(session, uba_id)
            open_count, open_uuids = _list_broker_open_orders(order_client)
            report["broker_open_order_count"] = open_count
        except Exception as exc:  # noqa: BLE001
            report["broker_open_order_count"] = None
            report["release_blockers"].append("BROKER_OPEN_ORDERS_CHECK_FAILED")
            report["warnings"].append(f"broker_open_orders:{type(exc).__name__}")
            if order_client is not None and hasattr(order_client, "close"):
                try:
                    order_client.close()
                except Exception:  # noqa: BLE001
                    pass
                order_client = None

        lookup_client = order_client  # 동일 조회 클라이언트 재사용

        # Conflicts — 조회만
        conflicts = list(
            session.scalars(
                select(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.user_broker_account_id
                    == uba_id,
                    BrokerRecoveryConflictEntity.resolved_at.is_(None),
                )
                .order_by(
                    BrokerRecoveryConflictEntity.broker_recovery_conflict_id.desc()
                )
            )
        )
        by_uuid: dict[str, list[int]] = defaultdict(list)
        for c in conflicts:
            by_uuid[str(c.external_order_id)].append(
                int(c.broker_recovery_conflict_id)
            )

        classified = []
        for c in conflicts:
            remote_now = None
            uuid = str(c.external_order_id)
            status_u = str(c.external_status or "").upper()
            if (
                do_lookup
                and lookup_client is not None
                and status_u in {"WAIT", "WATCH", "OPEN"}
            ):
                remote_now = _lookup_remote_status_sync(lookup_client, uuid)
            dups = [
                i
                for i in by_uuid.get(uuid, [])
                if i != int(c.broker_recovery_conflict_id)
            ]
            # 동일 UUID 다건 중 최신 외는 duplicate 후보
            is_dup = bool(dups) and int(c.broker_recovery_conflict_id) != max(
                by_uuid.get(uuid, [int(c.broker_recovery_conflict_id)])
            )
            row = classify_conflict(
                conflict_id=int(c.broker_recovery_conflict_id),
                conflict_type=str(c.conflict_type),
                review_status=str(c.review_status),
                broker_code=str(c.broker_code),
                market_code=c.market_code,
                side_code=c.side_code,
                external_status=c.external_status,
                external_order_id_masked=c.external_order_id_masked
                or _mask_uuid(uuid),
                linked_internal_order_id=c.linked_internal_order_id,
                remaining_quantity=c.remaining_quantity,
                executed_quantity=c.executed_quantity,
                detected_at=c.detected_at,
                last_remote_checked_at=c.last_remote_checked_at,
                paper_account_id=c.paper_account_id,
                now=now,
                broker_open_uuids=open_uuids,
                db_open_order_ids=set(report["db_open_order_ids"]),
                external_order_id=uuid,
                remote_lookup_status=remote_now,
                duplicate_of_ids=dups if is_dup else None,
            )
            classified.append(row)

        if lookup_client is not None and hasattr(lookup_client, "close"):
            try:
                lookup_client.close()
            except Exception:  # noqa: BLE001
                pass

        summary = summarize_classifications(classified)
        report["conflicts"] = {
            "summary": summary,
            "items": [r.to_dict() for r in classified],
            "samples": {
                CLASS_CURRENT_ACTIVE: [
                    r.to_dict()
                    for r in classified
                    if r.classification == CLASS_CURRENT_ACTIVE
                ][:3],
                CLASS_STATE_MISMATCH: [
                    r.to_dict()
                    for r in classified
                    if r.classification == CLASS_STATE_MISMATCH
                ][:3],
                CLASS_HISTORICAL: [
                    r.to_dict()
                    for r in classified
                    if r.classification == CLASS_HISTORICAL
                ][:3],
                CLASS_TEST: [
                    r.to_dict()
                    for r in classified
                    if r.classification == CLASS_TEST
                ][:3],
                CLASS_DUP: [
                    r.to_dict()
                    for r in classified
                    if r.classification == CLASS_DUP
                ][:3],
                CLASS_UNKNOWN: [
                    r.to_dict()
                    for r in classified
                    if r.classification == CLASS_UNKNOWN
                ][:3],
            },
        }

        if summary["release_blocker_count"] > 0:
            report["release_blockers"].append("ACTIVE_RECOVERY_CONFLICT")
        if summary["counts"].get(CLASS_UNKNOWN, 0) > 0:
            report["release_blockers"].append("RECOVERY_CONFLICT_UNCLASSIFIED")
        if int(report.get("broker_open_order_count") or 0) > 0:
            report["release_blockers"].append("REMOTE_OPEN_ORDER_EXISTS")
        if int(report.get("db_open_order_count") or 0) > 0:
            report["release_blockers"].append("INTERNAL_OPEN_ORDER_EXISTS")
        if report["recovery_account"]["trading_paused"]:
            report["release_blockers"].append("ACCOUNT_TRADING_PAUSE_ACTIVE")

        # PHASE 1 gates
        cred_d = report.get("credential") or {}
        cred_status = str(cred_d.get("verification_status") or "").upper()
        report["credential_verification_status"] = cred_status
        if cred_status != "VERIFIED":
            report["release_blockers"].append(
                f"CREDENTIAL_NOT_VERIFIED:{cred_status or 'MISSING'}"
            )

        if report.get("upbit_use_mock"):
            report["release_blockers"].append("UPBIT_USE_MOCK_TRUE")
        if report.get("live_order_enabled"):
            report["warnings"].append("LIVE_ALREADY_ON")
        if report.get("live_armed"):
            report["warnings"].append("ARM_ALREADY_ON")
        if ks.get("GLOBAL", {}).get("active"):
            report["release_blockers"].append("GLOBAL_KILL_SWITCH")
        if ks.get(f"UBA:{uba_id}", {}).get("active"):
            report["release_blockers"].append("UBA_KILL_SWITCH")

        trading = report["scheduler"]
        if str(trading.get("trading_scheduler_actual_state") or "").upper() not in {
            "PAUSED",
            "PAUSE",
        }:
            report["warnings"].append(
                f"TRADING_SCHEDULER={trading.get('trading_scheduler_actual_state')}"
            )
        recovery_state = str(
            (report.get("recovery_scheduler") or {}).get("actual_state") or ""
        ).upper()
        recovery_source = str(
            (report.get("recovery_scheduler") or {}).get("source") or ""
        )
        if recovery_source.startswith("operations_dashboard") and recovery_state not in {
            "RUNNING",
            "COOLDOWN",
        }:
            report["release_blockers"].append(
                f"RECOVERY_SCHEDULER_{recovery_state or 'UNKNOWN'}"
            )
        elif recovery_source in {"unavailable", ""} or recovery_state == "UNKNOWN":
            report["warnings"].append(
                "RECOVERY_SCHEDULER_STATUS_UNCONFIRMED_VIA_DASHBOARD"
            )

        orderable = None
        if report.get("broker_krw"):
            orderable = _dec(report["broker_krw"].get("orderable_approx"))
            report["orderable_krw"] = str(orderable)
            report["locked_krw"] = report["broker_krw"].get("locked")
            report["total_krw_balance"] = report["broker_krw"].get("balance")
            if orderable < Decimal("5100"):
                report["release_blockers"].append("INSUFFICIENT_ORDERABLE_KRW")

        # Market 후보 (자동 확정 금지)
        allow = list(DEFAULT_ALLOWLIST)
        report["allowlist"] = allow
        try:
            report["market_candidates"] = fetch_market_quotes(
                allow, amount=amount, orderable_krw=orderable
            )
            # 참고용 추천만 — 확정 아님
            report["system_suggested_market_for_pipeline_only"] = {
                "market": "KRW-XRP",
                "auto_confirmed": False,
                "note": "시스템 추천일 뿐 자동 확정 아님. 투자 전략 추천이 아니라 주문 파이프라인 검증 목적.",
            }
        except Exception as exc:  # noqa: BLE001
            report["market_candidates"] = []
            report["release_blockers"].append(
                f"MARKET_QUOTE_FAILED:{type(exc).__name__}"
            )

        # Dry-run: 운영자 확정 없으면 실행 금지
        if not operator_market or not operator_price:
            report["dry_run_executed"] = False
            report["dry_run"] = {
                "dry_run_executed": False,
                "reason": "OPERATOR_MARKET_PRICE_REQUIRED",
                "dry_run_ready": None,
                "live_execution_ready": False,
                "note": "Market/Limit Price 운영자 확정 후에만 Dry-run 실행",
            }
        else:
            # 운영자 확정값이 있을 때만 서비스 dry_run (create_order 금지 경로)
            from stock_platform.trading.upbit_live_smoke_service import (
                UpbitLiveSmokeService,
            )

            svc = UpbitLiveSmokeService(session)
            dry = svc.dry_run(
                user_broker_account_id=uba_id,
                market=operator_market,
                side="BUY",
                amount=amount,
                limit_price=Decimal(operator_price),
                actor="STEP8_12A_PREFLIGHT",
            )
            report["dry_run_executed"] = True
            report["dry_run"] = dry if isinstance(dry, dict) else {"result": dry}
            report["adapter_create_order_calls"] = int(
                (report["dry_run"] or {}).get("adapter_create_order_calls") or 0
            )

        # 최종 판정
        blockers = list(dict.fromkeys(report["release_blockers"]))
        report["release_blockers"] = blockers
        conflict_ok = (
            summary["release_blocker_count"] == 0
            and summary["counts"].get(CLASS_UNKNOWN, 0) == 0
            and int(report.get("broker_open_order_count") or 0) == 0
            and int(report.get("db_open_order_count") or 0) == 0
            and not report["recovery_account"]["trading_paused"]
        )
        recovery_ok = recovery_state in {"RUNNING", "COOLDOWN"} or (
            recovery_source in {"unavailable", ""}
            or recovery_state == "UNKNOWN"
        )
        # Dashboard 미접속 시 Recovery는 warning만 — Account Pause 등은 별도 blocker
        ops_ok = (
            not report.get("upbit_use_mock")
            and not report.get("live_order_enabled")
            and not report.get("live_armed")
            and not ks.get("GLOBAL", {}).get("active")
            and not ks.get(f"UBA:{uba_id}", {}).get("active")
            and recovery_ok
            and orderable is not None
            and orderable >= Decimal("5100")
            and report.get("adapter_create_order_calls", 0) == 0
        )
        if blockers:
            report["final_status"] = "BLOCKED"
            report["step_8_12b_ready"] = False
        elif conflict_ok and ops_ok:
            report["final_status"] = "READY_FOR_OPERATOR_APPROVAL"
            report["step_8_12b_ready"] = True
            report["note"] = (
                "운영자 Market/Limit Price 확정 및 별도 승인 절차 후에만 "
                "STEP 8-12B 진행. 본 스크립트는 승인 문구·실주문 명령을 생성하지 않음."
            )
        else:
            report["final_status"] = "BLOCKED"
            report["step_8_12b_ready"] = False

        text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        print(text)
        if args.out:
            path = Path(args.out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return 0 if report["final_status"] == "READY_FOR_OPERATOR_APPROVAL" else 3
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
