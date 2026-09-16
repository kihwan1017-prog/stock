"""STEP 10-3 — Operations Center Dashboard Summary (Read-only)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.broker.recovery_conflict_constants import (
    ACTIVE_REVIEW_STATUSES,
)
from stock_platform.broker.recovery_conflict_entities import (
    BrokerRecoveryConflictEntity,
)
from stock_platform.common.settings import get_settings
from stock_platform.operation.db_pool_monitor import measure_db_latency_ms
from stock_platform.operation.ops_monitoring.service import (
    OpsMonitoringDashboardService,
)
from stock_platform.operation.ops_monitoring.status import compute_overall_status
from stock_platform.operation.resource_monitor import build_resource_monitoring
from stock_platform.operation.runtime_info import build_system_identity
from stock_platform.operation.startup_runtime_policy import migration_at_head
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.outbox_entities import OrderOutbox
from stock_platform.risk_engine.kill_switch_models import KillSwitchStatus
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.trading.account_models import PaperAccount, UserBrokerAccount

_KST = ZoneInfo("Asia/Seoul")
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_DEFAULT_TTL_SEC = 3.0


def _health_from_flags(
    *,
    errors: list[str],
    warnings: list[str],
) -> str:
    return compute_overall_status({"errors": errors, "warnings": warnings})


def _today_bounds_kst() -> tuple[datetime, datetime]:
    today = datetime.now(_KST).date()
    start = datetime(today.year, today.month, today.day, tzinfo=_KST)
    end = start.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


class OperationsCenterDashboardService:
    """Admin Operations Center — 단일 Summary API (조회 전용, Mutation 없음)."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._ops = OpsMonitoringDashboardService(session)

    def summary(self, *, cache_ttl_sec: float = _DEFAULT_TTL_SEC) -> dict[str, Any]:
        cache_key = "summary"
        now = time.monotonic()
        cached = _CACHE.get(cache_key)
        if cached and (now - cached[0]) < max(0.5, float(cache_ttl_sec)):
            payload = dict(cached[1])
            payload["cache"] = {"hit": True, "ttl_seconds": cache_ttl_sec}
            return payload

        checked_at = datetime.now(timezone.utc)
        overview = self._ops.overview()
        schedulers_payload = self._ops.schedulers()
        positions_payload = self._ops.positions()
        audits_payload = self._ops.audits(limit=100)
        accounts_payload = self._ops.accounts(include_broker_balances=False)

        trading_ctrl = self._trading_scheduler_status()
        runtime_payload = self._ops.runtimes()
        safety = self._safety_block()
        orders_today = self._orders_today()
        queues = self._queue_sizes()
        resources = build_resource_monitoring()
        identity = build_system_identity()
        db_status, db_latency_ms, db_err = measure_db_latency_ms()

        system = {
            "health": overview.get("overall_status", "UNKNOWN"),
            "api_status": "HEALTHY",
            "backend_version": identity.get("version"),
            "build_version": identity.get("build_version"),
            "git_commit": identity.get("git_commit"),
            "environment": identity.get("environment"),
            "database": {
                "status": "CONNECTED" if db_status == "UP" else "ERROR",
                "latency_ms": db_latency_ms,
                "detail": db_err,
            },
            "migration_head": migration_at_head(self._session),
            "server_time": checked_at.isoformat(),
            "timezone": identity.get("timezone"),
            "uptime_seconds": identity.get("uptime_seconds"),
            "cpu": resources.get("cpu"),
            "memory": resources.get("memory"),
            "disk": resources.get("disk"),
            "queue_size": queues.get("total_pending"),
            "outbox_queue": queues.get("outbox_pending"),
            "event_queue": queues.get("post_fill_pending"),
        }

        runtime = {
            "health": self._runtime_health(runtime_payload, trading_ctrl),
            "scheduler": trading_ctrl,
            "strategy_runtime": self._strategy_runtime_summary(runtime_payload),
            "recovery": (overview.get("schedulers") or {}).get("recovery"),
            "hub_runners": overview.get("runtime"),
        }

        scheduler_section = {
            "health": self._scheduler_section_health(schedulers_payload),
            "items": schedulers_payload.get("schedulers") or [],
            "next_runs": self._next_scheduler_runs(
                schedulers_payload.get("schedulers") or []
            ),
            "recent_failures": self._recent_scheduler_failures(
                schedulers_payload.get("schedulers") or []
            ),
        }

        broker = overview.get("brokers") or {}
        broker_enriched = self._enrich_brokers(broker, accounts_payload)

        accounts_summary = self._accounts_summary(accounts_payload)

        payload = {
            "checked_at": checked_at.isoformat(),
            "read_only": True,
            "system": system,
            "runtime": runtime,
            "scheduler": scheduler_section,
            "safety": safety,
            "broker": broker_enriched,
            "orders": orders_today,
            "accounts": accounts_summary,
            "positions": {
                "count": positions_payload.get("count", 0),
                "items": (positions_payload.get("positions") or [])[:50],
            },
            "audit": {
                "count": audits_payload.get("count", 0),
                "items": audits_payload.get("audits") or [],
            },
            "ai_providers": self._ai_providers_block(),
            "ai_prompt_meta": self._ai_prompt_meta_block(),
            "ai_executions": self._ai_executions_block(),
            "ai_document_analyses": self._ai_document_analyses_block(),
            "ai_market_analyses": self._ai_market_analyses_block(),
            "ai_candidate_assessments": self._ai_candidate_assessments_block(),
            "ai_candidate_consensuses": self._ai_candidate_consensuses_block(),
            "ai_candidate_recommendation_queues": (
                self._ai_candidate_recommendation_queues_block()
            ),
            "ai_candidate_promotions": self._ai_candidate_promotions_block(),
            "ai_candidate_lifecycle": self._ai_candidate_lifecycle_block(),
            "ai_reviews": self._ai_reviews_block(),
            "ai_benchmarks": self._ai_benchmarks_block(),
            "cache": {"hit": False, "ttl_seconds": cache_ttl_sec},
        }
        _CACHE[cache_key] = (now, payload)
        return payload

    def _ai_providers_block(self) -> dict[str, Any]:
        """STEP 11-1/11-3 — AI Provider 상태 (네트워크 실호출·Secret 복호화 없음)."""

        try:
            from stock_platform.ai.providers.manager import get_ai_manager

            block = get_ai_manager().dashboard_block()
        except Exception as exc:  # noqa: BLE001
            return {
                "health": "ERROR",
                "default_provider": None,
                "count": 0,
                "healthy_count": 0,
                "items": [],
                "error": type(exc).__name__,
                "external_calls_on_read": 0,
            }

        # DB 메타만 병합 (복호화/외부 호출 금지)
        try:
            from stock_platform.ai.providers.management_service import (
                AIProviderManagementService,
            )

            db_items = {
                str(item["provider_code"]): item
                for item in AIProviderManagementService(
                    self._session
                ).list_configurations()
            }
            for item in block.get("items") or []:
                if not isinstance(item, dict):
                    continue
                db = db_items.get(str(item.get("id")))
                if not db:
                    continue
                cred = db.get("credential") if isinstance(db.get("credential"), dict) else {}
                item["configuration_source"] = "DB"
                item["credential_status"] = cred.get("status")
                item["credential_verified_at"] = cred.get("verified_at")
                item["credential_expires_at"] = cred.get("expires_at")
                item["reload_required"] = db.get("reload_required")
                item["config_drift"] = db.get("config_drift")
                item["db_config_version"] = db.get("config_version")
                item["runtime_config_version"] = db.get(
                    "runtime_loaded_version"
                )
                item["last_reload_result"] = db.get("last_reload_result")
            if db_items:
                block["configuration_source"] = block.get(
                    "configuration_source"
                ) or "DB"
                block["runtime_loaded"] = True
        except Exception:  # noqa: BLE001
            # DB 미연결/미마이그레이션 시 Manager 스냅샷만 유지
            pass

        block["external_calls_on_read"] = 0
        return block

    def _ai_prompt_meta_block(self) -> dict[str, Any]:
        """STEP 11-4 — Prompt/Schema/Policy 집계만 (렌더·AI 호출 금지)."""

        try:
            from stock_platform.ai.prompt.management_service import (
                AIPromptManagementService,
            )

            stats = AIPromptManagementService(self._session).dashboard_stats()
            stats["external_calls_on_read"] = 0
            return stats
        except Exception as exc:  # noqa: BLE001
            return {
                "active_prompt_count": 0,
                "draft_prompt_count": 0,
                "active_policy_count": 0,
                "active_schema_count": 0,
                "error": type(exc).__name__,
                "external_calls_on_read": 0,
            }

    def _ai_executions_block(self) -> dict[str, Any]:
        """STEP 11-5 — 실행 집계만 (외부 AI 호출 0)."""

        try:
            from stock_platform.ai.execution.service import AIExecutionService

            stats = AIExecutionService(self._session).dashboard_stats()
            stats["external_calls_on_read"] = 0
            return stats
        except Exception as exc:  # noqa: BLE001
            return {
                "today_requests": 0,
                "running": 0,
                "queued": 0,
                "error": type(exc).__name__,
                "external_calls_on_read": 0,
            }

    def _ai_document_analyses_block(self) -> dict[str, Any]:
        """STEP 11-6 — 뉴스/공시 분석 집계 (외부 AI 호출 0, 자동 분석 없음)."""

        try:
            from stock_platform.ai.document_analysis.service import (
                AIDocumentAnalysisService,
            )

            stats = AIDocumentAnalysisService(self._session).dashboard_summary()
            stats["external_calls_on_read"] = 0
            return stats
        except Exception as exc:  # noqa: BLE001
            return {
                "news_analysis_today": 0,
                "disclosure_analysis_today": 0,
                "error": type(exc).__name__,
                "external_calls_on_read": 0,
            }

    def _ai_market_analyses_block(self) -> dict[str, Any]:
        """STEP 11-7 — 차트/시장 분석 집계 (외부 AI 호출 0)."""

        try:
            from stock_platform.ai.market_analysis.service import (
                AIMarketAnalysisService,
            )

            stats = AIMarketAnalysisService(self._session).dashboard_summary()
            stats["external_calls_on_read"] = 0
            return stats
        except Exception as exc:  # noqa: BLE001
            return {
                "chart_analysis_today": 0,
                "market_analysis_today": 0,
                "error": type(exc).__name__,
                "external_calls_on_read": 0,
            }

    def _ai_candidate_assessments_block(self) -> dict[str, Any]:
        """STEP 11-9 — AI 후보 평가 초안 집계 (매매 후보 카운트와 별도, 외부 AI 호출 0)."""

        try:
            from stock_platform.ai.candidate_assessment.service import (
                AICandidateAssessmentService,
            )

            stats = AICandidateAssessmentService(self._session).dashboard_summary()
            stats["external_calls_on_read"] = 0
            return stats
        except Exception as exc:  # noqa: BLE001
            return {
                "assessments_today": 0,
                "stock_assessments": 0,
                "crypto_assessments": 0,
                "error": type(exc).__name__,
                "external_calls_on_read": 0,
            }

    def _ai_candidate_consensuses_block(self) -> dict[str, Any]:
        """STEP 11-10 — Multi-AI Consensus 집계 (외부 AI 호출 0)."""

        try:
            from stock_platform.ai.candidate_consensus.service import (
                AIConsensusService,
            )

            stats = AIConsensusService(self._session).dashboard_summary()
            stats["external_calls_on_read"] = 0
            return stats
        except Exception as exc:  # noqa: BLE001
            return {
                "consensus_today": 0,
                "stock_consensus": 0,
                "crypto_consensus": 0,
                "error": type(exc).__name__,
                "external_calls_on_read": 0,
            }

    def _ai_candidate_recommendation_queues_block(self) -> dict[str, Any]:
        """STEP 11-11 — 후보 추천 검토 큐 집계 (외부 AI 호출 0, 상태 변경 없음)."""

        try:
            from stock_platform.ai.candidate_recommendation_queue.service import (
                AIRecommendationQueueService,
            )

            stats = AIRecommendationQueueService(
                self._session
            ).dashboard_summary()
            stats["external_calls_on_read"] = 0
            return stats
        except Exception as exc:  # noqa: BLE001
            return {
                "status_counts": {},
                "expiring_within_6h": 0,
                "error": type(exc).__name__,
                "external_calls_on_read": 0,
            }

    def _ai_candidate_promotions_block(self) -> dict[str, Any]:
        """STEP 11-12 — Candidate Promotion 집계 (외부 AI·상태변경 0)."""

        try:
            from stock_platform.ai.candidate_promotion.service import (
                AICandidatePromotionService,
            )

            stats = AICandidatePromotionService(self._session).dashboard_summary()
            stats["external_calls_on_read"] = 0
            return stats
        except Exception as exc:  # noqa: BLE001
            return {
                "status_counts": {},
                "completed_today": 0,
                "candidate_created_count": 0,
                "error": type(exc).__name__,
                "external_calls_on_read": 0,
            }

    def _ai_candidate_lifecycle_block(self) -> dict[str, Any]:
        """STEP 11-13 — Candidate Lifecycle 집계 (외부 AI·상태변경 0)."""

        try:
            from stock_platform.ai.candidate_lifecycle.service import (
                AICandidateLifecycleService,
            )

            stats = AICandidateLifecycleService(self._session).dashboard_summary()
            stats["external_calls_on_read"] = 0
            return stats
        except Exception as exc:  # noqa: BLE001
            return {
                "total": 0,
                "healthy": 0,
                "revalidation_required": 0,
                "error": type(exc).__name__,
                "external_calls_on_read": 0,
            }

    def _ai_reviews_block(self) -> dict[str, Any]:
        """STEP 11-8 — Human Review 집계 (외부 AI 호출 0)."""

        try:
            from stock_platform.ai.review.service import AIReviewService

            stats = AIReviewService(self._session).dashboard_summary()
            stats["external_calls_on_read"] = 0
            return stats
        except Exception as exc:  # noqa: BLE001
            return {
                "review_pending": 0,
                "error": type(exc).__name__,
                "external_calls_on_read": 0,
            }

    def _ai_benchmarks_block(self) -> dict[str, Any]:
        """STEP 11-8 — Benchmark 집계 (외부 AI 호출 0)."""

        try:
            from stock_platform.ai.review.benchmark_service import (
                AIBenchmarkService,
            )

            stats = AIBenchmarkService(self._session).dashboard_summary()
            stats["external_calls_on_read"] = 0
            return stats
        except Exception as exc:  # noqa: BLE001
            return {
                "benchmark_running": 0,
                "error": type(exc).__name__,
                "external_calls_on_read": 0,
            }

    def _trading_scheduler_status(self) -> dict[str, Any]:
        try:
            from stock_platform.trading.trading_scheduler_control_service import (
                TradingSchedulerControlService,
            )

            return TradingSchedulerControlService(self._session).status()
        except Exception as exc:  # noqa: BLE001
            return {
                "desired_state": "UNKNOWN",
                "actual_state": "UNKNOWN",
                "health": "OFFLINE",
                "blocked_reason": type(exc).__name__,
            }

    def _safety_block(self) -> dict[str, Any]:
        live_on = int(
            self._session.scalar(
                select(func.count())
                .select_from(UserBrokerAccount)
                .where(UserBrokerAccount.live_order_enabled.is_(True))
            )
            or 0
        )
        armed = int(
            self._session.scalar(
                select(func.count())
                .select_from(UserBrokerAccount)
                .where(UserBrokerAccount.live_armed.is_(True))
            )
            or 0
        )
        kill = KillSwitchService(self._session).get_state()
        submission_unknown = int(
            self._session.scalar(
                select(func.count())
                .select_from(TradingOrderEntity)
                .where(
                    TradingOrderEntity.status_code.in_(
                        ["AMBIGUOUS_SUBMISSION", "MANUAL_REVIEW_REQUIRED"]
                    )
                )
            )
            or 0
        )
        pending_conflict = int(
            self._session.scalar(
                select(func.count())
                .select_from(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.review_status.in_(
                        list(ACTIVE_REVIEW_STATUSES)
                    )
                )
            )
            or 0
        )
        account_pause = 0
        try:
            from stock_platform.broker.recovery_account_state import (
                BrokerRecoveryAccountStateEntity,
            )

            account_pause = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(BrokerRecoveryAccountStateEntity)
                    .where(
                        BrokerRecoveryAccountStateEntity.trading_paused.is_(True)
                    )
                )
                or 0
            )
        except Exception:  # noqa: BLE001
            pass

        errors: list[str] = []
        warnings: list[str] = []
        if kill.status == KillSwitchStatus.ACTIVE:
            errors.append("KILL_SWITCH")
        if live_on > 0:
            warnings.append("LIVE_ON")
        if armed > 0:
            warnings.append("ARMED")
        if submission_unknown > 0:
            errors.append("SUBMISSION_UNKNOWN")
        if pending_conflict > 0:
            warnings.append("PENDING_CONFLICT")

        return {
            "health": _health_from_flags(errors=errors, warnings=warnings),
            "live": {"enabled_count": live_on, "status": "ON" if live_on else "OFF"},
            "arm": {"armed_count": armed, "status": "ON" if armed else "OFF"},
            "kill_switch": {
                "active": kill.status == KillSwitchStatus.ACTIVE,
                "status": kill.status.value,
                "reason": kill.reason,
            },
            "submission_unknown": submission_unknown,
            "pending_conflict": pending_conflict,
            "recovery_conflict_open": pending_conflict,
            "account_pause_count": account_pause,
        }

    def _orders_today(self) -> dict[str, Any]:
        day_start, day_end = _today_bounds_kst()
        base = (
            select(TradingOrderEntity.status_code, func.count())
            .where(
                TradingOrderEntity.created_at >= day_start,
                TradingOrderEntity.created_at <= day_end,
            )
            .group_by(TradingOrderEntity.status_code)
        )
        counts: dict[str, int] = {}
        for status, cnt in self._session.execute(base):
            counts[str(status)] = int(cnt)

        filled_statuses = {"FILLED", "PARTIALLY_FILLED"}
        submitted = sum(counts.values())
        filled = sum(v for k, v in counts.items() if k in filled_statuses)
        partial = counts.get("PARTIALLY_FILLED", 0)
        cancelled = counts.get("CANCELLED", 0) + counts.get("CANCELED", 0)
        rejected = sum(
            v
            for k, v in counts.items()
            if "REJECT" in k or k in {"FAILED", "ERROR"}
        )

        amount_sum = self._session.scalar(
            select(
                func.coalesce(func.sum(TradingOrderEntity.filled_amount), 0),
            ).where(
                TradingOrderEntity.created_at >= day_start,
                TradingOrderEntity.created_at <= day_end,
                TradingOrderEntity.status_code.in_(list(filled_statuses)),
            )
        )
        trade_amount = Decimal(str(amount_sum or 0))

        return {
            "date_kst": datetime.now(_KST).date().isoformat(),
            "submitted": submitted,
            "filled": filled,
            "partial": partial,
            "cancelled": cancelled,
            "rejected": rejected,
            "trade_amount": str(trade_amount),
            "fee_total": None,
            "by_status": counts,
        }

    def _queue_sizes(self) -> dict[str, int]:
        outbox_pending = int(
            self._session.scalar(
                select(func.count())
                .select_from(OrderOutbox)
                .where(
                    OrderOutbox.status_code.in_(
                        ["PENDING", "RETRY", "PROCESSING"]
                    )
                )
            )
            or 0
        )
        post_fill_pending = 0
        try:
            from stock_platform.order.post_fill_verification_entities import (
                PostFillVerificationEntity,
            )

            post_fill_pending = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(PostFillVerificationEntity)
                    .where(
                        PostFillVerificationEntity.status_code.in_(
                            ["PENDING", "WAITING_SNAPSHOT", "VERIFYING"]
                        )
                    )
                )
                or 0
            )
        except Exception:  # noqa: BLE001
            pass
        return {
            "outbox_pending": outbox_pending,
            "post_fill_pending": post_fill_pending,
            "total_pending": outbox_pending + post_fill_pending,
        }

    def _accounts_summary(self, accounts_payload: dict[str, Any]) -> dict[str, Any]:
        rows = accounts_payload.get("accounts") or []
        total_krw = Decimal("0")
        total_eval = Decimal("0")
        for row in rows:
            bal = row.get("broker_balance") or {}
            if isinstance(bal, dict):
                krw = bal.get("KRW") or bal.get("krw")
                if isinstance(krw, dict):
                    total_krw += Decimal(str(krw.get("total") or krw.get("available") or 0))
            ev = row.get("evaluation_amount")
            if ev is not None:
                total_eval += Decimal(str(ev))
        return {
            "count": len(rows),
            "total_krw_estimate": str(total_krw),
            "total_evaluation_estimate": str(total_eval),
            "items": rows[:20],
        }

    def _enrich_brokers(
        self,
        brokers: dict[str, Any],
        accounts_payload: dict[str, Any],
    ) -> dict[str, Any]:
        rows = accounts_payload.get("accounts") or []
        counts: dict[str, int] = {}
        for row in rows:
            code = str(row.get("broker_code") or "UNKNOWN").upper()
            counts[code] = counts.get(code, 0) + 1

        paper_count = int(
            self._session.scalar(
                select(func.count()).select_from(PaperAccount)
            )
            or 0
        )

        out: dict[str, Any] = {}
        for code, row in brokers.items():
            out[code] = {
                **row,
                "health": row.get("status"),
                "connected": row.get("status") in {"HEALTHY", "CONFIGURED"},
                "account_count": counts.get(code, 0),
                "last_sync": None,
                "api_latency_ms": None,
            }
        out["PAPER"] = {
            "health": "HEALTHY",
            "status": "HEALTHY",
            "connected": True,
            "account_count": paper_count,
            "last_sync": None,
            "api_latency_ms": None,
        }
        return out

    def _strategy_runtime_summary(
        self, runtime_payload: dict[str, Any]
    ) -> dict[str, Any]:
        rows = runtime_payload.get("runtimes") or []
        running = sum(
            1
            for r in rows
            if str(r.get("state") or "").upper() in {"RUNNING", "ACTIVE"}
        )
        paused = sum(
            1
            for r in rows
            if str(r.get("state") or "").upper() in {"PAUSED", "PAUSE", "IDLE"}
        )
        state = "idle" if running == 0 else "running"
        return {
            "state": state,
            "running_count": running,
            "paused_count": paused,
            "total": len(rows),
        }

    def _runtime_health(
        self,
        runtime_payload: dict[str, Any],
        trading_ctrl: dict[str, Any],
    ) -> str:
        errors: list[str] = []
        warnings: list[str] = []
        if str(trading_ctrl.get("actual_state")).upper() not in {
            "RUNNING",
            "PAUSED",
        }:
            warnings.append("SCHEDULER")
        runtimes = runtime_payload.get("runtimes") or []
        if runtimes and any(
            str(r.get("state")).upper() == "ERROR"
            for r in runtimes
        ):
            errors.append("STRATEGY_RUNTIME_ERROR")
        return _health_from_flags(errors=errors, warnings=warnings)

    def _scheduler_section_health(self, schedulers_payload: dict[str, Any]) -> str:
        items = schedulers_payload.get("schedulers") or []
        errors = [
            i["scheduler_name"]
            for i in items
            if str(i.get("actual_state")).upper() in {"ERROR", "FAILED"}
        ]
        warnings = [
            i["scheduler_name"]
            for i in items
            if i.get("stale") or str(i.get("actual_state")).upper() == "STOPPED"
        ]
        return _health_from_flags(
            errors=[f"SCHED_{e}" for e in errors],
            warnings=[f"SCHED_{w}" for w in warnings],
        )

    def _next_scheduler_runs(
        self, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        upcoming = [
            {
                "name": i.get("scheduler_name"),
                "next_run_at": i.get("next_run_at"),
            }
            for i in items
            if i.get("next_run_at")
        ]
        return sorted(upcoming, key=lambda x: str(x.get("next_run_at") or ""))[:10]

    def _recent_scheduler_failures(
        self, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return [
            {
                "name": i.get("scheduler_name"),
                "last_failed_at": i.get("last_failed_at"),
                "last_error_code": i.get("last_error_code"),
                "consecutive_failures": i.get("consecutive_failures"),
            }
            for i in items
            if i.get("last_failed_at") or i.get("last_error_code")
        ][:10]


def clear_operations_center_cache() -> None:
    """테스트용 캐시 초기화."""

    _CACHE.clear()
