from __future__ import annotations

"""공시 유형 분류 및 중요도 점수."""

from decimal import Decimal


_MAJOR_KEYWORDS = (
    "주요사항",
    "유상증자",
    "무상증자",
    "합병",
    "분할",
    "영업양도",
    "영업양수",
    "자기주식",
    "상장폐지",
    "거래정지",
    "횡령",
    "배임",
    "감사의견",
    "관리종목",
    "투자유의",
)

_PERIODIC_KEYWORDS = (
    "사업보고서",
    "분기보고서",
    "반기보고서",
    "연결감사보고서",
    "감사보고서",
)

_OWNERSHIP_KEYWORDS = (
    "임원ㆍ주요주주",
    "임원·주요주주",
    "대량보유",
    "주식등의 대량보유",
    "임원변경",
)


def classify_disclosure(
    report_name: str,
    remark: str | None = None,
) -> tuple[str, Decimal, bool, str | None]:
    """
    공시 유형·중요도·정정 여부를 판정한다.

    returns: (category_code, importance_score, is_correction, related_hint)
    """

    name = (report_name or "").strip()
    is_correction = "정정" in name or (remark or "").strip() == "유"

    if any(key in name for key in _MAJOR_KEYWORDS):
        category = "MAJOR"
        score = Decimal("90")
    elif any(key in name for key in _PERIODIC_KEYWORDS):
        category = "PERIODIC"
        score = Decimal("55")
    elif any(key in name for key in _OWNERSHIP_KEYWORDS):
        category = "OWNERSHIP"
        score = Decimal("65")
    elif is_correction:
        category = "CORRECTION"
        score = Decimal("70")
    else:
        category = "OTHER"
        score = Decimal("30")

    if is_correction and category != "CORRECTION":
        score = min(Decimal("100"), score + Decimal("10"))

    return category, score, is_correction, None
