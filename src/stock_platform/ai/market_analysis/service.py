"""STEP 11-7 — Market/Chart Analysis Service (create ≠ execute)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.execution.runner import AIExecutionRunner
from stock_platform.ai.execution.service import AIExecutionError, AIExecutionService
from stock_platform.ai.market_analysis.constants import (
    ANALYSIS_ENGINE_VERSION,
    HARD_BATCH_CAP,
    INDICATOR_VERSION,
    MAX_BATCH_EXTERNAL,
    MAX_BATCH_MOCK,
    REFERENCE_DISCLAIMER,
)
from stock_platform.ai.market_analysis.eligibility import AIMarketEligibilityService
from stock_platform.ai.market_analysis.entities import (
    AIMarketAnalysisEntity,
    AIMarketAnalysisHistoryEntity,
    AIMarketAnalysisIndicatorEntity,
    AIMarketAnalysisKrxLinkEntity,
    AIMarketAnalysisLevelEntity,
    AIMarketAnalysisSnapshotRefEntity,
    AIMarketAnalysisUpbitLinkEntity,
)
from stock_platform.ai.market_analysis.snapshot import validate_ai_numerics
from stock_platform.ai.providers.security import sanitize_for_log


class AIMarketAnalysisError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _analysis_key(
    *,
    analysis_type: str,
    exchange: str,
    symbol: str | None,
    timeframe: str | None,
    snapshot_hash: str,
    prompt_version_id: int | None,
    schema_id: int | None,
    provider: str,
    model: str,
) -> str:
    raw = (
        f"{analysis_type}:{exchange}:{symbol or '-'}:{timeframe or '-'}:"
        f"{snapshot_hash}:p{prompt_version_id or 0}:s{schema_id or 0}:"
        f"{provider}:{model}:{ANALYSIS_ENGINE_VERSION}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


class AIMarketAnalysisService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._eligibility = AIMarketEligibilityService(session)
        self._exec = AIExecutionService(session)

    def _history(
        self,
        analysis_id: int,
        *,
        action: str,
        actor: str,
        previous: str | None = None,
        new: str | None = None,
        reason: str | None = None,
        correlation_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._session.add(
            AIMarketAnalysisHistoryEntity(
                market_analysis_id=analysis_id,
                action=action,
                previous_status=previous,
                new_status=new,
                reason=reason,
                requested_by=actor,
                correlation_id=correlation_id,
                detail_sanitized=sanitize_for_log(detail or {}),
            )
        )

    def _public(self, row: AIMarketAnalysisEntity) -> dict[str, Any]:
        return {
            "id": row.market_analysis_id,
            "analysis_key": row.analysis_key,
            "analysis_type": row.analysis_type,
            "market_type": row.market_type,
            "exchange_code": row.exchange_code,
            "symbol": row.symbol,
            "timeframe": row.timeframe,
            "snapshot_key": row.snapshot_key,
            "snapshot_version": row.snapshot_version,
            "snapshot_hash": row.snapshot_hash,
            "snapshot_at": row.snapshot_at.isoformat() if row.snapshot_at else None,
            "candle_count": row.candle_count,
            "indicator_version": row.indicator_version,
            "task_type": row.task_type,
            "analysis_status": row.analysis_status,
            "execution_mode": row.execution_mode,
            "data_classification": row.data_classification,
            "data_quality_status": row.data_quality_status,
            "execution_request_id": row.execution_request_id,
            "provider_code": row.provider_code,
            "model": row.model,
            "prompt_version_id": row.prompt_version_id,
            "confidence": row.confidence,
            "trend_classification": row.trend_classification,
            "volatility_level": row.volatility_level,
            "market_regime": row.market_regime,
            "warnings": row.warnings,
            "safe_result": row.safe_result,
            "vision_used": row.vision_used,
            "analyzed_at": row.analyzed_at.isoformat() if row.analyzed_at else None,
            "superseded_at": (
                row.superseded_at.isoformat() if row.superseded_at else None
            ),
            "superseded_by_id": row.superseded_by_id,
            "created_by": row.created_by,
            "reason": row.reason,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    def create(
        self,
        *,
        actor: str,
        reason: str,
        analysis_type: str,
        exchange_code: str,
        symbol: str | None = None,
        timeframe: str = "1D",
        data_from: date | None = None,
        data_to: date | None = None,
        include_incomplete_candle: bool = False,
        execution_mode: str = "MOCK",
        provider_code: str | None = None,
        model: str | None = None,
        prompt_version_id: int | None = None,
        max_tokens: int = 512,
        timeout_sec: float = 30.0,
        fallback_enabled: bool = False,
        idempotency_key: str,
        force_new_version: bool = False,
        correlation_id: str | None = None,
        use_vision: bool = False,
    ) -> dict[str, Any]:
        existing = self._session.scalar(
            select(AIMarketAnalysisEntity).where(
                AIMarketAnalysisEntity.created_by == actor,
                AIMarketAnalysisEntity.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return {
                "idempotent_replay": True,
                "analysis": self._public(existing),
            }

        eval_result = self._eligibility.evaluate(
            analysis_type=analysis_type,
            exchange_code=exchange_code,
            symbol=symbol,
            timeframe=timeframe,
            data_from=data_from,
            data_to=data_to,
            include_incomplete_candle=include_incomplete_candle,
            execution_mode=execution_mode,
            provider_code=provider_code or "mock",
            prompt_version_id=prompt_version_id,
            use_vision=use_vision,
        )
        if not eval_result["eligible"]:
            raise AIMarketAnalysisError(
                "NOT_ELIGIBLE",
                ",".join(eval_result.get("blockers") or ["blocked"]),
            )

        snap_wrap = eval_result["snapshot"]
        snapshot = snap_wrap["snapshot"]
        provider = (provider_code or "mock").lower()
        model_name = model or ("mock-v1" if provider == "mock" else "default")
        key = _analysis_key(
            analysis_type=analysis_type,
            exchange=exchange_code.upper(),
            symbol=symbol,
            timeframe=timeframe if analysis_type == "SYMBOL_CHART" else None,
            snapshot_hash=snap_wrap["snapshot_hash"],
            prompt_version_id=eval_result.get("prompt_version_id"),
            schema_id=eval_result.get("schema_id"),
            provider=provider,
            model=model_name,
        )
        same = self._session.scalar(
            select(AIMarketAnalysisEntity).where(
                AIMarketAnalysisEntity.analysis_key == key,
                AIMarketAnalysisEntity.analysis_status.notin_(
                    ["SUPERSEDED", "CANCELLED", "FAILED"]
                ),
            )
        )
        if same is not None and not force_new_version:
            return {
                "idempotent_replay": True,
                "analysis": self._public(same),
                "code": "DUPLICATE_ANALYSIS",
            }

        # Prompt 입력 — Snapshot 요약 (전체 candle은 execution input에 compact)
        snap_for_prompt = dict(snapshot)
        # 계좌 정보 미포함 보장
        indicators = snapshot.get("indicators") or {}
        if analysis_type == "SYMBOL_CHART":
            input_payload = {
                "symbol": symbol or "",
                "exchange_code": exchange_code.upper(),
                "timeframe": timeframe,
                "indicators": json.dumps(indicators, ensure_ascii=False),
                "current_price": str(snapshot.get("latest_price") or ""),
                "snapshot_json": json.dumps(snap_for_prompt, ensure_ascii=False)[
                    :50_000
                ],
                "market_type": snapshot.get("market_type") or "",
                "data_quality": snap_wrap.get("data_quality_status") or "UNKNOWN",
            }
            task_type = "CHART_ANALYSIS"
        else:
            input_payload = {
                "exchange_code": exchange_code.upper(),
                "market_type": snapshot.get("market_type") or "",
                "snapshot_json": json.dumps(snap_for_prompt, ensure_ascii=False)[
                    :50_000
                ],
                "data_quality": snap_wrap.get("data_quality_status") or "UNKNOWN",
                "symbol_count": str(snapshot.get("symbol_count") or 0),
            }
            task_type = "MARKET_ANALYSIS"

        try:
            exec_result = self._exec.create_request(
                actor=actor,
                reason=reason[:500],
                task_type=task_type,
                execution_mode=execution_mode,
                idempotency_key=f"mkt-{idempotency_key}"[:64],
                input_payload=input_payload,
                provider_code=provider,
                requested_model=model_name,
                prompt_template_id=eval_result.get("prompt_template_id"),
                prompt_version_id=eval_result.get("prompt_version_id"),
                output_schema_id=eval_result.get("schema_id"),
                policy_ids=eval_result.get("policy_ids"),
                max_tokens=max_tokens,
                timeout_sec=timeout_sec,
                fallback_enabled=fallback_enabled,
                correlation_id=correlation_id or uuid.uuid4().hex[:32],
            )
        except AIExecutionError as exc:
            raise AIMarketAnalysisError(exc.code, exc.message) from exc

        exec_req = exec_result["request"]
        row = AIMarketAnalysisEntity(
            analysis_key=key
            if not force_new_version
            else f"{key}:{uuid.uuid4().hex[:8]}",
            idempotency_key=idempotency_key,
            analysis_type=analysis_type,
            market_type=str(snapshot.get("market_type") or "UNKNOWN"),
            exchange_code=exchange_code.upper(),
            symbol=symbol,
            timeframe=timeframe if analysis_type == "SYMBOL_CHART" else None,
            snapshot_key=snap_wrap["snapshot_key"],
            snapshot_version=str(snap_wrap.get("snapshot_version") or "1"),
            snapshot_at=_now(),
            data_from=data_from,
            data_to=data_to,
            candle_count=int(snap_wrap.get("candle_count") or 0),
            indicator_version=INDICATOR_VERSION,
            execution_request_id=exec_req["id"],
            task_type=task_type,
            analysis_status="DRAFT_ANALYSIS",
            execution_mode=execution_mode,
            data_classification="PUBLIC",
            prompt_template_id=eval_result.get("prompt_template_id"),
            prompt_version_id=eval_result.get("prompt_version_id"),
            output_schema_id=eval_result.get("schema_id"),
            policy_ids=eval_result.get("policy_ids"),
            provider_code=provider,
            model=model_name,
            input_hash=hashlib.sha256(
                json.dumps(input_payload, sort_keys=True).encode()
            ).hexdigest(),
            snapshot_hash=snap_wrap["snapshot_hash"],
            data_quality_status=str(snap_wrap.get("data_quality_status") or "UNKNOWN"),
            warnings=list(eval_result.get("warnings") or []),
            vision_used=False,
            created_by=actor,
            reason=reason[:500],
            correlation_id=correlation_id or exec_req.get("correlation_id"),
        )
        self._session.add(row)
        self._session.flush()

        instrument_id = snap_wrap.get("instrument_id")
        if instrument_id and analysis_type == "SYMBOL_CHART":
            if exchange_code.upper() == "KRX":
                self._session.add(
                    AIMarketAnalysisKrxLinkEntity(
                        market_analysis_id=row.market_analysis_id,
                        instrument_id=int(instrument_id),
                    )
                )
            elif exchange_code.upper() == "UPBIT":
                self._session.add(
                    AIMarketAnalysisUpbitLinkEntity(
                        market_analysis_id=row.market_analysis_id,
                        instrument_id=int(instrument_id),
                    )
                )

        self._session.add(
            AIMarketAnalysisSnapshotRefEntity(
                market_analysis_id=row.market_analysis_id,
                source_table=(
                    "market.price_daily"
                    if timeframe == "1D"
                    else "market.candle_minute"
                ),
                source_key=snap_wrap["snapshot_key"],
                source_version=str(snap_wrap.get("snapshot_version") or "1"),
                source_hash=snap_wrap["snapshot_hash"],
            )
        )
        if indicators:
            self._session.add(
                AIMarketAnalysisIndicatorEntity(
                    market_analysis_id=row.market_analysis_id,
                    indicator_code="BUNDLE",
                    indicator_version=INDICATOR_VERSION,
                    timeframe=timeframe,
                    value_json=sanitize_for_log(indicators)
                    if isinstance(indicators, dict)
                    else {},
                    quality_status=str(indicators.get("status_code") or "UNKNOWN")
                    if isinstance(indicators, dict)
                    else None,
                )
            )

        self._history(
            row.market_analysis_id,
            action="AI_MARKET_ANALYSIS_CREATED",
            actor=actor,
            new="DRAFT_ANALYSIS",
            reason=reason,
            correlation_id=row.correlation_id,
            detail={
                "snapshot_key": row.snapshot_key,
                "execution_request_id": row.execution_request_id,
            },
        )
        self._history(
            row.market_analysis_id,
            action="AI_MARKET_ANALYSIS_SNAPSHOT_CREATED",
            actor=actor,
            detail={
                "snapshot_hash": row.snapshot_hash,
                "candle_count": row.candle_count,
                "quality": row.data_quality_status,
            },
            correlation_id=row.correlation_id,
        )
        self._session.commit()
        self._session.refresh(row)
        return {
            "idempotent_replay": False,
            "analysis": self._public(row),
            "eligibility_warnings": eval_result.get("warnings"),
        }

    def dry_run(self, analysis_id: int, *, actor: str) -> dict[str, Any]:
        row = self._session.get(AIMarketAnalysisEntity, analysis_id)
        if row is None:
            raise AIMarketAnalysisError("NOT_FOUND", "analysis not found")
        if row.execution_request_id is None:
            raise AIMarketAnalysisError("NO_EXECUTION", "missing execution")
        self._history(
            analysis_id,
            action="AI_MARKET_ANALYSIS_DRY_RUN_STARTED",
            actor=actor,
            previous=row.analysis_status,
            correlation_id=row.correlation_id,
        )
        result = AIExecutionRunner(self._session).dry_run(
            row.execution_request_id, actor=actor
        )
        self._history(
            analysis_id,
            action="AI_MARKET_ANALYSIS_DRY_RUN_COMPLETED",
            actor=actor,
            detail={"ok": result.get("ok"), "external_ai_called": False},
            correlation_id=row.correlation_id,
        )
        self._session.commit()
        return {
            **result,
            "analysis": self._public(row),
            "disclaimer": REFERENCE_DISCLAIMER,
            "external_ai_called": False,
            "candle_count": row.candle_count,
            "data_quality_status": row.data_quality_status,
            "snapshot_hash": row.snapshot_hash,
        }

    async def execute(
        self,
        analysis_id: int,
        *,
        actor: str,
        confirm: bool = False,
    ) -> dict[str, Any]:
        row = self._session.get(AIMarketAnalysisEntity, analysis_id)
        if row is None:
            raise AIMarketAnalysisError("NOT_FOUND", "analysis not found")
        if row.execution_request_id is None:
            raise AIMarketAnalysisError("NO_EXECUTION", "missing execution")
        if row.data_quality_status == "INVALID":
            self._history(
                analysis_id,
                action="AI_MARKET_DATA_QUALITY_FAILED",
                actor=actor,
                previous=row.analysis_status,
                new="BLOCKED",
                correlation_id=row.correlation_id,
            )
            row.analysis_status = "BLOCKED"
            self._session.commit()
            raise AIMarketAnalysisError("DATA_QUALITY_INVALID", "quality INVALID")

        self._history(
            analysis_id,
            action="AI_MARKET_ANALYSIS_EXECUTION_REQUESTED",
            actor=actor,
            previous=row.analysis_status,
            new="RUNNING",
            detail={"confirm": confirm, "mode": row.execution_mode},
            correlation_id=row.correlation_id,
        )
        row.analysis_status = "RUNNING"
        self._session.commit()

        try:
            result = await AIExecutionRunner(self._session).execute(
                row.execution_request_id,
                actor=actor,
                confirm=confirm,
            )
        except AIExecutionError as exc:
            row.analysis_status = "FAILED"
            self._history(
                analysis_id,
                action="AI_MARKET_ANALYSIS_FAILED",
                actor=actor,
                previous="RUNNING",
                new="FAILED",
                reason=exc.message,
                correlation_id=row.correlation_id,
            )
            self._session.commit()
            raise AIMarketAnalysisError(exc.code, exc.message) from exc

        exec_req = self._exec.get_request(row.execution_request_id)
        exec_result = self._exec.get_result(row.execution_request_id)
        self._apply_outcome(
            row,
            actor=actor,
            exec_req=exec_req,
            exec_result=exec_result,
            runner_ok=bool(result.get("ok")),
        )
        self._session.commit()
        self._session.refresh(row)
        return {
            "ok": bool(result.get("ok")),
            "analysis": self._public(row),
            "execution": result,
            "disclaimer": REFERENCE_DISCLAIMER,
            "external_ai_called": bool(result.get("external_ai_called")),
            "mock_called": bool(result.get("mock_called")),
        }

    def _apply_outcome(
        self,
        row: AIMarketAnalysisEntity,
        *,
        actor: str,
        exec_req: dict[str, Any],
        exec_result: dict[str, Any] | None,
        runner_ok: bool,
    ) -> None:
        status = str(exec_req.get("status") or "")
        prev = row.analysis_status
        if status in {"SUCCEEDED", "SUCCEEDED_WITH_WARNINGS"} and exec_result:
            payload = exec_result.get("result_payload") or {}
            result_body = (
                payload.get("result") if isinstance(payload, dict) else {}
            ) or {}
            # Snapshot 메타로 numeric 검증 (stored hash만 — 원본 candle 미저장)
            snap_meta = {
                "symbol": row.symbol,
                "timeframe": row.timeframe,
                "candles": [],
            }
            numeric_warnings = validate_ai_numerics(
                snapshot=snap_meta, result_body=result_body
            )
            if numeric_warnings:
                self._history(
                    row.market_analysis_id,
                    action="AI_MARKET_NUMERIC_MISMATCH",
                    actor=actor,
                    detail={"warnings": numeric_warnings},
                    correlation_id=row.correlation_id,
                )

            for level in list(result_body.get("support_levels") or [])[:10]:
                self._session.add(
                    AIMarketAnalysisLevelEntity(
                        market_analysis_id=row.market_analysis_id,
                        level_type="SUPPORT",
                        price=str(level)[:40],
                        strength=None,
                        evidence="ai_reference_only",
                    )
                )
            for level in list(result_body.get("resistance_levels") or [])[:10]:
                self._session.add(
                    AIMarketAnalysisLevelEntity(
                        market_analysis_id=row.market_analysis_id,
                        level_type="RESISTANCE",
                        price=str(level)[:40],
                        strength=None,
                        evidence="ai_reference_only",
                    )
                )

            warnings = list(exec_result.get("warnings") or []) + numeric_warnings
            new_status = (
                "VALIDATED_WITH_WARNINGS"
                if status == "SUCCEEDED_WITH_WARNINGS" or warnings
                else "VALIDATED_ANALYSIS"
            )
            row.safe_result = sanitize_for_log(
                payload if isinstance(payload, dict) else {}
            )
            row.result_hash = exec_result.get("result_hash")
            row.confidence = exec_result.get("confidence")
            row.warnings = warnings
            row.trend_classification = (
                str(result_body.get("trend")) if result_body.get("trend") else None
            )
            row.volatility_level = (
                str(result_body.get("volatility"))
                if result_body.get("volatility")
                else None
            )
            row.market_regime = (
                str(result_body.get("market_regime"))
                if result_body.get("market_regime")
                else None
            )
            row.analysis_status = new_status
            row.analyzed_at = _now()
            self._history(
                row.market_analysis_id,
                action="AI_MARKET_ANALYSIS_VALIDATED"
                if new_status == "VALIDATED_ANALYSIS"
                else "AI_MARKET_ANALYSIS_WARNING",
                actor=actor,
                previous=prev,
                new=new_status,
                correlation_id=row.correlation_id,
            )
            self._history(
                row.market_analysis_id,
                action="AI_MARKET_ANALYSIS_COMPLETED",
                actor=actor,
                previous=prev,
                new=new_status,
                correlation_id=row.correlation_id,
            )
        elif status == "BLOCKED":
            row.analysis_status = "BLOCKED"
            self._history(
                row.market_analysis_id,
                action="AI_MARKET_ANALYSIS_BLOCKED",
                actor=actor,
                previous=prev,
                new="BLOCKED",
                correlation_id=row.correlation_id,
            )
        elif status == "CANCELLED":
            row.analysis_status = "CANCELLED"
            self._history(
                row.market_analysis_id,
                action="AI_MARKET_ANALYSIS_CANCELLED",
                actor=actor,
                previous=prev,
                new="CANCELLED",
                correlation_id=row.correlation_id,
            )
        else:
            row.analysis_status = "FAILED" if not runner_ok else "INVALID"
            self._history(
                row.market_analysis_id,
                action="AI_MARKET_ANALYSIS_FAILED",
                actor=actor,
                previous=prev,
                new=row.analysis_status,
                correlation_id=row.correlation_id,
            )

    def cancel(self, analysis_id: int, *, actor: str, reason: str) -> dict[str, Any]:
        row = self._session.get(AIMarketAnalysisEntity, analysis_id)
        if row is None:
            raise AIMarketAnalysisError("NOT_FOUND", "analysis not found")
        self._history(
            analysis_id,
            action="AI_MARKET_ANALYSIS_CANCEL_REQUESTED",
            actor=actor,
            previous=row.analysis_status,
            reason=reason,
            correlation_id=row.correlation_id,
        )
        if row.execution_request_id:
            try:
                self._exec.cancel(
                    row.execution_request_id, actor=actor, reason=reason
                )
            except AIExecutionError as exc:
                # recovery abandon 등으로 execution은 이미 terminal인데
                # analysis만 RUNNING 잔존하는 orphan 정리 허용
                if exc.code != "ALREADY_TERMINAL":
                    raise AIMarketAnalysisError(exc.code, exc.message) from exc
                self._terminalize_open_execution_runs(
                    int(row.execution_request_id),
                    actor=actor,
                    reason=reason or "execution_already_terminal",
                )
        row.analysis_status = "CANCELLED"
        self._history(
            analysis_id,
            action="AI_MARKET_ANALYSIS_CANCELLED",
            actor=actor,
            new="CANCELLED",
            reason=reason,
            correlation_id=row.correlation_id,
        )
        self._session.commit()
        return {"analysis": self._public(row)}

    def _terminalize_open_execution_runs(
        self,
        execution_request_id: int,
        *,
        actor: str,
        reason: str,
    ) -> int:
        """이미 terminal인 request에 남은 open run을 정리."""

        from stock_platform.ai.execution.constants import RunStatus
        from stock_platform.ai.execution.entities import AIExecutionRunEntity

        open_statuses = {
            RunStatus.CREATED.value,
            RunStatus.STARTED.value,
            RunStatus.RETRY_SCHEDULED.value,
            RunStatus.FALLBACK_SCHEDULED.value,
        }
        now = _now()
        runs = list(
            self._session.scalars(
                select(AIExecutionRunEntity).where(
                    AIExecutionRunEntity.execution_request_id
                    == execution_request_id,
                    AIExecutionRunEntity.status.in_(open_statuses),
                )
            )
        )
        for run in runs:
            run.status = RunStatus.CANCELLED.value
            run.completed_at = now
            if run.started_at is not None:
                run.latency_ms = int(
                    max(
                        0.0,
                        (now - run.started_at.astimezone(timezone.utc)).total_seconds()
                        * 1000.0,
                    )
                )
            run.error_code = "ORPHAN_RUN_CLOSED"
            run.sanitized_error = (reason or "orphan_run_closed")[:500]
            run.circuit_state = run.circuit_state or "UNKNOWN"
        return len(runs)

    def reanalyze(
        self,
        analysis_id: int,
        *,
        actor: str,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        old = self._session.get(AIMarketAnalysisEntity, analysis_id)
        if old is None:
            raise AIMarketAnalysisError("NOT_FOUND", "analysis not found")
        created = self.create(
            actor=actor,
            reason=reason,
            analysis_type=old.analysis_type,
            exchange_code=old.exchange_code,
            symbol=old.symbol,
            timeframe=old.timeframe or "1D",
            data_from=old.data_from,
            data_to=old.data_to,
            execution_mode=old.execution_mode,
            provider_code=old.provider_code,
            model=old.model,
            prompt_version_id=old.prompt_version_id,
            idempotency_key=idempotency_key,
            force_new_version=True,
            correlation_id=old.correlation_id,
        )
        new_id = created["analysis"]["id"]
        if new_id != old.market_analysis_id:
            prev = old.analysis_status
            old.analysis_status = "SUPERSEDED"
            old.superseded_at = _now()
            old.superseded_by_id = new_id
            self._history(
                old.market_analysis_id,
                action="AI_MARKET_ANALYSIS_SUPERSEDED",
                actor=actor,
                previous=prev,
                new="SUPERSEDED",
                reason=reason,
                detail={"superseded_by_id": new_id},
                correlation_id=old.correlation_id,
            )
            self._history(
                new_id,
                action="AI_MARKET_ANALYSIS_REANALYSIS_CREATED",
                actor=actor,
                reason=reason,
                detail={"previous_id": old.market_analysis_id},
                correlation_id=old.correlation_id,
            )
            self._session.commit()
        return created

    def get(self, analysis_id: int) -> dict[str, Any]:
        row = self._session.get(AIMarketAnalysisEntity, analysis_id)
        if row is None:
            raise AIMarketAnalysisError("NOT_FOUND", "analysis not found")
        return self._public(row)

    def history(self, analysis_id: int) -> list[dict[str, Any]]:
        rows = self._session.scalars(
            select(AIMarketAnalysisHistoryEntity)
            .where(
                AIMarketAnalysisHistoryEntity.market_analysis_id == analysis_id
            )
            .order_by(AIMarketAnalysisHistoryEntity.id.desc())
            .limit(100)
        ).all()
        return [
            {
                "id": r.id,
                "action": r.action,
                "previous_status": r.previous_status,
                "new_status": r.new_status,
                "reason": r.reason,
                "requested_by": r.requested_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    def list_analyses(
        self, *, analysis_type: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        stmt = select(AIMarketAnalysisEntity).order_by(
            AIMarketAnalysisEntity.market_analysis_id.desc()
        )
        if analysis_type:
            stmt = stmt.where(
                AIMarketAnalysisEntity.analysis_type == analysis_type
            )
        rows = self._session.scalars(stmt.limit(min(limit, 200))).all()
        return [self._public(r) for r in rows]

    def compare(self, left_id: int, right_id: int) -> dict[str, Any]:
        left = self.get(left_id)
        right = self.get(right_id)
        return {
            "left": left,
            "right": right,
            "diff": {
                "provider": [left.get("provider_code"), right.get("provider_code")],
                "model": [left.get("model"), right.get("model")],
                "snapshot_hash": [
                    left.get("snapshot_hash"),
                    right.get("snapshot_hash"),
                ],
                "trend": [
                    left.get("trend_classification"),
                    right.get("trend_classification"),
                ],
                "regime": [left.get("market_regime"), right.get("market_regime")],
                "confidence": [left.get("confidence"), right.get("confidence")],
                "result_equal": left.get("safe_result") == right.get("safe_result"),
            },
            "disclaimer": REFERENCE_DISCLAIMER,
        }

    def dashboard_summary(self) -> dict[str, Any]:
        rows = self._session.scalars(
            select(AIMarketAnalysisEntity).limit(500)
        ).all()
        today = _now().date()

        def _today(r: AIMarketAnalysisEntity) -> bool:
            return bool(r.analyzed_at and r.analyzed_at.date() == today) or bool(
                r.created_at and r.created_at.date() == today
            )

        by_status: dict[str, int] = {}
        for r in rows:
            by_status[r.analysis_status] = by_status.get(r.analysis_status, 0) + 1
        confs = [float(r.confidence) for r in rows if r.confidence is not None]
        return {
            "chart_analysis_today": sum(
                1
                for r in rows
                if r.analysis_type == "SYMBOL_CHART" and _today(r)
            ),
            "market_analysis_today": sum(
                1
                for r in rows
                if r.analysis_type == "MARKET_OVERVIEW" and _today(r)
            ),
            "running": by_status.get("RUNNING", 0),
            "queued": by_status.get("QUEUED", 0),
            "succeeded": by_status.get("VALIDATED_ANALYSIS", 0)
            + by_status.get("VALIDATED_WITH_WARNINGS", 0),
            "failed": by_status.get("FAILED", 0),
            "blocked": by_status.get("BLOCKED", 0),
            "data_quality_warning": sum(
                1
                for r in rows
                if r.data_quality_status
                in {"STALE", "INCOMPLETE", "GAP_DETECTED", "ACCEPTABLE"}
            ),
            "stale_snapshot_count": sum(
                1 for r in rows if r.data_quality_status == "STALE"
            ),
            "superseded": by_status.get("SUPERSEDED", 0),
            "average_confidence": (
                round(sum(confs) / len(confs), 4) if confs else None
            ),
            "mock_vs_external": {
                "mock": sum(1 for r in rows if r.execution_mode == "MOCK"),
                "external": sum(
                    1 for r in rows if r.execution_mode == "EXTERNAL"
                ),
            },
            "disclaimer": REFERENCE_DISCLAIMER,
            "auto_analysis_on_candle_sync": False,
            "external_ai_called": False,
        }


class AIMarketAnalysisBatchService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._svc = AIMarketAnalysisService(session)

    def create_batch(
        self,
        *,
        actor: str,
        reason: str,
        exchange_code: str,
        symbols: list[str],
        timeframe: str,
        execution_mode: str,
        provider_code: str,
        model: str | None,
        prompt_version_id: int | None,
        confirm: bool,
        idempotency_key: str,
        data_from: date | None = None,
        data_to: date | None = None,
        estimated_max_tokens: int | None = None,
        estimated_max_cost: float | None = None,
    ) -> dict[str, Any]:
        if not confirm:
            raise AIMarketAnalysisError(
                "CONFIRM_REQUIRED", "batch requires confirm=true"
            )
        if not symbols:
            raise AIMarketAnalysisError("EMPTY_SYMBOLS", "explicit symbols required")
        if data_from and data_to and (data_to - data_from).days > 800:
            raise AIMarketAnalysisError(
                "PERIOD_TOO_LONG", "period exceeds safe limit"
            )
        cap = (
            MAX_BATCH_EXTERNAL
            if execution_mode == "EXTERNAL"
            else MAX_BATCH_MOCK
        )
        cap = min(cap, HARD_BATCH_CAP)
        if len(symbols) > cap:
            raise AIMarketAnalysisError(
                "BATCH_LIMIT", f"max {cap} symbols for {execution_mode}"
            )

        created: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for idx, sym in enumerate(symbols):
            try:
                item = self._svc.create(
                    actor=actor,
                    reason=reason,
                    analysis_type="SYMBOL_CHART",
                    exchange_code=exchange_code,
                    symbol=sym,
                    timeframe=timeframe,
                    data_from=data_from,
                    data_to=data_to,
                    execution_mode=execution_mode,
                    provider_code=provider_code,
                    model=model,
                    prompt_version_id=prompt_version_id,
                    idempotency_key=f"{idempotency_key}:{idx}"[:64],
                )
                created.append(item["analysis"])
            except AIMarketAnalysisError as exc:
                errors.append(
                    {"symbol": sym, "code": exc.code, "message": exc.message}
                )

        if created:
            self._svc._history(
                created[0]["id"],
                action="AI_MARKET_ANALYSIS_BATCH_CREATED",
                actor=actor,
                reason=reason,
                detail={
                    "count": len(created),
                    "errors": len(errors),
                    "estimated_max_tokens": estimated_max_tokens,
                    "estimated_max_cost": estimated_max_cost,
                },
            )
            self._session.commit()

        return {
            "created_count": len(created),
            "error_count": len(errors),
            "items": created,
            "errors": errors,
            "cap": cap,
            "auto_execute": False,
            "disclaimer": REFERENCE_DISCLAIMER,
        }
