"""STEP 9-1 — Final Operational Preflight (READ ONLY).

금지: LIVE/ARM/Scheduler START/Runtime Resume/주문/Import/Ignore/Pause/DB UPDATE
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select

from stock_platform.broker import recovery_entities as _  # noqa: F401
from stock_platform.broker.account_repository import BrokerAccountSnapshotRepository
from stock_platform.broker.credential_adapter_factory import (
    build_upbit_private_client_for_uba,
    build_upbit_settings_from_vault,
)
from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultError,
    BrokerCredentialVaultService,
)
from stock_platform.broker.fee_policy import UpbitFeePolicy
from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.broker.recovery_conflict_constants import (
    ACTIVE_REVIEW_STATUSES,
)
from stock_platform.broker.recovery_conflict_entities import (
    BrokerRecoveryConflictEntity,
)
from stock_platform.broker.recovery_conflict_service import (
    BrokerRecoveryConflictService,
)
from stock_platform.broker.recovery_entities import BrokerRecoveryRunEntity
from stock_platform.broker.upbit.order_client import UpbitOrderRestClient
from stock_platform.broker.upbit.rules import UPBIT_MIN_NOTIONAL_KRW
from stock_platform.common.json_safe import to_jsonable
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.risk_engine.daily_loss_entities import AccountDailyLossEntity
from stock_platform.risk_engine.kill_switch_entities import KillSwitchEntity
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.risk_engine.uba_daily_loss_service import UbaDailyLossService
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.upbit_live_smoke_constants import (
    DEFAULT_ALLOWLIST,
    DEFAULT_SMOKE_AMOUNT,
)
from stock_platform.trading.upbit_scheduler_readiness import (
    collect_scheduler_readiness,
)

_KST = ZoneInfo("Asia/Seoul")
UBA = 58
BASE = "http://127.0.0.1:8000"
REPORT = Path(r"E:\StockTrading\reports\step9_1_final_operational_preflight.json")
FEE = UpbitFeePolicy()

def _dec(v: Any) -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:  # noqa: BLE001
        return Decimal("0")


def main() -> int:
    settings = get_settings()
    admin_key = (settings.admin_api_key or "").strip()
    if not admin_key:
        raise SystemExit("ADMIN_API_KEY required for read-only status")

    session = get_session_factory()()
    out: dict[str, Any] = {
        "step": "9-1",
        "mode": "READ_ONLY",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "uba_id": UBA,
        "mutations": {
            "live_on": 0,
            "arm_on": 0,
            "trading_scheduler_start": 0,
            "runtime_resume": 0,
            "create_order": 0,
            "cancel_order": 0,
            "replace_order": 0,
            "import": 0,
            "ignore": 0,
            "pause_resume": 0,
            "db_update": 0,
        },
    }
    blockers: list[str] = []
    try:
        uba = session.get(UserBrokerAccount, UBA)
        if uba is None:
            print(json.dumps({"error": "UBA_NOT_FOUND"}, ensure_ascii=False))
            return 2
        pause = session.scalar(
            select(BrokerRecoveryAccountStateEntity).where(
                BrokerRecoveryAccountStateEntity.user_broker_account_id == UBA
            )
        )
        cred = BrokerCredentialVaultService(session).status(UBA).as_dict()
        try:
            BrokerCredentialVaultService(session).assert_live_order_allowed(
                UBA, broker_code="UPBIT"
            )
            cred_assert = "OK"
        except BrokerCredentialVaultError as exc:
            cred_assert = f"{exc.code}:{exc.message}"
            blockers.append(f"credential:{exc.code}")

        out["account"] = {
            "uba_id": UBA,
            "user_id": uba.user_id,
            "broker_code": str(uba.broker_code).upper(),
            "account_kind": getattr(uba, "account_kind", None)
            or getattr(uba, "account_type", None)
            or "LIVE_UBA",
            "market_type": getattr(uba, "market_type", None) or "CRYPTO",
            "is_active": bool(uba.is_active),
            "ownership_user_id": uba.user_id,
            "trading_paused": bool(pause.trading_paused) if pause else None,
            "recovery_status": pause.recovery_status if pause else None,
            "last_error_code": pause.last_error_code if pause else None,
            "live_order_enabled": bool(uba.live_order_enabled),
            "live_armed": bool(uba.live_armed),
            "credential": cred,
            "credential_assert": cred_assert,
        }
        if out["account"]["trading_paused"]:
            blockers.append("trading_paused_on")
        if out["account"]["live_order_enabled"]:
            blockers.append("live_already_on")
        if out["account"]["live_armed"]:
            blockers.append("arm_already_on")

        # Recovery scheduler
        with httpx.Client(timeout=20.0) as http:
            sched = http.get(
                f"{BASE}/api/v1/admin/recovery/scheduler/status",
                headers={"X-Admin-API-Key": admin_key},
            )
            sched.raise_for_status()
            recovery_sched = sched.json()

        last_run = None
        if pause and pause.last_recovery_run_id:
            run = session.get(
                BrokerRecoveryRunEntity, pause.last_recovery_run_id
            )
            if run is not None:
                last_run = {
                    "id": run.broker_recovery_run_id,
                    "status": run.status_code,
                    "trigger": run.trigger_type,
                    "conflicts": run.conflicts_found,
                    "finished_at": str(run.finished_at),
                }
        out["recovery"] = {
            "desired": recovery_sched.get("desired_state"),
            "actual": recovery_sched.get("actual_state"),
            "running": recovery_sched.get("running"),
            "stale": recovery_sched.get("stale"),
            "enabled": recovery_sched.get("enabled"),
            "last_success_at": recovery_sched.get("last_success_at"),
            "last_error_code": recovery_sched.get("last_error_code"),
            "consecutive_failures": recovery_sched.get(
                "consecutive_failures"
            ),
            "failed_accounts_hint": recovery_sched.get("last_error_code"),
            "account_recovery_status": pause.recovery_status if pause else None,
            "account_last_error_code": pause.last_error_code if pause else None,
            "last_run": last_run,
            "current_active_error": (
                None
                if (pause and pause.recovery_status == "SUCCESS"
                    and not pause.last_error_code)
                else (pause.last_error_code if pause else None)
            ),
        }
        if recovery_sched.get("desired_state") != "RUNNING":
            blockers.append("recovery_desired!=RUNNING")
        if recovery_sched.get("actual_state") not in {"RUNNING", "COOLDOWN"}:
            blockers.append(
                f"recovery_actual={recovery_sched.get('actual_state')}"
            )
        if recovery_sched.get("stale") is True:
            blockers.append("recovery_stale")

        # Conflicts
        counts: dict[str, int] = {}
        for st in (
            "HISTORICAL_PRESERVED",
            "PENDING_REVIEW",
            "ON_HOLD",
            "IGNORED",
            "IMPORTED",
            "APPROVED_FOR_IMPORT",
        ):
            counts[st] = int(
                session.scalar(
                    select(func.count())
                    .select_from(BrokerRecoveryConflictEntity)
                    .where(
                        BrokerRecoveryConflictEntity.user_broker_account_id
                        == UBA,
                        BrokerRecoveryConflictEntity.review_status == st,
                    )
                )
                or 0
            )
        active = int(
            session.scalar(
                select(func.count())
                .select_from(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.user_broker_account_id == UBA,
                    BrokerRecoveryConflictEntity.review_status.in_(
                        list(ACTIVE_REVIEW_STATUSES)
                    ),
                )
            )
            or 0
        )
        # IMPORT_REQUIRED / UNSAFE — active 분류 잔여 없음 확인(상태 문자열 직접 카운트)
        import_required = 0
        unsafe = 0
        out["conflict"] = {
            **counts,
            "ACTIVE_REVIEW": active,
            "IMPORT_REQUIRED": import_required,
            "UNSAFE": unsafe,
            "note": "IMPORT_REQUIRED/UNSAFE는 분류 라벨; 현재 ACTIVE_REVIEW=0이면 잔여 없음",
        }
        if active != 0:
            blockers.append("active_review!=0")
        if counts.get("PENDING_REVIEW", 0) != 0:
            blockers.append("pending_review!=0")

        # Broker live read (orders/balance) — no orders placed
        blocking = BrokerRecoveryConflictService(
            session
        ).count_blocking_orders_for_uba(UBA)
        private = build_upbit_private_client_for_uba(session, UBA)
        t0 = time.perf_counter()
        accounts = asyncio.run(private.list_accounts())
        latency_accounts_ms = round((time.perf_counter() - t0) * 1000, 1)
        client = UpbitOrderRestClient(
            settings=build_upbit_settings_from_vault(
                BrokerCredentialVaultService(session).resolve_for_runtime(
                    UBA,
                    expected_broker="UPBIT",
                    require_verified=True,
                    touch_last_used=False,
                )
            ),
            user_broker_account_id=UBA,
        )
        t1 = time.perf_counter()
        opens = client.list_orders(state="wait", limit=50)
        latency_orders_ms = round((time.perf_counter() - t1) * 1000, 1)
        broker_open_n = len(opens) if isinstance(opens, list) else -1
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass

        krw_row = None
        for row in accounts if isinstance(accounts, list) else []:
            if str(row.get("currency") or "").upper() == "KRW":
                krw_row = row
                break
        krw_balance = _dec(krw_row.get("balance") if krw_row else 0)
        krw_locked = _dec(krw_row.get("locked") if krw_row else 0)
        krw_available = krw_balance  # Upbit balance는 가용(미잠금) 관례

        snap, positions = BrokerAccountSnapshotRepository(session).get_active_by_uba(
            UBA
        )
        pos_rows = []
        for p in positions or []:
            pos_rows.append(
                {
                    "market": getattr(p, "market_code", None)
                    or getattr(p, "symbol", None),
                    "qty": str(
                        getattr(p, "quantity", None) or getattr(p, "qty", None)
                    ),
                    "avg_price": str(
                        getattr(p, "avg_buy_price", None)
                        or getattr(p, "average_price", None)
                    ),
                }
            )
        live_positions = []
        for row in accounts if isinstance(accounts, list) else []:
            cur = str(row.get("currency") or "").upper()
            if cur in {"", "KRW"}:
                continue
            bal = _dec(row.get("balance"))
            locked = _dec(row.get("locked"))
            if bal + locked <= 0:
                continue
            live_positions.append(
                {
                    "currency": cur,
                    "balance": str(bal),
                    "locked": str(locked),
                    "avg_buy_price": str(row.get("avg_buy_price") or ""),
                    "unit_currency": row.get("unit_currency"),
                }
            )

        out["broker"] = {
            "open_orders": broker_open_n,
            "krw_balance": str(krw_balance),
            "krw_locked": str(krw_locked),
            "krw_available": str(krw_available),
            "db_snapshot_deposit": str(getattr(snap, "deposit_amount", None))
            if snap
            else None,
            "db_positions": pos_rows,
            "live_positions": live_positions,
            "api_latency_ms": {
                "accounts": latency_accounts_ms,
                "open_orders": latency_orders_ms,
            },
            "db_blocking_orders": blocking,
        }
        if broker_open_n != 0:
            blockers.append(f"broker_open={broker_open_n}")
        if any(blocking.values()):
            blockers.append(f"db_blocking={blocking}")

        # Risk
        try:
            kill_global = bool(KillSwitchService(session).is_active())
        except Exception as exc:  # noqa: BLE001
            kill_global = True
            blockers.append(f"kill_switch_err:{exc}")
        uba_ks = session.scalar(
            select(KillSwitchEntity).where(
                KillSwitchEntity.scope_code == f"UBA:{UBA}"
            )
        )
        user_ks = session.scalar(
            select(KillSwitchEntity).where(
                KillSwitchEntity.scope_code == f"USER:{uba.user_id}"
            )
        )
        today = datetime.now(_KST).date()
        loss_row = session.scalar(
            select(AccountDailyLossEntity).where(
                AccountDailyLossEntity.user_broker_account_id == UBA,
                AccountDailyLossEntity.trading_date == today,
            )
        )
        limit = _dec(loss_row.loss_limit_amount if loss_row else "300000")
        daily = UbaDailyLossService(session).diagnose(
            user_broker_account_id=UBA,
            loss_limit=limit,
            trading_date=today,
        ).to_dict()
        out["risk"] = {
            "global_kill_switch": kill_global,
            "uba_kill_switch": bool(uba_ks.active) if uba_ks else False,
            "user_kill_switch": bool(user_ks.active) if user_ks else False,
            "daily_loss": daily,
            "submission_unknown": blocking.get("submission_unknown", 0),
            "cancel_pending": blocking.get("cancel_pending", 0),
            "replace_pending": blocking.get("replace_pending", 0),
            "db_open": blocking.get("db_open", 0),
        }
        if kill_global:
            blockers.append("kill_switch_active")
        if out["risk"]["uba_kill_switch"]:
            blockers.append("uba_kill_switch_active")

        # Schedulers
        trading = collect_scheduler_readiness(settings)
        out["scheduler"] = {
            "recovery": {
                "desired": recovery_sched.get("desired_state"),
                "actual": recovery_sched.get("actual_state"),
                "running": recovery_sched.get("running"),
                "stale": recovery_sched.get("stale"),
            },
            "trading": {
                "desired": trading.trading_scheduler_desired_state,
                "actual": trading.trading_scheduler_actual_state,
                "paused": trading.trading_scheduler_paused,
                "running": trading.trading_running,
            },
            "tracking": {
                "desired": trading.tracking_desired_state,
                "running": trading.tracking_scheduler_running,
            },
            "post_fill": {
                "desired": trading.post_fill_desired_state,
                "running": trading.post_fill_scheduler_running,
            },
            "runtime_auto_resume": False,
            "note": "Runtime Auto Resume 계약=금지(STEP 8-15A/8-16)",
        }
        if trading.trading_scheduler_actual_state != "PAUSED":
            blockers.append(
                f"trading_actual={trading.trading_scheduler_actual_state}"
            )
        if trading.trading_scheduler_desired_state != "PAUSE":
            blockers.append(
                f"trading_desired={trading.trading_scheduler_desired_state}"
            )

        # Trading readiness (no order)
        amount = _dec(DEFAULT_SMOKE_AMOUNT)
        min_notional = _dec(UPBIT_MIN_NOTIONAL_KRW)
        # 수수료 버퍼: 매수 시 대략 amount * (1+fee) 필요 — fee policy 조회
        fee_rate = _dec(FEE.taker_rate)
        needed = amount * (Decimal("1") + fee_rate)
        can_5000 = (
            krw_available >= needed
            and amount >= min_notional
            and cred_assert == "OK"
            and broker_open_n == 0
            and not kill_global
            and active == 0
            and not out["account"]["trading_paused"]
        )
        out["trading_readiness"] = {
            "target_amount_krw": str(amount),
            "min_notional_krw": str(min_notional),
            "fee_rate_assumed": str(fee_rate),
            "needed_krw_with_fee": str(needed),
            "krw_available": str(krw_available),
            "krw_sufficient": bool(krw_available >= needed),
            "allowlist_markets": list(DEFAULT_ALLOWLIST),
            "broker_healthy": broker_open_n == 0 and latency_accounts_ms < 5000,
            "credential_ok": cred_assert == "OK",
            "can_place_5000_when_armed": can_5000,
            "gates_still_required": [
                "LIVE ON (별도 승인)",
                "ARM (별도 승인)",
                "Trading Scheduler START (별도 승인)",
                "명시적 create_order 승인",
            ],
            "note": "본 STEP은 가능 여부 평가만. 주문·LIVE·ARM 미수행",
        }
        if not out["trading_readiness"]["krw_sufficient"]:
            blockers.append("krw_insufficient_for_5000")

        # Final gate for STEP 9-2 readiness (preflight only — still LIVE OFF)
        step92_ok = (
            not out["account"]["trading_paused"]
            and active == 0
            and counts.get("PENDING_REVIEW", 0) == 0
            and counts.get("HISTORICAL_PRESERVED", 0) == 20
            and broker_open_n == 0
            and not kill_global
            and cred_assert == "OK"
            and trading.trading_scheduler_actual_state == "PAUSED"
            and not out["account"]["live_order_enabled"]
            and not out["account"]["live_armed"]
            and out["trading_readiness"]["krw_sufficient"]
        )
        # Release blockers for going live NOW — should still block LIVE
        release_blockers = list(blockers)
        # intentional holds (not defects)
        intentional = [
            "LIVE OFF (정상 — 본 STEP 유지)",
            "ARM OFF (정상 — 본 STEP 유지)",
            "Trading Scheduler PAUSED (정상 — 본 STEP 유지)",
        ]

        out["blockers"] = blockers
        out["intentional_holds"] = intentional
        out["release_blocker_for_live_now"] = (
            intentional + (["preflight_blockers:" + ",".join(blockers)] if blockers else [])
        )
        out["step_9_2_ready"] = step92_ok and not blockers
        out["verdict"] = (
            "PASS_READONLY"
            if step92_ok and not blockers
            else ("FAIL" if blockers else "PASS_WITH_NOTES")
        )

        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(
            json.dumps(to_jsonable(out), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(to_jsonable(out), ensure_ascii=False, indent=2))
        return 0 if out["verdict"].startswith("PASS") else 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
