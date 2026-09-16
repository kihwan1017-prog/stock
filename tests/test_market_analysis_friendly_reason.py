"""Unit tests for market analysis friendly reasons (no DB)."""

from stock_platform.markets.user_friendly_reasons import friendly_reason


def test_friendly_reason_known_codes():
    assert "장 마감" in friendly_reason("MARKET_CLOSED")
    assert "시세" in friendly_reason("FEED_DOWN")
    assert "이동평균" in friendly_reason("SHORT_MA_NOT_ABOVE_LONG_MA")


def test_friendly_reason_unknown_keeps_code():
    msg = friendly_reason("SOME_UNKNOWN_CODE")
    assert "SOME_UNKNOWN_CODE" in msg


def test_friendly_reason_none():
    assert friendly_reason(None) == "특이 사유 없음"
