"""STEP 8-5-16 — Account Daily Settlement Service."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from stock_platform.broker.recovery_distributed_lock import (
    LockAcquireResult,
    LockOwnershipLostError,
    LockReleaseReason,
    build_distributed_lock_manager_from_settings,
)
from stock_platform.broker.recovery_distributed_lock_scope import (
    RecoveryAccountKind,
    RecoveryLockScope,
)
from stock_platform.broker.recovery_lock import RecoveryAccountLockService
from stock_platform.common.settings import Settings, get_settings
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.settlement.adapters_paper import PaperSettlementAdapter
from stock_platform.settlement.broker_adapter import SettlementBrokerBundle
from stock_platform.settlement.constants import (
    AMBIGUOUS_ORDER_STATUSES,
    CRITICAL_ISSUE_TYPES,
    OPEN_ORDER_STATUSES,
    SettlementIssueSeverity,
    SettlementIssueType,
    SettlementStatus,
    SettlementType,
)
from stock_platform.settlement.entities import (
    AccountDailySettlementEntity,
    AccountDailySettlementIssueEntity,
)
from stock_platform.settlement.pnl import compute_pnl, d, within_tolerance
from stock_platform.trading.account_models import PaperAccount, PaperPosition
from stock_platform.trading.execution_entities import TradingExecution

logger = logging.getLogger(__name__)


class AccountDailySettlementService:
    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()

    def settle_paper_account(
        self,
        *,
        paper_account_id: int,
        market_date: date,
        settlement_type: str,
        broker_code: str = "PAPER",
        calendar_revision: int | None = None,
        actor: str = "SYSTEM",
    ) -> AccountDailySettlementEntity:
        adapter = PaperSettlementAdapter(
            self._session, paper_account_id=paper_account_id
        )
        return self._settle(
            user_broker_account_id=None,
            paper_account_id=paper_account_id,
            broker_code=broker_code,
            market_date=market_date,
            settlement_type=settlement_type,
            calendar_revision=calendar_revision,
            bundle=adapter.fetch_bundle(),
            actor=actor,
            account_kind=RecoveryAccountKind.PAPER,
            account_id=paper_account_id,
        )

    def settle_uba(
        self,
        *,
        user_broker_account_id: int,
        broker_code: str,
        market_date: date,
        settlement_type: str,
        calendar_revision: int | None = None,
        actor: str = "SYSTEM",
        bundle: SettlementBrokerBundle | None = None,
    ) -> AccountDailySettlementEntity:
        if bundle is None:
            from stock_platform.settlement.adapters_live import (
                build_live_settlement_adapter,
            )

            bundle = build_live_settlement_adapter(
                self._session,
                user_broker_account_id=user_broker_account_id,
                broker_code=broker_code,
            ).fetch_bundle()
        return self._settle(
            user_broker_account_id=user_broker_account_id,
            paper_account_id=None,
            broker_code=broker_code.upper(),
            market_date=market_date,
            settlement_type=settlement_type,
            calendar_revision=calendar_revision,
            bundle=bundle,
            actor=actor,
            account_kind=RecoveryAccountKind.USER_BROKER,
            account_id=user_broker_account_id,
        )

    def _settle(
        self,
        *,
        user_broker_account_id: int | None,
        paper_account_id: int | None,
        broker_code: str,
        market_date: date,
        settlement_type: str,
        calendar_revision: int | None,
        bundle: SettlementBrokerBundle,
        actor: str,
        account_kind: RecoveryAccountKind,
        account_id: int,
    ) -> AccountDailySettlementEntity:
        settings = self._settings
        if not bool(getattr(settings, "settlement_enabled", True)):
            row = self._get_or_create(
                user_broker_account_id=user_broker_account_id,
                paper_account_id=paper_account_id,
                broker_code=broker_code,
                market_date=market_date,
                settlement_type=settlement_type,
                calendar_revision=calendar_revision,
            )
            row.status_code = SettlementStatus.SKIPPED.value
            row.result_code = "SETTLEMENT_DISABLED"
            row.result_summary = "settlement_enabled=false"
            row.completed_at = datetime.now(timezone.utc)
            self._session.flush()
            return row

        row = self._get_or_create(
            user_broker_account_id=user_broker_account_id,
            paper_account_id=paper_account_id,
            broker_code=broker_code,
            market_date=market_date,
            settlement_type=settlement_type,
            calendar_revision=calendar_revision,
        )
        now = datetime.now(timezone.utc)
        row.status_code = SettlementStatus.RUNNING.value
        row.started_at = now
        row.updated_at = now
        self._session.flush()

        # 기존 Issue 정리 (재실행)
        for old in list(
            self._session.scalars(
                select(AccountDailySettlementIssueEntity).where(
                    AccountDailySettlementIssueEntity.settlement_id
                    == int(row.settlement_id)
                )
            )
        ):
            self._session.delete(old)
        self._session.flush()

        lock_mgr = build_distributed_lock_manager_from_settings(settings)
        # Lock Key: ACCOUNT_SETTLEMENT + account_id + market_date
        scope = RecoveryLockScope(
            account_kind=account_kind,
            account_id=account_id,
            broker_code=broker_code,
            market_type=f"ACCOUNT_SETTLEMENT:{market_date.isoformat()}",
        )
        handle = None
        try:
            acquire_result, handle = lock_mgr.acquire(
                scope, session=self._session, timeout=2.0
            )
            if (
                handle is None
                or acquire_result
                not in {
                    LockAcquireResult.ACQUIRED,
                    LockAcquireResult.STALE_TAKEN_OVER,
                }
            ):
                self._session.add(
                    self._issue(
                        row,
                        SettlementIssueType.LOCK_NOT_ACQUIRED.value,
                        SettlementIssueSeverity.WARNING.value,
                        description="settlement lock busy — defer",
                    )
                )
                row.status_code = SettlementStatus.RETRY_PENDING.value
                row.retry_count = int(row.retry_count or 0) + 1
                row.next_retry_at = now + timedelta(
                    seconds=int(
                        getattr(
                            settings,
                            "settlement_retry_base_seconds",
                            60,
                        )
                    )
                )
                row.result_code = "LOCK_NOT_ACQUIRED"
                self._session.flush()
                return row

            issues: list[AccountDailySettlementIssueEntity] = []

            # --- Ambiguous / unresolved orders ---
            local_orders = self._local_orders(
                user_broker_account_id=user_broker_account_id,
                paper_account_id=paper_account_id,
                broker_code=broker_code,
            )
            ambiguous = [
                o
                for o in local_orders
                if str(o.status_code) in AMBIGUOUS_ORDER_STATUSES
            ]
            open_orders = [
                o
                for o in local_orders
                if str(o.status_code) in OPEN_ORDER_STATUSES
            ]
            row.open_order_count = len(open_orders)
            row.unresolved_order_count = len(ambiguous)
            if ambiguous:
                issues.append(
                    self._issue(
                        row,
                        SettlementIssueType.AMBIGUOUS_ORDER_PRESENT.value,
                        SettlementIssueSeverity.CRITICAL.value,
                        description=(
                            f"{len(ambiguous)} ambiguous/unresolved orders"
                        ),
                        local_value=str(len(ambiguous)),
                    )
                )

            # --- External sync ---
            if not bundle.sync_ok:
                issues.append(
                    self._issue(
                        row,
                        SettlementIssueType.BROKER_DATA_UNAVAILABLE.value,
                        SettlementIssueSeverity.CRITICAL.value,
                        description=bundle.sync_error or "sync failed",
                    )
                )
                row.external_sync_status = "FAILED"
            else:
                row.external_sync_status = "OK"

            row.external_snapshot_meta = {
                "fetched_at": bundle.fetched_at.isoformat(),
                "position_count": len(bundle.positions),
                "open_order_count": len(bundle.open_orders),
                "execution_count": len(bundle.executions),
                "equity": str(bundle.equity)
                if bundle.equity is not None
                else None,
                **(bundle.meta or {}),
            }

            # --- Positions (paper: internal vs bundle identical → expect match) ---
            pos_mismatches = self._reconcile_positions(
                row,
                paper_account_id=paper_account_id,
                user_broker_account_id=user_broker_account_id,
                bundle=bundle,
            )
            issues.extend(pos_mismatches)
            row.position_mismatch_count = len(
                [
                    i
                    for i in pos_mismatches
                    if i.issue_type
                    == SettlementIssueType.POSITION_QUANTITY_MISMATCH.value
                ]
            )
            row.position_reconciliation_status = (
                "MISMATCH" if pos_mismatches else "OK"
            )

            # --- Cash ---
            cash_issue = self._reconcile_cash(
                row,
                paper_account_id=paper_account_id,
                bundle=bundle,
            )
            if cash_issue is not None:
                issues.append(cash_issue)
                row.cash_reconciliation_status = "MISMATCH"
                row.cash_mismatch_amount = d(cash_issue.difference or 0)
            else:
                row.cash_reconciliation_status = "OK"
                row.cash_mismatch_amount = Decimal("0")

            # --- Executions (local uniqueness) ---
            exec_issues = self._reconcile_executions_local(
                row,
                user_broker_account_id=user_broker_account_id,
                paper_account_id=paper_account_id,
            )
            issues.extend(exec_issues)
            row.execution_reconciliation_status = (
                "MISMATCH" if exec_issues else "OK"
            )
            row.order_reconciliation_status = (
                "MISMATCH" if ambiguous else "OK"
            )

            # --- PnL ---
            realized = Decimal("0")
            unrealized = Decimal("0")
            fees = Decimal("0")
            if paper_account_id is not None:
                acct = self._session.get(PaperAccount, paper_account_id)
                if acct is not None:
                    realized = d(acct.realized_profit_loss)
            for p in bundle.positions:
                if p.unrealized_pnl is not None:
                    unrealized += d(p.unrealized_pnl)
            for ex in self._local_executions(
                user_broker_account_id=user_broker_account_id,
                paper_account_id=paper_account_id,
            ):
                raw = getattr(ex, "raw_json", None) or {}
                if isinstance(raw, dict):
                    fees += d(raw.get("fee") or raw.get("paid_fee") or 0)

            internal_equity = None
            if paper_account_id is not None and bundle.equity is not None:
                internal_equity = bundle.equity
            elif bundle.cash.total is not None:
                internal_equity = d(bundle.cash.total) + sum(
                    d(p.evaluation_amount or 0) for p in bundle.positions
                )

            opening = self._opening_equity(
                paper_account_id=paper_account_id,
                market_date=market_date,
            )
            pnl = compute_pnl(
                realized_pnl=realized,
                unrealized_pnl=unrealized,
                fees=fees,
                taxes=Decimal("0"),
                opening_equity=opening,
                closing_equity=internal_equity,
                net_deposit_withdrawal=None,
            )
            row.realized_pnl = pnl.realized_pnl
            row.unrealized_pnl = pnl.unrealized_pnl
            row.gross_pnl = pnl.gross_pnl
            row.fees = pnl.fees
            row.taxes = pnl.taxes
            row.net_pnl = pnl.net_pnl
            row.opening_equity = pnl.opening_equity
            row.closing_equity = pnl.closing_equity
            row.internal_equity = internal_equity
            row.external_equity = bundle.equity
            if (
                internal_equity is not None
                and bundle.equity is not None
            ):
                row.equity_difference = abs(
                    d(internal_equity) - d(bundle.equity)
                )
                eq_tol = d(settings.settlement_equity_tolerance_krw)
                if not within_tolerance(
                    d(internal_equity), d(bundle.equity), tolerance=eq_tol
                ):
                    issues.append(
                        self._issue(
                            row,
                            SettlementIssueType.EQUITY_MISMATCH.value,
                            SettlementIssueSeverity.CRITICAL.value,
                            local_value=str(internal_equity),
                            external_value=str(bundle.equity),
                            difference=str(row.equity_difference),
                            tolerance=str(eq_tol),
                        )
                    )
            if pnl.deposits_unknown:
                issues.append(
                    self._issue(
                        row,
                        SettlementIssueType.DEPOSITS_UNKNOWN.value,
                        SettlementIssueSeverity.INFO.value,
                        description=(
                            "입출금 원장이 없어 Equity 차이를 "
                            "일일 손익으로 단정하지 않음"
                        ),
                    )
                )
            row.pnl_calculation_status = "OK"

            for issue in issues:
                self._session.add(issue)
            self._session.flush()

            # Ownership 재검증
            try:
                lock_mgr.assert_owns(handle, session=self._session)
            except (LockOwnershipLostError, TypeError, Exception):
                try:
                    lock_mgr.assert_owns(handle)
                except Exception:  # noqa: BLE001
                    self._session.add(
                        self._issue(
                            row,
                            SettlementIssueType.LOCK_OWNERSHIP_LOST.value,
                            SettlementIssueSeverity.CRITICAL.value,
                            description=(
                                "fencing/ownership lost — not committing success"
                            ),
                        )
                    )
                    row.status_code = SettlementStatus.FAILED.value
                    row.result_code = "LOCK_OWNERSHIP_LOST"
                    row.completed_at = datetime.now(timezone.utc)
                    self._session.flush()
                    return row

            critical = [
                i
                for i in issues
                if i.severity == SettlementIssueSeverity.CRITICAL.value
                or i.issue_type in CRITICAL_ISSUE_TYPES
            ]
            warnings = [
                i
                for i in issues
                if i.severity == SettlementIssueSeverity.WARNING.value
            ]
            infos = [
                i
                for i in issues
                if i.severity == SettlementIssueSeverity.INFO.value
            ]

            if critical:
                row.status_code = (
                    SettlementStatus.MANUAL_REVIEW_REQUIRED.value
                )
                row.result_code = "CRITICAL_MISMATCH"
                row.result_summary = (
                    f"critical_issues={len(critical)}"
                )
                if bool(
                    getattr(
                        settings,
                        "settlement_pause_account_on_critical_mismatch",
                        True,
                    )
                ):
                    self._pause_account(
                        user_broker_account_id=user_broker_account_id,
                        paper_account_id=paper_account_id,
                        broker_code=broker_code,
                    )
            elif warnings:
                row.status_code = (
                    SettlementStatus.SUCCEEDED_WITH_WARNINGS.value
                )
                row.result_code = "WARNINGS"
                row.result_summary = f"warnings={len(warnings)}"
            else:
                row.status_code = SettlementStatus.SUCCEEDED.value
                row.result_code = "OK"
                row.result_summary = (
                    f"ok infos={len(infos)} positions={len(bundle.positions)}"
                )

            row.completed_at = datetime.now(timezone.utc)
            row.detail_payload = {
                "actor": actor,
                "issue_count": len(issues),
                "critical": len(critical),
                "warnings": len(warnings),
            }
            self._session.flush()
            self._audit(
                "ACCOUNT_SETTLEMENT_FINISHED",
                {
                    "settlement_id": int(row.settlement_id),
                    "status": row.status_code,
                    "broker_code": broker_code,
                    "market_date": market_date.isoformat(),
                },
            )
            return row
        finally:
            if handle is not None:
                try:
                    lock_mgr.release(
                        handle,
                        reason=LockReleaseReason.SUCCESS,
                        session=self._session,
                    )
                except TypeError:
                    try:
                        lock_mgr.release(
                            handle, reason=LockReleaseReason.SUCCESS
                        )
                    except Exception:  # noqa: BLE001
                        pass
                except Exception:  # noqa: BLE001
                    pass

    def resolve_issue(
        self,
        *,
        issue_id: int,
        resolved_by: str,
        note: str,
    ) -> AccountDailySettlementIssueEntity:
        issue = self._session.get(
            AccountDailySettlementIssueEntity, int(issue_id)
        )
        if issue is None:
            raise LookupError(f"issue not found: {issue_id}")
        issue.resolved = True
        issue.resolved_by = resolved_by[:150]
        issue.resolved_at = datetime.now(timezone.utc)
        issue.resolution_note = note[:1000]
        self._session.flush()
        return issue

    def list_settlements(
        self,
        *,
        market_date: date | None = None,
        status_code: str | None = None,
        limit: int = 100,
    ) -> list[AccountDailySettlementEntity]:
        stmt = select(AccountDailySettlementEntity).order_by(
            AccountDailySettlementEntity.market_date.desc(),
            AccountDailySettlementEntity.settlement_id.desc(),
        )
        if market_date is not None:
            stmt = stmt.where(
                AccountDailySettlementEntity.market_date == market_date
            )
        if status_code:
            stmt = stmt.where(
                AccountDailySettlementEntity.status_code == status_code
            )
        stmt = stmt.limit(limit)
        return list(self._session.scalars(stmt))

    def health_summary(self, *, market_date: date | None = None) -> dict:
        today = market_date or datetime.now(timezone.utc).date()
        rows = self.list_settlements(market_date=today, limit=500)
        by_status: dict[str, int] = {}
        for r in rows:
            by_status[r.status_code] = by_status.get(r.status_code, 0) + 1
        mismatch = sum(int(r.position_mismatch_count or 0) for r in rows)
        ambiguous = sum(int(r.unresolved_order_count or 0) for r in rows)
        cash_mismatch = sum(
            1
            for r in rows
            if abs(d(r.cash_mismatch_amount))
            > d(self._settings.settlement_cash_tolerance_krw)
        )
        incomplete = [
            r
            for r in rows
            if r.status_code
            in {
                SettlementStatus.PENDING.value,
                SettlementStatus.RUNNING.value,
                SettlementStatus.RETRY_PENDING.value,
                SettlementStatus.MANUAL_REVIEW_REQUIRED.value,
                SettlementStatus.FAILED.value,
            }
        ]
        oldest = None
        if incomplete:
            oldest_row = min(
                incomplete,
                key=lambda x: x.started_at
                or x.created_at
                or datetime.now(timezone.utc),
            )
            oldest = {
                "settlement_id": int(oldest_row.settlement_id),
                "status_code": oldest_row.status_code,
                "started_at": (
                    oldest_row.started_at.isoformat()
                    if oldest_row.started_at
                    else None
                ),
            }
        last_ok = self._session.scalar(
            select(AccountDailySettlementEntity)
            .where(
                AccountDailySettlementEntity.status_code.in_(
                    [
                        SettlementStatus.SUCCEEDED.value,
                        SettlementStatus.SUCCEEDED_WITH_WARNINGS.value,
                    ]
                )
            )
            .order_by(AccountDailySettlementEntity.completed_at.desc())
            .limit(1)
        )
        last_fail = self._session.scalar(
            select(AccountDailySettlementEntity)
            .where(
                AccountDailySettlementEntity.status_code.in_(
                    [
                        SettlementStatus.FAILED.value,
                        SettlementStatus.MANUAL_REVIEW_REQUIRED.value,
                    ]
                )
            )
            .order_by(AccountDailySettlementEntity.completed_at.desc())
            .limit(1)
        )
        return {
            "market_date": today.isoformat(),
            "total": len(rows),
            "by_status": by_status,
            "position_mismatch_total": mismatch,
            "cash_mismatch_count": cash_mismatch,
            "unresolved_ambiguous_total": ambiguous,
            "manual_review": by_status.get(
                SettlementStatus.MANUAL_REVIEW_REQUIRED.value, 0
            ),
            "failed": by_status.get(SettlementStatus.FAILED.value, 0),
            "warnings": by_status.get(
                SettlementStatus.SUCCEEDED_WITH_WARNINGS.value, 0
            ),
            "succeeded": by_status.get(SettlementStatus.SUCCEEDED.value, 0)
            + by_status.get(
                SettlementStatus.SUCCEEDED_WITH_WARNINGS.value, 0
            ),
            "oldest_incomplete": oldest,
            "last_success_at": (
                last_ok.completed_at.isoformat()
                if last_ok and last_ok.completed_at
                else None
            ),
            "last_failure_at": (
                last_fail.completed_at.isoformat()
                if last_fail and last_fail.completed_at
                else None
            ),
            "enabled": bool(self._settings.settlement_enabled),
        }

    # ------------------------------------------------------------------
    def _get_or_create(
        self,
        *,
        user_broker_account_id: int | None,
        paper_account_id: int | None,
        broker_code: str,
        market_date: date,
        settlement_type: str,
        calendar_revision: int | None,
    ) -> AccountDailySettlementEntity:
        clauses = [
            AccountDailySettlementEntity.market_date == market_date,
            AccountDailySettlementEntity.settlement_type == settlement_type,
        ]
        if user_broker_account_id is not None:
            clauses.append(
                AccountDailySettlementEntity.user_broker_account_id
                == int(user_broker_account_id)
            )
        else:
            clauses.append(
                AccountDailySettlementEntity.paper_account_id
                == int(paper_account_id or 0)
            )
        existing = self._session.scalar(
            select(AccountDailySettlementEntity).where(and_(*clauses))
        )
        if existing is not None:
            if calendar_revision is not None:
                existing.calendar_revision = int(calendar_revision)
            return existing
        row = AccountDailySettlementEntity(
            user_broker_account_id=user_broker_account_id,
            paper_account_id=paper_account_id,
            broker_code=broker_code.upper(),
            market_date=market_date,
            calendar_revision=calendar_revision,
            settlement_type=settlement_type,
            status_code=SettlementStatus.PENDING.value,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def _local_orders(
        self,
        *,
        user_broker_account_id: int | None,
        paper_account_id: int | None,
        broker_code: str,
    ) -> list[TradingOrderEntity]:
        stmt = select(TradingOrderEntity)
        if user_broker_account_id is not None:
            stmt = stmt.where(
                TradingOrderEntity.user_broker_account_id
                == int(user_broker_account_id)
            )
        elif paper_account_id is not None:
            # Paper 주문은 paper_account_id 컬럼이 있을 수 있음
            if hasattr(TradingOrderEntity, "paper_account_id"):
                stmt = stmt.where(
                    TradingOrderEntity.paper_account_id
                    == int(paper_account_id)
                )
            else:
                return []
        else:
            return []
        if broker_code.upper() != "PAPER":
            stmt = stmt.where(
                TradingOrderEntity.broker_code == broker_code.upper()
            )
        return list(self._session.scalars(stmt.limit(5000)))

    def _local_executions(
        self,
        *,
        user_broker_account_id: int | None,
        paper_account_id: int | None,
    ) -> list[TradingExecution]:
        orders = self._local_orders(
            user_broker_account_id=user_broker_account_id,
            paper_account_id=paper_account_id,
            broker_code="PAPER"
            if paper_account_id
            else "KIWOOM",
        )
        if not orders:
            return []
        order_ids = [int(o.order_id) for o in orders]
        return list(
            self._session.scalars(
                select(TradingExecution).where(
                    TradingExecution.order_id.in_(order_ids)
                )
            )
        )

    def _reconcile_positions(
        self,
        row: AccountDailySettlementEntity,
        *,
        paper_account_id: int | None,
        user_broker_account_id: int | None,
        bundle: SettlementBrokerBundle,
    ) -> list[AccountDailySettlementIssueEntity]:
        issues: list[AccountDailySettlementIssueEntity] = []
        qty_tol = d(0)  # 수량은 기본 0
        avg_tol = d(self._settings.settlement_average_price_tolerance_krw)

        local_map: dict[str, Decimal] = {}
        local_avg: dict[str, Decimal] = {}
        if paper_account_id is not None:
            for p in self._session.scalars(
                select(PaperPosition).where(
                    PaperPosition.account_id == int(paper_account_id)
                )
            ):
                key = f"{p.exchange_code}:{p.symbol}".upper()
                local_map[key] = d(p.quantity)
                local_avg[key] = d(p.average_entry_price)

        ext_map = {
            f"{p.exchange_code}:{p.symbol}".upper(): p
            for p in bundle.positions
        }
        # Paper: local == external (same source) → should match
        keys = set(local_map) | set(ext_map)
        for key in keys:
            local_q = local_map.get(key, Decimal("0"))
            ext = ext_map.get(key)
            ext_q = d(ext.quantity) if ext else Decimal("0")
            if not within_tolerance(local_q, ext_q, tolerance=qty_tol):
                issues.append(
                    self._issue(
                        row,
                        SettlementIssueType.POSITION_QUANTITY_MISMATCH.value,
                        SettlementIssueSeverity.CRITICAL.value,
                        symbol=key,
                        local_value=str(local_q),
                        external_value=str(ext_q),
                        difference=str(abs(local_q - ext_q)),
                        tolerance=str(qty_tol),
                    )
                )
            elif (
                ext is not None
                and ext.average_price is not None
                and key in local_avg
            ):
                if not within_tolerance(
                    local_avg[key], d(ext.average_price), tolerance=avg_tol
                ):
                    issues.append(
                        self._issue(
                            row,
                            SettlementIssueType.POSITION_AVERAGE_PRICE_MISMATCH.value,
                            SettlementIssueSeverity.WARNING.value,
                            symbol=key,
                            local_value=str(local_avg[key]),
                            external_value=str(ext.average_price),
                            tolerance=str(avg_tol),
                        )
                    )
        return issues

    def _reconcile_cash(
        self,
        row: AccountDailySettlementEntity,
        *,
        paper_account_id: int | None,
        bundle: SettlementBrokerBundle,
    ) -> AccountDailySettlementIssueEntity | None:
        cash_tol = d(self._settings.settlement_cash_tolerance_krw)
        local_cash = Decimal("0")
        if paper_account_id is not None:
            acct = self._session.get(PaperAccount, paper_account_id)
            if acct is not None:
                local_cash = d(acct.available_cash)
        else:
            # LIVE: 내부 별도 cash ledger가 없으면 external만 기록
            return None
        ext_cash = d(bundle.cash.available)
        if not within_tolerance(local_cash, ext_cash, tolerance=cash_tol):
            return self._issue(
                row,
                SettlementIssueType.CASH_BALANCE_MISMATCH.value,
                SettlementIssueSeverity.CRITICAL.value,
                local_value=str(local_cash),
                external_value=str(ext_cash),
                difference=str(abs(local_cash - ext_cash)),
                tolerance=str(cash_tol),
            )
        return None

    def _reconcile_executions_local(
        self,
        row: AccountDailySettlementEntity,
        *,
        user_broker_account_id: int | None,
        paper_account_id: int | None,
    ) -> list[AccountDailySettlementIssueEntity]:
        """Broker Fill ID 중복 탐지."""

        executions = self._local_executions(
            user_broker_account_id=user_broker_account_id,
            paper_account_id=paper_account_id,
        )
        seen: dict[str, int] = {}
        issues: list[AccountDailySettlementIssueEntity] = []
        for ex in executions:
            key = f"{ex.broker_code}:{ex.broker_execution_id}"
            if key in seen:
                issues.append(
                    self._issue(
                        row,
                        SettlementIssueType.EXECUTION_DUPLICATE.value,
                        SettlementIssueSeverity.CRITICAL.value,
                        description=f"duplicate fill {key}",
                        local_value=key,
                    )
                )
            seen[key] = int(ex.execution_id)
        return issues

    def _opening_equity(
        self,
        *,
        paper_account_id: int | None,
        market_date: date,
    ) -> Decimal | None:
        if paper_account_id is None:
            return None
        # 직전 성공 Settlement closing_equity
        prev = self._session.scalar(
            select(AccountDailySettlementEntity)
            .where(
                AccountDailySettlementEntity.paper_account_id
                == int(paper_account_id),
                AccountDailySettlementEntity.market_date < market_date,
                AccountDailySettlementEntity.status_code.in_(
                    [
                        SettlementStatus.SUCCEEDED.value,
                        SettlementStatus.SUCCEEDED_WITH_WARNINGS.value,
                    ]
                ),
            )
            .order_by(AccountDailySettlementEntity.market_date.desc())
            .limit(1)
        )
        if prev is not None and prev.closing_equity is not None:
            return d(prev.closing_equity)
        acct = self._session.get(PaperAccount, paper_account_id)
        if acct is not None:
            return d(acct.initial_cash)
        return None

    def _pause_account(
        self,
        *,
        user_broker_account_id: int | None,
        paper_account_id: int | None,
        broker_code: str,
    ) -> None:
        if user_broker_account_id is None:
            return
        try:
            from stock_platform.broker.recovery_account_state import (
                BrokerRecoveryAccountStateEntity,
            )
            from stock_platform.broker.recovery_adapter import (
                AccountRecoveryContext,
            )

            ctx = AccountRecoveryContext(
                broker_code=broker_code.upper(),
                market_type="ALL",
                user_broker_account_id=int(user_broker_account_id),
                paper_account_id=None,
                user_id=None,
            )
            svc = RecoveryAccountLockService(self._session)
            row = svc._find(ctx)
            now = datetime.now(timezone.utc)
            if row is None:
                row = BrokerRecoveryAccountStateEntity(
                    broker_code=broker_code.upper(),
                    user_broker_account_id=int(user_broker_account_id),
                )
                self._session.add(row)
            row.trading_paused = True
            row.last_error_summary = "SETTLEMENT_CRITICAL_MISMATCH"[:200]
            row.updated_at = now
            self._session.flush()
            self._audit(
                "ACCOUNT_SETTLEMENT_PAUSE",
                {
                    "user_broker_account_id": int(user_broker_account_id),
                    "broker_code": broker_code,
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception("settlement_pause_failed")

    def _issue(
        self,
        row: AccountDailySettlementEntity,
        issue_type: str,
        severity: str,
        *,
        symbol: str | None = None,
        local_value: str | None = None,
        external_value: str | None = None,
        difference: str | None = None,
        tolerance: str | None = None,
        description: str | None = None,
    ) -> AccountDailySettlementIssueEntity:
        return AccountDailySettlementIssueEntity(
            settlement_id=int(row.settlement_id),
            issue_type=issue_type,
            severity=severity,
            symbol=symbol,
            local_value=local_value,
            external_value=external_value,
            difference=difference,
            tolerance=tolerance,
            description=description,
        )

    def _add_issue(self, row, **kwargs) -> None:
        self._session.add(self._issue(row, **kwargs))
        self._session.flush()

    def _audit(self, event_type: str, detail: dict[str, Any]) -> None:
        try:
            from stock_platform.operation.calendar_audit import (
                audit_calendar_event,
            )

            audit_calendar_event(event_type, detail=detail)
        except Exception:  # noqa: BLE001
            pass
