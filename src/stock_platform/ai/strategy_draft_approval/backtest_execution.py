"""STEP 12-7 — 승인 Strategy Definition 기반 Backtest 실행(과거 데이터만).

흐름(§13): Readiness/Provenance -> Compile -> Runtime Input Validation ->
RuleBasedBacktestAdapter -> 기존 BacktestEngine 실행 -> 기존
BacktestRepository로 저장(§14, 새 테이블 없음). 기존
`BacktestService.run_moving_average_backtest()` 경로는 전혀 건드리지
않는다 — 이 모듈은 그 옆에 승인 Definition 전용 실행 경로를 추가할 뿐이다.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.ai.strategy_draft_approval.backtest_spec import (
    BacktestSpecificationError,
    RuleBasedBacktestAdapter,
    apply_parameter_overrides,
    compile_specification,
)
from stock_platform.backtest.engine import BacktestEngine, BacktestValidationError
from stock_platform.backtest.models import BacktestPrice
from stock_platform.backtest.persistence_models import BacktestRunEntity
from stock_platform.backtest.repository import BacktestRepository
from stock_platform.markets.repository import PriceDailyRepository
from stock_platform.markets.service import InstrumentNotFoundError, PriceDailyService

# 개별 Indicator 계산에 필요한 최소 bar 수(요구 period)를 이 값 이상으로
# 확보해야 최소 1개 이상의 유효한 Indicator 값이 나온다.
_MIN_EXTRA_BARS = 1

# STEP12-15 인수 조건(§ STEP12-14 필수 인수 보완 1) — "대표 Backtest 자동
# 선택"이 Walk-Forward/Parameter Sensitivity가 내부적으로 생성하는 하위
# 실행까지 주워가지 않도록, 호출 목적을 `parameters.execution_purpose`에
# 저장한다(기존 backtest_run 테이블에 새 컬럼을 추가하지 않고, 이미 있는
# JSONB `parameters`를 재사용 — 스키마 변경 없음). 사용자가 직접 실행한
# Backtest(관리자 API의 기본값)만 PRIMARY다.
EXECUTION_PURPOSE_PRIMARY = "PRIMARY"
EXECUTION_PURPOSE_WALK_FORWARD_WINDOW = "WALK_FORWARD_WINDOW"
EXECUTION_PURPOSE_PARAMETER_SENSITIVITY_BASE = "PARAMETER_SENSITIVITY_BASE"
EXECUTION_PURPOSE_PARAMETER_SENSITIVITY_VARIATION = "PARAMETER_SENSITIVITY_VARIATION"
# "대표 Backtest"로 취급하지 않는(=latest 자동 선택에서 제외하는) 목적들.
NON_PRIMARY_EXECUTION_PURPOSES = frozenset(
    {
        EXECUTION_PURPOSE_WALK_FORWARD_WINDOW,
        EXECUTION_PURPOSE_PARAMETER_SENSITIVITY_BASE,
        EXECUTION_PURPOSE_PARAMETER_SENSITIVITY_VARIATION,
    }
)


class BacktestExecutionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _canonical_runtime_input(runtime_input: dict[str, Any]) -> str:
    normalized = {
        "symbol": runtime_input["symbol"],
        "exchange_code": runtime_input["exchange_code"],
        "start_date": runtime_input["start_date"].isoformat(),
        "end_date": runtime_input["end_date"].isoformat(),
        "initial_capital": str(runtime_input["initial_capital"]),
        "fee_ratio": str(runtime_input["fee_ratio"]),
        "sell_tax_ratio": str(runtime_input["sell_tax_ratio"]),
        "slippage_ratio": str(runtime_input["slippage_ratio"]),
    }
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_runtime_input_hash(runtime_input: dict[str, Any]) -> str:
    return hashlib.sha256(
        _canonical_runtime_input(runtime_input).encode("utf-8")
    ).hexdigest()


def validate_runtime_input(runtime_input: dict[str, Any]) -> None:
    """§15 — 최소 검증. 실패 시 BacktestExecutionError(fail closed)."""

    symbol = str(runtime_input.get("symbol") or "").strip()
    if not symbol:
        raise BacktestExecutionError("RUNTIME_INPUT_REQUIRED", "symbol은 공백일 수 없습니다.")
    exchange_code = str(runtime_input.get("exchange_code") or "").strip()
    if not exchange_code:
        raise BacktestExecutionError(
            "RUNTIME_INPUT_REQUIRED", "exchange_code는 공백일 수 없습니다."
        )
    start_date = runtime_input.get("start_date")
    end_date = runtime_input.get("end_date")
    if not isinstance(start_date, date) or not isinstance(end_date, date):
        raise BacktestExecutionError(
            "RUNTIME_INPUT_REQUIRED", "start_date/end_date가 필요합니다."
        )
    if start_date >= end_date:
        raise BacktestExecutionError(
            "RUNTIME_INPUT_REQUIRED", "start_date는 end_date보다 이전이어야 합니다."
        )
    initial_capital = runtime_input.get("initial_capital")
    if not isinstance(initial_capital, Decimal) or initial_capital <= 0:
        raise BacktestExecutionError(
            "RUNTIME_INPUT_REQUIRED", "initial_capital은 0보다 커야 합니다."
        )
    # 기존 BacktestEngine._validate()와 동일한 허용 범위(0~0.20)를 그대로
    # 재사용한다(새 상한을 임의로 만들지 않음).
    for name in ("fee_ratio", "sell_tax_ratio", "slippage_ratio"):
        value = runtime_input.get(name)
        if not isinstance(value, Decimal) or value < 0 or value > Decimal("0.20"):
            raise BacktestExecutionError(
                "RUNTIME_INPUT_REQUIRED", f"{name}은 0~0.20 사이여야 합니다."
            )


def _required_min_bars(specification: dict[str, Any]) -> int:
    periods = [
        int(req["period"]) for req in specification.get("indicator_requirements", [])
        if req.get("period") is not None
    ]
    return (max(periods) if periods else 0) + _MIN_EXTRA_BARS


def run_definition_backtest(
    session: Session,
    strategy_definition_id: int,
    *,
    runtime_input: dict[str, Any],
    actor: str,
    idempotency_key: str | None = None,
    parameter_overrides: list[tuple[tuple[Any, ...], Any]] | None = None,
    execution_purpose: str = EXECUTION_PURPOSE_PRIMARY,
) -> dict[str, Any]:
    """승인 Definition을 실제 과거 데이터에 대해 Backtest 실행하고 저장한다.

    Broker/Order/Runtime/Scheduler WRITE 없음 — `backtest.backtest_run`
    (+trade/equity)에만 기록한다(§14, 기존 테이블 재사용).

    `parameter_overrides`(STEP12-11)가 주어지면 원본 Definition은 전혀
    수정하지 않고 실행 시점에만 일회성으로 Rule 값을 override한
    Specification(§ apply_parameter_overrides, 새 executable_hash)으로
    실행한다 — 저장되는 `parameters.executable_hash`도 이 override 반영
    값이라 원본 Definition의 실제 executable_hash를 사칭하지 않는다."""

    key = (idempotency_key or "").strip() or uuid.uuid4().hex
    repo = BacktestRepository(session)
    existing = repo.find_by_idempotency_key(key)
    if existing is not None:
        return _to_dict(existing, idempotent_replay=True)

    try:
        specification = compile_specification(session, strategy_definition_id)
    except BacktestSpecificationError as exc:
        raise BacktestExecutionError(exc.code, exc.message) from exc
    if not specification["compilable"]:
        raise BacktestExecutionError(
            "DEFINITION_NOT_READY" if not specification["ready"] else "PROVENANCE_INVALID",
            "; ".join(specification["failure_reasons"]) or "컴파일 실패",
        )

    base_executable_hash = specification["executable_hash"]
    if parameter_overrides:
        try:
            specification = apply_parameter_overrides(specification, parameter_overrides)
        except BacktestSpecificationError as exc:
            raise BacktestExecutionError(exc.code, exc.message) from exc

    validate_runtime_input(runtime_input)
    runtime_input_hash = compute_runtime_input_hash(runtime_input)

    price_service = PriceDailyService(PriceDailyRepository(session))
    try:
        rows = price_service.get_between(
            exchange_code=runtime_input["exchange_code"].upper(),
            symbol=runtime_input["symbol"].upper(),
            start_date=runtime_input["start_date"],
            end_date=runtime_input["end_date"],
        )
    except InstrumentNotFoundError as exc:
        raise BacktestExecutionError("RUNTIME_INPUT_REQUIRED", str(exc)) from exc
    prices = [
        BacktestPrice(
            trade_date=row.trade_date,
            open_price=Decimal(row.open_price),
            high_price=Decimal(row.high_price),
            low_price=Decimal(row.low_price),
            close_price=Decimal(row.close_price),
            volume=Decimal(row.volume),
        )
        for row in rows
    ]
    if not prices:
        raise BacktestExecutionError(
            "RUNTIME_INPUT_REQUIRED",
            "지정한 기간/종목에 대한 과거 가격 데이터가 없습니다.",
        )
    min_bars = _required_min_bars(specification)
    if len(prices) < min_bars:
        raise BacktestExecutionError(
            "RUNTIME_INPUT_REQUIRED",
            f"Indicator 계산에 필요한 최소 {min_bars}개 bar보다 데이터가 부족합니다"
            f"(실제 {len(prices)}개).",
        )

    try:
        adapter = RuleBasedBacktestAdapter(specification, prices)
    except BacktestSpecificationError as exc:
        raise BacktestExecutionError(exc.code, exc.message) from exc

    try:
        result = BacktestEngine(adapter).run(
            exchange_code=runtime_input["exchange_code"],
            symbol=runtime_input["symbol"],
            prices=prices,
            initial_capital=runtime_input["initial_capital"],
            fee_ratio=runtime_input["fee_ratio"],
            sell_tax_ratio=runtime_input["sell_tax_ratio"],
            slippage_ratio=runtime_input["slippage_ratio"],
        )
    except BacktestValidationError as exc:
        raise BacktestExecutionError("RUNTIME_INPUT_REQUIRED", str(exc)) from exc

    parameters = {
        "strategy_definition_id": specification["strategy_definition_id"],
        "definition_version": specification["definition_version"],
        "definition_hash": specification["definition_hash"],
        "executable_hash": specification["executable_hash"],
        "compiler_version": specification["compiler_version"],
        "runtime_input_hash": runtime_input_hash,
        "runtime_input": _canonical_runtime_input(runtime_input),
        "requested_by": actor,
        "parameter_override_applied": bool(parameter_overrides),
        "base_executable_hash": base_executable_hash,
        "execution_purpose": execution_purpose,
    }
    run = repo.save_result(
        result=result,
        strategy_code=f"DEFINITION_{specification['strategy_definition_id']}",
        parameters=parameters,
        strategy_definition_id=specification["strategy_definition_id"],
        idempotency_key=key,
    )
    return _to_dict(run, idempotent_replay=False)


def _to_dict(run: BacktestRunEntity, *, idempotent_replay: bool) -> dict[str, Any]:
    return {
        "backtest_run_id": int(run.backtest_run_id),
        "strategy_definition_id": run.strategy_definition_id,
        "status": run.status_code,
        "summary": {
            "initial_capital": run.initial_capital,
            "final_equity": run.final_equity,
            "total_profit_loss": run.total_profit_loss,
            "total_return_rate": run.total_return_rate,
            "maximum_drawdown_rate": run.maximum_drawdown_rate,
            "trade_count": run.trade_count,
            "win_count": run.win_count,
            "loss_count": run.loss_count,
            "win_rate": run.win_rate,
            "average_trade_return_rate": run.average_trade_return_rate,
        },
        "parameters": run.parameters,
        "idempotent_replay": idempotent_replay,
    }


def _legacy_non_primary_backtest_run_ids(session: Session, strategy_definition_id: int) -> set[int]:
    """§ STEP12-16 인수 조건(STEP12-15 필수 인수 보완 6) — `execution_purpose`
    도입(STEP12-15) 이전에 생성된 Walk-Forward Window/Parameter Sensitivity
    Base·Variation Run은 마커가 없다. 이런 Legacy Run까지 제외하려면
    Walk-Forward/Sensitivity 자신의 기존 저장소에서 "그 Run을 실제로
    누가 참조하는지"를 역으로 조회해야 한다(새 마커 컬럼 추가가 아니라
    기존 저장 구조 재사용) — 참조되지 않는 나머지 과거 Standalone Run은
    전부 대표 후보로 남겨둔다(전부 제외하지 않음)."""
    from sqlalchemy import select

    from stock_platform.ai.strategy_draft_approval.parameter_sensitivity_entities import (
        ParameterSensitivityReportEntity,
    )
    from stock_platform.performance.entities import StrategyPerformanceRunEntity
    from stock_platform.performance.walk_forward_entities import WalkForwardWindowMetricEntity

    excluded: set[int] = set()

    window_rows = session.execute(
        select(WalkForwardWindowMetricEntity.parameter_payload)
        .join(
            StrategyPerformanceRunEntity,
            StrategyPerformanceRunEntity.strategy_performance_run_id
            == WalkForwardWindowMetricEntity.strategy_performance_run_id,
        )
        .where(StrategyPerformanceRunEntity.strategy_id == strategy_definition_id)
    ).scalars()
    for payload in window_rows:
        payload = payload or {}
        for key in ("train_backtest_run_id", "test_backtest_run_id"):
            run_id = payload.get(key)
            if run_id is not None:
                excluded.add(int(run_id))

    sensitivity_reports = session.execute(
        select(ParameterSensitivityReportEntity).where(
            ParameterSensitivityReportEntity.strategy_id == strategy_definition_id
        )
    ).scalars()
    for report in sensitivity_reports:
        if report.base_backtest_run_id is not None:
            excluded.add(int(report.base_backtest_run_id))
        for variation in report.variation_results or []:
            run_id = variation.get("backtest_run_id")
            if run_id is not None:
                excluded.add(int(run_id))

    return excluded


def get_latest_primary_backtest_run_id(session: Session, strategy_definition_id: int) -> int | None:
    """§ STEP12-15/16 인수 조건 — "대표 Backtest 자동 선택" 공용 Helper.
    Walk-Forward Window/Parameter Sensitivity Base·Variation처럼 다른
    분석의 부산물로 생성된 Run은 대표 Backtest가 아니므로 제외한다.
    `execution_purpose` 마커(STEP12-15 이후 생성분)로 우선 판정하고,
    마커가 없는 legacy Run은 Walk-Forward/Sensitivity 저장소를 역참조해
    Window/Variation 여부를 판정한다(§ `_legacy_non_primary_backtest_run_ids`)
    — 마커도 없고 역참조도 안 되는 legacy Standalone Run은 전부
    대표 후보로 남긴다. Quality Gate/Explainability 등 모든 "최신 대표
    Backtest" 선택 경로가 이 함수 하나만 재사용한다(중복 구현 금지).
    completed_at이 없는 테이블이라 `created_at DESC, backtest_run_id DESC`
    로 결정적 정렬한다."""
    from sqlalchemy import select

    stmt = (
        select(BacktestRunEntity)
        .where(
            BacktestRunEntity.strategy_definition_id == strategy_definition_id,
            BacktestRunEntity.status_code == "SUCCESS",
        )
        .order_by(BacktestRunEntity.created_at.desc(), BacktestRunEntity.backtest_run_id.desc())
    )
    candidates = list(session.scalars(stmt))
    if not candidates:
        return None

    # 마커가 있는 Run이 하나라도 있으면(전부 STEP12-15 이후 생성) legacy
    # 역참조 조회는 불필요 — 있는 legacy Run에 대해서만 1회 계산한다.
    needs_legacy_check = any((run.parameters or {}).get("execution_purpose") is None for run in candidates)
    legacy_excluded = (
        _legacy_non_primary_backtest_run_ids(session, strategy_definition_id) if needs_legacy_check else set()
    )

    for run in candidates:
        purpose = (run.parameters or {}).get("execution_purpose")
        if purpose is not None:
            if purpose in NON_PRIMARY_EXECUTION_PURPOSES:
                continue
            return int(run.backtest_run_id)
        if int(run.backtest_run_id) in legacy_excluded:
            continue
        return int(run.backtest_run_id)
    return None
