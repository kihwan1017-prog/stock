"""STEP 8-5-17 — Broker Snapshot Repository (UBA Binding 필수)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from stock_platform.broker.account_dto import BrokerAccountSyncResult
from stock_platform.broker.account_models import (
    BrokerAccountSnapshotEntity,
    BrokerPositionSnapshotEntity,
)
from stock_platform.broker.snapshot_constants import BrokerSnapshotStatus
from stock_platform.broker.snapshot_freshness import compute_snapshot_hash
from stock_platform.broker.snapshot_legacy_adoption import (
    LegacySnapshotAdoptionRejected,
    SnapshotLegacyAdoptionProof,
)


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
        legacy_adoption: SnapshotLegacyAdoptionProof | None = None,
    ) -> BrokerAccountSnapshotEntity:
        """UBA 또는 Paper 중 정확히 하나와 바인딩하여 저장한다.

        legacy_adoption: RETIRED+UBA NULL row를 ownership-proven 시에만 adopt.
        proof 없으면 legacy auto-adopt 하지 않음 (Upbit 등 fail-closed).
        """

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

        if legacy_adoption is not None:
            if uba_id is None:
                raise LegacySnapshotAdoptionRejected(
                    "legacy adoption requires UBA binding"
                )
            if int(legacy_adoption.target_uba_id) != int(uba_id):
                raise LegacySnapshotAdoptionRejected(
                    "legacy adoption target_uba_id mismatch"
                )
            if (
                str(legacy_adoption.broker_code).upper()
                != str(result.broker_code).upper()
            ):
                raise LegacySnapshotAdoptionRejected(
                    "legacy adoption broker_code mismatch"
                )

        broker = str(result.broker_code).upper()
        adopted_from: BrokerAccountSnapshotEntity | None = None

        # UBA 기준 ACTIVE 행 우선 조회 (broker-only latest 금지)
        account: BrokerAccountSnapshotEntity | None = None
        if uba_id is not None:
            account = self._session.scalar(
                select(BrokerAccountSnapshotEntity)
                .where(
                    BrokerAccountSnapshotEntity.user_broker_account_id
                    == int(uba_id),
                    BrokerAccountSnapshotEntity.snapshot_status
                    == BrokerSnapshotStatus.ACTIVE.value,
                )
                .with_for_update()
            )
            if account is None:
                # RETIRED same UBA → safe reactivate
                retired_same = list(
                    self._session.scalars(
                        select(BrokerAccountSnapshotEntity)
                        .where(
                            BrokerAccountSnapshotEntity.user_broker_account_id
                            == int(uba_id),
                            BrokerAccountSnapshotEntity.snapshot_status
                            == BrokerSnapshotStatus.RETIRED.value,
                        )
                        .with_for_update()
                    )
                )
                if len(retired_same) > 1:
                    raise LegacySnapshotAdoptionRejected(
                        "ambiguous RETIRED snapshots for same UBA"
                    )
                if len(retired_same) == 1:
                    account = retired_same[0]
                    adopted_from = account

            if account is None and legacy_adoption is not None:
                account = self._resolve_legacy_unbound_adopt(
                    result=result,
                    proof=legacy_adoption,
                )
                if account is not None:
                    adopted_from = account

        if account is None and paper_id is not None:
            account = self._session.scalar(
                select(BrokerAccountSnapshotEntity)
                .where(
                    BrokerAccountSnapshotEntity.paper_account_id
                    == int(paper_id),
                    BrokerAccountSnapshotEntity.snapshot_status
                    == BrokerSnapshotStatus.ACTIVE.value,
                )
                .with_for_update()
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
                broker_code=broker,
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
            account.broker_code = broker
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
        account.raw_data = self._merge_raw_for_adopt(
            previous=account.raw_data if adopted_from is not None else None,
            incoming=result.raw_data,
            adopted=adopted_from is not None,
            uba_id=int(uba_id) if uba_id else None,
            snapshot_id=(
                int(adopted_from.broker_account_snapshot_id)
                if adopted_from is not None
                and getattr(
                    adopted_from, "broker_account_snapshot_id", None
                )
                is not None
                else None
            ),
        )
        account.synchronized_at = snap_time
        account.snapshot_time = snap_time
        account.broker_server_time = result.broker_server_time
        account.snapshot_hash = new_hash

        # 포지션: UBA 바인딩 + (proof 시) ownership-proven legacy RETIRED cleanup
        self._replace_positions(
            result=result,
            uba_id=int(uba_id) if uba_id else None,
            paper_id=int(paper_id) if paper_id else None,
            legacy_adoption=legacy_adoption,
            snap_time=snap_time,
        )

        self._session.commit()
        self._session.refresh(account)
        return account

    def _resolve_legacy_unbound_adopt(
        self,
        *,
        result: BrokerAccountSyncResult,
        proof: SnapshotLegacyAdoptionProof,
    ) -> BrokerAccountSnapshotEntity | None:
        """RETIRED + UBA NULL 중 ownership-proven 단일 candidate만 adopt."""

        broker = str(result.broker_code).upper()
        candidates = list(
            self._session.scalars(
                select(BrokerAccountSnapshotEntity)
                .where(
                    BrokerAccountSnapshotEntity.broker_code == broker,
                    BrokerAccountSnapshotEntity.snapshot_status
                    == BrokerSnapshotStatus.RETIRED.value,
                    BrokerAccountSnapshotEntity.user_broker_account_id.is_(
                        None
                    ),
                    BrokerAccountSnapshotEntity.paper_account_id.is_(None),
                )
                .with_for_update()
            )
        )
        matched = [
            row
            for row in candidates
            if proof.matches_account(str(row.account_number or ""))
        ]
        if not matched:
            return None
        if len(matched) > 1:
            raise LegacySnapshotAdoptionRejected(
                "ambiguous RETIRED unbound snapshots for account identity"
            )

        # 동일 실계좌 ACTIVE가 다른 UBA에 있으면 fail-closed
        active_rows = list(
            self._session.scalars(
                select(BrokerAccountSnapshotEntity).where(
                    BrokerAccountSnapshotEntity.broker_code == broker,
                    BrokerAccountSnapshotEntity.snapshot_status
                    == BrokerSnapshotStatus.ACTIVE.value,
                )
            )
        )
        for row in active_rows:
            if not proof.matches_account(str(row.account_number or "")):
                continue
            other_uba = row.user_broker_account_id
            if other_uba is not None and int(other_uba) != int(
                proof.target_uba_id
            ):
                raise LegacySnapshotAdoptionRejected(
                    "ACTIVE snapshot bound to different UBA"
                )

        # RETIRED지만 다른 UBA에 묶인 행
        retired_bound = list(
            self._session.scalars(
                select(BrokerAccountSnapshotEntity).where(
                    BrokerAccountSnapshotEntity.broker_code == broker,
                    BrokerAccountSnapshotEntity.snapshot_status
                    == BrokerSnapshotStatus.RETIRED.value,
                    BrokerAccountSnapshotEntity.user_broker_account_id.is_not(
                        None
                    ),
                )
            )
        )
        for row in retired_bound:
            if not proof.matches_account(str(row.account_number or "")):
                continue
            if int(row.user_broker_account_id) != int(proof.target_uba_id):
                raise LegacySnapshotAdoptionRejected(
                    "RETIRED snapshot bound to different UBA"
                )

        return matched[0]

    def _merge_raw_for_adopt(
        self,
        *,
        previous: dict[str, Any] | None,
        incoming: dict[str, Any] | None,
        adopted: bool,
        uba_id: int | None,
        snapshot_id: int | None,
    ) -> dict[str, Any]:
        merged = dict(incoming or {})
        if previous:
            # retirement provenance 보존
            if "_retire" in previous and "_retire" not in merged:
                merged["_retire"] = previous.get("_retire")
        if adopted:
            merged["_adopt"] = {
                "target_uba_id": uba_id,
                "from_snapshot_id": snapshot_id,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        return merged

    def _replace_positions(
        self,
        *,
        result: BrokerAccountSyncResult,
        uba_id: int | None,
        paper_id: int | None,
        legacy_adoption: SnapshotLegacyAdoptionProof | None,
        snap_time: datetime,
    ) -> None:
        broker = str(result.broker_code).upper()

        if uba_id is not None:
            # 1) 현재 UBA bound rows
            self._session.execute(
                delete(BrokerPositionSnapshotEntity).where(
                    BrokerPositionSnapshotEntity.user_broker_account_id
                    == int(uba_id)
                )
            )
            # 2) ownership-proven legacy RETIRED + UBA NULL only
            if legacy_adoption is not None:
                legacy_rows = list(
                    self._session.scalars(
                        select(BrokerPositionSnapshotEntity)
                        .where(
                            BrokerPositionSnapshotEntity.broker_code
                            == broker,
                            BrokerPositionSnapshotEntity.user_broker_account_id.is_(
                                None
                            ),
                            BrokerPositionSnapshotEntity.snapshot_status
                            == BrokerSnapshotStatus.RETIRED.value,
                        )
                        .with_for_update()
                    )
                )
                # ACTIVE other-UBA / other-owner rows는 절대 삭제 금지
                active_foreign = list(
                    self._session.scalars(
                        select(BrokerPositionSnapshotEntity).where(
                            BrokerPositionSnapshotEntity.broker_code
                            == broker,
                            BrokerPositionSnapshotEntity.snapshot_status
                            == BrokerSnapshotStatus.ACTIVE.value,
                            BrokerPositionSnapshotEntity.user_broker_account_id.is_not(
                                None
                            ),
                        )
                    )
                )
                for row in active_foreign:
                    if not legacy_adoption.matches_account(
                        str(row.account_number or "")
                    ):
                        continue
                    if int(row.user_broker_account_id) != int(uba_id):
                        raise LegacySnapshotAdoptionRejected(
                            "ACTIVE position bound to different UBA"
                        )

                delete_ids = [
                    int(row.broker_position_snapshot_id)
                    for row in legacy_rows
                    if legacy_adoption.matches_account(
                        str(row.account_number or "")
                    )
                ]
                if delete_ids:
                    self._session.execute(
                        delete(BrokerPositionSnapshotEntity).where(
                            BrokerPositionSnapshotEntity.broker_position_snapshot_id.in_(
                                delete_ids
                            )
                        )
                    )
        else:
            # Paper / account_number exact replace (기존 계약)
            self._session.execute(
                delete(BrokerPositionSnapshotEntity).where(
                    BrokerPositionSnapshotEntity.broker_code == broker,
                    BrokerPositionSnapshotEntity.account_number
                    == result.account_number,
                )
            )

        for item in result.positions:
            self._session.add(
                BrokerPositionSnapshotEntity(
                    broker_code=broker,
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
        _ = paper_id  # paper_id는 account 바인딩에서만 사용
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

