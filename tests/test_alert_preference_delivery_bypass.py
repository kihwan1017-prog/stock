"""Alert preference must suppress Telegram even when allowlisted.

ROOT: evaluate_telegram_policy used allowlist/category without preference.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.notification.alert_v2.mapping import resolve_preference_key
from stock_platform.notification.telegram_policy import evaluate_telegram_policy


def _session_with_prefs(off_keys: set[str]) -> MagicMock:
    """DB-like session: listed keys OFF, others ON."""

    session = MagicMock()

    def _get(_cls, key):
        return SimpleNamespace(enabled=key not in off_keys)

    session.get.side_effect = _get
    return session


_NOISY_OFF = {
    "UPBIT_AI_DECISION",
    "CANDIDATE_ANALYSIS",
    "AUTO_SLOT",
    "SHADOW_ANALYSIS",
}


def test_candidate_analysis_off_blocks_scanner_candidate() -> None:
    d = evaluate_telegram_policy(
        event_type="UPBIT_SCANNER_CANDIDATE",
        detail={"broker_code": "UPBIT", "user_broker_account_id": 1380},
        session=_session_with_prefs(_NOISY_OFF),
    )
    assert d.allowed is False
    assert "PREFERENCE_OFF" in d.reason


def test_auto_slot_off_blocks_slot_assigned() -> None:
    d = evaluate_telegram_policy(
        event_type="UPBIT_PORTFOLIO_SLOT_ASSIGNED",
        detail={"broker_code": "UPBIT"},
        session=_session_with_prefs(_NOISY_OFF),
    )
    assert d.allowed is False
    assert "PREFERENCE_OFF" in d.reason


def test_shadow_analysis_off_blocks_shadow_opened() -> None:
    d = evaluate_telegram_policy(
        event_type="UPBIT_SCANNER_SHADOW_OPENED",
        detail={"broker_code": "UPBIT"},
        session=_session_with_prefs(_NOISY_OFF),
    )
    assert d.allowed is False
    assert "PREFERENCE_OFF" in d.reason


def test_upbit_ai_decision_off_blocks_ai_gate_system_and_upbit() -> None:
    for detail in (
        {"broker_code": "UPBIT", "telegram_market": "UPBIT"},
        {"telegram_market": "COMMON"},  # SYSTEM presentation → same key
        {"market": "UPBIT"},
    ):
        d = evaluate_telegram_policy(
            event_type="AI_GATE_RECOMMENDATION_CHANGED",
            detail=detail,
            session=_session_with_prefs(_NOISY_OFF),
        )
        assert d.allowed is False, detail
        assert "UPBIT_AI_DECISION" in d.reason


def test_kiwoom_ai_decision_unaffected_when_upbit_ai_off() -> None:
    with patch(
        "stock_platform.notification.telegram_policy._kiwoom_trading_ready",
        return_value=(True, "READY", {}),
    ):
        d = evaluate_telegram_policy(
            event_type="AI_GATE_RECOMMENDATION_CHANGED",
            detail={"broker_code": "KIWOOM", "market": "KIWOOM"},
            session=_session_with_prefs(_NOISY_OFF),
        )
    assert d.allowed is True
    assert "PREFERENCE_OFF" not in d.reason


def test_allowlist_true_preference_false_still_blocks() -> None:
    """allowlist 통과해도 preference OFF면 발송 금지."""

    d = evaluate_telegram_policy(
        event_type="UPBIT_SCANNER_CANDIDATE",
        detail={"broker_code": "UPBIT"},
        session=_session_with_prefs({"CANDIDATE_ANALYSIS"}),
    )
    assert d.allowed is False


def test_preference_true_allowlist_true_allows_analysis() -> None:
    usage = {"entry_count": 1, "entry_limit": 10, "blocking": False}
    with patch(
        "stock_platform.notification.telegram_policy._upbit_daily_usage",
        return_value=usage,
    ):
        d = evaluate_telegram_policy(
            event_type="UPBIT_SCANNER_CANDIDATE",
            detail={"broker_code": "UPBIT", "user_broker_account_id": 1380},
            session=_session_with_prefs(set()),  # all ON
        )
    assert d.allowed is True
    assert d.reason == "UPBIT_ENTRY_AVAILABLE"


def test_preference_save_false_same_runtime_immediate() -> None:
    """같은 session lookup으로 저장 직후 OFF 반영 (장기 cache 없음)."""

    session = MagicMock()
    state = {"CANDIDATE_ANALYSIS": True}

    def _get(_cls, key):
        return SimpleNamespace(enabled=state.get(key, True))

    session.get.side_effect = _get
    usage = {"entry_count": 0, "entry_limit": 10, "blocking": False}

    with patch(
        "stock_platform.notification.telegram_policy._upbit_daily_usage",
        return_value=usage,
    ):
        before = evaluate_telegram_policy(
            event_type="UPBIT_SCANNER_CANDIDATE",
            detail={"broker_code": "UPBIT"},
            session=session,
        )
        assert before.allowed is True

        state["CANDIDATE_ANALYSIS"] = False
        after = evaluate_telegram_policy(
            event_type="UPBIT_SCANNER_CANDIDATE",
            detail={"broker_code": "UPBIT"},
            session=session,
        )
        assert after.allowed is False


def test_positive_controls_important_alerts_still_allowed() -> None:
    session = _session_with_prefs(_NOISY_OFF)
    cases = [
        ("ORDER_FILLED", {"broker_code": "UPBIT", "side": "BUY"}),
        ("ORDER_FILLED", {"broker_code": "UPBIT", "side": "SELL"}),
        ("UPBIT_AUTO_LONG_HOLD", {"broker_code": "UPBIT"}),
        ("AUTOTRADING_DAILY_REPORT", {"report_date": "2026-08-30"}),
        ("ORDER_REJECTED", {"broker_code": "UPBIT"}),
        ("BROKER_DISCONNECTED", {"broker_code": "UPBIT"}),
    ]
    for et, detail in cases:
        d = evaluate_telegram_policy(event_type=et, detail=detail, session=session)
        assert d.allowed is True, (et, d.reason)


def test_event_preference_mapping_canonical() -> None:
    assert (
        resolve_preference_key(
            "AI_GATE_RECOMMENDATION_CHANGED", detail={"market": "UPBIT"}
        ).value
        == "UPBIT_AI_DECISION"
    )
    assert (
        resolve_preference_key(
            "UPBIT_SCANNER_CANDIDATE", detail={"broker_code": "UPBIT"}
        ).value
        == "CANDIDATE_ANALYSIS"
    )
    assert (
        resolve_preference_key(
            "UPBIT_PORTFOLIO_SLOT_ASSIGNED", detail={"broker_code": "UPBIT"}
        ).value
        == "AUTO_SLOT"
    )
    assert (
        resolve_preference_key(
            "UPBIT_SCANNER_SHADOW_OPENED", detail={"broker_code": "UPBIT"}
        ).value
        == "SHADOW_ANALYSIS"
    )
    assert (
        resolve_preference_key(
            "AI_GATE_RECOMMENDATION_CHANGED", detail={"market": "KIWOOM"}
        ).value
        == "KIWOOM_AI_DECISION"
    )
