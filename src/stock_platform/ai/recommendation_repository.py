"""사용자 AI 추천 Repository — STEP70."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.recommendation_models import (
    AiRecommendationRequest,
    AiRecommendationResult,
    UserAiRecommendationState,
)


class AiRecommendationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_request(
        self, row: AiRecommendationRequest
    ) -> AiRecommendationRequest:
        self._session.add(row)
        self._session.commit()
        self._session.refresh(row)
        return row

    def save(self) -> None:
        self._session.commit()

    def get_owned(
        self, *, user_id: int, request_id: int
    ) -> AiRecommendationRequest | None:
        return self._session.scalar(
            select(AiRecommendationRequest).where(
                AiRecommendationRequest.request_id == request_id,
                AiRecommendationRequest.user_id == user_id,
            )
        )

    def find_active_by_hash(
        self, *, user_id: int, input_hash: str
    ) -> AiRecommendationRequest | None:
        return self._session.scalar(
            select(AiRecommendationRequest)
            .where(
                AiRecommendationRequest.user_id == user_id,
                AiRecommendationRequest.input_hash == input_hash,
                AiRecommendationRequest.status.in_(
                    ("QUEUED", "PROCESSING", "COMPLETED")
                ),
            )
            .order_by(AiRecommendationRequest.created_at.desc())
            .limit(1)
        )

    def list_for_user(
        self,
        *,
        user_id: int,
        limit: int = 20,
        offset: int = 0,
        market_code: str | None = None,
        status: str | None = None,
        bookmarked_only: bool = False,
        include_hidden: bool = False,
    ) -> list[AiRecommendationRequest]:
        stmt = select(AiRecommendationRequest).where(
            AiRecommendationRequest.user_id == user_id
        )
        if market_code:
            stmt = stmt.where(
                AiRecommendationRequest.market_code == market_code.upper()
            )
        if status:
            stmt = stmt.where(AiRecommendationRequest.status == status.upper())
        if bookmarked_only or not include_hidden:
            stmt = stmt.outerjoin(
                UserAiRecommendationState,
                (
                    UserAiRecommendationState.request_id
                    == AiRecommendationRequest.request_id
                )
                & (UserAiRecommendationState.user_id == user_id),
            )
            if bookmarked_only:
                stmt = stmt.where(
                    UserAiRecommendationState.is_bookmarked.is_(True)
                )
            if not include_hidden:
                stmt = stmt.where(
                    (UserAiRecommendationState.request_id.is_(None))
                    | (UserAiRecommendationState.is_hidden.is_(False))
                )
        stmt = (
            stmt.order_by(AiRecommendationRequest.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self._session.scalars(stmt).unique())

    def count_for_user(
        self,
        *,
        user_id: int,
        market_code: str | None = None,
        status: str | None = None,
        bookmarked_only: bool = False,
        include_hidden: bool = False,
    ) -> int:
        from sqlalchemy import func

        stmt = select(func.count(AiRecommendationRequest.request_id)).where(
            AiRecommendationRequest.user_id == user_id
        )
        if market_code:
            stmt = stmt.where(
                AiRecommendationRequest.market_code == market_code.upper()
            )
        if status:
            stmt = stmt.where(AiRecommendationRequest.status == status.upper())
        if bookmarked_only or not include_hidden:
            stmt = stmt.select_from(AiRecommendationRequest).outerjoin(
                UserAiRecommendationState,
                (
                    UserAiRecommendationState.request_id
                    == AiRecommendationRequest.request_id
                )
                & (UserAiRecommendationState.user_id == user_id),
            )
            if bookmarked_only:
                stmt = stmt.where(
                    UserAiRecommendationState.is_bookmarked.is_(True)
                )
            if not include_hidden:
                stmt = stmt.where(
                    (UserAiRecommendationState.request_id.is_(None))
                    | (UserAiRecommendationState.is_hidden.is_(False))
                )
        return int(self._session.scalar(stmt) or 0)

    def list_results(
        self, request_id: int
    ) -> list[AiRecommendationResult]:
        return list(
            self._session.scalars(
                select(AiRecommendationResult)
                .where(AiRecommendationResult.request_id == request_id)
                .order_by(AiRecommendationResult.rank.asc())
            )
        )

    def list_top_results_batch(
        self, request_ids: list[int]
    ) -> dict[int, AiRecommendationResult]:
        if not request_ids:
            return {}
        rows = list(
            self._session.scalars(
                select(AiRecommendationResult)
                .where(AiRecommendationResult.request_id.in_(request_ids))
                .order_by(
                    AiRecommendationResult.request_id.asc(),
                    AiRecommendationResult.rank.asc(),
                )
            )
        )
        result: dict[int, AiRecommendationResult] = {}
        for row in rows:
            if int(row.request_id) not in result:
                result[int(row.request_id)] = row
        return result

    def replace_results(
        self,
        request_id: int,
        rows: list[AiRecommendationResult],
    ) -> None:
        existing = self.list_results(request_id)
        for row in existing:
            self._session.delete(row)
        for row in rows:
            self._session.add(row)
        self._session.commit()

    def get_or_create_state(
        self, *, user_id: int, request_id: int
    ) -> UserAiRecommendationState:
        row = self._session.scalar(
            select(UserAiRecommendationState).where(
                UserAiRecommendationState.user_id == user_id,
                UserAiRecommendationState.request_id == request_id,
            )
        )
        if row is not None:
            return row
        row = UserAiRecommendationState(
            user_id=user_id, request_id=request_id
        )
        self._session.add(row)
        self._session.commit()
        self._session.refresh(row)
        return row

    def list_states(
        self, *, user_id: int, request_ids: list[int]
    ) -> dict[int, UserAiRecommendationState]:
        if not request_ids:
            return {}
        rows = list(
            self._session.scalars(
                select(UserAiRecommendationState).where(
                    UserAiRecommendationState.user_id == user_id,
                    UserAiRecommendationState.request_id.in_(request_ids),
                )
            )
        )
        return {int(r.request_id): r for r in rows}

    def latest_completed(
        self, *, user_id: int, market_code: str | None = None
    ) -> AiRecommendationRequest | None:
        stmt = select(AiRecommendationRequest).where(
            AiRecommendationRequest.user_id == user_id,
            AiRecommendationRequest.status == "COMPLETED",
        )
        if market_code:
            stmt = stmt.where(
                AiRecommendationRequest.market_code == market_code.upper()
            )
        stmt = stmt.order_by(
            AiRecommendationRequest.completed_at.desc().nullslast(),
            AiRecommendationRequest.request_id.desc(),
        ).limit(1)
        return self._session.scalar(stmt)
