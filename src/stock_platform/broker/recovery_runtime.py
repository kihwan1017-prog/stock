"""STEP 8-4 — 통합 BrokerRecoveryManager."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.recovery_adapter import (
    AccountRecoveryContext,
    AdapterRecoveryResult,
)
from stock_platform.broker.recovery_adapters import (
    CryptoPaperRecoveryAdapter,
    KiwoomRecoveryAdapter,
    StockPaperRecoveryAdapter,
    UpbitRecoveryAdapter,
)
from stock_platform.broker.recovery_distributed_lock import (
    DistributedLockBusyError,
    DistributedRecoveryLockManager,
    LockAcquireResult,
    LockOwnershipLostError,
    LockReleaseReason,
    build_distributed_lock_manager_from_settings,
)
from stock_platform.broker.recovery_distributed_lock_audit import (
    audit_recovery_lock_event,
)
from stock_platform.broker.recovery_distributed_lock_scope import (
    scope_from_context,
)
from stock_platform.broker.recovery_entities import (
    BrokerRecoveryRunEntity,
    BrokerRecoveryStepEntity,
)
from stock_platform.broker.recovery_lock import (
    RecoveryAccountLockService,
    RecoveryLockError,
)
from stock_platform.broker.recovery_repository import (
    BrokerRecoveryRepository,
)
from stock_platform.broker.recovery_service import (
    BrokerRecoveryService,
)
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.trading.account_models import (
    PaperAccount,
    UserBrokerAccount,
)


class BrokerRecoveryManager:
    """
    Broker 공통 Recovery Runtime.

    - 계좌별 Adapter 선택·Lock·Timeout·실패 격리
    - 레거시 키움 전역 recover() 호환 유지
    """

    def __init__(
        self,
        *,
        distributed_lock_manager: DistributedRecoveryLockManager
        | None = None,
    ) -> None:
        self._global_lock = asyncio.Lock()
        self._account_locks: dict[str, asyncio.Lock] = {}
        self._running = False
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None
        # STEP 8-5-3 — Startup 완료 시각 (Scheduler Cooldown)
        self._startup_finished_at: datetime | None = None
        self._adapters = [
            KiwoomRecoveryAdapter(),
            UpbitRecoveryAdapter(),
            StockPaperRecoveryAdapter(),
            CryptoPaperRecoveryAdapter(),
        ]
        # STEP 8-5-6 — PostgreSQL 분산 Lock (테스트에서 주입 가능)
        self._dist_lock = (
            distributed_lock_manager
            or build_distributed_lock_manager_from_settings()
        )

    def _lock_for(self, scope_key: str) -> asyncio.Lock:
        if scope_key not in self._account_locks:
            self._account_locks[scope_key] = asyncio.Lock()
        return self._account_locks[scope_key]

    def _select_adapter(self, context: AccountRecoveryContext):
        for adapter in self._adapters:
            if adapter.supports(context):
                return adapter
        return None

    def discover_accounts(
        self,
        session: Session,
        *,
        broker_code: str | None = None,
        paper_account_id: int | None = None,
        user_broker_account_id: int | None = None,
    ) -> list[AccountRecoveryContext]:
        targets: list[AccountRecoveryContext] = []
        broker_filter = (broker_code or "").upper() or None

        # Paper
        if user_broker_account_id is None and (
            broker_filter is None
            or broker_filter in {"PAPER", "PAPER_STOCK", "PAPER_CRYPTO"}
        ):
            stmt = select(PaperAccount).where(
                PaperAccount.is_active.is_(True),
                PaperAccount.deleted_at.is_(None),
            )
            if paper_account_id is not None:
                stmt = stmt.where(
                    PaperAccount.account_id == paper_account_id
                )
            for row in session.scalars(stmt):
                ex = (row.exchange_code or row.broker_code or "KRX").upper()
                market = (
                    "CRYPTO"
                    if ex in {"UPBIT", "CRYPTO"}
                    else "STOCK"
                )
                code = (
                    "PAPER_CRYPTO" if market == "CRYPTO" else "PAPER_STOCK"
                )
                if broker_filter and broker_filter not in {
                    code,
                    "PAPER",
                }:
                    continue
                targets.append(
                    AccountRecoveryContext(
                        user_id=row.user_id,
                        broker_code=code,
                        market_type=market,
                        paper_account_id=int(row.account_id),
                        account_ref_masked=f"PAPER-{row.account_id}",
                    )
                )

        # Live UBA
        if paper_account_id is None and (
            broker_filter is None
            or broker_filter in {"KIWOOM", "UPBIT"}
        ):
            stmt = select(UserBrokerAccount).where(
                UserBrokerAccount.is_active.is_(True)
            )
            if user_broker_account_id is not None:
                stmt = stmt.where(
                    UserBrokerAccount.user_broker_account_id
                    == user_broker_account_id
                )
            if broker_filter in {"KIWOOM", "UPBIT"}:
                stmt = stmt.where(
                    UserBrokerAccount.broker_code == broker_filter
                )
            for row in session.scalars(stmt):
                code = (row.broker_code or "").upper()
                market = "CRYPTO" if code == "UPBIT" else "STOCK"
                targets.append(
                    AccountRecoveryContext(
                        user_id=int(row.user_id),
                        broker_code=code,
                        market_type=market,
                        user_broker_account_id=int(
                            row.user_broker_account_id
                        ),
                        account_ref_masked=row.masked_account_number,
                    )
                )

        # 환경변수 키움 시스템 슬롯 제거 (STEP 8-5-18)
        # 회원 계좌 Recovery 는 UBA/Paper 만 허용 — SYSTEM_SHARED 금지
        if (
            paper_account_id is None
            and user_broker_account_id is None
            and not targets
        ):
            # Fail Closed: 대상 없으면 빈 목록 (레거시 MAIN/SYSTEM 추가 금지)
            return targets

        return targets

    async def recover_account(
        self,
        context: AccountRecoveryContext,
        *,
        holder: str | None = None,
    ) -> AdapterRecoveryResult:
        """
        계좌 Recovery 진입점 (유일한 공개 경로).

        Lock 순서:
        Local asyncio.Lock → PostgreSQL Distributed Lock
        → account state → Runtime pause → Broker API
        """

        adapter = self._select_adapter(context)
        if adapter is None:
            return AdapterRecoveryResult(
                status="FAILED",
                broker_code=context.broker_code,
                paper_account_id=context.paper_account_id,
                user_broker_account_id=context.user_broker_account_id,
                user_id=context.user_id,
                errors=[
                    f"Unsupported broker: {context.broker_code}"
                ],
                trading_should_remain_paused=True,
            ).finish()

        lock = self._lock_for(context.scope_key)
        if lock.locked():
            raise RecoveryLockError(
                f"Recovery already running for {context.scope_key}"
            )

        async with lock:
            return await self._recover_account_under_lock(
                context,
                adapter=adapter,
                holder=holder,
            )

    async def _recover_account_under_lock(
        self,
        context: AccountRecoveryContext,
        *,
        adapter,
        holder: str | None = None,
    ) -> AdapterRecoveryResult:
        """분산 Lock 획득 후 실제 Recovery (호출자 우회 금지)."""

        scope = scope_from_context(context)
        acquire_result, dist_handle = self._dist_lock.acquire(scope)
        if acquire_result in {
            LockAcquireResult.BUSY,
            LockAcquireResult.TIMEOUT,
        } or dist_handle is None:
            busy = self._dist_lock.get_lock(scope.lock_scope_key) or {}
            audit_recovery_lock_event(
                "RECOVERY_DISTRIBUTED_LOCK_BUSY",
                detail={
                    "lock_scope_key": scope.lock_scope_key,
                    "broker_code": context.broker_code,
                    "account_ref_masked": context.account_ref_masked,
                    "owner_masked": busy.get("owner_instance_masked"),
                    "lease_expires_at": busy.get("lease_expires_at"),
                    "result": acquire_result.value,
                },
            )
            raise DistributedLockBusyError(
                f"Distributed recovery lock busy for {scope.lock_scope_key}",
                scope_key=scope.lock_scope_key,
                owner_masked=busy.get("owner_instance_masked"),
                lease_expires_at=busy.get("lease_expires_at"),
            )

        audit_recovery_lock_event(
            (
                "RECOVERY_DISTRIBUTED_LOCK_STALE_TAKEOVER"
                if acquire_result == LockAcquireResult.STALE_TAKEN_OVER
                else "RECOVERY_DISTRIBUTED_LOCK_ACQUIRED"
            ),
            detail={
                "lock_scope_key": scope.lock_scope_key,
                "broker_code": context.broker_code,
                "account_ref_masked": context.account_ref_masked,
                "fencing_token": dist_handle.fencing_token,
                "owner_masked": dist_handle.owner_instance_id[:20] + "…",
                "result": acquire_result.value,
            },
        )

        # STEP 8-5-5 — 해당 계좌 Runtime만 Pause
        try:
            from stock_platform.strategy_deployment.runtime_manager import (
                dynamic_strategy_runtime_manager,
            )

            await dynamic_strategy_runtime_manager.pause_account_runtimes(
                paper_account_id=context.paper_account_id,
                user_broker_account_id=context.user_broker_account_id,
                reason="recovery_running",
            )
        except Exception:  # noqa: BLE001
            pass

        await self._dist_lock.start_heartbeat(dist_handle)
        session = get_session_factory()()
        run_id: int | None = None
        release_reason = LockReleaseReason.FAILED
        keep_paused = True
        paused_before: bool | None = None
        result: AdapterRecoveryResult | None = None
        try:
            lock_svc = RecoveryAccountLockService(session)
            holder_id = holder or f"recovery-{uuid.uuid4().hex[:8]}"
            try:
                _row, paused_before = lock_svc.acquire(
                    context,
                    holder=holder_id,
                    ttl_seconds=int(context.timeout_seconds) + 60,
                )
                session.commit()
            except RecoveryLockError:
                session.rollback()
                release_reason = LockReleaseReason.CANCELLED
                raise

            repo = BrokerRecoveryRepository(session)
            run_entity = repo.start_run(
                trigger_type=context.trigger_type,
                broker_code=context.broker_code,
                user_id=context.user_id,
                paper_account_id=context.paper_account_id,
                user_broker_account_id=(
                    context.user_broker_account_id
                ),
                requested_by=context.requested_by,
            )
            run_id = int(run_entity.broker_recovery_run_id)
            run_entity.fencing_token = int(dist_handle.fencing_token)
            run_entity.lock_scope_key = dist_handle.lock_scope_key
            run_entity.owner_instance_id = dist_handle.owner_instance_id
            run_entity.lease_id = dist_handle.lease_id
            session.add(run_entity)
            session.commit()
            self._dist_lock.bind_recovery_run(dist_handle, run_id)

            try:
                result = await asyncio.wait_for(
                    adapter.recover(context),
                    timeout=context.timeout_seconds,
                )
            except TimeoutError:
                result = AdapterRecoveryResult(
                    status="FAILED",
                    broker_code=context.broker_code,
                    paper_account_id=context.paper_account_id,
                    user_broker_account_id=(
                        context.user_broker_account_id
                    ),
                    user_id=context.user_id,
                    errors=["Recovery timeout"],
                    retry_required=True,
                    trading_should_remain_paused=True,
                ).finish()
                release_reason = LockReleaseReason.TIMEOUT

            # Heartbeat 상실 또는 Fencing 검증
            if dist_handle.ownership_lost:
                raise LockOwnershipLostError(
                    f"lock ownership lost during recovery "
                    f"{dist_handle.lock_scope_key}"
                )
            try:
                self._dist_lock.assert_owns(dist_handle)
            except LockOwnershipLostError:
                raise

            status_map = {
                "SUCCESS": "SUCCESS",
                "PARTIAL": "SUCCESS",
                "SKIPPED": "SUCCESS",
                "MANUAL_REVIEW": "FAILED",
                "FAILED": "FAILED",
            }
            run_entity.status_code = status_map.get(
                result.status, "FAILED"
            )
            run_entity.finished_at = (
                result.finished_at or datetime.now(timezone.utc)
            )
            run_entity.open_orders_checked = (
                result.open_orders_checked
            )
            run_entity.orders_updated = result.orders_updated
            run_entity.fills_created = result.fills_created
            run_entity.balances_updated = result.balances_updated
            run_entity.positions_updated = result.positions_updated
            run_entity.conflicts_found = result.conflicts_found
            run_entity.result_payload = result.to_dict()
            if result.errors:
                run_entity.error_message = "; ".join(
                    result.errors
                )[:2000]
            session.add(
                BrokerRecoveryStepEntity(
                    broker_recovery_run_id=run_id,
                    component_code=f"{context.broker_code}_ADAPTER",
                    status_code=result.status,
                    message=result.status,
                    detail_payload=result.to_dict(),
                    started_at=result.started_at,
                    finished_at=(
                        result.finished_at
                        or datetime.now(timezone.utc)
                    ),
                )
            )
            # STEP 8-5-8 / 8-15A / 8-16 —
            # 장애·Conflict 면 Pause 유지. SUCCESS면 acquire 직전 Pause 복원
            # (Admin Resume 이후 Scheduler SUCCESS가 다시 Pause하지 않음.
            #  기존 Pause 계좌는 SUCCESS만으로 자동 Resume되지 않음.)
            if result.status == "MANUAL_REVIEW":
                final_status = "MANUAL_REVIEW"
            elif result.status == "BLOCKED_UPBIT_418":
                final_status = "MANUAL_REVIEW"
            elif result.status in {
                "FAILED",
                "DEFERRED_RATE_LIMIT",
            }:
                final_status = "FAILED"
            elif result.status in {
                "SUCCESS",
                "PARTIAL",
                "SKIPPED",
            }:
                final_status = "SUCCESS"
            else:
                # CHECK 위반 방지 — 알 수 없는 adapter status는 FAILED
                final_status = "FAILED"
            keep_paused = bool(
                final_status != "SUCCESS"
                or int(result.conflicts_found or 0) > 0
                or result.status
                in {
                    "FAILED",
                    "MANUAL_REVIEW",
                    "DEFERRED_RATE_LIMIT",
                    "BLOCKED_UPBIT_418",
                }
            )
            # Fencing 재확인 후 account state / soft lock 해제
            self._dist_lock.assert_owns(dist_handle)
            lock_svc.release(
                context,
                status_code=final_status,
                keep_paused=keep_paused,
                run_id=run_id,
                error_summary=(
                    "; ".join(result.errors)[:500]
                    if result.errors
                    else None
                ),
                paused_before=paused_before,
            )
            session.commit()
            release_reason = (
                LockReleaseReason.SUCCESS
                if final_status == "SUCCESS"
                else LockReleaseReason.FAILED
            )

            try:
                from stock_platform.strategy_deployment.runtime_manager import (
                    dynamic_strategy_runtime_manager,
                )

                # STEP 8-15A/8-16 — Runtime 자동 Resume 금지
                reason = (
                    "manual_review_required"
                    if result.status == "MANUAL_REVIEW"
                    else (
                        "recovery_success_runtime_held"
                        if final_status == "SUCCESS"
                        else "recovery_failed"
                    )
                )
                await dynamic_strategy_runtime_manager.pause_account_runtimes(
                    paper_account_id=context.paper_account_id,
                    user_broker_account_id=(
                        context.user_broker_account_id
                    ),
                    reason=reason,
                )
            except LockOwnershipLostError:
                raise
            except Exception:  # noqa: BLE001
                pass

            return result
        except DistributedLockBusyError:
            raise
        except RecoveryLockError:
            raise
        except LockOwnershipLostError as exc:
            session.rollback()
            audit_recovery_lock_event(
                "RECOVERY_DISTRIBUTED_LOCK_OWNERSHIP_LOST",
                detail={
                    "lock_scope_key": scope.lock_scope_key,
                    "broker_code": context.broker_code,
                    "account_ref_masked": context.account_ref_masked,
                    "fencing_token": dist_handle.fencing_token,
                    "recovery_run_id": run_id,
                    "error": str(exc)[:200],
                },
            )
            try:
                if run_id is not None:
                    run_row = session.get(
                        BrokerRecoveryRunEntity, run_id
                    )
                    if run_row is not None:
                        run_row.status_code = "LOCK_LOST"
                        run_row.finished_at = datetime.now(
                            timezone.utc
                        )
                        run_row.error_message = str(exc)[:2000]
                        session.add(run_row)
                        session.commit()
            except Exception:  # noqa: BLE001
                session.rollback()
            try:
                RecoveryAccountLockService(session).release(
                    context,
                    status_code="LOCK_LOST",
                    keep_paused=True,
                    run_id=run_id,
                    error_summary=str(exc)[:500],
                )
                session.commit()
            except Exception:  # noqa: BLE001
                session.rollback()
            release_reason = LockReleaseReason.LOST_OWNERSHIP
            # Resume 금지 — Pause 유지
            return AdapterRecoveryResult(
                status="FAILED",
                broker_code=context.broker_code,
                paper_account_id=context.paper_account_id,
                user_broker_account_id=context.user_broker_account_id,
                user_id=context.user_id,
                errors=[f"LOCK_LOST: {exc}"],
                trading_should_remain_paused=True,
                retry_required=True,
            ).finish()
        except Exception as exc:
            session.rollback()
            try:
                RecoveryAccountLockService(session).release(
                    context,
                    status_code="FAILED",
                    keep_paused=True,
                    run_id=run_id,
                    error_summary=str(exc)[:500],
                )
                session.commit()
            except Exception:  # noqa: BLE001
                session.rollback()
            release_reason = LockReleaseReason.FAILED
            raise
        finally:
            await self._dist_lock.stop_heartbeat(scope.lock_scope_key)
            # 소유권 상실 시 정상 RELEASED로 덮어쓰지 않음
            if release_reason != LockReleaseReason.LOST_OWNERSHIP:
                try:
                    released = self._dist_lock.release(
                        dist_handle, release_reason
                    )
                    audit_recovery_lock_event(
                        (
                            "RECOVERY_DISTRIBUTED_LOCK_RELEASED"
                            if released
                            else "RECOVERY_DISTRIBUTED_LOCK_RELEASE_SKIPPED"
                        ),
                        detail={
                            "lock_scope_key": scope.lock_scope_key,
                            "broker_code": context.broker_code,
                            "account_ref_masked": context.account_ref_masked,
                            "fencing_token": dist_handle.fencing_token,
                            "release_reason": str(release_reason),
                            "recovery_run_id": run_id,
                        },
                    )
                except Exception:  # noqa: BLE001
                    pass
            session.close()

    async def recover_all(
        self,
        *,
        trigger_type: str = "MANUAL",
        broker_code: str | None = None,
        paper_account_id: int | None = None,
        user_broker_account_id: int | None = None,
        requested_by: str | None = None,
        concurrency: int = 3,
        overall_timeout_seconds: float = 180.0,
    ) -> dict[str, Any]:
        async with self._global_lock:
            if self._running:
                raise ValueError(
                    "Broker recovery is already running"
                )
            self._running = True
            self._last_error = None
            started = datetime.now(timezone.utc)
            try:
                session = get_session_factory()()
                try:
                    contexts = self.discover_accounts(
                        session,
                        broker_code=broker_code,
                        paper_account_id=paper_account_id,
                        user_broker_account_id=(
                            user_broker_account_id
                        ),
                    )
                finally:
                    session.close()

                for ctx_i, ctx in enumerate(contexts):
                    contexts[ctx_i] = AccountRecoveryContext(
                        user_id=ctx.user_id,
                        broker_code=ctx.broker_code,
                        market_type=ctx.market_type,
                        paper_account_id=ctx.paper_account_id,
                        user_broker_account_id=(
                            ctx.user_broker_account_id
                        ),
                        account_ref_masked=ctx.account_ref_masked,
                        account_number_for_broker=(
                            ctx.account_number_for_broker
                        ),
                        trigger_type=trigger_type,
                        requested_by=requested_by,
                        timeout_seconds=60.0,
                    )

                sem = asyncio.Semaphore(max(1, concurrency))
                results: list[dict[str, Any]] = []

                async def _one(ctx: AccountRecoveryContext):
                    async with sem:
                        try:
                            r = await self.recover_account(ctx)
                            return r.to_dict()
                        except DistributedLockBusyError as exc:
                            return {
                                "status": "SKIPPED_DISTRIBUTED_LOCK",
                                "broker_code": ctx.broker_code,
                                "paper_account_id": ctx.paper_account_id,
                                "user_broker_account_id": (
                                    ctx.user_broker_account_id
                                ),
                                "errors": [str(exc)],
                                "scope_key": ctx.scope_key,
                                "lock_scope_key": exc.scope_key,
                                "owner_masked": exc.owner_masked,
                                "lease_expires_at": exc.lease_expires_at,
                            }
                        except RecoveryLockError as exc:
                            return {
                                "status": "SKIPPED_LOCKED",
                                "broker_code": ctx.broker_code,
                                "paper_account_id": ctx.paper_account_id,
                                "user_broker_account_id": (
                                    ctx.user_broker_account_id
                                ),
                                "errors": [str(exc)],
                                "scope_key": ctx.scope_key,
                            }
                        except Exception as exc:  # noqa: BLE001
                            return {
                                "status": "FAILED",
                                "broker_code": ctx.broker_code,
                                "errors": [str(exc)],
                                "scope_key": ctx.scope_key,
                            }

                try:
                    gathered = await asyncio.wait_for(
                        asyncio.gather(
                            *[_one(c) for c in contexts],
                            return_exceptions=False,
                        ),
                        timeout=overall_timeout_seconds,
                    )
                    results = list(gathered)
                except TimeoutError:
                    results.append(
                        {
                            "status": "FAILED",
                            "errors": ["Overall recovery timeout"],
                        }
                    )

                success = all(
                    r.get("status")
                    in {
                        "SUCCESS",
                        "PARTIAL",
                        "SKIPPED",
                        "SKIPPED_LOCKED",
                        "SKIPPED_DISTRIBUTED_LOCK",
                    }
                    for r in results
                ) if results else True

                self._last_result = {
                    "success": success,
                    "trigger_type": trigger_type,
                    "started_at": started.isoformat(),
                    "finished_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "account_count": len(contexts),
                    "accounts": results,
                }
                return self._last_result
            except Exception as exc:
                self._last_error = str(exc)
                raise
            finally:
                self._running = False

    async def recover(self) -> dict[str, Any]:
        """레거시 호환: 키움 시스템 경로 + 통합 계좌 복구.

        기존 BrokerRecoveryService(키움 단계)를 먼저 실행한 뒤
        발견된 전 계좌 Adapter 복구를 수행한다.
        """

        async with self._global_lock:
            if self._running:
                raise ValueError(
                    "Broker recovery is already running"
                )
            self._running = True
            self._last_error = None
            settings = get_settings()
            session = get_session_factory()()
            try:
                legacy_steps: list[dict[str, Any]] = []
                account_number = (
                    settings.kiwoom_account_number.strip()
                )
                if account_number:
                    service = BrokerRecoveryService(
                        session=session,
                        account_number=account_number,
                        start_websocket=(
                            settings.kiwoom_recovery_start_ws
                        ),
                        start_realtime_runners=(
                            settings.kiwoom_recovery_start_trading
                        ),
                        # Startup 시 스케줄러는 lifecycle이 담당
                        start_scheduler=False,
                    )
                    legacy = await service.recover()
                    legacy_steps = [
                        {
                            "component": s.component.value,
                            "status": s.status.value,
                            "message": s.message,
                            "detail": s.detail,
                        }
                        for s in legacy.steps
                    ]
                    legacy_success = legacy.success
                else:
                    legacy_success = True
                    legacy_steps = [
                        {
                            "component": "KIWOOM_LEGACY",
                            "status": "SKIPPED",
                            "message": "No KIWOOM_ACCOUNT_NUMBER",
                            "detail": {},
                        }
                    ]
            except Exception as exc:
                self._last_error = str(exc)
                raise
            finally:
                session.close()
                self._running = False

        # 통합 계좌 복구 (글로벌 락 재진입)
        unified = await self.recover_all(
            trigger_type="LEGACY_COMPAT",
            requested_by="broker_recovery_manager.recover",
        )
        self._last_result = {
            "success": legacy_success and unified.get("success", False),
            "started_at": unified.get("started_at"),
            "finished_at": unified.get("finished_at"),
            "steps": legacy_steps,
            "accounts": unified.get("accounts", []),
            "account_count": unified.get("account_count", 0),
        }
        return self._last_result

    def status(self) -> dict[str, Any]:
        session = get_session_factory()()
        try:
            latest = BrokerRecoveryRepository(session).latest()
            states = RecoveryAccountLockService(session).list_states(
                limit=50
            )
            db_latest = None
            if latest is not None:
                db_latest = {
                    "broker_recovery_run_id": int(
                        latest.broker_recovery_run_id
                    ),
                    "status_code": latest.status_code,
                    "broker_code": getattr(
                        latest, "broker_code", None
                    ),
                    "trigger_type": getattr(
                        latest, "trigger_type", None
                    ),
                    "started_at": (
                        latest.started_at.isoformat()
                        if latest.started_at
                        else None
                    ),
                    "finished_at": (
                        latest.finished_at.isoformat()
                        if latest.finished_at
                        else None
                    ),
                    "error_message": latest.error_message,
                    "open_orders_checked": getattr(
                        latest, "open_orders_checked", 0
                    ),
                    "orders_updated": getattr(
                        latest, "orders_updated", 0
                    ),
                    "fills_created": getattr(
                        latest, "fills_created", 0
                    ),
                    "balances_updated": getattr(
                        latest, "balances_updated", 0
                    ),
                    "positions_updated": getattr(
                        latest, "positions_updated", 0
                    ),
                    "conflicts_found": getattr(
                        latest, "conflicts_found", 0
                    ),
                }
            return {
                "running": self._running,
                "last_result": self._last_result,
                "last_error": self._last_error,
                "latest_run": db_latest,
                "account_states": [
                    {
                        "broker_code": s.broker_code,
                        "user_id": s.user_id,
                        "paper_account_id": s.paper_account_id,
                        "user_broker_account_id": (
                            s.user_broker_account_id
                        ),
                        "recovery_status": s.recovery_status,
                        "trading_paused": bool(s.trading_paused),
                        "last_error_summary": s.last_error_summary,
                        "updated_at": (
                            s.updated_at.isoformat()
                            if s.updated_at
                            else None
                        ),
                    }
                    for s in states
                ],
            }
        finally:
            session.close()


broker_recovery_manager = BrokerRecoveryManager()
