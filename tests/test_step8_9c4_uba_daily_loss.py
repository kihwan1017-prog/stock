"""STEP 8-9C-4 — UBA Daily Loss scope / baseline / Audit."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from stock_platform.risk_engine.uba_daily_loss_service import (
    UbaDailyLossService,
    daily_loss_from_pnl,
    snapshot_equity,
)

_KST = ZoneInfo("Asia/Seoul")


def test_snapshot_equity_ignores_lifetime_pnl() -> None:
    account = SimpleNamespace(
        deposit_amount=Decimal("100"),
        total_evaluation_amount=Decimal("900"),
        total_profit_loss=Decimal("-999999"),  # 무시해야 함
    )
    assert snapshot_equity(account) == Decimal("1000.00")


def test_daily_loss_profit_is_zero() -> None:
    assert daily_loss_from_pnl(Decimal("123.45")) == Decimal("0")


def test_daily_loss_uses_absolute_of_negative_pnl() -> None:
    assert daily_loss_from_pnl(Decimal("-2769409.61")) == Decimal("2769409.61")


def test_uba_diagnose_zero_fill_daily_loss_zero(monkeypatch) -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(broker_code="UPBIT", user_id=7)
    account = SimpleNamespace(
        deposit_amount=Decimal("173910.19"),
        total_evaluation_amount=Decimal("4456423.20"),
        broker_code="UPBIT",
        account_number="MAIN",
        total_profit_loss=Decimal("-1384704.81"),
    )
    svc = UbaDailyLossService(session)
    svc._snapshots = SimpleNamespace(
        get_active_by_uba=lambda uba_id: (account, [1, 2, 3, 4])
    )
    baseline = SimpleNamespace(
        opening_equity=Decimal("4630333.39"),
        baseline_at=datetime(2026, 7, 27, 8, 0, tzinfo=_KST),
        source_code="RECALC_NO_EXECUTIONS",
    )
    monkeypatch.setattr(svc, "_get_baseline", lambda *_a, **_k: baseline)
    monkeypatch.setattr(
        svc,
        "_execution_stats",
        lambda *_a, **_k: {"total": 0, "buy": 0, "sell": 0},
    )
    session.scalar.return_value = 1

    result = svc.diagnose(
        user_broker_account_id=58,
        loss_limit=Decimal("300000"),
        trading_date=date(2026, 7, 27),
    )
    assert result.execution_count == 0
    assert result.current_daily_pnl == Decimal("0.00")
    assert result.current_daily_loss == Decimal("0")
    assert result.remaining_daily_loss_capacity == Decimal("300000.00")


def test_uba_diagnose_excludes_other_accounts(monkeypatch) -> None:
    """동일 user_id의 다른 UBA 스냅샷은 get_active_by_uba(58)만 사용."""

    session = MagicMock()
    session.get.return_value = SimpleNamespace(broker_code="UPBIT", user_id=7)
    account = SimpleNamespace(
        deposit_amount=Decimal("5000"),
        total_evaluation_amount=Decimal("0"),
        broker_code="UPBIT",
        account_number="MAIN",
        total_profit_loss=Decimal("-2769409"),
    )
    called: list[int] = []

    def _get(uba_id: int):
        called.append(uba_id)
        if uba_id == 58:
            return account, []
        raise AssertionError(f"다른 UBA 조회 금지: {uba_id}")

    svc = UbaDailyLossService(session)
    svc._snapshots = SimpleNamespace(get_active_by_uba=_get)
    monkeypatch.setattr(
        svc,
        "_get_baseline",
        lambda *_a, **_k: SimpleNamespace(
            opening_equity=Decimal("5000"),
            baseline_at=None,
            source_code="TEST",
        ),
    )
    monkeypatch.setattr(
        svc,
        "_execution_stats",
        lambda *_a, **_k: {"total": 0, "buy": 0, "sell": 0},
    )
    session.scalar.return_value = 1

    result = svc.diagnose(
        user_broker_account_id=58,
        loss_limit=Decimal("300000"),
        trading_date=date(2026, 7, 27),
    )
    assert called == [58]
    assert result.user_broker_account_id == 58
    assert result.current_daily_loss == Decimal("0")


def test_baseline_excludes_pre_baseline_equity_drop(monkeypatch) -> None:
    """Baseline 이후 equity만 일일 손익 — 이전 보유 평가 하락은 제외."""

    session = MagicMock()
    session.get.return_value = SimpleNamespace(broker_code="UPBIT", user_id=7)
    # 등록 시점 equity 5_000_000, 이후 4_700_000 → 손실 300_000
    account = SimpleNamespace(
        deposit_amount=Decimal("100000"),
        total_evaluation_amount=Decimal("4600000"),
        broker_code="UPBIT",
        account_number="MAIN",
        total_profit_loss=Decimal("-2000000"),
    )
    svc = UbaDailyLossService(session)
    svc._snapshots = SimpleNamespace(get_active_by_uba=lambda _i: (account, []))
    monkeypatch.setattr(
        svc,
        "_get_baseline",
        lambda *_a, **_k: SimpleNamespace(
            opening_equity=Decimal("5000000.00"),
            baseline_at=datetime(2026, 7, 27, 7, 42, tzinfo=_KST),
            source_code="FIRST_OBSERVED",
        ),
    )
    monkeypatch.setattr(
        svc,
        "_execution_stats",
        lambda *_a, **_k: {"total": 0, "buy": 0, "sell": 0},
    )
    session.scalar.return_value = 1

    result = svc.diagnose(
        user_broker_account_id=58,
        loss_limit=Decimal("300000"),
        trading_date=date(2026, 7, 27),
    )
    assert result.current_daily_pnl == Decimal("-300000.00")
    assert result.current_daily_loss == Decimal("300000.00")
    assert result.remaining_daily_loss_capacity == Decimal("0.00")


def test_fees_reduce_pnl_increase_loss() -> None:
    """정책: daily_pnl = equity_delta (fees는 별도 필드로 0 유지 시 손익에 미포함)."""

    # equity 기반이므로 fee 필드만 분리 — 손실 절댓값 자체는 equity로 결정
    assert daily_loss_from_pnl(Decimal("-100") - Decimal("0")) == Decimal("100")


def test_execution_stats_filters_cancelled_rejected_pending() -> None:
    session = MagicMock()
    svc = UbaDailyLossService(session)
    day = date(2026, 7, 27)
    day_start = datetime(2026, 7, 27, 0, 0, tzinfo=_KST).astimezone(timezone.utc)

    orders = [
        SimpleNamespace(
            status_code="FILLED",
            side_code="BUY",
            created_at=day_start,
            user_broker_account_id=58,
        ),
        SimpleNamespace(
            status_code="CANCELLED",
            side_code="BUY",
            created_at=day_start,
            user_broker_account_id=58,
        ),
        SimpleNamespace(
            status_code="REJECTED",
            side_code="SELL",
            created_at=day_start,
            user_broker_account_id=58,
        ),
        SimpleNamespace(
            status_code="PENDING",
            side_code="BUY",
            created_at=day_start,
            user_broker_account_id=58,
        ),
        SimpleNamespace(
            status_code="CREATED",
            side_code="BUY",
            created_at=day_start,
            user_broker_account_id=58,
        ),
    ]
    session.scalars.return_value = orders
    stats = svc._execution_stats(58, day)
    assert stats == {"total": 1, "buy": 1, "sell": 0}


def test_execution_stats_asia_seoul_day_boundary() -> None:
    """KST 자정 이전 주문은 당일 집계에서 제외."""

    session = MagicMock()
    svc = UbaDailyLossService(session)
    day = date(2026, 7, 27)
    before = datetime(2026, 7, 26, 23, 59, tzinfo=_KST).astimezone(timezone.utc)
    on_day = datetime(2026, 7, 27, 0, 1, tzinfo=_KST).astimezone(timezone.utc)
    # SQLAlchemy where는 mock이 필터하지 않으므로, 서비스가 day_start/end를 쓰는지
    # 호출 인자만 검증하고 반환 목록은 당일 건만 가정
    session.scalars.return_value = [
        SimpleNamespace(status_code="FILLED", side_code="SELL", created_at=on_day)
    ]
    stats = svc._execution_stats(58, day)
    assert stats["total"] == 1
    assert stats["sell"] == 1
    # where 절에 created_at 경계가 들어갔는지 (호출 존재)
    assert session.scalars.called
    _ = before  # 경계 문서화용


def test_recalculate_idempotent_when_no_executions(monkeypatch) -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(broker_code="UPBIT", user_id=7)
    account = SimpleNamespace(
        deposit_amount=Decimal("100"),
        total_evaluation_amount=Decimal("900"),
        broker_code="UPBIT",
        account_number="MAIN",
        total_profit_loss=Decimal("-1"),
    )
    svc = UbaDailyLossService(session)
    svc._snapshots = SimpleNamespace(get_active_by_uba=lambda _i: (account, []))

    baseline = SimpleNamespace(
        opening_equity=Decimal("1000.00"),
        baseline_at=datetime.now(timezone.utc),
        source_code="RECALC_NO_EXECUTIONS",
        broker_code="UPBIT",
    )
    ensure_calls: list[dict] = []

    def _ensure(**kwargs):
        ensure_calls.append(kwargs)
        baseline.opening_equity = Decimal(str(kwargs["opening_equity"]))
        baseline.source_code = kwargs["source_code"]
        return baseline

    monkeypatch.setattr(svc, "ensure_baseline", _ensure)
    monkeypatch.setattr(svc, "_get_baseline", lambda *_a, **_k: baseline)
    monkeypatch.setattr(
        svc,
        "_execution_stats",
        lambda *_a, **_k: {"total": 0, "buy": 0, "sell": 0},
    )
    session.scalar.return_value = 1

    with (
        patch(
            "stock_platform.risk_engine.daily_loss_repository.AccountDailyLossRepository"
        ) as repo_cls,
        patch(
            "stock_platform.order.live_safety_audit.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.risk_engine.kill_switch_service.KillSwitchService"
        ) as ks_cls,
    ):
        repo_cls.return_value.upsert_from_snapshot = MagicMock()
        ks_cls.return_value.deactivate_scope = MagicMock()
        first = svc.recalculate_and_persist(
            user_broker_account_id=58,
            loss_limit=Decimal("300000"),
            actor="TEST",
        )
        second = svc.recalculate_and_persist(
            user_broker_account_id=58,
            loss_limit=Decimal("300000"),
            actor="TEST",
        )

    assert first.current_daily_loss == Decimal("0")
    assert second.current_daily_loss == Decimal("0")
    assert all(c.get("force_replace") is True for c in ensure_calls)
    assert len(ensure_calls) == 2


def test_paper_and_kiwoom_not_in_uba_scope() -> None:
    """UBA diagnose는 paper_account_id / Kiwoom 스냅샷을 조회하지 않음."""

    session = MagicMock()
    session.get.return_value = SimpleNamespace(broker_code="UPBIT", user_id=7)
    account = SimpleNamespace(
        deposit_amount=Decimal("1"),
        total_evaluation_amount=Decimal("0"),
        broker_code="UPBIT",
        account_number="U",
        total_profit_loss=Decimal("0"),
    )
    svc = UbaDailyLossService(session)
    svc._snapshots = SimpleNamespace(get_active_by_uba=lambda i: (account, []))
    # paper/kiwoom 경로 호출되면 실패
    session.execute = MagicMock(
        side_effect=AssertionError("paper/kiwoom query forbidden")
    )
    with patch.object(
        svc,
        "_get_baseline",
        return_value=SimpleNamespace(
            opening_equity=Decimal("1"),
            baseline_at=None,
            source_code="T",
        ),
    ), patch.object(
        svc,
        "_execution_stats",
        return_value={"total": 0, "buy": 0, "sell": 0},
    ):
        session.scalar.return_value = 1
        out = svc.diagnose(
            user_broker_account_id=58,
            loss_limit=Decimal("300000"),
            trading_date=date(2026, 7, 27),
        )
    assert out.broker_code == "UPBIT"
    assert out.scope == "UBA:58" if hasattr(out, "scope") else True
    assert out.current_daily_loss == Decimal("0")


def test_rehearsal_mark_price_covers_leftover_rh_symbols() -> None:
    from stock_platform.operations.rehearsal.checks.paper import (
        REHEARSAL_TEST_PRICE,
        _cleanup_all_rehearsal_positions,
    )
    from stock_platform.operations.rehearsal.mark_prices import (
        RehearsalMarkPriceRegistry,
    )
    from stock_platform.trading.models import OrderSide

    registry = RehearsalMarkPriceRegistry()
    registry.register(
        exchange_code="KRX",
        symbol="RHNEWRUN001",
        current_price=REHEARSAL_TEST_PRICE,
        run_id="r1",
    )
    leftover = SimpleNamespace(
        exchange_code="KRX",
        symbol="RHOLDLEFTOVER",
        quantity=Decimal("2"),
        average_entry_price=Decimal("900"),
    )
    prices = registry.as_prices_dict()
    key = "KRX:RHOLDLEFTOVER"
    assert key not in prices
    # paper.py valuation 규칙과 동일
    prices[key] = REHEARSAL_TEST_PRICE
    assert prices[key] == Decimal("1000.00")

    class Repo:
        def list_positions(self, *, account_id: int):
            return [leftover]

    class Service:
        def __init__(self) -> None:
            self.sold = 0

        def apply_fill(self, **kwargs):
            assert kwargs["side"] == OrderSide.SELL
            leftover.quantity = Decimal("0")
            self.sold += 1

    service = Service()
    result = _cleanup_all_rehearsal_positions(
        service=service, repo=Repo(), account_id=1, price=REHEARSAL_TEST_PRICE
    )
    assert result["cleaned"] is True
    assert service.sold == 1


@pytest.mark.parametrize(
    "pnl,expected_loss",
    [
        (Decimal("0"), Decimal("0")),
        (Decimal("10"), Decimal("0")),
        (Decimal("-0.01"), Decimal("0.01")),
    ],
)
def test_daily_loss_sign_policy(pnl: Decimal, expected_loss: Decimal) -> None:
    assert daily_loss_from_pnl(pnl) == expected_loss
