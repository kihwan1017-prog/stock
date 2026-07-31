"""STEP 12-18 — Runtime Registration Review Package & Commit.

ACTIVATED 상태인 Strategy Definition을 대상으로 계좌/시장/브로커/리스크/
운영 준비 상태를 재검증하고, 관리자의 명시적 Runtime Registration
Commit으로 Runtime Registry에 **비실행**(enabled=false, running=false)
상태로만 등록한다. Runtime 시작, Scheduler 등록, Broker 연결/로그인,
실시간 시세 구독, Signal 계산, 주문 생성/전송은 전혀 수행하지 않는다."""

from __future__ import annotations

import threading
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from stock_platform.ai.strategy_draft.service import StrategyDraftService
from stock_platform.ai.strategy_draft_approval.activation import (
    build_activation_checklist_template,
    run_create_activation_commit,
    run_create_activation_review_package,
    run_record_activation_decision,
)
from stock_platform.ai.strategy_draft_approval.activation_entities import (
    ACCOUNT_KIND_PAPER,
    ACCOUNT_KIND_USER_BROKER,
    EXECUTION_MODE_LIVE,
    EXECUTION_MODE_PAPER,
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
from stock_platform.ai.strategy_draft_approval.quality_gate import run_quality_gate
from stock_platform.ai.strategy_draft_approval.runtime_registration import (
    RuntimeRegistrationError,
    build_runtime_registration_checklist_template,
    check_runtime_registration_package_staleness,
    compute_registration_commit_hash,
    compute_registration_decision_input_hash,
    compute_registration_input_hash,
    compute_runtime_scope_hash,
    get_runtime_registration_history,
    get_runtime_registration_package,
    get_runtime_registration_scopes,
    get_runtime_registration_status,
    run_create_runtime_registration_commit,
    run_create_runtime_registration_package,
    run_record_runtime_registration_decision,
)
from stock_platform.ai.strategy_draft_approval.runtime_registration_entities import (
    REGISTRATION_READINESS_BLOCKED,
    REGISTRATION_READINESS_READY,
    StrategyRuntimeRegistrationCommitEntity,
    StrategyRuntimeRegistrationDecisionEntity,
    StrategyRuntimeRegistrationHistoryEntity,
    StrategyRuntimeRegistrationPackageEntity,
    StrategyRuntimeRegistryEntity,
)
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalService,
)
from stock_platform.ai.strategy_request.service import StrategyRequestService
from stock_platform.api.main import app  # noqa: F401  — 전체 모델 등록 부작용.
from stock_platform.database.session import get_session_factory
from stock_platform.strategy_deployment.definition_entities import (
    AccountStrategyLinkEntity,
    StrategyDefinitionEntity,
)
from stock_platform.broker.credential_entities import BrokerAccountCredentialEntity
from stock_platform.trading.account_models import PaperAccount, UserBrokerAccount

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_MARKER = "STEP12_18_TEST"
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
    "DELETE FROM trading.strategy_runtime_registration_history WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_runtime_registry WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_runtime_registration_commit WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_runtime_registration_decision WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_runtime_registration_package WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.account_strategy_link WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_deployment WHERE strategy_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    # strategy_id FK는 ondelete=SET NULL이므로, Strategy Definition이
    # 먼저 삭제되면 symbol로만 식별 가능한 고아 행이 남을 수 있다 —
    # 이 테스트 전용 symbol 패턴으로도 별도 정리한다.
    "DELETE FROM trading.strategy_deployment WHERE symbol LIKE 'STEP1218%'",
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
    "DELETE FROM trading.paper_account WHERE account_name LIKE 'STEP12_18_TEST%'",
    "DELETE FROM trading.broker_account_credential WHERE user_broker_account_id IN "
    "(SELECT user_broker_account_id FROM trading.user_broker_account WHERE account_alias LIKE 'STEP12_18_TEST%')",
    "DELETE FROM trading.user_broker_account WHERE account_alias LIKE 'STEP12_18_TEST%'",
    "DELETE FROM market.price_daily WHERE instrument_id IN "
    "(SELECT instrument_id FROM market.instrument WHERE symbol LIKE 'STEP1218%')",
    "DELETE FROM market.instrument WHERE symbol LIKE 'STEP1218%'",
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
            VALUES ('STOCK', :exchange, :symbol, 'STEP12-18 Test')
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
                VALUES (:iid, :td, :c, :c, :c, :c, 1000, 'STEP12_18_TEST')
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
        session, strategy_definition_id, runtime_input=_runtime_input(symbol), actor="STEP12_18_TEST:admin",
    )
    return result["backtest_run_id"]


def _create_paper_account(session, *, user_id: int = _REQUESTER_USER_ID, name_suffix: str = "") -> int:
    account = PaperAccount(
        user_id=user_id, account_name=f"STEP12_18_TEST_paper{name_suffix}", currency_code="KRW",
        initial_cash=Decimal("10000000"), available_cash=Decimal("10000000"), is_active=True,
    )
    session.add(account)
    session.flush()
    session.commit()
    return int(account.account_id)


def _create_live_account(
    session, *, user_id: int = _REQUESTER_USER_ID, verification_status: str = "VERIFIED",
    live_order_enabled: bool = True, alias_suffix: str = "",
) -> int:
    account = UserBrokerAccount(
        user_id=user_id, broker_code="KIWOOM", account_alias=f"STEP12_18_TEST_live{alias_suffix}",
        account_ref_hash="c" * 64, is_active=True, live_order_enabled=live_order_enabled,
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


def _seed_activated(session, *, symbol: str) -> dict:
    """PROMOTION_COMMITTED -> Activation Review(PAPER) -> APPROVE -> ACTIVATED까지."""
    ids = session.info["result_ids"]
    _seed_prices(session, symbol, _triangle_wave(150, period=30), start=date(2024, 1, 1))

    req = _create_approved_request(session, result_id=ids[0])
    approval = _approve(session, req["strategy_request_id"])
    strategy_id = approval["strategy_definition_id"]

    backtest_run_id = _run_backtest(session, strategy_id, symbol)
    quality_gate = run_quality_gate(session, strategy_id, actor="STEP12_18_TEST:admin")
    sensitivity = run_parameter_sensitivity(
        session, strategy_id, parameter_names=["stop_loss_rule.value"], runtime_input=_runtime_input(symbol),
        actor="STEP12_18_TEST:admin",
    )
    monte_carlo = run_monte_carlo_simulation(
        session, strategy_id, backtest_run_id=backtest_run_id, simulation_method="BOOTSTRAP_WITH_REPLACEMENT",
        actor="STEP12_18_TEST:admin", simulation_count=100,
    )
    explainability = run_generate_explainability(
        session, strategy_id, backtest_run_id=backtest_run_id,
        quality_gate_report_id=quality_gate["quality_gate_report_id"],
        parameter_sensitivity_report_id=sensitivity["parameter_sensitivity_report_id"],
        monte_carlo_report_id=monte_carlo["monte_carlo_report_id"],
        actor="STEP12_18_TEST:admin",
    )
    package = run_create_decision_package(
        session, strategy_id, explainability_report_id=explainability["explainability_report_id"],
        actor="STEP12_18_TEST:admin",
    )
    required_codes = [c["checklist_code"] for c in package["checklist_template"] if c["required"]]
    decision = run_record_human_decision(
        session, strategy_id, package["package_id"], decision_type="APPROVE_FOR_PROMOTION",
        reason_code="EVIDENCE_REVIEW_COMPLETED", reason_text="검토 완료, 승인합니다.",
        checklist_confirmations={c: True for c in required_codes}, acknowledged_warnings=["ALL"],
        actor="STEP12_18_TEST:reviewer",
    )
    commit = run_create_promotion_commit(
        session, strategy_id,
        decision_package_id=package["package_id"], human_decision_id=decision["decision_id"],
        promotion_readiness_hash=decision["promotion_readiness_hash"], commit_reason="검토 완료, 승인합니다.",
        confirmation_text="PROMOTE", actor="STEP12_18_TEST:committer",
    )

    paper_id = _create_paper_account(session)
    activation_package = run_create_activation_review_package(
        session, strategy_id,
        promotion_commit_id=commit["promotion_commit_id"], target_market_type="STOCK", target_broker_code="PAPER",
        target_account_kind=ACCOUNT_KIND_PAPER, target_paper_account_id=paper_id,
        requested_execution_mode=EXECUTION_MODE_PAPER, review_note="검토 시작", actor="STEP12_18_TEST:reviewer",
    )
    checklist_codes = [c["checklist_code"] for c in build_activation_checklist_template(EXECUTION_MODE_PAPER) if c["required"]]
    activation_decision = run_record_activation_decision(
        session, strategy_id, activation_package["activation_review_package_id"],
        decision_type="APPROVE_ACTIVATION", reason_code="READY_FOR_ACTIVATION_COMMIT", reason_text="검토 완료",
        checklist_confirmations={c: True for c in checklist_codes}, acknowledged_warnings=["ALL"],
        actor="STEP12_18_TEST:approver",
    )
    activation_commit = run_create_activation_commit(
        session, strategy_id,
        activation_review_package_id=activation_package["activation_review_package_id"],
        activation_decision_id=activation_decision["activation_decision_id"],
        activation_readiness_hash=activation_decision["decision_input_hash"], commit_reason="활성화 승인",
        confirmation_text="ACTIVATE", actor="STEP12_18_TEST:activator",
    )
    return {
        "strategy_id": strategy_id, "paper_id": paper_id,
        "activation_commit_id": activation_commit["activation_commit_id"],
        "activation_decision_id": activation_decision["activation_decision_id"],
    }


def _package_kwargs(seed: dict, **overrides) -> dict:
    base = dict(
        activation_commit_id=seed["activation_commit_id"], activation_decision_id=seed["activation_decision_id"],
        target_account_kind=ACCOUNT_KIND_PAPER, target_paper_account_id=seed["paper_id"],
        target_market_type="STOCK", target_broker_code="PAPER", execution_mode=EXECUTION_MODE_PAPER,
        actor="STEP12_18_TEST:reviewer",
    )
    base.update(overrides)
    return base


def _full_flow(session, seed: dict, **package_overrides) -> dict:
    package = run_create_runtime_registration_package(session, seed["strategy_id"], **_package_kwargs(seed, **package_overrides))
    checklist_codes = [
        c["checklist_code"] for c in build_runtime_registration_checklist_template(package["execution_mode"]) if c["required"]
    ]
    decision = run_record_runtime_registration_decision(
        session, seed["strategy_id"], package["runtime_registration_package_id"],
        decision_type="APPROVE_RUNTIME_REGISTRATION", reason_code="READY_FOR_RUNTIME_REGISTRATION_COMMIT",
        reason_text="등록 검토 완료", checklist_confirmations={c: True for c in checklist_codes},
        acknowledged_warnings=["ALL"], actor="STEP12_18_TEST:reg_approver",
    )
    return {"package": package, "decision": decision}


def _full_flow_and_commit(session, seed: dict, *, actor_suffix: str = "", **package_overrides) -> dict:
    flow = _full_flow(session, seed, **package_overrides)
    commit = run_create_runtime_registration_commit(
        session, seed["strategy_id"],
        runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
        runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
        registration_input_hash=flow["package"]["registration_input_hash"],
        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
        confirmation_text="REGISTER", actor=f"STEP12_18_TEST:registrar{actor_suffix}",
    )
    return {**flow, "commit": commit}


# ---------------------------------------------------------------------------
# A: Runtime Registration Package — happy path & 게이팅.
# ---------------------------------------------------------------------------


def test_runtime_registration_package_ready(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218A")
    result = run_create_runtime_registration_package(session, seed["strategy_id"], **_package_kwargs(seed))
    assert result["registration_readiness_status"] == REGISTRATION_READINESS_READY
    assert result["blocking_reason_codes"] == []


def test_package_blocked_when_strategy_not_activated(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218B")
    # ACTIVATION_COMMIT_NOT_FOUND 시나리오 — 존재하지 않는 Activation Commit.
    with pytest.raises(RuntimeRegistrationError) as exc_info:
        run_create_runtime_registration_package(
            session, seed["strategy_id"], **_package_kwargs(seed, activation_commit_id=999_999_999),
        )
    assert exc_info.value.code == "ACTIVATION_COMMIT_NOT_FOUND"


def test_package_account_not_found(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218C")
    result = run_create_runtime_registration_package(
        session, seed["strategy_id"], **_package_kwargs(seed, target_paper_account_id=999_999_999),
    )
    assert result["registration_readiness_status"] == REGISTRATION_READINESS_BLOCKED
    assert "ACCOUNT_NOT_FOUND" in result["blocking_reason_codes"]


def test_package_market_broker_mismatch(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218D")
    result = run_create_runtime_registration_package(
        session, seed["strategy_id"], **_package_kwargs(seed, target_market_type="CRYPTO"),
    )
    assert result["registration_readiness_status"] == REGISTRATION_READINESS_BLOCKED
    assert "UNSUPPORTED_MARKET" in result["blocking_reason_codes"]


def test_package_no_sensitive_credential_data(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218E")
    result = run_create_runtime_registration_package(session, seed["strategy_id"], **_package_kwargs(seed))
    assert "encrypted_payload" not in result["credential_snapshot_payload"]
    assert "nonce_b64" not in result["credential_snapshot_payload"]


# ---------------------------------------------------------------------------
# B: Runtime Scope Conflict 세분화.
# ---------------------------------------------------------------------------


def test_runtime_scope_already_registered_after_first_commit(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218F")
    flow = _full_flow(session, seed)
    run_create_runtime_registration_commit(
        session, seed["strategy_id"],
        runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
        runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
        registration_input_hash=flow["package"]["registration_input_hash"],
        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
        confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
    )
    # 동일 Strategy에 새 Package를 다시 생성하면(같은 Runtime Scope) 이미
    # Registry가 존재하므로 RUNTIME_SCOPE_ALREADY_REGISTERED가 감지돼야
    # 한다.
    second_package = run_create_runtime_registration_package(session, seed["strategy_id"], **_package_kwargs(seed))
    assert "RUNTIME_SCOPE_ALREADY_REGISTERED" in second_package["blocking_reason_codes"]


def test_account_strategy_link_created_inactive_after_commit(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218G")
    flow = _full_flow(session, seed)
    run_create_runtime_registration_commit(
        session, seed["strategy_id"],
        runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
        runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
        registration_input_hash=flow["package"]["registration_input_hash"],
        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
        confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
    )
    link = session.scalar(
        select(AccountStrategyLinkEntity).where(
            AccountStrategyLinkEntity.strategy_id == seed["strategy_id"],
            AccountStrategyLinkEntity.paper_account_id == seed["paper_id"],
        )
    )
    assert link is not None
    assert link.is_active is False  # 자동 활성화 금지.


# ---------------------------------------------------------------------------
# C: Registration Commit — 성공, Registry 비실행 확인.
# ---------------------------------------------------------------------------


def test_registration_commit_success_creates_non_executing_registry(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218H")
    flow = _full_flow(session, seed)
    result = run_create_runtime_registration_commit(
        session, seed["strategy_id"],
        runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
        runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
        registration_input_hash=flow["package"]["registration_input_hash"],
        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
        confirmation_text="  register  ", actor="STEP12_18_TEST:registrar",
    )
    assert result["registration_status"] == "REGISTERED"
    assert result["registry_enabled"] is False
    assert result["registry_running"] is False
    assert result["runtime_status"] == "NOT_STARTED"
    assert result["scheduler_status"] == "NOT_REGISTERED"
    assert result["broker_connection_status"] == "NOT_STARTED"
    assert result["market_data_status"] == "NOT_SUBSCRIBED"
    assert result["signal_status"] == "DISABLED"
    assert result["order_execution_status"] == "DISABLED"

    registry = session.scalar(
        select(StrategyRuntimeRegistryEntity).where(
            StrategyRuntimeRegistryEntity.strategy_definition_id == seed["strategy_id"]
        )
    )
    assert registry is not None
    assert registry.enabled is False
    assert registry.running is False
    assert registry.status == "REGISTERED"


def test_registration_commit_requires_exact_confirmation(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218I")
    flow = _full_flow(session, seed)
    with pytest.raises(RuntimeRegistrationError) as exc_info:
        run_create_runtime_registration_commit(
            session, seed["strategy_id"],
            runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
            runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
            registration_input_hash=flow["package"]["registration_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
            confirmation_text="register now", actor="STEP12_18_TEST:registrar",
        )
    assert exc_info.value.code == "INVALID_CONFIRMATION"


def test_registration_commit_duplicate_blocked(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218J")
    flow = _full_flow(session, seed)
    run_create_runtime_registration_commit(
        session, seed["strategy_id"],
        runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
        runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
        registration_input_hash=flow["package"]["registration_input_hash"],
        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
        confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
    )
    with pytest.raises(RuntimeRegistrationError) as exc_info:
        run_create_runtime_registration_commit(
            session, seed["strategy_id"],
            runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
            runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
            registration_input_hash=flow["package"]["registration_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
            confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
        )
    assert exc_info.value.code == "ALREADY_REGISTERED"


# ---------------------------------------------------------------------------
# D: Decision — Checklist/Reason Code/Stale.
# ---------------------------------------------------------------------------


def test_decision_incomplete_checklist_blocks_approve(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218K")
    package = run_create_runtime_registration_package(session, seed["strategy_id"], **_package_kwargs(seed))
    with pytest.raises(RuntimeRegistrationError) as exc_info:
        run_record_runtime_registration_decision(
            session, seed["strategy_id"], package["runtime_registration_package_id"],
            decision_type="APPROVE_RUNTIME_REGISTRATION", reason_code="READY_FOR_RUNTIME_REGISTRATION_COMMIT",
            reason_text="검토", checklist_confirmations={}, acknowledged_warnings=["ALL"],
            actor="STEP12_18_TEST:reg_approver2",
        )
    assert exc_info.value.code == "INCOMPLETE_CHECKLIST"


def test_decision_reject_does_not_ready(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218L")
    package = run_create_runtime_registration_package(session, seed["strategy_id"], **_package_kwargs(seed))
    decision = run_record_runtime_registration_decision(
        session, seed["strategy_id"], package["runtime_registration_package_id"],
        decision_type="REJECT_RUNTIME_REGISTRATION", reason_code="ACCOUNT_NOT_ELIGIBLE", reason_text="부적격",
        checklist_confirmations={}, acknowledged_warnings=[], actor="STEP12_18_TEST:reg_approver3",
    )
    assert decision["registration_ready"] is False


def test_stale_package_blocks_decision(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218M")
    package = run_create_runtime_registration_package(session, seed["strategy_id"], **_package_kwargs(seed))
    account = session.get(PaperAccount, seed["paper_id"])
    account.is_active = False
    session.commit()

    package_row = session.get(StrategyRuntimeRegistrationPackageEntity, package["runtime_registration_package_id"])
    stale, reasons = check_runtime_registration_package_staleness(session, package_row)
    assert stale is True

    with pytest.raises(RuntimeRegistrationError) as exc_info:
        run_record_runtime_registration_decision(
            session, seed["strategy_id"], package["runtime_registration_package_id"],
            decision_type="APPROVE_RUNTIME_REGISTRATION", reason_code="READY_FOR_RUNTIME_REGISTRATION_COMMIT",
            reason_text="검토", checklist_confirmations={}, acknowledged_warnings=["ALL"],
            actor="STEP12_18_TEST:reg_approver4",
        )
    assert exc_info.value.code == "STALE_RUNTIME_REGISTRATION_PACKAGE"


# ---------------------------------------------------------------------------
# E: Hash 결정성.
# ---------------------------------------------------------------------------


def test_runtime_scope_hash_deterministic() -> None:
    kwargs = dict(
        user_id=1, account_kind=ACCOUNT_KIND_PAPER, account_id=2, strategy_id=3, strategy_version=1,
        market_type="STOCK", broker_code="PAPER", execution_mode=EXECUTION_MODE_PAPER,
    )
    assert compute_runtime_scope_hash(**kwargs) == compute_runtime_scope_hash(**kwargs)
    changed = {**kwargs, "strategy_version": 2}
    assert compute_runtime_scope_hash(**kwargs) != compute_runtime_scope_hash(**changed)


# ---------------------------------------------------------------------------
# F: Atomicity — 실패 주입 Rollback 검증.
# ---------------------------------------------------------------------------


def _assert_registration_nothing_persisted(session, strategy_id: int) -> None:
    """§ STEP12-18R 보완(5) — Commit/Registry/History가 0개인 것은 물론,
    AccountStrategyLink도 "활성 Link 없음"이 아니라 행 자체가 0개임을
    확인한다(부분 성공 흔적이 전혀 없어야 한다)."""
    commit_count = session.scalar(
        select(StrategyRuntimeRegistrationCommitEntity.runtime_registration_commit_id).where(
            StrategyRuntimeRegistrationCommitEntity.strategy_definition_id == strategy_id
        )
    )
    assert commit_count is None
    registry_count = session.scalar(
        select(StrategyRuntimeRegistryEntity.runtime_registry_id).where(
            StrategyRuntimeRegistryEntity.strategy_definition_id == strategy_id
        )
    )
    assert registry_count is None
    link_rows = session.scalars(
        select(AccountStrategyLinkEntity).where(AccountStrategyLinkEntity.strategy_id == strategy_id)
    ).all()
    assert len(link_rows) == 0
    history_rows = session.scalars(
        select(StrategyRuntimeRegistrationHistoryEntity).where(
            StrategyRuntimeRegistrationHistoryEntity.strategy_definition_id == strategy_id,
            StrategyRuntimeRegistrationHistoryEntity.source_type == "COMMIT",
        )
    ).all()
    assert len(history_rows) == 0


def test_atomicity_failure_after_commit_insert_before_registry(session, monkeypatch) -> None:
    """A — Commit INSERT 후, Registry 생성 단계에서 실패."""
    import stock_platform.ai.strategy_draft_approval.runtime_registration as module

    seed = _seed_activated(session, symbol="STEP1218N")
    flow = _full_flow(session, seed)

    original_entity_init = module.StrategyRuntimeRegistryEntity.__init__

    def _fail_init(self, *args, **kwargs):
        raise RuntimeError("injected failure constructing Registry entity")

    monkeypatch.setattr(module.StrategyRuntimeRegistryEntity, "__init__", _fail_init)
    with pytest.raises(RuntimeError):
        run_create_runtime_registration_commit(
            session, seed["strategy_id"],
            runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
            runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
            registration_input_hash=flow["package"]["registration_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
            confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
        )
    monkeypatch.setattr(module.StrategyRuntimeRegistryEntity, "__init__", original_entity_init)
    session.rollback()
    _assert_registration_nothing_persisted(session, seed["strategy_id"])


def test_atomicity_failure_after_registry_insert_before_link(session, monkeypatch) -> None:
    """B — Registry INSERT 후, AccountStrategyLink 생성 단계에서 실패."""
    import stock_platform.ai.strategy_draft_approval.runtime_registration as module

    seed = _seed_activated(session, symbol="STEP1218O")
    flow = _full_flow(session, seed)

    original_link_init = module.AccountStrategyLinkEntity.__init__

    def _fail_init(self, *args, **kwargs):
        raise RuntimeError("injected failure constructing AccountStrategyLink entity")

    monkeypatch.setattr(module.AccountStrategyLinkEntity, "__init__", _fail_init)
    with pytest.raises(RuntimeError):
        run_create_runtime_registration_commit(
            session, seed["strategy_id"],
            runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
            runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
            registration_input_hash=flow["package"]["registration_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
            confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
        )
    monkeypatch.setattr(module.AccountStrategyLinkEntity, "__init__", original_link_init)
    session.rollback()
    _assert_registration_nothing_persisted(session, seed["strategy_id"])


def test_atomicity_failure_after_link_insert_before_history(session, monkeypatch) -> None:
    """C — AccountStrategyLink INSERT 후, History 생성 단계(4번째 flush)
    에서 실패."""
    seed = _seed_activated(session, symbol="STEP1218O2")
    flow = _full_flow(session, seed)

    original_flush = session.flush
    call_count = {"n": 0}

    def _flush_fourth_call_fails(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 4:
            raise RuntimeError("injected failure on history insert flush")
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(session, "flush", _flush_fourth_call_fails)
    with pytest.raises(RuntimeError):
        run_create_runtime_registration_commit(
            session, seed["strategy_id"],
            runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
            runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
            registration_input_hash=flow["package"]["registration_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
            confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
        )
    monkeypatch.undo()
    session.rollback()
    _assert_registration_nothing_persisted(session, seed["strategy_id"])


def test_atomicity_failure_history_insert_before_audit(session, monkeypatch) -> None:
    """D — History INSERT 후, Audit 기록 자체가 실패(AuditLogService.record
    호출이 예외를 던짐 — 그 내부 commit()에 도달하지 못함)."""
    import stock_platform.ai.strategy_draft_approval.runtime_registration as module

    seed = _seed_activated(session, symbol="STEP1218O3")
    flow = _full_flow(session, seed)

    def _boom(self, **kwargs):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(module.AuditLogService, "record", _boom)
    with pytest.raises(RuntimeError):
        run_create_runtime_registration_commit(
            session, seed["strategy_id"],
            runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
            runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
            registration_input_hash=flow["package"]["registration_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
            confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
        )
    monkeypatch.undo()
    session.rollback()
    _assert_registration_nothing_persisted(session, seed["strategy_id"])


def test_atomicity_failure_between_flush_and_commit(session, monkeypatch) -> None:
    """E — flush 후 commit 전 실패. `AuditLogService.record()`가 내부적으로
    호출하는 `session.commit()` 자체를 실패시켜, 모든 flush가 성공한
    뒤에도 최종 커밋 단계에서 실패하면 전부 Rollback됨을 확인한다."""
    seed = _seed_activated(session, symbol="STEP1218P")
    flow = _full_flow(session, seed)

    def _commit_fails(*args, **kwargs):
        raise RuntimeError("injected failure before commit")

    monkeypatch.setattr(session, "commit", _commit_fails)
    with pytest.raises(RuntimeError):
        run_create_runtime_registration_commit(
            session, seed["strategy_id"],
            runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
            runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
            registration_input_hash=flow["package"]["registration_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
            confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
        )
    monkeypatch.undo()
    session.rollback()
    _assert_registration_nothing_persisted(session, seed["strategy_id"])


# ---------------------------------------------------------------------------
# G: 실제 PostgreSQL 독립 Session 동시성 검증.
# ---------------------------------------------------------------------------


def test_concurrent_registration_commit_same_strategy_only_one_succeeds(result_ids) -> None:
    Session = get_session_factory()
    setup_session = Session()
    setup_session.info["result_ids"] = result_ids
    _cleanup(setup_session)
    seed = _seed_activated(setup_session, symbol="STEP1218Q")
    flow = _full_flow(setup_session, seed)
    setup_session.commit()

    barrier = threading.Barrier(2)
    results: list[tuple[str, object]] = []
    lock = threading.Lock()

    def _worker() -> None:
        thread_session = Session()
        try:
            barrier.wait(timeout=10)
            try:
                result = run_create_runtime_registration_commit(
                    thread_session, seed["strategy_id"],
                    runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
                    runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
                    registration_input_hash=flow["package"]["registration_input_hash"],
                    decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
                    confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
                )
                with lock:
                    results.append(("success", result))
            except RuntimeRegistrationError as exc:
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

    verify_session = Session()
    try:
        commits = verify_session.scalars(
            select(StrategyRuntimeRegistrationCommitEntity).where(
                StrategyRuntimeRegistrationCommitEntity.strategy_definition_id == seed["strategy_id"]
            )
        ).all()
        assert len(commits) == 1
        registries = verify_session.scalars(
            select(StrategyRuntimeRegistryEntity).where(
                StrategyRuntimeRegistryEntity.strategy_definition_id == seed["strategy_id"]
            )
        ).all()
        assert len(registries) == 1
        assert registries[0].enabled is False
        assert registries[0].running is False
    finally:
        _cleanup(verify_session)
        verify_session.close()


def test_concurrent_registration_commit_repeat_stability(result_ids) -> None:
    for i in range(3):
        Session = get_session_factory()
        setup_session = Session()
        setup_session.info["result_ids"] = result_ids
        _cleanup(setup_session)
        seed = _seed_activated(setup_session, symbol=f"STEP1218R{i}")
        flow = _full_flow(setup_session, seed)
        setup_session.commit()

        barrier = threading.Barrier(2)
        results: list[str] = []
        lock = threading.Lock()

        def _worker() -> None:
            thread_session = Session()
            try:
                barrier.wait(timeout=10)
                try:
                    run_create_runtime_registration_commit(
                        thread_session, seed["strategy_id"],
                        runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
                        runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
                        registration_input_hash=flow["package"]["registration_input_hash"],
                        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
                        confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
                    )
                    with lock:
                        results.append("success")
                except RuntimeRegistrationError:
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


def test_concurrent_same_decision_different_idempotency_key_only_one_succeeds(result_ids) -> None:
    """§ 재작업 6 — 동일 Decision + 서로 다른 Key로 동시 요청해도 Package
    당 Commit은 정확히 1개여야 한다(Key가 달라도 이미 Commit된 Package
    를 다시 Commit할 수는 없다)."""
    Session = get_session_factory()
    setup_session = Session()
    setup_session.info["result_ids"] = result_ids
    _cleanup(setup_session)
    seed = _seed_activated(setup_session, symbol="STEP1218S1")
    flow = _full_flow(setup_session, seed)
    setup_session.commit()

    barrier = threading.Barrier(2)
    results: list[tuple[str, object]] = []
    lock = threading.Lock()

    def _worker(key: str) -> None:
        thread_session = Session()
        try:
            barrier.wait(timeout=10)
            try:
                result = run_create_runtime_registration_commit(
                    thread_session, seed["strategy_id"],
                    runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
                    runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
                    registration_input_hash=flow["package"]["registration_input_hash"],
                    decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
                    confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar", idempotency_key=key,
                )
                with lock:
                    results.append(("success", result))
            except RuntimeRegistrationError as exc:
                thread_session.rollback()
                with lock:
                    results.append(("error", exc.code))
        finally:
            thread_session.close()

    t1 = threading.Thread(target=_worker, args=("key-a",))
    t2 = threading.Thread(target=_worker, args=("key-b",))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert len(results) == 2
    outcomes = [r[0] for r in results]
    assert outcomes.count("success") == 1
    assert outcomes.count("error") == 1

    verify_session = Session()
    try:
        commits = verify_session.scalars(
            select(StrategyRuntimeRegistrationCommitEntity).where(
                StrategyRuntimeRegistrationCommitEntity.strategy_definition_id == seed["strategy_id"]
            )
        ).all()
        assert len(commits) == 1
    finally:
        _cleanup(verify_session)
        verify_session.close()


def test_concurrent_different_scope_same_strategy_both_succeed(result_ids) -> None:
    """§ 재작업 6 — 서로 다른 정상 Scope(다른 Account)는 동시에 등록을
    시도해도 각각 독립적으로 성공해야 한다(서로를 차단하지 않는다)."""
    Session = get_session_factory()
    setup_session = Session()
    setup_session.info["result_ids"] = result_ids
    _cleanup(setup_session)
    seed = _seed_activated(setup_session, symbol="STEP1218S2")
    second_paper_id = _create_paper_account(setup_session, name_suffix="_concurrent_scope")
    flow_a = _full_flow(setup_session, seed)
    flow_b = _full_flow(setup_session, seed, target_paper_account_id=second_paper_id)
    setup_session.commit()

    barrier = threading.Barrier(2)
    results: list[tuple[str, object]] = []
    lock = threading.Lock()

    def _worker(flow: dict) -> None:
        thread_session = Session()
        try:
            barrier.wait(timeout=10)
            try:
                result = run_create_runtime_registration_commit(
                    thread_session, seed["strategy_id"],
                    runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
                    runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
                    registration_input_hash=flow["package"]["registration_input_hash"],
                    decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
                    confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
                )
                with lock:
                    results.append(("success", result))
            except RuntimeRegistrationError as exc:
                thread_session.rollback()
                with lock:
                    results.append(("error", exc.code))
        finally:
            thread_session.close()

    t1 = threading.Thread(target=_worker, args=(flow_a,))
    t2 = threading.Thread(target=_worker, args=(flow_b,))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert len(results) == 2
    outcomes = [r[0] for r in results]
    assert outcomes.count("success") == 2, f"둘 다 성공해야 하는데 결과: {results}"

    verify_session = Session()
    try:
        registries = verify_session.scalars(
            select(StrategyRuntimeRegistryEntity).where(
                StrategyRuntimeRegistryEntity.strategy_definition_id == seed["strategy_id"]
            )
        ).all()
        assert len(registries) == 2
    finally:
        _cleanup(verify_session)
        verify_session.close()


# ---------------------------------------------------------------------------
# H: Idempotency.
# ---------------------------------------------------------------------------


def test_package_idempotency_replay(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218S")
    kwargs = _package_kwargs(seed, idempotency_key="step12-18-package-replay")
    first = run_create_runtime_registration_package(session, seed["strategy_id"], **kwargs)
    second = run_create_runtime_registration_package(session, seed["strategy_id"], **kwargs)
    assert second["idempotent_replay"] is True
    assert second["runtime_registration_package_id"] == first["runtime_registration_package_id"]

    packages = session.scalars(
        select(StrategyRuntimeRegistrationPackageEntity).where(
            StrategyRuntimeRegistrationPackageEntity.strategy_definition_id == seed["strategy_id"]
        )
    ).all()
    assert len(packages) == 1


def test_commit_idempotency_replay(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218T")
    flow = _full_flow(session, seed)
    kwargs = dict(
        runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
        runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
        registration_input_hash=flow["package"]["registration_input_hash"],
        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
        confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar", idempotency_key="step12-18-commit-replay",
    )
    first = run_create_runtime_registration_commit(session, seed["strategy_id"], **kwargs)
    second = run_create_runtime_registration_commit(session, seed["strategy_id"], **kwargs)
    assert second["idempotent_replay"] is True
    assert second["runtime_registration_commit_id"] == first["runtime_registration_commit_id"]

    commits = session.scalars(
        select(StrategyRuntimeRegistrationCommitEntity).where(
            StrategyRuntimeRegistrationCommitEntity.strategy_definition_id == seed["strategy_id"]
        )
    ).all()
    assert len(commits) == 1
    registries = session.scalars(
        select(StrategyRuntimeRegistryEntity).where(
            StrategyRuntimeRegistryEntity.strategy_definition_id == seed["strategy_id"]
        )
    ).all()
    assert len(registries) == 1


# ---------------------------------------------------------------------------
# I: History / Status.
# ---------------------------------------------------------------------------


def test_history_persisted_ordering_and_shape(session) -> None:
    """§ STEP12-18R — 영속 불변 History(동적 합성 아님). Package/Decision/
    Commit 각각의 Transaction에서 함께 저장된 실제 행을 조회한다."""
    seed = _seed_activated(session, symbol="STEP1218U")
    flow = _full_flow(session, seed)
    run_create_runtime_registration_commit(
        session, seed["strategy_id"],
        runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
        runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
        registration_input_hash=flow["package"]["registration_input_hash"],
        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
        confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
    )
    history = get_runtime_registration_history(session, seed["strategy_id"])
    assert len(history) == 3
    events = [h["event_type"] for h in history]
    assert events == ["RUNTIME_REGISTRATION_REVIEW_CREATED", "RUNTIME_REGISTRATION_APPROVED", "RUNTIME_REGISTERED"]
    source_types = [h["source_type"] for h in history]
    assert source_types == ["PACKAGE", "DECISION", "COMMIT"]
    occurred_ats = [h["occurred_at"] for h in history]
    assert occurred_ats == sorted(occurred_ats)
    history_ids = [h["history_id"] for h in history]
    assert history_ids == sorted(history_ids)
    assert len({h["event_hash"] for h in history}) == 3  # 전부 서로 다른 결정적 Hash.
    for h in history:
        assert h["runtime_scope_hash"] == flow["package"]["runtime_scope_hash"]


def test_history_event_hash_deterministic() -> None:
    from datetime import datetime, timezone

    from stock_platform.ai.strategy_draft_approval.runtime_registration import (
        compute_runtime_registration_history_event_hash,
    )

    kwargs = dict(
        strategy_definition_id=1, runtime_scope_hash="scope-hash", event_type="RUNTIME_REGISTERED",
        previous_status="DECIDED", current_status="REGISTERED", source_type="COMMIT", source_id=5,
        actor_id="admin", occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc), algorithm_version="1.0.0",
    )
    assert compute_runtime_registration_history_event_hash(**kwargs) == compute_runtime_registration_history_event_hash(**kwargs)
    changed = {**kwargs, "actor_id": "different_admin"}
    assert compute_runtime_registration_history_event_hash(**kwargs) != compute_runtime_registration_history_event_hash(**changed)


def test_history_no_duplicate_on_decision_idempotent_replay(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218U2")
    package = run_create_runtime_registration_package(session, seed["strategy_id"], **_package_kwargs(seed))
    checklist_codes = [
        c["checklist_code"] for c in build_runtime_registration_checklist_template(EXECUTION_MODE_PAPER) if c["required"]
    ]
    kwargs = dict(
        decision_type="APPROVE_RUNTIME_REGISTRATION", reason_code="READY_FOR_RUNTIME_REGISTRATION_COMMIT",
        reason_text="등록 검토 완료", checklist_confirmations={c: True for c in checklist_codes},
        acknowledged_warnings=["ALL"], actor="STEP12_18_TEST:reg_approver", idempotency_key="step12-18r-decision-replay",
    )
    run_record_runtime_registration_decision(session, seed["strategy_id"], package["runtime_registration_package_id"], **kwargs)
    run_record_runtime_registration_decision(session, seed["strategy_id"], package["runtime_registration_package_id"], **kwargs)
    history = get_runtime_registration_history(session, seed["strategy_id"])
    decision_events = [h for h in history if h["source_type"] == "DECISION"]
    assert len(decision_events) == 1


def test_registration_status_reflects_commit(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218V")
    flow = _full_flow(session, seed)
    before = get_runtime_registration_status(session, seed["strategy_id"])
    assert before["registered"] is False
    run_create_runtime_registration_commit(
        session, seed["strategy_id"],
        runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
        runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
        registration_input_hash=flow["package"]["registration_input_hash"],
        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
        confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
    )
    after = get_runtime_registration_status(session, seed["strategy_id"])
    assert after["registered"] is True
    assert after["runtime_status"] == "NOT_STARTED"
    assert after["strategy_promotion_status"] == "ACTIVATED"


# ---------------------------------------------------------------------------
# J: Regression — Promotion State/Candidate Lifecycle 불변.
# ---------------------------------------------------------------------------


def test_promotion_state_unchanged_by_runtime_registration(session) -> None:
    """§ 핵심 설계 결정 — Runtime Registration은 Promotion State를 전혀
    전이시키지 않는다(ACTIVATED 그대로 유지)."""
    from stock_platform.ai.strategy_draft_approval.promotion_state_entities import (
        PROMOTION_STATE_ACTIVATED,
        StrategyPromotionStateEntity,
    )

    seed = _seed_activated(session, symbol="STEP1218W")
    state_before = session.scalar(
        select(StrategyPromotionStateEntity).where(
            StrategyPromotionStateEntity.strategy_definition_id == seed["strategy_id"]
        )
    )
    version_before = state_before.status_version
    flow = _full_flow(session, seed)
    run_create_runtime_registration_commit(
        session, seed["strategy_id"],
        runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
        runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
        registration_input_hash=flow["package"]["registration_input_hash"],
        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
        confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
    )
    state_after = session.scalar(
        select(StrategyPromotionStateEntity).where(
            StrategyPromotionStateEntity.strategy_definition_id == seed["strategy_id"]
        )
    )
    assert state_after.current_status == PROMOTION_STATE_ACTIVATED
    assert state_after.status_version == version_before  # 재전이 없음.


def test_candidate_lifecycle_unchanged_by_runtime_registration(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218X")
    definition = session.get(StrategyDefinitionEntity, seed["strategy_id"])
    before = session.execute(
        text("SELECT lifecycle_status FROM ai.candidate_lifecycle WHERE candidate_id = :cid"),
        {"cid": definition.candidate_id},
    ).scalar_one()
    flow = _full_flow(session, seed)
    run_create_runtime_registration_commit(
        session, seed["strategy_id"],
        runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
        runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
        registration_input_hash=flow["package"]["registration_input_hash"],
        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
        confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
    )
    after = session.execute(
        text("SELECT lifecycle_status FROM ai.candidate_lifecycle WHERE candidate_id = :cid"),
        {"cid": definition.candidate_id},
    ).scalar_one()
    assert before == after == "PROMOTED"


# ---------------------------------------------------------------------------
# K: STEP12-18R — 서로 다른 정상 Scope는 각각 등록 성공(Strategy 단독
# UNIQUE 제거 검증).
# ---------------------------------------------------------------------------


def test_no_strategy_definition_id_alone_unique_constraint() -> None:
    """§ 재작업 1 — Migration/DB Metadata로 Strategy 단독 UNIQUE가 없음을
    직접 확인한다."""
    commit_constraint_names = {c.name for c in StrategyRuntimeRegistrationCommitEntity.__table__.constraints}
    registry_constraint_names = {c.name for c in StrategyRuntimeRegistryEntity.__table__.constraints}
    assert "uq_runtime_reg_commit_strategy_definition" not in commit_constraint_names
    assert "uq_runtime_registry_strategy_definition" not in registry_constraint_names
    # Scope Hash UNIQUE는 여전히 존재해야 한다(유일성 기준 자체가 없어진
    # 것은 아니다 — 기준만 바뀐 것).
    assert "uq_runtime_reg_commit_scope_hash" in commit_constraint_names
    assert "uq_runtime_registry_scope_hash" in registry_constraint_names


def test_same_strategy_same_scope_duplicate_blocked(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218Y1")
    _full_flow_and_commit(session, seed)
    second_package = run_create_runtime_registration_package(session, seed["strategy_id"], **_package_kwargs(seed))
    assert "RUNTIME_SCOPE_ALREADY_REGISTERED" in second_package["blocking_reason_codes"]


def test_same_strategy_different_account_both_succeed(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218Y2")
    first = _full_flow_and_commit(session, seed, actor_suffix="1")
    assert first["commit"]["registration_status"] == "REGISTERED"

    second_paper_id = _create_paper_account(session, name_suffix="_second")
    second = _full_flow_and_commit(
        session, seed, actor_suffix="2", target_paper_account_id=second_paper_id,
    )
    assert second["commit"]["registration_status"] == "REGISTERED"
    assert second["commit"]["runtime_registration_commit_id"] != first["commit"]["runtime_registration_commit_id"]

    registries = session.scalars(
        select(StrategyRuntimeRegistryEntity).where(
            StrategyRuntimeRegistryEntity.strategy_definition_id == seed["strategy_id"]
        )
    ).all()
    assert len(registries) == 2


def test_same_strategy_different_user_both_succeed(session) -> None:
    """Cross-user 등록은 SYSTEM/공개 소유 Strategy에서만 정상이다(§
    STEP12-17 Account Ownership 정책 — USER 소유 Strategy는 다른
    사용자의 계좌를 대상으로 할 수 없다). 이 Strategy를 SYSTEM 소유로
    명시해 서로 다른 User의 계좌 각각에 등록될 수 있음을 확인한다."""
    from stock_platform.strategy_deployment.definition_entities import StrategyDefinitionEntity

    seed = _seed_activated(session, symbol="STEP1218Y3")
    definition = session.get(StrategyDefinitionEntity, seed["strategy_id"])
    definition.owner_type = "SYSTEM"
    definition.user_id = None
    session.commit()

    first = _full_flow_and_commit(session, seed, actor_suffix="1")
    assert first["commit"]["registration_status"] == "REGISTERED"

    other_user_paper_id = _create_paper_account(session, user_id=_REVIEWER_USER_ID, name_suffix="_other_user")
    second = _full_flow_and_commit(
        session, seed, actor_suffix="2", target_paper_account_id=other_user_paper_id,
    )
    assert second["commit"]["registration_status"] == "REGISTERED"

    registries = session.scalars(
        select(StrategyRuntimeRegistryEntity).where(
            StrategyRuntimeRegistryEntity.strategy_definition_id == seed["strategy_id"]
        )
    ).all()
    assert len(registries) == 2


def test_same_strategy_different_execution_mode_both_succeed(session) -> None:
    """PAPER Account(execution_mode=PAPER)와 LIVE Account(execution_mode=
    LIVE)는 서로 다른 Runtime Scope이므로 각각 등록 성공해야 한다."""
    seed = _seed_activated(session, symbol="STEP1218Y4")
    paper_result = _full_flow_and_commit(session, seed, actor_suffix="_paper")
    assert paper_result["commit"]["registration_status"] == "REGISTERED"

    live_uba_id = _create_live_account(session, alias_suffix="_y4")
    live_result = _full_flow_and_commit(
        session, seed, actor_suffix="_live",
        target_account_kind=ACCOUNT_KIND_USER_BROKER, target_paper_account_id=None,
        target_user_broker_account_id=live_uba_id, target_broker_code="KIWOOM", execution_mode=EXECUTION_MODE_LIVE,
    )
    assert live_result["commit"]["registration_status"] == "REGISTERED"

    registries = session.scalars(
        select(StrategyRuntimeRegistryEntity).where(
            StrategyRuntimeRegistryEntity.strategy_definition_id == seed["strategy_id"]
        )
    ).all()
    assert len(registries) == 2
    execution_modes = {r.execution_mode for r in registries}
    assert execution_modes == {EXECUTION_MODE_PAPER, EXECUTION_MODE_LIVE}


def test_same_strategy_same_account_different_version_conflict(session) -> None:
    """§ 재작업 1 — 같은 Account에 서로 다른 Version을 등록하려 하면
    STRATEGY_VERSION_CONFLICT로 명시적으로 차단한다(같은 물리적 대상에
    대해 두 Version이 동시에 유효하다고 주장하는 모순)."""
    from stock_platform.strategy_deployment.definition_entities import StrategyDefinitionEntity

    seed = _seed_activated(session, symbol="STEP1218Y5")
    first = _full_flow_and_commit(session, seed, actor_suffix="1")
    assert first["commit"]["registration_status"] == "REGISTERED"

    # 같은 Strategy Definition의 Version을 인위적으로 올려(재승인 등 미래
    # 기능을 흉내) 동일 Account에 대한 재등록을 시도한다.
    definition = session.get(StrategyDefinitionEntity, seed["strategy_id"])
    definition.definition_version = int(definition.definition_version or 1) + 1
    session.commit()

    second_package = run_create_runtime_registration_package(session, seed["strategy_id"], **_package_kwargs(seed))
    assert "STRATEGY_VERSION_CONFLICT" in second_package["blocking_reason_codes"]


# ---------------------------------------------------------------------------
# L: STEP12-18R — Promotion State 동시성 보호.
# ---------------------------------------------------------------------------


def test_promotion_state_lock_reverifies_version_and_hash_at_commit(session, monkeypatch) -> None:
    """§ 재작업 2 — Commit 직전 Promotion State version/hash 재검증. Package
    생성 시점 이후 Promotion State가(가상으로) 바뀌면 Stale로 차단돼야
    한다."""
    seed = _seed_activated(session, symbol="STEP1218Z1")
    flow = _full_flow(session, seed)

    from stock_platform.ai.strategy_draft_approval.promotion_state_entities import (
        StrategyPromotionStateEntity,
    )

    state_row = session.scalar(
        select(StrategyPromotionStateEntity).where(
            StrategyPromotionStateEntity.strategy_definition_id == seed["strategy_id"]
        )
    )
    # ACTIVATED 상태는 유지하되 status_version/state_hash만 인위적으로
    # 바꿔(가상 재전이를 흉내) Package 생성 시점 Snapshot과 어긋나게 한다.
    state_row.status_version = state_row.status_version + 100
    state_row.state_hash = "different-hash-simulating-concurrent-transition"
    session.commit()

    with pytest.raises(RuntimeRegistrationError) as exc_info:
        run_create_runtime_registration_commit(
            session, seed["strategy_id"],
            runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
            runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
            registration_input_hash=flow["package"]["registration_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
            confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
        )
    assert exc_info.value.code == "STALE_RUNTIME_REGISTRATION_PACKAGE"


def test_blocked_promotion_state_committed_first_blocks_registration(session) -> None:
    """§ 재작업 2 — "차단 상태 변경이 먼저 Commit되면 Runtime Registration
    은 실패해야 한다." Promotion State를 REVOKED로 먼저 변경·commit한 뒤
    Runtime Registration Commit을 시도하면 반드시 실패해야 한다(Promotion
    State Lock을 획득하는 즉시 최신 상태를 보게 되므로)."""
    seed = _seed_activated(session, symbol="STEP1218Z2")
    flow = _full_flow(session, seed)

    session.execute(
        text("UPDATE trading.strategy_promotion_state SET current_status = 'REVOKED' WHERE strategy_definition_id = :sid"),
        {"sid": seed["strategy_id"]},
    )
    session.commit()

    with pytest.raises(RuntimeRegistrationError) as exc_info:
        run_create_runtime_registration_commit(
            session, seed["strategy_id"],
            runtime_registration_package_id=flow["package"]["runtime_registration_package_id"],
            runtime_registration_decision_id=flow["decision"]["runtime_registration_decision_id"],
            registration_input_hash=flow["package"]["registration_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Runtime 등록",
            confirmation_text="REGISTER", actor="STEP12_18_TEST:registrar",
        )
    assert exc_info.value.code == "STRATEGY_NOT_ACTIVATED"

    # 부분 성공이 전혀 없어야 한다.
    _assert_registration_nothing_persisted(session, seed["strategy_id"])


# ---------------------------------------------------------------------------
# M: STEP12-18R — Runtime Registration Decision Idempotency 전용 테스트.
# ---------------------------------------------------------------------------


def test_decision_idempotency_replay_full_assertions(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218Z3")
    package = run_create_runtime_registration_package(session, seed["strategy_id"], **_package_kwargs(seed))
    checklist_codes = [
        c["checklist_code"] for c in build_runtime_registration_checklist_template(EXECUTION_MODE_PAPER) if c["required"]
    ]
    kwargs = dict(
        decision_type="APPROVE_RUNTIME_REGISTRATION", reason_code="READY_FOR_RUNTIME_REGISTRATION_COMMIT",
        reason_text="등록 검토 완료", checklist_confirmations={c: True for c in checklist_codes},
        acknowledged_warnings=["ALL"], actor="STEP12_18_TEST:reg_approver", idempotency_key="step12-18r-decision-full",
    )
    first = run_record_runtime_registration_decision(session, seed["strategy_id"], package["runtime_registration_package_id"], **kwargs)
    second = run_record_runtime_registration_decision(session, seed["strategy_id"], package["runtime_registration_package_id"], **kwargs)

    assert second["idempotent_replay"] is True
    assert second["runtime_registration_decision_id"] == first["runtime_registration_decision_id"]

    decisions = session.scalars(
        select(StrategyRuntimeRegistrationDecisionEntity).where(
            StrategyRuntimeRegistrationDecisionEntity.runtime_registration_package_id == package["runtime_registration_package_id"]
        )
    ).all()
    assert len(decisions) == 1

    registries = session.scalars(
        select(StrategyRuntimeRegistryEntity).where(
            StrategyRuntimeRegistryEntity.strategy_definition_id == seed["strategy_id"]
        )
    ).all()
    assert len(registries) == 0  # Decision만으로는 Registry가 생기지 않는다.

    from stock_platform.ai.strategy_draft_approval.promotion_commit import get_promotion_state

    state = get_promotion_state(session, seed["strategy_id"])
    assert state["current_status"] == "ACTIVATED"  # Decision Replay는 Promotion State를 건드리지 않는다.


def test_decision_idempotency_conflict_no_raw_db_error(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218Z4")
    package = run_create_runtime_registration_package(session, seed["strategy_id"], **_package_kwargs(seed))
    checklist_codes = [
        c["checklist_code"] for c in build_runtime_registration_checklist_template(EXECUTION_MODE_PAPER) if c["required"]
    ]
    run_record_runtime_registration_decision(
        session, seed["strategy_id"], package["runtime_registration_package_id"],
        decision_type="APPROVE_RUNTIME_REGISTRATION", reason_code="READY_FOR_RUNTIME_REGISTRATION_COMMIT",
        reason_text="등록 검토 완료", checklist_confirmations={c: True for c in checklist_codes},
        acknowledged_warnings=["ALL"], actor="STEP12_18_TEST:reg_approver", idempotency_key="step12-18r-decision-conflict",
    )
    with pytest.raises(RuntimeRegistrationError) as exc_info:
        run_record_runtime_registration_decision(
            session, seed["strategy_id"], package["runtime_registration_package_id"],
            decision_type="REJECT_RUNTIME_REGISTRATION", reason_code="ACCOUNT_NOT_ELIGIBLE", reason_text="다른 입력",
            checklist_confirmations={}, acknowledged_warnings=[],
            actor="STEP12_18_TEST:reg_approver", idempotency_key="step12-18r-decision-conflict",
        )
    assert exc_info.value.code == "IDEMPOTENCY_CONFLICT"
    assert "psycopg" not in exc_info.value.message and "IntegrityError" not in exc_info.value.message


# ---------------------------------------------------------------------------
# N: STEP12-18R — Stale Detection Matrix(개별 항목).
# ---------------------------------------------------------------------------


def test_stale_matrix_credential_version_change(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218ZA")
    live_uba_id = _create_live_account(session, alias_suffix="_stale_cred")
    package = run_create_runtime_registration_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_USER_BROKER, target_paper_account_id=None,
            target_user_broker_account_id=live_uba_id, target_broker_code="KIWOOM", execution_mode=EXECUTION_MODE_LIVE,
        ),
    )
    credential = session.scalar(
        select(BrokerAccountCredentialEntity).where(BrokerAccountCredentialEntity.user_broker_account_id == live_uba_id)
    )
    credential.key_version = credential.key_version + 1
    session.commit()

    package_row = session.get(StrategyRuntimeRegistrationPackageEntity, package["runtime_registration_package_id"])
    stale, reasons = check_runtime_registration_package_staleness(session, package_row)
    assert stale is True
    assert "CREDENTIAL_VERSION_CHANGED" in reasons


def test_stale_matrix_trading_flag_change(session, monkeypatch) -> None:
    import stock_platform.ai.strategy_draft_approval.activation as activation_module

    seed = _seed_activated(session, symbol="STEP1218ZB")
    paper_id = _create_paper_account(session, name_suffix="_stale_flag")
    package = run_create_runtime_registration_package(
        session, seed["strategy_id"], **_package_kwargs(seed, target_paper_account_id=paper_id),
    )
    package_row = session.get(StrategyRuntimeRegistrationPackageEntity, package["runtime_registration_package_id"])

    original_resolve = activation_module.ResolvedRiskPolicyResolver.resolve

    def _fake_resolve(self, **kwargs):
        policy = original_resolve(self, **kwargs)
        object.__setattr__(policy, "auto_trading_enabled", False)
        return policy

    monkeypatch.setattr(activation_module.ResolvedRiskPolicyResolver, "resolve", _fake_resolve)
    stale, reasons = check_runtime_registration_package_staleness(session, package_row)
    assert stale is True
    assert "RISK_SNAPSHOT_CHANGED" in reasons


def test_stale_matrix_live_order_flag_change(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218ZC")
    live_uba_id = _create_live_account(session, alias_suffix="_stale_live_order")
    package = run_create_runtime_registration_package(
        session, seed["strategy_id"],
        **_package_kwargs(
            seed, target_account_kind=ACCOUNT_KIND_USER_BROKER, target_paper_account_id=None,
            target_user_broker_account_id=live_uba_id, target_broker_code="KIWOOM", execution_mode=EXECUTION_MODE_LIVE,
        ),
    )
    account = session.get(UserBrokerAccount, live_uba_id)
    account.live_order_enabled = False
    session.commit()

    package_row = session.get(StrategyRuntimeRegistrationPackageEntity, package["runtime_registration_package_id"])
    stale, reasons = check_runtime_registration_package_staleness(session, package_row)
    assert stale is True
    assert "ACCOUNT_SNAPSHOT_CHANGED" in reasons


def test_stale_matrix_kill_switch_change(session, monkeypatch) -> None:
    import stock_platform.ai.strategy_draft_approval.activation as activation_module

    seed = _seed_activated(session, symbol="STEP1218ZD")
    paper_id = _create_paper_account(session, name_suffix="_stale_kill")
    package = run_create_runtime_registration_package(
        session, seed["strategy_id"], **_package_kwargs(seed, target_paper_account_id=paper_id),
    )
    package_row = session.get(StrategyRuntimeRegistrationPackageEntity, package["runtime_registration_package_id"])

    monkeypatch.setattr(activation_module.KillSwitchService, "is_active_for_scopes", lambda self, codes: True)
    stale, reasons = check_runtime_registration_package_staleness(session, package_row)
    assert stale is True
    assert "OPERATIONAL_SNAPSHOT_CHANGED" in reasons


def test_stale_matrix_account_pause_change(session, monkeypatch) -> None:
    import stock_platform.ai.strategy_draft_approval.activation as activation_module

    seed = _seed_activated(session, symbol="STEP1218ZE")
    paper_id = _create_paper_account(session, name_suffix="_stale_pause")
    package = run_create_runtime_registration_package(
        session, seed["strategy_id"], **_package_kwargs(seed, target_paper_account_id=paper_id),
    )
    package_row = session.get(StrategyRuntimeRegistrationPackageEntity, package["runtime_registration_package_id"])

    original_resolve = activation_module.ResolvedRiskPolicyResolver.resolve

    def _fake_resolve(self, **kwargs):
        policy = original_resolve(self, **kwargs)
        object.__setattr__(policy, "account_paused", True)
        return policy

    monkeypatch.setattr(activation_module.ResolvedRiskPolicyResolver, "resolve", _fake_resolve)
    stale, reasons = check_runtime_registration_package_staleness(session, package_row)
    assert stale is True
    assert "RISK_SNAPSHOT_CHANGED" in reasons


def test_stale_matrix_recovery_conflict_change(session, monkeypatch) -> None:
    import stock_platform.ai.strategy_draft_approval.activation as activation_module

    seed = _seed_activated(session, symbol="STEP1218ZF")
    paper_id = _create_paper_account(session, name_suffix="_stale_recovery")
    package = run_create_runtime_registration_package(
        session, seed["strategy_id"], **_package_kwargs(seed, target_paper_account_id=paper_id),
    )
    package_row = session.get(StrategyRuntimeRegistrationPackageEntity, package["runtime_registration_package_id"])

    monkeypatch.setattr(activation_module.RecoveryAccountLockService, "is_trading_paused", lambda self, **kwargs: True)
    stale, reasons = check_runtime_registration_package_staleness(session, package_row)
    assert stale is True
    assert "OPERATIONAL_SNAPSHOT_CHANGED" in reasons


def test_stale_matrix_promotion_state_version_and_hash_change(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218ZG")
    paper_id = _create_paper_account(session, name_suffix="_stale_promo")
    package = run_create_runtime_registration_package(
        session, seed["strategy_id"], **_package_kwargs(seed, target_paper_account_id=paper_id),
    )
    from stock_platform.ai.strategy_draft_approval.promotion_state_entities import (
        StrategyPromotionStateEntity,
    )

    state_row = session.scalar(
        select(StrategyPromotionStateEntity).where(
            StrategyPromotionStateEntity.strategy_definition_id == seed["strategy_id"]
        )
    )
    state_row.status_version = state_row.status_version + 1
    state_row.state_hash = "different-hash-for-stale-matrix-test"
    session.commit()

    package_row = session.get(StrategyRuntimeRegistrationPackageEntity, package["runtime_registration_package_id"])
    stale, reasons = check_runtime_registration_package_staleness(session, package_row)
    assert stale is True
    assert "PROMOTION_STATE_VERSION_CHANGED" in reasons
    assert "PROMOTION_STATE_HASH_CHANGED" in reasons


def test_stale_matrix_runtime_registry_creation_elsewhere_is_not_package_stale_but_blocks_new_package(session) -> None:
    """Runtime Registry가 (다른 Package를 통해) 이미 생성된 뒤에는, 새
    Package 생성 자체가 RUNTIME_SCOPE_ALREADY_REGISTERED로 BLOCKED된다
    (기존 Package의 Staleness와는 별개 경로)."""
    seed = _seed_activated(session, symbol="STEP1218ZH")
    _full_flow_and_commit(session, seed)
    new_package = run_create_runtime_registration_package(session, seed["strategy_id"], **_package_kwargs(seed))
    assert new_package["registration_readiness_status"] == REGISTRATION_READINESS_BLOCKED
    assert "RUNTIME_SCOPE_ALREADY_REGISTERED" in new_package["blocking_reason_codes"]


def test_stale_matrix_deployment_creation_blocks_new_package(session) -> None:
    from stock_platform.strategy_deployment.entities import StrategyDeploymentEntity

    seed = _seed_activated(session, symbol="STEP1218ZI")
    paper_id = _create_paper_account(session, name_suffix="_stale_deploy")
    existing_performance_run_id = session.execute(
        text("SELECT strategy_performance_run_id FROM trading.strategy_performance_run ORDER BY strategy_performance_run_id LIMIT 1")
    ).scalar_one()
    deployment = StrategyDeploymentEntity(
        strategy_code=f"STEP12_18_TEST_{seed['strategy_id']}", strategy_performance_run_id=existing_performance_run_id,
        strategy_id=seed["strategy_id"], market_code="KRX", symbol="STEP1218ZI", mode_code="PAPER",
        status_code="ACTIVE", owner_type="SYSTEM", requested_by="STEP12_18_TEST:setup",
    )
    session.add(deployment)
    session.commit()

    package = run_create_runtime_registration_package(
        session, seed["strategy_id"], **_package_kwargs(seed, target_paper_account_id=paper_id),
    )
    assert package["registration_readiness_status"] == REGISTRATION_READINESS_BLOCKED
    assert "DEPLOYMENT_ALREADY_EXISTS" in package["blocking_reason_codes"]


def test_stale_matrix_account_strategy_link_creation_blocks_new_package(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218ZJ")
    paper_id = _create_paper_account(session, name_suffix="_stale_link")
    link = AccountStrategyLinkEntity(
        strategy_id=seed["strategy_id"], user_id=_REQUESTER_USER_ID, paper_account_id=paper_id,
        user_broker_account_id=None, is_active=True, created_by="STEP12_18_TEST:setup",
    )
    session.add(link)
    session.commit()

    package = run_create_runtime_registration_package(
        session, seed["strategy_id"], **_package_kwargs(seed, target_paper_account_id=paper_id),
    )
    assert package["registration_readiness_status"] == REGISTRATION_READINESS_BLOCKED
    assert "ACCOUNT_STRATEGY_LINK_CONFLICT" in package["blocking_reason_codes"]


# ---------------------------------------------------------------------------
# O: STEP12-19 Carry-forward(3.2/3.3) — Scope별 History 필터 / 다중 Status.
# ---------------------------------------------------------------------------


def test_history_filtered_by_runtime_scope_hash_no_cross_scope_mixing(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218AA1")
    second_paper_id = _create_paper_account(session, name_suffix="_history_filter")
    first = _full_flow_and_commit(session, seed, actor_suffix="_a")
    second = _full_flow_and_commit(session, seed, actor_suffix="_b", target_paper_account_id=second_paper_id)

    scope_a_hash = first["package"]["runtime_scope_hash"]
    scope_b_hash = second["package"]["runtime_scope_hash"]
    assert scope_a_hash != scope_b_hash

    history_a = get_runtime_registration_history(session, seed["strategy_id"], runtime_scope_hash=scope_a_hash)
    history_b = get_runtime_registration_history(session, seed["strategy_id"], runtime_scope_hash=scope_b_hash)
    assert len(history_a) == 3
    assert len(history_b) == 3
    assert all(h["runtime_scope_hash"] == scope_a_hash for h in history_a)
    assert all(h["runtime_scope_hash"] == scope_b_hash for h in history_b)

    unfiltered = get_runtime_registration_history(session, seed["strategy_id"])
    assert len(unfiltered) == 6


def test_history_filtered_by_commit_id_and_execution_mode(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218AA2")
    second_paper_id = _create_paper_account(session, name_suffix="_history_filter2")
    first = _full_flow_and_commit(session, seed, actor_suffix="_a")
    _full_flow_and_commit(session, seed, actor_suffix="_b", target_paper_account_id=second_paper_id)

    by_commit = get_runtime_registration_history(
        session, seed["strategy_id"], runtime_registration_commit_id=first["commit"]["runtime_registration_commit_id"],
    )
    assert len(by_commit) == 3
    assert all(h["runtime_scope_hash"] == first["package"]["runtime_scope_hash"] for h in by_commit)

    by_mode = get_runtime_registration_history(session, seed["strategy_id"], execution_mode=EXECUTION_MODE_PAPER)
    assert len(by_mode) == 6  # 둘 다 PAPER 모드이므로 전체와 동일해야 한다.


def test_runtime_registration_scopes_lists_all_scopes(session) -> None:
    seed = _seed_activated(session, symbol="STEP1218AA3")
    second_paper_id = _create_paper_account(session, name_suffix="_scopes_list")
    _full_flow_and_commit(session, seed, actor_suffix="_a")
    _full_flow_and_commit(session, seed, actor_suffix="_b", target_paper_account_id=second_paper_id)

    scopes = get_runtime_registration_scopes(session, seed["strategy_id"])
    assert len(scopes) == 2
    for scope in scopes:
        assert scope["registry_enabled"] is False
        assert scope["registry_running"] is False
        assert scope["registration_status"] == "REGISTERED"
    account_ids = {s["target_paper_account_id"] for s in scopes}
    assert account_ids == {seed["paper_id"], second_paper_id}
