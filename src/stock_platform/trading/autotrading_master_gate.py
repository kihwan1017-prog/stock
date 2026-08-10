"""UBA 단위 UPBIT 자동매매 Master Gate (조회 전용, 주문/ARM 변경 없음)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.definition_entities import (
    AccountStrategyLinkEntity,
    StrategyDefinitionEntity,
)
from stock_platform.trading.account_models import UserBrokerAccount


STATUS_READY = "READY_FOR_AUTO_TRADING"
STATUS_BLOCKED = "BLOCKED"
STATUS_STRATEGY_REQUIRED = "STRATEGY_REQUIRED"

RUNTIME_STOPPED = "STOPPED"
RUNTIME_READY = "READY"
RUNTIME_RUNNING = "RUNNING"
RUNTIME_BLOCKED = "BLOCKED"


def evaluate_uba_autotrading_ready(
    session: Session,
    *,
    user_broker_account_id: int,
) -> dict[str, Any]:
    """UBA 자동매매 준비도 집계.

    LIVE ON / ARM / Worker ENABLE 등 운영 플래그는 **조회만** 한다.
    이 함수는 상태를 변경하지 않는다.
    """

    checks: dict[str, Any] = {}
    blockers: list[str] = []
    warnings: list[str] = []
    uba_id = int(user_broker_account_id)

    uba = session.get(UserBrokerAccount, uba_id)
    checks["uba"] = {
        "user_broker_account_id": uba_id,
        "found": uba is not None,
        "broker_code": getattr(uba, "broker_code", None),
        "is_active": bool(getattr(uba, "is_active", False)),
        "live_order_enabled": bool(
            getattr(uba, "live_order_enabled", False)
        ),
        "live_armed": bool(getattr(uba, "live_armed", False)),
        "user_id": getattr(uba, "user_id", None),
    }
    if uba is None:
        blockers.append("UBA_NOT_FOUND")
        return _result(
            uba_id=uba_id,
            status=STATUS_BLOCKED,
            blockers=blockers,
            warnings=warnings,
            checks=checks,
        )
    if str(uba.broker_code or "").upper() != "UPBIT":
        blockers.append("UBA_BROKER_MISMATCH")
    if not bool(uba.is_active) or getattr(uba, "deleted_at", None):
        blockers.append("UBA_INACTIVE")

    # --- Strategy links ---
    links = list(
        session.scalars(
            select(AccountStrategyLinkEntity).where(
                AccountStrategyLinkEntity.user_broker_account_id == uba_id,
            )
        )
    )
    active_links = [row for row in links if bool(row.is_active)]
    strategy_rows: list[dict[str, Any]] = []
    approved_active: list[dict[str, Any]] = []
    for link in links:
        strategy = session.get(
            StrategyDefinitionEntity, int(link.strategy_id)
        )
        approved = bool(
            strategy is not None
            and (
                strategy.approved_at is not None
                or str(getattr(strategy, "owner_type", "") or "").upper()
                == "SYSTEM"
            )
        )
        market = str(getattr(strategy, "market_type", "") or "").upper()
        upbit_ok = market in {"CRYPTO", "UPBIT", "MULTI", ""}
        payload = getattr(strategy, "parameter_payload", None) or {}
        if not isinstance(payload, dict):
            payload = {}
        symbol_hint = (
            str(payload.get("symbol") or payload.get("market") or "").strip()
            or None
        )
        item = {
            "link_id": int(link.account_strategy_link_id),
            "strategy_id": int(link.strategy_id),
            "is_active": bool(link.is_active),
            "strategy_found": strategy is not None,
            "strategy_is_active": bool(
                getattr(strategy, "is_active", False)
            ),
            "approved": approved,
            "approved_at": (
                strategy.approved_at.isoformat()
                if strategy is not None and strategy.approved_at
                else None
            ),
            "market_type": market or None,
            "upbit_compatible": upbit_ok,
            "symbol": symbol_hint.upper() if symbol_hint else None,
            "code": getattr(strategy, "strategy_code", None)
            or getattr(strategy, "code", None),
            "name": getattr(strategy, "name", None),
        }
        strategy_rows.append(item)
        if (
            item["is_active"]
            and item["strategy_is_active"]
            and item["approved"]
            and item["upbit_compatible"]
        ):
            approved_active.append(item)

    checks["strategy_links"] = {
        "total": len(links),
        "active_count": len(active_links),
        "approved_active_count": len(approved_active),
        "items": strategy_rows,
    }
    if not links:
        blockers.append("STRATEGY_REQUIRED")
    elif not approved_active:
        if active_links:
            blockers.append("STRATEGY_NOT_LIVE_APPROVED")
        else:
            blockers.append("STRATEGY_LINK_INACTIVE")

    # --- Runtime (in-memory) ---
    runtime_status = RUNTIME_STOPPED
    runtime_detail: dict[str, Any] = {
        "entries": 0,
        "matching": [],
    }
    try:
        from stock_platform.strategy_deployment.runtime_manager import (
            dynamic_strategy_runtime_manager,
        )
        from stock_platform.strategy_deployment.runtime_scope import (
            AccountKind,
            RuntimeLifecycleStatus,
        )

        snap = dynamic_strategy_runtime_manager.status()
        # status()는 runtimes 키를 사용 (레거시 entries 호환)
        entries = list(
            snap.get("runtimes") or snap.get("entries") or []
        )
        runtime_detail["entries"] = len(entries)
        matching = []
        for entry in entries:
            scope = entry.get("scope") or entry
            acct = scope.get("account_id") or scope.get(
                "user_broker_account_id"
            )
            kind = str(
                scope.get("account_kind") or entry.get("account_kind") or ""
            ).upper()
            if int(acct or 0) != uba_id:
                continue
            if kind and kind not in {
                AccountKind.USER_BROKER.value,
                "USER_BROKER",
                "",
            }:
                continue
            matching.append(entry)
        runtime_detail["matching"] = matching
        if matching:
            statuses = {
                str(
                    e.get("lifecycle_status")
                    or e.get("status")
                    or ""
                ).upper()
                for e in matching
            }
            if RuntimeLifecycleStatus.RUNNING.value in statuses:
                runtime_status = RUNTIME_RUNNING
            elif RuntimeLifecycleStatus.ERROR.value in statuses:
                runtime_status = RUNTIME_BLOCKED
            else:
                # CREATED/PAUSED/STOPPED + active link → READY (미실행 준비)
                runtime_status = (
                    RUNTIME_READY
                    if approved_active
                    else RUNTIME_STOPPED
                )
        elif approved_active:
            runtime_status = RUNTIME_READY
        else:
            runtime_status = RUNTIME_STOPPED
    except Exception as exc:  # noqa: BLE001
        runtime_detail["error"] = type(exc).__name__
        warnings.append("RUNTIME_STATUS_UNAVAILABLE")
        if approved_active:
            runtime_status = RUNTIME_READY

    checks["runtime"] = {
        "status": runtime_status,
        **runtime_detail,
    }
    if runtime_status == RUNTIME_BLOCKED:
        blockers.append("RUNTIME_BLOCKED")
    elif runtime_status == RUNTIME_STOPPED and not approved_active:
        pass  # STRATEGY blockers already cover
    # READY/RUNNING are OK for readiness mapping; RUNNING not required for prep

    # --- Activation / LIVE / ARM ---
    activation_ok = False
    try:
        from stock_platform.broker.live_transition_guard import (
            LiveTradingTransitionGuard,
        )

        # 조회만 — require_active는 상태 변경 없음(만료 처리는 get_active 내부)
        active_transition = LiveTradingTransitionGuard(
            session
        ).require_active(
            broker_code="UPBIT",
            user_broker_account_id=uba_id,
        )
        activation_ok = True
        expires_at = getattr(active_transition, "expires_at", None)
        remaining_ttl: float | None = None
        if expires_at is not None:
            exp = expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            remaining_ttl = max(
                0.0, (exp - datetime.now(timezone.utc)).total_seconds()
            )
        checks["activation"] = {
            "ok": True,
            "transition_id": int(
                getattr(
                    active_transition,
                    "live_trading_transition_id",
                    0,
                )
                or 0
            )
            or None,
            "activation_status": getattr(
                active_transition, "activation_status", None
            ),
            "enabled": bool(getattr(active_transition, "enabled", False)),
            "expires_at": (
                expires_at.isoformat() if expires_at is not None else None
            ),
            "remaining_ttl_seconds": remaining_ttl,
            "scope": getattr(active_transition, "scope", None),
            "broker_code": getattr(active_transition, "broker_code", None),
        }
    except Exception as exc:  # noqa: BLE001
        checks["activation"] = {
            "ok": False,
            "error": f"{type(exc).__name__}:{exc}"[:200],
        }
        blockers.append("ACTIVATION_INACTIVE")
    if not activation_ok and "activation" not in checks:
        checks["activation"] = {"ok": False}

    live_on = bool(getattr(uba, "live_order_enabled", False))
    live_approved = getattr(uba, "live_approved_at", None) is not None
    armed = bool(getattr(uba, "live_armed", False))
    arm_expired = False
    # expire_if_needed 호출 금지 — ARM TTL은 읽기만
    expires = getattr(uba, "arm_expires_at", None) or getattr(
        uba, "live_arm_expires_at", None
    )
    if expires is not None:
        exp = expires
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        arm_expired = exp <= datetime.now(timezone.utc)
    checks["arm"] = {
        "armed": armed,
        "expires_at": expires.isoformat() if expires else None,
        "expired": arm_expired,
    }
    checks["live"] = {
        "live_order_enabled": live_on,
        "live_approved": live_approved,
        "live_approved_at": (
            uba.live_approved_at.isoformat()
            if getattr(uba, "live_approved_at", None)
            else None
        ),
    }
    if not live_approved:
        blockers.append("LIVE_NOT_APPROVED")
    if not live_on:
        blockers.append("LIVE_OFF")
    if not armed or arm_expired:
        blockers.append("ARM_OFF_OR_EXPIRED")

    # --- Kill / Pause / Conflict / Recovery / Credential / Feed ---
    try:
        from stock_platform.trading.upbit_live_pipeline_readiness import (
            UpbitLivePipelineReadinessService,
        )

        pipe = UpbitLivePipelineReadinessService(session).evaluate(
            user_broker_account_id=uba_id
        )
        checks["pipeline"] = {
            "ops_ready": bool(pipe.get("ops_ready")),
            "blockers": list(pipe.get("blockers") or []),
            "warnings": list(pipe.get("warnings") or []),
            "credential": pipe.get("checks", {}).get("credential"),
            "kill": pipe.get("checks", {}).get("kill"),
            "pause": pipe.get("checks", {}).get("pause"),
            "quote_ws": pipe.get("checks", {}).get("quote_ws"),
            "hub_status": pipe.get("checks", {}).get("hub_status"),
            "connection": pipe.get("checks", {}).get("connection"),
            "recovery": pipe.get("checks", {}).get("recovery"),
        }
        for code in pipe.get("blockers") or []:
            if code not in blockers:
                # LIVE/ARM은 위에서 명시 — pipeline 중복 제외 가능
                if code in {
                    "LIVE_ORDER_DISABLED",
                    "LIVE_NOT_ARMED",
                    "ARM_EXPIRED",
                }:
                    continue
                blockers.append(str(code))
        for w in pipe.get("warnings") or []:
            if w not in warnings:
                warnings.append(str(w))
        feed = checks["pipeline"].get("quote_ws") or {}
        hub = checks["pipeline"].get("hub_status") or {}
        feed_eval = _evaluate_market_feed_for_auto_live(
            quote_ws=feed,
            hub=hub,
            strategy_symbols=_strategy_symbols_from_rows(approved_active),
        )
        checks["market_feed"] = feed_eval
        if not bool(feed_eval.get("ok")):
            # AUTO LIVE만 Fail Closed — Paper/Shadow 조회 WARN 정책은 유지
            blockers.append("MARKET_FEED_UNHEALTHY")
    except Exception as exc:  # noqa: BLE001
        checks["pipeline"] = {"error": type(exc).__name__}
        warnings.append("PIPELINE_READINESS_UNAVAILABLE")
        blockers.append("MARKET_FEED_UNHEALTHY")

    # Conflict count
    try:
        from stock_platform.broker.recovery_conflict_entities import (
            BrokerRecoveryConflictEntity,
        )

        from stock_platform.broker.recovery_conflict_constants import (
            ACTIVE_REVIEW_STATUSES,
        )

        conflict_n = int(
            session.scalar(
                select(func.count())
                .select_from(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.user_broker_account_id
                    == uba_id,
                    BrokerRecoveryConflictEntity.review_status.in_(
                        list(ACTIVE_REVIEW_STATUSES)
                    ),
                )
            )
            or 0
        )
        checks["conflict"] = {"open_count": conflict_n}
        if conflict_n > 0:
            blockers.append("CONFLICT_ACTIVE")
    except Exception:  # noqa: BLE001
        checks["conflict"] = {"open_count": None}
        warnings.append("CONFLICT_STATUS_UNAVAILABLE")

    # Risk policy / daily limit
    try:
        from stock_platform.risk_engine.user_risk_service import (
            UserRiskSettingService,
        )

        risk = UserRiskSettingService(session).resolve(
            user_id=int(uba.user_id),
            user_broker_account_id=uba_id,
        )
        risk_payload: dict[str, Any] = {
            "resolved": risk is not None,
            "daily_order_limit": getattr(risk, "daily_order_limit", None),
            "max_order_amount": (
                str(getattr(risk, "max_order_amount", None))
                if risk is not None
                else None
            ),
            "daily_max_order_amount": (
                str(getattr(risk, "daily_max_order_amount", None))
                if risk is not None
                else None
            ),
        }
        if risk is None:
            blockers.append("RISK_POLICY_MISSING")
        # 일일 건수 보강 (실패해도 Risk resolve 결과는 유지)
        try:
            from zoneinfo import ZoneInfo

            from sqlalchemy import not_

            from stock_platform.order.daily_risk_order_count import (
                count_daily_risk_orders,
                day_start_kst_as_utc,
                retired_unsubmitted_exclusion_clause,
            )
            from stock_platform.order.entities import TradingOrderEntity

            day_start = day_start_kst_as_utc()
            daily_count = count_daily_risk_orders(session, uba_id)
            counted_ids = list(
                session.scalars(
                    select(TradingOrderEntity.order_id)
                    .where(
                        TradingOrderEntity.user_broker_account_id == uba_id,
                        TradingOrderEntity.created_at >= day_start,
                        not_(retired_unsubmitted_exclusion_clause()),
                    )
                    .order_by(TradingOrderEntity.order_id.desc())
                    .limit(20)
                )
            )
            now_kst = datetime.now(timezone.utc).astimezone(
                ZoneInfo("Asia/Seoul")
            )
            risk_payload.update(
                {
                    "kst_date": now_kst.date().isoformat(),
                    "daily_order_count": daily_count,
                    "risk_counted_order_ids": [int(x) for x in counted_ids],
                }
            )
        except Exception:  # noqa: BLE001
            warnings.append("DAILY_RISK_COUNT_UNAVAILABLE")
        checks["risk"] = risk_payload
    except Exception:  # noqa: BLE001
        checks["risk"] = {"resolved": False}
        warnings.append("RISK_RESOLVE_UNAVAILABLE")

    # Live outbox worker
    try:
        from stock_platform.order.live_outbox_worker_runtime import (
            live_outbox_worker_runtime,
        )

        worker = live_outbox_worker_runtime.status()
        checks["live_outbox_worker"] = worker
        if not bool(worker.get("enabled")):
            blockers.append("LIVE_OUTBOX_WORKER_DISABLED")
        elif not bool(worker.get("running")):
            warnings.append("LIVE_OUTBOX_WORKER_NOT_RUNNING")
    except Exception:  # noqa: BLE001
        checks["live_outbox_worker"] = {"enabled": False}
        blockers.append("LIVE_OUTBOX_WORKER_DISABLED")

    pending_live = 0
    try:
        from stock_platform.order.outbox_entities import OrderOutbox
        from stock_platform.order.outbox_models import OutboxStatus

        pending_live = int(
            session.scalar(
                select(func.count())
                .select_from(OrderOutbox)
                .where(
                    OrderOutbox.user_broker_account_id == uba_id,
                    OrderOutbox.status_code.in_(
                        (
                            OutboxStatus.PENDING.value,
                            OutboxStatus.RETRY.value,
                        )
                    ),
                    OrderOutbox.payload_json["environment"].astext == "LIVE",
                )
            )
            or 0
        )
    except Exception:  # noqa: BLE001
        pending_live = 0
    checks["pending_live_outbox"] = pending_live

    # UPBIT 24/7 — KRX hours 비적용
    try:
        from stock_platform.realtime.live_runtime_control import (
            upbit_market_hours_policy,
        )

        checks["market_hours"] = upbit_market_hours_policy()
    except Exception:  # noqa: BLE001
        checks["market_hours"] = {
            "broker": "UPBIT",
            "applies_krx_session": False,
            "policy": "24/7_SUBJECT_TO_RECOVERY_KILL_ARM",
        }

    checks["single_uba_config"] = {
        "supported": True,
        "limitation": "SINGLE_UBA_SUPPORTED_WITH_LIMITATION",
        "note": "전역 RealtimeExecutionConfig — 다계좌 동시 LIVE는 미지원",
    }

    # AI Signal Gate 스냅샷 (조회 전용 — Runtime/주문 없음)
    try:
        from stock_platform.realtime.ai_signal_gate import (
            snapshot_ai_signal_gate_status,
        )

        symbols = _strategy_symbols_from_rows(approved_active) or ["KRW-XRP"]
        primary_symbol = symbols[0]
        ai_snap = snapshot_ai_signal_gate_status(
            session,
            exchange_code="UPBIT",
            symbol=primary_symbol,
        )
        checks["ai_signal_gate"] = ai_snap
        if bool(ai_snap.get("enabled")) and bool(ai_snap.get("stale", True)):
            warnings.append("AI_ANALYSIS_STALE_OR_MISSING")
    except Exception as exc:  # noqa: BLE001
        checks["ai_signal_gate"] = {"error": type(exc).__name__}
        warnings.append("AI_SIGNAL_GATE_STATUS_UNAVAILABLE")

    # Candle / News / Provider 상태 (조회 전용)
    checks["market_context"] = _snapshot_market_context_for_ai(
        session,
        symbol=(_strategy_symbols_from_rows(approved_active) or ["KRW-XRP"])[0],
    )

    # 최종 상태 — 승인 Strategy 없으면 STRATEGY_REQUIRED 우선 표시
    if "STRATEGY_REQUIRED" in blockers:
        status = STATUS_STRATEGY_REQUIRED
    elif blockers:
        status = STATUS_BLOCKED
    else:
        status = STATUS_READY

    return _result(
        uba_id=uba_id,
        status=status,
        blockers=blockers,
        warnings=warnings,
        checks=checks,
        runtime_status=runtime_status,
    )


def _strategy_symbols_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    """승인 active strategy row에서 심볼 힌트 추출 (없으면 기본 KRW-XRP)."""

    symbols: list[str] = []
    for row in rows:
        for key in ("symbol", "symbols", "primary_symbol"):
            raw = row.get(key)
            if isinstance(raw, str) and raw.strip():
                symbols.append(raw.strip().upper())
            elif isinstance(raw, (list, tuple)):
                for item in raw:
                    if str(item).strip():
                        symbols.append(str(item).strip().upper())
    # 중복 제거 유지 순서
    uniq: list[str] = []
    for sym in symbols:
        if sym not in uniq:
            uniq.append(sym)
    return uniq


def _parse_iso_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _evaluate_market_feed_for_auto_live(
    *,
    quote_ws: dict[str, Any],
    hub: dict[str, Any],
    strategy_symbols: list[str],
) -> dict[str, Any]:
    """AUTO LIVE용 Market Feed 판정 — stale/unhealthy면 Fail Closed.

    Paper/Shadow readiness의 WARN 정책을 바꾸지 않는다.
    """

    from stock_platform.common.settings import get_settings

    settings = get_settings()
    stale_limit = float(
        getattr(settings, "autotrading_market_feed_stale_seconds", 30.0)
        or 30.0
    )
    now = datetime.now(timezone.utc)
    symbols = strategy_symbols or [
        str(
            getattr(settings, "realtime_upbit_default_symbol", "") or "KRW-XRP"
        ).upper()
    ]

    connected = bool(
        quote_ws.get("ok")
        or quote_ws.get("connected")
        or quote_ws.get("running")
    )
    hub_running = bool(
        hub.get("ok")
        or hub.get("running")
        or hub.get("dispatch_running")
    )
    last_received = _parse_iso_utc(quote_ws.get("last_received_at"))
    last_hub_event = _parse_iso_utc(hub.get("last_event_at"))
    freshest = last_received or last_hub_event
    age_sec: float | None = None
    if freshest is not None:
        age_sec = max(0.0, (now - freshest).total_seconds())

    # cache에 목표 심볼 시세가 있으면 보조 확인 (실주문 없음)
    cache_hit: dict[str, Any] | None = None
    try:
        from stock_platform.realtime.manager import realtime_manager

        cache = getattr(realtime_manager, "cache", None)
        items = getattr(cache, "_items", None) if cache is not None else None
        if isinstance(items, dict):
            for sym in symbols:
                key = f"UPBIT:{sym.upper()}"
                hit = items.get(key)
                if hit is None:
                    continue
                recv = getattr(hit, "received_at", None) or getattr(
                    hit, "event_time", None
                )
                price = getattr(hit, "trade_price", None)
                cache_hit = {
                    "symbol": sym.upper(),
                    "trade_price": (
                        str(price) if price is not None else None
                    ),
                    "received_at": (
                        recv.isoformat()
                        if hasattr(recv, "isoformat")
                        else str(recv)
                        if recv
                        else None
                    ),
                }
                if recv is not None and hasattr(recv, "tzinfo"):
                    rdt = recv
                    if rdt.tzinfo is None:
                        rdt = rdt.replace(tzinfo=timezone.utc)
                    else:
                        rdt = rdt.astimezone(timezone.utc)
                    cache_age = max(0.0, (now - rdt).total_seconds())
                    if age_sec is None or cache_age < age_sec:
                        age_sec = cache_age
                        freshest = rdt
                break
    except Exception:  # noqa: BLE001
        cache_hit = None

    fresh = age_sec is not None and age_sec <= stale_limit
    ok = bool(connected and hub_running and fresh)
    reason = "OK"
    if not connected:
        reason = "QUOTE_WS_NOT_CONNECTED"
    elif not hub_running:
        reason = "HUB_DISPATCH_NOT_RUNNING"
    elif age_sec is None:
        reason = "NO_RECENT_QUOTE"
    elif not fresh:
        reason = "QUOTE_STALE"

    return {
        "ok": ok,
        "policy": "BLOCK_IF_UNHEALTHY_FOR_AUTO_LIVE",
        "stale_limit_seconds": stale_limit,
        "age_seconds": age_sec,
        "last_received_at": freshest.isoformat() if freshest else None,
        "symbols": symbols,
        "quote_ws": quote_ws,
        "hub": hub,
        "cache_hit": cache_hit,
        "reason": reason,
        "evaluator_path": (
            "UpbitTicker→QuoteHub→MovingAverageStrategyEvaluator"
        ),
    }


def _result(
    *,
    uba_id: int,
    status: str,
    blockers: list[str],
    warnings: list[str],
    checks: dict[str, Any],
    runtime_status: str | None = None,
) -> dict[str, Any]:
    return {
        "user_broker_account_id": uba_id,
        "status": status,
        "auto_trading_ready": status == STATUS_READY,
        "runtime_status": runtime_status
        or checks.get("runtime", {}).get("status"),
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
        "start_button_enabled": False,  # 이번 STEP — 시작 버튼 비활성
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def admin_set_uba_strategy_link_active(
    session: Session,
    *,
    user_broker_account_id: int,
    strategy_id: int,
    is_active: bool,
    actor: str,
) -> dict[str, Any]:
    """UBA↔Strategy link 활성/비활성 (Runtime RUN / 주문 없음)."""

    uba = session.get(UserBrokerAccount, int(user_broker_account_id))
    if uba is None:
        raise ValueError("UBA_NOT_FOUND")
    if str(uba.broker_code or "").upper() != "UPBIT":
        raise ValueError("UBA_BROKER_MISMATCH")

    strategy = session.get(StrategyDefinitionEntity, int(strategy_id))
    if strategy is None:
        raise ValueError("STRATEGY_NOT_FOUND")
    if is_active:
        if not bool(strategy.is_active):
            raise ValueError("STRATEGY_INACTIVE")
        approved = strategy.approved_at is not None or str(
            getattr(strategy, "owner_type", "") or ""
        ).upper() == "SYSTEM"
        if not approved:
            raise ValueError("STRATEGY_NOT_APPROVED")
        if getattr(uba, "live_approved_at", None) is None:
            raise ValueError("LIVE_NOT_APPROVED")
        market = str(strategy.market_type or "").upper()
        if market and market not in {"CRYPTO", "UPBIT", "MULTI"}:
            raise ValueError("STRATEGY_BROKER_INCOMPATIBLE")

    link = session.scalar(
        select(AccountStrategyLinkEntity).where(
            AccountStrategyLinkEntity.user_broker_account_id
            == int(user_broker_account_id),
            AccountStrategyLinkEntity.strategy_id == int(strategy_id),
        ).limit(1)
    )
    if link is None:
        if not is_active:
            raise ValueError("LINK_NOT_FOUND")
        # 활성 요청인데 link 없음 → 생성 (승인·호환 검증 통과 후)
        link = AccountStrategyLinkEntity(
            strategy_id=int(strategy_id),
            user_id=int(uba.user_id),
            paper_account_id=None,
            user_broker_account_id=int(user_broker_account_id),
            is_active=True,
            created_by=actor,
        )
        session.add(link)
    else:
        if is_active and int(link.user_id) != int(uba.user_id):
            raise ValueError("UBA_OWNERSHIP_MISMATCH")
        link.is_active = bool(is_active)
    session.flush()
    return {
        "link_id": int(link.account_strategy_link_id),
        "strategy_id": int(strategy_id),
        "user_broker_account_id": int(user_broker_account_id),
        "is_active": bool(link.is_active),
        "actor": actor,
        "runtime_started": False,
        "orders_submitted": 0,
    }


def _snapshot_market_context_for_ai(
    session: Session,
    *,
    symbol: str,
) -> dict[str, Any]:
    """Candle/News/Ollama 조회 스냅샷 — operation 모듈에 위임."""

    from stock_platform.operation.upbit_ai_context_snapshot import (
        snapshot_upbit_ai_context,
    )

    return snapshot_upbit_ai_context(session, symbol=symbol)

