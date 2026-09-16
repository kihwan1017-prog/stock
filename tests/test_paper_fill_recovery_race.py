"""Paper ACCEPTED Fill Recovery 경합·재처리 회귀."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import text

from stock_platform.auth.models import AuthUser
from stock_platform.common.settings import clear_settings_cache
from stock_platform.database.session import get_engine, get_session_factory
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.execution_service import (
    OrderExecutionCommand,
    OrderExecutionService,
)
from stock_platform.order.models import OrderSide, OrderStatus, OrderType
from stock_platform.order.paper_fill_recovery import (
    recover_stalled_paper_accepted_orders,
)
from stock_platform.order.paper_outbox_fill_service import (
    PaperOutboxFillResult,
    PaperOutboxFillService,
)
from stock_platform.risk.persistence_models import PositionPlanEntity  # noqa: F401
from stock_platform.strategy_deployment.entities import (  # noqa: F401
    StrategyDeploymentEntity,
)
from stock_platform.trading.account_repository import PaperAccountRepository
from stock_platform.trading.account_service import PaperAccountService

pytestmark = pytest.mark.integration

_PREFIX = "PAPER_REC_"
_SYMBOL = "RECSYM"
_INITIAL = Decimal("5000000.00")


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PAPER_OUTBOX_AUTO_FILL", "true")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("UPBIT_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "false")
    clear_settings_cache()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    yield
    clear_settings_cache()
    try:
        get_engine().dispose()
    except Exception:  # noqa: BLE001
        pass
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@pytest.fixture()
def rec_harness():
    Session = get_session_factory()
    session = Session()
    token = uuid.uuid4().hex[:8]
    created = {"user_id": None, "account_id": None, "token": token}
    try:
        user = AuthUser(
            username=f"{_PREFIX}{token}",
            password_hash="x",
            display_name=token,
            is_active=True,
        )
        session.add(user)
        session.flush()
        created["user_id"] = int(user.user_id)
        acct = PaperAccountService(PaperAccountRepository(session)).create_account(
            account_name=f"{_PREFIX}{token}",
            initial_cash=_INITIAL,
            user_id=created["user_id"],
        )
        session.commit()
        created["account_id"] = int(acct.account_id)
        yield session, created
    finally:
        session.rollback()
        aid = created.get("account_id")
        uid = created.get("user_id")
        try:
            if aid is not None:
                session.execute(
                    text("DELETE FROM trading.paper_trade WHERE account_id=:a"),
                    {"a": aid},
                )
                session.execute(
                    text("DELETE FROM trading.paper_order WHERE account_id=:a"),
                    {"a": aid},
                )
                session.execute(
                    text(
                        """
                        DELETE FROM trading.trading_order_status_history
                        WHERE order_id IN (
                          SELECT order_id FROM trading.trading_order
                          WHERE account_id=:a
                        )
                        """
                    ),
                    {"a": aid},
                )
                session.execute(
                    text(
                        """
                        DELETE FROM trading.order_outbox
                        WHERE order_id IN (
                          SELECT order_id FROM trading.trading_order
                          WHERE account_id=:a
                        )
                        """
                    ),
                    {"a": aid},
                )
                session.execute(
                    text("DELETE FROM trading.trading_order WHERE account_id=:a"),
                    {"a": aid},
                )
                session.execute(
                    text("DELETE FROM trading.paper_position WHERE account_id=:a"),
                    {"a": aid},
                )
                session.execute(
                    text("DELETE FROM trading.paper_account WHERE account_id=:a"),
                    {"a": aid},
                )
            if uid is not None:
                session.execute(
                    text("DELETE FROM auth.user WHERE user_id=:u"),
                    {"u": uid},
                )
            session.commit()
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            raise RuntimeError(
                f"PAPER_REC harness cleanup failed (account_id={aid}): {exc}"
            ) from exc
        session.close()


def _submit_accepted(
    session,
    account_id: int,
    user_id: int,
    *,
    side: OrderSide = OrderSide.BUY,
) -> int:
    """Outbox Worker 없이 ACCEPTED TradingOrder 생성 (Fill은 별도)."""

    result = OrderExecutionService(session).submit(
        OrderExecutionCommand(
            account_id=account_id,
            broker_code="PAPER",
            exchange_code="PAPER",
            symbol=_SYMBOL,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=Decimal("2"),
            order_amount=None,
            price=Decimal("10000"),
            strategy_code="REC_TEST",
            account_number=f"PAPER-{account_id}",
            skip_risk_checks=True,
            metadata_payload={
                "environment": "PAPER",
                "source": "REC_TEST",
            },
            actor="REC_TEST",
            order_source="AUTO",
            environment="PAPER",
            user_id=user_id,
            idempotency_key=f"REC:{account_id}:{uuid.uuid4().hex}",
        )
    )
    assert result.allowed, result.reason_code
    order_id = int(result.order_id)
    # Outbox dispatch 없이 ACCEPTED로 강제 (Worker Fill 실패 시나리오 재현)
    order = session.get(TradingOrderEntity, order_id)
    assert order is not None
    if order.status_code != OrderStatus.ACCEPTED.value:
        order.status_code = OrderStatus.ACCEPTED.value
    session.commit()
    return order_id


def test_a_worker_fill_fail_then_recovery(rec_harness, monkeypatch):
    session, created = rec_harness
    aid = created["account_id"]
    oid = _submit_accepted(session, aid, created["user_id"])

    original = PaperOutboxFillService.fill_accepted_order
    calls = {"n": 0}

    def _fail_once(self, order_id, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return PaperOutboxFillResult(
                filled=False,
                skipped=True,
                reason_code="SIMULATED_WORKER_FAIL",
                order_id=int(order_id),
                order_status="ACCEPTED",
            )
        return original(self, order_id, **kwargs)

    monkeypatch.setattr(PaperOutboxFillService, "fill_accepted_order", _fail_once)
    # Worker 경로 시뮬레이션: 첫 Fill 실패
    r1 = PaperOutboxFillService(session).fill_accepted_order(oid, actor="WORKER")
    assert r1.filled is False
    session.commit()

    monkeypatch.setattr(PaperOutboxFillService, "fill_accepted_order", original)
    Session = get_session_factory()
    with Session() as s2:
        out = recover_stalled_paper_accepted_orders(s2, limit=20, actor="RECOVERY")
    assert out["filled"] >= 1

    session.expire_all()
    order = session.get(TradingOrderEntity, oid)
    assert order is not None
    assert order.status_code == OrderStatus.FILLED.value
    fills = session.execute(
        text("SELECT COUNT(*) FROM trading.paper_trade WHERE account_id=:a"),
        {"a": aid},
    ).scalar_one()
    assert int(fills) >= 1


def test_b_worker_recovery_race_single_fill(rec_harness):
    session, created = rec_harness
    aid = created["account_id"]
    oid = _submit_accepted(session, aid, created["user_id"])
    session.commit()

    barrier = threading.Barrier(2)
    results: list[PaperOutboxFillResult] = []

    def _run(label: str):
        Session = get_session_factory()
        with Session() as s:
            barrier.wait(timeout=10)
            if label == "recovery":
                out = recover_stalled_paper_accepted_orders(
                    s, limit=20, actor="RECOVERY_RACE"
                )
                results.append(
                    PaperOutboxFillResult(
                        filled=out["filled"] >= 1,
                        skipped=out["filled"] < 1,
                        reason_code=(
                            "FILLED" if out["filled"] >= 1 else "SKIPPED"
                        ),
                        order_id=oid,
                    )
                )
            else:
                r = PaperOutboxFillService(s).fill_accepted_order(
                    oid, actor="WORKER_RACE"
                )
                s.commit()
                results.append(r)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_run, "worker")
        f2 = pool.submit(_run, "recovery")
        f1.result(timeout=30)
        f2.result(timeout=30)

    filled_n = sum(1 for r in results if r.filled)
    assert filled_n == 1, results

    session.expire_all()
    order = session.get(TradingOrderEntity, oid)
    assert order.status_code == OrderStatus.FILLED.value
    fills = int(
        session.execute(
            text("SELECT COUNT(*) FROM trading.paper_trade WHERE account_id=:a"),
            {"a": aid},
        ).scalar_one()
    )
    assert fills == 1


def test_c_fill_txn_failure_retryable(rec_harness, monkeypatch):
    session, created = rec_harness
    aid = created["account_id"]
    oid = _submit_accepted(session, aid, created["user_id"])

    from stock_platform.trading.execution_service import PaperExecutionService

    original_apply = PaperExecutionService.apply_fill

    def _boom(self, **kwargs):
        raise RuntimeError("SIMULATED_FLUSH_FAIL")

    monkeypatch.setattr(PaperExecutionService, "apply_fill", _boom)
    r = PaperOutboxFillService(session).fill_accepted_order(oid, actor="TXN_FAIL")
    assert r.filled is False
    session.rollback()

    session.expire_all()
    order = session.get(TradingOrderEntity, oid)
    assert order.status_code == OrderStatus.ACCEPTED.value
    fills = int(
        session.execute(
            text("SELECT COUNT(*) FROM trading.paper_trade WHERE account_id=:a"),
            {"a": aid},
        ).scalar_one()
    )
    assert fills == 0

    monkeypatch.setattr(PaperExecutionService, "apply_fill", original_apply)
    Session = get_session_factory()
    with Session() as s2:
        out = recover_stalled_paper_accepted_orders(s2, limit=20)
    assert out["filled"] >= 1
    session.expire_all()
    assert session.get(TradingOrderEntity, oid).status_code == OrderStatus.FILLED.value


def test_d_stale_then_recovery(rec_harness, monkeypatch):
    session, created = rec_harness
    aid = created["account_id"]
    oid = _submit_accepted(session, aid, created["user_id"])

    # claim 후 중단 시뮬레이션: Fill 미완료 ACCEPTED 유지
    original = PaperOutboxFillService.fill_accepted_order

    def _abort(self, order_id, **kwargs):
        return PaperOutboxFillResult(
            filled=False,
            skipped=True,
            reason_code="STALE_ABORT",
            order_id=int(order_id),
            order_status="ACCEPTED",
        )

    monkeypatch.setattr(PaperOutboxFillService, "fill_accepted_order", _abort)
    PaperOutboxFillService(session).fill_accepted_order(oid, actor="STALE")
    session.commit()
    monkeypatch.setattr(PaperOutboxFillService, "fill_accepted_order", original)

    with get_session_factory()() as s2:
        out = recover_stalled_paper_accepted_orders(s2, limit=20)
    assert out["filled"] >= 1
    session.expire_all()
    assert session.get(TradingOrderEntity, oid).status_code == OrderStatus.FILLED.value


def test_e_no_starvation_among_accepted(rec_harness):
    session, created = rec_harness
    aid = created["account_id"]
    # 오래된 고착 주문(타 계좌) + 현재 주문
    Session = get_session_factory()
    other_ids = []
    with Session() as s:
        user = AuthUser(
            username=f"{_PREFIX}old_{uuid.uuid4().hex[:6]}",
            password_hash="x",
            display_name="old",
            is_active=True,
        )
        s.add(user)
        s.flush()
        other = PaperAccountService(PaperAccountRepository(s)).create_account(
            account_name=f"{_PREFIX}old_{uuid.uuid4().hex[:6]}",
            initial_cash=_INITIAL,
            user_id=int(user.user_id),
        )
        s.commit()
        other_aid = int(other.account_id)
        for _ in range(3):
            other_ids.append(_submit_accepted(s, other_aid, int(user.user_id)))

    target = _submit_accepted(session, aid, created["user_id"])
    session.commit()

    # 최신 우선 + limit 으로 target이 처리되어야 함
    with Session() as s2:
        out = recover_stalled_paper_accepted_orders(s2, limit=5, actor="NO_STARVE")
    assert out["filled"] >= 1
    session.expire_all()
    assert (
        session.get(TradingOrderEntity, target).status_code
        == OrderStatus.FILLED.value
    )


def test_f_sell_no_position_cancelled_by_recovery(rec_harness):
    """포지션 없는 SELL ACCEPTED는 CANCELLED로 고착 해소."""

    session, created = rec_harness
    aid = created["account_id"]
    oid = _submit_accepted(
        session, aid, created["user_id"], side=OrderSide.SELL
    )

    with get_session_factory()() as s2:
        out = recover_stalled_paper_accepted_orders(s2, limit=20)
    assert out["filled"] == 0
    session.expire_all()
    order = session.get(TradingOrderEntity, oid)
    assert order is not None
    assert order.status_code == OrderStatus.CANCELLED.value
    meta = dict(order.metadata_payload or {})
    assert meta.get("paper_auto_fill_last_error") == "NO_POSITION_CANCELLED"
    fills = int(
        session.execute(
            text("SELECT COUNT(*) FROM trading.paper_trade WHERE account_id=:a"),
            {"a": aid},
        ).scalar_one()
    )
    assert fills == 0
