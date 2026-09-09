"""USER PRIVATE LIVE Runtime 자격 — catalog approved_at 과 분리.

PUBLIC USER: catalog/publication 승인(approved_at)이 필요하다.
SYSTEM: owner_type 만으로 허용.
USER PRIVATE: 다음 중 하나.
  1) 레거시 catalog stamp (approved_at) — 17483 build 경로 호환
  2) 이 전략 자신의 Backtest SUCCESS + PaperValidationPolicy PAPER_PASS

LiveTrading Activation / UBA live_approved_at / ARM 과는 다른 층이다.
approved_at 를 직접 UPDATE 하지 않는다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.strategy_draft_approval.quality_gate import (
    QualityGateThresholds,
)
from stock_platform.backtest.persistence_models import BacktestRunEntity
from stock_platform.performance.entities import StrategyPerformanceRunEntity
from stock_platform.performance.models import PerformanceRunType
from stock_platform.strategy_deployment.definition_entities import (
    StrategyDefinitionEntity,
)
from stock_platform.trading.paper_validation_policy import (
    RESULT_PASS,
    PaperValidationPolicyService,
)


CODE_INACTIVE = "STRATEGY_INACTIVE"
CODE_NOT_APPROVED = "STRATEGY_NOT_APPROVED"
CODE_EVIDENCE_NOT_READY = "STRATEGY_EVIDENCE_NOT_READY"

MODE_SYSTEM = "SYSTEM"
MODE_PUBLIC_CATALOG = "PUBLIC_CATALOG"
MODE_PRIVATE_CATALOG_STAMP = "PRIVATE_CATALOG_STAMP"
MODE_PRIVATE_EVIDENCE = "PRIVATE_EVIDENCE"

_QG = QualityGateThresholds()


def evaluate_strategy_runtime_authorization(
    session: Session,
    *,
    strategy_id: int,
) -> dict[str, Any]:
    """Runtime START 전 전략 자격. 주문/Activation/LIVE 플래그는 다루지 않는다."""

    definition = session.get(StrategyDefinitionEntity, int(strategy_id))
    if definition is None or getattr(definition, "deleted_at", None) is not None:
        return {
            "ok": False,
            "code": CODE_INACTIVE,
            "approved": False,
            "mode": None,
        }
    if not bool(getattr(definition, "is_active", False)):
        return {
            "ok": False,
            "code": CODE_INACTIVE,
            "approved": False,
            "mode": None,
            "is_active": False,
        }

    owner = str(getattr(definition, "owner_type", "") or "").upper()
    visibility = str(getattr(definition, "visibility", "") or "").upper()
    has_stamp = getattr(definition, "approved_at", None) is not None

    if owner == "SYSTEM":
        return {
            "ok": True,
            "code": None,
            "approved": True,
            "mode": MODE_SYSTEM,
            "is_active": True,
        }

    if visibility == "PUBLIC":
        if not has_stamp:
            return {
                "ok": False,
                "code": CODE_NOT_APPROVED,
                "approved": False,
                "mode": MODE_PUBLIC_CATALOG,
                "is_active": True,
                "reason": "PUBLIC_USER_requires_catalog_approved_at",
            }
        return {
            "ok": True,
            "code": None,
            "approved": True,
            "mode": MODE_PUBLIC_CATALOG,
            "is_active": True,
        }

    # USER PRIVATE
    if has_stamp:
        return {
            "ok": True,
            "code": None,
            "approved": True,
            "mode": MODE_PRIVATE_CATALOG_STAMP,
            "is_active": True,
            "approved_at": definition.approved_at.isoformat()
            if definition.approved_at
            else None,
        }

    evidence = collect_private_live_evidence(
        session, definition=definition
    )
    if not evidence["ok"]:
        return {
            "ok": False,
            "code": CODE_EVIDENCE_NOT_READY,
            "approved": False,
            "mode": MODE_PRIVATE_EVIDENCE,
            "is_active": True,
            **evidence,
        }
    return {
        "ok": True,
        "code": None,
        "approved": True,
        "mode": MODE_PRIVATE_EVIDENCE,
        "is_active": True,
        **evidence,
    }


def collect_private_live_evidence(
    session: Session,
    *,
    definition: StrategyDefinitionEntity,
) -> dict[str, Any]:
    """이 전략 ID 의 Backtest/Paper 만 인정. 원본 전략 증거 상속 금지."""

    strategy_id = int(definition.strategy_id)
    compile_ok, compile_detail = _compile_ready(session, strategy_id)
    backtest = _own_successful_backtest(session, strategy_id)
    paper = _own_paper_pass(session, strategy_id)
    blockers: list[str] = []
    if not compile_ok:
        blockers.append("COMPILE_NOT_READY")
    if backtest is None:
        blockers.append("OWN_BACKTEST_SUCCESS_REQUIRED")
    if paper is None:
        blockers.append("OWN_PAPER_PASS_REQUIRED")
    return {
        "ok": not blockers,
        "blockers": blockers,
        "compile": compile_detail,
        "backtest_run_id": None if backtest is None else int(backtest.backtest_run_id),
        "backtest_symbol": None if backtest is None else str(backtest.symbol),
        "paper_run_id": None if paper is None else int(paper["run_id"]),
        "paper_result": None if paper is None else paper["result"],
        "paper_integrity": None if paper is None else paper.get("integrity"),
        "source_strategy_id": getattr(definition, "source_strategy_id", None),
        "evidence_inheritance_allowed": False,
    }


def _compile_ready(session: Session, strategy_id: int) -> tuple[bool, dict[str, Any]]:
    try:
        from stock_platform.ai.strategy_draft_approval.backtest_spec import (
            compile_specification,
        )

        spec = compile_specification(session, strategy_id)
    except Exception as exc:  # noqa: BLE001
        return False, {"ok": False, "error": exc.__class__.__name__}
    compilable = bool(spec.get("compilable"))
    return compilable, {
        "ok": compilable,
        "compilable": compilable,
        "ready": bool(spec.get("ready")),
        "timeframe": spec.get("timeframe"),
        "errors": list(spec.get("errors") or [])[:8],
    }


def _own_successful_backtest(
    session: Session, strategy_id: int
) -> BacktestRunEntity | None:
    stmt = (
        select(BacktestRunEntity)
        .where(
            BacktestRunEntity.strategy_definition_id == int(strategy_id),
            BacktestRunEntity.status_code == "SUCCESS",
        )
        .order_by(
            BacktestRunEntity.created_at.desc(),
            BacktestRunEntity.backtest_run_id.desc(),
        )
    )
    for run in session.scalars(stmt):
        if int(run.trade_count or 0) < int(_QG.min_trade_count_fail):
            continue
        mdd = Decimal(str(run.maximum_drawdown_rate or 0))
        if mdd > Decimal(str(_QG.max_drawdown_rate_fail)):
            continue
        return run
    return None


def _own_paper_pass(session: Session, strategy_id: int) -> dict[str, Any] | None:
    stmt = (
        select(StrategyPerformanceRunEntity)
        .where(
            StrategyPerformanceRunEntity.strategy_id == int(strategy_id),
            StrategyPerformanceRunEntity.run_type == PerformanceRunType.PAPER.value,
        )
        .order_by(
            StrategyPerformanceRunEntity.strategy_performance_run_id.desc()
        )
    )
    service = PaperValidationPolicyService(session)
    for run in session.scalars(stmt):
        if int(run.strategy_id or 0) != int(strategy_id):
            continue
        evaluated = service.evaluate_run(
            run_id=int(run.strategy_performance_run_id),
            evaluated_strategy_id=int(strategy_id),
        )
        layers = dict(evaluated.layers or {})
        if evaluated.result != RESULT_PASS:
            continue
        if str(layers.get("execution_integrity") or "").upper() != "PASS":
            continue
        return {
            "run_id": int(run.strategy_performance_run_id),
            "result": evaluated.result,
            "integrity": layers.get("execution_integrity"),
            "symbol": run.symbol,
        }
    return None
