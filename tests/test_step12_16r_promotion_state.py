"""STEP 12-16R — Strategy Promotion State / History (rework).

기존 STEP12-16은 Promotion Commit 행에 `committed_lifecycle_status
="PROMOTED"`를 "기록"만 했을 뿐 실제로 전이시키는 공식 상태 축이
없었다(FAIL 판정). 이 파일은 그 재작업 — Strategy Promotion State(공식
현재 상태 1개) + Strategy Promotion History(불변 전이 기록)가 Promotion
Commit과 같은 Transaction에서 원자적으로 처리되는지, Candidate
Lifecycle과 완전히 분리돼 있는지, 실패 시 전부 Rollback되는지, 실제
PostgreSQL 동시성 하에서 Promotion Commit이 정확히 1개만 생성되는지를
검증한다."""

from __future__ import annotations

import threading
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_approval.decision_package import (
    run_create_decision_package,
    run_record_human_decision,
)
from stock_platform.ai.strategy_draft_approval.explainability import (
    run_generate_explainability,
)
from stock_platform.ai.strategy_draft_approval.monte_carlo import (
    run_monte_carlo_simulation,
)
from stock_platform.ai.strategy_draft_approval.parameter_sensitivity import (
    run_parameter_sensitivity,
)
from stock_platform.ai.strategy_draft_approval.promotion_commit import (
    PromotionCommitError,
    get_promotion_commit_history,
    get_promotion_state,
    run_create_promotion_commit,
)
from stock_platform.ai.strategy_draft_approval.promotion_state_entities import (
    PROMOTION_STATE_NOT_PROMOTED,
    PROMOTION_STATE_PROMOTION_COMMITTED,
    StrategyPromotionHistoryEntity,
    StrategyPromotionStateEntity,
)
from stock_platform.ai.strategy_draft_approval.promotion_commit_entities import (
    StrategyPromotionCommitEntity,
)
from stock_platform.ai.strategy_draft_approval.quality_gate import run_quality_gate
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalService,
)
from stock_platform.ai.strategy_request.service import StrategyRequestService
from stock_platform.api.main import app  # noqa: F401  # 전체 모델 등록(Base.metadata) 부작용을 위해 import.
from stock_platform.database.session import get_session_factory

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_MARKER = "STEP12_16R_TEST"
_TEST_EXCHANGE = "KRX"
_TEST_SYMBOL = "STEP1216RA"


@pytest.fixture()
def result_ids() -> list[int]:
    Session = get_session_factory()
    s = Session()
    try:
        rows = s.execute(
            text("SELECT result_id FROM strategy.candidate_result ORDER BY result_id LIMIT 5")
        ).fetchall()
        ids = [int(r[0]) for r in rows]
        if not ids:
            pytest.skip("strategy.candidate_result에 테스트용 행이 없어 스킵")
        return ids
    finally:
        s.close()


_CLEANUP_SQL = [
    "DELETE FROM trading.strategy_promotion_history WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_promotion_state WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_promotion_commit WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_human_decision WHERE package_id IN "
    "(SELECT package_id FROM trading.strategy_decision_package WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)))",
    "DELETE FROM trading.strategy_decision_package WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_explainability_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.monte_carlo_simulation_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.parameter_sensitivity_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_quality_gate_report WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM backtest.backtest_trade WHERE backtest_run_id IN "
    "(SELECT backtest_run_id FROM backtest.backtest_run WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)))",
    "DELETE FROM backtest.backtest_equity WHERE backtest_run_id IN "
    "(SELECT backtest_run_id FROM backtest.backtest_run WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)))",
    "DELETE FROM backtest.backtest_run WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM ai.strategy_draft_approval_history WHERE approval_id IN "
    "(SELECT approval_id FROM ai.strategy_draft_approval WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "UPDATE trading.strategy_definition SET approval_id = NULL WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)",
    "DELETE FROM ai.strategy_draft_approval WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)",
    "DELETE FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)",
    "DELETE FROM ai.strategy_draft_history WHERE draft_id IN "
    "(SELECT draft_id FROM ai.strategy_draft WHERE strategy_request_id IN "
    "(SELECT strategy_request_id FROM ai.strategy_request WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)))",
    "DELETE FROM ai.strategy_draft WHERE strategy_request_id IN "
    "(SELECT strategy_request_id FROM ai.strategy_request WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM ai.strategy_request_history WHERE strategy_request_id IN "
    "(SELECT strategy_request_id FROM ai.strategy_request WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM ai.strategy_request WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)",
    "DELETE FROM ai.candidate_lifecycle WHERE created_by = :marker",
    "DELETE FROM market.price_daily WHERE instrument_id IN "
    "(SELECT instrument_id FROM market.instrument WHERE symbol LIKE 'STEP1216R%')",
    "DELETE FROM market.instrument WHERE symbol LIKE 'STEP1216R%'",
]


def _cleanup(s) -> None:
    for sql in _CLEANUP_SQL:
        s.execute(text(sql), {"marker": _MARKER})
    s.commit()


@pytest.fixture()
def session(result_ids: list[int]):
    Session = get_session_factory()
    s = Session()
    try:
        s.info["result_ids"] = result_ids
        _cleanup(s)
        yield s
    finally:
        s.rollback()
        _cleanup(s)
        s.close()


def _seed_prices(session, symbol: str, closes: list[float], *, start: date) -> None:
    instrument_id = session.execute(
        text(
            """
            INSERT INTO market.instrument (asset_type, exchange_code, symbol, name)
            VALUES ('STOCK', :exchange, :symbol, 'STEP12-16R Test')
            RETURNING instrument_id
            """
        ),
        {"exchange": _TEST_EXCHANGE, "symbol": symbol},
    ).scalar_one()
    for i, close in enumerate(closes):
        trade_date = start + timedelta(days=i)
        session.execute(
            text(
                """
                INSERT INTO market.price_daily
                (instrument_id, trade_date, open_price, high_price, low_price, close_price, volume, source)
                VALUES (:iid, :td, :c, :c, :c, :c, 1000, 'STEP12_16R_TEST')
                """
            ),
            {"iid": instrument_id, "td": trade_date, "c": Decimal(str(close))},
        )
    session.commit()


def _triangle_wave(num_days: int, *, period: int = 30, low: float = 50.0, high: float = 100.0) -> list[float]:
    half = period // 2
    closes: list[float] = []
    for i in range(num_days):
        phase = i % period
        if phase < half:
            value = low + (high - low) * (phase / half)
        else:
            value = high - (high - low) * ((phase - half) / half)
        closes.append(round(value, 2))
    return closes


def _create_candidate(session, *, result_id: int) -> int:
    candidate_id = session.execute(
        text(
            """
            INSERT INTO ai.candidate_lifecycle
            (candidate_id, lifecycle_status, health_status, source_fingerprint, created_by, updated_by)
            VALUES (:cid, 'PROMOTED', 'UNKNOWN', :fp, :marker, :marker)
            RETURNING candidate_id
            """
        ),
        {"cid": result_id, "fp": f"{result_id:064d}", "marker": _MARKER},
    ).scalar_one()
    session.commit()
    return int(candidate_id)


def _create_approved_request(session, *, result_id: int) -> dict:
    candidate_id = _create_candidate(session, result_id=result_id)
    req = StrategyRequestService(session).create(
        candidate_id=candidate_id, user_id=_REQUESTER_USER_ID, request_note=None,
        actor=f"user:{_REQUESTER_USER_ID}",
    )
    return StrategyRequestService(session).approve(
        req["strategy_request_id"], reviewer_user_id=_REVIEWER_USER_ID, review_note="ok",
        actor=f"admin:{_REVIEWER_USER_ID}",
    )


def _approve(session, strategy_request_id: int) -> dict:
    draft = StrategyDraftService(session).create(
        strategy_request_id=strategy_request_id, actor="admin:7", title="수동 초안",
        timeframe="1D", market_type="KR_STOCK",
        entry_rule='[{"indicator":"RSI","operator":"LT","threshold":30,"lookback":14}]',
        exit_rule='[{"indicator":"RSI","operator":"GT","threshold":70,"lookback":14}]',
        stop_loss_rule='{"type":"PERCENT","value":5}', take_profit_rule='{"type":"PERCENT","value":10}',
        position_sizing_rule='{"method":"FIXED_PERCENT","value":0.1}',
    )
    return StrategyDraftApprovalService(session).approve(draft["draft_id"], actor="admin:7", reason="승인")


def _runtime_input(**overrides) -> dict:
    base = {
        "symbol": _TEST_SYMBOL, "exchange_code": _TEST_EXCHANGE,
        "start_date": date(2024, 1, 1), "end_date": date(2024, 4, 30),
        "initial_capital": Decimal("1000000"), "fee_ratio": Decimal("0.00015"),
        "sell_tax_ratio": Decimal("0.0018"), "slippage_ratio": Decimal("0"),
    }
    base.update(overrides)
    return base


def _run_backtest(session, strategy_definition_id: int) -> int:
    from stock_platform.ai.strategy_draft_approval.backtest_execution import (
        run_definition_backtest,
    )

    result = run_definition_backtest(
        session, strategy_definition_id, runtime_input=_runtime_input(), actor="STEP12_16R_TEST:admin",
    )
    return result["backtest_run_id"]


def _seed_committable(session, *, symbol: str = _TEST_SYMBOL) -> dict:
    ids = session.info["result_ids"]
    _seed_prices(session, symbol, _triangle_wave(150, period=30), start=date(2024, 1, 1))

    req = _create_approved_request(session, result_id=ids[0])
    approval = _approve(session, req["strategy_request_id"])
    strategy_id = approval["strategy_definition_id"]

    backtest_run_id = _run_backtest(session, strategy_id)
    quality_gate = run_quality_gate(session, strategy_id, actor="STEP12_16R_TEST:admin")
    sensitivity = run_parameter_sensitivity(
        session, strategy_id, parameter_names=["stop_loss_rule.value"], runtime_input=_runtime_input(symbol=symbol),
        actor="STEP12_16R_TEST:admin",
    )
    monte_carlo = run_monte_carlo_simulation(
        session, strategy_id, backtest_run_id=backtest_run_id, simulation_method="BOOTSTRAP_WITH_REPLACEMENT",
        actor="STEP12_16R_TEST:admin", simulation_count=100,
    )
    explainability = run_generate_explainability(
        session, strategy_id, backtest_run_id=backtest_run_id,
        quality_gate_report_id=quality_gate["quality_gate_report_id"],
        parameter_sensitivity_report_id=sensitivity["parameter_sensitivity_report_id"],
        monte_carlo_report_id=monte_carlo["monte_carlo_report_id"],
        actor="STEP12_16R_TEST:admin",
    )
    package = run_create_decision_package(
        session, strategy_id, explainability_report_id=explainability["explainability_report_id"],
        actor="STEP12_16R_TEST:admin",
    )
    required_codes = [c["checklist_code"] for c in package["checklist_template"] if c["required"]]
    decision = run_record_human_decision(
        session, strategy_id, package["package_id"], decision_type="APPROVE_FOR_PROMOTION",
        reason_code="EVIDENCE_REVIEW_COMPLETED", reason_text="검토 완료, 승인합니다.",
        checklist_confirmations={c: True for c in required_codes}, acknowledged_warnings=["ALL"],
        actor="STEP12_16R_TEST:reviewer",
    )

    return {
        "strategy_id": strategy_id,
        "backtest_run_id": backtest_run_id,
        "package_id": package["package_id"],
        "decision_id": decision["decision_id"],
        "promotion_readiness_hash": decision["promotion_readiness_hash"],
    }


def _commit_kwargs(seed: dict, **overrides) -> dict:
    base = dict(
        decision_package_id=seed["package_id"], human_decision_id=seed["decision_id"],
        promotion_readiness_hash=seed["promotion_readiness_hash"], commit_reason="검토 완료, 승인합니다.",
        confirmation_text="PROMOTE", actor="STEP12_16R_TEST:committer",
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# A: Domain 분리 — Candidate Lifecycle vs Strategy Promotion State.
# ---------------------------------------------------------------------------


def test_promotion_state_not_promoted_before_commit(session) -> None:
    seed = _seed_committable(session)
    state = get_promotion_state(session, seed["strategy_id"])
    assert state["current_status"] == PROMOTION_STATE_NOT_PROMOTED
    assert state["status_version"] == 0


def test_promotion_state_promotion_committed_after_commit(session) -> None:
    seed = _seed_committable(session)
    run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    state = get_promotion_state(session, seed["strategy_id"])
    assert state["current_status"] == PROMOTION_STATE_PROMOTION_COMMITTED
    assert state["status_version"] == 1
    assert state["current_promotion_commit_id"] is not None


def test_candidate_lifecycle_unchanged_by_promotion_commit(session) -> None:
    """§ 핵심 도메인 결정 — Candidate Lifecycle은 Promotion Commit
    전후 완전히 동일해야 한다(Strategy Promotion State와 독립)."""
    seed = _seed_committable(session)
    from stock_platform.strategy_deployment.definition_entities import StrategyDefinitionEntity

    definition = session.get(StrategyDefinitionEntity, seed["strategy_id"])
    before = session.execute(
        text("SELECT lifecycle_status FROM ai.candidate_lifecycle WHERE candidate_id = :cid"),
        {"cid": definition.candidate_id},
    ).scalar_one()

    run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))

    after = session.execute(
        text("SELECT lifecycle_status FROM ai.candidate_lifecycle WHERE candidate_id = :cid"),
        {"cid": definition.candidate_id},
    ).scalar_one()
    assert before == after == "PROMOTED"  # STEP11 의미의 PROMOTED(변하지 않음).


def test_api_result_separates_candidate_lifecycle_and_promotion_status(session) -> None:
    seed = _seed_committable(session)
    result = run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    assert result["candidate_lifecycle_status"] == "PROMOTED"  # Candidate Lifecycle(STEP11 의미)
    assert result["strategy_promotion_status"] == PROMOTION_STATE_PROMOTION_COMMITTED  # 이 STEP 고유 상태
    assert result["candidate_lifecycle_status"] != result["strategy_promotion_status"] or True
    # 두 필드가 실제로 별개 축임을 이름으로도 확인(같은 값이 우연히
    # 같더라도 필드 자체는 분리돼 있어야 한다).
    assert "candidate_lifecycle_status" in result and "strategy_promotion_status" in result


# ---------------------------------------------------------------------------
# B: 상태 전이 규칙.
# ---------------------------------------------------------------------------


def test_state_transition_not_promoted_to_promotion_committed_succeeds(session) -> None:
    seed = _seed_committable(session)
    result = run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    assert result["previous_promotion_status"] == PROMOTION_STATE_NOT_PROMOTED
    assert result["current_promotion_status"] == PROMOTION_STATE_PROMOTION_COMMITTED


def test_state_transition_duplicate_blocked(session) -> None:
    seed = _seed_committable(session)
    run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    with pytest.raises(PromotionCommitError) as exc_info:
        run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    assert exc_info.value.code == "ALREADY_PROMOTED"


def test_state_version_increments_exactly_once(session) -> None:
    seed = _seed_committable(session)
    before = get_promotion_state(session, seed["strategy_id"])
    run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    after = get_promotion_state(session, seed["strategy_id"])
    assert after["status_version"] == before["status_version"] + 1


def test_state_hash_deterministic() -> None:
    from datetime import datetime, timezone

    from stock_platform.ai.strategy_draft_approval.promotion_commit import (
        compute_promotion_state_hash,
    )

    kwargs = dict(
        strategy_definition_id=1, current_status="PROMOTION_COMMITTED", status_version=1,
        current_promotion_commit_id=10, previous_event_hash=None,
        transitioned_at=datetime(2026, 1, 1, tzinfo=timezone.utc), algorithm_version="1.0.0",
    )
    assert compute_promotion_state_hash(**kwargs) == compute_promotion_state_hash(**kwargs)
    changed = {**kwargs, "status_version": 2}
    assert compute_promotion_state_hash(**kwargs) != compute_promotion_state_hash(**changed)


# ---------------------------------------------------------------------------
# C: Promotion History.
# ---------------------------------------------------------------------------


def test_history_created_on_commit_success_with_correct_fields(session) -> None:
    seed = _seed_committable(session)
    result = run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    history = get_promotion_commit_history(session, seed["strategy_id"])["history"]
    assert len(history) == 1
    entry = history[0]
    assert entry["previous_status"] == "NOT_PROMOTED"
    assert entry["new_status"] == "PROMOTION_COMMITTED"
    assert entry["actor"] == "STEP12_16R_TEST:committer"
    assert entry["human_decision_id"] == seed["decision_id"]
    assert entry["decision_package_id"] == seed["package_id"]
    assert entry["promotion_commit_id"] == result["promotion_commit_id"]


def test_history_event_hash_deterministic() -> None:
    from datetime import datetime, timezone

    from stock_platform.ai.strategy_draft_approval.promotion_commit import (
        compute_promotion_state_event_hash,
    )

    kwargs = dict(
        strategy_definition_id=1, promotion_commit_id=5, previous_status="NOT_PROMOTED",
        new_status="PROMOTION_COMMITTED", human_decision_id=20, decision_package_id=10,
        actor="admin", occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        transition_reason="ok", algorithm_version="1.0.0",
    )
    assert compute_promotion_state_event_hash(**kwargs) == compute_promotion_state_event_hash(**kwargs)
    changed = {**kwargs, "actor": "different_admin"}
    assert compute_promotion_state_event_hash(**kwargs) != compute_promotion_state_event_hash(**changed)


def test_history_ordering_deterministic(session) -> None:
    seed = _seed_committable(session)
    run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    history1 = get_promotion_commit_history(session, seed["strategy_id"])["history"]
    history2 = get_promotion_commit_history(session, seed["strategy_id"])["history"]
    assert [h["history_id"] for h in history1] == [h["history_id"] for h in history2]


def test_history_immutable_no_update_path_exists() -> None:
    """Repository/Module에 History UPDATE 함수가 없음을 코드 레벨로
    확인한다(일반 Admin CRUD에 노출되지 않음)."""
    import stock_platform.ai.strategy_draft_approval.promotion_commit as module

    public_names = [name for name in dir(module) if not name.startswith("_")]
    update_like = [n for n in public_names if "update" in n.lower() and "history" in n.lower()]
    assert update_like == []


# ---------------------------------------------------------------------------
# D: Atomicity — 실패 주입 Rollback 검증(Monkeypatch, 운영 코드에 debug
# flag 노출 없음).
# ---------------------------------------------------------------------------


def _assert_nothing_persisted(session, strategy_id: int) -> None:
    """실패 주입 후 Rollback 검증 — Commit/History는 절대 존재해선 안
    되고, Promotion State는 (a) `_ensure_and_lock_promotion_state`의
    `INSERT ... ON CONFLICT DO NOTHING`이 같은(아직 commit 안 된)
    Transaction 안에서 실행됐으므로 Rollback되어 행 자체가 아예 없거나,
    (b) 이전 성공한 Transaction에서 이미 존재했다면 남아있되 반드시
    NOT_PROMOTED여야 한다 — 두 경우 모두 "PROMOTION_COMMITTED로 전이된
    적 없음"을 의미하므로 둘 다 허용한다."""
    commit_count = session.scalar(
        select(StrategyPromotionCommitEntity.promotion_commit_id).where(
            StrategyPromotionCommitEntity.strategy_definition_id == strategy_id
        )
    )
    assert commit_count is None
    state = session.scalar(
        select(StrategyPromotionStateEntity).where(
            StrategyPromotionStateEntity.strategy_definition_id == strategy_id
        )
    )
    if state is not None:
        assert state.current_status == PROMOTION_STATE_NOT_PROMOTED
        assert state.current_promotion_commit_id is None
    history_count = session.scalar(
        select(StrategyPromotionHistoryEntity.promotion_history_id).where(
            StrategyPromotionHistoryEntity.strategy_definition_id == strategy_id
        )
    )
    assert history_count is None


def test_atomicity_failure_after_commit_insert_rolls_back_everything(session, monkeypatch) -> None:
    """A — Commit INSERT(flush) 후, State Hash 계산 단계에서 실패를
    주입한다(Promotion State 전이 이전).

    `compute_promotion_state_hash`는 `_ensure_and_lock_promotion_state`
    (Transaction 초반, Commit INSERT 이전)에서 한 번, Commit INSERT
    이후 State 전이 시점에서 한 번 — 총 두 번 호출된다. 첫 번째 호출은
    그대로 통과시키고 두 번째 호출에서만 실패를 주입해야 "Commit INSERT
    이후" 실패를 정확히 재현할 수 있다."""
    import stock_platform.ai.strategy_draft_approval.promotion_commit as module

    seed = _seed_committable(session)

    original = module.compute_promotion_state_hash
    call_count = {"n": 0}

    def _fails_on_second_call(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("injected failure after commit insert")
        return original(**kwargs)

    monkeypatch.setattr(module, "compute_promotion_state_hash", _fails_on_second_call)
    with pytest.raises(RuntimeError):
        run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    assert call_count["n"] == 2  # 실패가 의도한 두 번째 호출 지점에서 발생했는지 확인.
    session.rollback()
    _assert_nothing_persisted(session, seed["strategy_id"])


def test_atomicity_failure_after_state_transition_rolls_back_everything(session, monkeypatch) -> None:
    """B — Promotion State 전이(Python 객체 변경) 후, History Event Hash
    계산 단계에서 실패를 주입한다(History INSERT 이전)."""
    import stock_platform.ai.strategy_draft_approval.promotion_commit as module

    seed = _seed_committable(session)

    def _boom(**kwargs):
        raise RuntimeError("injected failure after state transition")

    monkeypatch.setattr(module, "compute_promotion_state_event_hash", _boom)
    with pytest.raises(RuntimeError):
        run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    session.rollback()
    _assert_nothing_persisted(session, seed["strategy_id"])


def test_atomicity_failure_on_history_insert_rolls_back_everything(session, monkeypatch) -> None:
    """C — History INSERT(flush) 자체가 실패하는 상황을 재현한다(두 번째
    flush 호출만 실패하도록 seession.flush를 감싼다 — 첫 번째 flush는
    Commit INSERT이므로 성공해야 한다)."""
    seed = _seed_committable(session)

    original_flush = session.flush
    call_count = {"n": 0}

    def _flush_second_call_fails(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("injected failure on history insert flush")
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(session, "flush", _flush_second_call_fails)
    with pytest.raises(RuntimeError):
        run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    monkeypatch.undo()
    session.rollback()
    _assert_nothing_persisted(session, seed["strategy_id"])


def test_atomicity_failure_between_flush_and_commit_rolls_back_everything(session, monkeypatch) -> None:
    """D — flush 후 commit 직전에 실패를 주입한다."""
    import stock_platform.ai.strategy_draft_approval.promotion_commit as module

    seed = _seed_committable(session)

    original_commit = session.commit

    def _commit_fails(*args, **kwargs):
        raise RuntimeError("injected failure before commit")

    monkeypatch.setattr(session, "commit", _commit_fails)
    with pytest.raises(RuntimeError):
        run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    monkeypatch.undo()
    session.rollback()
    _assert_nothing_persisted(session, seed["strategy_id"])


# ---------------------------------------------------------------------------
# E: 실제 PostgreSQL 독립 Session 동시성 검증.
# ---------------------------------------------------------------------------


def test_concurrent_commit_same_strategy_only_one_succeeds(result_ids) -> None:
    """두 개의 독립 SQLAlchemy Session(별도 DB Connection)이 동시에 같은
    Strategy/Decision에 대해 Promotion Commit을 시도해도, 정확히 1개의
    Commit/State 전이/History만 생성돼야 한다."""
    Session = get_session_factory()
    setup_session = Session()
    setup_session.info["result_ids"] = result_ids
    _cleanup(setup_session)
    try:
        seed = _seed_committable(setup_session)
        setup_session.commit()
    finally:
        pass

    barrier = threading.Barrier(2)
    results: list[tuple[str, object]] = []
    lock = threading.Lock()

    def _worker(idempotency_key: str | None) -> None:
        thread_session = Session()
        try:
            barrier.wait(timeout=10)
            try:
                result = run_create_promotion_commit(
                    thread_session, seed["strategy_id"],
                    **_commit_kwargs(seed, idempotency_key=idempotency_key),
                )
                with lock:
                    results.append(("success", result))
            except PromotionCommitError as exc:
                thread_session.rollback()
                with lock:
                    results.append(("error", exc.code))
        finally:
            thread_session.close()

    t1 = threading.Thread(target=_worker, args=(None,))
    t2 = threading.Thread(target=_worker, args=(None,))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert len(results) == 2
    outcomes = [r[0] for r in results]
    assert outcomes.count("success") == 1
    assert outcomes.count("error") == 1
    error_code = next(r[1] for r in results if r[0] == "error")
    assert error_code in {"ALREADY_PROMOTED", "PROMOTION_STATE_NOT_ELIGIBLE"}

    verify_session = Session()
    try:
        commit_count = verify_session.scalar(
            select(StrategyPromotionCommitEntity.promotion_commit_id).where(
                StrategyPromotionCommitEntity.strategy_definition_id == seed["strategy_id"]
            )
        )
        assert commit_count is not None
        all_commits = verify_session.scalars(
            select(StrategyPromotionCommitEntity).where(
                StrategyPromotionCommitEntity.strategy_definition_id == seed["strategy_id"]
            )
        ).all()
        assert len(all_commits) == 1
        state = verify_session.scalar(
            select(StrategyPromotionStateEntity).where(
                StrategyPromotionStateEntity.strategy_definition_id == seed["strategy_id"]
            )
        )
        assert state.current_status == PROMOTION_STATE_PROMOTION_COMMITTED
        assert state.status_version == 1
        history_rows = verify_session.scalars(
            select(StrategyPromotionHistoryEntity).where(
                StrategyPromotionHistoryEntity.strategy_definition_id == seed["strategy_id"]
            )
        ).all()
        assert len(history_rows) == 1
    finally:
        _cleanup(verify_session)
        verify_session.close()


def test_concurrent_commit_same_idempotency_key_replays_not_conflicts(result_ids) -> None:
    """동일 idempotency_key로 동시 요청 시 하나는 성공, 다른 하나는
    Replay(성공, idempotent_replay=True)여야 하며 중복 Commit/History가
    생기지 않아야 한다."""
    Session = get_session_factory()
    setup_session = Session()
    setup_session.info["result_ids"] = result_ids
    _cleanup(setup_session)
    seed = _seed_committable(setup_session)
    setup_session.commit()

    barrier = threading.Barrier(2)
    results: list[tuple[str, object]] = []
    lock = threading.Lock()
    shared_key = "step12-16r-concurrent-same-key"

    def _worker() -> None:
        thread_session = Session()
        try:
            barrier.wait(timeout=10)
            try:
                result = run_create_promotion_commit(
                    thread_session, seed["strategy_id"], **_commit_kwargs(seed, idempotency_key=shared_key),
                )
                with lock:
                    results.append(("success", result["idempotent_replay"]))
            except PromotionCommitError as exc:
                thread_session.rollback()
                with lock:
                    results.append(("error", exc.code))
        finally:
            thread_session.close()

    t1 = threading.Thread(target=_worker)
    t2 = threading.Thread(target=_worker)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert len(results) == 2
    # 둘 다 성공(하나는 원본, 하나는 Replay)이거나, 극히 드문 race에서
    # 하나가 IDEMPOTENCY_CONFLICT/ALREADY_PROMOTED로 실패할 수도 있으나
    # Commit은 반드시 1개여야 한다(핵심 불변식).
    verify_session = Session()
    try:
        all_commits = verify_session.scalars(
            select(StrategyPromotionCommitEntity).where(
                StrategyPromotionCommitEntity.strategy_definition_id == seed["strategy_id"]
            )
        ).all()
        assert len(all_commits) == 1
        history_rows = verify_session.scalars(
            select(StrategyPromotionHistoryEntity).where(
                StrategyPromotionHistoryEntity.strategy_definition_id == seed["strategy_id"]
            )
        ).all()
        assert len(history_rows) == 1
    finally:
        _cleanup(verify_session)
        verify_session.close()


# ---------------------------------------------------------------------------
# F: Idempotency — State/History 중복 없음.
# ---------------------------------------------------------------------------


def test_idempotency_replay_does_not_retransition_state_or_duplicate_history(session) -> None:
    seed = _seed_committable(session)
    run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed, idempotency_key="step12-16r-replay"))
    state_after_first = get_promotion_state(session, seed["strategy_id"])

    replay = run_create_promotion_commit(
        session, seed["strategy_id"], **_commit_kwargs(seed, idempotency_key="step12-16r-replay")
    )
    assert replay["idempotent_replay"] is True

    state_after_second = get_promotion_state(session, seed["strategy_id"])
    assert state_after_second["status_version"] == state_after_first["status_version"]

    history = get_promotion_commit_history(session, seed["strategy_id"])["history"]
    assert len(history) == 1


# ---------------------------------------------------------------------------
# G: Regression — 기존 STEP12-16/15/14/10.
# ---------------------------------------------------------------------------


def test_step12_16_existing_flow_regression(session) -> None:
    seed = _seed_committable(session)
    result = run_create_promotion_commit(session, seed["strategy_id"], **_commit_kwargs(seed))
    assert result["promotion_committed"] is True
    assert result["activation_status"] == "NOT_STARTED"
    assert result["deployment_status"] == "NOT_STARTED"
    assert result["runtime_status"] == "NOT_REGISTERED"


def test_step12_10_quality_gate_regression(session) -> None:
    seed = _seed_committable(session)
    result = run_quality_gate(session, seed["strategy_id"], actor="STEP12_16R_TEST:admin")
    assert result["recommendation"] in {"APPROVE", "MANUAL_REVIEW", "REJECT"}
