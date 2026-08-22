"""공통 MANUAL/AUTO open-order isolation — unit only."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.order.live_open_order_exposure import (
    LocalOpenOrder,
    RemoteOpenOrderRef,
    RemoteOpenOrderView,
    STATE_FRESH,
    STATE_UNKNOWN,
    combine_open_order_exposure,
    evaluate_live_open_order_exposure,
)
from stock_platform.order.order_ownership import (
    ORDER_OWNERSHIP_UNKNOWN,
    classify_local_open_order,
    is_local_auto_provenance,
)
from stock_platform.trading.symbol_ownership.constants import (
    OWNER_AUTO,
    OWNER_MANUAL,
)


def _fresh(*uuids: str, market: str | None = None) -> RemoteOpenOrderView:
    orders = tuple(
        RemoteOpenOrderRef(
            uuid=u.lower(), identifier=None, market=market
        )
        for u in uuids
    )
    return RemoteOpenOrderView(status=STATE_FRESH, orders=orders, source="TEST")


def test_a_upbit_manual_remote_3_auto_0_pass_gate() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    out = evaluate_live_open_order_exposure(
        session,
        uba_id=1380,
        broker_code="UPBIT",
        remote_view=_fresh("u1", "u2", "u3"),
    )
    assert out.manual_open_count == 3
    assert out.auto_open_count == 0
    assert out.unknown_open_count == 0
    assert out.total_open_count == 3
    assert out.canonical_count == 0  # AUTO risk count
    assert out.auto_open_count < 1


def test_b_upbit_local_auto_1_blocks() -> None:
    session = MagicMock()
    session.scalars.return_value = [
        SimpleNamespace(
            order_id=10,
            broker_order_id="auto-uuid",
            client_order_id="c1",
            client_order_identifier=None,
            symbol="KRW-PEPE",
            strategy_id=17483,
            strategy_deployment_id=868,
            metadata_payload={"order_source": "AUTO"},
            broker_code="UPBIT",
        )
    ]
    out = evaluate_live_open_order_exposure(
        session,
        uba_id=1380,
        broker_code="UPBIT",
        remote_view=_fresh(),
    )
    assert out.auto_open_count == 1
    assert out.manual_open_count == 0
    assert out.auto_open_count >= 1


def test_c_kiwoom_manual_pending_excluded_from_auto() -> None:
    session = MagicMock()
    # local empty
    session.scalars.side_effect = [
        [],  # load_local_open_orders
        [  # pending
            SimpleNamespace(
                broker_order_id="K-1",
                order_no=None,
                symbol="005930",
            ),
            SimpleNamespace(
                broker_order_id="K-2",
                order_no=None,
                symbol="000660",
            ),
            SimpleNamespace(
                broker_order_id="K-3",
                order_no=None,
                symbol="035420",
            ),
        ],
    ]
    # pending local match lookup → none
    session.scalar.return_value = None
    out = evaluate_live_open_order_exposure(
        session,
        uba_id=1381,
        broker_code="KIWOOM",
        environment="LIVE",
    )
    assert out.manual_open_count == 3
    assert out.auto_open_count == 0
    assert out.auto_open_count < 1


def test_d_kiwoom_local_auto_blocks() -> None:
    session = MagicMock()
    session.scalars.side_effect = [
        [
            SimpleNamespace(
                order_id=99,
                broker_order_id="ko-1",
                client_order_id="c",
                client_order_identifier=None,
                symbol="005930",
                strategy_id=1,
                strategy_deployment_id=2,
                metadata_payload={},
                broker_code="KIWOOM",
            )
        ],
        [],  # no pending
    ]
    out = evaluate_live_open_order_exposure(
        session,
        uba_id=1381,
        broker_code="KIWOOM",
    )
    assert out.auto_open_count == 1
    assert out.manual_open_count == 0


def test_e_mixed_manual_remote_and_local_auto() -> None:
    local = [
        LocalOpenOrder(
            order_id=1,
            broker_order_id="auto-1",
            client_order_id=None,
            client_order_identifier=None,
            symbol="KRW-PEPE",
            strategy_id=1,
            owner=OWNER_AUTO,
        )
    ]
    out = combine_open_order_exposure(
        local_orders=local,
        remote_view=_fresh("m1", "m2", "m3"),
        source="TEST",
        broker="UPBIT",
        uba_id=1380,
    )
    assert out.auto_open_count == 1
    assert out.manual_open_count == 3
    assert out.total_open_count == 4


def test_f_unknown_remote_fail_closed_reason() -> None:
    session = MagicMock()
    session.scalars.return_value = []
    out = evaluate_live_open_order_exposure(
        session,
        uba_id=1380,
        broker_code="UPBIT",
        remote_view=RemoteOpenOrderView(
            status=STATE_UNKNOWN, source="TEST"
        ),
    )
    assert out.remote_state_ok is False
    assert out.reason_code == "REMOTE_OPEN_CHECK_FAILED"


def test_g_manual_btc_does_not_count_for_auto_pepe() -> None:
    """account-wide: MANUAL BTC remote 가 AUTO PEPE gate 를 막지 않음."""

    session = MagicMock()
    session.scalars.return_value = []
    out = evaluate_live_open_order_exposure(
        session,
        uba_id=1380,
        broker_code="UPBIT",
        remote_view=_fresh("btc-1", market="KRW-BTC"),
    )
    assert out.manual_open_count == 1
    assert out.auto_open_count == 0


def test_h_same_uuid_local_auto_dedupe() -> None:
    uid = "90db6b4d-d837-45be-834f-0c5fbfbef5e6"
    local = [
        LocalOpenOrder(
            order_id=1,
            broker_order_id=uid,
            client_order_id="cid",
            client_order_identifier=None,
            strategy_id=9,
            owner=OWNER_AUTO,
        )
    ]
    out = combine_open_order_exposure(
        local_orders=local,
        remote_view=_fresh(uid),
        source="TEST",
        broker="UPBIT",
        uba_id=1,
    )
    assert out.mapped_remote_count == 1
    assert out.remote_unmapped_count == 0
    assert out.auto_open_count == 1
    assert out.manual_open_count == 0


def test_i_local_auto_provenance_restart_safe() -> None:
    assert is_local_auto_provenance(strategy_id=17483) is True
    assert is_local_auto_provenance(strategy_id=None) is False
    d = classify_local_open_order(
        broker="UPBIT",
        uba_id=1380,
        symbol="KRW-GEOD",
        local_order_id=1,
        broker_order_id="x",
        strategy_id=17483,
        strategy_deployment_id=868,
    )
    assert d.owner == OWNER_AUTO


def test_j_manual_local_no_strategy() -> None:
    d = classify_local_open_order(
        broker="KIWOOM",
        uba_id=1381,
        symbol="005930",
        local_order_id=2,
        broker_order_id="y",
        strategy_id=None,
    )
    assert d.owner == OWNER_MANUAL


def test_k_order_ownership_unknown_constant() -> None:
    assert ORDER_OWNERSHIP_UNKNOWN == "ORDER_OWNERSHIP_UNKNOWN"
