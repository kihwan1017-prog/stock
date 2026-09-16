"""STEP 12-17 — Activation Review & Activation Commit.

PROMOTION_COMMITTED 상태인 Strategy Definition을 대상으로 Activation
Review Package(계좌·시장·브로커·리스크·운영 준비 상태 검증) → Human
Activation Decision → Activation Commit까지 검증한다. Runtime 등록/시작,
Scheduler 등록, Broker 연결, 주문 실행은 전혀 수행하지 않는다."""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_approval.activation import (
    ActivationError,
    _can_transition_activation_state,
    build_activation_checklist_template,
    check_activation_package_staleness,
    compute_activation_commit_hash,
    compute_activation_decision_input_hash,
    compute_activation_review_input_hash,
    get_activation_commit,
    get_activation_decision,
    get_activation_review_package,
    get_activation_status,
    run_create_activation_commit,
    run_create_activation_review_package,
    run_record_activation_decision,
)
from stock_platform.ai.strategy_draft_approval.activation_entities import (
    ACCOUNT_KIND_PAPER,
    ACCOUNT_KIND_USER_BROKER,
    ACTIVATION_READINESS_BLOCKED,
    ACTIVATION_READINESS_READY,
    EXECUTION_MODE_LIVE,
    EXECUTION_MODE_PAPER,
    StrategyActivationCommitEntity,
    StrategyActivationDecisionEntity,
    StrategyActivationReviewPackageEntity,
)
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
    run_create_promotion_commit,
)
from stock_platform.ai.strategy_draft_approval.promotion_state_entities import (
    PROMOTION_STATE_ACTIVATED,
    PROMOTION_STATE_ACTIVATION_REVIEW,
    PROMOTION_STATE_NOT_PROMOTED,
    PROMOTION_STATE_PROMOTION_COMMITTED,
    StrategyPromotionHistoryEntity,
    StrategyPromotionStateEntity,
)
from stock_platform.ai.strategy_draft_approval.quality_gate import run_quality_gate
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalService,
)
from stock_platform.ai.strategy_request.service import StrategyRequestService
from stock_platform.api.main import app  # noqa: F401  — 전체 모델 등록 부작용.
from stock_platform.broker.credential_entities import BrokerAccountCredentialEntity
from stock_platform.database.session import get_session_factory
from stock_platform.trading.account_models import PaperAccount, UserBrokerAccount

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_MARKER = "STEP12_17_TEST"
_TEST_EXCHANGE = "KRX"


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
    "DELETE FROM trading.strategy_activation_commit WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_activation_decision WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_activation_review_package WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
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
    "DELETE FROM trading.broker_account_credential WHERE user_broker_account_id IN "
    "(SELECT user_broker_account_id FROM trading.user_broker_account WHERE account_alias LIKE 'STEP12_17_TEST%')",
    "DELETE FROM trading.user_broker_account WHERE account_alias LIKE 'STEP12_17_TEST%'",
    "DELETE FROM trading.paper_account WHERE account_name LIKE 'STEP12_17_TEST%'",
    "DELETE FROM market.price_daily WHERE instrument_id IN "
    "(SELECT instrument_id FROM market.instrument WHERE symbol LIKE 'STEP1217%')",
    "DELETE FROM market.instrument WHERE symbol LIKE 'STEP1217%'",
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


def _seed_prices(session, symbol: str, closes: list[float], *, start: date) -> None:
    instrument_id = session.execute(
        text(
            """
            INSERT INTO market.instrument (asset_type, exchange_code, symbol, name)
            VALUES ('STOCK', :exchange, :symbol, 'STEP12-17 Test')
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
                VALUES (:iid, :td, :c, :c, :c, :c, 1000, 'STEP12_17_TEST')
                """
            ),
            {"iid": instrument_id, "td": trade_date, "c": Decimal(str(close))},
        )
    session.commit()


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


def _runtime_input(symbol: str, **overrides) -> dict:
    base = {
        "symbol": symbol, "exchange_code": _TEST_EXCHANGE,
        "start_date": date(2024, 1, 1), "end_date": date(2024, 4, 30),
        "initial_capital": Decimal("1000000"), "fee_ratio": Decimal("0.00015"),
        "sell_tax_ratio": Decimal("0.0018"), "slippage_ratio": Decimal("0"),
    }
    base.update(overrides)
    return base


def _run_backtest(session, strategy_definition_id: int, symbol: str) -> int:
    from stock_platform.ai.strategy_draft_approval.backtest_execution import (
        run_definition_backtest,
    )

    result = run_definition_backtest(
        session, strategy_definition_id, runtime_input=_runtime_input(symbol), actor="STEP12_17_TEST:admin",
    )
    return result["backtest_run_id"]


def _seed_promotion_committed(session, *, symbol: str, result_id_index: int = 0) -> dict:
    ids = session.info["result_ids"]
    if result_id_index >= len(ids):
        pytest.skip(f"result_ids[{result_id_index}] 없음 — 테스트 데이터 부족")
    _seed_prices(session, symbol, _triangle_wave(150, period=30), start=date(2024, 1, 1))

    req = _create_approved_request(session, result_id=ids[result_id_index])
    approval = _approve(session, req["strategy_request_id"])
    strategy_id = approval["strategy_definition_id"]

    backtest_run_id = _run_backtest(session, strategy_id, symbol)
    quality_gate = run_quality_gate(session, strategy_id, actor="STEP12_17_TEST:admin")
    sensitivity = run_parameter_sensitivity(
        session, strategy_id, parameter_names=["stop_loss_rule.value"], runtime_input=_runtime_input(symbol),
        actor="STEP12_17_TEST:admin",
    )
    monte_carlo = run_monte_carlo_simulation(
        session, strategy_id, backtest_run_id=backtest_run_id, simulation_method="BOOTSTRAP_WITH_REPLACEMENT",
        actor="STEP12_17_TEST:admin", simulation_count=100,
    )
    explainability = run_generate_explainability(
        session, strategy_id, backtest_run_id=backtest_run_id,
        quality_gate_report_id=quality_gate["quality_gate_report_id"],
        parameter_sensitivity_report_id=sensitivity["parameter_sensitivity_report_id"],
        monte_carlo_report_id=monte_carlo["monte_carlo_report_id"],
        actor="STEP12_17_TEST:admin",
    )
    package = run_create_decision_package(
        session, strategy_id, explainability_report_id=explainability["explainability_report_id"],
        actor="STEP12_17_TEST:admin",
    )
    required_codes = [c["checklist_code"] for c in package["checklist_template"] if c["required"]]
    decision = run_record_human_decision(
        session, strategy_id, package["package_id"], decision_type="APPROVE_FOR_PROMOTION",
        reason_code="EVIDENCE_REVIEW_COMPLETED", reason_text="검토 완료, 승인합니다.",
        checklist_confirmations={c: True for c in required_codes}, acknowledged_warnings=["ALL"],
        actor="STEP12_17_TEST:reviewer",
    )
    commit = run_create_promotion_commit(
        session, strategy_id,
        decision_package_id=package["package_id"], human_decision_id=decision["decision_id"],
        promotion_readiness_hash=decision["promotion_readiness_hash"], commit_reason="검토 완료, 승인합니다.",
        confirmation_text="PROMOTE", actor="STEP12_17_TEST:committer",
    )
    return {"strategy_id": strategy_id, "promotion_commit_id": commit["promotion_commit_id"]}


def _create_paper_account(session, *, user_id: int = _REQUESTER_USER_ID) -> int:
    account = PaperAccount(
        user_id=user_id, account_name="STEP12_17_TEST_paper", currency_code="KRW",
        initial_cash=Decimal("10000000"), available_cash=Decimal("10000000"), is_active=True,
    )
    session.add(account)
    session.flush()
    session.commit()
    return int(account.account_id)


def _create_live_account(
    session, *, user_id: int = _REQUESTER_USER_ID, verification_status: str = "VERIFIED",
    live_order_enabled: bool = True,
) -> int:
    account = UserBrokerAccount(
        user_id=user_id, broker_code="KIWOOM", account_alias="STEP12_17_TEST_live",
        account_ref_hash="a" * 64, is_active=True, live_order_enabled=live_order_enabled,
    )
    session.add(account)
    session.flush()
    credential = BrokerAccountCredentialEntity(
        user_broker_account_id=account.user_broker_account_id, broker_code="KIWOOM",
        credential_type="BROKER_API", encrypted_payload="ciphertext", nonce_b64="nonce",
        is_active=True, verification_status=verification_status,
    )
    session.add(credential)
    session.flush()
    session.commit()
    return int(account.user_broker_account_id)


def _package_kwargs(seed: dict, *, target_account_kind: str, requested_execution_mode: str, **overrides) -> dict:
    base = dict(
        promotion_commit_id=seed["promotion_commit_id"], target_market_type="STOCK", target_broker_code="PAPER",
        target_account_kind=target_account_kind, requested_execution_mode=requested_execution_mode,
        review_note="검토 시작", actor="STEP12_17_TEST:reviewer",
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# A: Activation Review Package — PAPER happy path.
# ---------------------------------------------------------------------------


def test_paper_activation_review_package_ready(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217A")
    paper_id = _create_paper_account(session)
    result = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id,
        ),
    )
    assert result["readiness_status"] == ACTIVATION_READINESS_READY
    assert result["blocking_reason_codes"] == []

    state = session.scalar(
        select(StrategyPromotionStateEntity).where(
            StrategyPromotionStateEntity.strategy_definition_id == seed["strategy_id"]
        )
    )
    assert state.current_status == PROMOTION_STATE_ACTIVATION_REVIEW


def test_live_activation_review_package_ready_with_verified_credential(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217B")
    uba_id = _create_live_account(session)
    result = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_USER_BROKER, requested_execution_mode=EXECUTION_MODE_LIVE,
            target_broker_code="KIWOOM", target_user_broker_account_id=uba_id,
        ),
    )
    assert result["readiness_status"] == ACTIVATION_READINESS_READY
    assert "CREDENTIAL_NOT_FOUND" not in result["blocking_reason_codes"]
    assert "CREDENTIAL_REVOKED" not in result["blocking_reason_codes"]
    # 민감정보 미저장 확인.
    assert "encrypted_payload" not in result["broker_snapshot_payload"]
    assert "nonce_b64" not in result["broker_snapshot_payload"]


def test_live_activation_review_package_blocked_without_credential(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217C")
    account = UserBrokerAccount(
        user_id=_REQUESTER_USER_ID, broker_code="KIWOOM", account_alias="STEP12_17_TEST_nocred",
        account_ref_hash="b" * 64, is_active=True, live_order_enabled=True,
    )
    session.add(account)
    session.flush()
    session.commit()
    result = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_USER_BROKER, requested_execution_mode=EXECUTION_MODE_LIVE,
            target_broker_code="KIWOOM", target_user_broker_account_id=int(account.user_broker_account_id),
        ),
    )
    assert result["readiness_status"] == ACTIVATION_READINESS_BLOCKED
    assert "CREDENTIAL_NOT_FOUND" in result["blocking_reason_codes"]

    state = session.scalar(
        select(StrategyPromotionStateEntity).where(
            StrategyPromotionStateEntity.strategy_definition_id == seed["strategy_id"]
        )
    )
    assert state.current_status == PROMOTION_STATE_ACTIVATION_REVIEW  # BLOCKED여도 review 진입


def test_live_activation_review_package_blocked_with_revoked_credential(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217D")
    uba_id = _create_live_account(session, verification_status="REVOKED")
    result = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_USER_BROKER, requested_execution_mode=EXECUTION_MODE_LIVE,
            target_broker_code="KIWOOM", target_user_broker_account_id=uba_id,
        ),
    )
    assert result["readiness_status"] == ACTIVATION_READINESS_BLOCKED
    assert "CREDENTIAL_REVOKED" in result["blocking_reason_codes"]


def test_activation_review_package_blocked_market_broker_mismatch(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217E")
    paper_id = _create_paper_account(session)
    result = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id, target_market_type="CRYPTO",
        ),
    )
    assert result["readiness_status"] == ACTIVATION_READINESS_BLOCKED
    assert "UNSUPPORTED_MARKET" in result["blocking_reason_codes"]


def test_activation_review_package_account_not_found(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217F")
    result = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=999_999_999,
        ),
    )
    assert result["readiness_status"] == ACTIVATION_READINESS_BLOCKED
    assert "ACCOUNT_NOT_FOUND" in result["blocking_reason_codes"]


def test_activation_review_package_promotion_not_committed_blocks_creation(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217G")
    paper_id = _create_paper_account(session)
    run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id,
        ),
    )
    with pytest.raises(ActivationError) as exc_info:
        run_create_activation_review_package(
            session, seed["strategy_id"],
            **_package_kwargs(
                seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
                target_paper_account_id=paper_id,
            ),
        )
    assert exc_info.value.code == "ALREADY_UNDER_REVIEW"


# ---------------------------------------------------------------------------
# B: Domain 분리 — Candidate Lifecycle 불변.
# ---------------------------------------------------------------------------


def test_candidate_lifecycle_unchanged_through_full_activation_flow(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217H")
    paper_id = _create_paper_account(session)

    from stock_platform.strategy_deployment.definition_entities import StrategyDefinitionEntity

    definition = session.get(StrategyDefinitionEntity, seed["strategy_id"])
    before = session.execute(
        text("SELECT lifecycle_status FROM ai.candidate_lifecycle WHERE candidate_id = :cid"),
        {"cid": definition.candidate_id},
    ).scalar_one()

    package = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id,
        ),
    )
    checklist_codes = [c["checklist_code"] for c in build_activation_checklist_template(EXECUTION_MODE_PAPER) if c["required"]]
    decision = run_record_activation_decision(
        session, seed["strategy_id"], package["activation_review_package_id"],
        decision_type="APPROVE_ACTIVATION", reason_code="READY_FOR_ACTIVATION_COMMIT", reason_text="검토 완료",
        checklist_confirmations={c: True for c in checklist_codes}, acknowledged_warnings=["ALL"],
        actor="STEP12_17_TEST:approver",
    )
    run_create_activation_commit(
        session, seed["strategy_id"],
        activation_review_package_id=package["activation_review_package_id"],
        activation_decision_id=decision["activation_decision_id"],
        activation_readiness_hash=decision["decision_input_hash"], commit_reason="활성화 승인",
        confirmation_text="ACTIVATE", actor="STEP12_17_TEST:activator",
    )

    after = session.execute(
        text("SELECT lifecycle_status FROM ai.candidate_lifecycle WHERE candidate_id = :cid"),
        {"cid": definition.candidate_id},
    ).scalar_one()
    assert before == after == "PROMOTED"


# ---------------------------------------------------------------------------
# C: Transition Map.
# ---------------------------------------------------------------------------


def test_transition_map_only_allows_specified_edges() -> None:
    assert _can_transition_activation_state(PROMOTION_STATE_PROMOTION_COMMITTED, PROMOTION_STATE_ACTIVATION_REVIEW)
    assert _can_transition_activation_state(PROMOTION_STATE_ACTIVATION_REVIEW, PROMOTION_STATE_ACTIVATED)
    assert not _can_transition_activation_state(PROMOTION_STATE_NOT_PROMOTED, PROMOTION_STATE_ACTIVATION_REVIEW)
    assert not _can_transition_activation_state(PROMOTION_STATE_ACTIVATED, PROMOTION_STATE_PROMOTION_COMMITTED)
    assert not _can_transition_activation_state(PROMOTION_STATE_PROMOTION_COMMITTED, PROMOTION_STATE_ACTIVATED)


# ---------------------------------------------------------------------------
# D: Human Activation Decision + Activation Commit — 전체 happy path.
# ---------------------------------------------------------------------------


def _full_paper_flow(session, seed: dict) -> dict:
    paper_id = _create_paper_account(session)
    package = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id,
        ),
    )
    checklist_codes = [c["checklist_code"] for c in build_activation_checklist_template(EXECUTION_MODE_PAPER) if c["required"]]
    decision = run_record_activation_decision(
        session, seed["strategy_id"], package["activation_review_package_id"],
        decision_type="APPROVE_ACTIVATION", reason_code="READY_FOR_ACTIVATION_COMMIT", reason_text="검토 완료",
        checklist_confirmations={c: True for c in checklist_codes}, acknowledged_warnings=["ALL"],
        actor="STEP12_17_TEST:approver",
    )
    return {"package": package, "decision": decision, "paper_id": paper_id}


def test_activation_commit_success_transitions_to_activated(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217I")
    flow = _full_paper_flow(session, seed)
    result = run_create_activation_commit(
        session, seed["strategy_id"],
        activation_review_package_id=flow["package"]["activation_review_package_id"],
        activation_decision_id=flow["decision"]["activation_decision_id"],
        activation_readiness_hash=flow["decision"]["decision_input_hash"], commit_reason="활성화 승인",
        confirmation_text="  activate  ", actor="STEP12_17_TEST:activator",
    )
    assert result["activation_committed"] is True
    assert result["strategy_promotion_status"] == PROMOTION_STATE_ACTIVATED
    assert result["previous_promotion_status"] == PROMOTION_STATE_ACTIVATION_REVIEW
    assert result["deployment_status"] == "NOT_STARTED"
    assert result["runtime_status"] == "NOT_REGISTERED"
    assert result["scheduler_status"] == "NOT_REGISTERED"
    assert result["broker_connection_status"] == "NOT_STARTED"
    assert result["order_execution_status"] == "DISABLED"


def test_activation_commit_requires_exact_confirmation_text(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217J")
    flow = _full_paper_flow(session, seed)
    with pytest.raises(ActivationError) as exc_info:
        run_create_activation_commit(
            session, seed["strategy_id"],
            activation_review_package_id=flow["package"]["activation_review_package_id"],
            activation_decision_id=flow["decision"]["activation_decision_id"],
            activation_readiness_hash=flow["decision"]["decision_input_hash"], commit_reason="활성화 승인",
            confirmation_text="activate now", actor="STEP12_17_TEST:activator",
        )
    assert exc_info.value.code == "INVALID_CONFIRMATION"


def test_activation_commit_duplicate_blocked(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217K")
    flow = _full_paper_flow(session, seed)
    run_create_activation_commit(
        session, seed["strategy_id"],
        activation_review_package_id=flow["package"]["activation_review_package_id"],
        activation_decision_id=flow["decision"]["activation_decision_id"],
        activation_readiness_hash=flow["decision"]["decision_input_hash"], commit_reason="활성화 승인",
        confirmation_text="ACTIVATE", actor="STEP12_17_TEST:activator",
    )
    with pytest.raises(ActivationError) as exc_info:
        run_create_activation_commit(
            session, seed["strategy_id"],
            activation_review_package_id=flow["package"]["activation_review_package_id"],
            activation_decision_id=flow["decision"]["activation_decision_id"],
            activation_readiness_hash=flow["decision"]["decision_input_hash"], commit_reason="활성화 승인",
            confirmation_text="ACTIVATE", actor="STEP12_17_TEST:activator",
        )
    assert exc_info.value.code == "ALREADY_ACTIVATED"


def test_activation_decision_reject_and_request_changes(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217L")
    paper_id = _create_paper_account(session)
    package = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id,
        ),
    )
    decision = run_record_activation_decision(
        session, seed["strategy_id"], package["activation_review_package_id"],
        decision_type="REJECT_ACTIVATION", reason_code="ACCOUNT_NOT_ELIGIBLE", reason_text="계좌 부적격",
        checklist_confirmations={}, acknowledged_warnings=[], actor="STEP12_17_TEST:approver",
    )
    assert decision["activation_ready"] is False
    # Reject 이후에도 Promotion State는 ACTIVATION_REVIEW에 머무른다(자동 Revoke 없음).
    state = session.scalar(
        select(StrategyPromotionStateEntity).where(
            StrategyPromotionStateEntity.strategy_definition_id == seed["strategy_id"]
        )
    )
    assert state.current_status == PROMOTION_STATE_ACTIVATION_REVIEW


def test_activation_decision_incomplete_checklist_blocks_approve(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217M")
    paper_id = _create_paper_account(session)
    package = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id,
        ),
    )
    with pytest.raises(ActivationError) as exc_info:
        run_record_activation_decision(
            session, seed["strategy_id"], package["activation_review_package_id"],
            decision_type="APPROVE_ACTIVATION", reason_code="READY_FOR_ACTIVATION_COMMIT", reason_text="검토 완료",
            checklist_confirmations={}, acknowledged_warnings=["ALL"], actor="STEP12_17_TEST:approver",
        )
    assert exc_info.value.code == "INCOMPLETE_CHECKLIST"


# ---------------------------------------------------------------------------
# E: Promotion History 다중 정렬 — NOT_PROMOTED->PROMOTION_COMMITTED->
# ACTIVATION_REVIEW->ACTIVATED.
# ---------------------------------------------------------------------------


def test_promotion_history_multi_transition_ordering(session) -> None:
    from stock_platform.ai.strategy_draft_approval.promotion_commit import (
        get_promotion_commit_history,
    )

    seed = _seed_promotion_committed(session, symbol="STEP1217N")
    flow = _full_paper_flow(session, seed)
    run_create_activation_commit(
        session, seed["strategy_id"],
        activation_review_package_id=flow["package"]["activation_review_package_id"],
        activation_decision_id=flow["decision"]["activation_decision_id"],
        activation_readiness_hash=flow["decision"]["decision_input_hash"], commit_reason="활성화 승인",
        confirmation_text="ACTIVATE", actor="STEP12_17_TEST:activator",
    )
    history = get_promotion_commit_history(session, seed["strategy_id"])["history"]
    assert len(history) == 3
    transitions = [(h["previous_status"], h["new_status"]) for h in history]
    assert transitions == [
        (PROMOTION_STATE_NOT_PROMOTED, PROMOTION_STATE_PROMOTION_COMMITTED),
        (PROMOTION_STATE_PROMOTION_COMMITTED, PROMOTION_STATE_ACTIVATION_REVIEW),
        (PROMOTION_STATE_ACTIVATION_REVIEW, PROMOTION_STATE_ACTIVATED),
    ]
    occurred_ats = [h["occurred_at"] for h in history]
    assert occurred_ats == sorted(occurred_ats)
    history_ids = [h["history_id"] for h in history]
    assert history_ids == sorted(history_ids)
    # 같은 promotion_commit_id를 재사용(§ 명세 "동일 History 테이블 재사용").
    assert len({h["promotion_commit_id"] for h in history}) == 1


# ---------------------------------------------------------------------------
# F: Stale Detection.
# ---------------------------------------------------------------------------


def test_stale_package_blocks_all_three_decision_types(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217O")
    paper_id = _create_paper_account(session)
    package = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id,
        ),
    )
    # Account를 비활성화해 Stale을 유발한다(관계없는 재계산 없이 실제
    # Snapshot이 달라지는 시나리오).
    account = session.get(PaperAccount, paper_id)
    account.is_active = False
    session.commit()

    package_row = session.get(StrategyActivationReviewPackageEntity, package["activation_review_package_id"])
    stale, reasons = check_activation_package_staleness(session, package_row)
    assert stale is True

    for decision_type, reason_code in (
        ("APPROVE_ACTIVATION", "READY_FOR_ACTIVATION_COMMIT"),
        ("REQUEST_ACTIVATION_CHANGES", "ACCOUNT_CONFIGURATION_REQUIRED"),
        ("REJECT_ACTIVATION", "ACCOUNT_NOT_ELIGIBLE"),
    ):
        with pytest.raises(ActivationError) as exc_info:
            run_record_activation_decision(
                session, seed["strategy_id"], package["activation_review_package_id"],
                decision_type=decision_type, reason_code=reason_code, reason_text="검토",
                checklist_confirmations={}, acknowledged_warnings=["ALL"], actor="STEP12_17_TEST:approver2",
            )
        assert exc_info.value.code == "STALE_ACTIVATION_PACKAGE"


def test_unrelated_report_addition_is_not_stale(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217P")
    paper_id = _create_paper_account(session)
    package = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id,
        ),
    )
    package_row = session.get(StrategyActivationReviewPackageEntity, package["activation_review_package_id"])
    stale, reasons = check_activation_package_staleness(session, package_row)
    assert stale is False
    assert reasons == []


# ---------------------------------------------------------------------------
# G: Checklist — PAPER vs LIVE differ.
# ---------------------------------------------------------------------------


def test_checklist_template_differs_by_execution_mode() -> None:
    paper_codes = {c["checklist_code"] for c in build_activation_checklist_template(EXECUTION_MODE_PAPER)}
    live_codes = {c["checklist_code"] for c in build_activation_checklist_template(EXECUTION_MODE_LIVE)}
    assert "PAPER_ACCOUNT_CONFIRMED" in paper_codes
    assert "PAPER_ACCOUNT_CONFIRMED" not in live_codes
    assert "LIVE_ACCOUNT_CONFIRMED" in live_codes
    assert "LIVE_ACCOUNT_CONFIRMED" not in paper_codes
    common = paper_codes & live_codes
    assert "PROMOTION_COMMIT_CONFIRMED" in common
    assert "ACTIVATION_NOT_RUNTIME_START_CONFIRMED" in common


# ---------------------------------------------------------------------------
# H: Hash 결정성.
# ---------------------------------------------------------------------------


def test_activation_review_input_hash_deterministic() -> None:
    kwargs = dict(
        strategy_definition_id=1, promotion_commit_id=2, target_market_type="STOCK", target_broker_code="PAPER",
        target_account_kind=ACCOUNT_KIND_PAPER, target_user_broker_account_id=None, target_paper_account_id=3,
        requested_execution_mode=EXECUTION_MODE_PAPER, requested_runtime_scope_payload={"a": 1},
        requested_capital_limit=None, effective_risk_snapshot_payload={}, account_snapshot_payload={},
        broker_snapshot_payload={}, operational_snapshot_payload={}, blocking_reason_codes=[], warning_reason_codes=[],
        missing_requirement_codes=[], algorithm_version="1.0.0",
    )
    assert compute_activation_review_input_hash(**kwargs) == compute_activation_review_input_hash(**kwargs)
    changed = {**kwargs, "target_market_type": "CRYPTO"}
    assert compute_activation_review_input_hash(**kwargs) != compute_activation_review_input_hash(**changed)


def test_activation_commit_hash_deterministic() -> None:
    kwargs = dict(
        strategy_definition_id=1, definition_version=1, definition_hash="h1", executable_hash="h2",
        promotion_commit_id=2, promotion_commit_hash="h3", activation_review_package_id=3, review_input_hash="h4",
        activation_decision_id=4, decision_input_hash="h5", target_market_type="STOCK", target_broker_code="PAPER",
        target_account_kind=ACCOUNT_KIND_PAPER, target_user_broker_account_id=None, execution_mode=EXECUTION_MODE_PAPER,
        runtime_scope_hash="h6", risk_snapshot_hash="h7", account_snapshot_hash="h8", credential_snapshot_hash="h9",
        previous_promotion_status=PROMOTION_STATE_ACTIVATION_REVIEW, committed_promotion_status=PROMOTION_STATE_ACTIVATED,
        committed_by="admin", committed_at=datetime(2026, 1, 1, tzinfo=timezone.utc), confirmation_hash="h10",
        algorithm_version="1.0.0",
    )
    assert compute_activation_commit_hash(**kwargs) == compute_activation_commit_hash(**kwargs)
    changed = {**kwargs, "committed_by": "different_admin"}
    assert compute_activation_commit_hash(**kwargs) != compute_activation_commit_hash(**changed)


# ---------------------------------------------------------------------------
# I: Atomicity — 실패 주입 Rollback 검증(Activation Commit).
# ---------------------------------------------------------------------------


def _assert_activation_nothing_persisted(session, strategy_id: int) -> None:
    commit_count = session.scalar(
        select(StrategyActivationCommitEntity.activation_commit_id).where(
            StrategyActivationCommitEntity.strategy_definition_id == strategy_id
        )
    )
    assert commit_count is None
    state = session.scalar(
        select(StrategyPromotionStateEntity).where(
            StrategyPromotionStateEntity.strategy_definition_id == strategy_id
        )
    )
    if state is not None:
        assert state.current_status != PROMOTION_STATE_ACTIVATED
    history_rows = session.scalars(
        select(StrategyPromotionHistoryEntity).where(
            StrategyPromotionHistoryEntity.strategy_definition_id == strategy_id,
            StrategyPromotionHistoryEntity.new_status == PROMOTION_STATE_ACTIVATED,
        )
    ).all()
    assert len(history_rows) == 0


def test_activation_commit_atomicity_failure_after_commit_insert(session, monkeypatch) -> None:
    import stock_platform.ai.strategy_draft_approval.activation as module

    seed = _seed_promotion_committed(session, symbol="STEP1217Q")
    flow = _full_paper_flow(session, seed)

    original = module.compute_promotion_state_hash
    call_count = {"n": 0}

    def _fails_on_call(**kwargs):
        call_count["n"] += 1
        raise RuntimeError("injected failure after activation commit insert")

    monkeypatch.setattr(module, "compute_promotion_state_hash", _fails_on_call)
    with pytest.raises(RuntimeError):
        run_create_activation_commit(
            session, seed["strategy_id"],
            activation_review_package_id=flow["package"]["activation_review_package_id"],
            activation_decision_id=flow["decision"]["activation_decision_id"],
            activation_readiness_hash=flow["decision"]["decision_input_hash"], commit_reason="활성화 승인",
            confirmation_text="ACTIVATE", actor="STEP12_17_TEST:activator",
        )
    assert call_count["n"] == 1
    session.rollback()
    _assert_activation_nothing_persisted(session, seed["strategy_id"])


def test_activation_commit_atomicity_failure_after_state_transition(session, monkeypatch) -> None:
    import stock_platform.ai.strategy_draft_approval.activation as module

    seed = _seed_promotion_committed(session, symbol="STEP1217R")
    flow = _full_paper_flow(session, seed)

    def _boom(**kwargs):
        raise RuntimeError("injected failure after state transition")

    monkeypatch.setattr(module, "compute_promotion_state_event_hash", _boom)
    with pytest.raises(RuntimeError):
        run_create_activation_commit(
            session, seed["strategy_id"],
            activation_review_package_id=flow["package"]["activation_review_package_id"],
            activation_decision_id=flow["decision"]["activation_decision_id"],
            activation_readiness_hash=flow["decision"]["decision_input_hash"], commit_reason="활성화 승인",
            confirmation_text="ACTIVATE", actor="STEP12_17_TEST:activator",
        )
    session.rollback()
    _assert_activation_nothing_persisted(session, seed["strategy_id"])


def test_activation_commit_atomicity_failure_on_history_insert_flush(session, monkeypatch) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217S")
    flow = _full_paper_flow(session, seed)

    original_flush = session.flush
    call_count = {"n": 0}

    def _flush_second_call_fails(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("injected failure on history insert flush")
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(session, "flush", _flush_second_call_fails)
    with pytest.raises(RuntimeError):
        run_create_activation_commit(
            session, seed["strategy_id"],
            activation_review_package_id=flow["package"]["activation_review_package_id"],
            activation_decision_id=flow["decision"]["activation_decision_id"],
            activation_readiness_hash=flow["decision"]["decision_input_hash"], commit_reason="활성화 승인",
            confirmation_text="ACTIVATE", actor="STEP12_17_TEST:activator",
        )
    monkeypatch.undo()
    session.rollback()
    _assert_activation_nothing_persisted(session, seed["strategy_id"])


def test_activation_commit_atomicity_failure_between_flush_and_commit(session, monkeypatch) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217T")
    flow = _full_paper_flow(session, seed)

    def _commit_fails(*args, **kwargs):
        raise RuntimeError("injected failure before commit")

    monkeypatch.setattr(session, "commit", _commit_fails)
    with pytest.raises(RuntimeError):
        run_create_activation_commit(
            session, seed["strategy_id"],
            activation_review_package_id=flow["package"]["activation_review_package_id"],
            activation_decision_id=flow["decision"]["activation_decision_id"],
            activation_readiness_hash=flow["decision"]["decision_input_hash"], commit_reason="활성화 승인",
            confirmation_text="ACTIVATE", actor="STEP12_17_TEST:activator",
        )
    monkeypatch.undo()
    session.rollback()
    _assert_activation_nothing_persisted(session, seed["strategy_id"])


# ---------------------------------------------------------------------------
# J: 실제 PostgreSQL 독립 Session 동시성 검증.
# ---------------------------------------------------------------------------


def test_concurrent_activation_commit_same_strategy_only_one_succeeds(result_ids) -> None:
    Session = get_session_factory()
    setup_session = Session()
    setup_session.info["result_ids"] = result_ids
    _cleanup(setup_session)
    seed = _seed_promotion_committed(setup_session, symbol="STEP1217U")
    flow = _full_paper_flow(setup_session, seed)
    setup_session.commit()

    barrier = threading.Barrier(2)
    results: list[tuple[str, object]] = []
    lock = threading.Lock()

    def _worker() -> None:
        thread_session = Session()
        try:
            barrier.wait(timeout=10)
            try:
                result = run_create_activation_commit(
                    thread_session, seed["strategy_id"],
                    activation_review_package_id=flow["package"]["activation_review_package_id"],
                    activation_decision_id=flow["decision"]["activation_decision_id"],
                    activation_readiness_hash=flow["decision"]["decision_input_hash"], commit_reason="활성화 승인",
                    confirmation_text="ACTIVATE", actor="STEP12_17_TEST:activator",
                )
                with lock:
                    results.append(("success", result))
            except ActivationError as exc:
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
    outcomes = [r[0] for r in results]
    assert outcomes.count("success") == 1
    assert outcomes.count("error") == 1
    error_code = next(r[1] for r in results if r[0] == "error")
    assert error_code in {"ALREADY_ACTIVATED", "PROMOTION_STATE_NOT_ELIGIBLE"}

    verify_session = Session()
    try:
        all_commits = verify_session.scalars(
            select(StrategyActivationCommitEntity).where(
                StrategyActivationCommitEntity.strategy_definition_id == seed["strategy_id"]
            )
        ).all()
        assert len(all_commits) == 1
        state = verify_session.scalar(
            select(StrategyPromotionStateEntity).where(
                StrategyPromotionStateEntity.strategy_definition_id == seed["strategy_id"]
            )
        )
        assert state.current_status == PROMOTION_STATE_ACTIVATED
        activated_history = verify_session.scalars(
            select(StrategyPromotionHistoryEntity).where(
                StrategyPromotionHistoryEntity.strategy_definition_id == seed["strategy_id"],
                StrategyPromotionHistoryEntity.new_status == PROMOTION_STATE_ACTIVATED,
            )
        ).all()
        assert len(activated_history) == 1
    finally:
        _cleanup(verify_session)
        verify_session.close()


def test_concurrent_activation_commit_repeat_stability(result_ids) -> None:
    """3회 반복 실행해도 매번 정확히 1개만 성공함을 확인한다(§ "실제 병렬
    테스트를 하지 않았다면 Concurrency 완료라고 표현하지 마세요")."""
    for i in range(3):
        Session = get_session_factory()
        setup_session = Session()
        setup_session.info["result_ids"] = result_ids
        _cleanup(setup_session)
        seed = _seed_promotion_committed(setup_session, symbol=f"STEP1217V{i}")
        flow = _full_paper_flow(setup_session, seed)
        setup_session.commit()

        barrier = threading.Barrier(2)
        results: list[str] = []
        lock = threading.Lock()

        def _worker() -> None:
            thread_session = Session()
            try:
                barrier.wait(timeout=10)
                try:
                    run_create_activation_commit(
                        thread_session, seed["strategy_id"],
                        activation_review_package_id=flow["package"]["activation_review_package_id"],
                        activation_decision_id=flow["decision"]["activation_decision_id"],
                        activation_readiness_hash=flow["decision"]["decision_input_hash"], commit_reason="활성화 승인",
                        confirmation_text="ACTIVATE", actor="STEP12_17_TEST:activator",
                    )
                    with lock:
                        results.append("success")
                except ActivationError:
                    thread_session.rollback()
                    with lock:
                        results.append("error")
            finally:
                thread_session.close()

        t1 = threading.Thread(target=_worker)
        t2 = threading.Thread(target=_worker)
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)
        assert results.count("success") == 1, f"반복 {i}: success count={results.count('success')}"
        _cleanup(setup_session)
        setup_session.close()


# ---------------------------------------------------------------------------
# K: Idempotency.
# ---------------------------------------------------------------------------


def test_activation_review_package_idempotency_replay(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217W")
    paper_id = _create_paper_account(session)
    kwargs = _package_kwargs(
        seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
        target_paper_account_id=paper_id, idempotency_key="step12-17-package-replay",
    )
    first = run_create_activation_review_package(session, seed["strategy_id"], **kwargs)
    second = run_create_activation_review_package(session, seed["strategy_id"], **kwargs)
    assert second["idempotent_replay"] is True
    assert second["activation_review_package_id"] == first["activation_review_package_id"]

    packages = session.scalars(
        select(StrategyActivationReviewPackageEntity).where(
            StrategyActivationReviewPackageEntity.strategy_definition_id == seed["strategy_id"]
        )
    ).all()
    assert len(packages) == 1


def test_activation_commit_idempotency_replay(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217X")
    flow = _full_paper_flow(session, seed)
    kwargs = dict(
        activation_review_package_id=flow["package"]["activation_review_package_id"],
        activation_decision_id=flow["decision"]["activation_decision_id"],
        activation_readiness_hash=flow["decision"]["decision_input_hash"], commit_reason="활성화 승인",
        confirmation_text="ACTIVATE", actor="STEP12_17_TEST:activator", idempotency_key="step12-17-commit-replay",
    )
    first = run_create_activation_commit(session, seed["strategy_id"], **kwargs)
    second = run_create_activation_commit(session, seed["strategy_id"], **kwargs)
    assert second["idempotent_replay"] is True
    assert second["activation_commit_id"] == first["activation_commit_id"]

    commits = session.scalars(
        select(StrategyActivationCommitEntity).where(
            StrategyActivationCommitEntity.strategy_definition_id == seed["strategy_id"]
        )
    ).all()
    assert len(commits) == 1


# ---------------------------------------------------------------------------
# L: API — Cross-Strategy 404.
# ---------------------------------------------------------------------------


def test_get_activation_review_package_cross_strategy_404(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217Y")
    paper_id = _create_paper_account(session)
    package = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id,
        ),
    )
    with pytest.raises(ActivationError) as exc_info:
        get_activation_review_package(session, package["activation_review_package_id"], strategy_definition_id=999_999)
    assert exc_info.value.code == "NOT_FOUND"


def test_activation_status_reflects_committed_state(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217Z")
    flow = _full_paper_flow(session, seed)
    before = get_activation_status(session, seed["strategy_id"])
    assert before["activation_committed"] is False
    run_create_activation_commit(
        session, seed["strategy_id"],
        activation_review_package_id=flow["package"]["activation_review_package_id"],
        activation_decision_id=flow["decision"]["activation_decision_id"],
        activation_readiness_hash=flow["decision"]["decision_input_hash"], commit_reason="활성화 승인",
        confirmation_text="ACTIVATE", actor="STEP12_17_TEST:activator",
    )
    after = get_activation_status(session, seed["strategy_id"])
    assert after["activation_committed"] is True
    assert after["strategy_promotion_status"] == PROMOTION_STATE_ACTIVATED
    assert after["deployment_status"] == "NOT_STARTED"
    assert after["runtime_status"] == "NOT_REGISTERED"


# ---------------------------------------------------------------------------
# M: Regression — STEP12-16R/16.
# ---------------------------------------------------------------------------


def test_step12_16r_regression_promotion_commit_still_reaches_promotion_committed(session) -> None:
    seed = _seed_promotion_committed(session, symbol="STEP1217AA")
    state = session.scalar(
        select(StrategyPromotionStateEntity).where(
            StrategyPromotionStateEntity.strategy_definition_id == seed["strategy_id"]
        )
    )
    assert state.current_status == PROMOTION_STATE_PROMOTION_COMMITTED
    assert state.status_version == 1


# ---------------------------------------------------------------------------
# N: STEP12-18 선행 — STEP12-17 제한사항 보완 테스트.
# ---------------------------------------------------------------------------


def test_live_risk_fail_closed_blocks_without_explicit_system_risk_setting(session, monkeypatch) -> None:
    """§ 보완(1) — LIVE Risk Fail Closed. Resolver가 실제로는 System Risk
    Setting 행 없이 코드 하드코딩 permissive 기본값만 반환하는 상황을
    monkeypatch로 재현한다(개발 DB에는 이미 System Risk Setting 행이 있어
    자연 상태로는 이 경로를 재현할 수 없다)."""
    import stock_platform.ai.strategy_draft_approval.activation as module
    from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicyResolver

    seed = _seed_promotion_committed(session, symbol="STEP1217AB")
    uba_id = _create_live_account(session)

    original_resolve = ResolvedRiskPolicyResolver.resolve

    def _fake_resolve(self, **kwargs):
        policy = original_resolve(self, **kwargs)
        object.__setattr__(policy, "source_layers", ("code_fallback",))
        return policy

    monkeypatch.setattr(ResolvedRiskPolicyResolver, "resolve", _fake_resolve)
    result = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_USER_BROKER, requested_execution_mode=EXECUTION_MODE_LIVE,
            target_broker_code="KIWOOM", target_user_broker_account_id=uba_id,
        ),
    )
    assert result["readiness_status"] == ACTIVATION_READINESS_BLOCKED
    assert "RISK_SETTING_NOT_FOUND" in result["blocking_reason_codes"]
    assert result["effective_risk_snapshot_payload"]["effective_risk_explicit"] is False


def test_paper_uses_safe_paper_default_when_risk_not_explicit(session, monkeypatch) -> None:
    """PAPER는 명시적 System Risk Setting이 없어도 차단되지 않고 보수적
    고정값(SAFE_PAPER_DEFAULT)으로 안전하게 대체된다."""
    from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicyResolver

    seed = _seed_promotion_committed(session, symbol="STEP1217AC")
    paper_id = _create_paper_account(session)

    original_resolve = ResolvedRiskPolicyResolver.resolve

    def _fake_resolve(self, **kwargs):
        policy = original_resolve(self, **kwargs)
        object.__setattr__(policy, "source_layers", ("code_fallback",))
        return policy

    monkeypatch.setattr(ResolvedRiskPolicyResolver, "resolve", _fake_resolve)
    result = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id,
        ),
    )
    assert result["readiness_status"] == ACTIVATION_READINESS_READY
    assert result["effective_risk_snapshot_payload"]["risk_source"] == "SAFE_PAPER_DEFAULT"
    assert result["effective_risk_snapshot_payload"]["effective_risk_explicit"] is False


def test_live_full_activation_flow_end_to_end(session) -> None:
    """§ 보완(2) — LIVE Review Package -> Checklist -> APPROVE_ACTIVATION
    -> ACTIVATE Commit -> ACTIVATED 전체 경로를 실측한다."""
    seed = _seed_promotion_committed(session, symbol="STEP1217AD")
    uba_id = _create_live_account(session)
    package = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_USER_BROKER, requested_execution_mode=EXECUTION_MODE_LIVE,
            target_broker_code="KIWOOM", target_user_broker_account_id=uba_id,
        ),
    )
    assert package["readiness_status"] == ACTIVATION_READINESS_READY
    checklist_codes = [c["checklist_code"] for c in build_activation_checklist_template(EXECUTION_MODE_LIVE) if c["required"]]
    decision = run_record_activation_decision(
        session, seed["strategy_id"], package["activation_review_package_id"],
        decision_type="APPROVE_ACTIVATION", reason_code="LIVE_SAFETY_REVIEW_COMPLETED", reason_text="LIVE 검토 완료",
        checklist_confirmations={c: True for c in checklist_codes}, acknowledged_warnings=["ALL"],
        actor="STEP12_17_TEST:live_approver",
    )
    assert decision["activation_ready"] is True
    result = run_create_activation_commit(
        session, seed["strategy_id"],
        activation_review_package_id=package["activation_review_package_id"],
        activation_decision_id=decision["activation_decision_id"],
        activation_readiness_hash=decision["decision_input_hash"], commit_reason="LIVE 활성화 승인",
        confirmation_text="ACTIVATE", actor="STEP12_17_TEST:live_activator",
    )
    assert result["strategy_promotion_status"] == PROMOTION_STATE_ACTIVATED
    assert result["execution_mode"] == EXECUTION_MODE_LIVE


def test_live_credential_revoked_blocks_commit_via_stale(session) -> None:
    """§ 보완(2) 추가 차단 — Package 생성 후 Credential이 REVOKED로
    바뀌면 Decision/Commit 모두 Stale로 차단돼야 한다."""
    seed = _seed_promotion_committed(session, symbol="STEP1217AE")
    uba_id = _create_live_account(session)
    package = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_USER_BROKER, requested_execution_mode=EXECUTION_MODE_LIVE,
            target_broker_code="KIWOOM", target_user_broker_account_id=uba_id,
        ),
    )
    credential = session.scalar(
        select(BrokerAccountCredentialEntity).where(BrokerAccountCredentialEntity.user_broker_account_id == uba_id)
    )
    credential.verification_status = "REVOKED"
    session.commit()

    with pytest.raises(ActivationError) as exc_info:
        run_record_activation_decision(
            session, seed["strategy_id"], package["activation_review_package_id"],
            decision_type="APPROVE_ACTIVATION", reason_code="LIVE_SAFETY_REVIEW_COMPLETED", reason_text="검토",
            checklist_confirmations={}, acknowledged_warnings=["ALL"], actor="STEP12_17_TEST:live_approver2",
        )
    assert exc_info.value.code == "STALE_ACTIVATION_PACKAGE"


def test_live_trading_disabled_blocks_package(session, monkeypatch) -> None:
    from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicyResolver

    seed = _seed_promotion_committed(session, symbol="STEP1217AF")
    uba_id = _create_live_account(session)

    original_resolve = ResolvedRiskPolicyResolver.resolve

    def _fake_resolve(self, **kwargs):
        policy = original_resolve(self, **kwargs)
        object.__setattr__(policy, "auto_trading_enabled", False)
        return policy

    monkeypatch.setattr(ResolvedRiskPolicyResolver, "resolve", _fake_resolve)
    result = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_USER_BROKER, requested_execution_mode=EXECUTION_MODE_LIVE,
            target_broker_code="KIWOOM", target_user_broker_account_id=uba_id,
        ),
    )
    assert "TRADING_DISABLED" in result["blocking_reason_codes"]


def test_live_order_disabled_warns_package(session) -> None:
    """Strategy lifecycle activation은 LIVE OFF여도 review 가능 — 실주문은 별도 gate."""
    seed = _seed_promotion_committed(session, symbol="STEP1217AG")
    uba_id = _create_live_account(session, live_order_enabled=False)
    result = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_USER_BROKER, requested_execution_mode=EXECUTION_MODE_LIVE,
            target_broker_code="KIWOOM", target_user_broker_account_id=uba_id,
        ),
    )
    assert result["readiness_status"] == ACTIVATION_READINESS_READY
    assert "LIVE_ORDER_DISABLED" in result["warning_reason_codes"]
    assert "LIVE_ORDER_DISABLED" not in result["blocking_reason_codes"]


def test_kill_switch_active_blocks_package(session, monkeypatch) -> None:
    import stock_platform.ai.strategy_draft_approval.activation as module

    seed = _seed_promotion_committed(session, symbol="STEP1217AH")
    paper_id = _create_paper_account(session)
    monkeypatch.setattr(module.KillSwitchService, "is_active_for_scopes", lambda self, codes: True)
    result = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id,
        ),
    )
    assert "KILL_SWITCH_ACTIVE" in result["blocking_reason_codes"]


def test_recovery_conflict_blocks_package(session, monkeypatch) -> None:
    import stock_platform.ai.strategy_draft_approval.activation as module

    seed = _seed_promotion_committed(session, symbol="STEP1217AI")
    paper_id = _create_paper_account(session)
    monkeypatch.setattr(module.RecoveryAccountLockService, "is_trading_paused", lambda self, **kwargs: True)
    result = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id,
        ),
    )
    assert "RECOVERY_CONFLICT" in result["blocking_reason_codes"]


def test_account_paused_blocks_package(session, monkeypatch) -> None:
    from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicyResolver

    seed = _seed_promotion_committed(session, symbol="STEP1217AJ")
    paper_id = _create_paper_account(session)

    original_resolve = ResolvedRiskPolicyResolver.resolve

    def _fake_resolve(self, **kwargs):
        policy = original_resolve(self, **kwargs)
        object.__setattr__(policy, "account_paused", True)
        return policy

    monkeypatch.setattr(ResolvedRiskPolicyResolver, "resolve", _fake_resolve)
    result = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id,
        ),
    )
    assert "ACCOUNT_PAUSED" in result["blocking_reason_codes"]


def test_activation_decision_idempotency_replay_and_conflict(session) -> None:
    """§ 보완(3) — 같은 Key+같은 입력은 Replay, 같은 Key+다른 입력은
    IDEMPOTENCY_CONFLICT여야 하며 Replay는 중복 Decision/재전이/History
    중복을 만들지 않아야 한다."""
    seed = _seed_promotion_committed(session, symbol="STEP1217AK")
    paper_id = _create_paper_account(session)
    package = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id,
        ),
    )
    checklist_codes = [c["checklist_code"] for c in build_activation_checklist_template(EXECUTION_MODE_PAPER) if c["required"]]

    first = run_record_activation_decision(
        session, seed["strategy_id"], package["activation_review_package_id"],
        decision_type="APPROVE_ACTIVATION", reason_code="READY_FOR_ACTIVATION_COMMIT", reason_text="검토 완료",
        checklist_confirmations={c: True for c in checklist_codes}, acknowledged_warnings=["ALL"],
        actor="STEP12_17_TEST:idem_approver", idempotency_key="step12-17-decision-replay",
    )
    # 같은 Package에는 최종 Decision이 1개만 허용되므로(UNIQUE), 동일 Key로
    # 재요청했을 때 진짜 Replay 경로(기존 행 재조회)를 타는지 확인한다.
    second = run_record_activation_decision(
        session, seed["strategy_id"], package["activation_review_package_id"],
        decision_type="APPROVE_ACTIVATION", reason_code="READY_FOR_ACTIVATION_COMMIT", reason_text="검토 완료",
        checklist_confirmations={c: True for c in checklist_codes}, acknowledged_warnings=["ALL"],
        actor="STEP12_17_TEST:idem_approver", idempotency_key="step12-17-decision-replay",
    )
    assert second["idempotent_replay"] is True
    assert second["activation_decision_id"] == first["activation_decision_id"]

    decisions = session.scalars(
        select(StrategyActivationDecisionEntity).where(
            StrategyActivationDecisionEntity.activation_review_package_id == package["activation_review_package_id"]
        )
    ).all()
    assert len(decisions) == 1

    with pytest.raises(ActivationError) as exc_info:
        run_record_activation_decision(
            session, seed["strategy_id"], package["activation_review_package_id"],
            decision_type="REJECT_ACTIVATION", reason_code="ACCOUNT_NOT_ELIGIBLE", reason_text="다른 입력",
            checklist_confirmations={}, acknowledged_warnings=[],
            actor="STEP12_17_TEST:idem_approver", idempotency_key="step12-17-decision-replay",
        )
    assert exc_info.value.code == "IDEMPOTENCY_CONFLICT"


def test_account_ownership_mismatch_blocks_package(session) -> None:
    """§ 보완(4) — USER 소유 Strategy는 다른 사용자의 계좌를 대상으로 할
    수 없다(Cross-user Runtime 등록 금지)."""
    from stock_platform.strategy_deployment.definition_entities import StrategyDefinitionEntity

    seed = _seed_promotion_committed(session, symbol="STEP1217AL")
    definition = session.get(StrategyDefinitionEntity, seed["strategy_id"])
    definition.owner_type = "USER"
    definition.user_id = _REQUESTER_USER_ID
    session.commit()

    other_user_paper_id = _create_paper_account(session, user_id=_REVIEWER_USER_ID)
    result = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=other_user_paper_id,
        ),
    )
    assert result["readiness_status"] == ACTIVATION_READINESS_BLOCKED
    assert "ACCOUNT_OWNERSHIP_MISMATCH" in result["blocking_reason_codes"]


def test_account_strategy_link_conflict_code(session) -> None:
    """§ 보완(5) — 다른 Strategy가 같은 Account에 활성 Link로 묶여 있으면
    ACCOUNT_STRATEGY_LINK_CONFLICT로 차단한다. 동일 Strategy+Account Link는 허용."""
    from stock_platform.strategy_deployment.definition_entities import AccountStrategyLinkEntity

    seed = _seed_promotion_committed(session, symbol="STEP1217AM")
    other_seed = _seed_promotion_committed(session, symbol="STEP1217AM2", result_id_index=1)
    paper_id = _create_paper_account(session)
    link = AccountStrategyLinkEntity(
        strategy_id=other_seed["strategy_id"], user_id=_REQUESTER_USER_ID, paper_account_id=paper_id,
        user_broker_account_id=None, is_active=True, created_by="STEP12_17_TEST:setup",
    )
    session.add(link)
    session.commit()

    result = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id,
        ),
    )
    assert result["readiness_status"] == ACTIVATION_READINESS_BLOCKED
    assert "ACCOUNT_STRATEGY_LINK_CONFLICT" in result["blocking_reason_codes"]


def test_matching_account_strategy_link_allows_package(session) -> None:
    """동일 Strategy+Account의 활성 Link는 Activation positive evidence."""
    from stock_platform.strategy_deployment.definition_entities import AccountStrategyLinkEntity

    seed = _seed_promotion_committed(session, symbol="STEP1217AM3")
    paper_id = _create_paper_account(session)
    link = AccountStrategyLinkEntity(
        strategy_id=seed["strategy_id"], user_id=_REQUESTER_USER_ID, paper_account_id=paper_id,
        user_broker_account_id=None, is_active=True, created_by="STEP12_17_TEST:setup",
    )
    session.add(link)
    session.commit()

    result = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id,
        ),
    )
    assert result["readiness_status"] == ACTIVATION_READINESS_READY
    assert "ACCOUNT_STRATEGY_LINK_CONFLICT" not in result["blocking_reason_codes"]


def test_package_status_fields_separated_and_not_immediately_stale(session) -> None:
    """§ 보완(7) — created_readiness_status/current_effective_status/
    stale/decided/activation_committed가 API 응답에서 분리돼 있고, Package
    생성이 유발한 PROMOTION_COMMITTED->ACTIVATION_REVIEW 전이 자체는
    Package를 즉시 Stale로 만들지 않는다."""
    seed = _seed_promotion_committed(session, symbol="STEP1217AN")
    paper_id = _create_paper_account(session)
    package = run_create_activation_review_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_PAPER, requested_execution_mode=EXECUTION_MODE_PAPER,
            target_paper_account_id=paper_id,
        ),
    )
    fetched = get_activation_review_package(session, package["activation_review_package_id"])
    assert fetched["created_readiness_status"] == ACTIVATION_READINESS_READY
    assert fetched["current_effective_status"] == ACTIVATION_READINESS_READY
    assert fetched["stale"] is False
    assert fetched["decided"] is False
    assert fetched["activation_committed"] is False
