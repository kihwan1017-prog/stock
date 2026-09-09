"""Paper validation acceptance policy — STEP12-10 QualityGate FAIL 경계 재사용.

Paper 전용 수익 임계값은 만들지 않는다. Walk-Forward 안정성/과적합 Rule은
Paper run에 WF 입력이 없어 적용하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.ai.strategy_draft_approval.quality_gate import (
    QualityGateThresholds,
)
from stock_platform.performance.entities import (
    StrategyPerformanceMetricEntity,
    StrategyPerformanceRunEntity,
)
from stock_platform.performance.models import PerformanceRunStatus, PerformanceRunType
from stock_platform.strategy_deployment.definition_entities import (
    StrategyDefinitionEntity,
)


PAPER_VALIDATION_POLICY_VERSION = "1.0.0"
RESULT_PASS = "PAPER_PASS"
RESULT_FAIL = "PAPER_FAIL"
RESULT_INSUFFICIENT = "PAPER_INSUFFICIENT_EVIDENCE"

REASON_INSUFFICIENT_CLOSED_TRADES = "INSUFFICIENT_CLOSED_TRADES"
REASON_RUN_NOT_COMPLETED = "RUN_NOT_COMPLETED"
REASON_ORDER_FILL_MISMATCH = "ORDER_FILL_MISMATCH"
REASON_OVERSELL_DETECTED = "OVERSELL_DETECTED"
REASON_NEGATIVE_CASH = "NEGATIVE_CASH"
REASON_POSITION_RECONCILIATION_FAILED = "POSITION_RECONCILIATION_FAILED"
REASON_REAL_BROKER_INVOCATION_DETECTED = "REAL_BROKER_INVOCATION_DETECTED"
REASON_SHARPE_BELOW_THRESHOLD = "SHARPE_BELOW_THRESHOLD"
REASON_MDD_ABOVE_THRESHOLD = "MDD_ABOVE_THRESHOLD"
REASON_PROFIT_FACTOR_BELOW_THRESHOLD = "PROFIT_FACTOR_BELOW_THRESHOLD"
REASON_MISSING_METRIC = "MISSING_METRIC"
REASON_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
REASON_AMBIGUOUS_SUBMISSION = "AMBIGUOUS_SUBMISSION"
REASON_DUPLICATE_ORDER_IDS = "DUPLICATE_ORDER_IDS"
REASON_FEE_TAX_RECONCILIATION_FAILED = "FEE_TAX_RECONCILIATION_FAILED"
REASON_WRONG_RUN_TYPE = "WRONG_RUN_TYPE"
REASON_SOURCE_EVIDENCE_NOT_INHERITED = "SOURCE_EVIDENCE_NOT_INHERITED"

_QG = QualityGateThresholds()
ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class PaperValidationPolicy:
    """QualityGateThresholds의 FAIL 경계만 재사용. warn은 Paper PASS를 막지 않는다."""

    version: str = PAPER_VALIDATION_POLICY_VERSION
    min_closed_trades: int = _QG.min_trade_count_fail
    min_sharpe_ratio: Decimal = _QG.min_sharpe_ratio_fail
    max_drawdown_rate: Decimal = _QG.max_drawdown_rate_fail
    min_profit_factor: Decimal = _QG.min_profit_factor_fail
    # SoT 없음 — 보고만
    win_rate_rule: str = "REPORT_ONLY"
    return_rule: str = "REPORT_ONLY"


@dataclass(frozen=True, slots=True)
class PaperValidationResult:
    result: str
    reason_codes: list[str]
    policy_version: str
    layers: dict[str, str]
    details: dict[str, Any] = field(default_factory=dict)
    source_strategy_paper_validated: bool = False
    derived_strategy_paper_validated: bool = False
    evidence_inheritance_allowed: bool = False


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def evaluate_paper_snapshot(
    *,
    snapshot: dict[str, Any],
    policy: PaperValidationPolicy | None = None,
    evaluated_strategy_id: int | None = None,
) -> PaperValidationResult:
    """순수 평가. DB WRITE 없음."""

    policy = policy or PaperValidationPolicy()
    reasons: list[str] = []
    sufficiency = "PASS"
    integrity = "PASS"
    quality = "PASS"

    status = str(snapshot.get("status_code") or "").upper()
    run_type = str(snapshot.get("run_type") or "").upper()
    payload = dict(snapshot.get("result_payload") or {})
    metric = dict(snapshot.get("metric") or {})
    evidence_strategy_id = snapshot.get("strategy_id")
    required = [
        snapshot.get("run_id"),
        evidence_strategy_id,
        snapshot.get("symbol"),
        snapshot.get("period_start"),
        snapshot.get("period_end"),
        payload.get("bars"),
        payload.get("signals"),
        payload.get("fills"),
        payload.get("closed_trades"),
        metric.get("total_trade_count"),
    ]
    if any(item is None or item == "" for item in required):
        sufficiency = "FAIL"
        reasons.append(REASON_INSUFFICIENT_EVIDENCE)
    if run_type and run_type != PerformanceRunType.PAPER.value:
        sufficiency = "FAIL"
        reasons.append(REASON_WRONG_RUN_TYPE)
    if status and status != PerformanceRunStatus.COMPLETED.value:
        sufficiency = "FAIL"
        reasons.append(REASON_RUN_NOT_COMPLETED)
    if not metric:
        sufficiency = "FAIL"
        reasons.append(REASON_MISSING_METRIC)

    trades = int(metric.get("total_trade_count") or payload.get("closed_trade_count") or 0)
    if trades < int(policy.min_closed_trades):
        if status == PerformanceRunStatus.COMPLETED.value and metric:
            sufficiency = "FAIL"
            reasons.append(REASON_INSUFFICIENT_CLOSED_TRADES)
        elif REASON_INSUFFICIENT_EVIDENCE not in reasons:
            sufficiency = "FAIL"
            reasons.append(REASON_INSUFFICIENT_CLOSED_TRADES)

    buy_orders = int(payload.get("buy_orders") or 0)
    sell_orders = int(payload.get("sell_orders") or 0)
    fills = int(payload.get("fills") or 0)
    order_ids = list(payload.get("order_ids") or [])
    run_completed = status == PerformanceRunStatus.COMPLETED.value

    # REAL broker는 완료 여부와 무관하게 FAIL
    kiwoom_calls = int(payload.get("kiwoom_adapter_calls") or 0)
    upbit_calls = int(payload.get("upbit_adapter_calls") or 0)
    if kiwoom_calls > 0 or upbit_calls > 0:
        integrity = "FAIL"
        reasons.append(REASON_REAL_BROKER_INVOCATION_DETECTED)

    if run_completed:
        if fills != buy_orders + sell_orders or fills != len(order_ids):
            integrity = "FAIL"
            reasons.append(REASON_ORDER_FILL_MISMATCH)
        if order_ids and len(order_ids) != len(set(int(x) for x in order_ids)):
            integrity = "FAIL"
            reasons.append(REASON_DUPLICATE_ORDER_IDS)

        open_pos = dict(payload.get("open_position") or {})
        open_qty = _dec(open_pos.get("quantity")) or ZERO
        if open_qty < ZERO:
            integrity = "FAIL"
            reasons.append(REASON_OVERSELL_DETECTED)

        cash = _dec(payload.get("final_cash"))
        if cash is None:
            sufficiency = "FAIL"
            reasons.append(REASON_INSUFFICIENT_EVIDENCE)
        elif cash < ZERO:
            integrity = "FAIL"
            reasons.append(REASON_NEGATIVE_CASH)

        closed = list(payload.get("closed_trades") or [])
        wins = int(metric.get("winning_trade_count") or 0)
        losses = int(metric.get("losing_trade_count") or 0)
        if metric and (wins + losses != trades or len(closed) != trades):
            integrity = "FAIL"
            reasons.append(REASON_POSITION_RECONCILIATION_FAILED)

        blocked = list(payload.get("blocked") or [])
        if any(
            str(item.get("reason") or "").upper() in {
                "AMBIGUOUS_SUBMISSION",
                "IDENTITY_CONFLICT",
            }
            for item in blocked
            if isinstance(item, dict)
        ):
            integrity = "FAIL"
            reasons.append(REASON_AMBIGUOUS_SUBMISSION)

        if payload.get("integrity_ok") is False:
            integrity = "FAIL"
            reasons.append(REASON_POSITION_RECONCILIATION_FAILED)

        fee = _dec(payload.get("fee_total")) or ZERO
        tax = _dec(payload.get("tax_total")) or ZERO
        realized = _dec(payload.get("realized_pnl"))
        net = _dec(metric.get("net_profit_amount"))
        if realized is not None and net is not None:
            expected = (realized - fee - tax).quantize(Decimal("0.01"))
            if expected != net.quantize(Decimal("0.01")):
                integrity = "FAIL"
                reasons.append(REASON_FEE_TAX_RECONCILIATION_FAILED)

    sharpe = _dec(metric.get("sharpe_ratio"))
    mdd = _dec(metric.get("maximum_drawdown_rate"))
    pf = _dec(metric.get("profit_factor"))
    if run_completed and metric:
        if sharpe is None or mdd is None or pf is None:
            sufficiency = "FAIL"
            reasons.append(REASON_MISSING_METRIC)
        else:
            if sharpe < policy.min_sharpe_ratio:
                quality = "FAIL"
                reasons.append(REASON_SHARPE_BELOW_THRESHOLD)
            if mdd > policy.max_drawdown_rate:
                quality = "FAIL"
                reasons.append(REASON_MDD_ABOVE_THRESHOLD)
            if pf < policy.min_profit_factor:
                quality = "FAIL"
                reasons.append(REASON_PROFIT_FACTOR_BELOW_THRESHOLD)

    # 파생 전략은 원본 run을 자기 PASS로 쓰지 않는다
    inherit_blocked = False
    if (
        evaluated_strategy_id is not None
        and evidence_strategy_id is not None
        and int(evaluated_strategy_id) != int(evidence_strategy_id)
    ):
        inherit_blocked = True
        reasons.append(REASON_SOURCE_EVIDENCE_NOT_INHERITED)

    unique_reasons: list[str] = []
    for code in reasons:
        if code not in unique_reasons:
            unique_reasons.append(code)

    insufficient_markers = {
        REASON_INSUFFICIENT_EVIDENCE,
        REASON_MISSING_METRIC,
        REASON_RUN_NOT_COMPLETED,
        REASON_WRONG_RUN_TYPE,
        REASON_SOURCE_EVIDENCE_NOT_INHERITED,
    }
    if inherit_blocked or REASON_RUN_NOT_COMPLETED in unique_reasons:
        overall = RESULT_INSUFFICIENT
    elif REASON_REAL_BROKER_INVOCATION_DETECTED in unique_reasons:
        overall = RESULT_FAIL
    elif any(code in unique_reasons for code in insufficient_markers) and integrity != "FAIL" and quality != "FAIL":
        overall = RESULT_INSUFFICIENT
    elif integrity == "FAIL" or quality == "FAIL" or REASON_INSUFFICIENT_CLOSED_TRADES in unique_reasons:
        overall = RESULT_FAIL
    elif sufficiency == "FAIL":
        overall = RESULT_INSUFFICIENT
    else:
        overall = RESULT_PASS

    source_validated = (
        overall == RESULT_PASS
        and not inherit_blocked
        and (
            evaluated_strategy_id is None
            or int(evaluated_strategy_id) == int(evidence_strategy_id or 0)
        )
    )
    return PaperValidationResult(
        result=overall,
        reason_codes=unique_reasons,
        policy_version=policy.version,
        layers={
            "evidence_sufficiency": sufficiency,
            "execution_integrity": integrity,
            "performance_quality": quality,
        },
        details={
            "trades": trades,
            "fills": fills,
            "win_rate": str(metric.get("win_rate")) if metric.get("win_rate") is not None else None,
            "total_return_rate": str(metric.get("total_return_rate")) if metric.get("total_return_rate") is not None else None,
            "maximum_drawdown_rate": str(mdd) if mdd is not None else None,
            "sharpe_ratio": str(sharpe) if sharpe is not None else None,
            "profit_factor": str(pf) if pf is not None else None,
            "win_rate_rule": policy.win_rate_rule,
            "return_rule": policy.return_rule,
            "thresholds": {
                "min_closed_trades": policy.min_closed_trades,
                "min_sharpe_ratio": str(policy.min_sharpe_ratio),
                "max_drawdown_rate": str(policy.max_drawdown_rate),
                "min_profit_factor": str(policy.min_profit_factor),
            },
        },
        source_strategy_paper_validated=source_validated,
        derived_strategy_paper_validated=False,
        evidence_inheritance_allowed=False,
    )


def paper_validation_result_as_dict(result: PaperValidationResult) -> dict[str, Any]:
    return {
        "result": result.result,
        "reason_codes": list(result.reason_codes),
        "policy_version": result.policy_version,
        "layers": dict(result.layers),
        "details": dict(result.details),
        "source_strategy_paper_validated": result.source_strategy_paper_validated,
        "derived_strategy_paper_validated": result.derived_strategy_paper_validated,
        "evidence_inheritance_allowed": result.evidence_inheritance_allowed,
    }


class PaperValidationPolicyService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._policy = PaperValidationPolicy()

    def evaluate_run(
        self,
        *,
        run_id: int,
        evaluated_strategy_id: int | None = None,
    ) -> PaperValidationResult:
        run = self._session.get(StrategyPerformanceRunEntity, int(run_id))
        if run is None:
            return evaluate_paper_snapshot(
                snapshot={"status_code": "", "run_type": "PAPER", "result_payload": {}, "metric": {}},
                policy=self._policy,
                evaluated_strategy_id=evaluated_strategy_id,
            )
        metric = self._session.scalar(
            select(StrategyPerformanceMetricEntity).where(
                StrategyPerformanceMetricEntity.strategy_performance_run_id
                == int(run_id)
            )
        )
        snapshot = {
            "run_id": int(run.strategy_performance_run_id),
            "strategy_id": run.strategy_id,
            "run_type": run.run_type,
            "status_code": run.status_code,
            "symbol": run.symbol,
            "period_start": str(run.period_start_date),
            "period_end": str(run.period_end_date),
            "result_payload": dict(run.result_payload or {}),
            "metric": {
                "total_trade_count": metric.total_trade_count if metric else None,
                "winning_trade_count": metric.winning_trade_count if metric else None,
                "losing_trade_count": metric.losing_trade_count if metric else None,
                "sharpe_ratio": metric.sharpe_ratio if metric else None,
                "maximum_drawdown_rate": metric.maximum_drawdown_rate if metric else None,
                "profit_factor": metric.profit_factor if metric else None,
                "win_rate": metric.win_rate if metric else None,
                "total_return_rate": metric.total_return_rate if metric else None,
                "net_profit_amount": metric.net_profit_amount if metric else None,
            }
            if metric is not None
            else {},
        }
        return evaluate_paper_snapshot(
            snapshot=snapshot,
            policy=self._policy,
            evaluated_strategy_id=evaluated_strategy_id
            if evaluated_strategy_id is not None
            else (int(run.strategy_id) if run.strategy_id else None),
        )

    def evaluate_strategy_isolation(
        self,
        *,
        strategy_id: int,
        run_id: int,
    ) -> PaperValidationResult:
        """파생 전략에 원본 run을 적용하면 상속 금지 결과를 반환한다."""

        definition = self._session.get(StrategyDefinitionEntity, int(strategy_id))
        source_id = (
            int(definition.source_strategy_id)
            if definition is not None and definition.source_strategy_id
            else None
        )
        result = self.evaluate_run(
            run_id=run_id,
            evaluated_strategy_id=int(strategy_id),
        )
        source_eval = self.evaluate_run(
            run_id=run_id,
            evaluated_strategy_id=source_id,
        )
        if source_id is not None and int(strategy_id) != source_id:
            return PaperValidationResult(
                result=RESULT_INSUFFICIENT,
                reason_codes=[REASON_SOURCE_EVIDENCE_NOT_INHERITED],
                policy_version=self._policy.version,
                layers=result.layers,
                details={
                    **result.details,
                    "derived_strategy_id": int(strategy_id),
                    "source_strategy_id": source_id,
                    "source_run_id": int(run_id),
                    "derived_revalidation_required": True,
                },
                source_strategy_paper_validated=source_eval.result == RESULT_PASS,
                derived_strategy_paper_validated=False,
                evidence_inheritance_allowed=False,
            )
        return result
