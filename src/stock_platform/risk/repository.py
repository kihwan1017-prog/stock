from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.risk.persistence_models import (
    PositionPlanEntity,
    RiskPolicyEntity,
)


class RiskRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save_policy(
        self,
        policy: RiskPolicyEntity,
    ) -> RiskPolicyEntity:
        self._session.add(policy)
        self._session.commit()
        self._session.refresh(policy)
        return policy

    def get_policy(
        self,
        policy_id: int,
    ) -> RiskPolicyEntity | None:
        return self._session.get(RiskPolicyEntity, policy_id)

    def get_policy_by_name(
        self,
        policy_name: str,
    ) -> RiskPolicyEntity | None:
        return self._session.scalar(
            select(RiskPolicyEntity).where(
                RiskPolicyEntity.policy_name == policy_name
            )
        )

    def list_active_policies(self) -> list[RiskPolicyEntity]:
        stmt = (
            select(RiskPolicyEntity)
            .where(RiskPolicyEntity.is_active.is_(True))
            .order_by(RiskPolicyEntity.policy_name.asc())
        )
        return list(self._session.scalars(stmt))

    def save_position_plan(
        self,
        plan: PositionPlanEntity,
    ) -> PositionPlanEntity:
        self._session.add(plan)
        self._session.commit()
        self._session.refresh(plan)
        return plan
