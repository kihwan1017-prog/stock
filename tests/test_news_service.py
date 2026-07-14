from stock_platform.news.service import NewsService


def test_clean_html() -> None:
    value = "<b>삼성전자</b> &amp; 반도체"

    assert NewsService._clean_html(value) == "삼성전자 & 반도체"
