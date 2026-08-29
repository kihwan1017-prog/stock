# -*- coding: utf-8 -*-
"""Historical exit recovery DETECT_ONLY + Long Hold Watch V1 tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from stock_platform.operation.upbit_historical_exit_recovery.constants import (
    MODE_DETECT_ONLY,
    PROPOSED_ACTION_CREATE_INTENT,
    PROPOSED_INTENT_STATUS,
)
from stock_platform.operation.upbit_historical_exit_recovery.service import (
    dry_run_historical_exit_recovery,
    evaluate_candidate,
    evaluate_exit_condition,
)
from stock_platform.operation.upbit_long_hold_watch.checkpoints import (
    dedupe_key,
    long_hold_badge,
    select_latest_checkpoint,
)
from stock_platform.operation.upbit_long_hold_watch.service import (
    build_long_hold_summary,
    exit_state_user_label,
    format_long_hold_alert,
)


def test_select_checkpoint_under_6h():
    assert select_latest_checkpoint(5 * 3600) is None
    assert select_latest_checkpoint(None) is None


def test_select_checkpoint_6_12_24():
    assert select_latest_checkpoint(6 * 3600) == "6H"
    assert select_latest_checkpoint(12 * 3600) == "12H"
    assert select_latest_checkpoint(24 * 3600) == "24H"


def test_select_checkpoint_40h_only_24h():
    assert select_latest_checkpoint(40.6 * 3600) == "24H"


def test_select_checkpoint_48h():
    assert select_latest_checkpoint(48 * 3600) == "48H"
    assert select_latest_checkpoint(72 * 3600) == "72H"


def test_long_hold_badge_tooltip():
    b = long_hold_badge(40 * 3600)
    assert b is not None
    assert "자동 청산" in b["tooltip"]
    assert "24h+" in b["label"]


def test_dedupe_key_stable():
    assert dedupe_key(position_id=62, checkpoint="24H") == "LONG_HOLD:62:24H"


def test_format_long_hold_alert_pnl_label_and_no_json():
    title, body = format_long_hold_alert(
        {
            "symbol": "KRW-ADA",
            "symbol_name": "에이다",
            "holding_seconds": int(40.6 * 3600),
            "entry_price": "300",
            "current_price": "278.5",
            "current_price_stale": False,
            "estimated_pnl": -726.3,
            "estimated_pnl_rate_pct": -7.26,
            "exit_state": "BEARISH_WAITING_EDGE",
            "auto_slot_used": 1,
            "auto_slot_limit": 6,
        }
    )
    assert "장기보유" in title
    assert "평가손익" in body
    assert "순손익" not in body
    assert "자동매도 알림이 아닙니다" in body
    assert "{" not in body


def test_format_long_hold_stale_price():
    _, body = format_long_hold_alert(
        {
            "symbol": "KRW-ADA",
            "holding_seconds": 7 * 3600,
            "entry_price": "300",
            "current_price": None,
            "current_price_stale": True,
            "exit_state": "STALE_PRICE",
        }
    )
    assert "데이터 확인 필요" in body


def test_exit_state_labels():
    assert "대기" in exit_state_user_label("NO_EXIT_SIGNAL")
    assert "약세" in exit_state_user_label("BEARISH_WAITING_EDGE")
    assert "진행" in exit_state_user_label("ORDER_PENDING")


def test_ma_bearish_no_new_edge_active():
    cond = evaluate_exit_condition(
        short_ma=Decimal("278"),
        long_ma=Decimal("280"),
        prev_short_ma=Decimal("278.5"),
        prev_long_ma=Decimal("280"),
    )
    assert cond["ma_state"] == "BEARISH"
    assert cond["dead_cross_edge"] is False
    assert cond["current_exit_condition_active"] is True
    assert cond["new_edge_required_for_recovery"] is False


def test_ma_bullish_inactive():
    cond = evaluate_exit_condition(
        short_ma=Decimal("310"),
        long_ma=Decimal("300"),
    )
    assert cond["current_exit_condition_active"] is False


def _binding(**kwargs):
    base = {
        "binding_id": 62,
        "user_broker_account_id": 1380,
        "symbol": "KRW-ADA",
        "status": "OPEN",
        "ownership_code": "STRATEGY_OWNED",
        "entry_order_id": 1925,
        "owned_quantity": Decimal("33.33333333"),
        "entry_price": Decimal("300"),
        "opened_at": datetime.now(timezone.utc) - timedelta(hours=40),
        "meta_json": {},
    }
    base.update(kwargs)
    return base


def _eligible_patches():
    return (
        patch(
            "stock_platform.operation.upbit_historical_exit_recovery.service._broker_qty",
            return_value=Decimal("33.33333333"),
        ),
        patch(
            "stock_platform.operation.upbit_historical_exit_recovery.service._has_active_intent",
            return_value=False,
        ),
        patch(
            "stock_platform.operation.upbit_historical_exit_recovery.service._blocking_lifecycle",
            return_value=[],
        ),
        patch(
            "stock_platform.operation.upbit_historical_exit_recovery.service._find_orphan_exit_order",
            return_value={
                "order_id": 1926,
                "blocked": False,
                "filled_quantity": "0",
                "status_code": "CANCELLED",
                "exit_reason": "MA_DEAD_CROSS",
            },
        ),
        patch(
            "stock_platform.operation.upbit_historical_exit_recovery.service._quote_price",
            return_value=(Decimal("278.5"), datetime.now(timezone.utc), False),
        ),
        patch(
            "stock_platform.operation.upbit_historical_exit_recovery.service._slot_info",
            return_value={"slot_id": 4, "slot_no": 1},
        ),
    )


def test_evaluate_manual_excluded():
    out = evaluate_candidate(
        MagicMock(),
        binding=_binding(ownership_code="MANUAL"),
        short_ma=Decimal("270"),
        long_ma=Decimal("280"),
    )
    assert "MANUAL_EXCLUDED" in out["blockers"]
    assert out["db_mutated"] is False


def test_evaluate_unknown_excluded():
    out = evaluate_candidate(
        MagicMock(),
        binding=_binding(ownership_code="UNKNOWN"),
        short_ma=Decimal("270"),
        long_ma=Decimal("280"),
    )
    assert "UNKNOWN_EXCLUDED" in out["blockers"]


def test_evaluate_flat_excluded():
    with patch(
        "stock_platform.operation.upbit_historical_exit_recovery.service._broker_qty",
        return_value=Decimal("0"),
    ):
        out = evaluate_candidate(
            MagicMock(),
            binding=_binding(owned_quantity=Decimal("0")),
            short_ma=Decimal("270"),
            long_ma=Decimal("280"),
        )
    assert "POSITION_FLAT" in out["blockers"]


def test_evaluate_broker_zero_excluded():
    patches = list(_eligible_patches())
    patches[0] = patch(
        "stock_platform.operation.upbit_historical_exit_recovery.service._broker_qty",
        return_value=Decimal("0"),
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        out = evaluate_candidate(
            MagicMock(),
            binding=_binding(),
            short_ma=Decimal("270"),
            long_ma=Decimal("280"),
        )
    assert "BROKER_QTY_ZERO" in out["blockers"]


def test_evaluate_qty_mismatch_blocked():
    patches = list(_eligible_patches())
    patches[0] = patch(
        "stock_platform.operation.upbit_historical_exit_recovery.service._broker_qty",
        return_value=Decimal("10"),
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        out = evaluate_candidate(
            MagicMock(),
            binding=_binding(),
            short_ma=Decimal("270"),
            long_ma=Decimal("280"),
        )
    assert "POSITION_BROKER_QTY_MISMATCH" in out["blockers"]


def test_evaluate_open_sell_and_intent_excluded():
    with (
        patch(
            "stock_platform.operation.upbit_historical_exit_recovery.service._broker_qty",
            return_value=Decimal("33.33333333"),
        ),
        patch(
            "stock_platform.operation.upbit_historical_exit_recovery.service._has_active_intent",
            return_value=True,
        ),
        patch(
            "stock_platform.operation.upbit_historical_exit_recovery.service._blocking_lifecycle",
            return_value=["OPEN_SELL_EXISTS"],
        ),
        patch(
            "stock_platform.operation.upbit_historical_exit_recovery.service._find_orphan_exit_order",
            return_value={
                "order_id": 1926,
                "blocked": False,
                "filled_quantity": "0",
                "status_code": "CANCELLED",
                "exit_reason": "MA_DEAD_CROSS",
            },
        ),
        patch(
            "stock_platform.operation.upbit_historical_exit_recovery.service._quote_price",
            return_value=(Decimal("278.5"), datetime.now(timezone.utc), False),
        ),
        patch(
            "stock_platform.operation.upbit_historical_exit_recovery.service._slot_info",
            return_value={},
        ),
    ):
        out = evaluate_candidate(
            MagicMock(),
            binding=_binding(),
            short_ma=Decimal("270"),
            long_ma=Decimal("280"),
        )
    assert "EXISTING_EXIT_INTENT" in out["blockers"]
    assert "OPEN_SELL_EXISTS" in out["blockers"]


def test_evaluate_partial_fill_blocked():
    patches = list(_eligible_patches())
    patches[3] = patch(
        "stock_platform.operation.upbit_historical_exit_recovery.service._find_orphan_exit_order",
        return_value={
            "order_id": 1926,
            "blocked": True,
            "block_reason": "PARTIAL_HISTORICAL_FILL",
            "filled_quantity": "10",
            "status_code": "CANCELLED",
            "exit_reason": "MA_DEAD_CROSS",
        },
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        out = evaluate_candidate(
            MagicMock(),
            binding=_binding(),
            short_ma=Decimal("270"),
            long_ma=Decimal("280"),
        )
    assert "PARTIAL_HISTORICAL_FILL" in out["blockers"]


def test_evaluate_missing_historical_exit():
    patches = list(_eligible_patches())
    patches[3] = patch(
        "stock_platform.operation.upbit_historical_exit_recovery.service._find_orphan_exit_order",
        return_value=None,
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        out = evaluate_candidate(
            MagicMock(),
            binding=_binding(),
            short_ma=Decimal("270"),
            long_ma=Decimal("280"),
        )
    assert "HISTORICAL_EXIT_ORDER_MISSING" in out["blockers"]


def test_evaluate_eligible_bearish_no_edge_dry_run_no_mutation():
    patches = _eligible_patches()
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        out = evaluate_candidate(
            MagicMock(),
            binding=_binding(),
            short_ma=Decimal("270"),
            long_ma=Decimal("280"),
            prev_short_ma=Decimal("271"),
            prev_long_ma=Decimal("281"),
        )
    assert out["eligible"] is True
    assert out["mode"] == MODE_DETECT_ONLY
    assert out["proposed"]["proposed_action"] == PROPOSED_ACTION_CREATE_INTENT
    assert out["proposed"]["proposed_intent_status"] == PROPOSED_INTENT_STATUS
    assert out["proposed"]["proposed_order"] == "NONE_IN_THIS_WRK"
    assert out["db_mutated"] is False
    assert out["order_created"] is False
    assert out["exit_intent_inserted"] is False
    assert out["ma_condition"]["dead_cross_edge"] is False


def test_dry_run_not_found():
    with patch(
        "stock_platform.operation.upbit_historical_exit_recovery.service.list_historical_exit_recovery_candidates",
        return_value={"candidates": []},
    ):
        out = dry_run_historical_exit_recovery(
            MagicMock(), user_broker_account_id=1380, symbol="KRW-ADA"
        )
    assert out["eligible"] is False
    assert out["db_mutated"] is False


def test_condition_inactive_classified():
    patches = _eligible_patches()
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        out = evaluate_candidate(
            MagicMock(),
            binding=_binding(),
            short_ma=Decimal("310"),
            long_ma=Decimal("300"),
        )
    assert "CURRENT_CONDITION_INACTIVE" in out["blockers"]


def test_long_hold_summary_reuse():
    s = build_long_hold_summary(
        [
            {
                "symbol": "KRW-ADA",
                "holding_seconds": 40 * 3600,
                "estimated_pnl_rate_pct": -7.2,
                "checkpoint": "24H",
            }
        ]
    )
    assert s["count"] == 1


def test_alert_preference_catalog_has_long_hold():
    from stock_platform.notification.alert_v2.categories import (
        AlertPreferenceKey,
        PREFERENCE_CATALOG,
    )
    from stock_platform.notification.alert_v2.mapping import resolve_preference_key

    assert any(r["key"] == "AUTO_LONG_HOLD" for r in PREFERENCE_CATALOG)
    assert (
        resolve_preference_key("UPBIT_AUTO_LONG_HOLD")
        == AlertPreferenceKey.AUTO_LONG_HOLD
    )


def test_telegram_allowlist_includes_long_hold():
    from stock_platform.notification.telegram_policy import (
        is_telegram_event_allowlisted,
    )

    assert is_telegram_event_allowlisted("UPBIT_AUTO_LONG_HOLD")


def test_run_long_hold_no_sell():
    from stock_platform.operation.upbit_long_hold_watch.service import (
        run_long_hold_watch_once,
    )

    emitted = []

    def _emit(detail):
        emitted.append(detail)
        return {"emitted": True, "dedupe_key": detail["dedupe_key"]}

    with patch(
        "stock_platform.operation.upbit_long_hold_watch.service.evaluate_long_hold_positions",
        return_value=[
            {
                "symbol": "KRW-ADA",
                "checkpoint": "24H",
                "dedupe_key": "LONG_HOLD:62:24H",
                "holding_seconds": 40 * 3600,
                "estimated_pnl_rate_pct": -7.2,
            }
        ],
    ):
        out = run_long_hold_watch_once(
            MagicMock(),
            user_broker_account_id=1380,
            emit=True,
            emit_fn=_emit,
        )
    assert out["sell_created"] == 0
    assert len(emitted) == 1
