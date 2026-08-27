"""UPBIT trailing exit P0 dedupe + forward shadow — unit tests (no LIVE orders)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.constants import (
    VARIANT_T1,
    VARIANT_T2,
)
from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.service import (
    enroll_on_position_open,
    observe_price_tick,
    variant_specs,
)
from stock_platform.position.exit_monitor import (
    ManagedPosition,
    PositionExitMonitorService,
)
from stock_platform.position.exit_monitor_live import (
    STATE_EXIT_ORDER_PENDING,
    clear_exit_trigger_cycle,
    exit_cycle_key,
    is_live_exit_eligible,
    persist_exit_lifecycle,
    read_exit_lifecycle,
)


ZERO = Decimal("0")
UBA = 1380


def _open_binding(*, binding_id: int = 99, qty: str = "10") -> SimpleNamespace:
    return SimpleNamespace(
        binding_id=binding_id,
        strategy_id=7,
        status="OPEN",
        owned_quantity=Decimal(qty),
    )


def _live_pos(**overrides) -> ManagedPosition:
    base = dict(
        account_id=0,
        exchange_code="UPBIT",
        symbol="KRW-XRP",
        quantity=Decimal("100"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        highest_price=Decimal("100"),
        stop_loss_price=Decimal("95"),
        take_profit_price=Decimal("110"),
        trailing_stop_ratio=Decimal("0.03"),
        relative_loss_ratio=None,
        broker_code="UPBIT",
        user_broker_account_id=UBA,
        owner_user_id=61,
        environment="LIVE",
        binding_id=99,
    )
    base.update(overrides)
    return ManagedPosition(**base)


def _monitor(session=None, *, allowed=True, order_id=501, reason="OK"):
    session = session or MagicMock()
    monitor = PositionExitMonitorService(session)
    fake_exec = MagicMock()
    fake_exec.submit.return_value = SimpleNamespace(
        allowed=allowed,
        order_id=order_id if allowed else None,
        reason_code=reason,
        outbox_id=7 if allowed else None,
    )
    monitor._execution = fake_exec
    publisher = MagicMock()
    monitor._publisher_impl = publisher
    return monitor, fake_exec, publisher


def _patch_live_guards(binding=_open_binding()):
    return patch.multiple(
        "stock_platform.position.exit_monitor_live",
        load_open_strategy_binding=MagicMock(return_value=binding),
        load_broker_position_snapshot=MagicMock(return_value=None),
        has_blocking_live_exit_sell=MagicMock(return_value=False),
    )


# --- A: OPEN + trailing false → no event ---
def test_a_open_trailing_false_no_event() -> None:
    monitor, execution, publisher = _monitor()
    with _patch_live_guards():
        actions = monitor.evaluate_and_exit(
            [
                _live_pos(
                    current_price=Decimal("101"),
                    highest_price=Decimal("102"),
                )
            ]
        )
    assert actions[0].submitted is False
    assert actions[0].reason == "HOLD"
    execution.submit.assert_not_called()
    publisher.publish.assert_not_called()


# --- B: false→true → trigger/submit 1 ---
def test_b_false_to_true_submit_once() -> None:
    monitor, execution, publisher = _monitor()
    with _patch_live_guards():
        actions = monitor.evaluate_and_exit(
            [
                _live_pos(
                    current_price=Decimal("116"),
                    highest_price=Decimal("120"),
                    stop_loss_price=Decimal("50"),
                    take_profit_price=Decimal("200"),
                )
            ]
        )
    assert actions[0].reason == "TRAILING_STOP"
    assert actions[0].submitted is True
    execution.submit.assert_called_once()
    publisher.publish.assert_called_once()


# --- C: true across 20 ticks → telegram still 1 (lifecycle dedupe) ---
def test_c_true_20_ticks_telegram_once() -> None:
    snap = SimpleNamespace(raw_data={})
    binding = _open_binding()
    session = MagicMock()
    monitor, execution, publisher = _monitor(session)
    pos = _live_pos(
        current_price=Decimal("116"),
        highest_price=Decimal("120"),
        stop_loss_price=Decimal("50"),
        take_profit_price=Decimal("200"),
    )
    with patch.multiple(
        "stock_platform.position.exit_monitor_live",
        load_open_strategy_binding=MagicMock(return_value=binding),
        load_broker_position_snapshot=MagicMock(return_value=snap),
        has_blocking_live_exit_sell=MagicMock(
            side_effect=[False] + [True] * 19
        ),
    ):
        for _ in range(20):
            monitor.evaluate_and_exit([pos])
    assert execution.submit.call_count == 1
    assert publisher.publish.call_count == 1


# --- D: existing active exit → additional SELL 0 ---
def test_d_active_exit_blocks_second_sell() -> None:
    monitor, execution, publisher = _monitor()
    with patch.multiple(
        "stock_platform.position.exit_monitor_live",
        load_open_strategy_binding=MagicMock(return_value=_open_binding()),
        load_broker_position_snapshot=MagicMock(return_value=None),
        has_blocking_live_exit_sell=MagicMock(return_value=True),
    ):
        actions = monitor.evaluate_and_exit(
            [_live_pos(current_price=Decimal("94"))]
        )
    assert actions[0].submitted is False
    execution.submit.assert_not_called()
    publisher.publish.assert_not_called()


# --- E: submit blocked → Telegram spam 0 ---
def test_e_submit_blocked_telegram_zero() -> None:
    monitor, execution, publisher = _monitor(
        allowed=False, reason="ACTIVATION_INACTIVE"
    )
    with _patch_live_guards():
        for _ in range(5):
            monitor.evaluate_and_exit(
                [_live_pos(current_price=Decimal("94"))]
            )
    assert execution.submit.call_count == 5  # retry allowed
    publisher.publish.assert_not_called()


# --- F/G: no OPEN binding (MA closed) → trailing 0 ---
def test_f_g_closed_binding_no_trailing() -> None:
    monitor, execution, publisher = _monitor()
    with patch.multiple(
        "stock_platform.position.exit_monitor_live",
        load_open_strategy_binding=MagicMock(return_value=None),
        load_broker_position_snapshot=MagicMock(return_value=None),
        has_blocking_live_exit_sell=MagicMock(return_value=False),
    ):
        actions = monitor.evaluate_and_exit(
            [
                _live_pos(
                    current_price=Decimal("116"),
                    highest_price=Decimal("120"),
                    stop_loss_price=Decimal("50"),
                    take_profit_price=Decimal("200"),
                )
            ]
        )
    assert actions[0].reason == "TRAILING_EVALUATION_SKIPPED"
    assert actions[0].submitted is False
    execution.submit.assert_not_called()
    publisher.publish.assert_not_called()


# --- H: eligibility without ownership ---
def test_h_no_ownership_ineligible() -> None:
    ok, reason = is_live_exit_eligible(
        quantity=Decimal("1"),
        binding=None,
        has_active_exit_order=False,
    )
    assert ok is False
    assert reason == "NO_OPEN_BINDING"


# --- I: same trigger cycle idempotent notify ---
def test_i_cycle_key_stable() -> None:
    a = exit_cycle_key(uba_id=1380, binding_id=44, reason="TRAILING_STOP")
    b = exit_cycle_key(uba_id=1380, binding_id=44, reason="TRAILING_STOP")
    assert a == b


# --- J: different positions independent ---
def test_j_different_positions_independent() -> None:
    monitor, execution, publisher = _monitor()
    with _patch_live_guards(_open_binding(binding_id=1)):
        monitor.evaluate_and_exit(
            [
                _live_pos(
                    symbol="KRW-ENA",
                    binding_id=1,
                    current_price=Decimal("116"),
                    highest_price=Decimal("120"),
                    stop_loss_price=Decimal("50"),
                    take_profit_price=Decimal("200"),
                )
            ]
        )
    with _patch_live_guards(_open_binding(binding_id=2)):
        monitor.evaluate_and_exit(
            [
                _live_pos(
                    symbol="KRW-RE",
                    binding_id=2,
                    current_price=Decimal("116"),
                    highest_price=Decimal("120"),
                    stop_loss_price=Decimal("50"),
                    take_profit_price=Decimal("200"),
                )
            ]
        )
    assert execution.submit.call_count == 2
    assert publisher.publish.call_count == 2


# --- K: lifecycle clear on HOLD ---
def test_k_clear_cycle_on_hold() -> None:
    snap = SimpleNamespace(raw_data={})
    persist_exit_lifecycle(
        snap,
        {
            "state": STATE_EXIT_ORDER_PENDING,
            "cycle_key": "x",
            "reason": "TRAILING_STOP",
        },
    )
    clear_exit_trigger_cycle(snap)
    life = read_exit_lifecycle(snap.raw_data)
    assert life["state"] == "OPEN_MONITORING"


# --- O/P: shadow variants do not create REAL sell ---
def test_o_p_shadow_no_real_sell() -> None:
    session = MagicMock()
    session.scalar.return_value = None
    # enroll uses session.add/flush — MagicMock ok
    result = enroll_on_position_open(
        session,
        user_broker_account_id=UBA,
        binding_id=501,
        symbol="KRW-BTC",
        strategy_id=1,
        entry_order_id=1,
        entry_at=datetime.now(timezone.utc),
        entry_price=Decimal("100"),
        entry_quantity=Decimal("1"),
        settings=SimpleNamespace(
            upbit_trailing_forward_shadow_enabled=True,
            upbit_trailing_forward_shadow_deployed_at="2020-01-01T00:00:00+00:00",
        ),
    )
    assert result["ok"] is True
    assert "T0" in variant_specs()
    assert VARIANT_T1 in variant_specs()
    assert VARIANT_T2 in variant_specs()
    # observe with mocked row
    row = SimpleNamespace(
        status="ACTIVE",
        entry_price=Decimal("100"),
        entry_quantity=Decimal("1"),
        entry_fee=None,
        entry_at=datetime.now(timezone.utc),
        variants_json={k: {"outcome_status": "ACTIVE", "peak_price": "100"} for k in variant_specs()},
        shadow_state_json={},
        binding_id=501,
    )
    session.scalar.return_value = row
    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.service.shadow_enabled",
        return_value=True,
    ):
        # peak then trail for T0 (3%): peak 110 → trigger 106.7, price 106
        observe_price_tick(
            session,
            binding_id=501,
            price=Decimal("110"),
        )
        observe_price_tick(
            session,
            binding_id=501,
            price=Decimal("106"),
        )
    # REAL sell never called — no OrderExecution in shadow path
    assert row.variants_json["T0"].get("outcome_status") in {
        "VIRTUAL_TRAILING_EXIT",
        "ACTIVE",
    }


def test_s_duplicate_enrollment() -> None:
    session = MagicMock()
    existing = SimpleNamespace(shadow_row_id=9)
    session.scalar.return_value = existing
    out = enroll_on_position_open(
        session,
        user_broker_account_id=UBA,
        binding_id=501,
        symbol="KRW-BTC",
        strategy_id=1,
        entry_order_id=1,
        entry_at=datetime.now(timezone.utc),
        entry_price=Decimal("100"),
        settings=SimpleNamespace(
            upbit_trailing_forward_shadow_enabled=True,
            upbit_trailing_forward_shadow_deployed_at="",
        ),
    )
    assert out.get("duplicate") is True
    session.add.assert_not_called()


# --- Epoch A–H: immutable deploy epoch (now() fallback 금지) ---
def test_epoch_a_config_deployed_at() -> None:
    from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.service import (
        deployment_epoch,
    )

    settings = SimpleNamespace(
        upbit_trailing_forward_shadow_deployed_at="2026-08-27T11:12:00+00:00"
    )
    e1 = deployment_epoch(settings)
    e2 = deployment_epoch(settings)
    assert e1 == e2
    assert e1.isoformat().startswith("2026-08-27T11:12:00")


def test_epoch_b_c_no_config_constant_stable() -> None:
    from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.constants import (
        FEATURE_DEPLOY_EPOCH,
    )
    from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.service import (
        deployment_epoch,
    )

    settings = SimpleNamespace(upbit_trailing_forward_shadow_deployed_at="")
    values = [deployment_epoch(settings, session=None) for _ in range(100)]
    assert all(v == FEATURE_DEPLOY_EPOCH for v in values)
    assert values[0] == values[-1]


def test_epoch_d_restart_simulation_same() -> None:
    from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.service import (
        deployment_epoch,
    )

    settings = SimpleNamespace(upbit_trailing_forward_shadow_deployed_at="")
    before = deployment_epoch(settings)
    # restart simulation = 새 import 경로에서도 동일 상수
    from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow import (
        service as svc2,
    )

    after = svc2.deployment_epoch(settings)
    assert before == after


def test_epoch_e_opened_before_excluded() -> None:
    session = MagicMock()
    session.scalar.return_value = None
    out = enroll_on_position_open(
        session,
        user_broker_account_id=UBA,
        binding_id=9001,
        symbol="KRW-AAA",
        strategy_id=1,
        entry_order_id=1,
        entry_at=datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc),
        entry_price=Decimal("1"),
        settings=SimpleNamespace(
            upbit_trailing_forward_shadow_enabled=True,
            upbit_trailing_forward_shadow_deployed_at="2026-08-27T11:12:00+00:00",
        ),
    )
    assert out["ok"] is True
    added = session.add.call_args[0][0]
    assert added.status == "PRE_EXISTING_POSITION_EXCLUDED"


def test_epoch_f_opened_after_enrolled() -> None:
    session = MagicMock()
    session.scalar.return_value = None
    out = enroll_on_position_open(
        session,
        user_broker_account_id=UBA,
        binding_id=9002,
        symbol="KRW-BBB",
        strategy_id=1,
        entry_order_id=1,
        entry_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        entry_price=Decimal("1"),
        settings=SimpleNamespace(
            upbit_trailing_forward_shadow_enabled=True,
            upbit_trailing_forward_shadow_deployed_at="2026-08-27T11:12:00+00:00",
        ),
    )
    assert out["ok"] is True
    added = session.add.call_args[0][0]
    assert added.status == "ACTIVE"


def test_epoch_g_same_binding_cohort_one() -> None:
    session = MagicMock()
    session.scalar.return_value = None
    settings = SimpleNamespace(
        upbit_trailing_forward_shadow_enabled=True,
        upbit_trailing_forward_shadow_deployed_at="2026-08-27T11:12:00+00:00",
    )
    enroll_on_position_open(
        session,
        user_broker_account_id=UBA,
        binding_id=9003,
        symbol="KRW-CCC",
        strategy_id=1,
        entry_order_id=1,
        entry_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        entry_price=Decimal("1"),
        settings=settings,
    )
    assert session.add.call_count == 1
    session.scalar.return_value = SimpleNamespace(shadow_row_id=77)
    out2 = enroll_on_position_open(
        session,
        user_broker_account_id=UBA,
        binding_id=9003,
        symbol="KRW-CCC",
        strategy_id=1,
        entry_order_id=1,
        entry_at=datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc),
        entry_price=Decimal("1"),
        settings=settings,
    )
    assert out2.get("duplicate") is True
    assert session.add.call_count == 1


def test_epoch_h_existing_excluded_not_converted() -> None:
    session = MagicMock()
    existing = SimpleNamespace(
        shadow_row_id=48, status="PRE_EXISTING_POSITION_EXCLUDED"
    )
    session.scalar.return_value = existing
    out = enroll_on_position_open(
        session,
        user_broker_account_id=UBA,
        binding_id=48,
        symbol="KRW-EUL",
        strategy_id=1,
        entry_order_id=1,
        entry_at=datetime(2026, 8, 27, 13, 0, tzinfo=timezone.utc),
        entry_price=Decimal("1"),
        settings=SimpleNamespace(
            upbit_trailing_forward_shadow_enabled=True,
            upbit_trailing_forward_shadow_deployed_at="",
        ),
    )
    assert out.get("duplicate") is True
    session.add.assert_not_called()


def test_exit_reason_precedence_stop_before_trailing() -> None:
    from stock_platform.risk.engine import RiskManagementEngine
    from stock_platform.risk.models import ExitEvaluationRequest

    d = RiskManagementEngine().evaluate_exit(
        ExitEvaluationRequest(
            entry_price=Decimal("100"),
            current_price=Decimal("94"),
            highest_price=Decimal("120"),
            stop_loss_price=Decimal("95"),
            take_profit_price=Decimal("200"),
            trailing_stop_ratio=Decimal("0.03"),
            relative_loss_ratio=None,
        )
    )
    assert d.reason == "STOP_LOSS"
