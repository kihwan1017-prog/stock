"""STEP 8-11 — 통합 운영 모니터링 Dashboard 집계 (조회 전용).

기존 Service/Repository/Readiness를 재사용한다.
LIVE ON / ARM / 주문 / Scheduler Resume / Kill Switch 변경 금지.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from stock_platform.auth.models import AuthUser
from stock_platform.broker.account_models import BrokerPositionSnapshotEntity
from stock_platform.broker.account_repository import BrokerAccountSnapshotRepository
from stock_platform.broker.credential_vault_service import BrokerCredentialVaultService
from stock_platform.common.settings import get_settings
from stock_platform.operation.db_pool_monitor import measure_db_latency_ms
from stock_platform.operation.ops_monitoring.masking import (
    mask_broker_uuid,
    mask_login_id,
    mask_notification_body,
    redact_mapping,
)
from stock_platform.operation.ops_monitoring.status import (
    compute_overall_status,
    daily_loss_usage_status,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.kill_switch_entities import KillSwitchEntity
from stock_platform.risk_engine.kill_switch_models import KillSwitchStatus
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.risk_engine.uba_daily_loss_service import UbaDailyLossService
from stock_platform.risk_engine.user_risk_service import UserRiskSettingService
from stock_platform.trading.account_identity import uba_kill_switch_scope
from stock_platform.trading.account_masking import mask_account_number
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.upbit_scheduler_readiness import (
    collect_scheduler_readiness,
)


_KST = ZoneInfo("Asia/Seoul")
_ZERO = Decimal("0")
_OPEN_STATUSES = (
    "CREATED",
    "PENDING",
    "SENT",
    "ACCEPTED",
    "OPEN",
    "PARTIALLY_FILLED",
    "PARTIAL",
    "CANCEL_REQUESTED",
    "CANCEL_PENDING",
    "REPLACE_REQUESTED",
    "UNKNOWN",
    "SUBMISSION_UNKNOWN",
)
_MANUAL_REVIEW_STATUSES = {
    "UNKNOWN",
    "SUBMISSION_UNKNOWN",
    "CANCEL_PENDING",
    "CANCEL_FAILED",
}
_ORDER_SORT_ALLOWLIST = {
    "created_at",
    "updated_at",
    "order_id",
    "status_code",
}

# 동일 프로세스 새로고침 사이클에서 Broker 잔고 중복 호출 방지
_BALANCE_CACHE: dict[int, tuple[float, dict[str, Any]]] = {}


class OpsMonitoringDashboardService:
    """Admin Operations Dashboard — Read-only facade."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._settings = get_settings()

    # ------------------------------------------------------------------ overview
    def overview(self) -> dict[str, Any]:
        checked_at = datetime.now(timezone.utc)
        db_status, latency_ms, db_err = measure_db_latency_ms()
        database = {
            "status": "HEALTHY" if db_status == "UP" else "ERROR",
            "latency_ms": latency_ms,
            "reason_code": None if db_status == "UP" else "DB_UNHEALTHY",
            "detail": db_err,
        }

        sched = self._scheduler_bundle()
        kill = KillSwitchService(self._session).get_state()
        global_active = kill.status == KillSwitchStatus.ACTIVE
        active_account_ks = self._active_uba_kill_count()

        brokers = self._broker_overview()
        runtime = self._runtime_counts()
        alerts = self._alert_counts()

        errors: list[str] = []
        warnings: list[str] = []
        if database["status"] != "HEALTHY":
            errors.append("DATABASE_UNHEALTHY")
        if global_active:
            errors.append("KILL_SWITCH_GLOBAL")
        if active_account_ks > 0:
            errors.append("KILL_SWITCH_UBA")
        for code, row in brokers.items():
            if row.get("status") == "ERROR":
                errors.append(f"BROKER_{code}_ERROR")
            elif row.get("status") in {"UNHEALTHY", "STALE"}:
                warnings.append(f"BROKER_{code}_{row['status']}")
        trading = sched.get("trading") or {}
        if trading.get("running") is True and trading.get("desired_state") == "PAUSE":
            errors.append("TRADING_SCHEDULER_UNEXPECTED_RUNNING")
        recovery = sched.get("recovery") or {}
        recovery_actual = str(recovery.get("actual_state") or "").upper()
        recovery_desired = str(recovery.get("desired_state") or "").upper()
        if recovery_desired == "RUNNING" and recovery_actual in {
            "STOPPED",
            "ERROR",
            "UNKNOWN",
        }:
            if recovery_actual == "ERROR":
                errors.append("RECOVERY_SCHEDULER_ERROR")
            else:
                warnings.append("RECOVERY_SCHEDULER_STOPPED")
        # COOLDOWN / DISABLED 는 정상 운영 상태 — STOPPED 경고 금지
        if int(alerts.get("manual_review") or 0) > 0:
            errors.append("MANUAL_REVIEW_REQUIRED")
        if int(alerts.get("critical") or 0) > 0:
            errors.append("CRITICAL_ALERTS")
        if int(runtime.get("error_count") or 0) > 0:
            warnings.append("RUNTIME_ERRORS")

        overall = compute_overall_status(
            {"errors": errors, "warnings": warnings}
        )
        return {
            "overall_status": overall,
            "checked_at": checked_at.isoformat(),
            "error_codes": errors,
            "warning_codes": warnings,
            "database": database,
            "api": {"status": "HEALTHY"},
            "brokers": brokers,
            "schedulers": sched,
            "runtime": runtime,
            "kill_switch": {
                "global_active": global_active,
                "active_account_count": active_account_ks,
            },
            "alerts": alerts,
        }

    # ------------------------------------------------------------------ accounts
    def accounts(self, *, include_broker_balances: bool = True) -> dict[str, Any]:
        checked_at = datetime.now(timezone.utc)
        stale_sec = int(
            getattr(self._settings, "ops_dashboard_readiness_stale_seconds", 30)
        )
        ubas = list(
            self._session.scalars(
                select(UserBrokerAccount).order_by(
                    UserBrokerAccount.user_broker_account_id.asc()
                )
            )
        )
        user_ids = {int(u.user_id) for u in ubas}
        users = {
            int(row.user_id): row
            for row in self._session.scalars(
                select(AuthUser).where(AuthUser.user_id.in_(user_ids or [-1]))
            )
        }
        sched = self._scheduler_bundle()
        kill_global = (
            KillSwitchService(self._session).get_state().status
            == KillSwitchStatus.ACTIVE
        )
        vault = BrokerCredentialVaultService(self._session)
        loss_svc = UbaDailyLossService(self._session)
        snaps = BrokerAccountSnapshotRepository(self._session)
        today = datetime.now(_KST).date()
        day_start = datetime(
            today.year, today.month, today.day, tzinfo=_KST
        ).astimezone(timezone.utc)

        # 주문 집계 batch
        open_counts = self._count_orders_by_uba(
            statuses=_OPEN_STATUSES, since=None
        )
        today_counts = self._count_orders_by_uba(statuses=None, since=day_start)

        rows: list[dict[str, Any]] = []
        for uba in ubas:
            uba_id = int(uba.user_broker_account_id)
            owner = users.get(int(uba.user_id))
            blockers: list[str] = []
            warnings: list[str] = []
            cred_status = "UNKNOWN"
            try:
                cred = vault.status(uba_id)
                cred_status = str(cred.verification_status or "UNKNOWN")
                if cred_status != "VERIFIED":
                    blockers.append(f"CREDENTIAL_{cred_status}")
            except Exception as exc:  # noqa: BLE001
                cred_status = "ERROR"
                blockers.append(f"CREDENTIAL_LOOKUP_FAILED:{type(exc).__name__}")

            ks_active = kill_global or self._uba_kill_active(uba_id)
            if ks_active:
                blockers.append("KILL_SWITCH_ACTIVE")

            open_cnt = int(open_counts.get(uba_id, 0))
            today_cnt = int(today_counts.get(uba_id, 0))
            if open_cnt > 0:
                blockers.append("DB_OPEN_ORDERS")

            # Daily loss — diagnose only (baseline 쓰기 금지)
            loss_limit = Decimal("300000")
            daily = {
                "current_daily_pnl": None,
                "current_daily_loss": None,
                "max_daily_loss_limit": None,
                "remaining_daily_loss_capacity": None,
                "status": "UNKNOWN",
                "reason_code": None,
            }
            try:
                try:
                    policy = UserRiskSettingService(self._session).resolve(
                        user_id=int(uba.user_id),
                        user_broker_account_id=uba_id,
                    )
                    limit_val = getattr(policy, "daily_max_loss_amount", None)
                    if limit_val is not None and Decimal(str(limit_val)) > 0:
                        loss_limit = Decimal(str(limit_val))
                except Exception:  # noqa: BLE001
                    pass
                breakdown = loss_svc.diagnose(
                    user_broker_account_id=uba_id,
                    loss_limit=loss_limit,
                    trading_date=today,
                )
                daily = {
                    "current_daily_pnl": str(breakdown.current_daily_pnl),
                    "current_daily_loss": str(breakdown.current_daily_loss),
                    "max_daily_loss_limit": str(breakdown.max_daily_loss_limit),
                    "remaining_daily_loss_capacity": str(
                        breakdown.remaining_daily_loss_capacity
                    ),
                    "status": daily_loss_usage_status(
                        current_loss=breakdown.current_daily_loss,
                        limit_amount=breakdown.max_daily_loss_limit,
                    ),
                    "reason_code": None,
                }
                if breakdown.current_daily_loss >= breakdown.max_daily_loss_limit:
                    blockers.append("DAILY_LOSS_LIMIT")
                elif breakdown.current_daily_loss >= (
                    breakdown.max_daily_loss_limit * Decimal("0.70")
                ):
                    warnings.append("DAILY_LOSS_WARNING")
            except Exception as exc:  # noqa: BLE001
                daily["reason_code"] = f"DAILY_LOSS_ERROR:{type(exc).__name__}"
                warnings.append("DAILY_LOSS_UNAVAILABLE")

            balance = {
                "orderable_krw": None,
                "locked_krw": None,
                "total_krw_balance": None,
                "status": "NOT_APPLICABLE",
                "reason_code": None,
            }
            broker_open = {
                "count": None,
                "status": "NOT_APPLICABLE",
                "reason_code": None,
            }
            broker_health = {
                "status": "UNKNOWN",
                "reason_code": None,
            }
            if str(uba.broker_code).upper() == "UPBIT" and include_broker_balances:
                balance, broker_open, broker_health = self._upbit_balance_safe(
                    uba_id
                )
                if balance.get("status") == "ERROR":
                    warnings.append("BROKER_BALANCE_ERROR")
                elif balance.get("status") == "OK":
                    try:
                        orderable = Decimal(str(balance["orderable_krw"]))
                        if orderable < Decimal("5000"):
                            warnings.append("INSUFFICIENT_KRW_ORDERABLE")
                            blockers.append("INSUFFICIENT_KRW_ORDERABLE")
                    except Exception:  # noqa: BLE001
                        pass
                if broker_open.get("count"):
                    blockers.append("BROKER_OPEN_ORDERS")
            elif str(uba.broker_code).upper() == "KIWOOM":
                broker_health = {"status": "NOT_PROBED", "reason_code": None}
                # snapshot 예수금만 참고 (0 위장 금지)
                account, _ = snaps.get_active_by_uba(uba_id)
                if account is None:
                    balance = {
                        "orderable_krw": None,
                        "locked_krw": None,
                        "total_krw_balance": None,
                        "status": "UNKNOWN",
                        "reason_code": "SNAPSHOT_MISSING",
                    }
                else:
                    balance = {
                        "orderable_krw": None,
                        "locked_krw": None,
                        "total_krw_balance": str(account.deposit_amount),
                        "status": "SNAPSHOT_ONLY",
                        "reason_code": None,
                    }

            live_on = bool(uba.live_order_enabled)
            armed = bool(uba.live_armed)
            arm_exp = (
                uba.arm_expires_at.isoformat() if uba.arm_expires_at else None
            )
            if live_on:
                warnings.append("LIVE_ON")
            if armed:
                warnings.append("ARMED")

            # dry_run / live_execution — 로컬 게이트 (실주문·ARM 호출 없음)
            dry_run_ready = len(blockers) == 0 and not kill_global
            live_blockers = list(blockers)
            if not live_on:
                live_blockers.append("LIVE_OFF")
            if not armed:
                live_blockers.append("DISARMED")
            live_execution_ready = (
                len(blockers) == 0 and live_on and armed and not kill_global
            )

            rows.append(
                {
                    "user_broker_account_id": uba_id,
                    "owner_user_id": int(uba.user_id),
                    "owner_login_id_masked": mask_login_id(
                        owner.username if owner else None
                    ),
                    "account_alias": getattr(uba, "account_alias", None)
                    or getattr(uba, "display_name", None),
                    "broker_code": str(uba.broker_code).upper(),
                    "account_kind": getattr(uba, "account_kind", None)
                    or getattr(uba, "account_type_code", None),
                    "active": bool(uba.is_active),
                    "masked_account_ref": mask_account_number(
                        getattr(uba, "account_number", None)
                    ),
                    "credential_status": cred_status,
                    "broker_health": broker_health,
                    "live_order_enabled": live_on,
                    "live_armed": armed,
                    "arm_expires_at": arm_exp,
                    # arm_token 절대 미포함
                    "dry_run_ready": dry_run_ready,
                    "live_execution_ready": live_execution_ready,
                    "blockers": blockers,
                    "warnings": warnings,
                    "live_blockers": live_blockers,
                    **{k: daily[k] for k in daily},
                    "open_order_count": open_cnt,
                    "broker_open_order_count": broker_open.get("count"),
                    "broker_open_order_status": broker_open.get("status"),
                    "today_order_count": today_cnt,
                    "kill_switch_active": ks_active,
                    "runtime_state": runtime_state_for_uba(self._session, uba_id),
                    "trading_scheduler_state": (sched.get("trading") or {}).get(
                        "actual_state"
                    ),
                    "tracking_scheduler_state": (sched.get("tracking") or {}).get(
                        "actual_state"
                    ),
                    "post_fill_scheduler_state": (
                        sched.get("post_fill") or {}
                    ).get("actual_state"),
                    "recovery_scheduler_state": (
                        sched.get("recovery") or {}
                    ).get("actual_state"),
                    "orderable_krw": balance.get("orderable_krw"),
                    "locked_krw": balance.get("locked_krw"),
                    "total_krw_balance": balance.get("total_krw_balance"),
                    "balance_status": balance.get("status"),
                    "balance_reason_code": balance.get("reason_code"),
                    "checked_at": checked_at.isoformat(),
                    "stale": False,
                    "stale_after_seconds": stale_sec,
                }
            )

        return {
            "checked_at": checked_at.isoformat(),
            "count": len(rows),
            "accounts": rows,
        }

    # ------------------------------------------------------------------ schedulers
    def schedulers(self) -> dict[str, Any]:
        checked_at = datetime.now(timezone.utc)
        items: list[dict[str, Any]] = []
        bundle = self._scheduler_bundle()
        for name, row in bundle.items():
            items.append(
                {
                    "scheduler_name": name,
                    "scope": row.get("scope", "SYSTEM"),
                    "desired_state": row.get("desired_state"),
                    "actual_state": row.get("actual_state"),
                    "running": row.get("running"),
                    "enabled": row.get("enabled"),
                    "last_started_at": row.get("last_started_at"),
                    "last_finished_at": row.get("last_finished_at"),
                    "last_success_at": row.get("last_success_at"),
                    "last_failed_at": row.get("last_failed_at"),
                    "next_run_at": row.get("next_run_at"),
                    "consecutive_failures": row.get("consecutive_failures"),
                    "last_error_code": row.get("last_error_code"),
                    "snapshot_checked_at": checked_at.isoformat(),
                    "stale": bool(row.get("stale", False)),
                }
            )
        # 추가 존재하는 스케줄러만 probe (없으면 임의 생성 금지)
        for probe in (
            self._probe_market_session_scheduler,
            self._probe_recovery_scheduler_detail,
        ):
            extra = probe()
            if extra is not None:
                # 중복 이름 스킵
                if any(i["scheduler_name"] == extra["scheduler_name"] for i in items):
                    continue
                items.append(extra)
        return {"checked_at": checked_at.isoformat(), "schedulers": items}

    # ------------------------------------------------------------------ runtimes
    def runtimes(self) -> dict[str, Any]:
        checked_at = datetime.now(timezone.utc)
        stale_sec = int(
            getattr(self._settings, "ops_dashboard_runtime_stale_seconds", 60)
        )
        rows: list[dict[str, Any]] = []
        try:
            from stock_platform.strategy_deployment.runtime_manager import (
                dynamic_strategy_runtime_manager,
            )

            entries = dynamic_strategy_runtime_manager.list_entries()
            for entry in entries:
                if hasattr(entry, "__dict__") and not isinstance(entry, dict):
                    data = {
                        k: getattr(entry, k, None)
                        for k in (
                            "scope",
                            "scope_key",
                            "user_id",
                            "account_id",
                            "user_broker_account_id",
                            "broker_code",
                            "market_type",
                            "strategy_id",
                            "strategy_version",
                            "state",
                            "started_at",
                            "paused_at",
                            "last_heartbeat_at",
                            "last_error_code",
                        )
                    }
                else:
                    data = dict(entry)
                hb = data.get("last_heartbeat_at")
                stale = False
                if isinstance(hb, datetime):
                    age = (checked_at - hb.astimezone(timezone.utc)).total_seconds()
                    stale = age > stale_sec
                rows.append(
                    {
                        "scope": data.get("scope") or data.get("scope_key"),
                        "user_id": data.get("user_id"),
                        "account_id": data.get("account_id")
                        or data.get("user_broker_account_id"),
                        "broker_code": data.get("broker_code"),
                        "market_type": data.get("market_type"),
                        "strategy_id": data.get("strategy_id"),
                        "strategy_version": data.get("strategy_version"),
                        "state": data.get("state"),
                        "started_at": _iso(data.get("started_at")),
                        "paused_at": _iso(data.get("paused_at")),
                        "last_heartbeat_at": _iso(data.get("last_heartbeat_at")),
                        "last_error_code": data.get("last_error_code"),
                        "stale": stale,
                        "stale_after_seconds": stale_sec,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            return {
                "checked_at": checked_at.isoformat(),
                "runtimes": [],
                "status": "ERROR",
                "reason_code": f"RUNTIME_REGISTRY_ERROR:{type(exc).__name__}",
            }
        return {
            "checked_at": checked_at.isoformat(),
            "runtimes": rows,
            "status": "OK",
        }

    # ------------------------------------------------------------------ risk
    def risk(self) -> dict[str, Any]:
        accounts = self.accounts(include_broker_balances=False)
        risk_rows: list[dict[str, Any]] = []
        for row in accounts["accounts"]:
            uba_id = int(row["user_broker_account_id"])
            max_order = None
            max_open = None
            daily_limit = None
            try:
                policy = UserRiskSettingService(self._session).resolve(
                    user_id=int(row["owner_user_id"]),
                    user_broker_account_id=uba_id,
                )
                max_order = _dec_str(getattr(policy, "max_order_amount", None))
                max_open = getattr(policy, "max_open_orders", None)
                daily_limit = getattr(policy, "daily_order_limit", None)
            except Exception:  # noqa: BLE001
                pass
            risk_rows.append(
                {
                    "user_broker_account_id": uba_id,
                    "broker_code": row["broker_code"],
                    "current_daily_pnl": row.get("current_daily_pnl"),
                    "current_daily_loss": row.get("current_daily_loss"),
                    "max_daily_loss_limit": row.get("max_daily_loss_limit"),
                    "remaining_daily_loss_capacity": row.get(
                        "remaining_daily_loss_capacity"
                    ),
                    "risk_status": row.get("status"),
                    "max_order_amount": max_order,
                    "max_open_orders": max_open,
                    "daily_order_limit": daily_limit,
                    "current_open_orders": row.get("open_order_count"),
                    "today_orders": row.get("today_order_count"),
                    "kill_switch_active": row.get("kill_switch_active"),
                    "checked_at": row.get("checked_at"),
                }
            )
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "accounts": risk_rows,
        }

    # ------------------------------------------------------------------ orders
    def orders(
        self,
        *,
        status: str | None = None,
        broker_code: str | None = None,
        user_broker_account_id: int | None = None,
        market: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
        sort: str = "created_at",
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        if date_from and date_to and (date_to - date_from) > timedelta(days=31):
            raise ValueError("date range max 31 days")
        sort_col = sort if sort in _ORDER_SORT_ALLOWLIST else "created_at"

        filters = []
        if status:
            filters.append(
                TradingOrderEntity.status_code == status.strip().upper()
            )
        if broker_code:
            filters.append(
                func.upper(TradingOrderEntity.broker_code)
                == broker_code.strip().upper()
            )
        if user_broker_account_id is not None:
            filters.append(
                TradingOrderEntity.user_broker_account_id
                == int(user_broker_account_id)
            )
        if market:
            # symbol / market 필드 이름 호환
            market_u = market.strip().upper()
            if hasattr(TradingOrderEntity, "symbol"):
                filters.append(
                    func.upper(TradingOrderEntity.symbol) == market_u
                )
        if date_from:
            filters.append(TradingOrderEntity.created_at >= date_from)
        if date_to:
            filters.append(TradingOrderEntity.created_at <= date_to)

        stmt = select(TradingOrderEntity)
        if filters:
            stmt = stmt.where(and_(*filters))
        order_attr = getattr(TradingOrderEntity, sort_col)
        stmt = stmt.order_by(order_attr.desc()).offset(offset).limit(limit)
        rows = list(self._session.scalars(stmt))

        # post-fill status batch
        post_fill_map = self._post_fill_status_map(
            [int(r.order_id) for r in rows if getattr(r, "order_id", None)]
        )

        items = []
        for o in rows:
            oid = int(o.order_id)
            st = str(getattr(o, "status_code", "") or "").upper()
            filled = getattr(o, "filled_quantity", None)
            qty = getattr(o, "quantity", None) or getattr(
                o, "requested_quantity", None
            )
            remaining = None
            try:
                if qty is not None and filled is not None:
                    remaining = str(Decimal(str(qty)) - Decimal(str(filled)))
            except Exception:  # noqa: BLE001
                remaining = None
            items.append(
                {
                    "created_at": _iso(o.created_at),
                    "updated_at": _iso(getattr(o, "updated_at", None)),
                    "order_id": oid,
                    "run_id": getattr(o, "run_id", None),
                    "identifier": getattr(o, "client_order_id", None)
                    or getattr(o, "idempotency_key", None),
                    "user_broker_account_id": getattr(
                        o, "user_broker_account_id", None
                    ),
                    "broker_code": getattr(o, "broker_code", None),
                    "market": getattr(o, "symbol", None),
                    "side": getattr(o, "side_code", None),
                    "order_type": getattr(o, "order_type_code", None),
                    "requested_quantity": _dec_str(qty),
                    "requested_price": _dec_str(
                        getattr(o, "limit_price", None)
                    ),
                    "requested_amount": _dec_str(
                        getattr(o, "requested_amount", None)
                    ),
                    "internal_status": st,
                    "broker_status": getattr(o, "broker_status_code", None),
                    "broker_uuid_masked": mask_broker_uuid(
                        getattr(o, "broker_order_id", None)
                        or getattr(o, "exchange_order_id", None)
                    ),
                    "filled_quantity": _dec_str(filled),
                    "average_fill_price": _dec_str(
                        getattr(o, "average_fill_price", None)
                    ),
                    "remaining_quantity": remaining,
                    "post_fill_status": post_fill_map.get(oid),
                    "manual_review_required": st in _MANUAL_REVIEW_STATUSES,
                }
            )
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "limit": limit,
            "offset": offset,
            "count": len(items),
            "orders": items,
        }

    # ------------------------------------------------------------------ positions
    def positions(self) -> dict[str, Any]:
        checked_at = datetime.now(timezone.utc)
        stale_sec = int(
            getattr(self._settings, "ops_dashboard_position_stale_seconds", 60)
        )
        rows = list(
            self._session.scalars(
                select(BrokerPositionSnapshotEntity)
                .where(BrokerPositionSnapshotEntity.snapshot_status == "ACTIVE")
                .limit(500)
            )
        )
        items = []
        for p in rows:
            snap_at = getattr(p, "captured_at", None) or getattr(
                p, "updated_at", None
            ) or getattr(p, "created_at", None)
            stale = False
            if isinstance(snap_at, datetime):
                age = (
                    checked_at - snap_at.astimezone(timezone.utc)
                ).total_seconds()
                stale = age > stale_sec
            qty = getattr(p, "quantity", None)
            avg = getattr(p, "average_purchase_price", None)
            cur = getattr(p, "current_price", None)
            eval_amt = getattr(p, "evaluation_amount", None)
            upnl = getattr(p, "profit_loss", None)
            items.append(
                {
                    "user_broker_account_id": getattr(
                        p, "user_broker_account_id", None
                    ),
                    "broker_code": getattr(p, "broker_code", None),
                    "market": getattr(p, "symbol", None),
                    "symbol": getattr(p, "symbol", None),
                    "quantity": _dec_str(qty),
                    "average_price": _dec_str(avg),
                    "current_price": _dec_str(cur),
                    "evaluation_amount": _dec_str(eval_amt),
                    "unrealized_pnl": _dec_str(upnl),
                    "return_rate": _dec_str(
                        getattr(p, "profit_loss_rate", None)
                    ),
                    "snapshot_time": _iso(snap_at),
                    "price_source": "SNAPSHOT",
                    "stale": stale,
                    "stale_after_seconds": stale_sec,
                }
            )
        return {
            "checked_at": checked_at.isoformat(),
            "positions": items,
            "count": len(items),
        }

    # ------------------------------------------------------------------ alerts
    def alerts(self, *, limit: int = 100) -> dict[str, Any]:
        limit = max(1, min(int(limit), 200))
        checked_at = datetime.now(timezone.utc)
        items: list[dict[str, Any]] = []

        # Kill switch
        kill = KillSwitchService(self._session).get_state()
        if kill.status == KillSwitchStatus.ACTIVE:
            items.append(
                _alert(
                    "CRITICAL",
                    "KILL_SWITCH",
                    "KILL_SWITCH_GLOBAL",
                    "Global Kill Switch Active",
                    kill.reason or "active",
                )
            )
        for ks in self._session.scalars(
            select(KillSwitchEntity).where(KillSwitchEntity.active.is_(True))
        ):
            if ks.scope_code == KillSwitchService.GLOBAL_SCOPE:
                continue
            items.append(
                _alert(
                    "ERROR",
                    "KILL_SWITCH",
                    "KILL_SWITCH_SCOPE",
                    f"Kill Switch {ks.scope_code}",
                    ks.reason or "active",
                    uba=_parse_uba_scope(ks.scope_code),
                )
            )

        # Recovery conflicts
        try:
            from stock_platform.broker.recovery_conflict_service import (
                BrokerRecoveryConflictService,
            )

            conflicts = BrokerRecoveryConflictService(self._session).list_conflicts(
                # PENDING_REVIEW만 Review Required / Critical Alert
                review_status="PENDING_REVIEW",
                limit=50,
            )
            for c in conflicts:
                items.append(
                    _alert(
                        "WARNING",
                        "RECOVERY",
                        "RECOVERY_CONFLICT",
                        "Recovery Conflict Pending",
                        str(
                            getattr(c, "conflict_type", None)
                            or getattr(c, "review_status", None)
                            or ""
                        ),
                        uba=getattr(c, "user_broker_account_id", None),
                        related_order_id=getattr(c, "order_id", None),
                        manual=True,
                    )
                )
        except Exception:  # noqa: BLE001
            pass

        # Post-fill issues
        try:
            from stock_platform.order.post_fill_verification_service import (
                PostFillVerificationService,
            )

            counts = PostFillVerificationService(self._session).dashboard_counts()
            for code in ("mismatch", "failed", "expired"):
                n = int(counts.get(code) or counts.get(code.upper()) or 0)
                if n > 0:
                    items.append(
                        _alert(
                            "ERROR",
                            "POST_FILL",
                            f"POST_FILL_{code.upper()}",
                            f"Post-fill {code}",
                            f"count={n}",
                            manual=True,
                        )
                    )
        except Exception:  # noqa: BLE001
            pass

        # Submission unknown orders
        unknown_cnt = int(
            self._session.scalar(
                select(func.count())
                .select_from(TradingOrderEntity)
                .where(
                    TradingOrderEntity.status_code.in_(
                        ("UNKNOWN", "SUBMISSION_UNKNOWN")
                    )
                )
            )
            or 0
        )
        if unknown_cnt:
            items.append(
                _alert(
                    "ERROR",
                    "ORDER",
                    "SUBMISSION_UNKNOWN",
                    "Submission Unknown Orders",
                    f"count={unknown_cnt}",
                    manual=True,
                )
            )

        items = items[:limit]
        return {
            "checked_at": checked_at.isoformat(),
            "count": len(items),
            "alerts": items,
        }

    # ------------------------------------------------------------------ audits
    def audits(
        self,
        *,
        event_type: str | None = None,
        actor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        from stock_platform.operation.audit_models import AuditEvent

        limit = max(1, min(int(limit), 200))
        stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(
            limit
        )
        if event_type:
            stmt = select(AuditEvent).where(
                AuditEvent.event_type == event_type
            ).order_by(AuditEvent.created_at.desc()).limit(limit)
        if actor:
            stmt = select(AuditEvent).where(AuditEvent.actor == actor).order_by(
                AuditEvent.created_at.desc()
            ).limit(limit)
        rows = list(self._session.scalars(stmt))
        items = []
        for row in rows:
            detail = redact_mapping(getattr(row, "detail", None) or {})
            summary = None
            if isinstance(detail, dict):
                summary = str(
                    detail.get("summary")
                    or detail.get("message")
                    or detail.get("status")
                    or ""
                )[:160] or None
            items.append(
                {
                    "occurred_at": _iso(row.created_at),
                    "event_type": row.event_type,
                    "actor": row.actor,
                    "target_type": detail.get("target_type")
                    if isinstance(detail, dict)
                    else None,
                    "target_id": detail.get("target_id")
                    or detail.get("user_broker_account_id")
                    if isinstance(detail, dict)
                    else None,
                    "result": detail.get("result")
                    if isinstance(detail, dict)
                    else None,
                    "correlation_id": row.run_id or row.request_id,
                    "summary": summary,
                }
            )
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "audits": items,
            "count": len(items),
        }

    # ------------------------------------------------------------------ notifications
    def notifications(self, *, limit: int = 50) -> dict[str, Any]:
        from stock_platform.notification.inbox_models import Notification

        limit = max(1, min(int(limit), 200))
        rows = list(
            self._session.scalars(
                select(Notification)
                .order_by(Notification.created_at.desc())
                .limit(limit)
            )
        )
        items = []
        for row in rows:
            items.append(
                {
                    "created_at": _iso(row.created_at),
                    "channel": "INBOX",
                    "severity": row.severity,
                    "event_type": row.event_type,
                    "title": row.title,
                    "message_preview": mask_notification_body(row.message),
                    "delivery_status": "STORED",
                    "retry_count": 0,
                    "last_error_code": None,
                }
            )
        # Telegram ops status (민감정보 없이)
        telegram = {"status": "UNKNOWN", "reason_code": None}
        try:
            enabled = bool(getattr(self._settings, "telegram_enabled", False))
            telegram = {
                "status": "CONFIGURED" if enabled else "DISABLED",
                "summary": "telegram_enabled=" + str(enabled),
            }
        except Exception as exc:  # noqa: BLE001
            telegram = {
                "status": "ERROR",
                "reason_code": type(exc).__name__,
            }
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "telegram": telegram,
            "notifications": items,
            "count": len(items),
        }

    # ============================== helpers ==============================
    def _scheduler_bundle(self) -> dict[str, dict[str, Any]]:
        settings = self._settings
        out: dict[str, dict[str, Any]] = {}
        try:
            snap = collect_scheduler_readiness(settings)
            out["trading"] = {
                "scope": "SYSTEM",
                "desired_state": snap.trading_scheduler_desired_state,
                "actual_state": snap.trading_scheduler_actual_state,
                "running": snap.trading_running,
                "enabled": True,
                "stale": snap.snapshot_stale,
            }
            out["tracking"] = {
                "scope": "UPBIT_LIVE",
                "desired_state": snap.tracking_desired_state,
                "actual_state": (
                    "RUNNING"
                    if snap.tracking_scheduler_running
                    else "STOPPED"
                ),
                "running": snap.tracking_scheduler_running,
                "enabled": snap.tracking_scheduler_running,
            }
            out["post_fill"] = {
                "scope": "SYSTEM",
                "desired_state": snap.post_fill_desired_state,
                "actual_state": (
                    "RUNNING"
                    if snap.post_fill_scheduler_running
                    else "STOPPED"
                ),
                "running": snap.post_fill_scheduler_running,
                "enabled": snap.post_fill_scheduler_running,
            }
        except Exception as exc:  # noqa: BLE001
            out["trading"] = {
                "scope": "SYSTEM",
                "desired_state": "PAUSE",
                "actual_state": "UNKNOWN",
                "running": None,
                "enabled": None,
                "last_error_code": type(exc).__name__,
                "stale": True,
            }

        recovery_enabled = bool(
            getattr(settings, "recovery_scheduler_enabled", True)
        )
        recovery_running = None
        try:
            from stock_platform.broker.recovery_scheduler import (
                broker_recovery_scheduler,
            )

            st = broker_recovery_scheduler.status()
            recovery_running = bool(st.get("running")) if isinstance(st, dict) else None
            actual = str(
                (st or {}).get("actual_state")
                or (
                    "RUNNING"
                    if recovery_running
                    else ("STOPPED" if recovery_running is False else "UNKNOWN")
                )
            ).upper()
            out["recovery"] = {
                "scope": "SYSTEM",
                "desired_state": str(
                    (st or {}).get("desired_state")
                    or ("RUNNING" if recovery_enabled else "STOPPED")
                ),
                "actual_state": actual,
                "running": recovery_running,
                "enabled": bool((st or {}).get("enabled", recovery_enabled)),
                "reason_code": (st or {}).get("reason_code"),
                "cooldown_active": bool((st or {}).get("cooldown_active")),
                "cooldown_remaining_seconds": (st or {}).get(
                    "cooldown_remaining_seconds"
                ),
                "next_run_at": (st or {}).get("next_run_at"),
                "last_success_at": (st or {}).get("last_success_at"),
                "last_failed_at": (st or {}).get("last_failed_at"),
                "consecutive_failures": (st or {}).get(
                    "consecutive_failures"
                ),
                "last_error_code": (st or {}).get("last_error_code"),
                "stale": bool((st or {}).get("stale", False)),
                "job_count": (st or {}).get("job_count"),
            }
        except Exception:  # noqa: BLE001
            out["recovery"] = {
                "scope": "SYSTEM",
                "desired_state": "RUNNING" if recovery_enabled else "STOPPED",
                "actual_state": "UNKNOWN",
                "running": None,
                "enabled": recovery_enabled,
                "stale": True,
                "reason_code": "STATUS_LOOKUP_FAILED",
            }
        return out

    def _broker_overview(self) -> dict[str, dict[str, Any]]:
        settings = self._settings
        upbit_mock = bool(getattr(settings, "upbit_use_mock", True))
        upbit = {
            "status": "HEALTHY",
            "mock_enabled": upbit_mock,
            "reason_code": None,
        }
        if upbit_mock:
            upbit["status"] = "WARNING"
            upbit["reason_code"] = "MOCK_ENABLED"
        # LIVE health gate (스냅샷 기반 — 주문 아님)
        try:
            from stock_platform.operation.live_health_gate import (
                evaluate_live_order_health,
            )

            result = evaluate_live_order_health(self._session)
            critical = bool(
                (result or {}).get("critical")
                or (result or {}).get("blocked")
            )
            if critical:
                upbit["status"] = "UNHEALTHY"
                upbit["reason_code"] = "LIVE_HEALTH_CRITICAL"
        except Exception as exc:  # noqa: BLE001
            upbit["status"] = "UNKNOWN"
            upbit["reason_code"] = type(exc).__name__

        kiwoom_key = bool(getattr(settings, "kiwoom_app_key", "") or "")
        kiwoom = {
            "status": "CONFIGURED" if kiwoom_key else "NOT_CONFIGURED",
            "mock_enabled": None,
            "reason_code": None if kiwoom_key else "MISSING_APP_KEY",
        }
        return {"UPBIT": upbit, "KIWOOM": kiwoom}

    def _runtime_counts(self) -> dict[str, int]:
        try:
            payload = self.runtimes()
            rows = payload.get("runtimes") or []
            running = sum(
                1
                for r in rows
                if str(r.get("state") or "").upper() in {"RUNNING", "ACTIVE"}
            )
            paused = sum(
                1
                for r in rows
                if str(r.get("state") or "").upper() in {"PAUSED", "PAUSE"}
            )
            errors = sum(
                1
                for r in rows
                if str(r.get("state") or "").upper() in {"ERROR", "FAILED"}
                or r.get("last_error_code")
            )
            return {
                "running_count": running,
                "paused_count": paused,
                "error_count": errors,
            }
        except Exception:  # noqa: BLE001
            return {
                "running_count": 0,
                "paused_count": 0,
                "error_count": 0,
                "status": "UNKNOWN",  # type: ignore[dict-item]
            }

    def _alert_counts(self) -> dict[str, int]:
        alerts = self.alerts(limit=200).get("alerts") or []
        critical = sum(1 for a in alerts if a.get("severity") == "CRITICAL")
        warning = sum(1 for a in alerts if a.get("severity") == "WARNING")
        manual = sum(1 for a in alerts if a.get("manual_review_required"))
        return {
            "critical": critical,
            "warning": warning,
            "manual_review": manual,
        }

    def _active_uba_kill_count(self) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(KillSwitchEntity)
                .where(
                    KillSwitchEntity.active.is_(True),
                    KillSwitchEntity.scope_code != KillSwitchService.GLOBAL_SCOPE,
                )
            )
            or 0
        )

    def _uba_kill_active(self, uba_id: int) -> bool:
        scope = uba_kill_switch_scope(uba_id)
        row = self._session.scalar(
            select(KillSwitchEntity).where(
                KillSwitchEntity.scope_code == scope,
                KillSwitchEntity.active.is_(True),
            )
        )
        return row is not None

    def _count_orders_by_uba(
        self,
        *,
        statuses: tuple[str, ...] | None,
        since: datetime | None,
    ) -> dict[int, int]:
        stmt = select(
            TradingOrderEntity.user_broker_account_id,
            func.count(),
        ).group_by(TradingOrderEntity.user_broker_account_id)
        if statuses:
            stmt = stmt.where(TradingOrderEntity.status_code.in_(statuses))
        if since is not None:
            stmt = stmt.where(TradingOrderEntity.created_at >= since)
        result: dict[int, int] = {}
        for uba_id, cnt in self._session.execute(stmt):
            if uba_id is None:
                continue
            result[int(uba_id)] = int(cnt)
        return result

    def _upbit_balance_safe(
        self, uba_id: int
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        ttl = int(
            getattr(self._settings, "ops_dashboard_broker_balance_ttl_seconds", 20)
        )
        now = time.time()
        cached = _BALANCE_CACHE.get(uba_id)
        if cached and now - cached[0] < ttl:
            payload = cached[1]
            return (
                payload["balance"],
                payload["broker_open"],
                payload["broker_health"],
            )

        balance: dict[str, Any] = {
            "orderable_krw": None,
            "locked_krw": None,
            "total_krw_balance": None,
            "status": "UNKNOWN",
            "reason_code": None,
        }
        broker_open: dict[str, Any] = {
            "count": None,
            "status": "UNKNOWN",
            "reason_code": None,
        }
        broker_health = {"status": "UNKNOWN", "reason_code": None}
        try:
            import asyncio

            from stock_platform.broker.credential_adapter_factory import (
                build_upbit_private_client_for_uba,
            )

            client = build_upbit_private_client_for_uba(self._session, uba_id)

            async def _fetch() -> tuple[list, list]:
                accounts = await client.list_accounts()
                open_orders: list = []
                if hasattr(client, "list_orders"):
                    try:
                        open_orders = await client.list_orders(state="wait")  # type: ignore[misc]
                    except TypeError:
                        open_orders = []
                return list(accounts or []), list(open_orders or [])

            accounts, open_orders = asyncio.run(_fetch())
            for row in accounts:
                if str(row.get("currency") or "").upper() != "KRW":
                    continue
                bal = Decimal(str(row.get("balance") or 0))
                locked = Decimal(str(row.get("locked") or 0))
                balance = {
                    "orderable_krw": str(bal - locked),
                    "locked_krw": str(locked),
                    "total_krw_balance": str(bal),
                    "status": "OK",
                    "reason_code": None,
                }
                break
            else:
                balance = {
                    "orderable_krw": None,
                    "locked_krw": None,
                    "total_krw_balance": None,
                    "status": "UNKNOWN",
                    "reason_code": "KRW_ROW_MISSING",
                }
            broker_open = {
                "count": len(open_orders),
                "status": "OK",
                "reason_code": None,
            }
            broker_health = {"status": "HEALTHY", "reason_code": None}
        except Exception as exc:  # noqa: BLE001
            balance = {
                "orderable_krw": None,
                "locked_krw": None,
                "total_krw_balance": None,
                "status": "ERROR",
                "reason_code": type(exc).__name__,
            }
            broker_open = {
                "count": None,
                "status": "ERROR",
                "reason_code": type(exc).__name__,
            }
            broker_health = {
                "status": "UNKNOWN",
                "reason_code": type(exc).__name__,
            }

        _BALANCE_CACHE[uba_id] = (
            now,
            {
                "balance": balance,
                "broker_open": broker_open,
                "broker_health": broker_health,
            },
        )
        return balance, broker_open, broker_health

    def _post_fill_status_map(self, order_ids: list[int]) -> dict[int, str | None]:
        if not order_ids:
            return {}
        try:
            from stock_platform.order.post_fill_verification_entities import (
                PostFillVerificationEntity,
            )

            rows = list(
                self._session.scalars(
                    select(PostFillVerificationEntity).where(
                        PostFillVerificationEntity.order_id.in_(order_ids)
                    )
                )
            )
            return {
                int(r.order_id): getattr(r, "status_code", None)
                for r in rows
                if getattr(r, "order_id", None) is not None
            }
        except Exception:  # noqa: BLE001
            return {}

    def _probe_market_session_scheduler(self) -> dict[str, Any] | None:
        try:
            from stock_platform.operation.market_session_job_scheduler import (
                market_session_job_scheduler,
            )

            running = bool(
                getattr(market_session_job_scheduler, "running", False)
            )
            return {
                "scheduler_name": "market_session",
                "scope": "SYSTEM",
                "desired_state": None,
                "actual_state": "RUNNING" if running else "STOPPED",
                "running": running,
                "enabled": True,
                "last_started_at": None,
                "last_finished_at": None,
                "last_success_at": None,
                "last_failed_at": None,
                "next_run_at": None,
                "consecutive_failures": None,
                "last_error_code": None,
                "snapshot_checked_at": datetime.now(timezone.utc).isoformat(),
                "stale": False,
            }
        except Exception:  # noqa: BLE001
            return None

    def _probe_recovery_scheduler_detail(self) -> dict[str, Any] | None:
        try:
            from stock_platform.broker.recovery_scheduler import (
                broker_recovery_scheduler,
            )

            st = broker_recovery_scheduler.status()
            return {
                "scheduler_name": "recovery",
                "scope": "SYSTEM",
                "desired_state": st.get("desired_state"),
                "actual_state": st.get("actual_state"),
                "running": st.get("running"),
                "enabled": st.get("enabled"),
                "last_started_at": None,
                "last_finished_at": None,
                "last_success_at": st.get("last_success_at"),
                "last_failed_at": st.get("last_failed_at"),
                "next_run_at": st.get("next_run_at"),
                "consecutive_failures": st.get("consecutive_failures"),
                "last_error_code": st.get("last_error_code"),
                "snapshot_checked_at": datetime.now(timezone.utc).isoformat(),
                "stale": bool(st.get("stale", False)),
                "reason_code": st.get("reason_code"),
            }
        except Exception:  # noqa: BLE001
            return None


def runtime_state_for_uba(session: Session, uba_id: int) -> str | None:
    try:
        from stock_platform.strategy_deployment.runtime_manager import (
            dynamic_strategy_runtime_manager,
        )

        entries = dynamic_strategy_runtime_manager.list_entries()
        for entry in entries:
            acct = getattr(entry, "account_id", None) or getattr(
                entry, "user_broker_account_id", None
            )
            if acct is not None and int(acct) == int(uba_id):
                return str(getattr(entry, "state", None) or "UNKNOWN")
    except Exception:  # noqa: BLE001
        return None
    return None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _dec_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(Decimal(str(value)))
    except Exception:  # noqa: BLE001
        return None


def _alert(
    severity: str,
    category: str,
    code: str,
    title: str,
    message: str,
    *,
    uba: int | None = None,
    related_order_id: int | None = None,
    manual: bool = False,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "category": category,
        "code": code,
        "title": title,
        "message": mask_notification_body(message) or "",
        "user_broker_account_id": uba,
        "related_order_id": related_order_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "OPEN",
        "manual_review_required": manual or severity in {"CRITICAL", "ERROR"},
    }


def _parse_uba_scope(scope: str) -> int | None:
    text = (scope or "").upper()
    if text.startswith("UBA:"):
        try:
            return int(text.split(":", 1)[1])
        except ValueError:
            return None
    return None
