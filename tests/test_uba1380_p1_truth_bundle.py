"""UBA1380 P1 truth bundle — fee / anomaly / risk snapshot / provenance / pnl fee flag.

Mock session only — real broker 호출 없음.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from stock_platform.operation.autotrading_truth_bundle import (
    build_risk_decision_snapshot,
    build_scanner_to_fill_provenance,
    fee_truth_summary,
    maybe_stamp_risk_decision_snapshot,
    pnl_fee_incomplete_from_trades,
    position_lifecycle_anomalies,
)


def _mapping_result(rows: list[dict]):
    """SQLAlchemy mappings().all() / first() 최소 mock."""

    class _Mappings:
        def __init__(self, data: list[dict]):
            self._data = data

        def all(self):
            return self._data

        def first(self):
            return self._data[0] if self._data else None

    class _Result:
        def __init__(self, data: list[dict]):
            self._data = data

        def mappings(self):
            return _Mappings(self._data)

    return _Result(rows)


def test_fee_truth_flags_buy_sell_partial_and_incomplete() -> None:
    session = MagicMock()
    order_rows = [
        {
            "order_id": 1,
            "side_code": "BUY",
            "status_code": "FILLED",
            "metadata_payload": {"upbit_paid_fee": "1.2"},
            "filled_quantity": 1,
            "order_quantity": 1,
        },
        {
            "order_id": 2,
            "side_code": "SELL",
            "status_code": "FILLED",
            "metadata_payload": {},  # fee 키 부재
            "filled_quantity": 1,
            "order_quantity": 1,
        },
        {
            "order_id": 3,
            "side_code": "BUY",
            "status_code": "PARTIALLY_FILLED",
            "metadata_payload": {"upbit_paid_fee": "0.5"},
            "filled_quantity": 0.5,
            "order_quantity": 1,
        },
    ]
    binding_rows = [
        {"binding_id": 10, "status": "CLOSED", "fees": "1.7"},
        {"binding_id": 11, "status": "CLOSED", "fees": None},
    ]
    session.execute.side_effect = [
        _mapping_result(order_rows),
        _mapping_result(binding_rows),
    ]
    out = fee_truth_summary(session, user_broker_account_id=1380)
    assert out["BUY_FEE_SUPPORTED"] is True
    assert out["SELL_FEE_SUPPORTED"] is True
    assert out["PARTIAL_FILL_FEE_SUPPORTED"] is True
    assert "UPBIT_FEE_SOURCE" in out
    assert "CANONICAL_FEE_SOURCE_OF_TRUTH" in out
    comp = out["FEE_COMPLETENESS"]
    assert comp["buy_with_fee"] == 2  # full + partial buy
    assert comp["sell_missing_fee"] == 1
    assert comp["partial_with_fee"] == 1
    assert comp["bindings_fees_null"] == 1
    assert comp["fee_incomplete"] is True


def test_position_lifecycle_anomaly_classification() -> None:
    session = MagicMock()
    bindings = [
        {
            "binding_id": 1,
            "symbol": "KRW-BTC",
            "status": "OPEN",
            "owned_quantity": 0,
            "realized_pnl": "0",
            "opened_at": "2026-01-01",
            "closed_at": None,
        },
        {
            "binding_id": 2,
            "symbol": "KRW-ETH",
            "status": "CLOSED",
            "owned_quantity": 1.5,
            "realized_pnl": "10",
            "opened_at": "2026-01-01",
            "closed_at": "2026-01-02",
        },
    ]
    slots = [
        {
            "slot_id": 9,
            "symbol": "KRW-XRP",
            "status": "WAITING_SIGNAL",
            "opened_at": "2026-01-01",
            "closed_at": None,
        }
    ]
    session.execute.side_effect = [
        _mapping_result(bindings),
        _mapping_result(slots),
    ]
    out = position_lifecycle_anomalies(session, user_broker_account_id=1380)
    assert out["READ_ONLY"] is True
    assert out["counts"]["OPEN_QTY0"] == 1
    assert out["counts"]["CLOSED_QTY_POSITIVE"] == 1
    assert out["counts"]["WAITING_WITH_OPENED_AT"] == 1
    types = {i["type"] for i in out["items"]}
    assert "OPEN_QTY0" in types
    open0 = next(i for i in out["items"] if i["type"] == "OPEN_QTY0")
    assert open0["classification"] == "LIFECYCLE_DATA_BUG_OR_STALE"


def test_build_risk_decision_snapshot_immutable_shape() -> None:
    snap = build_risk_decision_snapshot(
        allowed=True,
        result="PASS",
        reason_codes=["LIVE_SAFETY_PASS"],
        limits={"daily_entry_limit": 50},
        usage={"daily_entry_used": 3},
    )
    assert snap["schema"] == "risk_decision_snapshot_v1"
    assert snap["allowed"] is True
    assert snap["limits"]["daily_entry_limit"] == 50
    assert "stamped_at" in snap
    # extra는 상위 키를 덮지 않음
    snap2 = build_risk_decision_snapshot(
        allowed=False,
        reason_codes="BLOCKED",
        extra={"allowed": True, "note": "x"},
    )
    assert snap2["allowed"] is False
    assert snap2["note"] == "x"


def test_maybe_stamp_risk_snapshot_buy_only_no_overwrite() -> None:
    snap = build_risk_decision_snapshot(allowed=True, result="PASS")
    meta = maybe_stamp_risk_decision_snapshot({}, snap, side="BUY")
    assert "risk_decision_snapshot" in meta
    first = meta["risk_decision_snapshot"]
    meta2 = maybe_stamp_risk_decision_snapshot(
        meta,
        build_risk_decision_snapshot(allowed=False, result="NO"),
        side="BUY",
    )
    assert meta2["risk_decision_snapshot"] == first
    sell_meta = maybe_stamp_risk_decision_snapshot({}, snap, side="SELL")
    assert "risk_decision_snapshot" not in sell_meta


def test_provenance_unknown_when_missing() -> None:
    session = MagicMock()
    # order exists but empty metadata; no binding; no trace
    session.execute.side_effect = [
        _mapping_result(
            [
                {
                    "order_id": 99,
                    "symbol": "KRW-BTC",
                    "metadata_payload": {},
                    "broker_order_id": None,
                    "client_order_id": None,
                    "user_broker_account_id": 1380,
                }
            ]
        ),
        # trace query may still run — return empty
        _mapping_result([]),
    ]
    out = build_scanner_to_fill_provenance(session, order_id=99)
    assert out["order_id"] == 99
    assert out["scanner_run_id"] == "UNKNOWN"
    assert out["candidate_selection_id"] == "UNKNOWN"
    assert out["execution_trace_id"] == "UNKNOWN"
    assert out["missing_any"] is True


def test_pnl_fee_incomplete_display_logic() -> None:
    complete = pnl_fee_incomplete_from_trades(
        [{"fees": "1.5", "gross_pnl": "10"}, {"fees": "0", "gross_pnl": "0"}]
    )
    assert complete["fee_incomplete"] is False
    incomplete = pnl_fee_incomplete_from_trades(
        [
            {"fees": None, "gross_pnl": "10"},
            {"fees": "0", "gross_pnl": "5"},
        ]
    )
    assert incomplete["fee_incomplete"] is True
    assert incomplete["fee_incomplete_trade_count"] == 2
    assert incomplete["fee_incomplete_display_note_ko"]


def test_uba_truth_layer_reexports_present() -> None:
    from stock_platform.trading import uba_truth_layer as tl

    assert callable(tl.fee_truth_summary)
    assert callable(tl.build_risk_decision_snapshot)
    assert callable(tl.build_scanner_to_fill_provenance)
