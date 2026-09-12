from decimal import Decimal

from stock_platform.broker.kiwoom.price import (
    normalize_kiwoom_price,
    parse_kiwoom_mrkcond_quote,
)
from stock_platform.position.lot_rounding import is_krx_tick_aligned, krx_tick_size


def test_normalize_kiwoom_price_signed_and_plain() -> None:
    assert normalize_kiwoom_price("-40200") == Decimal("40200")
    assert normalize_kiwoom_price("+40200") == Decimal("40200")
    assert normalize_kiwoom_price("40200") == Decimal("40200")
    assert normalize_kiwoom_price("0") == Decimal("0")
    assert normalize_kiwoom_price("") is None
    assert normalize_kiwoom_price(None) is None
    assert normalize_kiwoom_price("abc") is None


def test_normalize_keeps_comma_and_whitespace() -> None:
    assert normalize_kiwoom_price(" -40,200 ") == Decimal("40200")


def test_mrkcond_negative_best_ask_009240_fixture() -> None:
    quote = parse_kiwoom_mrkcond_quote(
        {
            "return_code": 0,
            "stk_nm": "한샘",
            "sel_fpr_bid": "-40200",
            "buy_fpr_bid": "-40150",
        },
        api_id="ka10004",
    )
    assert quote.ok is True
    assert quote.name == "한샘"
    assert quote.raw_best_ask == "-40200"
    assert quote.best_ask == Decimal("40200")
    tick = krx_tick_size(quote.best_ask)
    assert tick == Decimal("50")
    assert is_krx_tick_aligned(quote.best_ask) is True


def test_mrkcond_positive_ask_still_works() -> None:
    quote = parse_kiwoom_mrkcond_quote({"sel_fpr_bid": "+40600"})
    assert quote.ok is True
    assert quote.best_ask == Decimal("40600")


def test_mrkcond_zero_or_missing_ask_is_invalid() -> None:
    assert parse_kiwoom_mrkcond_quote({"sel_fpr_bid": "0"}).ok is False
    assert parse_kiwoom_mrkcond_quote({}).ok is False
    assert parse_kiwoom_mrkcond_quote({"sel_fpr_bid": ""}).ok is False
