"""Kiwoom MOCK PostgreSQL E2E — LIVE HTTP/실계좌 0.

결정적 Mock 이벤트로:
접수 → 부분/완전 체결 → Ledger → 매도 청산 → 거부/취소/정정
→ Recovery/Reconciliation → Kill/Pause → Scope 격리
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from stock_platform.auth.models import AuthUser
from stock_platform.broker.account_models import (
    BrokerAccountSnapshotEntity,
    BrokerPositionSnapshotEntity,
)
from stock_platform.broker.kiwoom.mock_adapter import KiwoomMockBrokerAdapter
from stock_platform.broker.kiwoom.mock_gateway import KiwoomMockOrderGateway
from stock_platform.broker.kiwoom.ws_models import KiwoomOrderEventType
from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.broker.recovery_entities import (  # noqa: F401
    BrokerRecoveryRunEntity,
)
from stock_platform.common.settings import clear_settings_cache, get_settings
from stock_platform.database.session import get_engine, get_session_factory
from stock_platform.order.cancel_replace_service import (
    OrderCancelReplaceService,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.models import OrderStatus
from stock_platform.risk_engine.kill_switch_guard import (
    PersistentKillSwitchGuard,
)
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.risk.persistence_models import PositionPlanEntity  # noqa: F401
from stock_platform.strategy_deployment.entities import (  # noqa: F401
    StrategyDeploymentEntity,
)
from stock_platform.trading.account_identity import uba_kill_switch_scope
from stock_platform.trading.account_models import (
    UserBrokerAccount,
)
from stock_platform.trading.account_repository import PaperAccountRepository
from stock_platform.trading.account_service import PaperAccountService

pytestmark = pytest.mark.integration

_PREFIX = "KMOCK_E2E_"
_SYMBOL = "005930"
_INITIAL = Decimal("10000000.00")


@pytest.fixture(autouse=True)
def _safe_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("UPBIT_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
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
def harness():
    Session = get_session_factory()
    session = Session()
    token = uuid.uuid4().hex[:8]
    created: dict = {
        "token": token,
        "user_id": None,
        "paper_id": None,
        "uba_id": None,
        "uba2_id": None,
        "kill_scopes": [],
        "order_ids": [],
    }
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

        paper = PaperAccountService(PaperAccountRepository(session)).create_account(
            account_name=f"{_PREFIX}{token}",
            initial_cash=_INITIAL,
            user_id=created["user_id"],
        )
        session.commit()
        created["paper_id"] = int(paper.account_id)

        uba = UserBrokerAccount(
            user_id=created["user_id"],
            broker_code="KIWOOM",
            account_alias=f"{_PREFIX}{token}",
            account_ref_hash=uuid.uuid4().hex,
            is_active=True,
            live_order_enabled=False,
        )
        session.add(uba)
        session.flush()
        created["uba_id"] = int(uba.user_broker_account_id)

        uba2 = UserBrokerAccount(
            user_id=created["user_id"],
            broker_code="KIWOOM",
            account_alias=f"{_PREFIX}{token}_b",
            account_ref_hash=uuid.uuid4().hex,
            is_active=True,
            live_order_enabled=False,
        )
        session.add(uba2)
        session.flush()
        created["uba2_id"] = int(uba2.user_broker_account_id)
        session.commit()

        yield session, created
    finally:
        session.rollback()
        _cleanup(session, created)
        session.close()


def _cleanup(session, created: dict) -> None:
    try:
        for scope in created.get("kill_scopes") or []:
            try:
                KillSwitchService(session).deactivate_scope(
                    scope_code=scope, actor="KMOCK", reason="cleanup"
                )
            except Exception:  # noqa: BLE001
                pass
        uba_ids = [
            i
            for i in (created.get("uba_id"), created.get("uba2_id"))
            if i is not None
        ]
        paper_id = created.get("paper_id")
        uid = created.get("user_id")
        if uba_ids:
            session.execute(
                text(
                    """
                    DELETE FROM trading.execution
                    WHERE order_id IN (
                      SELECT order_id FROM trading.trading_order
                      WHERE user_broker_account_id = ANY(:u)
                    )
                    """
                ),
                {"u": uba_ids},
            )
            session.execute(
                text(
                    """
                    DELETE FROM trading.trading_order_status_history
                    WHERE order_id IN (
                      SELECT order_id FROM trading.trading_order
                      WHERE user_broker_account_id = ANY(:u)
                    )
                    """
                ),
                {"u": uba_ids},
            )
            session.execute(
                text(
                    "DELETE FROM trading.trading_order "
                    "WHERE user_broker_account_id = ANY(:u)"
                ),
                {"u": uba_ids},
            )
            session.execute(
                text(
                    "DELETE FROM trading.broker_position_snapshot "
                    "WHERE user_broker_account_id = ANY(:u)"
                ),
                {"u": uba_ids},
            )
            session.execute(
                text(
                    "DELETE FROM trading.broker_account_snapshot "
                    "WHERE user_broker_account_id = ANY(:u)"
                ),
                {"u": uba_ids},
            )
            session.execute(
                text(
                    "DELETE FROM operation.broker_recovery_account_state "
                    "WHERE user_broker_account_id = ANY(:u)"
                ),
                {"u": uba_ids},
            )
            session.execute(
                text(
                    "DELETE FROM trading.user_broker_account "
                    "WHERE user_broker_account_id = ANY(:u)"
                ),
                {"u": uba_ids},
            )
        if paper_id is not None:
            session.execute(
                text("DELETE FROM trading.paper_account WHERE account_id=:a"),
                {"a": paper_id},
            )
        if uid is not None:
            session.execute(
                text("DELETE FROM auth.user WHERE user_id=:u"),
                {"u": uid},
            )
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()


def _exec_count(session, order_id: int) -> int:
    return int(
        session.execute(
            text(
                "SELECT COUNT(*) FROM trading.execution "
                "WHERE order_id=:o"
            ),
            {"o": order_id},
        ).scalar_one()
    )


def _pos_qty(session, uba_id: int, symbol: str = _SYMBOL) -> Decimal:
    val = session.execute(
        text(
            """
            SELECT quantity FROM trading.broker_position_snapshot
            WHERE user_broker_account_id=:u AND symbol=:s
            """
        ),
        {"u": uba_id, "s": symbol},
    ).scalar()
    return Decimal(str(val or 0))


def _cash(session, uba_id: int) -> tuple[Decimal, Decimal]:
    row = session.execute(
        text(
            """
            SELECT available_order_amount, raw_data
            FROM trading.broker_account_snapshot
            WHERE user_broker_account_id=:u
            """
        ),
        {"u": uba_id},
    ).mappings().first()
    if row is None:
        return Decimal("0"), Decimal("0")
    raw = row["raw_data"] or {}
    return (
        Decimal(str(row["available_order_amount"] or 0)),
        Decimal(str(raw.get("realized_profit_loss") or 0)),
    )


def test_kiwoom_mock_autotrading_e2e_full(harness) -> None:
    session, created = harness
    settings = get_settings()
    assert settings.kiwoom_live_order_enabled is False
    assert settings.upbit_live_order_enabled is False
    assert settings.global_live_order_enabled is False

    paper_id = created["paper_id"]
    uba_id = created["uba_id"]
    uba2_id = created["uba2_id"]
    gw = KiwoomMockOrderGateway(session)
    assert gw.live_api_calls == 0
    assert gw.adapter.live_http_calls == 0

    # --- 1. 정상 매수 접수 ---
    buy = gw.accept_order(
        paper_account_id=paper_id,
        user_broker_account_id=uba_id,
        symbol=_SYMBOL,
        side="BUY",
        quantity=Decimal("10"),
        price=Decimal("70000"),
    )
    assert buy.status_code == OrderStatus.ACCEPTED.value
    assert buy.broker_order_id and buy.broker_order_id.startswith("KMOCK-")
    created["order_ids"].append(int(buy.order_id))

    # --- 2. 부분 체결 → 완전 체결 ---
    r1 = gw.apply_fill_event(
        broker_order_id=buy.broker_order_id,
        filled_quantity=Decimal("4"),
        remaining_quantity=Decimal("6"),
        fill_price=Decimal("70000"),
        event_type=KiwoomOrderEventType.PARTIALLY_FILLED,
        symbol=_SYMBOL,
        side="BUY",
        broker_execution_id="E-BUY-1",
    )
    assert r1.duplicate is False and r1.order_found is True
    session.expire_all()
    buy = session.get(TradingOrderEntity, buy.order_id)
    assert buy.status_code == OrderStatus.PARTIALLY_FILLED.value
    assert buy.filled_quantity == Decimal("4")
    assert _exec_count(session, buy.order_id) == 1

    r2 = gw.apply_fill_event(
        broker_order_id=buy.broker_order_id,
        filled_quantity=Decimal("10"),
        remaining_quantity=Decimal("0"),
        fill_price=Decimal("70000"),
        event_type=KiwoomOrderEventType.FILLED,
        symbol=_SYMBOL,
        side="BUY",
        broker_execution_id="E-BUY-2",
    )
    assert r2.duplicate is False
    session.expire_all()
    buy = session.get(TradingOrderEntity, buy.order_id)
    assert buy.status_code == OrderStatus.FILLED.value
    assert buy.filled_quantity == Decimal("10")
    assert _exec_count(session, buy.order_id) == 2
    assert _pos_qty(session, uba_id) == Decimal("10")

    # --- 3. 중복 체결 이벤트 방지 ---
    from datetime import datetime, timezone

    from stock_platform.broker.kiwoom.execution_models import (
        KiwoomExecutionEvent,
    )

    dup = gw.apply_direct_execution(
        KiwoomExecutionEvent(
            broker_order_id=buy.broker_order_id,
            broker_execution_id="E-BUY-2",
            symbol=_SYMBOL,
            side_code="BUY",
            execution_price=Decimal("70000"),
            execution_quantity=Decimal("6"),
            remaining_quantity=Decimal("0"),
            executed_at=datetime.now(timezone.utc),
            raw_payload={},
        )
    )
    assert dup.duplicate is True
    assert _exec_count(session, buy.order_id) == 2
    assert _pos_qty(session, uba_id) == Decimal("10")

    cash_after_buy, _ = _cash(session, uba_id)
    assert cash_after_buy == _INITIAL - Decimal("700000")

    # --- 4–5. 매도 청산 + Position/Cash/PnL ---
    sell = gw.accept_order(
        paper_account_id=paper_id,
        user_broker_account_id=uba_id,
        symbol=_SYMBOL,
        side="SELL",
        quantity=Decimal("10"),
        price=Decimal("71000"),
    )
    assert sell.status_code == OrderStatus.ACCEPTED.value
    created["order_ids"].append(int(sell.order_id))
    rs = gw.apply_fill_event(
        broker_order_id=sell.broker_order_id,
        filled_quantity=Decimal("10"),
        remaining_quantity=Decimal("0"),
        fill_price=Decimal("71000"),
        event_type=KiwoomOrderEventType.FILLED,
        symbol=_SYMBOL,
        side="SELL",
        broker_execution_id="E-SELL-1",
    )
    assert rs.duplicate is False
    session.expire_all()
    assert _pos_qty(session, uba_id) == Decimal("0")
    cash_final, realized = _cash(session, uba_id)
    assert cash_final == _INITIAL + Decimal("10000")  # 10*(71000-70000)
    assert realized == Decimal("10000.00")

    # --- 6. 주문 거부 ---
    reject_adapter = KiwoomMockBrokerAdapter(reject_symbols={_SYMBOL})
    reject_gw = KiwoomMockOrderGateway(session, adapter=reject_adapter)
    rejected = reject_gw.accept_order(
        paper_account_id=paper_id,
        user_broker_account_id=uba_id,
        symbol=_SYMBOL,
        side="BUY",
        quantity=Decimal("1"),
        price=Decimal("70000"),
    )
    assert rejected.status_code == OrderStatus.REJECTED.value
    assert rejected.broker_order_id is None
    created["order_ids"].append(int(rejected.order_id))

    # --- 7. 미체결 취소 ---
    open_buy = gw.accept_order(
        paper_account_id=paper_id,
        user_broker_account_id=uba_id,
        symbol=_SYMBOL,
        side="BUY",
        quantity=Decimal("3"),
        price=Decimal("69000"),
    )
    created["order_ids"].append(int(open_buy.order_id))
    cancelled = OrderCancelReplaceService(
        session=session, adapter=gw.adapter
    ).cancel(order_id=int(open_buy.order_id), actor="KMOCK")
    assert cancelled.status_code == OrderStatus.CANCELLED.value

    # --- 8. 주문 정정 ---
    to_replace = gw.accept_order(
        paper_account_id=paper_id,
        user_broker_account_id=uba_id,
        symbol=_SYMBOL,
        side="BUY",
        quantity=Decimal("2"),
        price=Decimal("68000"),
    )
    created["order_ids"].append(int(to_replace.order_id))
    replaced = OrderCancelReplaceService(
        session=session, adapter=gw.adapter
    ).replace(
        order_id=int(to_replace.order_id),
        quantity=Decimal("2"),
        price=Decimal("68500"),
        actor="KMOCK",
    )
    assert replaced.status_code == OrderStatus.REPLACED.value
    assert Decimal(str(replaced.order_price)) == Decimal("68500")
    assert gw.adapter.replace_count >= 1

    # --- 9–10. Recovery + Reconciliation ---
    mid = gw.accept_order(
        paper_account_id=paper_id,
        user_broker_account_id=uba_id,
        symbol=_SYMBOL,
        side="BUY",
        quantity=Decimal("5"),
        price=Decimal("70000"),
    )
    created["order_ids"].append(int(mid.order_id))
    gw.apply_fill_event(
        broker_order_id=mid.broker_order_id,
        filled_quantity=Decimal("2"),
        remaining_quantity=Decimal("3"),
        fill_price=Decimal("70000"),
        event_type=KiwoomOrderEventType.PARTIALLY_FILLED,
        symbol=_SYMBOL,
        side="BUY",
        broker_execution_id="E-REC-1",
    )
    # 프로세스 중단 시뮬레이션: gateway last_filled 초기화 후 원격 누적 재동기화
    crashed = KiwoomMockOrderGateway(session, adapter=gw.adapter)
    recon = crashed.reconcile_remote_filled(
        broker_order_id=mid.broker_order_id,
        remote_filled_quantity=Decimal("5"),
        fill_price=Decimal("70000"),
        symbol=_SYMBOL,
        side="BUY",
        broker_execution_id="E-REC-2",
    )
    assert recon.order_found is True
    assert recon.duplicate is False
    session.expire_all()
    mid = session.get(TradingOrderEntity, mid.order_id)
    assert mid.status_code == OrderStatus.FILLED.value
    assert mid.filled_quantity == Decimal("5")
    assert _exec_count(session, mid.order_id) == 2
    # 이미 원격=로컬이면 duplicate
    again = crashed.reconcile_remote_filled(
        broker_order_id=mid.broker_order_id,
        remote_filled_quantity=Decimal("5"),
        fill_price=Decimal("70000"),
        symbol=_SYMBOL,
        side="BUY",
    )
    assert again.duplicate is True

    # 포지션 정리 (5주 보유 → 매도)
    flat = gw.accept_order(
        paper_account_id=paper_id,
        user_broker_account_id=uba_id,
        symbol=_SYMBOL,
        side="SELL",
        quantity=Decimal("5"),
        price=Decimal("70000"),
    )
    created["order_ids"].append(int(flat.order_id))
    gw.apply_fill_event(
        broker_order_id=flat.broker_order_id,
        filled_quantity=Decimal("5"),
        remaining_quantity=Decimal("0"),
        fill_price=Decimal("70000"),
        event_type=KiwoomOrderEventType.FILLED,
        symbol=_SYMBOL,
        side="SELL",
        broker_execution_id="E-FLAT-1",
    )
    assert _pos_qty(session, uba_id) == Decimal("0")

    # --- 11. Kill Switch 차단 (BUY) ---
    scope = uba_kill_switch_scope(uba_id)
    created["kill_scopes"].append(scope)
    KillSwitchService(session).activate_scope(
        scope_code=scope, actor="KMOCK", reason="e2e"
    )
    session.commit()
    with pytest.raises(PermissionError):
        PersistentKillSwitchGuard(session).require_order_allowed(
            side="BUY",
            user_broker_account_id=uba_id,
            allow_sell=True,
        )
    # SELL은 allow_sell=True면 통과
    PersistentKillSwitchGuard(session).require_order_allowed(
        side="SELL",
        user_broker_account_id=uba_id,
        allow_sell=True,
    )
    KillSwitchService(session).deactivate_scope(
        scope_code=scope, actor="KMOCK", reason="done"
    )
    session.commit()

    # --- 12. Account Pause 차단 ---
    from stock_platform.broker.recovery_lock import (
        RecoveryAccountLockService,
    )

    session.add(
        BrokerRecoveryAccountStateEntity(
            broker_code="KIWOOM",
            user_id=created["user_id"],
            user_broker_account_id=uba_id,
            recovery_status="IDLE",
            trading_paused=True,
        )
    )
    session.commit()
    assert (
        RecoveryAccountLockService(session).is_trading_paused(
            user_broker_account_id=uba_id,
            broker_code="KIWOOM",
        )
        is True
    )
    session.execute(
        text(
            "UPDATE operation.broker_recovery_account_state "
            "SET trading_paused=false WHERE user_broker_account_id=:u"
        ),
        {"u": uba_id},
    )
    session.commit()

    # --- 13. Scope 격리 ---
    o1 = gw.accept_order(
        paper_account_id=paper_id,
        user_broker_account_id=uba_id,
        symbol=_SYMBOL,
        side="BUY",
        quantity=Decimal("1"),
        price=Decimal("70000"),
        client_order_id=f"ISO-A-{uuid.uuid4().hex[:12]}",
    )
    o2 = gw.accept_order(
        paper_account_id=paper_id,
        user_broker_account_id=uba2_id,
        symbol=_SYMBOL,
        side="BUY",
        quantity=Decimal("1"),
        price=Decimal("70000"),
        client_order_id=f"ISO-B-{uuid.uuid4().hex[:12]}",
    )
    created["order_ids"].extend([int(o1.order_id), int(o2.order_id)])
    gw.apply_fill_event(
        broker_order_id=o1.broker_order_id,
        filled_quantity=Decimal("1"),
        remaining_quantity=Decimal("0"),
        fill_price=Decimal("70000"),
        event_type=KiwoomOrderEventType.FILLED,
        symbol=_SYMBOL,
        side="BUY",
        broker_execution_id="E-ISO-1",
    )
    assert _pos_qty(session, uba_id) == Decimal("1")
    assert _pos_qty(session, uba2_id) == Decimal("0")
    gw.apply_fill_event(
        broker_order_id=o2.broker_order_id,
        filled_quantity=Decimal("1"),
        remaining_quantity=Decimal("0"),
        fill_price=Decimal("70000"),
        event_type=KiwoomOrderEventType.FILLED,
        symbol=_SYMBOL,
        side="BUY",
        broker_execution_id="E-ISO-2",
    )
    assert _pos_qty(session, uba2_id) == Decimal("1")
    # cross-account 혼입 없음
    assert o1.user_broker_account_id != o2.user_broker_account_id

    # LIVE 호출 0
    assert gw.live_api_calls == 0
    assert gw.adapter.live_http_calls == 0
    assert reject_adapter.live_http_calls == 0
