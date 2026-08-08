"""공식 Service 경로로 UPBIT MA Strategy 구축 (실주문 0).

DB INSERT 금지 — StrategyDefinitionService / Backtest / link_to_account 만 사용.
Runtime RUN / LIVE ON / ARM / Worker ENABLE 금지.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.backtest.persistence_service import (
    BacktestPersistenceService,
)
from stock_platform.backtest.engine import BacktestValidationError
from stock_platform.database.session import get_session_factory
# FK 메타 로딩 — strategy_definition flush 전 ORM 테이블 등록
import stock_platform.ai.candidate_lifecycle.entities  # noqa: F401
import stock_platform.ai.strategy_draft.entities  # noqa: F401
import stock_platform.ai.strategy_draft_approval.entities  # noqa: F401
import stock_platform.ai.strategy_request.entities  # noqa: F401
import stock_platform.auth.models  # noqa: F401
from stock_platform.performance.backtest_analytics import (
    analyze_backtest_run,
)
from stock_platform.realtime.ma_evaluator import MovingAverageStrategyEvaluator
from stock_platform.realtime.market_event import RealtimeMarketEvent
from stock_platform.realtime.strategy_models import (
    RealtimePositionState,
    RealtimeStrategyConfig,
)
from stock_platform.strategy_deployment.ownership import (
    StrategyDefinitionService,
    market_compatible,
)
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    StrategyRuntimeScope,
)
from stock_platform.trading.autotrading_master_gate import (
    evaluate_uba_autotrading_ready,
)


UBA_ID = 1380
OWNER_USER_ID = 61
ACTOR_ADMIN = "admin:strategy-build"
ACTOR_USER = "user:61:strategy-build"

PARAMS = {
    "strategy_type": "MOVING_AVERAGE_CROSS",
    "evaluator": "MovingAverageStrategyEvaluator",
    "symbols": ["KRW-XRP"],
    "symbol": "KRW-XRP",
    "exchange_code": "UPBIT",
    "short_window": 5,
    "long_window": 20,
    "stop_loss_ratio": "0.03",
    "take_profit_ratio": "0.06",
    "position_ratio": "0.20",
    "cooldown_seconds": 30,
    "purpose": "first_upbit_autotrading_validation",
}


def _user(*, user_id: int, is_admin: bool) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id,
        username=f"user{user_id}" if not is_admin else "admin_ops",
        roles=["admin"] if is_admin else ["user"],
        permissions=["trading:read", "trading:write"],
    )


def _ser(v):
    if isinstance(v, (datetime, date, Decimal)):
        return str(v)
    if isinstance(v, SimpleNamespace):
        return {k: _ser(getattr(v, k)) for k in vars(v)}
    return v


def _paper_shadow_ma_cycle(*, strategy_id: int) -> dict:
    """Paper/Shadow: tick → MA BUY/SELL (실 adapter 없음)."""

    from datetime import timezone

    from stock_platform.realtime.hub_constants import SignalType

    scope = StrategyRuntimeScope(
        user_id=OWNER_USER_ID,
        account_kind=AccountKind.USER_BROKER,
        account_id=UBA_ID,
        strategy_id=max(1, int(strategy_id)),
        strategy_version="1",
        broker_code="UPBIT",
        market_type="CRYPTO",
    )
    cfg = RealtimeStrategyConfig(
        short_window=3,
        long_window=5,
        stop_loss_ratio=Decimal("0.03"),
        take_profit_ratio=Decimal("0.06"),
        cooldown_seconds=0,
        minimum_change_rate=Decimal("0"),
    )
    ev = MovingAverageStrategyEvaluator(scope, cfg)
    prices = [
        "100",
        "100",
        "100",
        "100",
        "100",
        "101",
        "103",
        "108",
        "115",
        "120",
        "118",
        "110",
        "100",
        "90",
    ]
    signals = []
    position = RealtimePositionState(
        quantity=Decimal("0"), average_entry_price=None
    )
    now = datetime.now(timezone.utc)
    for i, p in enumerate(prices):
        event = RealtimeMarketEvent(
            broker_code="UPBIT",
            market_type="CRYPTO",
            symbol="KRW-XRP",
            event_type="TICKER",
            event_time=now,
            received_at=now,
            exchange_code="UPBIT",
            price=Decimal(p),
            change_rate=Decimal("0.01"),
            raw_sequence=i + 1,
        )
        sig = ev.evaluate(event, position=position, allow_signal=True)
        if sig is None:
            continue
        st = str(sig.signal_type)
        signals.append(
            {
                "type": st,
                "reason": sig.reason_code,
                "price": str(sig.reference_price),
            }
        )
        if st == SignalType.BUY.value:
            position = RealtimePositionState(
                quantity=Decimal("1"),
                average_entry_price=Decimal(p),
            )
        elif st in {SignalType.SELL.value, SignalType.EXIT.value}:
            position = RealtimePositionState(
                quantity=Decimal("0"),
                average_entry_price=None,
            )
    buy_n = sum(1 for s in signals if s["type"] == "BUY")
    sell_n = sum(1 for s in signals if s["type"] == "SELL")
    return {
        "signals": signals,
        "buy_count": buy_n,
        "sell_count": sell_n,
        "adapter_create_order": 0,
        "v1_orders": 0,
        "ok": buy_n >= 1 and sell_n >= 1,
    }


def main() -> None:
    report: dict = {"steps": []}
    session = get_session_factory()()
    try:
        owner = _user(user_id=OWNER_USER_ID, is_admin=False)
        admin = _user(user_id=1, is_admin=True)
        service = StrategyDefinitionService(session)

        # 1) Definition 생성 (active=false)
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        row = service.create_user_strategy(
            owner,
            strategy_code=f"UPBIT_MA_XRP_V1_{stamp}",
            name="UPBIT MA Crossover KRW-XRP",
            description=(
                "First UPBIT autotrading validation strategy. "
                "MovingAverageStrategyEvaluator compatible."
            ),
            market_type="CRYPTO",
            parameter_payload=dict(PARAMS),
            actor=ACTOR_USER,
        )
        session.flush()
        strategy_id = int(row.strategy_id)
        report["steps"].append(
            {
                "create": True,
                "strategy_id": strategy_id,
                "is_active": bool(row.is_active),
                "approved_at": None,
            }
        )
        assert market_compatible(
            market_type="CRYPTO", account_broker="UPBIT"
        )

        # 2) Backtest (공식 Persistence)
        backtest: dict = {}
        try:
            run, result = BacktestPersistenceService(
                session
            ).run_and_save_moving_average(
                exchange_code="UPBIT",
                symbol="KRW-XRP",
                start_date=date(2024, 1, 1),
                end_date=date(2026, 8, 1),
                initial_capital=Decimal("1000000"),
                short_window=int(PARAMS["short_window"]),
                long_window=int(PARAMS["long_window"]),
                stop_loss_ratio=Decimal(PARAMS["stop_loss_ratio"]),
                take_profit_ratio=Decimal(PARAMS["take_profit_ratio"]),
                position_ratio=Decimal(PARAMS["position_ratio"]),
                fee_ratio=Decimal("0.0005"),
                sell_tax_ratio=Decimal("0"),
                slippage_ratio=Decimal("0"),
            )
            session.flush()
            summary = result.summary
            analytics = None
            try:
                analytics = analyze_backtest_run(
                    session, int(run.backtest_run_id)
                )
            except Exception as exc:  # noqa: BLE001
                analytics = {"error": f"{type(exc).__name__}:{exc}"[:200]}
            backtest = {
                "status": "OK",
                "backtest_run_id": int(run.backtest_run_id),
                "period": {
                    "start": str(result.start_date),
                    "end": str(result.end_date),
                },
                "trade_count": int(summary.trade_count),
                "win_rate": str(summary.win_rate),
                "total_return_rate": str(summary.total_return_rate),
                "mdd": str(summary.maximum_drawdown_rate),
                "initial_capital": str(summary.initial_capital),
                "final_equity": str(summary.final_equity),
                "total_profit_loss": str(summary.total_profit_loss),
                "analytics": analytics
                if isinstance(analytics, dict)
                else (
                    {
                        "sharpe": getattr(analytics, "sharpe_ratio", None),
                        "profit_factor": getattr(
                            analytics, "profit_factor", None
                        ),
                        "grade": getattr(analytics, "grade", None),
                    }
                    if analytics is not None
                    else None
                ),
            }
        except BacktestValidationError as exc:
            msg = str(exc)
            if "empty" in msg.lower() or "insufficient" in msg.lower():
                backtest = {"status": "DATA_INSUFFICIENT", "error": msg}
            else:
                backtest = {"status": "FAIL", "error": msg}
        report["backtest"] = backtest

        # 3) Paper/Shadow MA cycle
        paper = _paper_shadow_ma_cycle(strategy_id=strategy_id)
        report["paper_shadow"] = paper

        # 4) 공식 승인 + 활성 (Admin Service)
        # 성과 왜곡 없이 관리자 승인 workflow — 단순 MA Definition 승인
        service.admin_approve(
            strategy_id, actor=ACTOR_ADMIN, approve=True
        )
        service.admin_set_active(
            strategy_id, is_active=True, actor=ACTOR_ADMIN
        )
        session.flush()
        approved = service.require(strategy_id)
        report["approval"] = {
            "approved_at": str(approved.approved_at),
            "approved_by": approved.approved_by,
            "is_active": bool(approved.is_active),
            "live_definition_approved": approved.approved_at is not None,
        }

        # 5) UBA 1380 link (owner user) — Runtime RUN 없음
        link = service.link_to_account(
            owner,
            strategy_id=strategy_id,
            paper_account_id=None,
            user_broker_account_id=UBA_ID,
            account_broker="UPBIT",
            actor=ACTOR_USER,
        )
        session.flush()
        report["link"] = {
            "link_id": int(link.account_strategy_link_id),
            "strategy_id": strategy_id,
            "uba_id": UBA_ID,
            "is_active": bool(link.is_active),
            "user_id": int(link.user_id),
            "runtime_started": False,
        }

        # duplicate link 시도 → 별도 검증은 테스트에서
        session.commit()

        # 6) Readiness (주문/런타임 변경 없음)
        ready = evaluate_uba_autotrading_ready(
            session, user_broker_account_id=UBA_ID
        )
        report["readiness"] = {
            "status": ready["status"],
            "runtime_status": ready.get("runtime_status"),
            "blockers": ready["blockers"],
            "warnings": ready.get("warnings"),
            "strategy_required_removed": "STRATEGY_REQUIRED"
            not in ready["blockers"],
            "strategy_links": ready["checks"].get("strategy_links"),
            "live": ready["checks"].get("live"),
            "worker": ready["checks"].get("live_outbox_worker"),
        }

        # 운영 플래그 미변경 확인
        from sqlalchemy import text

        uba = session.execute(
            text(
                "SELECT live_order_enabled, live_armed, live_approved_at "
                "FROM trading.user_broker_account "
                "WHERE user_broker_account_id = :id"
            ),
            {"id": UBA_ID},
        ).mappings().one()
        report["ops_unchanged"] = {
            "live_order_enabled": bool(uba["live_order_enabled"]),
            "live_armed": bool(uba["live_armed"]),
            "live_approved_at": uba["live_approved_at"],
        }
        report["strategy_id"] = strategy_id
        report["params"] = PARAMS

        print(json.dumps(report, ensure_ascii=False, default=_ser, indent=2))
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
