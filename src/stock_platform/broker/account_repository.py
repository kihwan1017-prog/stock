"""STEP 8-5-17 — Broker Snapshot Repository (UBA Binding 필수)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from stock_platform.broker.account_dto import BrokerAccountSyncResult
from stock_platform.broker.account_models import (
    BrokerAccountSnapshotEntity,
    BrokerPositionSnapshotEntity,
)
from stock_platform.broker.snapshot_constants import BrokerSnapshotStatus
from stock_platform.broker.snapshot_freshness import compute_snapshot_hash


class BrokerSnapshotBindingError(ValueError):
    """UBA/Paper Binding 없이 Snapshot을 저장하려 할 때."""


class BrokerAccountSnapshotRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(
        self,
        result: BrokerAccountSyncResult,
        *,
        user_broker_account_id: int | None = None,
        paper_account_id: int | None = None,
    ) -> BrokerAccountSnapshotEntity:
        """UBA 또는 Paper 중 정확히 하나와 바인딩하여 저장한다."""

        uba_id = user_broker_account_id
        if uba_id is None:
            uba_id = result.user_broker_account_id
        paper_id = paper_account_id
        if paper_id is None:
            paper_id = result.paper_account_id

        if (uba_id is None) == (paper_id is None):
            # 둘 다 None 또는 둘 다 있음
            if uba_id is None and paper_id is None:
                raise BrokerSnapshotBindingError(
                    "user_broker_account_id or paper_account_id required"
                )
            raise BrokerSnapshotBindingError(
                "provide exactly one of user_broker_account_id / paper_account_id"
            )

        # UBA 기준 ACTIVE 행 우선 조회 (broker-only latest 금지)
        account: BrokerAccountSnapshotEntity | None = None
        if uba_id is not None:
            account = self._session.scalar(
                select(BrokerAccountSnapshotEntity).where(
                    BrokerAccountSnapshotEntity.user_broker_account_id
                    == int(uba_id),
                    BrokerAccountSnapshotEntity.snapshot_status
                    == BrokerSnapshotStatus.ACTIVE.value,
                )
            )
        if account is None and paper_id is not None:
            account = self._session.scalar(
                select(BrokerAccountSnapshotEntity).where(
                    BrokerAccountSnapshotEntity.paper_account_id
                    == int(paper_id),
                    BrokerAccountSnapshotEntity.snapshot_status
                    == BrokerSnapshotStatus.ACTIVE.value,
                )
            )

        now = datetime.now(timezone.utc)
        snap_time = result.synchronized_at or now
        new_hash = compute_snapshot_hash(
            broker_code=result.broker_code,
            account_number=result.account_number,
            deposit_amount=result.deposit_amount,
            available_order_amount=result.available_order_amount,
            total_evaluation_amount=result.total_evaluation_amount,
            synchronized_at=snap_time,
        )

        if account is None:
            account = BrokerAccountSnapshotEntity(
                broker_code=result.broker_code.upper(),
                account_number=result.account_number,
                user_broker_account_id=int(uba_id) if uba_id else None,
                paper_account_id=int(paper_id) if paper_id else None,
                snapshot_status=BrokerSnapshotStatus.ACTIVE.value,
                snapshot_generation=1,
                snapshot_version=1,
            )
            self._session.add(account)
        else:
            # Generation/Version 증가 (내용 변경 시)
            prev_hash = account.snapshot_hash
            account.snapshot_generation = int(
                account.snapshot_generation or 1
            ) + 1
            if prev_hash and prev_hash != new_hash:
                account.snapshot_version = int(
                    account.snapshot_version or 1
                ) + 1
            account.broker_code = result.broker_code.upper()
            account.account_number = result.account_number
            account.user_broker_account_id = (
                int(uba_id) if uba_id else None
            )
            account.paper_account_id = (
                int(paper_id) if paper_id else None
            )
            account.snapshot_status = BrokerSnapshotStatus.ACTIVE.value

        account.deposit_amount = result.deposit_amount
        account.available_order_amount = result.available_order_amount
        account.total_purchase_amount = result.total_purchase_amount
        account.total_evaluation_amount = result.total_evaluation_amount
        account.total_profit_loss = result.total_profit_loss
        account.total_return_rate = result.total_return_rate
        account.raw_data = result.raw_data
        account.synchronized_at = snap_time
        account.snapshot_time = snap_time
        account.broker_server_time = result.broker_server_time
        account.snapshot_hash = new_hash

        # 포지션: 동일 바인딩 키로 교체
        if uba_id is not None:
            self._session.execute(
                delete(BrokerPositionSnapshotEntity).where(
                    BrokerPositionSnapshotEntity.user_broker_account_id
                    == int(uba_id)
                )
            )
        else:
            self._session.execute(
                delete(BrokerPositionSnapshotEntity).where(
                    BrokerPositionSnapshotEntity.broker_code
                    == result.broker_code.upper(),
                    BrokerPositionSnapshotEntity.account_number
                    == result.account_number,
                )
            )

        for item in result.positions:
            self._session.add(
                BrokerPositionSnapshotEntity(
                    broker_code=result.broker_code.upper(),
                    account_number=result.account_number,
                    user_broker_account_id=(
                        int(uba_id) if uba_id else None
                    ),
                    snapshot_status=BrokerSnapshotStatus.ACTIVE.value,
                    exchange_code=item.exchange_code,
                    symbol=item.symbol,
                    name=item.name,
                    quantity=item.quantity,
                    available_quantity=item.available_quantity,
                    average_purchase_price=item.average_purchase_price,
                    current_price=item.current_price,
                    purchase_amount=item.purchase_amount,
                    evaluation_amount=item.evaluation_amount,
                    profit_loss=item.profit_loss,
                    return_rate=item.return_rate,
                    raw_data=item.raw_data,
                    synchronized_at=snap_time,
                )
            )

        self._session.commit()
        self._session.refresh(account)
        return account

    def get_active_by_uba(
        self, user_broker_account_id: int
    ) -> tuple[
        BrokerAccountSnapshotEntity | None,
        list[BrokerPositionSnapshotEntity],
    ]:
        account = self._session.scalar(
            select(BrokerAccountSnapshotEntity).where(
                BrokerAccountSnapshotEntity.user_broker_account_id
                == int(user_broker_account_id),
                BrokerAccountSnapshotEntity.snapshot_status
                == BrokerSnapshotStatus.ACTIVE.value,
            )
        )
        if account is None:
            return None, []
        positions = list(
            self._session.scalars(
                select(BrokerPositionSnapshotEntity)
                .where(
                    BrokerPositionSnapshotEntity.user_broker_account_id
                    == int(user_broker_account_id),
                    BrokerPositionSnapshotEntity.snapshot_status
                    == BrokerSnapshotStatus.ACTIVE.value,
                )
                .order_by(BrokerPositionSnapshotEntity.symbol)
            )
        )
        return account, positions

    def get_latest(
        self,
        *,
        broker_code: str,
        account_number: str,
        user_broker_account_id: int | None = None,
    ):
        """레거시 호환 — UBA가 있으면 UBA 조회 우선, 없으면 ORPHAN 제외."""

        if user_broker_account_id is not None:
            return self.get_active_by_uba(int(user_broker_account_id))

        account = self._session.scalar(
            select(BrokerAccountSnapshotEntity).where(
                BrokerAccountSnapshotEntity.broker_code
                == broker_code.upper(),
                BrokerAccountSnapshotEntity.account_number
                == account_number,
                BrokerAccountSnapshotEntity.snapshot_status
                == BrokerSnapshotStatus.ACTIVE.value,
                BrokerAccountSnapshotEntity.user_broker_account_id.is_not(
                    None
                ),
            )
        )
        if account is None:
            return None, []
        positions = list(
            self._session.scalars(
                select(BrokerPositionSnapshotEntity)
                .where(
                    BrokerPositionSnapshotEntity.broker_code
                    == broker_code.upper(),
                    BrokerPositionSnapshotEntity.account_number
                    == account_number,
                    BrokerPositionSnapshotEntity.snapshot_status
                    == BrokerSnapshotStatus.ACTIVE.value,
                )
                .order_by(BrokerPositionSnapshotEntity.symbol)
            )
        )
        return account, positions

    def mark_stale(self, snapshot_id: int) -> BrokerAccountSnapshotEntity:
        row = self._session.get(
            BrokerAccountSnapshotEntity, int(snapshot_id)
        )
        if row is None:
            raise LookupError(f"snapshot not found: {snapshot_id}")
        row.snapshot_status = BrokerSnapshotStatus.STALE.value
        self._session.flush()
        return row

    def release_orphan_for_uba(
        self, user_broker_account_id: int
    ) -> int:
        """UBA의 STALE/ORPHAN이 아닌 잘못된 바인딩 정리용."""

        rows = list(
            self._session.scalars(
                select(BrokerAccountSnapshotEntity).where(
                    BrokerAccountSnapshotEntity.user_broker_account_id
                    == int(user_broker_account_id),
                    BrokerAccountSnapshotEntity.snapshot_status
                    == BrokerSnapshotStatus.STALE.value,
                )
            )
        )
        for row in rows:
            row.snapshot_status = BrokerSnapshotStatus.SUPERSEDED.value
        self._session.flush()
        return len(rows)

    def list_orphans(self, *, limit: int = 100) -> list[BrokerAccountSnapshotEntity]:
        """관리자 ORPHAN 큐."""

        return list(
            self._session.scalars(
                select(BrokerAccountSnapshotEntity)
                .where(
                    BrokerAccountSnapshotEntity.snapshot_status.in_(
                        [
                            BrokerSnapshotStatus.ORPHAN.value,
                            BrokerSnapshotStatus.REBIND_PENDING.value,
                        ]
                    )
                )
                .order_by(BrokerAccountSnapshotEntity.synchronized_at.desc())
                .limit(max(1, min(int(limit), 500)))
            )
        )

    def rebind_orphan(
        self,
        *,
        snapshot_id: int,
        target_user_broker_account_id: int,
        reason: str,
        actor: str,
    ) -> BrokerAccountSnapshotEntity:
        """관리자 승인 재바인딩 — 자동 재바인딩 금지."""

        from stock_platform.trading.account_masking import hash_account_ref
        from stock_platform.trading.account_models import UserBrokerAccount

        row = self._session.get(
            BrokerAccountSnapshotEntity, int(snapshot_id)
        )
        if row is None:
            raise LookupError(f"snapshot not found: {snapshot_id}")
        if row.snapshot_status not in {
            BrokerSnapshotStatus.ORPHAN.value,
            BrokerSnapshotStatus.REBIND_PENDING.value,
        }:
            raise ValueError(
                f"snapshot status not rebindable: {row.snapshot_status}"
            )

        uba = self._session.get(
            UserBrokerAccount, int(target_user_broker_account_id)
        )
        if uba is None:
            raise LookupError(
                f"uba not found: {target_user_broker_account_id}"
            )
        if str(uba.broker_code).upper() != str(row.broker_code).upper():
            raise ValueError("broker_code mismatch for rebind")

        # account_ref_hash 검증 (가능하면)
        snap_hash = hash_account_ref(row.account_number)
        if uba.account_ref_hash and snap_hash and uba.account_ref_hash != snap_hash:
            # UBA:{id} 저장 형태(Upbit)는 해시 불일치 가능 — 마스킹 힌트만 허용 시
            stored = str(row.account_number or "")
            if not stored.upper().startswith("UBA:"):
                raise ValueError("account_ref_hash mismatch for rebind")

        # 동일 UBA ACTIVE 중복 금지
        existing = self._session.scalar(
            select(BrokerAccountSnapshotEntity).where(
                BrokerAccountSnapshotEntity.user_broker_account_id
                == int(target_user_broker_account_id),
                BrokerAccountSnapshotEntity.snapshot_status
                == BrokerSnapshotStatus.ACTIVE.value,
                BrokerAccountSnapshotEntity.broker_account_snapshot_id
                != int(snapshot_id),
            )
        )
        if existing is not None:
            raise ValueError("target UBA already has ACTIVE snapshot")

        row.snapshot_status = BrokerSnapshotStatus.REBIND_PENDING.value
        self._session.flush()

        row.user_broker_account_id = int(target_user_broker_account_id)
        row.paper_account_id = None
        row.snapshot_status = BrokerSnapshotStatus.ACTIVE.value
        # 이력용 메타 (Audit 외 Snapshot raw_data 에도 보존)
        meta = dict(row.raw_data or {})
        meta["_rebind"] = {
            "actor": actor,
            "reason": (reason or "")[:200],
            "target_uba": int(target_user_broker_account_id),
        }
        row.raw_data = meta

        # 포지션도 동일 UBA 로 맞춤
        positions = list(
            self._session.scalars(
                select(BrokerPositionSnapshotEntity).where(
                    BrokerPositionSnapshotEntity.broker_code
                    == row.broker_code,
                    BrokerPositionSnapshotEntity.account_number
                    == row.account_number,
                )
            )
        )
        for pos in positions:
            pos.user_broker_account_id = int(target_user_broker_account_id)
            if pos.snapshot_status in {
                BrokerSnapshotStatus.ORPHAN.value,
                BrokerSnapshotStatus.REBIND_PENDING.value,
            }:
                pos.snapshot_status = BrokerSnapshotStatus.ACTIVE.value

        self._session.flush()
        return row

    def retire_orphan(
        self,
        *,
        snapshot_id: int,
        reason: str,
        actor: str,
    ) -> BrokerAccountSnapshotEntity:
        """확정 불가 ORPHAN → RETIRED (물리 삭제 없음)."""

        row = self._session.get(
            BrokerAccountSnapshotEntity, int(snapshot_id)
        )
        if row is None:
            raise LookupError(f"snapshot not found: {snapshot_id}")
        if row.snapshot_status not in {
            BrokerSnapshotStatus.ORPHAN.value,
            BrokerSnapshotStatus.REBIND_PENDING.value,
            BrokerSnapshotStatus.INVALID.value,
        }:
            raise ValueError(
                f"snapshot status not retireable: {row.snapshot_status}"
            )
        row.snapshot_status = BrokerSnapshotStatus.RETIRED.value
        meta = dict(row.raw_data or {})
        meta["_retire"] = {
            "actor": actor,
            "reason": (reason or "")[:200],
        }
        row.raw_data = meta
        self._session.flush()
        return row

