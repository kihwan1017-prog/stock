"""Telegram 운영 명령용 상태 집계 — 자동매매 로직 변경 없음."""

from __future__ import annotations

import os
import platform
import shutil
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.markets.repository import (
    PriceDailyRepository,
)
from stock_platform.markets.service import (
    InstrumentNotFoundError,
    PriceDailyService,
)
from stock_platform.notification.telegram_operations_notifier import (
    format_dashboard_summary_html,
)
from stock_platform.operation.health_service import (
    SystemHealthService,
)
from stock_platform.operation.operations_center_dashboard_service import (
    OperationsCenterDashboardService,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.models import OrderStatus
from stock_platform.risk_engine.kill_switch_service import (
    KillSwitchService,
)
from stock_platform.risk_engine.runtime import (
    realtime_risk_policy,
)
from stock_platform.trading.account_models import (
    PaperAccount,
    PaperPosition,
    UserBrokerAccount,
)


ZERO = Decimal("0")


class TelegramOpsStatusService:
    """/status /health /orders /positions 응답 텍스트 생성."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._settings = get_settings()
        self._prices = PriceDailyService(
            PriceDailyRepository(session)
        )
        self._dashboard = OperationsCenterDashboardService(session)

    def _summary(self) -> dict[str, Any]:
        return self._dashboard.summary(cache_ttl_sec=3)

    async def build_status_text(self) -> str:
        """STEP 10-3 Operations Center Summary 재사용."""
        return format_dashboard_summary_html(self._summary())

    def build_start_text(self) -> str:
        return "\n".join(
            [
                "<b>🛰 Telegram 운영센터</b>",
                "조회·알림·승인 전용 (자동 주문/LIVE/ARM 금지)",
                "",
                "/help — 명령 목록",
                "/status — 시스템 요약",
                "/ping — 연결 확인",
            ]
        )

    def build_ping_text(self) -> str:
        checked = self._summary().get("checked_at", "")
        return f"<b>🏓 PONG</b>\nserver_time={checked}"

    def build_version_text(self) -> str:
        system = self._summary().get("system") or {}
        return "\n".join(
            [
                "<b>📌 Version</b>",
                f"backend: {system.get('backend_version', 'dev')}",
                f"build: {system.get('build_version', 'n/a')}",
                f"commit: {system.get('git_commit', 'n/a')}",
                f"env: {system.get('environment', self._settings.app_env)}",
            ]
        )

    def build_runtime_text(self) -> str:
        summary = self._summary()
        runtime = summary.get("runtime") or {}
        safety = summary.get("safety") or {}
        lines = ["<b>⚙️ Runtime</b>"]
        sched = runtime.get("scheduler") or {}
        recovery = runtime.get("recovery") or {}
        lines.extend(
            [
                f"Scheduler desired: {sched.get('desired_state', 'n/a')}",
                f"Scheduler actual: {sched.get('actual_state', 'n/a')}",
                f"Recovery: {recovery.get('actual_state', 'n/a')}",
                f"LIVE: {(safety.get('live') or {}).get('status', 'OFF')}",
                f"ARM: {(safety.get('arm') or {}).get('status', 'OFF')}",
                (
                    "Kill Switch: "
                    f"{(safety.get('kill_switch') or {}).get('status', 'n/a')}"
                ),
            ]
        )
        return "\n".join(lines)

    def build_scheduler_text(self) -> str:
        summary = self._summary()
        sched_ctrl = (summary.get("runtime") or {}).get("scheduler") or {}
        sched_section = summary.get("scheduler") or {}
        lines = [
            "<b>📅 Scheduler</b>",
            f"Trading desired: {sched_ctrl.get('desired_state')}",
            f"Trading actual: {sched_ctrl.get('actual_state')}",
            f"Health: {sched_ctrl.get('health')}",
        ]
        blocked = sched_ctrl.get("blocked_reason")
        if blocked:
            lines.append(f"Blocked: {blocked}")
        items = sched_section.get("items") or []
        if items:
            lines.append(f"Hub jobs: {len(items)}")
        return "\n".join(lines)

    def build_broker_text(self) -> str:
        broker = self._summary().get("broker") or {}
        lines = ["<b>🏦 Broker</b>"]
        if not broker:
            lines.append("등록된 브로커 없음")
            return "\n".join(lines)
        for code, row in broker.items():
            if not isinstance(row, dict):
                continue
            health = row.get("health") or row.get("status")
            lines.append(f"{code}: {health}")
        return "\n".join(lines)

    def build_account_text(self) -> str:
        accounts = self._summary().get("accounts") or {}
        items = accounts.get("items") or []
        lines = [
            "<b>👤 Accounts</b>",
            f"Total: {accounts.get('count', len(items))}",
        ]
        for row in items[:15]:
            if not isinstance(row, dict):
                continue
            uba_id = row.get("user_broker_account_id") or row.get("id")
            broker = row.get("broker_code") or row.get("broker")
            live = row.get("live_order_enabled")
            arm = row.get("live_armed")
            lines.append(
                f"UBA {uba_id} {broker} LIVE={live} ARM={arm}"
            )
        return "\n".join(lines)

    def build_balance_text(self) -> str:
        rows = list(
            self._session.scalars(
                select(UserBrokerAccount).limit(10)
            )
        )
        lines = ["<b>💰 Balance (UBA snapshot)</b>"]
        if not rows:
            lines.append("UBA 없음")
            return "\n".join(lines)
        for uba in rows:
            lines.append(
                f"UBA {uba.id} {uba.broker_code} "
                f"live={uba.live_order_enabled} arm={uba.live_armed}"
            )
        paper = list(self._session.scalars(select(PaperAccount).limit(5)))
        for account in paper:
            lines.append(
                f"Paper {account.id} cash={account.cash_balance}"
            )
        return "\n".join(lines)

    def build_audit_text(self) -> str:
        audit = self._summary().get("audit") or {}
        items = audit.get("items") or []
        lines = [
            "<b>📋 Audit (recent)</b>",
            f"Count: {audit.get('count', len(items))}",
        ]
        for row in items[:10]:
            if not isinstance(row, dict):
                continue
            event = row.get("event_type") or row.get("action")
            actor = row.get("actor") or row.get("user")
            lines.append(f"• {event} — {actor}")
        return "\n".join(lines)

    def build_recovery_text(self) -> str:
        safety = self._summary().get("safety") or {}
        runtime = self._summary().get("runtime") or {}
        recovery = runtime.get("recovery") or {}
        lines = [
            "<b>🔁 Recovery</b>",
            f"State: {recovery.get('actual_state', 'n/a')}",
            f"Open conflicts: {safety.get('pending_conflict', 0)}",
            f"Submission unknown: {safety.get('submission_unknown', 0)}",
            f"Account pause: {safety.get('account_pause_count', 0)}",
        ]
        return "\n".join(lines)

    async def build_legacy_status_text(self) -> str:
        kill = KillSwitchService(self._session).get_state()
        health = await SystemHealthService().build()
        components = health.get("components") or {}
        db = components.get("database") or {}
        broker = components.get("kiwoom_rest") or {}
        scheduler = components.get("scheduler") or {}

        open_orders = self._count_open_orders()
        open_positions = self._count_open_positions()
        pnl = self._today_pnl_summary()
        jobs = self._running_jobs_hint()

        lines = [
            "<b>📊 System Status</b>",
            f"Server: {self._settings.app_name}",
            f"Version: {getattr(self._settings, 'app_version', 'dev')}",
            f"Env: {self._settings.app_env}",
            f"DB: {db.get('status', 'UNKNOWN')}",
            (
                f"Broker: {broker.get('status', 'UNKNOWN')}"
                f" (mock={self._settings.kiwoom_use_mock})"
            ),
            f"Scheduler: {scheduler.get('status', 'UNKNOWN')}",
            f"Running Jobs: {jobs}",
            f"Kill Switch: {kill.status.value}",
            (
                "Daily Loss Limit: "
                f"{realtime_risk_policy.max_daily_loss}"
            ),
            f"Today's PnL: {pnl}",
            f"Open Orders: {open_orders}",
            f"Open Positions: {open_positions}",
        ]
        return "\n".join(lines)

    async def build_health_text(self) -> str:
        health = await SystemHealthService().build()
        components = health.get("components") or {}
        resources = self._resource_snapshot()

        lines = [
            "<b>🩺 Health</b>",
            f"Overall: {health.get('status', 'UNKNOWN')}",
            f"CPU: {resources['cpu']}",
            f"Memory: {resources['memory']}",
            f"Disk: {resources['disk']}",
            (
                "DB: "
                f"{(components.get('database') or {}).get('status', 'UNKNOWN')}"
            ),
            (
                "Broker: "
                f"{(components.get('kiwoom_rest') or {}).get('status', 'UNKNOWN')}"
            ),
            (
                "Ollama: "
                f"{(components.get('ollama') or {}).get('status', 'UNKNOWN')}"
            ),
            (
                "Scheduler: "
                f"{(components.get('scheduler') or {}).get('status', 'UNKNOWN')}"
            ),
        ]
        return "\n".join(lines)

    def build_orders_text(self) -> str:
        today_start = datetime.combine(
            date.today(),
            time.min,
            tzinfo=timezone.utc,
        )
        rows = list(
            self._session.scalars(
                select(TradingOrderEntity).where(
                    TradingOrderEntity.created_at
                    >= today_start
                )
            )
        )
        filled = 0
        open_count = 0
        cancelled = 0
        rejected = 0
        for row in rows:
            status = (row.status_code or "").upper()
            if status == OrderStatus.FILLED.value:
                filled += 1
            elif status == OrderStatus.CANCELLED.value:
                cancelled += 1
            elif status in {
                OrderStatus.REJECTED.value,
                OrderStatus.FAILED.value,
            }:
                rejected += 1
            elif status not in {
                OrderStatus.FILLED.value,
                OrderStatus.CANCELLED.value,
                OrderStatus.REJECTED.value,
                OrderStatus.FAILED.value,
            }:
                open_count += 1

        lines = [
            "<b>🧾 Orders (today)</b>",
            f"Total: {len(rows)}",
            f"Filled: {filled}",
            f"Open / Working: {open_count}",
            f"Cancelled: {cancelled}",
            f"Rejected/Failed: {rejected}",
        ]
        return "\n".join(lines)

    def build_positions_text(self) -> str:
        positions = list(
            self._session.scalars(
                select(PaperPosition).where(
                    PaperPosition.quantity > ZERO
                )
            )
        )
        total_cost = ZERO
        total_value = ZERO
        lines = [
            "<b>📦 Positions</b>",
            f"Count: {len(positions)}",
        ]
        for pos in positions[:20]:
            price = self._current_price(
                pos.exchange_code,
                pos.symbol,
                pos.average_entry_price,
            )
            cost = pos.quantity * pos.average_entry_price
            value = pos.quantity * price
            pnl = value - cost
            total_cost += cost
            total_value += value
            lines.append(
                f"- {pos.symbol} qty={pos.quantity} "
                f"pnl={pnl.quantize(Decimal('0.01'))}"
            )

        unrealized = total_value - total_cost
        roi = (
            (unrealized / total_cost * Decimal("100"))
            if total_cost > ZERO
            else ZERO
        )
        lines.extend(
            [
                f"Unrealized PnL: {unrealized.quantize(Decimal('0.01'))}",
                f"Total Return %: {roi.quantize(Decimal('0.01'))}",
            ]
        )
        return "\n".join(lines)

    def build_system_text(self) -> str:
        settings = self._settings
        return "\n".join(
            [
                "<b>🖥 System</b>",
                f"App: {settings.app_name}",
                f"Env: {settings.app_env}",
                f"Timezone: {settings.app_timezone}",
                f"Platform: {platform.platform()}",
                f"PID: {os.getpid()}",
                (
                    "Telegram enabled: "
                    f"{settings.telegram_enabled}"
                ),
                (
                    "Telegram ops: "
                    f"{getattr(settings, 'telegram_ops_enabled', False)}"
                ),
            ]
        )

    def build_providers_text(self) -> str:
        summary = self._summary()
        block = summary.get("ai_providers") or {}
        items = block.get("items") or []
        lines = [
            "<b>🤖 AI Providers</b>",
            f"Health: {block.get('health', 'n/a')}",
            f"Default: {block.get('default_provider', 'n/a')}",
            f"Count: {block.get('count', 0)}",
        ]
        for row in items:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"• {row.get('id')} [{row.get('status')}] "
                f"model={row.get('model')} "
                f"caps={len(row.get('capabilities') or [])}"
            )
        return "\n".join(lines)

    async def build_provider_health_text(self) -> str:
        """캐시/스냅샷만 — 외부 AI 호출 없음."""

        from stock_platform.ai.providers.manager import get_ai_manager

        rows = get_ai_manager().cached_health_snapshot()
        lines = ["<b>🩺 Provider Health (cache)</b>"]
        for row in rows:
            lines.append(
                f"• {row.get('provider_id')}: {row.get('status')}"
                + (
                    f" ({row.get('latency_ms')}ms)"
                    if row.get("latency_ms") is not None
                    else ""
                )
            )
        return "\n".join(lines)

    def build_provider_detail_text(self, provider_id: str) -> str:
        if not provider_id:
            return "사용법: /provider &lt;name&gt;"
        summary = self._summary()
        block = summary.get("ai_providers") or {}
        items = block.get("items") or []
        for row in items:
            if not isinstance(row, dict):
                continue
            if str(row.get("id")) == provider_id:
                return "\n".join(
                    [
                        f"<b>Provider {provider_id}</b>",
                        f"Status: {row.get('status')}",
                        f"Enabled: {row.get('enabled')}",
                        f"Configured: {row.get('configured')}",
                        f"Model: {row.get('model')}",
                        f"Endpoint: {row.get('endpoint') or 'n/a'}",
                        f"Circuit: {row.get('circuit_state')}",
                        f"Latency: {row.get('latency_ms')}",
                        f"Source: {row.get('configuration_source') or block.get('configuration_source')}",
                        f"Credential: {row.get('credential_status') or 'n/a'}",
                        f"Reload Required: {row.get('reload_required')}",
                    ]
                )
        return f"Provider '{provider_id}' 없음"

    def build_provider_config_text(self, provider_id: str) -> str:
        """DB/ENV 설정 요약 — Secret·외부 호출 없음."""

        if not provider_id:
            return "사용법: /provider_config &lt;name&gt;"
        return self.build_provider_detail_text(provider_id)

    def build_ai_prompt_meta_text(self, kind: str) -> str:
        """Prompt/Policy/Schema 집계만 — 본문·수정·AI 호출 없음."""

        summary = self._summary()
        meta = summary.get("ai_prompt_meta") or {}
        title = {
            "prompts": "AI Prompts",
            "policies": "AI Policies",
            "schemas": "AI Schemas",
        }.get(kind, "AI Meta")
        return "\n".join(
            [
                f"<b>{title} (meta only)</b>",
                f"Active Prompts: {meta.get('active_prompt_count', 0)}",
                f"Draft Prompts: {meta.get('draft_prompt_count', 0)}",
                f"Active Policies: {meta.get('active_policy_count', 0)}",
                f"Active Schemas: {meta.get('active_schema_count', 0)}",
                "Raw templates/policies are not shown.",
            ]
        )

    def build_ai_executions_text(self) -> str:
        summary = self._summary()
        block = summary.get("ai_executions") or {}
        return "\n".join(
            [
                "<b>AI Executions (meta)</b>",
                f"Running: {block.get('running', 0)}",
                f"Queued: {block.get('queued', 0)}",
                f"Succeeded: {block.get('succeeded', 0)}",
                f"Failed: {block.get('failed', 0)}",
                f"Blocked: {block.get('blocked', 0)}",
                f"Today: {block.get('today_requests', 0)}",
                "Execute/Cancel from Telegram is forbidden.",
            ]
        )

    def build_ai_costs_text(self) -> str:
        summary = self._summary()
        block = summary.get("ai_executions") or {}
        return "\n".join(
            [
                "<b>AI Costs (estimate)</b>",
                f"Today Tokens: {block.get('today_tokens', 0)}",
                f"Today Est. Cost: {block.get('today_estimated_cost')}",
                "Not live billing. No FX conversion.",
            ]
        )

    def build_ai_news_text(self) -> str:
        summary = self._summary()
        block = summary.get("ai_document_analyses") or {}
        return "\n".join(
            [
                "<b>AI News Analysis (meta)</b>",
                f"Today analyzed: {block.get('news_analysis_today', 0)}",
                f"Succeeded: {block.get('succeeded', 0)}",
                f"Failed: {block.get('failed', 0)}",
                f"Blocked: {block.get('blocked', 0)}",
                f"Running: {block.get('running', 0)}",
                f"Warnings: {block.get('validation_warning', 0)}",
                "Execute/reanalyze from Telegram is forbidden.",
            ]
        )

    def build_ai_disclosures_text(self) -> str:
        summary = self._summary()
        block = summary.get("ai_document_analyses") or {}
        return "\n".join(
            [
                "<b>AI Disclosure Analysis (meta)</b>",
                f"Today analyzed: {block.get('disclosure_analysis_today', 0)}",
                f"Succeeded: {block.get('succeeded', 0)}",
                f"Failed: {block.get('failed', 0)}",
                f"Blocked: {block.get('blocked', 0)}",
                f"Running: {block.get('running', 0)}",
                f"Warnings: {block.get('validation_warning', 0)}",
                "Execute/reanalyze from Telegram is forbidden.",
            ]
        )

    def build_ai_charts_text(self) -> str:
        summary = self._summary()
        block = summary.get("ai_market_analyses") or {}
        return "\n".join(
            [
                "<b>AI Chart Analysis (meta)</b>",
                f"Today analyzed: {block.get('chart_analysis_today', 0)}",
                f"Running: {block.get('running', 0)}",
                f"Succeeded: {block.get('succeeded', 0)}",
                f"Failed: {block.get('failed', 0)}",
                f"Blocked: {block.get('blocked', 0)}",
                f"Data Quality Warning: {block.get('data_quality_warning', 0)}",
                "Execute from Telegram is forbidden.",
            ]
        )

    def build_ai_markets_text(self) -> str:
        summary = self._summary()
        block = summary.get("ai_market_analyses") or {}
        return "\n".join(
            [
                "<b>AI Market Analysis (meta)</b>",
                f"Today analyzed: {block.get('market_analysis_today', 0)}",
                f"Running: {block.get('running', 0)}",
                f"Succeeded: {block.get('succeeded', 0)}",
                f"Failed: {block.get('failed', 0)}",
                f"Blocked: {block.get('blocked', 0)}",
                f"Data Quality Warning: {block.get('data_quality_warning', 0)}",
                "Execute from Telegram is forbidden.",
            ]
        )

    def build_ai_reviews_text(self) -> str:
        """STEP 11-8 — Human Review 조회만 (승인/반려 금지)."""
        summary = self._summary()
        block = summary.get("ai_reviews") or {}
        return "\n".join(
            [
                "<b>AI Human Review (meta)</b>",
                f"Pending: {block.get('review_pending', 0)}",
                f"Assigned: {block.get('assigned', 0)}",
                f"Completed Today: {block.get('completed_today', 0)}",
                f"Approved (quality): {block.get('approved', 0)}",
                f"Rejected: {block.get('rejected', 0)}",
                f"Major Disagreement: {block.get('major_disagreement', 0)}",
                "AI 분석 품질 승인 ≠ 매매 승인.",
                "Submit/approve/reject from Telegram is forbidden.",
            ]
        )

    def build_ai_benchmarks_text(self) -> str:
        """STEP 11-8 — Benchmark 조회만 (실행 금지)."""
        summary = self._summary()
        block = summary.get("ai_benchmarks") or {}
        return "\n".join(
            [
                "<b>AI Benchmark (meta)</b>",
                f"Running: {block.get('benchmark_running', 0)}",
                f"Last Status: {block.get('last_benchmark_status') or '-'}",
                f"Last ID: {block.get('last_benchmark_id') or '-'}",
                "Execute/confirm from Telegram is forbidden.",
            ]
        )

    def build_ai_candidate_assessments_text(self) -> str:
        """STEP 11-9 — AI 후보 평가 초안 집계 (조회만, execute 금지)."""
        summary = self._summary()
        block = summary.get("ai_candidate_assessments") or {}
        return "\n".join(
            [
                "<b>AI Candidate Assessment (meta)</b>",
                f"Today: {block.get('assessments_today', 0)}",
                f"Stock: {block.get('stock_assessments', 0)} / Crypto: {block.get('crypto_assessments', 0)}",
                f"Running: {block.get('running', 0)} / Succeeded: {block.get('succeeded', 0)}",
                f"Review Pending: {block.get('review_pending', 0)}",
                f"Major Conflict: {block.get('major_conflict', 0)}",
                f"Low Evidence: {block.get('low_evidence_quality', 0)}",
                "Reference draft only — not trading candidates.",
                "Execute/confirm from Telegram is forbidden.",
            ]
        )

    def build_ai_consensus_text(self) -> str:
        """STEP 11-10 — Multi-AI Consensus 집계 (조회만, calculate/synthesize 금지)."""
        summary = self._summary()
        block = summary.get("ai_candidate_consensuses") or {}
        avg_conf = block.get("average_confidence")
        avg_conf_text = f"{avg_conf:.2f}" if isinstance(avg_conf, (int, float)) else "-"
        return "\n".join(
            [
                "<b>AI Candidate Consensus (meta)</b>",
                f"Today: {block.get('consensus_today', 0)}",
                f"Stock: {block.get('stock_consensus', 0)} / Crypto: {block.get('crypto_consensus', 0)}",
                f"Calculated: {block.get('calculated', 0)}",
                f"Review Pending: {block.get('review_pending', 0)}",
                f"Split/Weak: {block.get('split_or_weak', 0)}",
                f"Avg Confidence: {avg_conf_text}",
                "Reference draft only — not trading approval.",
                "Calculate/synthesize from Telegram is forbidden.",
            ]
        )

    def build_ai_candidate_queue_text(self) -> str:
        """STEP 11-11 — 후보 추천 검토 큐 집계 (조회만, create/decide 금지)."""
        summary = self._summary()
        block = summary.get("ai_candidate_recommendation_queues") or {}
        counts = block.get("status_counts") if isinstance(block.get("status_counts"), dict) else {}
        queued = int(counts.get("QUEUED") or 0)
        under_review = int(counts.get("UNDER_REVIEW") or 0)
        approved = int(counts.get("APPROVED_FOR_CONSIDERATION") or 0)
        approved_warn = int(counts.get("APPROVED_WITH_WARNINGS") or 0)
        return "\n".join(
            [
                "<b>AI Candidate Recommendation Queue (meta)</b>",
                f"Queued: {queued}",
                f"Under Review: {under_review}",
                f"Approved for Consideration: {approved}",
                f"Approved w/ Warnings: {approved_warn}",
                f"Expiring ≤6h: {block.get('expiring_within_6h', 0)}",
                "Internal review queue — not candidate registration or trading.",
                "Create/decide from Telegram is forbidden.",
            ]
        )

    def build_ai_candidate_promotions_text(self) -> str:
        """STEP 11-12 — Candidate Promotion 집계 (조회만, commit 금지)."""
        summary = self._summary()
        block = summary.get("ai_candidate_promotions") or {}
        counts = (
            block.get("status_counts")
            if isinstance(block.get("status_counts"), dict)
            else {}
        )
        return "\n".join(
            [
                "<b>AI Candidate Promotion Gateway (meta)</b>",
                f"Validated: {int(counts.get('VALIDATED') or 0) + int(counts.get('VALIDATED_WITH_WARNINGS') or 0)}",
                f"Dry-run: {int(counts.get('DRY_RUN_COMPLETED') or 0)}",
                f"First Pending: {int(counts.get('FIRST_APPROVAL_PENDING') or 0)}",
                f"Final Pending: {int(counts.get('FINAL_APPROVAL_PENDING') or 0)}",
                f"Commit Pending: {int(counts.get('COMMIT_PENDING') or 0)}",
                f"Completed Today: {block.get('completed_today', 0)}",
                f"Candidate Created: {block.get('candidate_created_count', 0)}",
                f"Blocked/Stale: {int(counts.get('BLOCKED') or 0)}/{int(counts.get('STALE') or 0)}",
                "Manual promotion only — not trading/strategy/order approval.",
                "Create/approve/commit from Telegram is forbidden.",
            ]
        )

    def build_ai_candidate_lifecycle_text(self) -> str:
        """STEP 11-13 — Candidate Lifecycle 집계 (조회만, mutate 금지)."""
        summary = self._summary()
        block = summary.get("ai_candidate_lifecycle") or {}
        return "\n".join(
            [
                "<b>AI Candidate Lifecycle (meta)</b>",
                f"Total: {block.get('total', 0)}",
                f"Healthy: {block.get('healthy', 0)}",
                f"Warning: {block.get('warning', 0)}",
                f"Revalidation Required: {block.get('revalidation_required', 0)}",
                f"Expiring ≤24h: {block.get('expiring_soon', 0)}",
                f"Expired: {block.get('expired', 0)}",
                f"Revoked: {block.get('revoked', 0)}",
                f"Superseded: {block.get('superseded', 0)}",
                f"Archived: {block.get('archived', 0)}",
                f"Source Changed: {block.get('source_changed', 0)}",
                f"Revocation Blocked: {block.get('revocation_blocked', 0)}",
                "Reference lifecycle only — not trading/strategy/order approval.",
                "Expire/revoke mutate from Telegram is forbidden.",
            ]
        )

    def build_help_text(self) -> str:
        return "\n".join(
            [
                "<b>🤖 Commands (Read-only)</b>",
                "/start — 환영·안내",
                "/status — Operations Center 요약",
                "/system — 프로세스·환경",
                "/runtime — Runtime·LIVE·ARM",
                "/scheduler — Trading Scheduler",
                "/broker — 브로커 헬스",
                "/account — 계정 목록",
                "/balance — 잔고 스냅샷",
                "/orders — 오늘 주문 요약",
                "/positions — 보유 포지션",
                "/audit — 최근 Audit",
                "/recovery — Recovery 상태",
                "/health — 헬스·리소스",
                "/providers — AI Provider 목록",
                "/provider_health — AI Provider Health (cache)",
                "/provider &lt;name&gt; — Provider 상세",
                "/provider_config &lt;name&gt; — Provider 설정 요약",
                "/ai_prompts — Prompt 집계",
                "/ai_policies — Policy 집계",
                "/ai_schemas — Schema 집계",
                "/ai_executions — Execution 집계",
                "/ai_costs — Cost 집계",
                "/ai_news — News Analysis 집계",
                "/ai_disclosures — Disclosure Analysis 집계",
                "/ai_charts — Chart Analysis 집계",
                "/ai_markets — Market Analysis 집계",
                "/ai_reviews — Human Review 집계",
                "/ai_benchmarks — Benchmark 집계",
                "/ai_candidate_assessments — 후보 평가 초안 집계",
                "/ai_consensus — Multi-AI 합의 초안 집계",
                "/ai_candidate_queue — 후보 추천 검토 큐 집계",
                "/ai_candidate_promotions — Candidate Promotion 집계",
                "/ai_candidate_lifecycle — Candidate Lifecycle 집계",
                "/version — 빌드 정보",
                "/ping — 연결 확인",
                "",
                "<b>⚠️ 승인 필요 (YES /confirm)</b>",
                "/kill — Kill Switch ON",
                "/resume — Kill Switch OFF",
                "/pause_scheduler — Scheduler PAUSE",
                "/start_scheduler &lt;uba_id&gt; — Scheduler START",
                "/help — 이 도움말",
            ]
        )

    def _count_open_orders(self) -> int:
        terminal = {
            OrderStatus.FILLED.value,
            OrderStatus.CANCELLED.value,
            OrderStatus.REJECTED.value,
            OrderStatus.FAILED.value,
        }
        rows = list(
            self._session.scalars(select(TradingOrderEntity))
        )
        return sum(
            1
            for row in rows
            if (row.status_code or "").upper() not in terminal
        )

    def _count_open_positions(self) -> int:
        return int(
            self._session.scalar(
                select(func.count()).select_from(
                    PaperPosition
                ).where(PaperPosition.quantity > ZERO)
            )
            or 0
        )

    def _today_pnl_summary(self) -> str:
        accounts = list(
            self._session.scalars(select(PaperAccount))
        )
        if not accounts:
            return "0 (no paper account)"
        realized = sum(
            (
                Decimal(account.realized_profit_loss)
                for account in accounts
            ),
            ZERO,
        )
        return str(realized.quantize(Decimal("0.01")))

    def _running_jobs_hint(self) -> str:
        from stock_platform.position.exit_monitor_runtime import (
            position_exit_monitor_manager,
        )
        from stock_platform.risk_engine.daily_loss_runtime import (
            daily_loss_monitor_manager,
        )

        exit_status = position_exit_monitor_manager.status()
        daily_status = daily_loss_monitor_manager.status()
        parts = []
        if exit_status.get("enabled"):
            parts.append("exit_monitor")
        if daily_status.get("loss_limit"):
            parts.append("daily_loss")
        return ", ".join(parts) if parts else "none"

    def _current_price(
        self,
        exchange_code: str,
        symbol: str,
        fallback: Decimal,
    ) -> Decimal:
        try:
            latest = self._prices.get_latest(
                exchange_code,
                symbol,
            )
        except (InstrumentNotFoundError, Exception):
            return fallback
        if latest is None:
            return fallback
        price = Decimal(str(latest.close_price))
        return price if price > ZERO else fallback

    @staticmethod
    def _resource_snapshot() -> dict[str, str]:
        disk = shutil.disk_usage(".")
        disk_pct = (
            (disk.used / disk.total) * 100
            if disk.total
            else 0.0
        )
        memory = "N/A"
        cpu = "N/A"
        try:
            import psutil  # type: ignore

            memory = (
                f"{psutil.virtual_memory().percent:.1f}%"
            )
            cpu = f"{psutil.cpu_percent(interval=0.0):.1f}%"
        except Exception:
            # stdlib fallback
            try:
                load = os.getloadavg()  # type: ignore[attr-defined]
                cpu = f"load={load[0]:.2f}"
            except (AttributeError, OSError):
                cpu = "unavailable"
            memory = "unavailable"

        return {
            "cpu": cpu,
            "memory": memory,
            "disk": f"{disk_pct:.1f}% used",
        }
