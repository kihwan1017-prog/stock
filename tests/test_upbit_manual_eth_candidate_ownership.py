"""MANUAL ETH scanner → Shadow OK / REAL candidate NO + Telegram semantics."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from stock_platform.notification.builtin_templates import builtin_template_for
from stock_platform.notification.template_pipeline import render_notification
from stock_platform.trading.symbol_ownership.constants import (
    OWNER_AUTO,
    OWNER_AUTO_EXCLUDED,
    OWNER_FREE,
    OWNER_MANUAL,
    OWNER_UNKNOWN,
    SKIP_AUTO_ALREADY_MANAGED,
    SKIP_AUTO_EXCLUDED,
    SKIP_MANUAL_SYMBOL_EXCLUDED,
    SKIP_OWNERSHIP_UNKNOWN,
)
from stock_platform.trading.symbol_ownership.decision import (
    OwnershipFacts,
    decide_ownership,
)


def test_a_manual_eth_blocks_real_candidate() -> None:
    eth = decide_ownership(
        OwnershipFacts(broker_position_qty=Decimal("0.68"))
    )
    assert eth.owner == OWNER_MANUAL
    assert eth.entry_allowed is False
    assert eth.entry_skip_reason == SKIP_MANUAL_SYMBOL_EXCLUDED


def test_b_free_xrp_entry_allowed() -> None:
    xrp = decide_ownership(OwnershipFacts())
    assert xrp.owner == OWNER_FREE
    assert xrp.entry_allowed is True


def test_c_auto_slot_duplicate_entry_blocked() -> None:
    # OPEN/EXIT/COOLDOWN occupancy — 재진입 차단
    auto = decide_ownership(
        OwnershipFacts(
            auto_slot_active=True,
            auto_slot_occupies_entry=True,
        )
    )
    assert auto.owner == OWNER_AUTO
    assert auto.entry_allowed is False
    assert auto.entry_skip_reason == SKIP_AUTO_ALREADY_MANAGED


def test_c2_waiting_signal_only_allows_first_entry() -> None:
    # WAITING_SIGNAL 자기 슬롯만 — 첫 ENTRY 진행 허용 (false-positive 루프 방지)
    waiting = decide_ownership(
        OwnershipFacts(auto_slot_active=True, auto_slot_occupies_entry=False)
    )
    assert waiting.owner == OWNER_AUTO
    assert waiting.entry_allowed is True
    assert waiting.entry_skip_reason is None


def test_c3_open_binding_still_blocks() -> None:
    bound = decide_ownership(
        OwnershipFacts(
            auto_binding_qty=Decimal("1"),
            auto_slot_active=True,
            auto_slot_occupies_entry=False,
        )
    )
    assert bound.entry_allowed is False
    assert bound.entry_skip_reason == SKIP_AUTO_ALREADY_MANAGED


def test_d_auto_excluded_blocks() -> None:
    excluded = decide_ownership(OwnershipFacts(user_excluded=True))
    assert excluded.owner == OWNER_AUTO_EXCLUDED
    assert excluded.entry_allowed is False
    assert excluded.entry_skip_reason == SKIP_AUTO_EXCLUDED


def test_e_unknown_fail_closed() -> None:
    # AUTO 존재 + MANUAL open order → UNKNOWN mix → fail closed
    mixed = decide_ownership(
        OwnershipFacts(
            auto_binding_qty=Decimal("1"),
            manual_open_orders=1,
        )
    )
    assert mixed.owner == OWNER_UNKNOWN
    assert mixed.entry_allowed is False
    assert mixed.entry_skip_reason == SKIP_OWNERSHIP_UNKNOWN


def test_f_scanner_candidate_telegram_not_real_autotrading_label() -> None:
    tpl = builtin_template_for("UPBIT_SCANNER_CANDIDATE")
    assert "자동매매 후보 선정" not in tpl["title_template"]
    assert "시장 후보 분석" in tpl["title_template"]
    assert "실제 자동매매 후보가 아닙니다" in tpl["body_template"]

    rendered = render_notification(
        event_type="UPBIT_SCANNER_CANDIDATE",
        title="raw",
        message="raw",
        detail={
            "source": "upbit_opportunity_scanner_v0",
            "shadow_only": True,
            "candidate": {
                "symbol": "KRW-ETH",
                "rank": 2,
                "score": 68.82,
                "recommendation": "ALLOW",
                "confidence": 0.95,
            },
        },
    )
    assert "ETH" in rendered.body
    assert "실제 자동매매 후보가 아닙니다" in rendered.body
    assert "자동매매 후보 선정" not in rendered.title


def test_shadow_and_slot_labels_separated() -> None:
    shadow = builtin_template_for("UPBIT_SCANNER_SHADOW_OPENED")
    slot = builtin_template_for("UPBIT_PORTFOLIO_SLOT_ASSIGNED")
    assert "Shadow 후보 분석" in shadow["title_template"]
    assert "실제 자동매매 후보가 아닙니다" in shadow["body_template"]
    assert "자동매매 슬롯 등록" in slot["title_template"]
    assert "매수조건 감시 중" in slot["body_template"]


def test_portfolio_gate_reports_manual_excluded() -> None:
    from stock_platform.operation.upbit_full_market.portfolio_service import (
        UpbitPortfolioService,
    )

    session = MagicMock()
    svc = UpbitPortfolioService(session)
    with patch.object(
        svc,
        "_ownership_entry_gate",
        return_value={
            "allowed": False,
            "reason": SKIP_MANUAL_SYMBOL_EXCLUDED,
            "owner": OWNER_MANUAL,
            "ownership_reasons": ["MANUAL_POSITION"],
        },
    ):
        gate = svc._ownership_entry_gate(1380, "KRW-ETH")
    assert gate["allowed"] is False
    assert gate["reason"] == SKIP_MANUAL_SYMBOL_EXCLUDED
