from decimal import Decimal

from stock_platform.disclosure.classifier import classify_disclosure
from stock_platform.news.service import NewsService


def test_clean_html() -> None:
    value = "<b>삼성전자</b> &amp; 반도체"
    assert NewsService._clean_html(value) == "삼성전자 & 반도체"


def test_normalize_title() -> None:
    assert NewsService._normalize_title("  삼성  전자  ") == "삼성 전자"


def test_classify_major_disclosure() -> None:
    category, score, is_correction, _ = classify_disclosure(
        "주요사항보고서(유상증자결정)"
    )
    assert category == "MAJOR"
    assert score >= Decimal("90")
    assert is_correction is False


def test_classify_correction_disclosure() -> None:
    category, score, is_correction, _ = classify_disclosure(
        "[정정]분기보고서"
    )
    assert is_correction is True
    assert category == "PERIODIC"
    assert score >= Decimal("65")
