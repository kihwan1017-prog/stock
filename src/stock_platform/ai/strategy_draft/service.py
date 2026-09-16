"""STEP 12-2-1 — Strategy Draft 저장/버전관리 서비스.

승인(APPROVED)된 Strategy Request 위에 Strategy Draft를 저장·버전관리하는
기반 구조만 다룬다. AI 호출, Prompt 생성, LLM Provider 호출, Strategy 자동
생성, Backtest, Paper Trading, Runtime/Order/Broker/Scheduler WRITE는 이
서비스의 범위가 아니다(STEP12-2-2 이후).

Version/Revision 정책은 constants.py 모듈 docstring 참고.

동시성(STEP12-2-1A): 새 Version/Revision 생성은 다음 고정 순서로 잠근다.
    1. StrategyRequestEntity FOR UPDATE
    2. AICandidateLifecycleEntity FOR UPDATE
    3. 기존 활성(latest) StrategyDraftEntity FOR UPDATE
candidate_lifecycle 쪽의 expire/revoke(approve_revocation)/supersede는
이 서비스가 잠그는 것과 동일한 candidate_lifecycle 행을 FOR UPDATE로
잠그므로(STEP12-1A에서 확인), 두 서비스가 동시에 같은 Candidate를
대상으로 호출돼도 Postgres가 직렬화한다.

STEP12-2-1A 재검증 정책: 새 Version 생성(create)과 새 Revision 생성
(create_revision) 모두 Candidate Lifecycle 현재 상태 + fingerprint를
재검증한다("같은 승인 안의 단순 편집"으로 간주해 재검증을 생략하는 대신,
Revision도 새 활성 Draft 행을 만드는 행위이므로 동일한 안전 기준을
적용 — 근거는 서비스 docstring 및 완료 보고 참고). update()/archive()는
기존 행의 상태만 바꾸거나 내용을 편집할 뿐 새로운 "근거 채택"이 아니므로
재검증하지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stock_platform.ai.candidate_lifecycle.entities import AICandidateLifecycleEntity
from stock_platform.ai.strategy_draft.constants import (
    ALLOWED_TRANSITIONS,
    CONTENT_FIELDS,
    ELIGIBLE_STRATEGY_REQUEST_STATUS,
)
from stock_platform.ai.strategy_draft.entities import (
    StrategyDraftEntity,
    StrategyDraftHistoryEntity,
)
from stock_platform.ai.strategy_request.constants import (
    ELIGIBLE_CANDIDATE_LIFECYCLE_STATUSES,
)
from stock_platform.ai.strategy_request.entities import StrategyRequestEntity


class StrategyDraftError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_dict(row: StrategyDraftEntity) -> dict[str, Any]:
    return {
        "draft_id": int(row.draft_id),
        "strategy_request_id": int(row.strategy_request_id),
        "version": int(row.version),
        "revision": int(row.revision),
        "label": (
            f"v{row.version}"
            if row.revision == 1
            else f"v{row.version}-r{row.revision}"
        ),
        "status": row.status,
        "title": row.title,
        "summary": row.summary,
        "entry_rule": row.entry_rule,
        "exit_rule": row.exit_rule,
        "stop_loss_rule": row.stop_loss_rule,
        "take_profit_rule": row.take_profit_rule,
        "position_sizing_rule": row.position_sizing_rule,
        "timeframe": row.timeframe,
        "market_type": row.market_type,
        "risk_parameters": row.risk_parameters,
        "indicator_configuration": row.indicator_configuration,
        "llm_provider": row.llm_provider,
        "llm_model": row.llm_model,
        "prompt_version": row.prompt_version,
        "candidate_fingerprint": row.candidate_fingerprint,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _history_to_dict(row: StrategyDraftHistoryEntity) -> dict[str, Any]:
    return {
        "history_id": int(row.history_id),
        "draft_id": int(row.draft_id),
        "action": row.action,
        "previous_status": row.previous_status,
        "new_status": row.new_status,
        "previous_version": row.previous_version,
        "new_version": row.new_version,
        "previous_revision": row.previous_revision,
        "new_revision": row.new_revision,
        "reason": row.reason,
        "actor": row.actor,
        "correlation_id": row.correlation_id,
        "created_at": row.created_at,
    }


class StrategyDraftService:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 공용 재검증 헬퍼 (STEP12-2-2 Generation 서비스와 공유)
    # ------------------------------------------------------------------
    def validate_creatable(
        self, strategy_request_id: int
    ) -> tuple[StrategyRequestEntity, AICandidateLifecycleEntity]:
        """Draft 생성 가능 여부를 잠금과 함께 검증한다.

        `create()`가 내부적으로 쓰는 것과 동일한 재검증(request 잠금 ->
        candidate 잠금/상태/fingerprint 확인)을 공개 메서드로 노출해,
        STEP12-2-2의 Generation 서비스가 AI 호출 전/후 두 차례 동일한
        검증을 중복 구현 없이 재사용할 수 있게 한다. 호출자는 이미 이
        세션의 트랜잭션 안에 있어야 하며, 반환 후에도 잠금은 트랜잭션이
        끝날 때까지 유지된다.
        """
        request = self._lock_request(strategy_request_id)
        candidate = self._lock_and_validate_candidate(request)
        return request, candidate

    # ------------------------------------------------------------------
    # 생성 (신규 Draft / 새 Version)
    # ------------------------------------------------------------------
    def create(
        self,
        *,
        strategy_request_id: int,
        actor: str,
        title: str,
        timeframe: str,
        market_type: str,
        summary: str | None = None,
        entry_rule: str | None = None,
        exit_rule: str | None = None,
        stop_loss_rule: str | None = None,
        take_profit_rule: str | None = None,
        position_sizing_rule: str | None = None,
        risk_parameters: dict[str, Any] | None = None,
        indicator_configuration: dict[str, Any] | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        prompt_version: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        request, candidate = self.validate_creatable(strategy_request_id)

        latest = self._session.scalar(
            select(StrategyDraftEntity)
            .where(StrategyDraftEntity.strategy_request_id == int(strategy_request_id))
            .order_by(
                StrategyDraftEntity.version.desc(),
                StrategyDraftEntity.revision.desc(),
            )
            .limit(1)
            .with_for_update()
        )

        if latest is None:
            new_version = 1
        else:
            new_version = int(latest.version) + 1
            if latest.status == "DRAFT":
                previous_status = latest.status
                latest.status = "SUPERSEDED"
                self._session.flush()
                self._record_history(
                    latest,
                    action="SUPERSEDED",
                    previous_status=previous_status,
                    new_status="SUPERSEDED",
                    reason="새 Version 생성으로 대체됨",
                    actor=actor,
                    correlation_id=correlation_id,
                )

        row = StrategyDraftEntity(
            strategy_request_id=int(strategy_request_id),
            version=new_version,
            revision=1,
            status="DRAFT",
            title=title,
            summary=summary,
            entry_rule=entry_rule,
            exit_rule=exit_rule,
            stop_loss_rule=stop_loss_rule,
            take_profit_rule=take_profit_rule,
            position_sizing_rule=position_sizing_rule,
            timeframe=timeframe,
            market_type=market_type,
            risk_parameters=risk_parameters,
            indicator_configuration=indicator_configuration,
            llm_provider=llm_provider,
            llm_model=llm_model,
            prompt_version=prompt_version,
            # 요청 시점 스냅샷이 아니라 방금 재검증한 "현재" fingerprint를
            # 저장한다(STEP12-2-1A) — 이 시점에 이미 승인 시점 값과 일치함을
            # 확인했으므로 값 자체는 동일하지만, 의미상 "검증된 현재값"임을
            # 명확히 하기 위해 candidate에서 다시 가져온다.
            candidate_fingerprint=candidate.source_fingerprint,
            created_by=actor,
        )
        self._session.add(row)
        try:
            self._session.flush()
        except IntegrityError as exc:
            self._session.rollback()
            raise StrategyDraftError(
                "DUPLICATE_ACTIVE_DRAFT",
                "이미 활성(DRAFT) Draft가 존재합니다(동시 생성 감지).",
            ) from exc

        self._record_history(
            row,
            action="CREATE_VERSION" if latest is not None else "CREATE",
            previous_status=None,
            new_status="DRAFT",
            previous_version=latest.version if latest is not None else None,
            new_version=new_version,
            previous_revision=None,
            new_revision=1,
            reason=None,
            actor=actor,
            correlation_id=correlation_id,
        )
        self._session.commit()
        self._session.refresh(row)
        return _to_dict(row)

    def create_revision(
        self,
        draft_id: int,
        *,
        actor: str,
        reason: str | None = None,
        correlation_id: str | None = None,
        **content_overrides: Any,
    ) -> dict[str, Any]:
        old_row, candidate = self._lock_draft_via_request_with_candidate(draft_id)

        allowed = ALLOWED_TRANSITIONS.get(old_row.status, frozenset())
        if "REGENERATED" not in allowed:
            raise StrategyDraftError(
                "INVALID_STATE_TRANSITION",
                f"{old_row.status} 상태에서는 Revision을 생성할 수 없습니다.",
            )

        fields = {name: getattr(old_row, name) for name in CONTENT_FIELDS}
        for key, value in content_overrides.items():
            if key in CONTENT_FIELDS and value is not None:
                fields[key] = value

        new_row = StrategyDraftEntity(
            strategy_request_id=old_row.strategy_request_id,
            version=old_row.version,
            revision=int(old_row.revision) + 1,
            status="DRAFT",
            candidate_fingerprint=candidate.source_fingerprint,
            created_by=actor,
            **fields,
        )
        self._session.add(new_row)

        previous_status = old_row.status
        old_row.status = "REGENERATED"
        try:
            self._session.flush()
        except IntegrityError as exc:
            self._session.rollback()
            raise StrategyDraftError(
                "DUPLICATE_ACTIVE_DRAFT",
                "이미 활성(DRAFT) Draft가 존재합니다(동시 생성 감지).",
            ) from exc

        self._record_history(
            old_row,
            action="REGENERATED",
            previous_status=previous_status,
            new_status="REGENERATED",
            reason=reason,
            actor=actor,
            correlation_id=correlation_id,
        )
        self._record_history(
            new_row,
            action="CREATE_REVISION",
            previous_status=None,
            new_status="DRAFT",
            previous_version=old_row.version,
            new_version=new_row.version,
            previous_revision=old_row.revision,
            new_revision=new_row.revision,
            reason=reason,
            actor=actor,
            correlation_id=correlation_id,
        )
        self._session.commit()
        self._session.refresh(new_row)
        return _to_dict(new_row)

    # ------------------------------------------------------------------
    # 수정 (내용 편집 — Version/Revision 변경 없음)
    # ------------------------------------------------------------------
    def update(
        self,
        draft_id: int,
        *,
        actor: str,
        reason: str | None = None,
        correlation_id: str | None = None,
        **content_overrides: Any,
    ) -> dict[str, Any]:
        row = self._lock_draft_via_request(draft_id)
        if row.status != "DRAFT":
            raise StrategyDraftError(
                "INVALID_STATE_TRANSITION",
                f"{row.status} 상태의 Draft는 수정할 수 없습니다(DRAFT만 편집 가능).",
            )
        if row.llm_provider is not None:
            # STEP12-2-3: AI가 생성한 원본 Draft를 PATCH로 직접 덮어쓰면
            # llm_provider/llm_model/prompt_version/candidate_fingerprint는
            # 그대로 남은 채 실제 내용만 바뀌어, "이 Provenance로 생성된
            # 결과"라는 기록이 사실과 달라지는 provenance 훼손이 발생한다.
            # AI 생성 Draft는 직접 수정을 막고 create_revision()으로 새
            # Revision을 만들도록 강제한다(원본은 REGENERATED로 보존).
            raise StrategyDraftError(
                "AI_GENERATED_DRAFT_REQUIRES_REVISION",
                (
                    "AI가 생성한 Draft는 직접 수정할 수 없습니다. "
                    "create_revision()으로 새 Revision을 생성하세요."
                ),
            )

        changed = False
        for key, value in content_overrides.items():
            if key in CONTENT_FIELDS and value is not None:
                setattr(row, key, value)
                changed = True

        if not changed:
            return _to_dict(row)

        self._session.flush()
        self._record_history(
            row,
            action="UPDATE",
            previous_status=row.status,
            new_status=row.status,
            reason=reason,
            actor=actor,
            correlation_id=correlation_id,
        )
        self._session.commit()
        self._session.refresh(row)
        return _to_dict(row)

    # ------------------------------------------------------------------
    # Archive
    # ------------------------------------------------------------------
    def archive(
        self,
        draft_id: int,
        *,
        actor: str,
        reason: str | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        row = self._lock_draft_via_request(draft_id)
        allowed = ALLOWED_TRANSITIONS.get(row.status, frozenset())
        if "ARCHIVED" not in allowed:
            raise StrategyDraftError(
                "INVALID_STATE_TRANSITION",
                f"{row.status} -> ARCHIVED 전이는 허용되지 않습니다.",
            )
        previous_status = row.status
        row.status = "ARCHIVED"
        self._session.flush()
        self._record_history(
            row,
            action="ARCHIVE",
            previous_status=previous_status,
            new_status="ARCHIVED",
            reason=reason,
            actor=actor,
            correlation_id=correlation_id,
        )
        self._session.commit()
        self._session.refresh(row)
        return _to_dict(row)

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    def get(self, draft_id: int) -> dict[str, Any]:
        return _to_dict(self._require(draft_id))

    def get_owned(self, draft_id: int, *, user_id: int) -> dict[str, Any]:
        row = self._require(draft_id)
        request = self._session.get(StrategyRequestEntity, row.strategy_request_id)
        if request is None or int(request.user_id) != int(user_id):
            raise StrategyDraftError(
                "OWNERSHIP_DENIED", "본인 Strategy Request의 Draft가 아닙니다."
            )
        return _to_dict(row)

    def list(
        self,
        *,
        strategy_request_id: int | None = None,
        status: str | None = None,
        user_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        stmt = select(StrategyDraftEntity)
        if user_id is not None:
            stmt = stmt.join(
                StrategyRequestEntity,
                StrategyRequestEntity.strategy_request_id
                == StrategyDraftEntity.strategy_request_id,
            ).where(StrategyRequestEntity.user_id == int(user_id))
        if strategy_request_id is not None:
            stmt = stmt.where(
                StrategyDraftEntity.strategy_request_id == int(strategy_request_id)
            )
        if status is not None:
            stmt = stmt.where(StrategyDraftEntity.status == status)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = int(self._session.scalar(count_stmt) or 0)

        rows = list(
            self._session.scalars(
                stmt.order_by(StrategyDraftEntity.draft_id.desc())
                .offset(max(0, offset))
                .limit(min(max(limit, 1), 200))
            )
        )
        return {"items": [_to_dict(r) for r in rows], "total": total}

    def get_version(self, strategy_request_id: int, version: int) -> dict[str, Any]:
        rows = list(
            self._session.scalars(
                select(StrategyDraftEntity)
                .where(
                    StrategyDraftEntity.strategy_request_id == int(strategy_request_id),
                    StrategyDraftEntity.version == int(version),
                )
                .order_by(StrategyDraftEntity.revision.asc())
            )
        )
        if not rows:
            raise StrategyDraftError(
                "NOT_FOUND",
                f"Version {version} not found for strategy_request "
                f"{strategy_request_id}",
            )
        return {
            "strategy_request_id": int(strategy_request_id),
            "version": int(version),
            "items": [_to_dict(r) for r in rows],
        }

    def get_history(
        self, draft_id: int, *, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        self._require(draft_id)
        stmt = (
            select(StrategyDraftHistoryEntity)
            .where(StrategyDraftHistoryEntity.draft_id == int(draft_id))
            .order_by(StrategyDraftHistoryEntity.history_id.desc())
            .offset(max(0, offset))
            .limit(min(max(limit, 1), 200))
        )
        rows = list(self._session.scalars(stmt))
        return {"items": [_history_to_dict(r) for r in rows]}

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------
    def _require(self, draft_id: int) -> StrategyDraftEntity:
        row = self._session.get(StrategyDraftEntity, int(draft_id))
        if row is None:
            raise StrategyDraftError(
                "NOT_FOUND", f"Strategy Draft not found: {draft_id}"
            )
        return row

    def _lock_request(self, strategy_request_id: int) -> StrategyRequestEntity:
        request = self._session.scalar(
            select(StrategyRequestEntity)
            .where(
                StrategyRequestEntity.strategy_request_id == int(strategy_request_id)
            )
            .with_for_update()
        )
        if request is None:
            raise StrategyDraftError(
                "STRATEGY_REQUEST_NOT_FOUND",
                f"Strategy Request not found: {strategy_request_id}",
            )
        if request.status != ELIGIBLE_STRATEGY_REQUEST_STATUS:
            raise StrategyDraftError(
                "STRATEGY_REQUEST_NOT_APPROVED",
                (
                    f"APPROVED 상태의 Strategy Request만 Draft를 생성할 수 "
                    f"있습니다. 현재 상태: {request.status}"
                ),
            )
        return request

    def _lock_and_validate_candidate(
        self, request: StrategyRequestEntity
    ) -> AICandidateLifecycleEntity:
        """새 Version/Revision 생성 직전 Candidate 재검증(STEP12-2-1A).

        호출자가 이미 request(StrategyRequestEntity)를 FOR UPDATE로 잠근
        뒤 호출해야 한다(고정 순서: request -> candidate).
        """
        candidate = self._session.scalar(
            select(AICandidateLifecycleEntity)
            .where(
                AICandidateLifecycleEntity.candidate_id == int(request.candidate_id)
            )
            .with_for_update()
        )
        if candidate is None:
            raise StrategyDraftError(
                "CANDIDATE_NOT_FOUND",
                f"Candidate not found: {request.candidate_id}",
            )
        if candidate.lifecycle_status not in ELIGIBLE_CANDIDATE_LIFECYCLE_STATUSES:
            raise StrategyDraftError(
                "CANDIDATE_NOT_ACTIVE_AT_DRAFT",
                (
                    "Draft 생성 재검증 실패 — ACTIVE 상태(PROMOTED/ACTIVE_REVIEW) "
                    f"Candidate만 가능합니다. 현재 상태: {candidate.lifecycle_status}"
                ),
            )

        approved_fingerprint = request.candidate_fingerprint_at_review
        if approved_fingerprint is None:
            # 레거시 데이터(STEP12-1A 이전에 승인된 요청)는 승인 시점
            # fingerprint 기록이 없어 변경 여부를 검증할 수 없다. 안전하게
            # 재검증/backfill하는 대신 생성을 차단한다(묵시적 통과 금지).
            raise StrategyDraftError(
                "CANDIDATE_FINGERPRINT_CHANGED",
                (
                    "승인 시점 fingerprint 기록이 없어 안전성을 확인할 수 "
                    "없습니다(레거시 승인 데이터). Draft 생성이 차단됩니다."
                ),
            )
        if candidate.source_fingerprint != approved_fingerprint:
            raise StrategyDraftError(
                "CANDIDATE_FINGERPRINT_CHANGED",
                "현재 Candidate fingerprint가 승인 시점과 다릅니다(Candidate 변경 감지).",
            )
        return candidate

    def _lock_draft_via_request_with_candidate(
        self, draft_id: int
    ) -> tuple[StrategyDraftEntity, AICandidateLifecycleEntity]:
        """request -> candidate -> draft 순으로 잠그고 Candidate를 재검증한다.

        create_revision()에서 사용 — 새 Revision도 새로운 활성 Draft 행을
        만드는 행위이므로 create()와 동일한 재검증 기준을 적용한다.
        """
        preview = self._session.get(StrategyDraftEntity, int(draft_id))
        if preview is None:
            raise StrategyDraftError(
                "NOT_FOUND", f"Strategy Draft not found: {draft_id}"
            )
        request = self._session.scalar(
            select(StrategyRequestEntity)
            .where(
                StrategyRequestEntity.strategy_request_id
                == preview.strategy_request_id
            )
            .with_for_update()
        )
        if request is None:
            raise StrategyDraftError(
                "STRATEGY_REQUEST_NOT_FOUND",
                f"Strategy Request not found: {preview.strategy_request_id}",
            )
        candidate = self._lock_and_validate_candidate(request)
        row = self._session.scalar(
            select(StrategyDraftEntity)
            .where(StrategyDraftEntity.draft_id == int(draft_id))
            .with_for_update()
        )
        if row is None:
            raise StrategyDraftError(
                "NOT_FOUND", f"Strategy Draft not found: {draft_id}"
            )
        return row, candidate

    def _lock_draft_via_request(self, draft_id: int) -> StrategyDraftEntity:
        """부모 strategy_request -> 대상 draft 순으로 잠근다(고정 순서).

        create()도 동일하게 strategy_request를 먼저 잠그므로, 두 메서드가
        동시에 같은 Strategy Request를 대상으로 호출돼도 교착상태 없이
        직렬화된다.
        """
        preview = self._session.get(StrategyDraftEntity, int(draft_id))
        if preview is None:
            raise StrategyDraftError(
                "NOT_FOUND", f"Strategy Draft not found: {draft_id}"
            )
        self._session.scalar(
            select(StrategyRequestEntity)
            .where(
                StrategyRequestEntity.strategy_request_id
                == preview.strategy_request_id
            )
            .with_for_update()
        )
        row = self._session.scalar(
            select(StrategyDraftEntity)
            .where(StrategyDraftEntity.draft_id == int(draft_id))
            .with_for_update()
        )
        if row is None:
            raise StrategyDraftError(
                "NOT_FOUND", f"Strategy Draft not found: {draft_id}"
            )
        return row

    def _record_history(
        self,
        row: StrategyDraftEntity,
        *,
        action: str,
        previous_status: str | None,
        new_status: str | None,
        actor: str,
        correlation_id: str | None,
        reason: str | None = None,
        previous_version: int | None = None,
        new_version: int | None = None,
        previous_revision: int | None = None,
        new_revision: int | None = None,
    ) -> None:
        history = StrategyDraftHistoryEntity(
            draft_id=int(row.draft_id),
            action=action,
            previous_status=previous_status,
            new_status=new_status,
            previous_version=previous_version,
            new_version=new_version,
            previous_revision=previous_revision,
            new_revision=new_revision,
            reason=(reason or "").strip()[:1000] or None,
            actor=actor,
            correlation_id=correlation_id,
        )
        self._session.add(history)
        self._session.flush()
