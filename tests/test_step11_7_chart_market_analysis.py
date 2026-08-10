"""STEP 11-7 Chart/Market AI analysis tests (Mock only)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from stock_platform.ai.execution.constants import (
    BLOCKED_TASK_TYPES,
    EXECUTABLE_TASK_TYPES,
)
from stock_platform.ai.market_analysis.candle import (
    normalize_candle_row,
    to_decimal,
    validate_ohlc,
)
from stock_platform.ai.market_analysis.constants import (
    MAX_BATCH_EXTERNAL,
    MAX_BATCH_MOCK,
    MAX_DAILY_CANDLES,
    MIN_DAILY_CANDLES,
    VISION_ENABLED_DEFAULT,
)


def test_chart_market_tasks_executable() -> None:
    assert "CHART_ANALYSIS" in EXECUTABLE_TASK_TYPES
    assert "MARKET_ANALYSIS" in EXECUTABLE_TASK_TYPES
    assert "STRATEGY_DRAFT" in BLOCKED_TASK_TYPES
    assert "STOCK_CANDIDATE_ANALYSIS" in EXECUTABLE_TASK_TYPES


def test_migration_and_head() -> None:
    from tests.migration_helpers import assert_revision_is_ancestor_of_head

    versions = Path("database/alembic/versions")
    assert any(p.name.startswith("y5f6a7b8c9d0") for p in versions.glob("*.py"))
    assert_revision_is_ancestor_of_head("ae5f6a7b8c9d")


def test_candle_limits() -> None:
    assert MIN_DAILY_CANDLES == 30
    assert MAX_DAILY_CANDLES == 250
    assert MAX_BATCH_MOCK == 100
    assert MAX_BATCH_EXTERNAL == 10


def test_decimal_rejects_nan_inf() -> None:
    with pytest.raises(ValueError):
        to_decimal(float("nan"))
    with pytest.raises(ValueError):
        to_decimal(float("inf"))
    assert to_decimal("123.45") == Decimal("123.45")


def test_ohlc_validation() -> None:
    flags = validate_ohlc(
        open_price=Decimal("10"),
        high=Decimal("7"),
        low=Decimal("8"),
        close=Decimal("9"),
        volume=Decimal("-1"),
    )
    assert "NEGATIVE_VOLUME" in flags
    assert "HIGH_BELOW_LOW" in flags


def test_normalize_candle_decimal_strings() -> None:
    row = normalize_candle_row(
        {
            "open_time": "2026-01-01",
            "close_time": "2026-01-01",
            "open": "100",
            "high": "110",
            "low": "90",
            "close": "105",
            "volume": "1000",
            "is_complete": True,
            "source": "KIWOOM",
            "adjusted": True,
        }
    )
    assert row["open"] == "100.00000000"
    assert row["quality_flags"] == []


def test_vision_disabled_by_default() -> None:
    assert VISION_ENABLED_DEFAULT is False


def test_strategy_still_blocked() -> None:
    from stock_platform.ai.execution.service import (
        AIExecutionError,
        AIExecutionService,
    )

    with pytest.raises(AIExecutionError) as exc:
        AIExecutionService(MagicMock()).create_request(
            actor="a",
            reason="r",
            task_type="STRATEGY_DRAFT",
            execution_mode="MOCK",
            idempotency_key="s1",
        )
    assert exc.value.code == "AI_TASK_EXECUTION_NOT_ENABLED"


def test_chart_task_create_allowed_at_gate() -> None:
    from stock_platform.ai.execution.service import AIExecutionService

    session = MagicMock()
    session.scalar.return_value = None
    session.flush = MagicMock()
    session.commit = MagicMock()
    result = AIExecutionService(session).create_request(
        actor="admin:1",
        reason="chart",
        task_type="CHART_ANALYSIS",
        execution_mode="MOCK",
        idempotency_key="c1",
        input_payload={
            "symbol": "005930",
            "exchange_code": "KRX",
            "timeframe": "1D",
            "indicators": "{}",
            "current_price": "70000",
            "snapshot_json": "{}",
            "market_type": "KR_STOCK",
            "data_quality": "GOOD",
        },
    )
    assert result["idempotent_replay"] is False


def test_trading_order_scheduler_no_market_analysis_import() -> None:
    offenders: list[str] = []
    for root in (
        Path("src/stock_platform/trading"),
        Path("src/stock_platform/order"),
        Path("src/stock_platform/scheduler"),
    ):
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "market_analysis" in text or "ai.market_analysis" in text:
                offenders.append(str(path))
    assert offenders == []


def test_batch_confirm_and_cap() -> None:
    from stock_platform.ai.market_analysis.service import (
        AIMarketAnalysisBatchService,
        AIMarketAnalysisError,
    )

    with pytest.raises(AIMarketAnalysisError) as exc:
        AIMarketAnalysisBatchService(MagicMock()).create_batch(
            actor="a",
            reason="r",
            exchange_code="KRX",
            symbols=["005930"],
            timeframe="1D",
            execution_mode="MOCK",
            provider_code="mock",
            model=None,
            prompt_version_id=None,
            confirm=False,
            idempotency_key="b1",
        )
    assert exc.value.code == "CONFIRM_REQUIRED"

    with pytest.raises(AIMarketAnalysisError) as exc2:
        AIMarketAnalysisBatchService(MagicMock()).create_batch(
            actor="a",
            reason="r",
            exchange_code="KRX",
            symbols=[str(i) for i in range(20)],
            timeframe="1D",
            execution_mode="EXTERNAL",
            provider_code="openai",
            model="x",
            prompt_version_id=None,
            confirm=True,
            idempotency_key="b2",
        )
    assert exc2.value.code == "BATCH_LIMIT"


def test_seed_schemas_have_chart_market() -> None:
    from stock_platform.ai.prompt.seed_data import (
        CHART_ANALYSIS_RESULT_V1,
        MARKET_ANALYSIS_RESULT_V1,
        SEED_PROMPTS,
        SEED_SCHEMAS,
    )

    assert any(s["code"] == "MARKET_ANALYSIS_RESULT_V1" for s in SEED_SCHEMAS)
    assert any(p["code"] == "MARKET_ANALYSIS_BASE" for p in SEED_PROMPTS)
    assert "buy" not in str(CHART_ANALYSIS_RESULT_V1).lower()
    assert "target_price" not in str(MARKET_ANALYSIS_RESULT_V1).lower()
    assert "allocate" not in str(MARKET_ANALYSIS_RESULT_V1).lower()


def test_eligibility_vision_blocked() -> None:
    from stock_platform.ai.market_analysis.eligibility import (
        AIMarketEligibilityService,
    )

    result = AIMarketEligibilityService(MagicMock()).evaluate(
        analysis_type="SYMBOL_CHART",
        exchange_code="KRX",
        symbol="005930",
        use_vision=True,
    )
    assert result["eligible"] is False
    assert "VISION" in str(result.get("reasons") or result)


def test_cancel_allows_already_terminal_execution() -> None:
    """recovery abandon 후 analysis RUNNING orphan을 cancel로 정리할 수 있어야 한다."""

    from datetime import datetime, timezone
    from types import SimpleNamespace

    from stock_platform.ai.execution.service import AIExecutionError
    from stock_platform.ai.market_analysis.service import AIMarketAnalysisService

    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        market_analysis_id=15,
        analysis_status="RUNNING",
        execution_request_id=15,
        correlation_id="corr-15",
        analyzed_at=None,
        safe_result=None,
        confidence=None,
        provider_code="ollama",
        model="qwen3.5:4b",
        warnings=None,
        reason="r",
        created_by="job",
        created_at=now,
        updated_at=now,
        analysis_type="SYMBOL_CHART",
        exchange_code="UPBIT",
        symbol="KRW-XRP",
        timeframe="1m",
        execution_mode="EXTERNAL",
        data_from=None,
        data_to=None,
        prompt_version_id=None,
        superseded_at=None,
        superseded_by_id=None,
    )
    session = MagicMock()
    session.get.return_value = row
    session.scalars.return_value = []  # open runs 없음

    svc = AIMarketAnalysisService(session)
    svc._exec = MagicMock()
    svc._exec.cancel.side_effect = AIExecutionError(
        "ALREADY_TERMINAL", "Cannot cancel terminal request"
    )
    svc._history = MagicMock()
    svc._public = MagicMock(return_value={"id": 15, "analysis_status": "CANCELLED"})

    out = svc.cancel(15, actor="admin:test", reason="orphan cleanup after abandon")
    assert out["analysis"]["analysis_status"] == "CANCELLED"
    assert row.analysis_status == "CANCELLED"
    session.commit.assert_called()
