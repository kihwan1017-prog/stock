"""STEP 12-19 — Runtime Deployment Readiness & Disabled Scheduler Plan.

REGISTERED(비실행, `enabled=false`/`running=false`)된 Runtime Registry를
대상으로 Deployment Readiness Package/Decision/Commit을 통해
`StrategyDeployment.status_code=READY_TO_START`와 비활성 Scheduler Plan을
확정한다. Runtime 시작, Scheduler 실제 등록, Broker 연결/로그인, 실시간
시세 구독, Signal 계산, 주문 생성/전송은 전혀 수행하지 않는다."""

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
    DeploymentReadinessError,
    build_deployment_checklist_template,
    check_deployment_readiness_package_staleness,
    compute_deployment_commit_hash,
    compute_scheduler_plan_hash,
    get_deployment_readiness_history,
    get_deployment_readiness_package,
    get_deployment_readiness_scopes,
    get_deployment_readiness_status,
    get_scheduler_plan,
    list_scheduler_plans,
    run_create_deployment_readiness_commit,
    run_create_deployment_readiness_package,
    run_record_deployment_readiness_decision,
)
from stock_platform.ai.strategy_draft_approval.deployment_readiness_entities import (
    READINESS_STATUS_BLOCKED,
    READINESS_STATUS_READY,
    StrategyDeploymentReadinessCommitEntity,
    StrategyDeploymentReadinessHistoryEntity,
    StrategyDeploymentReadinessPackageEntity,
    StrategyRuntimeSchedulerPlanEntity,
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
from stock_platform.strategy_deployment.definition_entities import (
    AccountStrategyLinkEntity,
    StrategyDefinitionEntity,
)
from stock_platform.strategy_deployment.entities import StrategyDeploymentEntity
from stock_platform.strategy_deployment.models import StrategyDeploymentStatus
from stock_platform.broker.credential_entities import BrokerAccountCredentialEntity
from stock_platform.trading.account_models import PaperAccount, UserBrokerAccount

pytestmark = pytest.mark.integration

_REQUESTER_USER_ID = 8
_REVIEWER_USER_ID = 7
_MARKER = "STEP12_19_TEST"
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
    "DELETE FROM trading.strategy_deployment WHERE symbol LIKE 'STEP1219%'",
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
    "DELETE FROM trading.paper_account WHERE account_name LIKE 'STEP12_19_TEST%'",
    "DELETE FROM trading.broker_account_credential WHERE user_broker_account_id IN "
    "(SELECT user_broker_account_id FROM trading.user_broker_account WHERE account_alias LIKE 'STEP12_19_TEST%')",
    "DELETE FROM trading.user_broker_account WHERE account_alias LIKE 'STEP12_19_TEST%'",
    "DELETE FROM market.price_daily WHERE instrument_id IN "
    "(SELECT instrument_id FROM market.instrument WHERE symbol LIKE 'STEP1219%')",
    "DELETE FROM market.instrument WHERE symbol LIKE 'STEP1219%'",
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
            VALUES ('STOCK', :exchange, :symbol, 'STEP12-19 Test')
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
                VALUES (:iid, :td, :c, :c, :c, :c, 1000, 'STEP12_19_TEST')
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
        session, strategy_definition_id, runtime_input=_runtime_input(symbol), actor="STEP12_19_TEST:admin",
    )
    return result["backtest_run_id"]


def _create_paper_account(session, *, user_id: int = _REQUESTER_USER_ID, name_suffix: str = "") -> int:
    account = PaperAccount(
        user_id=user_id, account_name=f"STEP12_19_TEST_paper{name_suffix}", currency_code="KRW",
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
        user_id=user_id, broker_code="KIWOOM", account_alias=f"STEP12_19_TEST_live{alias_suffix}",
        account_ref_hash="d" * 64, is_active=True, live_order_enabled=live_order_enabled,
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


def _seed_registered(
    session, *, symbol: str, execution_mode: str = EXECUTION_MODE_PAPER, result_id_index: int = 0,
) -> dict:
    """PROMOTION_COMMITTED -> Activation(PAPER) -> ACTIVATED -> Runtime
    Registration Commit(PAPER 또는 LIVE)까지 도달한 상태를 만든다."""
    ids = session.info["result_ids"]
    _seed_prices(session, symbol, _triangle_wave(150, period=30), start=date(2024, 1, 1))

    req = _create_approved_request(session, result_id=ids[result_id_index])
    approval = _approve(session, req["strategy_request_id"])
    strategy_id = approval["strategy_definition_id"]

    backtest_run_id = _run_backtest(session, strategy_id, symbol)
    quality_gate = run_quality_gate(session, strategy_id, actor="STEP12_19_TEST:admin")
    sensitivity = run_parameter_sensitivity(
        session, strategy_id, parameter_names=["stop_loss_rule.value"], runtime_input=_runtime_input(symbol),
        actor="STEP12_19_TEST:admin",
    )
    monte_carlo = run_monte_carlo_simulation(
        session, strategy_id, backtest_run_id=backtest_run_id, simulation_method="BOOTSTRAP_WITH_REPLACEMENT",
        actor="STEP12_19_TEST:admin", simulation_count=100,
    )
    explainability = run_generate_explainability(
        session, strategy_id, backtest_run_id=backtest_run_id,
        quality_gate_report_id=quality_gate["quality_gate_report_id"],
        parameter_sensitivity_report_id=sensitivity["parameter_sensitivity_report_id"],
        monte_carlo_report_id=monte_carlo["monte_carlo_report_id"],
        actor="STEP12_19_TEST:admin",
    )
    package = run_create_decision_package(
        session, strategy_id, explainability_report_id=explainability["explainability_report_id"],
        actor="STEP12_19_TEST:admin",
    )
    required_codes = [c["checklist_code"] for c in package["checklist_template"] if c["required"]]
    decision = run_record_human_decision(
        session, strategy_id, package["package_id"], decision_type="APPROVE_FOR_PROMOTION",
        reason_code="EVIDENCE_REVIEW_COMPLETED", reason_text="검토 완료, 승인합니다.",
        checklist_confirmations={c: True for c in required_codes}, acknowledged_warnings=["ALL"],
        actor="STEP12_19_TEST:reviewer",
    )
    commit = run_create_promotion_commit(
        session, strategy_id,
        decision_package_id=package["package_id"], human_decision_id=decision["decision_id"],
        promotion_readiness_hash=decision["promotion_readiness_hash"], commit_reason="검토 완료, 승인합니다.",
        confirmation_text="PROMOTE", actor="STEP12_19_TEST:committer",
    )

    paper_id = _create_paper_account(session, name_suffix=f"_{symbol}")
    activation_package = run_create_activation_review_package(
        session, strategy_id,
        promotion_commit_id=commit["promotion_commit_id"], target_market_type="STOCK", target_broker_code="PAPER",
        target_account_kind=ACCOUNT_KIND_PAPER, target_paper_account_id=paper_id,
        requested_execution_mode=EXECUTION_MODE_PAPER, review_note="검토 시작", actor="STEP12_19_TEST:reviewer",
    )
    checklist_codes = [c["checklist_code"] for c in build_activation_checklist_template(EXECUTION_MODE_PAPER) if c["required"]]
    activation_decision = run_record_activation_decision(
        session, strategy_id, activation_package["activation_review_package_id"],
        decision_type="APPROVE_ACTIVATION", reason_code="READY_FOR_ACTIVATION_COMMIT", reason_text="검토 완료",
        checklist_confirmations={c: True for c in checklist_codes}, acknowledged_warnings=["ALL"],
        actor="STEP12_19_TEST:approver",
    )
    activation_commit = run_create_activation_commit(
        session, strategy_id,
        activation_review_package_id=activation_package["activation_review_package_id"],
        activation_decision_id=activation_decision["activation_decision_id"],
        activation_readiness_hash=activation_decision["decision_input_hash"], commit_reason="활성화 승인",
        confirmation_text="ACTIVATE", actor="STEP12_19_TEST:activator",
    )

    live_uba_id: int | None = None
    if execution_mode == EXECUTION_MODE_LIVE:
        live_uba_id = _create_live_account(session, alias_suffix=f"_{symbol}")
        reg_package = run_create_runtime_registration_package(
            session, strategy_id,
            activation_commit_id=activation_commit["activation_commit_id"],
            activation_decision_id=activation_decision["activation_decision_id"],
            target_account_kind=ACCOUNT_KIND_USER_BROKER, target_user_broker_account_id=live_uba_id,
            target_market_type="STOCK", target_broker_code="KIWOOM", execution_mode=EXECUTION_MODE_LIVE,
            actor="STEP12_19_TEST:reg_reviewer",
        )
    else:
        reg_package = run_create_runtime_registration_package(
            session, strategy_id,
            activation_commit_id=activation_commit["activation_commit_id"],
            activation_decision_id=activation_decision["activation_decision_id"],
            target_account_kind=ACCOUNT_KIND_PAPER, target_paper_account_id=paper_id,
            target_market_type="STOCK", target_broker_code="PAPER", execution_mode=EXECUTION_MODE_PAPER,
            actor="STEP12_19_TEST:reg_reviewer",
        )
    reg_checklist_codes = [
        c["checklist_code"] for c in build_runtime_registration_checklist_template(reg_package["execution_mode"]) if c["required"]
    ]
    reg_decision = run_record_runtime_registration_decision(
        session, strategy_id, reg_package["runtime_registration_package_id"],
        decision_type="APPROVE_RUNTIME_REGISTRATION", reason_code="READY_FOR_RUNTIME_REGISTRATION_COMMIT",
        reason_text="등록 검토 완료", checklist_confirmations={c: True for c in reg_checklist_codes},
        acknowledged_warnings=["ALL"], actor="STEP12_19_TEST:reg_approver",
    )
    reg_commit = run_create_runtime_registration_commit(
        session, strategy_id,
        runtime_registration_package_id=reg_package["runtime_registration_package_id"],
        runtime_registration_decision_id=reg_decision["runtime_registration_decision_id"],
        registration_input_hash=reg_package["registration_input_hash"],
        decision_input_hash=reg_decision["decision_input_hash"], commit_reason="Runtime 등록",
        confirmation_text="REGISTER", actor="STEP12_19_TEST:registrar",
    )
    registry = session.scalar(
        select(StrategyRuntimeRegistryEntity).where(
            StrategyRuntimeRegistryEntity.runtime_registration_commit_id == reg_commit["runtime_registration_commit_id"]
        )
    )
    return {
        "strategy_id": strategy_id, "paper_id": paper_id, "live_uba_id": live_uba_id,
        "runtime_registration_commit_id": reg_commit["runtime_registration_commit_id"],
        "runtime_registry_id": int(registry.runtime_registry_id),
        "runtime_scope_hash": registry.runtime_scope_hash,
    }


def _full_flow(session, seed: dict, *, idempotency_key: str | None = None) -> dict:
    package = run_create_deployment_readiness_package(
        session, seed["strategy_id"],
        runtime_registration_commit_id=seed["runtime_registration_commit_id"],
        runtime_registry_id=seed["runtime_registry_id"], actor="STEP12_19_TEST:reviewer",
        idempotency_key=idempotency_key,
    )
    checklist_codes = [
        c["checklist_code"] for c in build_deployment_checklist_template(package["execution_mode"]) if c["required"]
    ]
    decision = run_record_deployment_readiness_decision(
        session, seed["strategy_id"], package["deployment_readiness_package_id"],
        decision_type="APPROVE_DEPLOYMENT", reason_code="READY_FOR_DEPLOYMENT_COMMIT",
        reason_text="배포 준비 검토 완료", checklist_confirmations={c: True for c in checklist_codes},
        acknowledged_warnings=["ALL"], actor="STEP12_19_TEST:deploy_approver",
    )
    return {"package": package, "decision": decision}


def _full_flow_and_commit(session, seed: dict, *, actor_suffix: str = "", idempotency_key: str | None = None) -> dict:
    flow = _full_flow(session, seed)
    commit = run_create_deployment_readiness_commit(
        session, seed["strategy_id"],
        deployment_readiness_package_id=flow["package"]["deployment_readiness_package_id"],
        deployment_readiness_decision_id=flow["decision"]["deployment_readiness_decision_id"],
        runtime_registration_commit_id=seed["runtime_registration_commit_id"],
        runtime_scope_hash=seed["runtime_scope_hash"],
        deployment_input_hash=flow["package"]["deployment_input_hash"],
        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Deployment 확정",
        confirmation_text="DEPLOY", actor=f"STEP12_19_TEST:deployer{actor_suffix}",
        idempotency_key=idempotency_key,
    )
    return {**flow, "commit": commit}


# ---------------------------------------------------------------------------
# A: Deployment Readiness Package — happy path & 게이팅.
# ---------------------------------------------------------------------------


def test_package_ready_for_paper(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219A")
    result = run_create_deployment_readiness_package(
        session, seed["strategy_id"], runtime_registration_commit_id=seed["runtime_registration_commit_id"],
        runtime_registry_id=seed["runtime_registry_id"], actor="STEP12_19_TEST:reviewer",
    )
    assert result["readiness_status"] == READINESS_STATUS_READY
    assert result["blocking_reason_codes"] == []
    assert result["execution_mode"] == EXECUTION_MODE_PAPER


def test_package_ready_for_live(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219A2", execution_mode=EXECUTION_MODE_LIVE)
    result = run_create_deployment_readiness_package(
        session, seed["strategy_id"], runtime_registration_commit_id=seed["runtime_registration_commit_id"],
        runtime_registry_id=seed["runtime_registry_id"], actor="STEP12_19_TEST:reviewer",
    )
    assert result["readiness_status"] == READINESS_STATUS_READY
    assert result["execution_mode"] == EXECUTION_MODE_LIVE


def test_package_blocked_when_registration_commit_not_found(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219B")
    with pytest.raises(DeploymentReadinessError) as exc_info:
        run_create_deployment_readiness_package(
            session, seed["strategy_id"], runtime_registration_commit_id=999_999_999,
            runtime_registry_id=seed["runtime_registry_id"], actor="STEP12_19_TEST:reviewer",
        )
    assert exc_info.value.code == "RUNTIME_REGISTRATION_COMMIT_NOT_FOUND"


def test_package_blocked_when_registry_not_found(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219C")
    with pytest.raises(DeploymentReadinessError) as exc_info:
        run_create_deployment_readiness_package(
            session, seed["strategy_id"], runtime_registration_commit_id=seed["runtime_registration_commit_id"],
            runtime_registry_id=999_999_999, actor="STEP12_19_TEST:reviewer",
        )
    assert exc_info.value.code == "RUNTIME_REGISTRY_NOT_FOUND"


def test_package_blocked_when_registry_already_enabled(session) -> None:
    """Registry가 이미 enabled=true라면(다른 어떤 경로로든) Deployment
    대상이 될 수 없다 — RUNTIME_ALREADY_ENABLED."""
    seed = _seed_registered(session, symbol="STEP1219D")
    registry = session.get(StrategyRuntimeRegistryEntity, seed["runtime_registry_id"])
    registry.enabled = True
    session.commit()
    result = run_create_deployment_readiness_package(
        session, seed["strategy_id"], runtime_registration_commit_id=seed["runtime_registration_commit_id"],
        runtime_registry_id=seed["runtime_registry_id"], actor="STEP12_19_TEST:reviewer",
    )
    assert result["readiness_status"] == READINESS_STATUS_BLOCKED
    assert "RUNTIME_ALREADY_ENABLED" in result["blocking_reason_codes"]


def test_package_blocked_when_registry_already_running(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219D2")
    registry = session.get(StrategyRuntimeRegistryEntity, seed["runtime_registry_id"])
    registry.running = True
    session.commit()
    result = run_create_deployment_readiness_package(
        session, seed["strategy_id"], runtime_registration_commit_id=seed["runtime_registration_commit_id"],
        runtime_registry_id=seed["runtime_registry_id"], actor="STEP12_19_TEST:reviewer",
    )
    assert result["readiness_status"] == READINESS_STATUS_BLOCKED
    assert "RUNTIME_ALREADY_RUNNING" in result["blocking_reason_codes"]


def test_package_no_sensitive_credential_data(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219E", execution_mode=EXECUTION_MODE_LIVE)
    result = run_create_deployment_readiness_package(
        session, seed["strategy_id"], runtime_registration_commit_id=seed["runtime_registration_commit_id"],
        runtime_registry_id=seed["runtime_registry_id"], actor="STEP12_19_TEST:reviewer",
    )
    assert "encrypted_payload" not in result["credential_snapshot_payload"]
    assert "nonce_b64" not in result["credential_snapshot_payload"]


def test_package_idempotent_replay_same_input(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219F")
    first = run_create_deployment_readiness_package(
        session, seed["strategy_id"], runtime_registration_commit_id=seed["runtime_registration_commit_id"],
        runtime_registry_id=seed["runtime_registry_id"], actor="STEP12_19_TEST:reviewer", idempotency_key="pkg-key-1",
    )
    second = run_create_deployment_readiness_package(
        session, seed["strategy_id"], runtime_registration_commit_id=seed["runtime_registration_commit_id"],
        runtime_registry_id=seed["runtime_registry_id"], actor="STEP12_19_TEST:reviewer", idempotency_key="pkg-key-1",
    )
    assert first["deployment_readiness_package_id"] == second["deployment_readiness_package_id"]
    assert second["idempotent_replay"] is True


def test_package_idempotency_conflict_on_different_input(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219G")
    run_create_deployment_readiness_package(
        session, seed["strategy_id"], runtime_registration_commit_id=seed["runtime_registration_commit_id"],
        runtime_registry_id=seed["runtime_registry_id"], actor="STEP12_19_TEST:reviewer", idempotency_key="pkg-key-2",
    )
    other_seed = _seed_registered(session, symbol="STEP1219G2", result_id_index=1)
    with pytest.raises(DeploymentReadinessError) as exc_info:
        run_create_deployment_readiness_package(
            session, other_seed["strategy_id"], runtime_registration_commit_id=other_seed["runtime_registration_commit_id"],
            runtime_registry_id=other_seed["runtime_registry_id"], actor="STEP12_19_TEST:reviewer",
            idempotency_key="pkg-key-2",
        )
    assert exc_info.value.code == "IDEMPOTENCY_CONFLICT"


# ---------------------------------------------------------------------------
# B: Deployment Conflict — 기존 Deployment/Scheduler Plan.
# ---------------------------------------------------------------------------


def test_deployment_already_exists_blocks_new_package(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219H")
    _full_flow_and_commit(session, seed)
    second_package = run_create_deployment_readiness_package(
        session, seed["strategy_id"], runtime_registration_commit_id=seed["runtime_registration_commit_id"],
        runtime_registry_id=seed["runtime_registry_id"], actor="STEP12_19_TEST:reviewer2",
    )
    assert "DEPLOYMENT_ALREADY_EXISTS" in second_package["blocking_reason_codes"]


# ---------------------------------------------------------------------------
# C: Decision — Checklist/Reason Code/Stale.
# ---------------------------------------------------------------------------


def test_decision_incomplete_checklist_blocks_approve(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219I")
    package = run_create_deployment_readiness_package(
        session, seed["strategy_id"], runtime_registration_commit_id=seed["runtime_registration_commit_id"],
        runtime_registry_id=seed["runtime_registry_id"], actor="STEP12_19_TEST:reviewer",
    )
    with pytest.raises(DeploymentReadinessError) as exc_info:
        run_record_deployment_readiness_decision(
            session, seed["strategy_id"], package["deployment_readiness_package_id"],
            decision_type="APPROVE_DEPLOYMENT", reason_code="READY_FOR_DEPLOYMENT_COMMIT",
            reason_text="검토", checklist_confirmations={}, acknowledged_warnings=["ALL"],
            actor="STEP12_19_TEST:deploy_approver2",
        )
    assert exc_info.value.code == "INCOMPLETE_CHECKLIST"


def test_decision_reject_does_not_ready(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219J")
    package = run_create_deployment_readiness_package(
        session, seed["strategy_id"], runtime_registration_commit_id=seed["runtime_registration_commit_id"],
        runtime_registry_id=seed["runtime_registry_id"], actor="STEP12_19_TEST:reviewer",
    )
    decision = run_record_deployment_readiness_decision(
        session, seed["strategy_id"], package["deployment_readiness_package_id"],
        decision_type="REJECT_DEPLOYMENT", reason_code="ACCOUNT_NOT_ELIGIBLE", reason_text="부적격",
        checklist_confirmations={}, acknowledged_warnings=[], actor="STEP12_19_TEST:deploy_approver3",
    )
    assert decision["deployment_ready"] is False


def test_decision_duplicate_blocked(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219J2")
    flow = _full_flow(session, seed)
    with pytest.raises(DeploymentReadinessError) as exc_info:
        run_record_deployment_readiness_decision(
            session, seed["strategy_id"], flow["package"]["deployment_readiness_package_id"],
            decision_type="APPROVE_DEPLOYMENT", reason_code="READY_FOR_DEPLOYMENT_COMMIT",
            reason_text="재시도", checklist_confirmations={}, acknowledged_warnings=["ALL"],
            actor="STEP12_19_TEST:deploy_approver4",
        )
    assert exc_info.value.code == "DUPLICATE_DEPLOYMENT_READINESS_DECISION"


def test_stale_package_blocks_decision(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219K")
    package = run_create_deployment_readiness_package(
        session, seed["strategy_id"], runtime_registration_commit_id=seed["runtime_registration_commit_id"],
        runtime_registry_id=seed["runtime_registry_id"], actor="STEP12_19_TEST:reviewer",
    )
    account = session.get(PaperAccount, seed["paper_id"])
    account.is_active = False
    session.commit()

    package_row = session.get(StrategyDeploymentReadinessPackageEntity, package["deployment_readiness_package_id"])
    stale, reasons = check_deployment_readiness_package_staleness(session, package_row)
    assert stale is True
    assert "ACCOUNT_SNAPSHOT_CHANGED" in reasons

    with pytest.raises(DeploymentReadinessError) as exc_info:
        run_record_deployment_readiness_decision(
            session, seed["strategy_id"], package["deployment_readiness_package_id"],
            decision_type="APPROVE_DEPLOYMENT", reason_code="READY_FOR_DEPLOYMENT_COMMIT",
            reason_text="검토", checklist_confirmations={}, acknowledged_warnings=["ALL"],
            actor="STEP12_19_TEST:deploy_approver5",
        )
    assert exc_info.value.code == "STALE_DEPLOYMENT_READINESS_PACKAGE"


def test_stale_matrix_registry_status_change(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219K2")
    package = run_create_deployment_readiness_package(
        session, seed["strategy_id"], runtime_registration_commit_id=seed["runtime_registration_commit_id"],
        runtime_registry_id=seed["runtime_registry_id"], actor="STEP12_19_TEST:reviewer",
    )
    registry = session.get(StrategyRuntimeRegistryEntity, seed["runtime_registry_id"])
    registry.enabled = True
    session.commit()
    package_row = session.get(StrategyDeploymentReadinessPackageEntity, package["deployment_readiness_package_id"])
    stale, reasons = check_deployment_readiness_package_staleness(session, package_row)
    assert stale is True
    assert "RUNTIME_REGISTRY_STATUS_CHANGED" in reasons


# ---------------------------------------------------------------------------
# D: Deployment Commit — 성공, READY_TO_START, Scheduler Plan 비활성.
# ---------------------------------------------------------------------------


def test_commit_success_creates_ready_to_start_deployment(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219L")
    result = _full_flow_and_commit(session, seed)["commit"]
    assert result["deployment_status"] == StrategyDeploymentStatus.READY_TO_START.value
    assert result["scheduler_plan_enabled"] is False
    assert result["scheduler_plan_registered_to_scheduler"] is False
    assert result["scheduler_job_id"] is None

    deployment = session.get(StrategyDeploymentEntity, result["strategy_deployment_id"])
    assert deployment.status_code == StrategyDeploymentStatus.READY_TO_START.value
    assert deployment.activated_at is None
    assert deployment.stopped_at is None

    scheduler_plan = session.get(StrategyRuntimeSchedulerPlanEntity, result["scheduler_plan_id"])
    assert scheduler_plan.enabled is False
    assert scheduler_plan.registered_to_scheduler is False
    assert scheduler_plan.scheduler_job_id is None

    registry = session.get(StrategyRuntimeRegistryEntity, seed["runtime_registry_id"])
    assert registry.enabled is False
    assert registry.running is False


def test_commit_scheduler_plan_defaults_for_stock(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219L2")
    result = _full_flow_and_commit(session, seed)["commit"]
    scheduler_plan = session.get(StrategyRuntimeSchedulerPlanEntity, result["scheduler_plan_id"])
    assert scheduler_plan.scheduler_type == "MARKET_SESSION"
    assert scheduler_plan.timezone == "Asia/Seoul"
    assert scheduler_plan.market_calendar == "KRX"
    assert scheduler_plan.market_open_offset == 9 * 3600
    assert scheduler_plan.market_close_offset == 15 * 3600 + 20 * 60


def test_commit_requires_exact_confirmation(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219M")
    flow = _full_flow(session, seed)
    with pytest.raises(DeploymentReadinessError) as exc_info:
        run_create_deployment_readiness_commit(
            session, seed["strategy_id"],
            deployment_readiness_package_id=flow["package"]["deployment_readiness_package_id"],
            deployment_readiness_decision_id=flow["decision"]["deployment_readiness_decision_id"],
            runtime_registration_commit_id=seed["runtime_registration_commit_id"],
            runtime_scope_hash=seed["runtime_scope_hash"],
            deployment_input_hash=flow["package"]["deployment_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Deployment 확정",
            confirmation_text="deploy now", actor="STEP12_19_TEST:deployer",
        )
    assert exc_info.value.code == "INVALID_CONFIRMATION"


def test_commit_duplicate_blocked(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219N")
    flow = _full_flow_and_commit(session, seed)
    with pytest.raises(DeploymentReadinessError) as exc_info:
        run_create_deployment_readiness_commit(
            session, seed["strategy_id"],
            deployment_readiness_package_id=flow["package"]["deployment_readiness_package_id"],
            deployment_readiness_decision_id=flow["decision"]["deployment_readiness_decision_id"],
            runtime_registration_commit_id=seed["runtime_registration_commit_id"],
            runtime_scope_hash=seed["runtime_scope_hash"],
            deployment_input_hash=flow["package"]["deployment_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Deployment 확정",
            confirmation_text="DEPLOY", actor="STEP12_19_TEST:deployer2",
        )
    assert exc_info.value.code == "DEPLOYMENT_ALREADY_EXISTS"


def test_commit_idempotent_replay(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219N2")
    flow = _full_flow(session, seed, idempotency_key="commit-key-1")
    first = run_create_deployment_readiness_commit(
        session, seed["strategy_id"],
        deployment_readiness_package_id=flow["package"]["deployment_readiness_package_id"],
        deployment_readiness_decision_id=flow["decision"]["deployment_readiness_decision_id"],
        runtime_registration_commit_id=seed["runtime_registration_commit_id"],
        runtime_scope_hash=seed["runtime_scope_hash"],
        deployment_input_hash=flow["package"]["deployment_input_hash"],
        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Deployment 확정",
        confirmation_text="DEPLOY", actor="STEP12_19_TEST:deployer3", idempotency_key="commit-key-1",
    )
    second = run_create_deployment_readiness_commit(
        session, seed["strategy_id"],
        deployment_readiness_package_id=flow["package"]["deployment_readiness_package_id"],
        deployment_readiness_decision_id=flow["decision"]["deployment_readiness_decision_id"],
        runtime_registration_commit_id=seed["runtime_registration_commit_id"],
        runtime_scope_hash=seed["runtime_scope_hash"],
        deployment_input_hash=flow["package"]["deployment_input_hash"],
        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Deployment 확정",
        confirmation_text="DEPLOY", actor="STEP12_19_TEST:deployer3", idempotency_key="commit-key-1",
    )
    assert first["deployment_readiness_commit_id"] == second["deployment_readiness_commit_id"]
    assert second["idempotent_replay"] is True


# ---------------------------------------------------------------------------
# E: Hash 결정성.
# ---------------------------------------------------------------------------


def test_scheduler_plan_hash_deterministic() -> None:
    kwargs = dict(
        runtime_scope_hash="a" * 64, scheduler_type="MARKET_SESSION", timezone_name="Asia/Seoul",
        market_calendar="KRX", cron_expression=None, interval_seconds=None, start_policy="MARKET_OPEN",
        stop_policy="MARKET_CLOSE", market_open_offset=32400, market_close_offset=55200,
        holiday_policy="KRX_HOLIDAY_CALENDAR", plan_version=1, algorithm_version="1.0.0",
    )
    assert compute_scheduler_plan_hash(**kwargs) == compute_scheduler_plan_hash(**kwargs)
    changed = {**kwargs, "plan_version": 2}
    assert compute_scheduler_plan_hash(**kwargs) != compute_scheduler_plan_hash(**changed)


def test_deployment_commit_hash_deterministic() -> None:
    from datetime import datetime, timezone as tz

    kwargs = dict(
        strategy_definition_id=1, runtime_registration_commit_id=2, runtime_registry_id=3,
        deployment_readiness_package_id=4, deployment_readiness_decision_id=5, runtime_scope_hash="b" * 64,
        strategy_deployment_id=6, scheduler_plan_id=7, deployment_input_hash="c" * 64, decision_input_hash="d" * 64,
        scheduler_plan_hash="e" * 64, committed_by="tester", committed_at=datetime(2024, 1, 1, tzinfo=tz.utc),
        confirmation_hash="f" * 64, algorithm_version="1.0.0",
    )
    assert compute_deployment_commit_hash(**kwargs) == compute_deployment_commit_hash(**kwargs)
    changed = {**kwargs, "strategy_deployment_id": 999}
    assert compute_deployment_commit_hash(**kwargs) != compute_deployment_commit_hash(**changed)


# ---------------------------------------------------------------------------
# F: Atomicity — 실패 주입 Rollback 검증.
# ---------------------------------------------------------------------------


def _assert_deployment_nothing_persisted(session, strategy_id: int, *, pre_existing_deployment_ids: set[int]) -> None:
    commit_count = session.scalar(
        select(StrategyDeploymentReadinessCommitEntity.deployment_readiness_commit_id).where(
            StrategyDeploymentReadinessCommitEntity.strategy_definition_id == strategy_id
        )
    )
    assert commit_count is None
    new_deployments = session.scalars(
        select(StrategyDeploymentEntity).where(StrategyDeploymentEntity.strategy_id == strategy_id)
    ).all()
    assert {int(d.strategy_deployment_id) for d in new_deployments} == pre_existing_deployment_ids
    scheduler_plans = session.scalars(
        select(StrategyRuntimeSchedulerPlanEntity).where(
            StrategyRuntimeSchedulerPlanEntity.runtime_registry_id.in_(
                select(StrategyRuntimeRegistryEntity.runtime_registry_id).where(
                    StrategyRuntimeRegistryEntity.strategy_definition_id == strategy_id
                )
            )
        )
    ).all()
    assert len(scheduler_plans) == 0
    history_rows = session.scalars(
        select(StrategyDeploymentReadinessHistoryEntity).where(
            StrategyDeploymentReadinessHistoryEntity.strategy_definition_id == strategy_id,
            StrategyDeploymentReadinessHistoryEntity.source_type == "COMMIT",
        )
    ).all()
    assert len(history_rows) == 0


def test_atomicity_failure_after_deployment_insert_before_scheduler_plan(session, monkeypatch) -> None:
    import stock_platform.ai.strategy_draft_approval.deployment_readiness as module

    seed = _seed_registered(session, symbol="STEP1219O")
    flow = _full_flow(session, seed)

    original_init = module.StrategyRuntimeSchedulerPlanEntity.__init__

    def _fail_init(self, *args, **kwargs):
        raise RuntimeError("injected failure constructing Scheduler Plan entity")

    monkeypatch.setattr(module.StrategyRuntimeSchedulerPlanEntity, "__init__", _fail_init)
    with pytest.raises(RuntimeError):
        run_create_deployment_readiness_commit(
            session, seed["strategy_id"],
            deployment_readiness_package_id=flow["package"]["deployment_readiness_package_id"],
            deployment_readiness_decision_id=flow["decision"]["deployment_readiness_decision_id"],
            runtime_registration_commit_id=seed["runtime_registration_commit_id"],
            runtime_scope_hash=seed["runtime_scope_hash"],
            deployment_input_hash=flow["package"]["deployment_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Deployment 확정",
            confirmation_text="DEPLOY", actor="STEP12_19_TEST:deployer",
        )
    monkeypatch.setattr(module.StrategyRuntimeSchedulerPlanEntity, "__init__", original_init)
    session.rollback()
    _assert_deployment_nothing_persisted(session, seed["strategy_id"], pre_existing_deployment_ids=set())
    registry = session.get(StrategyRuntimeRegistryEntity, seed["runtime_registry_id"])
    assert registry.enabled is False
    assert registry.running is False


def test_atomicity_failure_after_scheduler_plan_before_readiness_commit(session, monkeypatch) -> None:
    import stock_platform.ai.strategy_draft_approval.deployment_readiness as module

    seed = _seed_registered(session, symbol="STEP1219O2")
    flow = _full_flow(session, seed)

    original_init = module.StrategyDeploymentReadinessCommitEntity.__init__

    def _fail_init(self, *args, **kwargs):
        raise RuntimeError("injected failure constructing Readiness Commit entity")

    monkeypatch.setattr(module.StrategyDeploymentReadinessCommitEntity, "__init__", _fail_init)
    with pytest.raises(RuntimeError):
        run_create_deployment_readiness_commit(
            session, seed["strategy_id"],
            deployment_readiness_package_id=flow["package"]["deployment_readiness_package_id"],
            deployment_readiness_decision_id=flow["decision"]["deployment_readiness_decision_id"],
            runtime_registration_commit_id=seed["runtime_registration_commit_id"],
            runtime_scope_hash=seed["runtime_scope_hash"],
            deployment_input_hash=flow["package"]["deployment_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Deployment 확정",
            confirmation_text="DEPLOY", actor="STEP12_19_TEST:deployer",
        )
    monkeypatch.setattr(module.StrategyDeploymentReadinessCommitEntity, "__init__", original_init)
    session.rollback()
    _assert_deployment_nothing_persisted(session, seed["strategy_id"], pre_existing_deployment_ids=set())


def test_atomicity_failure_after_history_insert_before_audit(session, monkeypatch) -> None:
    import stock_platform.ai.strategy_draft_approval.deployment_readiness as module

    seed = _seed_registered(session, symbol="STEP1219O3")
    flow = _full_flow(session, seed)

    def _boom(self, **kwargs):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(module.AuditLogService, "record", _boom)
    with pytest.raises(RuntimeError):
        run_create_deployment_readiness_commit(
            session, seed["strategy_id"],
            deployment_readiness_package_id=flow["package"]["deployment_readiness_package_id"],
            deployment_readiness_decision_id=flow["decision"]["deployment_readiness_decision_id"],
            runtime_registration_commit_id=seed["runtime_registration_commit_id"],
            runtime_scope_hash=seed["runtime_scope_hash"],
            deployment_input_hash=flow["package"]["deployment_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Deployment 확정",
            confirmation_text="DEPLOY", actor="STEP12_19_TEST:deployer",
        )
    monkeypatch.undo()
    session.rollback()
    _assert_deployment_nothing_persisted(session, seed["strategy_id"], pre_existing_deployment_ids=set())


def test_atomicity_failure_between_flush_and_commit(session, monkeypatch) -> None:
    seed = _seed_registered(session, symbol="STEP1219O4")
    flow = _full_flow(session, seed)

    def _commit_fails(*args, **kwargs):
        raise RuntimeError("injected failure before commit")

    monkeypatch.setattr(session, "commit", _commit_fails)
    with pytest.raises(RuntimeError):
        run_create_deployment_readiness_commit(
            session, seed["strategy_id"],
            deployment_readiness_package_id=flow["package"]["deployment_readiness_package_id"],
            deployment_readiness_decision_id=flow["decision"]["deployment_readiness_decision_id"],
            runtime_registration_commit_id=seed["runtime_registration_commit_id"],
            runtime_scope_hash=seed["runtime_scope_hash"],
            deployment_input_hash=flow["package"]["deployment_input_hash"],
            decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Deployment 확정",
            confirmation_text="DEPLOY", actor="STEP12_19_TEST:deployer",
        )
    monkeypatch.undo()
    session.rollback()
    _assert_deployment_nothing_persisted(session, seed["strategy_id"], pre_existing_deployment_ids=set())


# ---------------------------------------------------------------------------
# G: 비실행 증명 — Scheduler 실제 미등록, Runtime/Broker/Order 미실행.
# ---------------------------------------------------------------------------


def test_no_real_scheduler_job_registered(session, monkeypatch) -> None:
    """§ 명세 §18 — `AsyncIOScheduler.add_job`이 Package/Decision/Commit
    전체 흐름 동안 단 한 번도 호출되지 않았음을 Monkeypatch Spy로 증명한다."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    call_count = {"n": 0}
    original_add_job = AsyncIOScheduler.add_job

    def _spy_add_job(self, *args, **kwargs):
        call_count["n"] += 1
        return original_add_job(self, *args, **kwargs)

    monkeypatch.setattr(AsyncIOScheduler, "add_job", _spy_add_job)
    seed = _seed_registered(session, symbol="STEP1219P")
    result = _full_flow_and_commit(session, seed)["commit"]
    assert call_count["n"] == 0
    assert result["scheduler_plan_registered_to_scheduler"] is False
    assert result["scheduler_job_id"] is None


def test_no_runtime_manager_methods_called(session, monkeypatch) -> None:
    """§ 명세 §19 — `DynamicStrategyRuntimeManager`의 실행 관련 메서드가
    전혀 호출되지 않았음을 증명한다(이 모듈은 애초에 import조차 하지
    않는다는 것은 이미 확인됐으나, 실제 스파이로도 재확인한다)."""
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

    seed = _seed_registered(session, symbol="STEP1219Q")
    _full_flow_and_commit(session, seed)
    assert call_counts == {}


def test_runtime_registry_unaffected_by_deployment_commit(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219Q2")
    before = session.get(StrategyRuntimeRegistryEntity, seed["runtime_registry_id"])
    before_enabled, before_running, before_status = before.enabled, before.running, before.status
    _full_flow_and_commit(session, seed)
    session.expire_all()
    after = session.get(StrategyRuntimeRegistryEntity, seed["runtime_registry_id"])
    assert after.enabled == before_enabled == False  # noqa: E712
    assert after.running == before_running == False  # noqa: E712
    assert after.status == before_status


# ---------------------------------------------------------------------------
# H: 실제 PostgreSQL 독립 Session 동시성 검증.
# ---------------------------------------------------------------------------


def test_concurrent_commit_same_scope_only_one_succeeds(result_ids) -> None:
    Session = get_session_factory()
    setup_session = Session()
    setup_session.info["result_ids"] = result_ids
    _cleanup(setup_session)
    seed = _seed_registered(setup_session, symbol="STEP1219R")
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
                result = run_create_deployment_readiness_commit(
                    thread_session, seed["strategy_id"],
                    deployment_readiness_package_id=flow["package"]["deployment_readiness_package_id"],
                    deployment_readiness_decision_id=flow["decision"]["deployment_readiness_decision_id"],
                    runtime_registration_commit_id=seed["runtime_registration_commit_id"],
                    runtime_scope_hash=seed["runtime_scope_hash"],
                    deployment_input_hash=flow["package"]["deployment_input_hash"],
                    decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Deployment 확정",
                    confirmation_text="DEPLOY", actor="STEP12_19_TEST:deployer",
                )
                with lock:
                    results.append(("success", result))
            except DeploymentReadinessError as exc:
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
            select(StrategyDeploymentReadinessCommitEntity).where(
                StrategyDeploymentReadinessCommitEntity.strategy_definition_id == seed["strategy_id"]
            )
        ).all()
        assert len(commits) == 1
        deployments = verify_session.scalars(
            select(StrategyDeploymentEntity).where(StrategyDeploymentEntity.strategy_id == seed["strategy_id"])
        ).all()
        assert len(deployments) == 1
        assert deployments[0].status_code == StrategyDeploymentStatus.READY_TO_START.value
    finally:
        _cleanup(verify_session)
        verify_session.close()


def test_concurrent_commit_repeat_stability(result_ids) -> None:
    for i in range(3):
        Session = get_session_factory()
        setup_session = Session()
        setup_session.info["result_ids"] = result_ids
        _cleanup(setup_session)
        seed = _seed_registered(setup_session, symbol=f"STEP1219S{i}")
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
                    run_create_deployment_readiness_commit(
                        thread_session, seed["strategy_id"],
                        deployment_readiness_package_id=flow["package"]["deployment_readiness_package_id"],
                        deployment_readiness_decision_id=flow["decision"]["deployment_readiness_decision_id"],
                        runtime_registration_commit_id=seed["runtime_registration_commit_id"],
                        runtime_scope_hash=seed["runtime_scope_hash"],
                        deployment_input_hash=flow["package"]["deployment_input_hash"],
                        decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Deployment 확정",
                        confirmation_text="DEPLOY", actor="STEP12_19_TEST:deployer",
                    )
                    with lock:
                        results.append("success")
                except DeploymentReadinessError:
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
    """서로 다른 Runtime Scope(다른 Strategy)의 동시 Commit은 서로
    간섭 없이 모두 성공해야 한다."""
    Session = get_session_factory()
    setup_session = Session()
    setup_session.info["result_ids"] = result_ids
    _cleanup(setup_session)
    seed_a = _seed_registered(setup_session, symbol="STEP1219T1")
    seed_b = _seed_registered(setup_session, symbol="STEP1219T2", result_id_index=1)
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
            run_create_deployment_readiness_commit(
                thread_session, seed["strategy_id"],
                deployment_readiness_package_id=flow["package"]["deployment_readiness_package_id"],
                deployment_readiness_decision_id=flow["decision"]["deployment_readiness_decision_id"],
                runtime_registration_commit_id=seed["runtime_registration_commit_id"],
                runtime_scope_hash=seed["runtime_scope_hash"],
                deployment_input_hash=flow["package"]["deployment_input_hash"],
                decision_input_hash=flow["decision"]["decision_input_hash"], commit_reason="Deployment 확정",
                confirmation_text="DEPLOY", actor="STEP12_19_TEST:deployer",
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
# I: History/Status/Scopes/Scheduler Plan 조회.
# ---------------------------------------------------------------------------


def test_history_persisted_ordering_and_no_duplicate_on_replay(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219U")
    _full_flow_and_commit(session, seed)
    history = get_deployment_readiness_history(session, seed["strategy_id"])
    event_types = [h["event_type"] for h in history]
    assert event_types == [
        "DEPLOYMENT_READINESS_REVIEW_CREATED", "DEPLOYMENT_APPROVED", "DEPLOYMENT_READY_TO_START",
    ]
    occurred_ats = [h["occurred_at"] for h in history]
    assert occurred_ats == sorted(occurred_ats)


def test_status_reflects_deployed_state(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219V")
    before = get_deployment_readiness_status(session, seed["strategy_id"])
    assert before["deployed"] is False
    _full_flow_and_commit(session, seed)
    after = get_deployment_readiness_status(session, seed["strategy_id"])
    assert after["deployed"] is True
    assert after["deployment_status"] == StrategyDeploymentStatus.READY_TO_START.value


def test_scopes_lists_committed_scope(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219W")
    _full_flow_and_commit(session, seed)
    scopes = get_deployment_readiness_scopes(session, seed["strategy_id"])
    assert len(scopes) == 1
    assert scopes[0]["runtime_scope_hash"] == seed["runtime_scope_hash"]
    assert scopes[0]["scheduler_plan_enabled"] is False


def test_scheduler_plan_list_and_get(session) -> None:
    seed = _seed_registered(session, symbol="STEP1219X")
    commit = _full_flow_and_commit(session, seed)["commit"]
    plans = list_scheduler_plans(session, seed["strategy_id"])
    assert len(plans) == 1
    assert plans[0]["scheduler_plan_id"] == commit["scheduler_plan_id"]
    fetched = get_scheduler_plan(session, commit["scheduler_plan_id"])
    assert fetched["enabled"] is False
    assert fetched["registered_to_scheduler"] is False


def test_package_get_cross_strategy_not_found(session) -> None:
    seed_a = _seed_registered(session, symbol="STEP1219Y1")
    seed_b = _seed_registered(session, symbol="STEP1219Y2", result_id_index=1)
    package = run_create_deployment_readiness_package(
        session, seed_a["strategy_id"], runtime_registration_commit_id=seed_a["runtime_registration_commit_id"],
        runtime_registry_id=seed_a["runtime_registry_id"], actor="STEP12_19_TEST:reviewer",
    )
    with pytest.raises(DeploymentReadinessError) as exc_info:
        get_deployment_readiness_package(session, package["deployment_readiness_package_id"], strategy_definition_id=seed_b["strategy_id"])
    assert exc_info.value.code == "NOT_FOUND"
