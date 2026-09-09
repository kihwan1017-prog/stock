"""STEP 8-4 — Upbit Recovery Adapter (STEP 8-5-2/8-5-4)."""

from __future__ import annotations

import asyncio

from stock_platform.broker.credential_adapter_factory import (
    build_upbit_private_client_for_uba,
    build_upbit_settings_from_vault,
)
from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultError,
    BrokerCredentialVaultService,
)
from stock_platform.broker.recovery_adapter import (
    AccountRecoveryContext,
    AdapterRecoveryResult,
)
from stock_platform.broker.recovery_conflict_service import (
    BrokerRecoveryConflictService,
)
from stock_platform.broker.upbit.account_factory import (
    build_upbit_private_client,
)
from stock_platform.broker.upbit.account_sync_service import (
    UpbitAccountSyncService,
)
from stock_platform.broker.upbit.order_client import UpbitOrderRestClient
from stock_platform.broker.upbit.order_reconcile_service import (
    UpbitOrderReconcileService,
)
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory


class UpbitRecoveryAdapter:
    broker_code = "UPBIT"

    def supports(self, context: AccountRecoveryContext) -> bool:
        return context.broker_code.upper() == "UPBIT"

    async def recover(
        self, context: AccountRecoveryContext
    ) -> AdapterRecoveryResult:
        result = AdapterRecoveryResult(
            status="SUCCESS",
            broker_code=self.broker_code,
            paper_account_id=context.paper_account_id,
            user_broker_account_id=context.user_broker_account_id,
            user_id=context.user_id,
        )
        settings = get_settings()
        session = get_session_factory()()
        try:
            order_client: UpbitOrderRestClient | None = None
            if context.user_broker_account_id is not None:
                try:
                    private = build_upbit_private_client_for_uba(
                        session,
                        int(context.user_broker_account_id),
                    )
                    resolved = BrokerCredentialVaultService(
                        session
                    ).resolve_for_runtime(
                        int(context.user_broker_account_id),
                        expected_broker="UPBIT",
                        require_verified=True,
                        touch_last_used=True,
                    )
                    order_client = UpbitOrderRestClient(
                        settings=build_upbit_settings_from_vault(
                            resolved
                        ),
                        user_broker_account_id=int(
                            context.user_broker_account_id
                        ),
                    )
                except BrokerCredentialVaultError as exc:
                    result.status = "FAILED"
                    result.errors.append(exc.code)
                    result.detail["credential_error"] = {
                        "code": exc.code,
                        "message": exc.message,
                    }
                    result.trading_should_remain_paused = True
                    result.retry_required = True
                    return result.finish()
            else:
                if settings.upbit_use_mock:
                    result.status = "SKIPPED"
                    result.warnings.append("UPBIT_USE_MOCK=true")
                    return result.finish()
                private = build_upbit_private_client(
                    require_credentials=True
                )
                order_client = UpbitOrderRestClient(settings=settings)

            sync = await UpbitAccountSyncService(
                session=session,
                private_client=private,
                user_broker_account_id=context.user_broker_account_id,
            ).synchronize(
                user_broker_account_id=context.user_broker_account_id
            )
            result.balances_updated = 1
            result.positions_updated = int(
                sync.get("position_count")
                or len(sync.get("positions") or [])
                or 0
            )
            result.detail["account_sync"] = {
                "broker_account_snapshot_id": sync.get(
                    "broker_account_snapshot_id"
                ),
                "deposit_amount": sync.get("deposit_amount"),
            }

            uba_id = context.user_broker_account_id

            def _reconcile() -> dict:
                return UpbitOrderReconcileService(
                    session, order_client=order_client
                ).reconcile_open_orders(
                    limit=50,
                    user_broker_account_id=uba_id,
                )

            reconcile = await asyncio.to_thread(_reconcile)
            result.open_orders_checked = int(
                reconcile.get("checked") or 0
            )
            result.orders_updated = int(
                reconcile.get("updated") or 0
            )
            remote_only_orders = list(
                reconcile.get("remote_only_orders") or []
            )
            remote_only = int(
                reconcile.get("remote_only")
                or len(remote_only_orders)
                or 0
            )
            conflicts = 0
            account_pause_conflicts = 0
            if remote_only and not context.allow_auto_create_external_orders:
                conflict_svc = BrokerRecoveryConflictService(session)
                try:
                    from stock_platform.trading.symbol_ownership import (
                        SymbolOwnershipService,
                    )
                    from stock_platform.trading.symbol_ownership.constants import (
                        CONFLICT_SAME_SYMBOL_MANUAL_AUTO,
                    )

                    ownership_svc = SymbolOwnershipService(session)
                except Exception:  # noqa: BLE001
                    ownership_svc = None
                    CONFLICT_SAME_SYMBOL_MANUAL_AUTO = (
                        "SAME_SYMBOL_MANUAL_AUTO_CONFLICT"
                    )

                for remote in remote_only_orders:
                    market = str(remote.get("market") or "").strip().upper()
                    classification = None
                    if ownership_svc is not None and market and uba_id:
                        classification = ownership_svc.classify_remote_order(
                            broker_code="UPBIT",
                            user_broker_account_id=int(uba_id),
                            symbol=market,
                        )
                    row = conflict_svc.upsert_remote_only(
                        remote=remote,
                        user_id=context.user_id,
                        user_broker_account_id=uba_id,
                        recovery_run_id=None,
                        broker_code="UPBIT",
                    )
                    if row is not None and classification is not None:
                        from stock_platform.broker.recovery_conflict_constants import (
                            RecoveryConflictReviewStatus,
                            RecoveryConflictResolution,
                        )

                        row.risk_level = classification.risk_level
                        if classification.conflict_kind == (
                            CONFLICT_SAME_SYMBOL_MANUAL_AUTO
                        ):
                            row.conflict_type = CONFLICT_SAME_SYMBOL_MANUAL_AUTO
                            row.review_status = (
                                RecoveryConflictReviewStatus.ON_HOLD
                            )
                            ownership_svc.activate_same_symbol_hold(
                                broker_code="UPBIT",
                                user_broker_account_id=int(uba_id),
                                symbol=market,
                                reason_code=CONFLICT_SAME_SYMBOL_MANUAL_AUTO,
                                detail=classification.to_dict(),
                            )
                            _notify_same_symbol_conflict(market)
                        elif not classification.pause_account:
                            # MANUAL remote activity — 계좌 pause/resume 차단 금지
                            row.pause_reason = classification.conflict_kind
                            # INFO 등 비허용 risk_level 은 CHECK 위반으로 flush 실패 →
                            # recovery FAILED + trading_paused 고착을 막기 위해 clamp
                            allowed_risk = {
                                "LOW",
                                "MEDIUM",
                                "HIGH",
                                "CRITICAL",
                            }
                            risk = str(
                                classification.risk_level or "LOW"
                            ).upper()
                            row.risk_level = (
                                risk if risk in allowed_risk else "LOW"
                            )
                            row.review_status = (
                                RecoveryConflictReviewStatus.IGNORED
                            )
                            row.resolution_type = (
                                RecoveryConflictResolution.IGNORE_EXTERNAL_ORDER
                            )
                            row.resolution_note = (
                                "REMOTE_MANUAL_ACTIVITY_NO_ACCOUNT_PAUSE"
                            )
                        session.flush()
                        if classification.pause_account:
                            account_pause_conflicts += 1
                    elif row is not None:
                        account_pause_conflicts += 1

                # 활성 검토 Conflict 수 (대시보드용)
                if uba_id is not None:
                    conflicts = conflict_svc.count_active_for_uba(int(uba_id))
                else:
                    conflicts = int(remote_only)
                # 계좌 전체 pause: AUTO provenance mismatch 등만
                if account_pause_conflicts > 0:
                    conflict_svc.pause_account_for_conflicts(
                        user_broker_account_id=uba_id,
                        user_id=context.user_id,
                        broker_code="UPBIT",
                    )
                    result.warnings.append(
                        "External-only Upbit orders require manual_review "
                        "(auto-create disabled)"
                    )
                elif conflicts > 0:
                    result.warnings.append(
                        "Remote MANUAL orders recorded without account pause "
                        "(symbol ownership isolation)"
                    )
                session.commit()

            result.conflicts_found = conflicts
            result.detail["reconcile"] = {
                k: reconcile.get(k)
                for k in (
                    "checked",
                    "updated",
                    "mode",
                    "message",
                    "conflicts",
                    "remote_only",
                )
                if k in reconcile
            }
            result.detail["remote_only_count"] = remote_only
            result.detail["account_pause_conflicts"] = account_pause_conflicts

            if account_pause_conflicts > 0:
                result.status = "MANUAL_REVIEW"
                result.trading_should_remain_paused = True
            elif result.errors:
                result.status = "FAILED"
                result.trading_should_remain_paused = True
                result.retry_required = True

        except BrokerCredentialVaultError as exc:
            session.rollback()
            result.status = "FAILED"
            result.errors.append(exc.code)
            result.detail["credential_error"] = {
                "code": exc.code,
                "message": exc.message,
            }
            result.trading_should_remain_paused = True
            result.retry_required = True
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            from datetime import datetime, timezone, timedelta

            from stock_platform.broker.upbit.exceptions import (
                UpbitBanOrBlockError,
                UpbitRateLimitError,
            )

            if isinstance(exc, UpbitBanOrBlockError):
                result.status = "BLOCKED_UPBIT_418"
                result.errors.append("UPBIT_418_BLOCKED")
                result.trading_should_remain_paused = True
                result.retry_required = False
                result.warnings.append(
                    "Upbit 418 ban — auto retry stopped for this account"
                )
                result.detail["rate_limit"] = {
                    "http_status": 418,
                    "retry_after_seconds": exc.retry_after_seconds,
                }
            elif isinstance(exc, UpbitRateLimitError):
                # 긴 Retry-After → DEFERRED + Lock 해제 (Scheduler 재실행)
                delay = float(exc.retry_after_seconds or 30.0)
                result.status = "DEFERRED_RATE_LIMIT"
                result.errors.append("UPBIT_429_DEFERRED")
                result.trading_should_remain_paused = True
                result.retry_required = True
                result.warnings.append(
                    f"Deferred for rate limit ({delay:.0f}s)"
                )
                result.detail["rate_limit"] = {
                    "http_status": 429,
                    "retry_after_seconds": delay,
                    "cooldown_until": (
                        exc.cooldown_until.isoformat()
                        if exc.cooldown_until
                        else (
                            datetime.now(timezone.utc)
                            + timedelta(seconds=delay)
                        ).isoformat()
                    ),
                }
                # next_retry_at 기록
                try:
                    from stock_platform.broker.recovery_account_state import (
                        BrokerRecoveryAccountStateEntity,
                    )
                    from sqlalchemy import select

                    stmt = select(BrokerRecoveryAccountStateEntity).where(
                        BrokerRecoveryAccountStateEntity.broker_code
                        == "UPBIT",
                        BrokerRecoveryAccountStateEntity.user_broker_account_id
                        == context.user_broker_account_id,
                    )
                    state = session.scalar(stmt.limit(1))
                    if state is not None:
                        state.next_retry_at = (
                            exc.cooldown_until
                            or datetime.now(timezone.utc)
                            + timedelta(seconds=delay)
                        )
                        state.next_retry_reason = "DEFERRED_RATE_LIMIT"
                        state.rate_limit_endpoint_group = (
                            exc.endpoint_group or "default"
                        )
                        state.last_error_code = "rate_limit"
                        session.commit()
                except Exception:  # noqa: BLE001
                    session.rollback()
            else:
                result.status = "FAILED"
                result.errors.append(str(exc))
                result.trading_should_remain_paused = True
                result.retry_required = True
                msg = str(exc).lower()
                if "rate" in msg or "429" in msg or "too many" in msg:
                    result.warnings.append(
                        "Possible rate limit — retry later"
                    )
                    result.retry_required = True
        finally:
            session.close()

        return result.finish()


def _notify_same_symbol_conflict(symbol: str) -> None:
    """동일 Symbol MANUAL/AUTO 충돌 알림 — 실패해도 Recovery 계속."""

    try:
        from stock_platform.notification.publisher import notification_publisher

        notification_publisher.publish(
            event_type="SAME_SYMBOL_MANUAL_AUTO_CONFLICT",
            title="자동/일반매매 충돌",
            message=(
                f"종목 {symbol}: 자동매매 보유 중 수동 주문이 감지되어 "
                "해당 종목 자동매매를 일시 중지합니다."
            ),
            detail={
                "symbol": symbol,
                "broker_code": "UPBIT",
                "reason": "SAME_SYMBOL_MANUAL_AUTO_CONFLICT",
            },
        )
    except Exception:  # noqa: BLE001
        pass
