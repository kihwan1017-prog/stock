"""STEP 12-20 — Operation Readiness Certification (final STEP12 gate).

READY_TO_START(§ STEP12-19) Deployment를 대상으로 Strategy/Promotion/
Activation/Runtime Registration/Deployment/Scheduler Plan/Credential/
Risk/Trading Flag/Kill Switch/Recovery/Account/Runtime Scope/Deployment
Scope/History/Audit 15개 영역을 하나의 Certification으로 재검증하고,
관리자의 명시적 Operation Commit으로 같은 Deployment 행을
`status_code=READY_TO_OPERATE`로 전진시킨다. Runtime 시작, Scheduler
실제 등록, Broker 연결, 실시간 시세 구독, Signal 계산, 주문 생성/전송은
전혀 수행하지 않는다."""

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
from stock_platform.ai.strategy_draft_approval.deployment_readiness import (
    build_deployment_checklist_template,
    run_create_deployment_readiness_commit,
    run_create_deployment_readiness_package,
    run_record_deployment_readiness_decision,
)
from stock_platform.ai.strategy_draft_approval.deployment_readiness_entities import (
    StrategyRuntimeSchedulerPlanEntity,
)
from stock_platform.ai.strategy_draft_approval.explainability import (
    run_generate_explainability,
)
from stock_platform.ai.strategy_draft_approval.monte_carlo import (
    run_monte_carlo_simulation,
)
from stock_platform.ai.strategy_draft_approval.operation_readiness import (
    OperationReadinessError,
    build_operation_readiness_checklist_template,
    check_operation_readiness_package_staleness,
    compute_operation_commit_hash,
    get_operation_readiness_certification,
    get_operation_readiness_history,
    get_operation_readiness_package,
    get_operation_readiness_status,
    run_create_operation_readiness_commit,
    run_create_operation_readiness_package,
    run_record_operation_readiness_decision,
)
from stock_platform.ai.strategy_draft_approval.operation_readiness_entities import (
    READINESS_STATUS_BLOCKED,
    READINESS_STATUS_READY,
    StrategyOperationReadinessCommitEntity,
    StrategyOperationReadinessHistoryEntity,
    StrategyOperationReadinessPackageEntity,
)
from stock_platform.ai.strategy_draft_approval.parameter_sensitivity import (
    run_parameter_sensitivity,
)
from stock_platform.ai.strategy_draft_approval.promotion_commit import (
    run_create_promotion_commit,
)
from stock_platform.ai.strategy_draft_approval.quality_gate import run_quality_gate
from stock_platform.ai.strategy_draft_approval.runtime_registration import (
    build_runtime_registration_checklist_template,
    run_create_runtime_registration_commit,
    run_create_runtime_registration_package,
    run_record_runtime_registration_decision,
)
from stock_platform.ai.strategy_draft_approval.runtime_registration_entities import (
    StrategyRuntimeRegistryEntity,
)
from stock_platform.ai.strategy_draft_approval.service import (
    StrategyDraftApprovalService,
)
from stock_platform.ai.strategy_request.service import StrategyRequestService
from stock_platform.api.main import app  # noqa: F401  — 전체 모델 등록 부작용.
from stock_platform.database.session import get_session_factory
from stock_platform.strategy_deployment.entities import StrategyDeploymentEntity
from stock_platform.strategy_deployment.models import StrategyDeploymentStatus
from stock_platform.broker.credential_entities import BrokerAccountCredentialEntity
from stock_platform.trading.account_models import PaperAccount, UserBrokerAccount

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_MARKER = "STEP12_20_TEST"
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
    "DELETE FROM trading.strategy_operation_readiness_history WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_operation_readiness_commit WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_operation_readiness_decision WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_operation_readiness_package WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_deployment_readiness_history WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_deployment_readiness_commit WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_runtime_scheduler_plan WHERE runtime_registry_id IN "
    "(SELECT runtime_registry_id FROM trading.strategy_runtime_registry WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker)))",
    "DELETE FROM trading.strategy_deployment_readiness_decision WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
    "DELETE FROM trading.strategy_deployment_readiness_package WHERE strategy_definition_id IN "
    "(SELECT strategy_id FROM trading.strategy_definition WHERE candidate_id IN "
    "(SELECT candidate_id FROM ai.candidate_lifecycle WHERE created_by = :marker))",
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
    "DELETE FROM trading.strategy_deployment WHERE symbol LIKE 'STEP1220%'",
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
    "DELETE FROM trading.paper_account WHERE account_name LIKE 'STEP12_20_TEST%'",
    "DELETE FROM trading.broker_account_credential WHERE user_broker_account_id IN "
    "(SELECT user_broker_account_id FROM trading.user_broker_account WHERE account_alias LIKE 'STEP12_20_TEST%')",
    "DELETE FROM trading.user_broker_account WHERE account_alias LIKE 'STEP12_20_TEST%'",
    "DELETE FROM market.price_daily WHERE instrument_id IN "
    "(SELECT instrument_id FROM market.instrument WHERE symbol LIKE 'STEP1220%')",
    "DELETE FROM market.instrument WHERE symbol LIKE 'STEP1220%'",
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
            VALUES ('STOCK', :exchange, :symbol, 'STEP12-20 Test')
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
                VALUES (:iid, :td, :c, :c, :c, :c, 1000, 'STEP12_20_TEST')
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
        session, strategy_definition_id, runtime_input=_runtime_input(symbol), actor="STEP12_20_TEST:admin",
    )
    return result["backtest_run_id"]


def _create_paper_account(session, *, user_id: int = _REQUESTER_USER_ID, name_suffix: str = "") -> int:
    account = PaperAccount(
        user_id=user_id, account_name=f"STEP12_20_TEST_paper{name_suffix}", currency_code="KRW",
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
        user_id=user_id, broker_code="KIWOOM", account_alias=f"STEP12_20_TEST_live{alias_suffix}",
        account_ref_hash="e" * 64, is_active=True, live_order_enabled=live_order_enabled,
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


def _seed_deployed(
    session, *, symbol: str, execution_mode: str = EXECUTION_MODE_PAPER, result_id_index: int = 0,
) -> dict:
    """PROMOTION_COMMITTED -> Activation -> ACTIVATED -> Runtime
    Registration Commit -> Deployment Readiness Commit(READY_TO_START)까지
    도달한 상태를 만든다."""
    ids = session.info["result_ids"]
    _seed_prices(session, symbol, _triangle_wave(150, period=30), start=date(2024, 1, 1))

    req = _create_approved_request(session, result_id=ids[result_id_index])
    approval = _approve(session, req["strategy_request_id"])
    strategy_id = approval["strategy_definition_id"]

    backtest_run_id = _run_backtest(session, strategy_id, symbol)
    quality_gate = run_quality_gate(session, strategy_id, actor="STEP12_20_TEST:admin")
    sensitivity = run_parameter_sensitivity(
        session, strategy_id, parameter_names=["stop_loss_rule.value"], runtime_input=_runtime_input(symbol),
        actor="STEP12_20_TEST:admin",
    )
    monte_carlo = run_monte_carlo_simulation(
        session, strategy_id, backtest_run_id=backtest_run_id, simulation_method="BOOTSTRAP_WITH_REPLACEMENT",
        actor="STEP12_20_TEST:admin", simulation_count=100,
    )
    explainability = run_generate_explainability(
        session, strategy_id, backtest_run_id=backtest_run_id,
        quality_gate_report_id=quality_gate["quality_gate_report_id"],
        parameter_sensitivity_report_id=sensitivity["parameter_sensitivity_report_id"],
        monte_carlo_report_id=monte_carlo["monte_carlo_report_id"],
        actor="STEP12_20_TEST:admin",
    )
    package = run_create_decision_package(
        session, strategy_id, explainability_report_id=explainability["explainability_report_id"],
        actor="STEP12_20_TEST:admin",
    )
    required_codes = [c["checklist_code"] for c in package["checklist_template"] if c["required"]]
    decision = run_record_human_decision(
        session, strategy_id, package["package_id"], decision_type="APPROVE_FOR_PROMOTION",
        reason_code="EVIDENCE_REVIEW_COMPLETED", reason_text="검토 완료, 승인합니다.",
        checklist_confirmations={c: True for c in required_codes}, acknowledged_warnings=["ALL"],
        actor="STEP12_20_TEST:reviewer",
    )
    commit = run_create_promotion_commit(
        session, strategy_id,
        decision_package_id=package["package_id"], human_decision_id=decision["decision_id"],
        promotion_readiness_hash=decision["promotion_readiness_hash"], commit_reason="검토 완료, 승인합니다.",
        confirmation_text="PROMOTE", actor="STEP12_20_TEST:committer",
    )

    paper_id = _create_paper_account(session, name_suffix=f"_{symbol}")
    activation_package = run_create_activation_review_package(
        session, strategy_id,
        promotion_commit_id=commit["promotion_commit_id"], target_market_type="STOCK", target_broker_code="PAPER",
        target_account_kind=ACCOUNT_KIND_PAPER, target_paper_account_id=paper_id,
        requested_execution_mode=EXECUTION_MODE_PAPER, review_note="검토 시작", actor="STEP12_20_TEST:reviewer",
    )
    checklist_codes = [c["checklist_code"] for c in build_activation_checklist_template(EXECUTION_MODE_PAPER) if c["required"]]
    activation_decision = run_record_activation_decision(
        session, strategy_id, activation_package["activation_review_package_id"],
        decision_type="APPROVE_ACTIVATION", reason_code="READY_FOR_ACTIVATION_COMMIT", reason_text="검토 완료",
        checklist_confirmations={c: True for c in checklist_codes}, acknowledged_warnings=["ALL"],
        actor="STEP12_20_TEST:approver",
    )
    activation_commit = run_create_activation_commit(
        session, strategy_id,
        activation_review_package_id=activation_package["activation_review_package_id"],
        activation_decision_id=activation_decision["activation_decision_id"],
        activation_readiness_hash=activation_decision["decision_input_hash"], commit_reason="활성화 승인",
        confirmation_text="ACTIVATE", actor="STEP12_20_TEST:activator",
    )

    if execution_mode == EXECUTION_MODE_LIVE:
        live_uba_id = _create_live_account(session, alias_suffix=f"_{symbol}")
        reg_package = run_create_runtime_registration_package(
            session, strategy_id,
            activation_commit_id=activation_commit["activation_commit_id"],
            activation_decision_id=activation_decision["activation_decision_id"],
            target_account_kind=ACCOUNT_KIND_USER_BROKER, target_user_broker_account_id=live_uba_id,
            target_market_type="STOCK", target_broker_code="KIWOOM", execution_mode=EXECUTION_MODE_LIVE,
            actor="STEP12_20_TEST:reg_reviewer",
        )
    else:
        reg_package = run_create_runtime_registration_package(
            session, strategy_id,
            activation_commit_id=activation_commit["activation_commit_id"],
            activation_decision_id=activation_decision["activation_decision_id"],
            target_account_kind=ACCOUNT_KIND_PAPER, target_paper_account_id=paper_id,
            target_market_type="STOCK", target_broker_code="PAPER", execution_mode=EXECUTION_MODE_PAPER,
            actor="STEP12_20_TEST:reg_reviewer",
        )
    reg_checklist_codes = [
        c["checklist_code"] for c in build_runtime_registration_checklist_template(reg_package["execution_mode"]) if c["required"]
    ]
    reg_decision = run_record_runtime_registration_decision(
        session, strategy_id, reg_package["runtime_registration_package_id"],
        decision_type="APPROVE_RUNTIME_REGISTRATION", reason_code="READY_FOR_RUNTIME_REGISTRATION_COMMIT",
        reason_text="등록 검토 완료", checklist_confirmations={c: True for c in reg_checklist_codes},
        acknowledged_warnings=["ALL"], actor="STEP12_20_TEST:reg_approver",
    )
    reg_commit = run_create_runtime_registration_commit(
        session, strategy_id,
        runtime_registration_package_id=reg_package["runtime_registration_package_id"],
        runtime_registration_decision_id=reg_decision["runtime_registration_decision_id"],
        registration_input_hash=reg_package["registration_input_hash"],
        decision_input_hash=reg_decision["decision_input_hash"], commit_reason="Runtime 등록",
        confirmation_text="REGISTER", actor="STEP12_20_TEST:registrar",
    )
    registry = session.scalar(
        select(StrategyRuntimeRegistryEntity).where(
            StrategyRuntimeRegistryEntity.runtime_registration_commit_id == reg_commit["runtime_registration_commit_id"]
        )
    )

    deploy_package = run_create_deployment_readiness_package(
        session, strategy_id, runtime_registration_commit_id=reg_commit["runtime_registration_commit_id"],
        runtime_registry_id=int(registry.runtime_registry_id), actor="STEP12_20_TEST:deploy_reviewer",
    )
    deploy_checklist_codes = [
        c["checklist_code"] for c in build_deployment_checklist_template(deploy_package["execution_mode"]) if c["required"]
    ]
    deploy_decision = run_record_deployment_readiness_decision(
        session, strategy_id, deploy_package["deployment_readiness_package_id"],
        decision_type="APPROVE_DEPLOYMENT", reason_code="READY_FOR_DEPLOYMENT_COMMIT",
        reason_text="배포 준비 검토 완료", checklist_confirmations={c: True for c in deploy_checklist_codes},
        acknowledged_warnings=["ALL"], actor="STEP12_20_TEST:deploy_approver",
    )
    deploy_commit = run_create_deployment_readiness_commit(
        session, strategy_id,
        deployment_readiness_package_id=deploy_package["deployment_readiness_package_id"],
        deployment_readiness_decision_id=deploy_decision["deployment_readiness_decision_id"],
        runtime_registration_commit_id=reg_commit["runtime_registration_commit_id"],
        runtime_scope_hash=registry.runtime_scope_hash,
        deployment_input_hash=deploy_package["deployment_input_hash"],
        decision_input_hash=deploy_decision["decision_input_hash"], commit_reason="Deployment 확정",
        confirmation_text="DEPLOY", actor="STEP12_20_TEST:deployer",
    )
    return {
        "strategy_id": strategy_id, "paper_id": paper_id,
        "runtime_registry_id": int(registry.runtime_registry_id),
        "runtime_scope_hash": registry.runtime_scope_hash,
        "deployment_readiness_commit_id": deploy_commit["deployment_readiness_commit_id"],
        "strategy_deployment_id": deploy_commit["strategy_deployment_id"],
        "scheduler_plan_id": deploy_commit["scheduler_plan_id"],
    }


def _full_flow(session, seed: dict, *, idempotency_key: str | None = None) -> dict:
    package = run_create_operation_readiness_package(
        session, seed["strategy_id"], deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        actor="STEP12_20_TEST:reviewer", idempotency_key=idempotency_key,
    )
    checklist_codes = [
        c["checklist_code"] for c in build_operation_readiness_checklist_template(package["execution_mode"]) if c["required"]
    ]
    decision = run_record_operation_readiness_decision(
        session, seed["strategy_id"], package["operation_readiness_package_id"],
        decision_type="APPROVE_OPERATION", reason_code="READY_FOR_OPERATION_COMMIT",
        reason_text="운영 준비 검토 완료", checklist_confirmations={c: True for c in checklist_codes},
        acknowledged_warnings=["ALL"], actor="STEP12_20_TEST:op_approver",
    )
    return {"package": package, "decision": decision}


def _full_flow_and_commit(session, seed: dict, *, actor_suffix: str = "", idempotency_key: str | None = None) -> dict:
    flow = _full_flow(session, seed)
    commit = run_create_operation_readiness_commit(
        session, seed["strategy_id"],
        operation_readiness_package_id=flow["package"]["operation_readiness_package_id"],
        operation_readiness_decision_id=flow["decision"]["operation_readiness_decision_id"],
        deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        runtime_scope_hash=seed["runtime_scope_hash"],
        operation_input_hash=flow["package"]["operation_input_hash"],
        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="운영 준비 완료",
        confirmation_text="OPERATE", actor=f"STEP12_20_TEST:operator{actor_suffix}",
        idempotency_key=idempotency_key,
    )
    return {**flow, "commit": commit}


# ---------------------------------------------------------------------------
# A: Operation Readiness Package — happy path & 게이팅.
# ---------------------------------------------------------------------------


def test_package_ready_for_paper(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220A")
    result = run_create_operation_readiness_package(
        session, seed["strategy_id"], deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        actor="STEP12_20_TEST:reviewer",
    )
    assert result["readiness_status"] == READINESS_STATUS_READY
    assert result["blocking_reason_codes"] == []
    assert result["execution_mode"] == EXECUTION_MODE_PAPER


def test_package_ready_for_live(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220A2", execution_mode=EXECUTION_MODE_LIVE)
    result = run_create_operation_readiness_package(
        session, seed["strategy_id"], deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        actor="STEP12_20_TEST:reviewer",
    )
    assert result["readiness_status"] == READINESS_STATUS_READY
    assert result["execution_mode"] == EXECUTION_MODE_LIVE


def test_package_blocked_when_deployment_readiness_commit_not_found(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220B")
    with pytest.raises(OperationReadinessError) as exc_info:
        run_create_operation_readiness_package(
            session, seed["strategy_id"], deployment_readiness_commit_id=999_999_999, actor="STEP12_20_TEST:reviewer",
        )
    assert exc_info.value.code == "DEPLOYMENT_READINESS_COMMIT_NOT_FOUND"


def test_package_blocked_when_deployment_not_ready_to_start(session) -> None:
    """Deployment가 이미 다른 상태(예: FAILED)로 바뀌면 DEPLOYMENT_NOT_READY."""
    seed = _seed_deployed(session, symbol="STEP1220C")
    deployment = session.get(StrategyDeploymentEntity, seed["strategy_deployment_id"])
    deployment.status_code = StrategyDeploymentStatus.FAILED.value
    session.commit()
    result = run_create_operation_readiness_package(
        session, seed["strategy_id"], deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        actor="STEP12_20_TEST:reviewer",
    )
    assert result["readiness_status"] == READINESS_STATUS_BLOCKED
    assert "DEPLOYMENT_NOT_READY" in result["blocking_reason_codes"]


def test_package_blocked_when_registry_enabled(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220D")
    registry = session.get(StrategyRuntimeRegistryEntity, seed["runtime_registry_id"])
    registry.enabled = True
    session.commit()
    result = run_create_operation_readiness_package(
        session, seed["strategy_id"], deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        actor="STEP12_20_TEST:reviewer",
    )
    assert result["readiness_status"] == READINESS_STATUS_BLOCKED
    assert "RUNTIME_CONFIGURATION_INVALID" in result["blocking_reason_codes"]


def test_package_blocked_when_scheduler_plan_enabled(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220D2")
    plan = session.get(StrategyRuntimeSchedulerPlanEntity, seed["scheduler_plan_id"])
    plan.enabled = True
    session.commit()
    result = run_create_operation_readiness_package(
        session, seed["strategy_id"], deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        actor="STEP12_20_TEST:reviewer",
    )
    assert result["readiness_status"] == READINESS_STATUS_BLOCKED
    assert "SCHEDULER_PLAN_INVALID" in result["blocking_reason_codes"]


def test_package_no_sensitive_credential_data(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220E", execution_mode=EXECUTION_MODE_LIVE)
    result = run_create_operation_readiness_package(
        session, seed["strategy_id"], deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        actor="STEP12_20_TEST:reviewer",
    )
    package_row = session.get(StrategyOperationReadinessPackageEntity, result["operation_readiness_package_id"])
    assert "encrypted_payload" not in package_row.credential_snapshot_payload
    assert "nonce_b64" not in package_row.credential_snapshot_payload


def test_package_idempotent_replay_same_input(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220F")
    first = run_create_operation_readiness_package(
        session, seed["strategy_id"], deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        actor="STEP12_20_TEST:reviewer", idempotency_key="op-pkg-key-1",
    )
    second = run_create_operation_readiness_package(
        session, seed["strategy_id"], deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        actor="STEP12_20_TEST:reviewer", idempotency_key="op-pkg-key-1",
    )
    assert first["operation_readiness_package_id"] == second["operation_readiness_package_id"]
    assert second["idempotent_replay"] is True


def test_package_idempotency_conflict_on_different_input(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220G")
    run_create_operation_readiness_package(
        session, seed["strategy_id"], deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        actor="STEP12_20_TEST:reviewer", idempotency_key="op-pkg-key-2",
    )
    other_seed = _seed_deployed(session, symbol="STEP1220G2", result_id_index=1)
    with pytest.raises(OperationReadinessError) as exc_info:
        run_create_operation_readiness_package(
            session, other_seed["strategy_id"], deployment_readiness_commit_id=other_seed["deployment_readiness_commit_id"],
            actor="STEP12_20_TEST:reviewer", idempotency_key="op-pkg-key-2",
        )
    assert exc_info.value.code == "IDEMPOTENCY_CONFLICT"


def test_certification_all_areas_passed_when_ready(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220H")
    result = run_create_operation_readiness_package(
        session, seed["strategy_id"], deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        actor="STEP12_20_TEST:reviewer",
    )
    certification = get_operation_readiness_certification(session, result["operation_readiness_package_id"])
    assert certification["all_areas_passed"] is True
    for area, info in certification["certification_areas"].items():
        assert info["passed"] is True, f"{area} failed unexpectedly"


def test_certification_reflects_failed_area(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220H2")
    registry = session.get(StrategyRuntimeRegistryEntity, seed["runtime_registry_id"])
    registry.running = True
    session.commit()
    result = run_create_operation_readiness_package(
        session, seed["strategy_id"], deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        actor="STEP12_20_TEST:reviewer",
    )
    certification = get_operation_readiness_certification(session, result["operation_readiness_package_id"])
    assert certification["all_areas_passed"] is False
    assert certification["certification_areas"]["RUNTIME_SCOPE"]["passed"] is False


# ---------------------------------------------------------------------------
# B: Decision — Checklist/Reason Code/Stale.
# ---------------------------------------------------------------------------


def test_decision_incomplete_checklist_blocks_approve(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220I")
    package = run_create_operation_readiness_package(
        session, seed["strategy_id"], deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        actor="STEP12_20_TEST:reviewer",
    )
    with pytest.raises(OperationReadinessError) as exc_info:
        run_record_operation_readiness_decision(
            session, seed["strategy_id"], package["operation_readiness_package_id"],
            decision_type="APPROVE_OPERATION", reason_code="READY_FOR_OPERATION_COMMIT",
            reason_text="검토", checklist_confirmations={}, acknowledged_warnings=["ALL"],
            actor="STEP12_20_TEST:op_approver2",
        )
    assert exc_info.value.code == "INCOMPLETE_CHECKLIST"


def test_decision_reject_does_not_ready(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220J")
    package = run_create_operation_readiness_package(
        session, seed["strategy_id"], deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        actor="STEP12_20_TEST:reviewer",
    )
    decision = run_record_operation_readiness_decision(
        session, seed["strategy_id"], package["operation_readiness_package_id"],
        decision_type="REJECT_OPERATION", reason_code="ACCOUNT_NOT_ELIGIBLE", reason_text="부적격",
        checklist_confirmations={}, acknowledged_warnings=[], actor="STEP12_20_TEST:op_approver3",
    )
    assert decision["operation_ready"] is False


def test_decision_duplicate_blocked(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220J2")
    flow = _full_flow(session, seed)
    with pytest.raises(OperationReadinessError) as exc_info:
        run_record_operation_readiness_decision(
            session, seed["strategy_id"], flow["package"]["operation_readiness_package_id"],
            decision_type="APPROVE_OPERATION", reason_code="READY_FOR_OPERATION_COMMIT",
            reason_text="재시도", checklist_confirmations={}, acknowledged_warnings=["ALL"],
            actor="STEP12_20_TEST:op_approver4",
        )
    assert exc_info.value.code == "DUPLICATE_OPERATION_READINESS_DECISION"


def test_stale_package_blocks_decision(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220K")
    package = run_create_operation_readiness_package(
        session, seed["strategy_id"], deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        actor="STEP12_20_TEST:reviewer",
    )
    account = session.get(PaperAccount, seed["paper_id"])
    account.is_active = False
    session.commit()

    package_row = session.get(StrategyOperationReadinessPackageEntity, package["operation_readiness_package_id"])
    stale, reasons = check_operation_readiness_package_staleness(session, package_row)
    assert stale is True

    with pytest.raises(OperationReadinessError) as exc_info:
        run_record_operation_readiness_decision(
            session, seed["strategy_id"], package["operation_readiness_package_id"],
            decision_type="APPROVE_OPERATION", reason_code="READY_FOR_OPERATION_COMMIT",
            reason_text="검토", checklist_confirmations={}, acknowledged_warnings=["ALL"],
            actor="STEP12_20_TEST:op_approver5",
        )
    assert exc_info.value.code == "STALE_OPERATION_READINESS_PACKAGE"


# ---------------------------------------------------------------------------
# C: Commit — 성공, READY_TO_OPERATE.
# ---------------------------------------------------------------------------


def test_commit_success_advances_same_deployment_to_ready_to_operate(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220L")
    result = _full_flow_and_commit(session, seed)["commit"]
    assert result["deployment_status"] == StrategyDeploymentStatus.READY_TO_OPERATE.value

    deployment = session.get(StrategyDeploymentEntity, seed["strategy_deployment_id"])
    assert deployment.status_code == StrategyDeploymentStatus.READY_TO_OPERATE.value
    assert int(deployment.strategy_deployment_id) == result["strategy_deployment_id"]
    assert deployment.activated_at is None
    assert deployment.stopped_at is None

    registry = session.get(StrategyRuntimeRegistryEntity, seed["runtime_registry_id"])
    assert registry.enabled is False
    assert registry.running is False
    plan = session.get(StrategyRuntimeSchedulerPlanEntity, seed["scheduler_plan_id"])
    assert plan.enabled is False
    assert plan.registered_to_scheduler is False


def test_commit_requires_exact_confirmation(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220M")
    flow = _full_flow(session, seed)
    with pytest.raises(OperationReadinessError) as exc_info:
        run_create_operation_readiness_commit(
            session, seed["strategy_id"],
            operation_readiness_package_id=flow["package"]["operation_readiness_package_id"],
            operation_readiness_decision_id=flow["decision"]["operation_readiness_decision_id"],
            deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
            runtime_scope_hash=seed["runtime_scope_hash"],
            operation_input_hash=flow["package"]["operation_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="운영 준비 완료",
            confirmation_text="operate now", actor="STEP12_20_TEST:operator",
        )
    assert exc_info.value.code == "INVALID_CONFIRMATION"


def test_commit_duplicate_blocked(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220N")
    flow = _full_flow_and_commit(session, seed)
    with pytest.raises(OperationReadinessError) as exc_info:
        run_create_operation_readiness_commit(
            session, seed["strategy_id"],
            operation_readiness_package_id=flow["package"]["operation_readiness_package_id"],
            operation_readiness_decision_id=flow["decision"]["operation_readiness_decision_id"],
            deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
            runtime_scope_hash=seed["runtime_scope_hash"],
            operation_input_hash=flow["package"]["operation_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="운영 준비 완료",
            confirmation_text="OPERATE", actor="STEP12_20_TEST:operator2",
        )
    assert exc_info.value.code == "OPERATION_ALREADY_CERTIFIED"


def test_commit_idempotent_replay(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220N2")
    flow = _full_flow(session, seed, idempotency_key="op-commit-key-1")
    first = run_create_operation_readiness_commit(
        session, seed["strategy_id"],
        operation_readiness_package_id=flow["package"]["operation_readiness_package_id"],
        operation_readiness_decision_id=flow["decision"]["operation_readiness_decision_id"],
        deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        runtime_scope_hash=seed["runtime_scope_hash"],
        operation_input_hash=flow["package"]["operation_input_hash"],
        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="운영 준비 완료",
        confirmation_text="OPERATE", actor="STEP12_20_TEST:operator3", idempotency_key="op-commit-key-1",
    )
    second = run_create_operation_readiness_commit(
        session, seed["strategy_id"],
        operation_readiness_package_id=flow["package"]["operation_readiness_package_id"],
        operation_readiness_decision_id=flow["decision"]["operation_readiness_decision_id"],
        deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
        runtime_scope_hash=seed["runtime_scope_hash"],
        operation_input_hash=flow["package"]["operation_input_hash"],
        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="운영 준비 완료",
        confirmation_text="OPERATE", actor="STEP12_20_TEST:operator3", idempotency_key="op-commit-key-1",
    )
    assert first["operation_readiness_commit_id"] == second["operation_readiness_commit_id"]
    assert second["idempotent_replay"] is True


# ---------------------------------------------------------------------------
# D: Hash 결정성.
# ---------------------------------------------------------------------------


def test_operation_commit_hash_deterministic() -> None:
    from datetime import datetime, timezone as tz

    kwargs = dict(
        strategy_definition_id=1, deployment_readiness_commit_id=2, operation_readiness_package_id=3,
        operation_readiness_decision_id=4, runtime_scope_hash="a" * 64, operation_input_hash="b" * 64,
        decision_input_hash="c" * 64, committed_by="tester", committed_at=datetime(2024, 1, 1, tzinfo=tz.utc),
        confirmation_hash="d" * 64, algorithm_version="1.0.0",
    )
    assert compute_operation_commit_hash(**kwargs) == compute_operation_commit_hash(**kwargs)
    changed = {**kwargs, "operation_readiness_package_id": 999}
    assert compute_operation_commit_hash(**kwargs) != compute_operation_commit_hash(**changed)


# ---------------------------------------------------------------------------
# E: Atomicity — 실패 주입 Rollback 검증.
# ---------------------------------------------------------------------------


def _assert_operation_nothing_persisted(session, strategy_id: int, *, deployment_id: int) -> None:
    commit_count = session.scalar(
        select(StrategyOperationReadinessCommitEntity.operation_readiness_commit_id).where(
            StrategyOperationReadinessCommitEntity.strategy_definition_id == strategy_id
        )
    )
    assert commit_count is None
    history_rows = session.scalars(
        select(StrategyOperationReadinessHistoryEntity).where(
            StrategyOperationReadinessHistoryEntity.strategy_definition_id == strategy_id,
            StrategyOperationReadinessHistoryEntity.source_type == "COMMIT",
        )
    ).all()
    assert len(history_rows) == 0
    deployment = session.get(StrategyDeploymentEntity, deployment_id)
    assert deployment.status_code == StrategyDeploymentStatus.READY_TO_START.value


def test_atomicity_failure_after_deployment_status_change_before_commit_insert(session, monkeypatch) -> None:
    import stock_platform.ai.strategy_draft_approval.operation_readiness as module

    seed = _seed_deployed(session, symbol="STEP1220O")
    flow = _full_flow(session, seed)

    original_init = module.StrategyOperationReadinessCommitEntity.__init__

    def _fail_init(self, *args, **kwargs):
        raise RuntimeError("injected failure constructing Operation Readiness Commit entity")

    monkeypatch.setattr(module.StrategyOperationReadinessCommitEntity, "__init__", _fail_init)
    with pytest.raises(RuntimeError):
        run_create_operation_readiness_commit(
            session, seed["strategy_id"],
            operation_readiness_package_id=flow["package"]["operation_readiness_package_id"],
            operation_readiness_decision_id=flow["decision"]["operation_readiness_decision_id"],
            deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
            runtime_scope_hash=seed["runtime_scope_hash"],
            operation_input_hash=flow["package"]["operation_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="운영 준비 완료",
            confirmation_text="OPERATE", actor="STEP12_20_TEST:operator",
        )
    monkeypatch.setattr(module.StrategyOperationReadinessCommitEntity, "__init__", original_init)
    session.rollback()
    _assert_operation_nothing_persisted(session, seed["strategy_id"], deployment_id=seed["strategy_deployment_id"])


def test_atomicity_failure_after_history_insert_before_audit(session, monkeypatch) -> None:
    import stock_platform.ai.strategy_draft_approval.operation_readiness as module

    seed = _seed_deployed(session, symbol="STEP1220O2")
    flow = _full_flow(session, seed)

    def _boom(self, **kwargs):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(module.AuditLogService, "record", _boom)
    with pytest.raises(RuntimeError):
        run_create_operation_readiness_commit(
            session, seed["strategy_id"],
            operation_readiness_package_id=flow["package"]["operation_readiness_package_id"],
            operation_readiness_decision_id=flow["decision"]["operation_readiness_decision_id"],
            deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
            runtime_scope_hash=seed["runtime_scope_hash"],
            operation_input_hash=flow["package"]["operation_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="운영 준비 완료",
            confirmation_text="OPERATE", actor="STEP12_20_TEST:operator",
        )
    monkeypatch.undo()
    session.rollback()
    _assert_operation_nothing_persisted(session, seed["strategy_id"], deployment_id=seed["strategy_deployment_id"])


def test_atomicity_failure_between_flush_and_commit(session, monkeypatch) -> None:
    seed = _seed_deployed(session, symbol="STEP1220O3")
    flow = _full_flow(session, seed)

    def _commit_fails(*args, **kwargs):
        raise RuntimeError("injected failure before commit")

    monkeypatch.setattr(session, "commit", _commit_fails)
    with pytest.raises(RuntimeError):
        run_create_operation_readiness_commit(
            session, seed["strategy_id"],
            operation_readiness_package_id=flow["package"]["operation_readiness_package_id"],
            operation_readiness_decision_id=flow["decision"]["operation_readiness_decision_id"],
            deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
            runtime_scope_hash=seed["runtime_scope_hash"],
            operation_input_hash=flow["package"]["operation_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="운영 준비 완료",
            confirmation_text="OPERATE", actor="STEP12_20_TEST:operator",
        )
    monkeypatch.undo()
    session.rollback()
    _assert_operation_nothing_persisted(session, seed["strategy_id"], deployment_id=seed["strategy_deployment_id"])


# ---------------------------------------------------------------------------
# F: 비실행 증명 — Scheduler 실제 미등록, Runtime/Broker/Order 미실행.
# ---------------------------------------------------------------------------


def test_no_real_scheduler_job_registered(session, monkeypatch) -> None:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    call_count = {"n": 0}
    original_add_job = AsyncIOScheduler.add_job

    def _spy_add_job(self, *args, **kwargs):
        call_count["n"] += 1
        return original_add_job(self, *args, **kwargs)

    monkeypatch.setattr(AsyncIOScheduler, "add_job", _spy_add_job)
    seed = _seed_deployed(session, symbol="STEP1220P")
    result = _full_flow_and_commit(session, seed)["commit"]
    assert call_count["n"] == 0
    plan = session.get(StrategyRuntimeSchedulerPlanEntity, seed["scheduler_plan_id"])
    assert plan.enabled is False
    assert plan.registered_to_scheduler is False
    assert plan.scheduler_job_id is None
    assert result["deployment_status"] == StrategyDeploymentStatus.READY_TO_OPERATE.value


def test_no_runtime_manager_methods_called(session, monkeypatch) -> None:
    from stock_platform.strategy_deployment.runtime_manager import (
        DynamicStrategyRuntimeManager,
    )

    call_counts: dict[str, int] = {}
    for method_name in ("initialize", "initialize_scoped", "reload", "reload_scope", "put_entry", "resume_runtime"):
        original = getattr(DynamicStrategyRuntimeManager, method_name)

        def _make_spy(name, orig):
            async def _spy(self, *args, **kwargs):
                call_counts[name] = call_counts.get(name, 0) + 1
                return await orig(self, *args, **kwargs)
            return _spy

        monkeypatch.setattr(DynamicStrategyRuntimeManager, method_name, _make_spy(method_name, original))

    seed = _seed_deployed(session, symbol="STEP1220Q")
    _full_flow_and_commit(session, seed)
    assert call_counts == {}


def test_runtime_registry_unaffected_by_operation_commit(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220Q2")
    before = session.get(StrategyRuntimeRegistryEntity, seed["runtime_registry_id"])
    before_enabled, before_running = before.enabled, before.running
    _full_flow_and_commit(session, seed)
    session.expire_all()
    after = session.get(StrategyRuntimeRegistryEntity, seed["runtime_registry_id"])
    assert after.enabled == before_enabled == False  # noqa: E712
    assert after.running == before_running == False  # noqa: E712


# ---------------------------------------------------------------------------
# G: 실제 PostgreSQL 독립 Session 동시성 검증.
# ---------------------------------------------------------------------------


def test_concurrent_commit_same_scope_only_one_succeeds(result_ids) -> None:
    Session = get_session_factory()
    setup_session = Session()
    setup_session.info["result_ids"] = result_ids
    _cleanup(setup_session)
    seed = _seed_deployed(setup_session, symbol="STEP1220R")
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
                result = run_create_operation_readiness_commit(
                    thread_session, seed["strategy_id"],
                    operation_readiness_package_id=flow["package"]["operation_readiness_package_id"],
                    operation_readiness_decision_id=flow["decision"]["operation_readiness_decision_id"],
                    deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
                    runtime_scope_hash=seed["runtime_scope_hash"],
                    operation_input_hash=flow["package"]["operation_input_hash"],
                    decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="운영 준비 완료",
                    confirmation_text="OPERATE", actor="STEP12_20_TEST:operator",
                )
                with lock:
                    results.append(("success", result))
            except OperationReadinessError as exc:
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
            select(StrategyOperationReadinessCommitEntity).where(
                StrategyOperationReadinessCommitEntity.strategy_definition_id == seed["strategy_id"]
            )
        ).all()
        assert len(commits) == 1
        deployment = verify_session.get(StrategyDeploymentEntity, seed["strategy_deployment_id"])
        assert deployment.status_code == StrategyDeploymentStatus.READY_TO_OPERATE.value
    finally:
        _cleanup(verify_session)
        verify_session.close()


def test_concurrent_commit_repeat_stability(result_ids) -> None:
    for i in range(3):
        Session = get_session_factory()
        setup_session = Session()
        setup_session.info["result_ids"] = result_ids
        _cleanup(setup_session)
        seed = _seed_deployed(setup_session, symbol=f"STEP1220S{i}")
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
                    run_create_operation_readiness_commit(
                        thread_session, seed["strategy_id"],
                        operation_readiness_package_id=flow["package"]["operation_readiness_package_id"],
                        operation_readiness_decision_id=flow["decision"]["operation_readiness_decision_id"],
                        deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
                        runtime_scope_hash=seed["runtime_scope_hash"],
                        operation_input_hash=flow["package"]["operation_input_hash"],
                        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="운영 준비 완료",
                        confirmation_text="OPERATE", actor="STEP12_20_TEST:operator",
                    )
                    with lock:
                        results.append("success")
                except OperationReadinessError:
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


def test_concurrent_commit_different_scope_both_succeed(result_ids) -> None:
    Session = get_session_factory()
    setup_session = Session()
    setup_session.info["result_ids"] = result_ids
    _cleanup(setup_session)
    seed_a = _seed_deployed(setup_session, symbol="STEP1220T1")
    seed_b = _seed_deployed(setup_session, symbol="STEP1220T2", result_id_index=1)
    flow_a = _full_flow(setup_session, seed_a)
    flow_b = _full_flow(setup_session, seed_b)
    setup_session.commit()

    barrier = threading.Barrier(2)
    results: list[str] = []
    lock = threading.Lock()

    def _worker(seed, flow) -> None:
        thread_session = Session()
        try:
            barrier.wait(timeout=10)
            run_create_operation_readiness_commit(
                thread_session, seed["strategy_id"],
                operation_readiness_package_id=flow["package"]["operation_readiness_package_id"],
                operation_readiness_decision_id=flow["decision"]["operation_readiness_decision_id"],
                deployment_readiness_commit_id=seed["deployment_readiness_commit_id"],
                runtime_scope_hash=seed["runtime_scope_hash"],
                operation_input_hash=flow["package"]["operation_input_hash"],
                decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="운영 준비 완료",
                confirmation_text="OPERATE", actor="STEP12_20_TEST:operator",
            )
            with lock:
                results.append("success")
        finally:
            thread_session.close()

    t1 = threading.Thread(target=_worker, args=(seed_a, flow_a))
    t2 = threading.Thread(target=_worker, args=(seed_b, flow_b))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)
    assert results.count("success") == 2


# ---------------------------------------------------------------------------
# H: History/Status 조회.
# ---------------------------------------------------------------------------


def test_history_persisted_ordering_and_no_duplicate_on_replay(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220U")
    _full_flow_and_commit(session, seed)
    history = get_operation_readiness_history(session, seed["strategy_id"])
    event_types = [h["event_type"] for h in history]
    assert event_types == ["REVIEW_CREATED", "APPROVED", "READY_TO_OPERATE"]
    occurred_ats = [h["occurred_at"] for h in history]
    assert occurred_ats == sorted(occurred_ats)


def test_status_reflects_certified_state(session) -> None:
    seed = _seed_deployed(session, symbol="STEP1220V")
    before = get_operation_readiness_status(session, seed["strategy_id"])
    assert before["certified"] is False
    _full_flow_and_commit(session, seed)
    after = get_operation_readiness_status(session, seed["strategy_id"])
    assert after["certified"] is True
    assert after["deployment_status"] == StrategyDeploymentStatus.READY_TO_OPERATE.value


def test_package_get_cross_strategy_not_found(session) -> None:
    seed_a = _seed_deployed(session, symbol="STEP1220Y1")
    seed_b = _seed_deployed(session, symbol="STEP1220Y2", result_id_index=1)
    package = run_create_operation_readiness_package(
        session, seed_a["strategy_id"], deployment_readiness_commit_id=seed_a["deployment_readiness_commit_id"],
        actor="STEP12_20_TEST:reviewer",
    )
    with pytest.raises(OperationReadinessError) as exc_info:
        get_operation_readiness_package(session, package["operation_readiness_package_id"], strategy_definition_id=seed_b["strategy_id"])
    assert exc_info.value.code == "NOT_FOUND"
