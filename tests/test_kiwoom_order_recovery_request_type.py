"""K_ONLY — Kiwoom TradingOrder recovery request_type / client wiring."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from stock_platform.broker.account_models import (
    BrokerAccountSnapshotEntity,
    BrokerPositionSnapshotEntity,
)
from stock_platform.broker.kiwoom.inquiry_client import KiwoomOrderInquiryClient
from stock_platform.broker.kiwoom.inquiry_models import (
    KiwoomExecution,
    KiwoomInquiryPage,
    KiwoomPendingOrder,
)
from stock_platform.broker.kiwoom.recovery import KiwoomOrderRecoveryService
from stock_platform.order.models import OrderStatus


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeSyncRestClient:
    """http_client.KiwoomRestClient 계약 (request_type 필수)."""

    def __init__(
        self,
        *,
        pages: list[tuple[dict[str, Any], dict[str, str]]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.pages = list(pages or [])
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.create_count = 0
        self.cancel_count = 0
        self.amend_count = 0

    def post(
        self,
        *,
        path: str,
        api_id: str,
        body: dict[str, Any],
        request_type: str,
        continuation_key: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        self.calls.append(
            {
                "path": path,
                "api_id": api_id,
                "body": body,
                "request_type": request_type,
                "continuation_key": continuation_key,
            }
        )
        if self.error is not None:
            raise self.error
        if not self.pages:
            return {"return_code": 0, "oso": []}, {"cont-yn": "N"}
        return self.pages.pop(0)


class FakeAsyncAccountRestClient:
    """account sync용 async client.KiwoomRestClient 흉내 (request_type 없음)."""

    async def post(
        self, path: str, api_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return {"return_code": 0}


class FakeInquiryClient:
    """RecoveryService 단위 테스트용 inquiry stub."""

    def __init__(
        self,
        *,
        pages: list[KiwoomInquiryPage] | None = None,
        execution_pages: list[KiwoomInquiryPage] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._pages = list(pages or [])
        self._execution_pages = list(execution_pages or [])
        self._error = error
        self.calls = 0
        self.execution_calls = 0

    def get_pending_orders(
        self,
        *,
        account_number: str,
        continuation_key: str | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> KiwoomInquiryPage:
        self.calls += 1
        if self._error is not None:
            raise self._error
        if not self._pages:
            return KiwoomInquiryPage(items=[], has_next=False, next_key=None)
        return self._pages.pop(0)

    def get_executions(
        self,
        *,
        account_number: str,
        continuation_key: str | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> KiwoomInquiryPage:
        self.execution_calls += 1
        if self._error is not None:
            raise self._error
        if not self._execution_pages:
            return KiwoomInquiryPage(items=[], has_next=False, next_key=None)
        return self._execution_pages.pop(0)


class FakeOrderRepo:
    def __init__(self, orders: dict[str, Any]) -> None:
        self.orders = orders
        self.status_changes: list[tuple[str, str]] = []

    def get_by_broker_order_id(
        self,
        *,
        broker_code: str,
        broker_order_id: str,
        user_broker_account_id: int | None = None,
    ) -> Any:
        return self.orders.get(str(broker_order_id))

    def change_status(
        self,
        *,
        entity: Any,
        new_status: OrderStatus,
        actor: str = "SYSTEM",
        reason_code: str | None = None,
        commit: bool = True,
        **kwargs: Any,
    ) -> Any:
        prev = str(entity.status_code)
        entity.status_code = new_status.value
        self.status_changes.append((prev, new_status.value))
        return entity


class _LedgerSession:
    """LiveFillLedger용 최소 in-memory session (P0-2 테스트와 동일 패턴)."""

    def __init__(self) -> None:
        self.positions: list[BrokerPositionSnapshotEntity] = []
        self.accounts: list[BrokerAccountSnapshotEntity] = []
        self.committed = 0
        self.rolled_back = 0

    def add(self, obj: Any) -> None:
        if isinstance(obj, BrokerPositionSnapshotEntity):
            self.positions.append(obj)
        elif isinstance(obj, BrokerAccountSnapshotEntity):
            self.accounts.append(obj)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def scalar(self, stmt: Any) -> Any:
        text = str(stmt).lower()
        if "broker_account_snapshot" in text or "deposit_amount" in text:
            return self.accounts[0] if self.accounts else None
        if self.positions:
            return self.positions[0]
        return None


def _pending(
    *,
    broker_order_id: str,
    filled: str,
    remaining: str,
    qty: str | None = None,
    price: str = "70000",
    side: str = "BUY",
    symbol: str = "005930",
) -> KiwoomPendingOrder:
    order_qty = Decimal(qty or str(Decimal(filled) + Decimal(remaining)))
    return KiwoomPendingOrder(
        broker_order_id=broker_order_id,
        symbol=symbol,
        side_code=side,
        order_quantity=order_qty,
        filled_quantity=Decimal(filled),
        remaining_quantity=Decimal(remaining),
        order_price=Decimal(price),
        raw_payload={},
    )


def _order(
    *,
    broker_order_id: str = "BO-1",
    status: str = "ACCEPTED",
    filled: str = "0",
    remaining: str = "10",
    side: str = "BUY",
    uba: int = 1381,
    symbol: str = "005930",
) -> SimpleNamespace:
    return SimpleNamespace(
        order_id=101,
        broker_order_id=broker_order_id,
        broker_code="KIWOOM",
        exchange_code="KRX",
        symbol=symbol,
        side_code=side,
        status_code=status,
        filled_quantity=Decimal(filled),
        remaining_quantity=Decimal(remaining),
        average_fill_price=None,
        user_broker_account_id=uba,
        quantity=Decimal(filled) + Decimal(remaining),
    )


def _service(
    inquiry: FakeInquiryClient,
    repo: FakeOrderRepo,
    session: Any | None = None,
) -> KiwoomOrderRecoveryService:
    svc = KiwoomOrderRecoveryService(
        session=session if session is not None else SimpleNamespace(commit=lambda: None),
        inquiry_client=inquiry,  # type: ignore[arg-type]
    )
    svc._repository = repo  # type: ignore[assignment]
    return svc


# ---------------------------------------------------------------------------
# Contract / wiring
# ---------------------------------------------------------------------------


def test_inquiry_rejects_async_account_client_without_request_type():
    with pytest.raises(TypeError, match="request_type"):
        KiwoomOrderInquiryClient(FakeAsyncAccountRestClient())  # type: ignore[arg-type]


def test_inquiry_accepts_sync_http_client_and_passes_request_type():
    rest = FakeSyncRestClient(
        pages=[({"return_code": 0, "oso": []}, {"cont-yn": "N"})]
    )
    client = KiwoomOrderInquiryClient(rest)  # type: ignore[arg-type]
    page = client.get_pending_orders(account_number="12345678")
    assert page.items == []
    assert rest.calls[0]["request_type"] == "INQUIRY"
    assert rest.calls[0]["api_id"] == "ka10075"
    # ka10075 필수 파라미터 기본 포함
    assert rest.calls[0]["body"]["all_stk_tp"] == "0"
    assert rest.calls[0]["body"]["trde_tp"] == "0"
    assert rest.calls[0]["body"]["stex_tp"] == "0"
    assert rest.create_count == 0
    assert rest.cancel_count == 0
    assert rest.amend_count == 0


def test_execution_inquiry_includes_required_body_and_request_type():
    rest = FakeSyncRestClient(
        pages=[
            (
                {
                    "return_code": 0,
                    "cntr": [
                        {
                            "ord_no": "0048830",
                            "stk_cd": "034310",
                            "cntr_qty": "1",
                            "cntr_pric": "12860",
                            "oso_qty": "0",
                            "ord_stt": "체결",
                            "ord_tm": "104834",
                            "io_tp_nm": "-매도",
                        }
                    ],
                },
                {"cont-yn": "N"},
            )
        ]
    )
    client = KiwoomOrderInquiryClient(rest)  # type: ignore[arg-type]
    page = client.get_executions(account_number="12345678")
    assert len(page.items) == 1
    assert page.items[0].broker_order_id == "0048830"
    assert page.items[0].execution_quantity == Decimal("1")
    assert rest.calls[0]["api_id"] == "ka10076"
    assert rest.calls[0]["request_type"] == "INQUIRY"
    assert rest.calls[0]["body"]["qry_tp"] == "0"
    assert rest.calls[0]["body"]["sell_tp"] == "0"
    assert rest.calls[0]["body"]["stex_tp"] == "0"


def test_execution_inquiry_raises_on_nonzero_return_code():
    from stock_platform.broker.kiwoom.inquiry_client import KiwoomInquiryError

    rest = FakeSyncRestClient(
        pages=[
            (
                {
                    "return_code": 1511,
                    "return_msg": "필수입력 파라미터=qry_tp",
                },
                {"cont-yn": "N"},
            )
        ]
    )
    client = KiwoomOrderInquiryClient(rest)  # type: ignore[arg-type]
    with pytest.raises(KiwoomInquiryError):
        client.get_executions(account_number="x")


def test_wrong_wiring_would_raise_on_post_without_guard():
    """가드 없는 구형 오주입 시 TypeError(request_type) 재현."""

    class LegacyInquiry:
        def __init__(self, rest_client: Any) -> None:
            self._rest_client = rest_client

        def get_pending_orders(self, *, account_number: str, **kwargs: Any):
            return self._rest_client.post(
                path="/api/dostk/acnt",
                api_id="ka10075",
                body={"account_no": account_number},
                request_type="INQUIRY",
            )

    async_client = FakeAsyncAccountRestClient()
    with pytest.raises(TypeError, match="request_type"):
        LegacyInquiry(async_client).get_pending_orders(account_number="x")


# ---------------------------------------------------------------------------
# Recovery A–H
# ---------------------------------------------------------------------------


def test_a_pending_zero_completes_without_typeerror():
    inquiry = FakeInquiryClient(
        pages=[KiwoomInquiryPage(items=[], has_next=False, next_key=None)]
    )
    repo = FakeOrderRepo({})
    summary = _service(inquiry, repo).recover_pending_orders(account_number="****4145")
    assert summary.inspected_pending == 0
    assert summary.matched_orders == 0
    assert summary.missing_local_orders == 0
    assert inquiry.calls == 1


def test_b_pending_order_inquiry_success():
    rest = FakeSyncRestClient(
        pages=[
            (
                {
                    "return_code": 0,
                    "oso": [
                        {
                            "ord_no": "BO-9",
                            "stk_cd": "005930",
                            "ord_qty": "10",
                            "cntr_qty": "0",
                            "oso_qty": "10",
                            "ord_uv": "70000",
                            "io_tp_nm": "BUY",
                        }
                    ],
                },
                {"cont-yn": "N"},
            )
        ]
    )
    page = KiwoomOrderInquiryClient(rest).get_pending_orders(  # type: ignore[arg-type]
        account_number="12345678"
    )
    assert len(page.items) == 1
    assert page.items[0].broker_order_id == "BO-9"
    assert rest.calls[0]["request_type"] == "INQUIRY"


def test_c_matched_order_status_reconciliation():
    session = _LedgerSession()
    order = _order(filled="0", remaining="10", status="ACCEPTED")
    inquiry = FakeInquiryClient(
        pages=[
            KiwoomInquiryPage(
                items=[_pending(broker_order_id="BO-1", filled="3", remaining="7")],
                has_next=False,
                next_key=None,
            )
        ]
    )
    repo = FakeOrderRepo({"BO-1": order})
    summary = _service(inquiry, repo, session=session).recover_pending_orders(
        account_number="x"
    )
    assert summary.matched_orders == 1
    assert order.status_code == OrderStatus.PARTIALLY_FILLED.value
    assert order.filled_quantity == Decimal("3")
    assert ("ACCEPTED", "PARTIALLY_FILLED") in repo.status_changes


def test_d_partial_fill_recovery():
    session = _LedgerSession()
    order = _order(filled="0", remaining="10", status="ACCEPTED")
    inquiry = FakeInquiryClient(
        pages=[
            KiwoomInquiryPage(
                items=[_pending(broker_order_id="BO-1", filled="4", remaining="6")],
                has_next=False,
                next_key=None,
            )
        ]
    )
    summary = _service(
        inquiry, FakeOrderRepo({"BO-1": order}), session=session
    ).recover_pending_orders(account_number="x")
    assert summary.matched_orders == 1
    assert order.filled_quantity == Decimal("4")
    assert order.remaining_quantity == Decimal("6")
    assert order.status_code == OrderStatus.PARTIALLY_FILLED.value


def test_e_full_fill_transitions_to_filled():
    session = _LedgerSession()
    order = _order(filled="0", remaining="10", status="ACCEPTED")
    inquiry = FakeInquiryClient(
        pages=[
            KiwoomInquiryPage(
                items=[_pending(broker_order_id="BO-1", filled="10", remaining="0")],
                has_next=False,
                next_key=None,
            )
        ]
    )
    summary = _service(
        inquiry, FakeOrderRepo({"BO-1": order}), session=session
    ).recover_pending_orders(account_number="x")
    assert summary.matched_orders == 1
    assert order.status_code == OrderStatus.FILLED.value
    assert order.remaining_quantity == Decimal("0")


def test_g_remote_only_does_not_create_trading_order():
    inquiry = FakeInquiryClient(
        pages=[
            KiwoomInquiryPage(
                items=[_pending(broker_order_id="REMOTE-ONLY", filled="1", remaining="0")],
                has_next=False,
                next_key=None,
            )
        ]
    )
    repo = FakeOrderRepo({})
    summary = _service(inquiry, repo).recover_pending_orders(account_number="x")
    assert summary.missing_local_orders == 1
    assert summary.matched_orders == 0
    assert repo.orders == {}


def test_h_api_error_propagates_fail_closed():
    inquiry = FakeInquiryClient(error=RuntimeError("broker_inquiry_failed"))
    with pytest.raises(RuntimeError, match="broker_inquiry_failed"):
        _service(inquiry, FakeOrderRepo({})).recover_pending_orders(account_number="x")


# ---------------------------------------------------------------------------
# P0-2 via recovery path
# ---------------------------------------------------------------------------


def test_f_and_p0_2_duplicate_fill_idempotent_and_buy_position():
    session = _LedgerSession()
    order = _order(filled="0", remaining="10", status="ACCEPTED", side="BUY")
    pending = _pending(broker_order_id="BO-1", filled="10", remaining="0", side="BUY")
    inquiry = FakeInquiryClient(
        pages=[
            KiwoomInquiryPage(items=[pending], has_next=False, next_key=None),
            KiwoomInquiryPage(items=[pending], has_next=False, next_key=None),
        ]
    )
    repo = FakeOrderRepo({"BO-1": order})
    svc = _service(inquiry, repo, session=session)

    first = svc.recover_pending_orders(account_number="x")
    assert first.position_writes >= 1
    assert len(session.positions) == 1
    assert Decimal(session.positions[0].quantity) == Decimal("10")
    assert Decimal(session.positions[0].average_purchase_price) == Decimal("70000")

    # 동일 fill 재적용 — local_filled 이미 10 → delta 0 → position_writes 0
    order.filled_quantity = Decimal("10")
    order.status_code = OrderStatus.FILLED.value
    second = svc.recover_pending_orders(account_number="x")
    assert second.position_writes == 0
    assert Decimal(session.positions[0].quantity) == Decimal("10")


def test_p0_2_partial_sell_decreases_qty():
    session = _LedgerSession()
    session.positions.append(
        BrokerPositionSnapshotEntity(
            broker_code="KIWOOM",
            account_number="UBA:1381",
            user_broker_account_id=1381,
            exchange_code="KRX",
            symbol="005930",
            name=None,
            quantity=Decimal("10"),
            available_quantity=Decimal("10"),
            average_purchase_price=Decimal("70000"),
            current_price=Decimal("70000"),
            purchase_amount=Decimal("700000"),
            evaluation_amount=Decimal("700000"),
            profit_loss=Decimal("0"),
            return_rate=Decimal("0"),
            raw_data={},
            synchronized_at=datetime.now(timezone.utc),
            snapshot_status="ACTIVE",
        )
    )
    order = _order(
        filled="0",
        remaining="4",
        status="ACCEPTED",
        side="SELL",
    )
    inquiry = FakeInquiryClient(
        pages=[
            KiwoomInquiryPage(
                items=[
                    _pending(
                        broker_order_id="BO-1",
                        filled="4",
                        remaining="0",
                        side="SELL",
                    )
                ],
                has_next=False,
                next_key=None,
            )
        ]
    )
    summary = _service(
        inquiry, FakeOrderRepo({"BO-1": order}), session=session
    ).recover_pending_orders(account_number="x")
    assert summary.position_writes >= 1
    assert Decimal(session.positions[0].quantity) == Decimal("6")


def test_p0_2_full_sell_closes_or_zeroes_position():
    session = _LedgerSession()
    session.positions.append(
        BrokerPositionSnapshotEntity(
            broker_code="KIWOOM",
            account_number="UBA:1381",
            user_broker_account_id=1381,
            exchange_code="KRX",
            symbol="005930",
            name=None,
            quantity=Decimal("5"),
            available_quantity=Decimal("5"),
            average_purchase_price=Decimal("70000"),
            current_price=Decimal("70000"),
            purchase_amount=Decimal("350000"),
            evaluation_amount=Decimal("350000"),
            profit_loss=Decimal("0"),
            return_rate=Decimal("0"),
            raw_data={},
            synchronized_at=datetime.now(timezone.utc),
            snapshot_status="ACTIVE",
        )
    )
    order = _order(filled="0", remaining="5", status="ACCEPTED", side="SELL")
    inquiry = FakeInquiryClient(
        pages=[
            KiwoomInquiryPage(
                items=[
                    _pending(
                        broker_order_id="BO-1",
                        filled="5",
                        remaining="0",
                        side="SELL",
                    )
                ],
                has_next=False,
                next_key=None,
            )
        ]
    )
    summary = _service(
        inquiry, FakeOrderRepo({"BO-1": order}), session=session
    ).recover_pending_orders(account_number="x")
    assert summary.position_writes >= 1
    qty = Decimal(session.positions[0].quantity)
    assert qty == Decimal("0") or str(
        getattr(session.positions[0], "snapshot_status", "")
    ).upper() in {"CLOSED", "RETIRED", "INACTIVE"}


def test_broker_mutation_counters_remain_zero_on_inquiry_path():
    rest = FakeSyncRestClient(
        pages=[({"return_code": 0, "oso": []}, {"cont-yn": "N"})]
    )
    KiwoomOrderInquiryClient(rest).get_pending_orders(account_number="x")  # type: ignore[arg-type]
    assert rest.create_count == 0
    assert rest.cancel_count == 0
    assert rest.amend_count == 0
    assert all(c["request_type"] == "INQUIRY" for c in rest.calls)


# ---------------------------------------------------------------------------
# ka10076 open-order fill recovery (pending 이탈 후 ACCEPTED 정합)
# ---------------------------------------------------------------------------


def _execution(
    *,
    broker_order_id: str = "0048830",
    qty: str = "1",
    price: str = "12860",
    remaining: str = "0",
    symbol: str = "034310",
) -> KiwoomExecution:
    return KiwoomExecution(
        broker_order_id=broker_order_id,
        symbol=symbol,
        execution_number=None,
        execution_quantity=Decimal(qty),
        execution_price=Decimal(price),
        raw_payload={
            "ord_no": broker_order_id,
            "stk_cd": symbol,
            "cntr_qty": qty,
            "cntr_pric": price,
            "oso_qty": remaining,
            "ord_stt": "체결",
            "ord_tm": "104834",
            "io_tp_nm": "-매도",
        },
    )


def test_recover_open_orders_from_executions_full_sell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from stock_platform.trading.execution_sync_service import (
        ExecutionSyncResult,
    )

    order = _order(
        broker_order_id="0048830",
        filled="0",
        remaining="1",
        status="ACCEPTED",
        side="SELL",
        symbol="034310",
    )
    session = SimpleNamespace(commit=lambda: None, refresh=lambda *_: None)
    inquiry = FakeInquiryClient(
        execution_pages=[
            KiwoomInquiryPage(
                items=[_execution()],
                has_next=False,
                next_key=None,
            )
        ]
    )
    svc = _service(inquiry, FakeOrderRepo({"0048830": order}), session=session)

    sync_calls: list[Any] = []

    class _FakeSync:
        def __init__(self, _session: Any) -> None:
            pass

        def synchronize(self, event: Any, *, actor: str = "") -> ExecutionSyncResult:
            sync_calls.append(event)
            order.filled_quantity = Decimal(str(order.filled_quantity or 0)) + event.execution_quantity
            order.remaining_quantity = Decimal("0")
            order.status_code = OrderStatus.FILLED.value
            order.average_fill_price = event.execution_price
            return ExecutionSyncResult(
                duplicate=False,
                order_found=True,
                execution_id=9001,
                order_status=OrderStatus.FILLED.value,
            )

    monkeypatch.setattr(
        "stock_platform.broker.kiwoom.recovery.ExecutionSyncService",
        _FakeSync,
    )
    monkeypatch.setattr(
        "stock_platform.broker.kiwoom.recovery.ensure_kiwoom_position_after_sync",
        lambda *a, **k: {"applied": True},
    )
    monkeypatch.setattr(
        svc,
        "_list_open_kiwoom_orders",
        lambda **kwargs: [order],
    )

    first = svc.recover_open_orders_from_executions(account_number="x")
    assert first.reconciled_from_executions == 1
    assert first.new_executions == 1
    assert len(sync_calls) == 1
    assert sync_calls[0].execution_quantity == Decimal("1")
    assert order.status_code == OrderStatus.FILLED.value

    # 2회차: delta=0 → duplicate/no new execution
    inquiry2 = FakeInquiryClient(
        execution_pages=[
            KiwoomInquiryPage(items=[_execution()], has_next=False, next_key=None)
        ]
    )
    svc2 = _service(inquiry2, FakeOrderRepo({"0048830": order}), session=session)
    monkeypatch.setattr(svc2, "_list_open_kiwoom_orders", lambda **kwargs: [order])
    monkeypatch.setattr(
        "stock_platform.broker.kiwoom.recovery.ExecutionSyncService",
        _FakeSync,
    )
    second = svc2.recover_open_orders_from_executions(account_number="x")
    assert second.new_executions == 0
    # ledger retry는 reconciled=True 가능, 신규 Execution은 없어야 함
    assert order.status_code == OrderStatus.FILLED.value


def test_norm_broker_order_id_strips_leading_zeros() -> None:
    from stock_platform.broker.kiwoom.recovery import _norm_broker_order_id

    assert _norm_broker_order_id("0048830") == _norm_broker_order_id("48830")
    assert _norm_broker_order_id("0") == "0"
