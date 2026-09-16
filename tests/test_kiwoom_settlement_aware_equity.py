"""Kiwoom settlement-aware Daily Loss equity — focused tests."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from stock_platform.broker.kiwoom.account_mapper import KiwoomAccountMapper
from stock_platform.broker.kiwoom.equity_policy import (
    KIWOOM_EQUITY_V1_IMMEDIATE_CASH,
    KIWOOM_EQUITY_V2_SETTLEMENT_AWARE,
    SOURCE_D2_PLUS_STOCK,
    SOURCE_ESTIMATED_ASSET,
    SOURCE_IMMEDIATE_PLUS_STOCK,
    compute_kiwoom_equity_for_risk,
    resolve_kiwoom_policy_for_baseline,
)
from stock_platform.risk_engine.uba_daily_loss_service import (
    daily_loss_from_pnl,
    snapshot_equity,
)


def _kiwoom_account(
    *,
    entr: str,
    tot_evlt: str,
    d1: str | None = None,
    d2: str | None = None,
    prsm: str | None = None,
    d1_sel: str | None = None,
) -> SimpleNamespace:
    deposit: dict = {"entr": entr}
    if d1 is not None:
        deposit["d1_entra"] = d1
    if d2 is not None:
        deposit["d2_entra"] = d2
    if prsm is not None:
        deposit["prsm_dpst_aset_amt"] = prsm
    if d1_sel is not None:
        deposit["d1_sel_exct_amt"] = d1_sel
    return SimpleNamespace(
        broker_code="KIWOOM",
        deposit_amount=Decimal(entr),
        total_evaluation_amount=Decimal(tot_evlt),
        total_profit_loss=Decimal("-999999"),
        raw_data={"deposit": deposit, "balance": {"tot_evlt_amt": tot_evlt}},
    )


def test_no_settlement_pending_uses_estimated_or_cash_plus_stock() -> None:
    account = _kiwoom_account(
        entr="1000000",
        tot_evlt="4000000",
        d1="1000000",
        d2="1000000",
        prsm="5000000",
    )
    result = compute_kiwoom_equity_for_risk(
        account, policy_version=KIWOOM_EQUITY_V2_SETTLEMENT_AWARE
    )
    assert result.pending_settlement_cash == Decimal("0.00")
    assert result.equity_for_risk == Decimal("5000000.00")
    assert result.equity_source == SOURCE_ESTIMATED_ASSET


def test_sell_settlement_pending_removes_false_loss() -> None:
    # entr에 아직 안 들어온 매도대금이 d2에만 있는 경우
    account = _kiwoom_account(
        entr="164342",
        tot_evlt="4707617",
        d1="435768",
        d2="435768",
        prsm="5133337",
        d1_sel="271426",
    )
    v1 = compute_kiwoom_equity_for_risk(
        account, policy_version=KIWOOM_EQUITY_V1_IMMEDIATE_CASH
    )
    v2 = compute_kiwoom_equity_for_risk(
        account, policy_version=KIWOOM_EQUITY_V2_SETTLEMENT_AWARE
    )
    assert v1.equity_for_risk == Decimal("4871959.00")
    assert v2.pending_settlement_cash == Decimal("271426.00")
    assert v2.equity_for_risk == Decimal("5133337.00")
    assert v2.equity_source == SOURCE_ESTIMATED_ASSET
    # settlement-only로 V1 대비 equity가 올라감 → false loss 감소
    assert v2.equity_for_risk - v1.equity_for_risk == Decimal("261378.00")
    assert v2.equity_for_risk > v1.equity_for_risk


def test_buy_settlement_state_d2_not_inflating_beyond_stock() -> None:
    # 매수 직후: entr 감소, 주식 평가 증가 — d2≈entr이면 pending 0
    account = _kiwoom_account(
        entr="500000",
        tot_evlt="4500000",
        d1="500000",
        d2="500000",
        prsm="5000000",
    )
    result = compute_kiwoom_equity_for_risk(
        account, policy_version=KIWOOM_EQUITY_V2_SETTLEMENT_AWARE
    )
    assert result.pending_settlement_cash == Decimal("0.00")
    assert result.equity_for_risk == Decimal("5000000.00")


def test_d1_d2_differs_from_entr_fallback_without_estimated() -> None:
    account = _kiwoom_account(
        entr="100000",
        tot_evlt="900000",
        d1="250000",
        d2="300000",
        prsm=None,
    )
    result = compute_kiwoom_equity_for_risk(
        account, policy_version=KIWOOM_EQUITY_V2_SETTLEMENT_AWARE
    )
    assert result.equity_for_risk == Decimal("1200000.00")
    assert result.equity_source == SOURCE_D2_PLUS_STOCK
    assert result.pending_settlement_cash == Decimal("200000.00")


def test_estimated_asset_available_preferred() -> None:
    account = _kiwoom_account(
        entr="100",
        tot_evlt="1000",
        d2="200",
        prsm="1195",
    )
    result = compute_kiwoom_equity_for_risk(
        account, policy_version=KIWOOM_EQUITY_V2_SETTLEMENT_AWARE
    )
    assert result.equity_source == SOURCE_ESTIMATED_ASSET
    assert result.equity_for_risk == Decimal("1195.00")


def test_estimated_asset_missing_fallback() -> None:
    account = _kiwoom_account(
        entr="100",
        tot_evlt="1000",
        d2="200",
    )
    result = compute_kiwoom_equity_for_risk(
        account, policy_version=KIWOOM_EQUITY_V2_SETTLEMENT_AWARE
    )
    assert result.estimated_asset is None
    assert result.equity_source == SOURCE_D2_PLUS_STOCK
    assert result.equity_for_risk == Decimal("1200.00")


def test_estimated_asset_rejected_when_nonsensical() -> None:
    # 추정자산이 주식평가의 85% 미만 → fallback
    account = _kiwoom_account(
        entr="100",
        tot_evlt="1000000",
        d2="100",
        prsm="100",
    )
    result = compute_kiwoom_equity_for_risk(
        account, policy_version=KIWOOM_EQUITY_V2_SETTLEMENT_AWARE
    )
    assert result.equity_source == SOURCE_D2_PLUS_STOCK
    assert result.equity_for_risk == Decimal("1000100.00")


def test_opening_current_same_policy_via_snapshot_equity() -> None:
    account = _kiwoom_account(
        entr="164342",
        tot_evlt="4707617",
        d2="435768",
        prsm="5133337",
    )
    opening = snapshot_equity(
        account, policy_version=KIWOOM_EQUITY_V2_SETTLEMENT_AWARE
    )
    current = snapshot_equity(
        account, policy_version=KIWOOM_EQUITY_V2_SETTLEMENT_AWARE
    )
    assert opening == current == Decimal("5133337.00")


def test_legacy_baseline_mid_day_stays_on_v1() -> None:
    assert (
        resolve_kiwoom_policy_for_baseline(None)
        == KIWOOM_EQUITY_V1_IMMEDIATE_CASH
    )
    assert (
        resolve_kiwoom_policy_for_baseline(KIWOOM_EQUITY_V1_IMMEDIATE_CASH)
        == KIWOOM_EQUITY_V1_IMMEDIATE_CASH
    )
    assert (
        resolve_kiwoom_policy_for_baseline(KIWOOM_EQUITY_V2_SETTLEMENT_AWARE)
        == KIWOOM_EQUITY_V2_SETTLEMENT_AWARE
    )


def test_genuine_mtm_loss_still_detected() -> None:
    opening = Decimal("5439301.00")
    # V2 equity still well below opening after settlement fix
    account = _kiwoom_account(
        entr="164342",
        tot_evlt="4707617",
        d2="435768",
        prsm="5133337",
    )
    current = snapshot_equity(
        account, policy_version=KIWOOM_EQUITY_V2_SETTLEMENT_AWARE
    )
    loss = daily_loss_from_pnl(current - opening)
    assert loss > Decimal("100000")
    assert loss == Decimal("305964.00")


def test_settlement_only_movement_does_not_create_false_loss() -> None:
    # 동일 총자산, entr만 d2로 이동한 것처럼 V2 equity 불변
    before = _kiwoom_account(
        entr="435768",
        tot_evlt="4707617",
        d1="435768",
        d2="435768",
        prsm="5143385",
    )
    after = _kiwoom_account(
        entr="164342",
        tot_evlt="4707617",
        d1="435768",
        d2="435768",
        prsm="5143385",
    )
    eq_before = snapshot_equity(
        before, policy_version=KIWOOM_EQUITY_V2_SETTLEMENT_AWARE
    )
    eq_after = snapshot_equity(
        after, policy_version=KIWOOM_EQUITY_V2_SETTLEMENT_AWARE
    )
    assert eq_before == eq_after
    # V1은 entr 이동을 손실로 오인
    v1_before = snapshot_equity(
        before, policy_version=KIWOOM_EQUITY_V1_IMMEDIATE_CASH
    )
    v1_after = snapshot_equity(
        after, policy_version=KIWOOM_EQUITY_V1_IMMEDIATE_CASH
    )
    assert v1_before - v1_after == Decimal("271426.00")


def test_daily_loss_limit_remains_fail_closed() -> None:
    opening = Decimal("5439301")
    current = Decimal("5133337")
    limit = Decimal("100000")
    loss = daily_loss_from_pnl(current - opening)
    assert loss > limit
    entry_allowed = loss < limit
    assert entry_allowed is False


def test_upbit_regression_unchanged() -> None:
    account = SimpleNamespace(
        broker_code="UPBIT",
        deposit_amount=Decimal("100"),
        total_evaluation_amount=Decimal("900"),
        total_profit_loss=Decimal("-999999"),
        raw_data={},
    )
    assert snapshot_equity(account) == Decimal("1000.00")


def test_mapper_embeds_equity_for_risk_provenance() -> None:
    mapped = KiwoomAccountMapper.map(
        account_number="****",
        deposit_payload={
            "entr": "164342",
            "d1_entra": "435768",
            "d2_entra": "435768",
            "prsm_dpst_aset_amt": "5133337",
            "d1_sel_exct_amt": "271426",
        },
        balance_payload={"tot_evlt_amt": "4707617", "acnt_evlt_remn_indv_tot": []},
    )
    meta = mapped.raw_data["equity_for_risk"]
    assert meta["equity_policy_version"] == KIWOOM_EQUITY_V2_SETTLEMENT_AWARE
    assert meta["equity_source"] == SOURCE_ESTIMATED_ASSET
    assert meta["pending_settlement_cash"] == "271426.00"
    # API 호환: deposit_amount는 여전히 entr
    assert mapped.deposit_amount == Decimal("164342")
    assert mapped.total_evaluation_amount == Decimal("4707617")


def test_v1_source_is_immediate_cash() -> None:
    account = _kiwoom_account(entr="10", tot_evlt="20", d2="99", prsm="999")
    result = compute_kiwoom_equity_for_risk(
        account, policy_version=KIWOOM_EQUITY_V1_IMMEDIATE_CASH
    )
    assert result.equity_source == SOURCE_IMMEDIATE_PLUS_STOCK
    assert result.equity_for_risk == Decimal("30.00")
