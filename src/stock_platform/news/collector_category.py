"""STEP N2 — Upbit 공지 category rule 매핑 (AI 미사용)."""

from __future__ import annotations

from stock_platform.news.collector_constants import (
    CATEGORY_CAUTION,
    CATEGORY_DELISTING,
    CATEGORY_DEPOSIT_WITHDRAWAL,
    CATEGORY_GENERAL,
    CATEGORY_LISTING,
    CATEGORY_MAINTENANCE,
    CATEGORY_SYSTEM,
    CATEGORY_TRADING_SUPPORT,
)

# Upbit API category 문자열 → 내부 enum
_SOURCE_CATEGORY_MAP: dict[str, str] = {
    "입출금": CATEGORY_DEPOSIT_WITHDRAWAL,
    "거래": CATEGORY_TRADING_SUPPORT,
    "디지털 자산": CATEGORY_TRADING_SUPPORT,
    "디지털자산": CATEGORY_TRADING_SUPPORT,
    "서비스": CATEGORY_GENERAL,
    "서비스+": CATEGORY_GENERAL,
    "안내": CATEGORY_GENERAL,
    "이벤트": CATEGORY_GENERAL,
}


def normalize_notice_category(
    *,
    source_category: str | None,
    title: str | None,
) -> str:
    """확실하지 않으면 GENERAL. AI 호출 없음."""

    title_text = (title or "").strip()
    src = (source_category or "").strip()

    # 제목 키워드 우선 (상장/유의 등 세분화)
    if any(k in title_text for k in ("거래지원 종료", "상장폐지", "거래 지원 종료")):
        return CATEGORY_DELISTING
    if any(
        k in title_text
        for k in (
            "디지털 자산 추가",
            "마켓 디지털 자산 추가",
            "거래지원 안내",
            "거래 지원 안내",
        )
    ):
        return CATEGORY_LISTING
    if any(k in title_text for k in ("입출금", "출금 중단", "입금 중단", "입출금 재개")):
        return CATEGORY_DEPOSIT_WITHDRAWAL
    if any(k in title_text for k in ("유의 종목", "투자 유의", "시장 경고", "주의 종목", "경보")):
        return CATEGORY_CAUTION
    if any(k in title_text for k in ("네트워크 점검", "정기 점검", "임시 점검", "서비스 점검")):
        return CATEGORY_MAINTENANCE
    if any(k in title_text for k in ("시스템 점검", "시스템 장애", "장애 복구")):
        return CATEGORY_SYSTEM
    if "거래지원" in title_text or "거래 지원" in title_text:
        return CATEGORY_TRADING_SUPPORT

    mapped = _SOURCE_CATEGORY_MAP.get(src)
    if mapped:
        return mapped

    # '서비스+' 처럼 접미사 변형
    base = src.rstrip("+").strip()
    mapped = _SOURCE_CATEGORY_MAP.get(base)
    if mapped:
        return mapped

    return CATEGORY_GENERAL
