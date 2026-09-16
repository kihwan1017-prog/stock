"""REAL Exit Protection V1 — SL/TP/Trailing activation/MaxHold 경계·우선순위."""

from __future__ import annotations

from decimal import Decimal

from stock_platform.risk.engine import RiskManagementEngine
from stock_platform.risk.models import ExitEvaluationRequest

ENTRY = Decimal("100")
SL_RATIO = Decimal("0.03")  # -3%
TP_RATIO = Decimal("0.02")  # +2%
TRAIL_ACT = Decimal("0.01")  # +1% arm
TRAIL_DD = Decimal("0.008")  # 0.80% drawdown from peak
MAX_HOLD = 6 * 3600  # 6h


def _base(**overrides: object) -> ExitEvaluationRequest:
    """공통 ExitEvaluationRequest — 테스트마다 필요한 필드만 덮어씀."""

    payload: dict = {
        "entry_price": ENTRY,
        "current_price": ENTRY,
        "highest_price": ENTRY,
        "stop_loss_price": ENTRY * (Decimal("1") - SL_RATIO),
        "take_profit_price": ENTRY * (Decimal("1") + TP_RATIO),
        "trailing_stop_ratio": TRAIL_DD,
        "trailing_activation_ratio": TRAIL_ACT,
        "trailing_armed": False,
        "holding_seconds": 0,
        "max_hold_seconds": MAX_HOLD,
    }
    payload.update(overrides)
    return ExitEvaluationRequest(**payload)  # type: ignore[arg-type]


def test_stop_loss_boundary_2_99_no_3_00_yes() -> None:
    engine = RiskManagementEngine()
    # -2.99% → 미청산 (highest는 entry 이상 유지)
    no = engine.evaluate_exit(
        _base(current_price=Decimal("97.01"), highest_price=ENTRY)
    )
    assert no.should_exit is False

    # -3.00% → STOP_LOSS
    yes = engine.evaluate_exit(
        _base(current_price=Decimal("97.00"), highest_price=ENTRY)
    )
    assert yes.should_exit is True
    assert yes.reason == "STOP_LOSS"


def test_take_profit_boundary_1_99_no_2_00_yes() -> None:
    engine = RiskManagementEngine()
    # trailing/hold 비활성 — TP만 검증
    no = engine.evaluate_exit(
        _base(
            current_price=Decimal("101.99"),
            highest_price=Decimal("101.99"),
            trailing_stop_ratio=None,
            max_hold_seconds=None,
        )
    )
    assert no.should_exit is False

    yes = engine.evaluate_exit(
        _base(
            current_price=Decimal("102.00"),
            highest_price=Decimal("102.00"),
            trailing_stop_ratio=None,
            max_hold_seconds=None,
        )
    )
    assert yes.should_exit is True
    assert yes.reason == "TAKE_PROFIT"


def test_trailing_activation_then_drawdown_0_79_no_0_80_yes() -> None:
    engine = RiskManagementEngine()
    # activation(+1%) 전 — peak +0.5% → trailing 미발화
    before = engine.evaluate_exit(
        _base(
            current_price=Decimal("100.50"),
            highest_price=Decimal("100.50"),
            trailing_armed=False,
            stop_loss_price=None,
            take_profit_price=None,
            max_hold_seconds=None,
        )
    )
    assert before.should_exit is False

    peak = Decimal("101")  # +1% armed
    # drawdown 0.79% from peak → trigger = 101 * (1-0.008) = 100.192
    # 0.79% → 101 * 0.9921 = 100.2021 > trigger
    dd079 = (peak * (Decimal("1") - Decimal("0.0079"))).quantize(
        Decimal("0.00000001")
    )
    no = engine.evaluate_exit(
        _base(
            current_price=dd079,
            highest_price=peak,
            trailing_armed=True,
            stop_loss_price=None,
            take_profit_price=None,
            max_hold_seconds=None,
        )
    )
    assert no.should_exit is False

    dd080 = (peak * (Decimal("1") - Decimal("0.0080"))).quantize(
        Decimal("0.00000001")
    )
    yes = engine.evaluate_exit(
        _base(
            current_price=dd080,
            highest_price=peak,
            trailing_armed=True,
            stop_loss_price=None,
            take_profit_price=None,
            max_hold_seconds=None,
        )
    )
    assert yes.should_exit is True
    assert yes.reason == "TRAILING_STOP"


def test_max_hold_boundary_5h59m59_no_6h_yes() -> None:
    engine = RiskManagementEngine()
    no = engine.evaluate_exit(
        _base(
            holding_seconds=MAX_HOLD - 1,  # 5:59:59
            stop_loss_price=None,
            take_profit_price=None,
            trailing_stop_ratio=None,
        )
    )
    assert no.should_exit is False

    yes = engine.evaluate_exit(
        _base(
            holding_seconds=MAX_HOLD,  # 6:00:00
            stop_loss_price=None,
            take_profit_price=None,
            trailing_stop_ratio=None,
        )
    )
    assert yes.should_exit is True
    assert yes.reason == "MAX_HOLD_TIME"


def test_precedence_stop_loss_wins_over_max_hold() -> None:
    engine = RiskManagementEngine()
    decision = engine.evaluate_exit(
        _base(
            current_price=Decimal("97.00"),  # SL hit
            highest_price=ENTRY,
            holding_seconds=MAX_HOLD,  # max hold도 충족
        )
    )
    assert decision.should_exit is True
    assert decision.reason == "STOP_LOSS"


def test_one_decision_only_single_reason() -> None:
    """동시에 여러 조건이 맞아도 reason은 하나."""

    engine = RiskManagementEngine()
    # SL + max hold + (가격상) TP 근처 — SL만
    decision = engine.evaluate_exit(
        _base(
            current_price=Decimal("97.00"),
            highest_price=Decimal("110"),
            holding_seconds=MAX_HOLD,
            trailing_armed=True,
        )
    )
    assert decision.should_exit is True
    assert decision.reason == "STOP_LOSS"
    # 동일 요청 재평가해도 동일 단일 결정
    again = engine.evaluate_exit(
        _base(
            current_price=Decimal("97.00"),
            highest_price=Decimal("110"),
            holding_seconds=MAX_HOLD,
            trailing_armed=True,
        )
    )
    assert again.reason == decision.reason
    assert again.should_exit is True


def test_terminal_cancelled_sell_not_outstanding_despite_outbox_intent() -> None:
    """CANCELLED + Outbox DONE(dispatch_intent 잔존) → pending-sell 재차단 금지."""

    from datetime import datetime, timezone
    from types import SimpleNamespace

    from stock_platform.order.models import OrderStatus
    from stock_platform.risk_engine.exit_risk import is_order_outstanding_for_sell

    cancelled = SimpleNamespace(
        status_code=OrderStatus.CANCELLED.value,
        order_quantity=Decimal("33.33333333"),
        remaining_quantity=Decimal("33.33333333"),
        filled_quantity=Decimal("0"),
        broker_order_id="uuid-cancelled",
        reason_code=None,
        metadata_payload={},
    )
    done_outbox = SimpleNamespace(
        status_code="DONE",
        confirmation_status=None,
        manual_review_reason=None,
        last_error=None,
        dispatch_intent_at=datetime(2026, 8, 27, 17, 29, 50, tzinfo=timezone.utc),
    )
    assert is_order_outstanding_for_sell(cancelled, done_outbox) is False

    filled = SimpleNamespace(
        status_code=OrderStatus.FILLED.value,
        order_quantity=Decimal("1"),
        remaining_quantity=Decimal("0"),
        filled_quantity=Decimal("1"),
        broker_order_id="uuid-filled",
        reason_code=None,
        metadata_payload={},
    )
    assert is_order_outstanding_for_sell(filled, done_outbox) is False
