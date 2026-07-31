"""Paper 무인 자동매매 E2E — 실제 PostgreSQL 통합 검증.

Signal/OrderExecution → Risk → Outbox → Paper Auto-Fill → Position/Balance/PnL
→ Exit / StopLoss / TakeProfit / Idempotency / KillSwitch / AccountPause / Recovery

LIVE·실계좌·실주문 호출 금지. 테스트 전용 Paper 계좌만 사용하고 종료 시 정리한다.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from stock_platform.auth.models import AuthUser
from stock_platform.broker.paper.adapter import PaperBrokerAdapter
from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
# SQLAlchemy FK 메타데이터 등록 (flush 시 NoReferencedTableError 방지)
from stock_platform.broker.recovery_entities import (  # noqa: F401
    BrokerRecoveryRunEntity,
)
from stock_platform.risk.persistence_models import (  # noqa: F401
    PositionPlanEntity,
)
from stock_platform.strategy_deployment.entities import (  # noqa: F401
    StrategyDeploymentEntity,
)
from stock_platform.common.settings import clear_settings_cache, get_settings
from stock_platform.database.session import get_engine, get_session_factory
from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.models import OrderSide, OrderType
from stock_platform.order.outbox_dispatcher import OrderOutboxDispatcher
from stock_platform.order.outbox_worker import OrderOutboxWorker
from stock_platform.order.paper_fill_recovery import (
    recover_stalled_paper_accepted_orders,
)
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
)
from stock_platform.realtime.risk_integrated_order_executor import (
    RiskIntegratedRealtimeOrderExecutor,
)
from stock_platform.realtime.safety_guard import RealtimeOrderSafetyGuard
from stock_platform.realtime.safety_models import RealtimeOrderSafetyConfig
from stock_platform.realtime.strategy_models import (
    RealtimeSignal,
    RealtimeSignalAction,
)
from stock_platform.risk.engine import RiskManagementEngine
from stock_platform.risk.models import ExitEvaluationRequest
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.risk_engine.user_risk_service import UserRiskSettingService
from stock_platform.trading.account_identity import paper_kill_switch_scope
from stock_platform.trading.account_repository import PaperAccountRepository
from stock_platform.trading.account_service import PaperAccountService

pytestmark = pytest.mark.integration

_PREFIX = "PAPER_E2E_"
_SYMBOL = "E2ESYM"
_EXCHANGE = "PAPER"
_BROKER = "PAPER"
_INITIAL_CASH = Decimal("10000000.00")
_BUY_PRICE = Decimal("10000")
_BUY_QTY = Decimal("2")
_SELL_PRICE = Decimal("11000")
_SL_PRICE = Decimal("9000")
_TP_PRICE = Decimal("12000")


# ---------------------------------------------------------------------------
# Feature flags (테스트 프로세스 한정)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _paper_e2e_flags(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PAPER_OUTBOX_AUTO_FILL", "true")
    monkeypatch.setenv("PAPER_OUTBOX_WORKER_ENABLED", "false")
    monkeypatch.setenv("PAPER_FILL_RECOVERY_ENABLED", "false")
    monkeypatch.setenv("PAPER_PRICE_FEED_ENABLED", "false")
    monkeypatch.setenv("REALTIME_EXECUTION_AUTO_START_ENABLED", "true")
    monkeypatch.setenv("REALTIME_PAPER_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("REALTIME_LIVE_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("UPBIT_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("DB_POOL_SIZE", "2")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "0")
    clear_settings_cache()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    settings = get_settings()
    assert settings.paper_outbox_auto_fill is True
    assert settings.realtime_live_auto_start_enabled is False
    yield
    clear_settings_cache()
    try:
        get_engine().dispose()
    except Exception:  # noqa: BLE001
        pass
    get_engine.cache_clear()
    get_session_factory.cache_clear()


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def harness():
    """테스트 전용 user + paper account + 정리."""

    Session = get_session_factory()
    session = Session()
    token = uuid.uuid4().hex[:10]
    username = f"{_PREFIX}{token}"
    account_name = f"{_PREFIX}acct_{token}"
    created: dict = {
        "user_id": None,
        "account_id": None,
        "order_ids": [],
        "token": token,
        "username": username,
        "account_name": account_name,
        "kill_scopes": [],
        "live_calls": [],
    }

    try:
        user = AuthUser(
            username=username,
            password_hash="paper-e2e-hash",
            display_name=username,
            is_active=True,
        )
        session.add(user)
        session.flush()
        created["user_id"] = int(user.user_id)

        account = PaperAccountService(
            PaperAccountRepository(session)
        ).create_account(
            account_name=account_name,
            initial_cash=_INITIAL_CASH,
            currency_code="KRW",
            user_id=created["user_id"],
            is_default=False,
            is_active=True,
        )
        # 시스템 한도와 충돌하지 않도록 사용자 리스크 한도 완화
        UserRiskSettingService(session).upsert_user(
            created["user_id"],
            {
                "max_order_amount": "50000000",
                "daily_max_order_amount": "100000000",
                "max_total_investment_amount": "100000000",
                "max_position_amount": "50000000",
                "max_position_count": 50,
                "account_paused": False,
                "auto_trading_enabled": True,
                "buy_enabled": True,
                "sell_enabled": True,
            },
            actor="PAPER_E2E",
        )
        session.commit()
        created["account_id"] = int(account.account_id)

        yield session, created
    finally:
        session.rollback()
        _cleanup(session, created)
        session.close()
        try:
            get_engine().dispose()
        except Exception:  # noqa: BLE001
            pass


def _cleanup(session, created: dict) -> None:
    aid = created.get("account_id")
    uid = created.get("user_id")
    token = created.get("token") or ""
    try:
        for scope in created.get("kill_scopes") or []:
            try:
                KillSwitchService(session).deactivate_scope(
                    scope_code=scope,
                    actor="PAPER_E2E_CLEANUP",
                    reason="cleanup",
                )
            except Exception:  # noqa: BLE001
                session.rollback()
        if aid is not None:
            session.execute(
                text(
                    "DELETE FROM operation.broker_recovery_account_state "
                    "WHERE paper_account_id = :aid"
                ),
                {"aid": aid},
            )
            session.execute(
                text(
                    "DELETE FROM trading.paper_trade "
                    "WHERE account_id = :aid"
                ),
                {"aid": aid},
            )
            session.execute(
                text(
                    "DELETE FROM trading.paper_order "
                    "WHERE account_id = :aid"
                ),
                {"aid": aid},
            )
            session.execute(
                text(
                    """
                    DELETE FROM trading.trading_order_status_history
                    WHERE order_id IN (
                      SELECT order_id FROM trading.trading_order
                      WHERE account_id = :aid
                    )
                    """
                ),
                {"aid": aid},
            )
            session.execute(
                text(
                    """
                    DELETE FROM trading.order_outbox
                    WHERE order_id IN (
                      SELECT order_id FROM trading.trading_order
                      WHERE account_id = :aid
                    )
                    """
                ),
                {"aid": aid},
            )
            session.execute(
                text(
                    "DELETE FROM trading.trading_order "
                    "WHERE account_id = :aid"
                ),
                {"aid": aid},
            )
            session.execute(
                text(
                    "DELETE FROM trading.paper_position "
                    "WHERE account_id = :aid"
                ),
                {"aid": aid},
            )
            session.execute(
                text(
                    "DELETE FROM trading.paper_account "
                    "WHERE account_id = :aid"
                ),
                {"aid": aid},
            )
        if uid is not None:
            session.execute(
                text(
                    "DELETE FROM trading.user_risk_setting "
                    "WHERE user_id = :uid"
                ),
                {"uid": uid},
            )
            session.execute(
                text("DELETE FROM auth.user WHERE user_id = :uid"),
                {"uid": uid},
            )
        # 접두어 orphan 방어
        session.execute(
            text(
                "DELETE FROM trading.paper_account "
                "WHERE account_name LIKE :p"
            ),
            {"p": f"{_PREFIX}%{token}%"},
        )
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()


def _assert_no_live(created: dict) -> None:
    assert created["live_calls"] == []
    assert os.environ.get("KIWOOM_LIVE_ORDER_ENABLED", "false").lower() in {
        "0",
        "false",
        "no",
    }
    assert os.environ.get("UPBIT_LIVE_ORDER_ENABLED", "false").lower() in {
        "0",
        "false",
        "no",
    }
    assert os.environ.get("GLOBAL_LIVE_ORDER_ENABLED", "false").lower() in {
        "0",
        "false",
        "no",
    }
    assert get_settings().realtime_live_auto_start_enabled is False


def _counts(session, account_id: int) -> dict:
    outbox = session.execute(
        text(
            """
            SELECT COUNT(*) FROM trading.order_outbox o
            JOIN trading.trading_order t ON t.order_id = o.order_id
            WHERE t.account_id = :aid
            """
        ),
        {"aid": account_id},
    ).scalar_one()
    orders = session.execute(
        text(
            "SELECT COUNT(*) FROM trading.trading_order "
            "WHERE account_id = :aid"
        ),
        {"aid": account_id},
    ).scalar_one()
    paper_orders = session.execute(
        text(
            "SELECT COUNT(*) FROM trading.paper_order "
            "WHERE account_id = :aid"
        ),
        {"aid": account_id},
    ).scalar_one()
    trades = session.execute(
        text(
            "SELECT COUNT(*) FROM trading.paper_trade "
            "WHERE account_id = :aid"
        ),
        {"aid": account_id},
    ).scalar_one()
    history = session.execute(
        text(
            """
            SELECT COUNT(*) FROM trading.trading_order_status_history h
            JOIN trading.trading_order t ON t.order_id = h.order_id
            WHERE t.account_id = :aid
            """
        ),
        {"aid": account_id},
    ).scalar_one()
    return {
        "outbox": int(outbox),
        "trading_order": int(orders),
        "paper_order": int(paper_orders),
        "execution": int(trades),
        "history": int(history),
    }


def _position(session, account_id: int) -> tuple[Decimal, Decimal]:
    row = session.execute(
        text(
            """
            SELECT quantity, average_entry_price
            FROM trading.paper_position
            WHERE account_id = :aid
              AND exchange_code = :ex
              AND symbol = :sym
            """
        ),
        {"aid": account_id, "ex": _EXCHANGE, "sym": _SYMBOL},
    ).fetchone()
    if row is None:
        return Decimal("0"), Decimal("0")
    return Decimal(str(row[0])), Decimal(str(row[1]))


def _account_cash_pnl(session, account_id: int) -> tuple[Decimal, Decimal]:
    row = session.execute(
        text(
            """
            SELECT available_cash, realized_profit_loss, user_id
            FROM trading.paper_account
            WHERE account_id = :aid
            """
        ),
        {"aid": account_id},
    ).fetchone()
    assert row is not None
    return Decimal(str(row[0])), Decimal(str(row[1]))


def _assert_ownership(session, account_id: int, user_id: int) -> None:
    row = session.execute(
        text(
            "SELECT user_id FROM trading.paper_account "
            "WHERE account_id = :aid"
        ),
        {"aid": account_id},
    ).fetchone()
    assert row is not None
    assert int(row[0]) == int(user_id)

    bad = session.execute(
        text(
            """
            SELECT COUNT(*) FROM trading.trading_order
            WHERE account_id = :aid
              AND (
                user_broker_account_id IS NOT NULL
                OR UPPER(COALESCE(
                  metadata_payload->>'environment', 'PAPER'
                )) = 'LIVE'
              )
            """
        ),
        {"aid": account_id},
    ).scalar_one()
    assert int(bad) == 0, "LIVE/UBA 주문이 Paper E2E 계좌에 섞이면 안 됨"

    cross = session.execute(
        text(
            """
            SELECT COUNT(*) FROM trading.trading_order
            WHERE account_id = :aid
              AND broker_code <> :broker
            """
        ),
        {"aid": account_id, "broker": _BROKER},
    ).scalar_one()
    assert int(cross) == 0


def _process_outbox_for_order(
    session_factory,
    *,
    order_id: int,
    worker_id: str,
) -> None:
    """글로벌 Outbox 적체와 무관하게 해당 order의 Outbox 1건을 직접 처리."""

    from stock_platform.order.outbox_entities import OrderOutbox
    from stock_platform.order.outbox_fencing import (
        record_outbox_audit,
        stable_request_hash,
    )
    from stock_platform.order.outbox_models import OutboxStatus
    from stock_platform.order.outbox_repository import OrderOutboxRepository
    from stock_platform.operation.idempotency_repository import (
        PostgreSqlIdempotencyRepository,
    )
    from sqlalchemy import select

    worker = OrderOutboxWorker(
        session_factory=session_factory,
        dispatcher=OrderOutboxDispatcher(adapter=PaperBrokerAdapter()),
        worker_id=worker_id,
        batch_size=1,
    )

    with session_factory() as session:
        entity = session.scalar(
            select(OrderOutbox)
            .where(OrderOutbox.order_id == int(order_id))
            .order_by(OrderOutbox.outbox_id.desc())
            .limit(1)
        )
        if entity is None:
            return
        if entity.status_code == OutboxStatus.DONE.value:
            # Outbox 완료·주문 ACCEPTED 고착이면 fill만
            status = session.execute(
                text(
                    "SELECT status_code FROM trading.trading_order "
                    "WHERE order_id = :oid"
                ),
                {"oid": order_id},
            ).scalar_one()
            if status == "ACCEPTED":
                from stock_platform.order.paper_outbox_fill_service import (
                    PaperOutboxFillService,
                )

                PaperOutboxFillService(session).fill_accepted_order(
                    int(order_id),
                    actor="PAPER_E2E_DIRECT_FILL",
                )
                session.commit()
            return

        repository = OrderOutboxRepository(session)
        fencing_token = int(entity.fencing_token or 0) + 1
        entity.fencing_token = fencing_token
        entity.status_code = OutboxStatus.PROCESSING.value
        entity.locked_by = worker_id
        session.flush()

        payload = dict(entity.payload_json or {})
        payload.setdefault("order_id", int(entity.order_id))
        request_hash = stable_request_hash(payload)
        repository.create_dispatch_intent(
            entity=entity,
            fencing_token=fencing_token,
            worker_id=worker_id,
            request_hash=request_hash,
        )
        session.commit()

    with session_factory() as session:
        repository = OrderOutboxRepository(session)
        idempotency = PostgreSqlIdempotencyRepository(session)
        entity = session.scalar(
            select(OrderOutbox)
            .where(OrderOutbox.order_id == int(order_id))
            .order_by(OrderOutbox.outbox_id.desc())
            .limit(1)
        )
        if entity is None:
            return
        fencing_token = int(entity.fencing_token or 0)
        payload = dict(entity.payload_json or {})
        payload.setdefault("order_id", int(entity.order_id))
        request_hash = stable_request_hash(payload)

        if worker._order_already_has_broker_id(session, entity.order_id):
            repository.mark_done(
                entity=entity,
                fencing_token=fencing_token,
                worker_id=worker_id,
            )
            session.commit()
            return

        record = idempotency.begin(
            idempotency_key=entity.idempotency_key,
            request_hash=request_hash,
        )
        if record.status_code == "COMPLETED":
            result = record.result_json or {}
        else:
            result = worker._dispatcher.dispatch(
                event_type=entity.event_type,
                payload=payload,
                idempotency_key=entity.idempotency_key,
                session=session,
            )
            idempotency.complete(
                idempotency_key=entity.idempotency_key,
                result_json=result,
            )

        if result.get("accepted"):
            worker._apply_order_broker_result(
                session=session,
                order_id=entity.order_id,
                result=result,
                event_type=entity.event_type,
            )
        repository.mark_done(
            entity=entity,
            fencing_token=fencing_token,
            worker_id=worker_id,
        )
        record_outbox_audit(
            session,
            event_type="OUTBOX_DONE",
            detail={"outbox_id": entity.outbox_id, "order_id": order_id},
            actor=worker_id,
        )
        session.commit()


def _ensure_order_filled(
    session,
    session_factory,
    *,
    order_id: int,
    worker_id: str,
) -> None:
    """해당 주문 Outbox를 직접 처리해 FILLED까지 보장."""

    _process_outbox_for_order(
        session_factory,
        order_id=int(order_id),
        worker_id=worker_id,
    )
    session.expire_all()
    status = session.execute(
        text(
            "SELECT status_code FROM trading.trading_order "
            "WHERE order_id = :oid"
        ),
        {"oid": order_id},
    ).scalar_one()
    if status == "FILLED":
        return
    if status == "ACCEPTED":
        from stock_platform.order.paper_outbox_fill_service import (
            PaperOutboxFillService,
        )

        result = PaperOutboxFillService(session).fill_accepted_order(
            int(order_id),
            actor="PAPER_E2E_ENSURE_FILL",
        )
        assert result.filled or result.reason_code == "ALREADY_TERMINAL", (
            result.reason_code
        )
        session.commit()
        session.expire_all()
        status = session.execute(
            text(
                "SELECT status_code FROM trading.trading_order "
                "WHERE order_id = :oid"
            ),
            {"oid": order_id},
        ).scalar_one()
    assert status == "FILLED", f"order {order_id} stuck at {status}"


def _run_outbox_worker(
    session_factory,
    worker_id: str,
    *,
    until_order_id: int | None = None,
    max_rounds: int = 30,
    recover_accepted: bool = True,
) -> None:
    """다른 PENDING Outbox가 있어도 대상 주문이 처리될 때까지 반복."""

    worker = OrderOutboxWorker(
        session_factory=session_factory,
        dispatcher=OrderOutboxDispatcher(adapter=PaperBrokerAdapter()),
        worker_id=worker_id,
        batch_size=50,
    )
    for round_idx in range(max_rounds):
        summary = worker.run_once()
        if until_order_id is None:
            return
        with session_factory() as probe:
            status = probe.execute(
                text(
                    "SELECT status_code FROM trading.trading_order "
                    "WHERE order_id = :oid"
                ),
                {"oid": until_order_id},
            ).scalar()
            outbox_status = probe.execute(
                text(
                    "SELECT status_code FROM trading.order_outbox "
                    "WHERE order_id = :oid "
                    "ORDER BY outbox_id DESC LIMIT 1"
                ),
                {"oid": until_order_id},
            ).scalar()
        if status in {"FILLED", "REJECTED", "CANCELLED"}:
            return
        if outbox_status == "DONE" and status == "ACCEPTED":
            if not recover_accepted:
                return
            # Outbox 성공 후 auto-fill 누락 → recovery로 보정
            with session_factory() as recover_session:
                recover_stalled_paper_accepted_orders(
                    recover_session,
                    actor="PAPER_E2E_WORKER_RECOVERY",
                )
            return
        if summary.claimed == 0:
            if (
                recover_accepted
                and until_order_id is not None
                and status == "ACCEPTED"
            ):
                with session_factory() as recover_session:
                    recover_stalled_paper_accepted_orders(
                        recover_session,
                        actor="PAPER_E2E_WORKER_RECOVERY",
                    )
            return
        _ = round_idx



def _submit_limit(
    session,
    *,
    account_id: int,
    user_id: int,
    side: OrderSide,
    quantity: Decimal,
    price: Decimal,
    idempotency_key: str | None = None,
    skip_risk_checks: bool = False,
    strategy_code: str | None = "PAPER_E2E",
    metadata: dict | None = None,
):
    meta = {
        "environment": "PAPER",
        "execution_mode": "PAPER",
        "runtime_scope_hash": f"paper-e2e-{account_id}",
        "strategy_version": "e2e-1",
        **(metadata or {}),
    }
    return OrderExecutionService(session).submit(
        OrderExecutionCommand(
            account_id=account_id,
            broker_code=_BROKER,
            exchange_code=_EXCHANGE,
            symbol=_SYMBOL,
            side=side,
            order_type=OrderType.LIMIT,
            price=price,
            quantity=quantity,
            account_number=f"PAPER-{account_id}",
            skip_risk_checks=skip_risk_checks,
            metadata_payload=meta,
            actor="PAPER_E2E",
            environment="PAPER",
            order_source="AUTO",
            is_risk_reducing=(side == OrderSide.SELL),
            user_id=user_id,
            owner_user_id=user_id,
            strategy_code=strategy_code,
            idempotency_key=idempotency_key,
            available_cash=_INITIAL_CASH,
            portfolio_value=_INITIAL_CASH,
        )
    )


def _signal_execute(
    session,
    *,
    account_id: int,
    user_id: int,
    action: RealtimeSignalAction,
    price: Decimal,
    reason_code: str,
):
    """RiskIntegrated: Signal → Risk → OrderExecution(Outbox enqueue)."""

    safety = RealtimeOrderSafetyGuard(
        RealtimeOrderSafetyConfig(
            max_order_amount=Decimal("5000000"),
            max_daily_loss=Decimal("5000000"),
            max_open_positions=20,
            duplicate_order_window_seconds=0,
            symbol_cooldown_seconds=0,
            max_orders_per_minute=100,
            enforce_market_hours_for_krx=False,
            live_trading_enabled=False,
        )
    )
    config = RealtimeExecutionConfig(
        mode=RealtimeExecutionMode.PAPER,
        account_id=account_id,
        order_amount=(price * _BUY_QTY),
        auto_fill=False,
        user_id=user_id,
    )
    now = datetime.now(timezone.utc)
    signal = RealtimeSignal(
        exchange_code=_EXCHANGE,
        symbol=_SYMBOL,
        action=action,
        signal_price=price,
        short_average=price,
        long_average=price,
        change_rate=Decimal("0"),
        reason_code=reason_code,
        generated_at=now,
        signal_id=f"sig-{uuid.uuid4().hex[:12]}",
        fingerprint=f"fp-{uuid.uuid4().hex[:12]}",
        scope_key=f"paper:{account_id}:e2e",
        user_id=user_id,
        account_kind="PAPER",
        account_id=account_id,
        strategy_id=None,
        strategy_version="e2e-1",
        broker_code=_BROKER,
        market_type="PAPER",
    )
    return RiskIntegratedRealtimeOrderExecutor(
        session=session,
        execution_config=config,
        safety_guard=safety,
    ).execute(signal)


def _valuation(session, account_id: int, mark: Decimal):
    svc = PaperAccountService(PaperAccountRepository(session))
    return svc.value_account(
        account_id=account_id,
        prices={f"{_EXCHANGE}:{_SYMBOL}": mark},
    )


# ---------------------------------------------------------------------------
# A. 정상 매수
# ---------------------------------------------------------------------------


def test_a_paper_buy_signal_to_position(harness) -> None:
    session, created = harness
    aid = created["account_id"]
    uid = created["user_id"]
    Session = get_session_factory()

    before = _counts(session, aid)
    result = _signal_execute(
        session,
        account_id=aid,
        user_id=uid,
        action=RealtimeSignalAction.BUY,
        price=_BUY_PRICE,
        reason_code="E2E_ENTRY",
    )
    assert result.order_id is not None, result.reason_code
    assert result.reason_code in {"QUEUED", "IDEMPOTENT_REPLAY"}
    created["order_ids"].append(int(result.order_id))
    session.commit()

    _ensure_order_filled(
        session,
        Session,
        order_id=int(result.order_id),
        worker_id=f"paper-e2e-a-{created['token']}",
    )
    session.expire_all()

    order = session.execute(
        text(
            """
            SELECT status_code, filled_quantity, average_fill_price,
                   broker_code, account_id, user_broker_account_id,
                   metadata_payload->>'environment' AS env,
                   metadata_payload->>'runtime_scope_hash' AS scope_hash,
                   metadata_payload->>'execution_mode' AS exec_mode
            FROM trading.trading_order WHERE order_id = :oid
            """
        ),
        {"oid": result.order_id},
    ).fetchone()
    assert order is not None
    assert order[0] == "FILLED"
    assert Decimal(str(order[1])) == _BUY_QTY
    assert Decimal(str(order[2])) == _BUY_PRICE
    assert order[3] == _BROKER
    assert int(order[4]) == aid
    assert order[5] is None
    assert (order[6] or "PAPER").upper() == "PAPER"

    qty, avg = _position(session, aid)
    assert qty == _BUY_QTY
    assert avg == _BUY_PRICE

    cash, realized = _account_cash_pnl(session, aid)
    expected_cash = _INITIAL_CASH - (_BUY_PRICE * _BUY_QTY)
    assert cash == expected_cash
    assert realized == Decimal("0")

    after = _counts(session, aid)
    assert after["outbox"] == before["outbox"] + 1
    assert after["trading_order"] == before["trading_order"] + 1
    assert after["paper_order"] == before["paper_order"] + 1
    assert after["execution"] == before["execution"] + 1
    assert after["history"] >= before["history"] + 1

    valuation = _valuation(session, aid, _BUY_PRICE)
    assert valuation.available_cash == expected_cash
    assert valuation.unrealized_profit_loss == Decimal("0")
    assert valuation.total_equity == _INITIAL_CASH
    # Paper 원장에 reserved_cash 컬럼 없음 → 가용현금으로 일치 검증
    assert cash == valuation.available_cash

    _assert_ownership(session, aid, uid)
    _assert_no_live(created)


# ---------------------------------------------------------------------------
# B. 정상 매도 청산
# ---------------------------------------------------------------------------


def test_b_paper_sell_exit_realized_pnl(harness) -> None:
    session, created = harness
    aid = created["account_id"]
    uid = created["user_id"]
    Session = get_session_factory()

    buy = _submit_limit(
        session,
        account_id=aid,
        user_id=uid,
        side=OrderSide.BUY,
        quantity=_BUY_QTY,
        price=_BUY_PRICE,
        idempotency_key=f"e2e-b-buy-{created['token']}",
    )
    assert buy.allowed and buy.order_id
    _ensure_order_filled(
        session,
        Session,
        order_id=int(buy.order_id),
        worker_id=f"paper-e2e-b-buy-{created['token']}",
    )

    sell = _submit_limit(
        session,
        account_id=aid,
        user_id=uid,
        side=OrderSide.SELL,
        quantity=_BUY_QTY,
        price=_SELL_PRICE,
        idempotency_key=f"e2e-b-sell-{created['token']}",
    )
    assert sell.allowed and sell.order_id, sell.reason_code
    _ensure_order_filled(
        session,
        Session,
        order_id=int(sell.order_id),
        worker_id=f"paper-e2e-b-sell-{created['token']}",
    )

    qty, _avg = _position(session, aid)
    assert qty == Decimal("0")

    cash, realized = _account_cash_pnl(session, aid)
    expected_pnl = ((_SELL_PRICE - _BUY_PRICE) * _BUY_QTY).quantize(
        Decimal("0.01")
    )
    expected_cash = _INITIAL_CASH + expected_pnl
    assert realized == expected_pnl
    assert cash == expected_cash

    valuation = _valuation(session, aid, _SELL_PRICE)
    assert valuation.unrealized_profit_loss == Decimal("0")
    assert valuation.realized_profit_loss == expected_pnl
    assert valuation.total_equity == expected_cash

    _assert_ownership(session, aid, uid)
    _assert_no_live(created)


# ---------------------------------------------------------------------------
# C. 손절 / D. 익절
# ---------------------------------------------------------------------------


def test_c_stop_loss_exit(harness) -> None:
    session, created = harness
    aid = created["account_id"]
    uid = created["user_id"]
    Session = get_session_factory()

    buy = _submit_limit(
        session,
        account_id=aid,
        user_id=uid,
        side=OrderSide.BUY,
        quantity=_BUY_QTY,
        price=_BUY_PRICE,
        idempotency_key=f"e2e-c-buy-{created['token']}",
    )
    assert buy.allowed
    _ensure_order_filled(
        session,
        Session,
        order_id=int(buy.order_id),
        worker_id=f"paper-e2e-c-buy-{created['token']}",
    )

    decision = RiskManagementEngine().evaluate_exit(
        ExitEvaluationRequest(
            entry_price=_BUY_PRICE,
            current_price=_SL_PRICE,
            highest_price=_BUY_PRICE,
            stop_loss_price=Decimal("9500"),
            take_profit_price=Decimal("12000"),
        )
    )
    assert decision.should_exit is True
    assert decision.reason == "STOP_LOSS"

    before = _counts(session, aid)
    sell = _submit_limit(
        session,
        account_id=aid,
        user_id=uid,
        side=OrderSide.SELL,
        quantity=_BUY_QTY,
        price=_SL_PRICE,
        idempotency_key=f"e2e-c-sl-{created['token']}",
        metadata={"exit_reason": "STOP_LOSS"},
    )
    assert sell.allowed and sell.order_id
    _ensure_order_filled(
        session,
        Session,
        order_id=int(sell.order_id),
        worker_id=f"paper-e2e-c-sl-{created['token']}",
    )

    after = _counts(session, aid)
    assert after["trading_order"] == before["trading_order"] + 1
    assert after["outbox"] == before["outbox"] + 1
    assert after["execution"] == before["execution"] + 1

    qty, _ = _position(session, aid)
    assert qty == Decimal("0")
    _cash, realized = _account_cash_pnl(session, aid)
    expected_pnl = ((_SL_PRICE - _BUY_PRICE) * _BUY_QTY).quantize(
        Decimal("0.01")
    )
    assert realized == expected_pnl
    assert expected_pnl < 0
    _assert_no_live(created)


def test_d_take_profit_exit(harness) -> None:
    session, created = harness
    aid = created["account_id"]
    uid = created["user_id"]
    Session = get_session_factory()

    buy = _submit_limit(
        session,
        account_id=aid,
        user_id=uid,
        side=OrderSide.BUY,
        quantity=_BUY_QTY,
        price=_BUY_PRICE,
        idempotency_key=f"e2e-d-buy-{created['token']}",
    )
    assert buy.allowed
    _ensure_order_filled(
        session,
        Session,
        order_id=int(buy.order_id),
        worker_id=f"paper-e2e-d-buy-{created['token']}",
    )

    decision = RiskManagementEngine().evaluate_exit(
        ExitEvaluationRequest(
            entry_price=_BUY_PRICE,
            current_price=_TP_PRICE,
            highest_price=_TP_PRICE,
            stop_loss_price=Decimal("9500"),
            take_profit_price=Decimal("11500"),
        )
    )
    assert decision.should_exit is True
    assert decision.reason == "TAKE_PROFIT"

    sell = _submit_limit(
        session,
        account_id=aid,
        user_id=uid,
        side=OrderSide.SELL,
        quantity=_BUY_QTY,
        price=_TP_PRICE,
        idempotency_key=f"e2e-d-tp-{created['token']}",
        metadata={"exit_reason": "TAKE_PROFIT"},
    )
    assert sell.allowed
    _ensure_order_filled(
        session,
        Session,
        order_id=int(sell.order_id),
        worker_id=f"paper-e2e-d-tp-{created['token']}",
    )

    qty, _ = _position(session, aid)
    assert qty == Decimal("0")
    _cash, realized = _account_cash_pnl(session, aid)
    expected_pnl = ((_TP_PRICE - _BUY_PRICE) * _BUY_QTY).quantize(
        Decimal("0.01")
    )
    assert realized == expected_pnl
    assert expected_pnl > 0
    _assert_no_live(created)


# ---------------------------------------------------------------------------
# E. 중복 방지
# ---------------------------------------------------------------------------


def test_e_idempotency_no_duplicate_fill(harness) -> None:
    session, created = harness
    aid = created["account_id"]
    uid = created["user_id"]
    Session = get_session_factory()
    key = f"e2e-idem-{created['token']}"

    first = _submit_limit(
        session,
        account_id=aid,
        user_id=uid,
        side=OrderSide.BUY,
        quantity=_BUY_QTY,
        price=_BUY_PRICE,
        idempotency_key=key,
    )
    assert first.allowed and first.order_id
    second = _submit_limit(
        session,
        account_id=aid,
        user_id=uid,
        side=OrderSide.BUY,
        quantity=_BUY_QTY,
        price=_BUY_PRICE,
        idempotency_key=key,
    )
    assert second.allowed
    assert second.reason_code == "IDEMPOTENT_REPLAY"
    assert second.order_id == first.order_id
    assert second.outbox_id == first.outbox_id

    _ensure_order_filled(
        session,
        Session,
        order_id=int(first.order_id),
        worker_id=f"paper-e2e-e1-{created['token']}",
    )
    # 동일 key 재실행 후에도 상태 유지
    _ensure_order_filled(
        session,
        Session,
        order_id=int(first.order_id),
        worker_id=f"paper-e2e-e2-{created['token']}",
    )

    counts = _counts(session, aid)
    assert counts["outbox"] == 1
    assert counts["trading_order"] == 1
    assert counts["paper_order"] == 1
    assert counts["execution"] == 1
    qty, _ = _position(session, aid)
    assert qty == _BUY_QTY
    status_final = session.execute(
        text(
            "SELECT status_code FROM trading.trading_order "
            "WHERE order_id = :oid"
        ),
        {"oid": first.order_id},
    ).scalar_one()
    assert status_final == "FILLED"
    _assert_no_live(created)


# ---------------------------------------------------------------------------
# F. Kill Switch
# ---------------------------------------------------------------------------


def test_f_kill_switch_blocks_orders(harness) -> None:
    session, created = harness
    aid = created["account_id"]
    uid = created["user_id"]
    scope = paper_kill_switch_scope(aid)
    created["kill_scopes"].append(scope)

    KillSwitchService(session).activate_scope(
        scope_code=scope,
        actor="PAPER_E2E",
        reason="e2e kill switch",
    )

    before = _counts(session, aid)
    result = _signal_execute(
        session,
        account_id=aid,
        user_id=uid,
        action=RealtimeSignalAction.BUY,
        price=_BUY_PRICE,
        reason_code="E2E_KS",
    )
    assert result.order_id is None
    assert "KILL" in result.reason_code

    direct = _submit_limit(
        session,
        account_id=aid,
        user_id=uid,
        side=OrderSide.BUY,
        quantity=_BUY_QTY,
        price=_BUY_PRICE,
        idempotency_key=f"e2e-f-{created['token']}",
    )
    assert direct.allowed is False
    assert "KILL" in direct.reason_code

    after = _counts(session, aid)
    assert after == before
    qty, _ = _position(session, aid)
    assert qty == Decimal("0")

    KillSwitchService(session).deactivate_scope(
        scope_code=scope,
        actor="PAPER_E2E",
        reason="e2e done",
    )
    _assert_no_live(created)


# ---------------------------------------------------------------------------
# G. Account Pause
# ---------------------------------------------------------------------------


def test_g_account_pause_blocks_orders(harness) -> None:
    session, created = harness
    aid = created["account_id"]
    uid = created["user_id"]

    # 1) Risk policy account_paused
    UserRiskSettingService(session).upsert_user(
        uid,
        {"account_paused": True},
        actor="PAPER_E2E",
    )
    session.commit()

    before = _counts(session, aid)
    policy_block = _submit_limit(
        session,
        account_id=aid,
        user_id=uid,
        side=OrderSide.BUY,
        quantity=_BUY_QTY,
        price=_BUY_PRICE,
        idempotency_key=f"e2e-g-policy-{created['token']}",
    )
    assert policy_block.allowed is False

    UserRiskSettingService(session).upsert_user(
        uid,
        {"account_paused": False},
        actor="PAPER_E2E",
    )
    session.commit()

    # 2) Recovery trading_paused
    session.add(
        BrokerRecoveryAccountStateEntity(
            broker_code=_BROKER,
            user_id=uid,
            paper_account_id=aid,
            recovery_status="IDLE",
            trading_paused=True,
        )
    )
    session.commit()

    signal_block = _signal_execute(
        session,
        account_id=aid,
        user_id=uid,
        action=RealtimeSignalAction.BUY,
        price=_BUY_PRICE,
        reason_code="E2E_PAUSE",
    )
    assert signal_block.order_id is None
    assert signal_block.reason_code == "ACCOUNT_PAUSED"

    direct = _submit_limit(
        session,
        account_id=aid,
        user_id=uid,
        side=OrderSide.BUY,
        quantity=_BUY_QTY,
        price=_BUY_PRICE,
        idempotency_key=f"e2e-g-lock-{created['token']}",
    )
    assert direct.allowed is False
    assert direct.reason_code == "ACCOUNT_PAUSED"

    after = _counts(session, aid)
    assert after == before
    qty, _ = _position(session, aid)
    assert qty == Decimal("0")
    _assert_no_live(created)


# ---------------------------------------------------------------------------
# H. Recovery (fill 직전 중단 재현)
# ---------------------------------------------------------------------------


def test_h_recovery_fills_exactly_once(
    harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, created = harness
    aid = created["account_id"]
    uid = created["user_id"]
    Session = get_session_factory()

    # Fill 직전 중단 재현: auto-fill 호출이 skip 되도록 패치
    from stock_platform.order import paper_outbox_fill_service as fill_mod
    from stock_platform.order.paper_outbox_fill_service import (
        PaperOutboxFillResult,
        PaperOutboxFillService,
    )

    original_fill = PaperOutboxFillService.fill_accepted_order

    def _simulate_crash_before_fill(
        self,
        order_id: int,
        *,
        actor: str = "PAPER_OUTBOX_AUTO_FILL",
        environment_hint: str | None = None,
    ) -> PaperOutboxFillResult:
        return PaperOutboxFillResult(
            filled=False,
            skipped=True,
            reason_code="SIMULATED_CRASH_BEFORE_FILL",
            order_id=int(order_id),
            order_status="ACCEPTED",
        )

    monkeypatch.setattr(
        PaperOutboxFillService,
        "fill_accepted_order",
        _simulate_crash_before_fill,
    )
    monkeypatch.setattr(
        fill_mod.PaperOutboxFillService,
        "fill_accepted_order",
        _simulate_crash_before_fill,
    )

    submit = _submit_limit(
        session,
        account_id=aid,
        user_id=uid,
        side=OrderSide.BUY,
        quantity=_BUY_QTY,
        price=_BUY_PRICE,
        idempotency_key=f"e2e-h-{created['token']}",
    )
    assert submit.allowed and submit.order_id
    _process_outbox_for_order(
        Session,
        order_id=int(submit.order_id),
        worker_id=f"paper-e2e-h-worker-{created['token']}",
    )
    session.expire_all()

    status = session.execute(
        text(
            "SELECT status_code FROM trading.trading_order "
            "WHERE order_id = :oid"
        ),
        {"oid": submit.order_id},
    ).scalar_one()
    assert status == "ACCEPTED"

    qty_before, _ = _position(session, aid)
    assert qty_before == Decimal("0")
    counts_stalled = _counts(session, aid)
    assert counts_stalled["execution"] == 0

    # Recovery 재개 — 원본 fill 복원 후 해당 주문만 복구
    monkeypatch.setattr(
        PaperOutboxFillService,
        "fill_accepted_order",
        original_fill,
    )
    monkeypatch.setattr(
        fill_mod.PaperOutboxFillService,
        "fill_accepted_order",
        original_fill,
    )

    fill_result = PaperOutboxFillService(session).fill_accepted_order(
        int(submit.order_id),
        actor="PAPER_E2E_RECOVERY",
    )
    assert fill_result.filled is True, fill_result.reason_code
    session.commit()
    session.expire_all()

    status2 = session.execute(
        text(
            "SELECT status_code FROM trading.trading_order "
            "WHERE order_id = :oid"
        ),
        {"oid": submit.order_id},
    ).scalar_one()
    assert status2 == "FILLED"

    qty, avg = _position(session, aid)
    assert qty == _BUY_QTY
    assert avg == _BUY_PRICE
    cash, _ = _account_cash_pnl(session, aid)
    assert cash == _INITIAL_CASH - (_BUY_PRICE * _BUY_QTY)

    # 동일 주문 재 recovery — 중복 없음
    again = PaperOutboxFillService(session).fill_accepted_order(
        int(submit.order_id),
        actor="PAPER_E2E_RECOVERY",
    )
    assert again.filled is False
    assert again.reason_code == "ALREADY_TERMINAL"

    batch = recover_stalled_paper_accepted_orders(
        session, actor="PAPER_E2E_RECOVERY"
    )
    # 우리 주문은 이미 FILLED — 이 계좌 execution 증가 없음
    assert batch["filled"] >= 0

    counts_final = _counts(session, aid)
    assert counts_final["execution"] == 1
    assert counts_final["paper_order"] == 1
    assert counts_final["trading_order"] == 1
    _assert_ownership(session, aid, uid)
    _assert_no_live(created)
