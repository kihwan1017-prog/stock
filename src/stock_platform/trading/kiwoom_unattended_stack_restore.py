"""Kiwoom MARKET_HOURS lease 복구 후 운영 스택 재기동.

대상: Market REALTIME feed · Strategy Runtime ensure/resume ·
LIVE Signal Execution Runner.

LIVE/ARM/Activation/lease는 LiveUnattendedAuthorizationService /
KiwoomTradingDayLifecycleService가 담당한다.

정책:
- Scheduler 강제 RUN 없음
- REAL 주문 강제 생성 없음
- Gate FAIL 시 stack start 금지
- Upbit UBA runner/상태 변경 금지 (scoped only)
- Worker/Runtime/ExecutionRunner 중복 start는 idempotent
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.definition_entities import (
    AccountStrategyLinkEntity,
)
from stock_platform.strategy_deployment.runtime_scope import (
    RuntimeLifecycleStatus,
)
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.live_unattended_authorization_service import (
    STATUS_ACTIVE,
    LiveUnattendedAuthorizationService,
)

logger = structlog.get_logger(__name__)


async def sync_kiwoom_account_state_for_startup(
    session: Session,
    *,
    user_broker_account_id: int,
) -> dict[str, Any]:
    """자동 시작 직전 예수금·보유·미체결 스냅샷 갱신 (주문 없음).

    공식 KiwoomAccountStateSyncService 경로 재사용.
    실패 시 LIVE/ARM 진행 금지용으로 ok=False 반환.
    """

    uba_id = int(user_broker_account_id)
    try:
        from stock_platform.broker.credential_adapter_factory import (
            build_kiwoom_account_client_for_uba,
            build_kiwoom_pending_order_client_for_uba,
        )
        from stock_platform.broker.kiwoom.account_sync_service import (
            KiwoomAccountSyncService,
        )
        from stock_platform.broker.kiwoom.account_state_sync_service import (
            KiwoomAccountStateSyncService,
        )
        from stock_platform.broker.kiwoom.pending_service import (
            KiwoomPendingOrderService,
        )

        account_client, _acct = build_kiwoom_account_client_for_uba(
            session, uba_id
        )
        result = await KiwoomAccountStateSyncService(
            session=session,
            account_sync_service=KiwoomAccountSyncService(
                session=session,
                account_client=account_client,
                user_broker_account_id=uba_id,
            ),
            pending_order_service=KiwoomPendingOrderService(
                session,
                build_kiwoom_pending_order_client_for_uba(session, uba_id),
            ),
        ).synchronize(user_broker_account_id=uba_id)
        session.flush()
        account = dict(result.account or {})
        pending = dict(result.pending_orders or {})
        # UNKNOWN/미체결 카운트 요약 (민감정보 제외)
        pending_count = pending.get("count")
        if pending_count is None:
            items = pending.get("items") or pending.get("orders") or []
            pending_count = len(items) if isinstance(items, list) else None
        return {
            "ok": True,
            "synced": True,
            "user_broker_account_id": uba_id,
            "snapshot_keys": sorted(account.keys())[:20],
            "has_deposit": "deposit_amount" in account
            or "ord_psbl_cash" in account
            or bool(account),
            "pending_order_count": pending_count,
            "fields": dict(result.fields or {}),
        }
        except Exception as exc:  # noqa: BLE001
            # CredentialVaultError 포함 — 민감정보 없이 코드만
            code = str(getattr(exc, "code", "") or "") or type(exc).__name__
            logger.warning(
                "kiwoom_startup_account_sync_failed",
                uba_id=uba_id,
                error=code,
            )
            return {
                "ok": False,
                "synced": False,
                "reason": (
                    code
                    if code
                    not in {"", "Exception", "Error"}
                    else "ACCOUNT_SYNC_FAILED"
                ),
                "error": type(exc).__name__,
                "message": str(exc)[:200],
            }


def evaluate_kiwoom_stack_restore_gates(
    session: Session,
    *,
    user_broker_account_id: int,
) -> dict[str, Any]:
    """스택 복구 전용 gate. 전부 PASS일 때만 feed/runtime/runner 기동."""

    uba_id = int(user_broker_account_id)
    blockers: list[str] = []
    checks: dict[str, Any] = {}

    uba = session.get(UserBrokerAccount, uba_id)
    if uba is None:
        return {"ok": False, "blockers": ["UBA_NOT_FOUND"], "checks": checks}
    if str(uba.broker_code or "").upper() != "KIWOOM":
        return {
            "ok": False,
            "blockers": ["UBA_BROKER_MISMATCH"],
            "checks": checks,
        }

    lease = LiveUnattendedAuthorizationService(session).get_active(uba_id)
    if lease is None or str(lease.status_code or "").upper() != STATUS_ACTIVE:
        blockers.append("NO_ACTIVE_LEASE")
        checks["lease"] = "MISSING"
    else:
        checks["lease"] = "ACTIVE"

    if not bool(getattr(uba, "live_order_enabled", False)):
        blockers.append("LIVE_OFF")
    if not bool(getattr(uba, "live_armed", False)):
        blockers.append("ARM_OFF")

    enable = LiveUnattendedAuthorizationService(session).evaluate_enable_gates(
        uba_id,
        authorization_mode="MARKET_HOURS",
    )
    checks["enable_gates"] = {
        "ok": enable.get("ok"),
        "blockers": list(enable.get("blockers") or []),
        "execution_env": enable.get("execution_env"),
    }
    ignored = {
        "RUNTIME_NOT_RUNNING",
        "OUTBOX_WORKER_NOT_RUNNING",
    }
    for code in enable.get("blockers") or []:
        if code in ignored:
            continue
        if code not in blockers:
            blockers.append(str(code))

    link = session.scalar(
        select(AccountStrategyLinkEntity)
        .where(
            AccountStrategyLinkEntity.user_broker_account_id == uba_id,
            AccountStrategyLinkEntity.is_active.is_(True),
        )
        .limit(1)
    )
    if link is None:
        blockers.append("NO_ACTIVE_STRATEGY_LINK")
        checks["strategy_link"] = None
    else:
        checks["strategy_link"] = {
            "strategy_id": int(link.strategy_id),
            "link_id": int(link.account_strategy_link_id),
        }

    uniq = list(dict.fromkeys(blockers))
    return {"ok": len(uniq) == 0, "blockers": uniq, "checks": checks}


async def restore_kiwoom_trading_stack(
    session: Session,
    *,
    user_broker_account_id: int,
    actor: str = "SYSTEM_KIWOOM_STACK_RESTORE",
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Gate PASS 시 feed → ensure-scope → resume → execution runner."""

    uba_id = int(user_broker_account_id)
    gates = evaluate_kiwoom_stack_restore_gates(
        session, user_broker_account_id=uba_id
    )
    if not gates["ok"]:
        return {
            "restored": False,
            "reason": "STACK_GATES_FAILED",
            "blockers": gates["blockers"],
            "gates": gates,
            "actor": actor,
        }

    detail: dict[str, Any] = {"gates": gates, "actor": actor}
    link_meta = (gates.get("checks") or {}).get("strategy_link") or {}
    strategy_id = link_meta.get("strategy_id")

    # 심볼: 명시 > link 메타 없음 시 빈 목록 (runtime이 기존 구독 유지)
    feed_symbols = [str(s).strip() for s in (symbols or []) if str(s).strip()]

    # 1) Kiwoom market realtime WS (idempotent)
    try:
        from stock_platform.realtime.kiwoom_market_realtime_runtime import (
            kiwoom_market_realtime_runtime,
        )

        st = kiwoom_market_realtime_runtime.status()
        already = bool(st.get("running") and st.get("connected"))
        same_uba = int(st.get("user_broker_account_id") or 0) == uba_id
        if already and same_uba:
            detail["feed"] = {
                "started": True,
                "idempotent": True,
                "reason": "ALREADY_RUNNING",
            }
        else:
            started = await kiwoom_market_realtime_runtime.start(
                user_broker_account_id=uba_id,
                symbols=feed_symbols,
                require_real=True,
            )
            detail["feed"] = {
                "started": bool(started.get("started")),
                "result": {
                    k: started.get(k)
                    for k in (
                        "started",
                        "reason",
                        "already_running",
                        "user_broker_account_id",
                    )
                    if k in started
                },
            }
            if not started.get("started") and not started.get(
                "already_running"
            ):
                return {
                    "restored": False,
                    "reason": "FEED_START_FAILED",
                    "detail": detail,
                    "actor": actor,
                }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "kiwoom_stack_feed_failed",
            uba_id=uba_id,
            error=type(exc).__name__,
        )
        return {
            "restored": False,
            "reason": "FEED_START_ERROR",
            "error": type(exc).__name__,
            "detail": detail,
            "actor": actor,
        }

    # 2) ensure-scope (PAUSED) + resume
    from stock_platform.strategy_deployment.runtime_bootstrap import (
        _build_scope_for_link,
    )
    from stock_platform.strategy_deployment.runtime_manager import (
        dynamic_strategy_runtime_manager,
    )
    from stock_platform.risk_engine.kill_switch_service import KillSwitchService

    if strategy_id is None:
        detail["runtime"] = {
            "resumed": False,
            "reason": "STRATEGY_ID_MISSING",
        }
    else:
        link = session.scalar(
            select(AccountStrategyLinkEntity).where(
                AccountStrategyLinkEntity.user_broker_account_id == uba_id,
                AccountStrategyLinkEntity.strategy_id == int(strategy_id),
                AccountStrategyLinkEntity.is_active.is_(True),
            )
        )
        if link is None:
            detail["runtime"] = {
                "resumed": False,
                "reason": "LINK_NOT_FOUND",
            }
        else:
            try:
                kill_active = bool(KillSwitchService(session).is_active())
            except Exception:  # noqa: BLE001
                kill_active = True
            try:
                scope, _ = _build_scope_for_link(
                    session, link, kill_active=kill_active
                )
                await dynamic_strategy_runtime_manager.initialize_scoped(
                    scope, force=True, start=False
                )
                entries = [
                    e
                    for e in dynamic_strategy_runtime_manager.list_entries(
                        user_broker_account_id=uba_id,
                        strategy_id=int(strategy_id),
                    )
                    if str(e.scope.broker_code or "").upper() == "KIWOOM"
                ]
                running = [
                    e
                    for e in entries
                    if e.status == RuntimeLifecycleStatus.RUNNING
                ]
                paused = [
                    e
                    for e in entries
                    if e.status == RuntimeLifecycleStatus.PAUSED
                ]
                if running:
                    detail["runtime"] = {
                        "resumed": True,
                        "reason": "ALREADY_RUNNING",
                        "idempotent": True,
                        "scope_key": running[0].scope.scope_key,
                    }
                elif paused:
                    entry = paused[0]
                    await dynamic_strategy_runtime_manager.resume_runtime(
                        entry.scope.scope_key
                    )
                    detail["runtime"] = {
                        "resumed": True,
                        "reason": "RESUMED",
                        "scope_key": entry.scope.scope_key,
                    }
                else:
                    detail["runtime"] = {
                        "resumed": False,
                        "reason": "NO_PAUSED_RUNTIME",
                    }
            except Exception as exc:  # noqa: BLE001
                detail["runtime"] = {
                    "resumed": False,
                    "reason": "RUNTIME_ERROR",
                    "error": type(exc).__name__,
                }

    # 3) realtime execution runner (scoped LIVE only)
    try:
        from stock_platform.api.v1.realtime_execution import (
            _start_live_for_uba,
        )

        runner = await _start_live_for_uba(uba_id)
        detail["runner"] = {
            "started": bool(
                runner.get("started") or runner.get("already_running")
            ),
            "idempotent": bool(runner.get("already_running")),
            "mode": runner.get("mode"),
            "user_broker_account_id": runner.get("user_broker_account_id")
            or uba_id,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "kiwoom_stack_runner_failed",
            uba_id=uba_id,
            error=type(exc).__name__,
        )
        detail["runner"] = {
            "started": False,
            "reason": "RUNNER_START_ERROR",
            "error": type(exc).__name__,
        }
        return {
            "restored": False,
            "reason": "RUNNER_START_FAILED",
            "detail": detail,
            "actor": actor,
        }

    restored_ok = bool(
        (detail.get("feed") or {}).get("started")
        and (detail.get("runner") or {}).get("started")
    )
    return {
        "restored": restored_ok,
        "reason": "OK" if restored_ok else "PARTIAL",
        "detail": detail,
        "actor": actor,
        "upbit_untouched": True,
    }
