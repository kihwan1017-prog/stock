"""STEP 8-4 — 계좌별 Recovery Lock / 거래 일시차단."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.broker.recovery_adapter import AccountRecoveryContext


class RecoveryLockError(Exception):
    """Lock 획득 실패."""


class RecoveryAccountLockService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _find(
        self, context: AccountRecoveryContext
    ) -> BrokerRecoveryAccountStateEntity | None:
        stmt = select(BrokerRecoveryAccountStateEntity).where(
            BrokerRecoveryAccountStateEntity.broker_code
            == context.broker_code.upper()
        )
        if context.paper_account_id is not None:
            stmt = stmt.where(
                BrokerRecoveryAccountStateEntity.paper_account_id
                == context.paper_account_id
            )
        elif context.user_broker_account_id is not None:
            stmt = stmt.where(
                BrokerRecoveryAccountStateEntity.user_broker_account_id
                == context.user_broker_account_id
            )
        else:
            stmt = stmt.where(
                BrokerRecoveryAccountStateEntity.paper_account_id.is_(
                    None
                ),
                BrokerRecoveryAccountStateEntity.user_broker_account_id.is_(
                    None
                ),
            )
        return self._session.scalar(stmt.limit(1))

    def acquire(
        self,
        context: AccountRecoveryContext,
        *,
        holder: str,
        ttl_seconds: int = 300,
    ) -> tuple[BrokerRecoveryAccountStateEntity, bool]:
        """Recovery soft-lock 획득.

        Returns:
            (state_row, paused_before) — paused_before 는 이번 acquire 직전 trading_paused.
            실행 중에는 일시 Pause 하고, release 시 SUCCESS면 paused_before 로 복원한다.
        """
        now = datetime.now(timezone.utc)
        row = self._find(context)
        if row is None:
            row = BrokerRecoveryAccountStateEntity(
                broker_code=context.broker_code.upper(),
                user_id=context.user_id,
                paper_account_id=context.paper_account_id,
                user_broker_account_id=context.user_broker_account_id,
            )
            self._session.add(row)
            self._session.flush()

        # 만료된 Lock은 회수
        if (
            row.recovery_status == "RUNNING"
            and row.lock_expires_at is not None
            and row.lock_expires_at > now
        ):
            raise RecoveryLockError(
                f"Recovery already running for {context.scope_key}"
            )

        paused_before = bool(row.trading_paused)
        row.recovery_status = "RUNNING"
        row.trading_paused = True
        row.lock_holder = holder
        row.lock_expires_at = now + timedelta(seconds=ttl_seconds)
        row.user_id = context.user_id
        row.last_error_summary = None
        row.updated_at = now
        self._session.flush()
        return row, paused_before

    def release(
        self,
        context: AccountRecoveryContext,
        *,
        status_code: str,
        keep_paused: bool,
        run_id: int | None,
        error_summary: str | None = None,
        paused_before: bool | None = None,
    ) -> None:
        """Recovery soft-lock 해제.

        STEP 8-15A/8-16 Pause 소유권:
        - keep_paused=True → trading_paused=True (Conflict/장애)
        - keep_paused=False + paused_before 제공 → acquire 직전 상태로 복원
          (Admin Resume 후 SUCCESS면 False 유지, 기존 Pause면 True 유지)
        - keep_paused=False + paused_before 없음 → False로 내리지 않음 (fail-closed)
        Admin Resume API 외의 임의 unpause 금지.
        """
        row = self._find(context)
        if row is None:
            return
        row.recovery_status = status_code
        if keep_paused:
            row.trading_paused = True
        elif paused_before is not None:
            row.trading_paused = bool(paused_before)
        # else: trading_paused 를 False 로 강제하지 않음
        row.lock_holder = None
        row.lock_expires_at = None
        row.last_recovery_run_id = run_id
        row.last_error_summary = error_summary
        row.updated_at = datetime.now(timezone.utc)
        self._session.flush()

    def is_trading_paused(
        self,
        *,
        paper_account_id: int | None = None,
        user_broker_account_id: int | None = None,
        broker_code: str | None = None,
    ) -> bool:
        now = datetime.now(timezone.utc)
        stmt = select(BrokerRecoveryAccountStateEntity).where(
            BrokerRecoveryAccountStateEntity.trading_paused.is_(True)
        )
        if paper_account_id is not None:
            stmt = stmt.where(
                BrokerRecoveryAccountStateEntity.paper_account_id
                == paper_account_id
            )
        elif user_broker_account_id is not None:
            stmt = stmt.where(
                BrokerRecoveryAccountStateEntity.user_broker_account_id
                == user_broker_account_id
            )
        else:
            return False
        if broker_code:
            stmt = stmt.where(
                BrokerRecoveryAccountStateEntity.broker_code
                == broker_code.upper()
            )
        row = self._session.scalar(stmt.limit(1))
        if row is None:
            return False
        # TTL 만료 RUNNING 은 pause 유지하되 orphan lock 정리 가능
        if (
            row.recovery_status == "RUNNING"
            and row.lock_expires_at is not None
            and row.lock_expires_at <= now
        ):
            row.recovery_status = "FAILED"
            row.lock_holder = None
            row.lock_expires_at = None
            # 실패로 pause 유지
            self._session.flush()
            return True
        return bool(row.trading_paused)

    def list_states(
        self,
        *,
        broker_code: str | None = None,
        limit: int = 100,
    ) -> list[BrokerRecoveryAccountStateEntity]:
        stmt = select(BrokerRecoveryAccountStateEntity)
        if broker_code:
            stmt = stmt.where(
                BrokerRecoveryAccountStateEntity.broker_code
                == broker_code.upper()
            )
        return list(
            self._session.scalars(
                stmt.order_by(
                    BrokerRecoveryAccountStateEntity.updated_at.desc()
                ).limit(limit)
            )
        )


def raise_if_recovery_paused(
    session: Session,
    *,
    paper_account_id: int | None = None,
    user_broker_account_id: int | None = None,
    broker_code: str | None = None,
    is_risk_reducing: bool = False,
) -> None:
    """Recovery 중 신규 주문 차단 (위험축소 SELL은 허용 검토)."""

    if is_risk_reducing:
        return
    paused = RecoveryAccountLockService(session).is_trading_paused(
        paper_account_id=paper_account_id,
        user_broker_account_id=user_broker_account_id,
        broker_code=broker_code,
    )
    if paused:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="계좌 Recovery 진행 중이거나 거래가 일시 차단되었습니다.",
        )
