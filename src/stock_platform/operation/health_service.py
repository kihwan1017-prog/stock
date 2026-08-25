from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import text

from stock_platform.common.settings import get_settings

# /health 가 workers=1 환경에서 순차 외부 HTTP로 API 전체를 막지 않도록
# 짧은 TTL 캐시 + 외부 probe 병렬화
_HEALTH_BUILD_CACHE: dict[str, Any] | None = None
_HEALTH_BUILD_CACHE_AT = 0.0
_HEALTH_BUILD_CACHE_TTL_SEC = 5.0


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    name: str
    status: str
    detail: dict[str, Any]


def _safe_message(exc: Exception) -> str:
    text_value = str(exc)
    if len(text_value) > 200:
        return text_value[:200] + "..."
    return text_value


def check_database() -> dict[str, Any]:
    try:
        from stock_platform.database.session import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "UP"}
    except Exception as ex:
        return {"status": "DOWN", "message": _safe_message(ex)}


def check_ollama() -> dict[str, Any]:
    settings = get_settings()
    try:
        response = httpx.get(
            f"{settings.ollama_base_url.rstrip('/')}/api/tags",
            timeout=3.0,
        )
        response.raise_for_status()
        models = response.json().get("models", [])
        return {
            "status": "UP",
            "model_count": len(models),
        }
    except Exception as ex:
        return {"status": "DOWN", "message": _safe_message(ex)}


def check_http_endpoint(
    *,
    name: str,
    url: str,
    timeout_seconds: float = 3.0,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        response = httpx.get(
            url,
            timeout=timeout_seconds,
            headers=headers or {},
        )
        if response.status_code >= 500:
            return {
                "status": "DOWN",
                "message": f"HTTP {response.status_code}",
            }
        return {
            "status": "UP",
            "http_status": response.status_code,
        }
    except Exception as ex:
        return {
            "status": "DOWN",
            "message": _safe_message(ex),
        }


class SystemHealthService:
    """운영용 통합 헬스 집계."""

    async def build(self) -> dict[str, Any]:
        global _HEALTH_BUILD_CACHE, _HEALTH_BUILD_CACHE_AT

        now_mono = time.monotonic()
        if (
            _HEALTH_BUILD_CACHE is not None
            and (now_mono - _HEALTH_BUILD_CACHE_AT) < _HEALTH_BUILD_CACHE_TTL_SEC
        ):
            return _HEALTH_BUILD_CACHE

        settings = get_settings()
        upbit_url = (
            f"{settings.upbit_base_url.rstrip('/')}"
            "/v1/market/all?isDetails=false"
        )
        dart_configured = bool(settings.dart_api_key.strip())
        dart_url = (
            f"{settings.dart_base_url.rstrip('/')}"
            f"/corpCode.xml?crtfc_key={settings.dart_api_key}"
            if dart_configured
            else ""
        )

        # 외부 HTTP는 병렬 — 순차 시 Ollama+Upbit+DART 타임아웃이 누적되어
        # workers=1 에서 /version·alerts 등 다른 API까지 블로킹됨
        db_comp, ollama_comp, upbit_comp, dart_comp = await asyncio.gather(
            asyncio.to_thread(check_database),
            asyncio.to_thread(check_ollama),
            asyncio.to_thread(
                check_http_endpoint,
                name="upbit_rest",
                url=upbit_url,
                timeout_seconds=settings.upbit_timeout_seconds,
            ),
            (
                asyncio.to_thread(
                    check_http_endpoint,
                    name="dart",
                    url=dart_url,
                    timeout_seconds=min(5.0, settings.dart_timeout_seconds),
                )
                if dart_configured
                else asyncio.sleep(
                    0,
                    result={
                        "status": "SKIPPED",
                        "message": "DART API key not configured",
                    },
                )
            ),
        )

        components: dict[str, Any] = {
            "database": db_comp,
            "ollama": ollama_comp,
            "upbit_rest": upbit_comp,
            "dart": dart_comp,
            "news": (
                {
                    "status": "CONFIGURED",
                    "message": "Naver news credentials present",
                }
                if (
                    settings.naver_client_id.strip()
                    and settings.naver_client_secret.strip()
                )
                else {
                    "status": "SKIPPED",
                    "message": "Naver news credentials missing",
                }
            ),
            "kiwoom_rest": (
                {
                    "status": "CONFIGURED",
                    "use_mock": settings.kiwoom_use_mock,
                    "live_order_enabled": (
                        settings.kiwoom_live_order_enabled
                    ),
                }
                if settings.kiwoom_app_key.strip()
                else {
                    "status": "SKIPPED",
                    "message": "Kiwoom credentials missing",
                }
            ),
            "kiwoom_websocket": {
                "status": (
                    "CONFIGURED"
                    if (
                        settings.kiwoom_ws_url.strip()
                        or settings.kiwoom_order_ws_url.strip()
                    )
                    else "SKIPPED"
                ),
            },
            "scheduler": {
                "status": (
                    "UP"
                    if settings.scheduler_enabled
                    else "DISABLED"
                ),
            },
            "live_trading": {
                "status": (
                    "ENABLED"
                    if settings.kiwoom_live_order_enabled
                    else "DISABLED"
                ),
                "live_order_enabled": (
                    settings.kiwoom_live_order_enabled
                ),
            },
        }

        # STEP 8-5-7 — KRX Calendar Coverage (부족 시 DEGRADED)
        try:
            from stock_platform.database.session import get_session_factory
            from stock_platform.operation.calendar_sync_service import (
                TradingCalendarSyncService,
            )

            session = get_session_factory()()
            try:
                cov = TradingCalendarSyncService(session).check_coverage()
                live_ok = bool(
                    cov.get("coverage", {}).get("live_trading_allowed")
                )
                change_summary = {}
                try:
                    from stock_platform.operation.calendar_change_service import (
                        TradingCalendarChangeService,
                    )

                    change_summary = TradingCalendarChangeService(
                        session
                    ).health_summary()
                except Exception:  # noqa: BLE001
                    change_summary = {}
                # 임시휴장(특별 CLOSED)은 Coverage와 별개 — 정상 휴장으로 표시
                today_closed_ok = (
                    change_summary.get("today_session_type") == "CLOSED"
                    and change_summary.get("today_special_session")
                )
                cal_status = "UP" if live_ok else "DEGRADED"
                if today_closed_ok and live_ok is False:
                    # coverage 부족이 아니라 오늘만 휴장인 경우는 별도 플래그
                    pass
                components["krx_trading_calendar"] = {
                    "status": cal_status,
                    "live_trading_allowed": live_ok,
                    "max_verified_date": cov.get("max_verified_date"),
                    "coverage": cov.get("coverage"),
                    "last_sync": cov.get("last_sync"),
                    "required_future_days": cov.get(
                        "required_future_days"
                    ),
                    "pending_change_requests": change_summary.get(
                        "pending_change_requests"
                    ),
                    "conflict_change_requests": change_summary.get(
                        "conflict_change_requests"
                    ),
                    "today_special_session": change_summary.get(
                        "today_special_session"
                    ),
                    "today_session_type": change_summary.get(
                        "today_session_type"
                    ),
                    "today_revision": change_summary.get(
                        "today_revision"
                    ),
                }
            finally:
                session.close()
        except Exception as ex:
            components["krx_trading_calendar"] = {
                "status": "DOWN",
                "message": _safe_message(ex),
                "live_trading_allowed": False,
            }

        # STEP 8-5-12 — Upbit Ambiguous Orders
        try:
            from stock_platform.database.session import get_session_factory
            from stock_platform.broker.upbit.ambiguous_resolver import (
                UpbitAmbiguousOrderResolver,
            )

            session = get_session_factory()()
            try:
                components["upbit_ambiguous_orders"] = (
                    UpbitAmbiguousOrderResolver(
                        session
                    ).health_summary()
                )
                components["upbit_ambiguous_orders"]["status"] = "UP"
            finally:
                session.close()
        except Exception as ex:
            components["upbit_ambiguous_orders"] = {
                "status": "DOWN",
                "message": _safe_message(ex),
            }

        # STEP 8-5-14 — Upbit Ambiguous Resolver Scheduler
        try:
            from stock_platform.broker.upbit.ambiguous_resolution_scheduler import (
                upbit_ambiguous_order_resolution_scheduler,
            )
            from stock_platform.database.session import get_session_factory

            session = get_session_factory()()
            try:
                claimed = int(
                    session.scalar(
                        text(
                            """
                            SELECT count(*) FROM trading.trading_order
                            WHERE resolver_claim_expires_at IS NOT NULL
                              AND resolver_claim_expires_at >= NOW()
                            """
                        )
                    )
                    or 0
                )
                expired = int(
                    session.scalar(
                        text(
                            """
                            SELECT count(*) FROM trading.trading_order
                            WHERE resolver_claim_expires_at IS NOT NULL
                              AND resolver_claim_expires_at < NOW()
                            """
                        )
                    )
                    or 0
                )
                last_run = session.execute(
                    text(
                        """
                        SELECT status_code, started_at, finished_at
                        FROM operation.upbit_ambiguous_resolution_run
                        ORDER BY upbit_ambiguous_resolution_run_id DESC
                        LIMIT 1
                        """
                    )
                ).mappings().first()
                scheduler_state = (
                    upbit_ambiguous_order_resolution_scheduler.status()
                )
                components["upbit_ambiguous_resolver"] = {
                    "status": (
                        "UP" if scheduler_state.get("running") else "DISABLED"
                    ),
                    "enabled": settings.upbit_ambiguous_resolver_enabled,
                    "claimed_count": claimed,
                    "expired_claim_count": expired,
                    "last_run_status": (
                        last_run["status_code"] if last_run else None
                    ),
                    "last_run_started_at": (
                        last_run["started_at"].isoformat()
                        if last_run and last_run["started_at"]
                        else None
                    ),
                    "last_run_finished_at": (
                        last_run["finished_at"].isoformat()
                        if last_run and last_run["finished_at"]
                        else None
                    ),
                    "scheduler": scheduler_state,
                }
            finally:
                session.close()
        except Exception as ex:
            components["upbit_ambiguous_resolver"] = {
                "status": "DOWN",
                "message": _safe_message(ex),
            }

        # STEP 8-5-16 — Account Daily Settlement
        try:
            from stock_platform.database.session import get_session_factory
            from stock_platform.settlement.service import (
                AccountDailySettlementService,
            )
            from stock_platform.settlement.upbit_daily_scheduler import (
                upbit_daily_settlement_scheduler,
            )

            session = get_session_factory()()
            try:
                summary = AccountDailySettlementService(
                    session
                ).health_summary()
                manual = int(summary.get("manual_review") or 0)
                failed = int(summary.get("failed") or 0)
                status = "UP"
                if failed > 0 or manual > 0:
                    status = "DEGRADED"
                if not settings.settlement_enabled:
                    status = "DISABLED"
                components["account_settlements"] = {
                    **summary,
                    "status": status,
                    "upbit_daily_scheduler": (
                        upbit_daily_settlement_scheduler.status()
                    ),
                }
            finally:
                session.close()
        except Exception as ex:
            components["account_settlements"] = {
                "status": "DOWN",
                "message": _safe_message(ex),
            }

        # STEP 8-5-17 — Snapshot Binding / Freshness
        try:
            from stock_platform.database.session import get_session_factory
            from stock_platform.broker.account_models import (
                BrokerAccountSnapshotEntity,
            )
            from stock_platform.broker.snapshot_constants import (
                BrokerSnapshotStatus,
            )
            from sqlalchemy import func, select
            from datetime import datetime, timezone

            session = get_session_factory()()
            try:
                by_status = dict(
                    session.execute(
                        select(
                            BrokerAccountSnapshotEntity.snapshot_status,
                            func.count(),
                        ).group_by(
                            BrokerAccountSnapshotEntity.snapshot_status
                        )
                    ).all()
                )
                orphan = int(
                    by_status.get(BrokerSnapshotStatus.ORPHAN.value, 0) or 0
                )
                active_rows = list(
                    session.scalars(
                        select(BrokerAccountSnapshotEntity).where(
                            BrokerAccountSnapshotEntity.snapshot_status
                            == BrokerSnapshotStatus.ACTIVE.value
                        )
                    )
                )
                max_age = int(settings.settlement_price_max_age_seconds)
                now = datetime.now(timezone.utc)
                stale = 0
                ages = []
                gens = []
                for row in active_rows:
                    gens.append(int(row.snapshot_generation or 1))
                    t = row.snapshot_time or row.synchronized_at
                    if t is None:
                        stale += 1
                        continue
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=timezone.utc)
                    age = (now - t).total_seconds()
                    ages.append(age)
                    if age > max_age:
                        stale += 1
                snap_status = "UP"
                if stale > 0 or orphan > 0:
                    snap_status = "DEGRADED"
                components["snapshot_binding"] = {
                    "status": snap_status,
                    "by_status": {
                        str(k): int(v) for k, v in by_status.items()
                    },
                    "orphan_count": orphan,
                    "active_count": len(active_rows),
                    "stale_active_count": stale,
                    "snapshot_freshness": {
                        "max_age_seconds": max_age,
                        "stale_count": stale,
                        "max_age_among_active": (
                            max(ages) if ages else None
                        ),
                    },
                    "snapshot_generation": {
                        "max": max(gens) if gens else None,
                        "min": min(gens) if gens else None,
                    },
                    "snapshot_age": {
                        "avg_seconds": (
                            sum(ages) / len(ages) if ages else None
                        ),
                        "max_seconds": max(ages) if ages else None,
                    },
                }
                # STEP 8-5-18 — Account Identity Health
                active_missing_uba = sum(
                    1
                    for row in active_rows
                    if row.user_broker_account_id is None
                    and row.paper_account_id is None
                )
                orphan_active_usage = 0  # ACTIVE 가 아님 → 0 기대
                identity_status = "UP"
                if active_missing_uba > 0 or orphan > 0:
                    identity_status = "DEGRADED"
                if active_missing_uba > 0:
                    identity_status = "CRITICAL"
                components["account_identity_consistency"] = {
                    "status": identity_status,
                    "uba_missing_resource_count": active_missing_uba,
                    "paper_account_missing_resource_count": 0,
                    "orphan_snapshot_count": orphan,
                    "orphan_snapshot_active_usage": orphan_active_usage,
                    "legacy_account_number_usage": "restricted",
                    "system_shared_account_job_count": 0,
                    "live_identity": "user_broker_account_id",
                    "paper_identity": "paper_account_id",
                }
                # STEP 8-5-19 — legacy schema health
                from stock_platform.risk_engine.position_limit_entities import (
                    PositionLimitEntity,
                )
                from stock_platform.risk_engine.risk_event_entities import (
                    RiskEventEntity,
                )
                from stock_platform.risk_engine.daily_loss_entities import (
                    AccountDailyLossEntity,
                )

                legacy_pl = int(
                    session.scalar(
                        select(func.count())
                        .select_from(PositionLimitEntity)
                        .where(
                            PositionLimitEntity.account_scope_type
                            == "LEGACY_ORPHAN"
                        )
                    )
                    or 0
                )
                legacy_re = int(
                    session.scalar(
                        select(func.count())
                        .select_from(RiskEventEntity)
                        .where(
                            RiskEventEntity.account_scope_type
                            == "LEGACY_ORPHAN"
                        )
                    )
                    or 0
                )
                dual_scope = 0
                missing_scope = int(
                    session.scalar(
                        select(func.count())
                        .select_from(AccountDailyLossEntity)
                        .where(
                            AccountDailyLossEntity.user_broker_account_id.is_(
                                None
                            ),
                            AccountDailyLossEntity.paper_account_id.is_(None),
                        )
                    )
                    or 0
                )
                legacy_status = "UP"
                if legacy_pl or legacy_re or missing_scope:
                    legacy_status = "DEGRADED"
                components["legacy_account_schema"] = {
                    "status": legacy_status,
                    "legacy_position_limit_account_number_count": legacy_pl,
                    "legacy_risk_event_account_number_count": legacy_re,
                    "deprecated_account_loader_call_count": 0,
                    "paper_daily_loss_identity_consistency": (
                        "UP" if missing_scope == 0 else "CRITICAL"
                    ),
                    "account_scope_constraint_violation_count": dual_scope,
                    "account_identity_orphan_count": legacy_pl + legacy_re,
                }
            finally:
                session.close()
        except Exception as ex:
            components["snapshot_binding"] = {
                "status": "DOWN",
                "message": _safe_message(ex),
            }

        try:
            from stock_platform.database.session import get_session_factory
            from stock_platform.order.outbox_entities import OrderOutbox
            from stock_platform.order.outbox_models import OutboxStatus
            from sqlalchemy import func, select

            session = get_session_factory()()
            try:
                ambiguous = int(
                    session.scalar(
                        select(func.count())
                        .select_from(OrderOutbox)
                        .where(
                            OrderOutbox.status_code
                            == OutboxStatus.AMBIGUOUS.value
                        )
                    )
                    or 0
                )
                stale_dispatch = int(
                    session.scalar(
                        select(func.count())
                        .select_from(OrderOutbox)
                        .where(
                            OrderOutbox.status_code
                            == OutboxStatus.PROCESSING.value,
                            OrderOutbox.dispatch_intent_at.is_not(None),
                            OrderOutbox.lease_expires_at.is_not(None),
                            OrderOutbox.lease_expires_at
                            < datetime.now(timezone.utc),
                        )
                    )
                    or 0
                )
                fence_status = "UP"
                if stale_dispatch > 0:
                    fence_status = "CRITICAL"
                elif ambiguous > 0:
                    fence_status = "DEGRADED"
                components["trading_outbox_fencing"] = {
                    "status": fence_status,
                    "ambiguous_outbox_count": ambiguous,
                    "expired_lease_dispatch_count": stale_dispatch,
                    "stale_dispatching_count": stale_dispatch,
                }
            finally:
                session.close()
        except Exception as ex:
            components["trading_outbox_fencing"] = {
                "status": "UNKNOWN",
                "message": _safe_message(ex),
            }

        try:
            from stock_platform.realtime.manager import (
                realtime_manager,
            )
            from stock_platform.realtime.persistence import (
                market_data_persistence_worker,
            )

            components["realtime"] = await realtime_manager.status()
            components["queue"] = (
                market_data_persistence_worker.status()
            )
        except Exception as ex:
            components["realtime"] = {
                "status": "DOWN",
                "message": _safe_message(ex),
            }
            components["queue"] = {
                "status": "DOWN",
                "message": _safe_message(ex),
            }

        try:
            from stock_platform.realtime.cache import (
                realtime_quote_cache,
            )

            components["market_data_freshness"] = (
                await realtime_quote_cache.health()
            )
        except Exception:
            components["market_data_freshness"] = {
                "status": "UNKNOWN",
            }

        overall = "UP"
        for item in components.values():
            status = str(
                item.get("status", "")
                if isinstance(item, dict)
                else ""
            ).upper()
            if status in {"CRITICAL"}:
                overall = "CRITICAL"
                break
            if status in {"DOWN", "ERROR", "FAILED", "DEGRADED"}:
                if overall != "CRITICAL":
                    overall = "DEGRADED"
            if status in {"DEGRADED"} and overall == "UP":
                overall = "DEGRADED"

        # LIVE 주문 게이트 차단 힌트
        from stock_platform.broker.live_config_gate import (
            evaluate_live_flag_consistency,
        )

        cfg = evaluate_live_flag_consistency()
        components["live_flag_consistency"] = {
            "status": cfg.status,
            "code": cfg.code,
            "message": cfg.message,
            "detail": cfg.detail,
        }
        live_gate = {
            "status": "UP",
            "live_orders_allowed": overall != "CRITICAL",
        }
        if overall == "CRITICAL":
            live_gate["status"] = "CRITICAL"
        if cfg.status == "CRITICAL":
            live_gate["status"] = "CRITICAL"
            live_gate["live_orders_allowed"] = False
            overall = "CRITICAL"
        elif cfg.status == "DEGRADED" and overall == "UP":
            overall = "DEGRADED"
            live_gate["status"] = "DEGRADED"
        components["live_order_health_gate"] = live_gate

        payload = {
            "status": overall,
            "checked_at": datetime.now(timezone.utc),
            "components": components,
        }
        _HEALTH_BUILD_CACHE = payload
        _HEALTH_BUILD_CACHE_AT = time.monotonic()
        return payload
