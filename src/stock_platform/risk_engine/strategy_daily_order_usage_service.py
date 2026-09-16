"""Strategy-owned daily submit / filled-entry usage — race-safe DB SoT."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from stock_platform.order.order_limit_policy_v2 import (
    ORDER_LIMIT_V2,
    trading_date_kst,
)
from stock_platform.risk_engine.strategy_owned_entities import (
    StrategyDailyOrderUsageEntity,
)


class StrategyDailyOrderUsageService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_or_create(
        self,
        *,
        user_broker_account_id: int,
        broker_code: str,
        strategy_id: int,
        deployment_id: int | None,
        trading_date: date | None = None,
        for_update: bool = False,
    ) -> StrategyDailyOrderUsageEntity:
        day = trading_date or trading_date_kst()
        uba = int(user_broker_account_id)
        broker = str(broker_code or "").upper()
        sid = int(strategy_id)
        dep = int(deployment_id or 0)

        stmt = select(StrategyDailyOrderUsageEntity).where(
            StrategyDailyOrderUsageEntity.trading_date == day,
            StrategyDailyOrderUsageEntity.broker_code == broker,
            StrategyDailyOrderUsageEntity.user_broker_account_id == uba,
            StrategyDailyOrderUsageEntity.strategy_id == sid,
            StrategyDailyOrderUsageEntity.deployment_id == dep,
        )
        if for_update:
            stmt = stmt.with_for_update()
        row = self._session.scalar(stmt)
        if row is not None:
            return row

        row = StrategyDailyOrderUsageEntity(
            trading_date=day,
            broker_code=broker,
            user_broker_account_id=uba,
            strategy_id=sid,
            deployment_id=dep,
            submit_count=0,
            filled_entry_count=0,
            filled_entry_order_ids=[],
            policy_version=ORDER_LIMIT_V2,
            meta_json={},
        )
        self._session.add(row)
        self._session.flush()
        if for_update:
            # 방금 insert한 행을 잠그려면 재조회
            locked = self._session.scalar(
                select(StrategyDailyOrderUsageEntity)
                .where(
                    StrategyDailyOrderUsageEntity.strategy_daily_order_usage_id
                    == row.strategy_daily_order_usage_id
                )
                .with_for_update()
            )
            return locked or row
        return row

    def snapshot(
        self,
        *,
        user_broker_account_id: int,
        broker_code: str,
        strategy_id: int,
        deployment_id: int | None,
        trading_date: date | None = None,
    ) -> dict[str, Any]:
        row = self.get_or_create(
            user_broker_account_id=user_broker_account_id,
            broker_code=broker_code,
            strategy_id=strategy_id,
            deployment_id=deployment_id,
            trading_date=trading_date,
            for_update=False,
        )
        return {
            "trading_date": row.trading_date.isoformat(),
            "submit_count": int(row.submit_count or 0),
            "filled_entry_count": int(row.filled_entry_count or 0),
            "policy_version": row.policy_version,
            "strategy_id": int(row.strategy_id),
            "deployment_id": int(row.deployment_id or 0),
        }

    def try_reserve_submit(
        self,
        *,
        user_broker_account_id: int,
        broker_code: str,
        strategy_id: int,
        deployment_id: int | None,
        submit_limit: int,
        trading_date: date | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        """원자적 submit_count+1. limit 도달 시 False.

        broker 전송 전 reservation. 로컬 실패 시 release_submit.
        """

        limit = max(0, int(submit_limit))
        day = trading_date or trading_date_kst()
        self.get_or_create(
            user_broker_account_id=user_broker_account_id,
            broker_code=broker_code,
            strategy_id=strategy_id,
            deployment_id=deployment_id,
            trading_date=day,
            for_update=False,
        )
        # PostgreSQL atomic conditional update
        result = self._session.execute(
            text(
                """
                UPDATE operation.strategy_daily_order_usage
                SET submit_count = submit_count + 1,
                    updated_at = NOW()
                WHERE trading_date = :day
                  AND broker_code = :broker
                  AND user_broker_account_id = :uba
                  AND strategy_id = :sid
                  AND deployment_id = :dep
                  AND submit_count < :limit
                RETURNING submit_count, filled_entry_count
                """
            ),
            {
                "day": day,
                "broker": str(broker_code or "").upper(),
                "uba": int(user_broker_account_id),
                "sid": int(strategy_id),
                "dep": int(deployment_id or 0),
                "limit": limit,
            },
        )
        row = result.mappings().first()
        if row is None:
            snap = self.snapshot(
                user_broker_account_id=user_broker_account_id,
                broker_code=broker_code,
                strategy_id=strategy_id,
                deployment_id=deployment_id,
                trading_date=day,
            )
            return False, snap
        return True, {
            "trading_date": day.isoformat(),
            "submit_count": int(row["submit_count"]),
            "filled_entry_count": int(row["filled_entry_count"]),
            "reserved": True,
        }

    def release_submit(
        self,
        *,
        user_broker_account_id: int,
        broker_code: str,
        strategy_id: int,
        deployment_id: int | None,
        trading_date: date | None = None,
    ) -> dict[str, Any]:
        """broker 미전송 시 reservation rollback."""

        day = trading_date or trading_date_kst()
        result = self._session.execute(
            text(
                """
                UPDATE operation.strategy_daily_order_usage
                SET submit_count = GREATEST(submit_count - 1, 0),
                    updated_at = NOW()
                WHERE trading_date = :day
                  AND broker_code = :broker
                  AND user_broker_account_id = :uba
                  AND strategy_id = :sid
                  AND deployment_id = :dep
                  AND submit_count > 0
                RETURNING submit_count, filled_entry_count
                """
            ),
            {
                "day": day,
                "broker": str(broker_code or "").upper(),
                "uba": int(user_broker_account_id),
                "sid": int(strategy_id),
                "dep": int(deployment_id or 0),
            },
        )
        row = result.mappings().first()
        if row is None:
            return self.snapshot(
                user_broker_account_id=user_broker_account_id,
                broker_code=broker_code,
                strategy_id=strategy_id,
                deployment_id=deployment_id,
                trading_date=day,
            )
        return {
            "trading_date": day.isoformat(),
            "submit_count": int(row["submit_count"]),
            "filled_entry_count": int(row["filled_entry_count"]),
            "released": True,
        }

    def record_filled_entry(
        self,
        *,
        user_broker_account_id: int,
        broker_code: str,
        strategy_id: int,
        deployment_id: int | None,
        entry_order_id: int,
        trading_date: date | None = None,
    ) -> dict[str, Any]:
        """첫 fill / 신규 OPEN binding — entry_order_id당 1회만 +1."""

        day = trading_date or trading_date_kst()
        oid = int(entry_order_id)
        row = self.get_or_create(
            user_broker_account_id=user_broker_account_id,
            broker_code=broker_code,
            strategy_id=strategy_id,
            deployment_id=deployment_id,
            trading_date=day,
            for_update=True,
        )
        seen = list(row.filled_entry_order_ids or [])
        # JSONB may return list already
        if not isinstance(seen, list):
            seen = []
        if oid in seen or str(oid) in {str(x) for x in seen}:
            return {
                "incremented": False,
                "submit_count": int(row.submit_count or 0),
                "filled_entry_count": int(row.filled_entry_count or 0),
                "entry_order_id": oid,
            }
        seen.append(oid)
        row.filled_entry_order_ids = seen
        row.filled_entry_count = int(row.filled_entry_count or 0) + 1
        row.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        return {
            "incremented": True,
            "submit_count": int(row.submit_count or 0),
            "filled_entry_count": int(row.filled_entry_count or 0),
            "entry_order_id": oid,
        }
