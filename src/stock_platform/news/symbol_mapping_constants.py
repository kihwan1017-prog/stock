"""STEP N3 — Symbol Mapping 상수 (AI/Scanner 연동 금지)."""

from __future__ import annotations

RESOLVER_VERSION = "upbit_symbol_resolver_v2"

MARKET_CODE_UPBIT = "UPBIT"
QUOTE_KRW = "KRW"

STATUS_MAPPED = "MAPPED"
STATUS_UNMAPPED = "UNMAPPED"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_PARTIAL = "PARTIAL"  # mapped + ambiguous candidates

MATCH_EXACT_MARKET_SYMBOL = "EXACT_MARKET_SYMBOL"
MATCH_EXACT_BASE_SYMBOL = "EXACT_BASE_SYMBOL"
MATCH_KOREAN_NAME = "KOREAN_NAME"
MATCH_ENGLISH_NAME = "ENGLISH_NAME"
MATCH_BODY_ONLY_ALIAS = "BODY_ONLY_ALIAS"

FIELD_TITLE = "TITLE"
FIELD_BODY = "BODY"

CONF_EXACT_MARKET = 1.00
CONF_EXACT_BASE = 0.95
CONF_KOREAN_NAME = 0.95
CONF_ENGLISH_NAME = 0.90
CONF_BODY_ONLY = 0.80

# 짧은/일반영어 토큰 — base-only 자동 mapping 금지 (Fail Closed)
AMBIGUOUS_BASE_TICKERS = frozenset(
    {
        "A",
        "I",
        "AI",
        "ALL",
        "AN",
        "AND",
        "AS",
        "AT",
        "BE",
        "BY",
        "DO",
        "FOR",
        "GO",
        "ID",
        "IF",
        "IN",
        "IS",
        "IT",
        "ME",
        "NO",
        "OF",
        "OK",
        "ON",
        "ONE",
        "OR",
        "SO",
        "TO",
        "UP",
        "WE",
        "YOU",
        "THE",
        "NOW",
        "HOT",
        "FUN",
        "GAS",
        "KEY",
        "NET",
        "NEW",
        "OLD",
        "TOP",
        "BOX",
        "CAT",
        "DOG",
        "ACE",
        "ANY",
        "CAN",
        "HAS",
        "HAD",
        "WAS",
        "ARE",
        "NOT",
        "BUT",
        "OUT",
        "OWN",
        "SET",
        "GET",
        "PUT",
        "RUN",
        "SAY",
        "SEE",
        "USE",
        "WAY",
        "WHO",
        "WHY",
        "HOW",
        "YES",
        "AGO",
        "VIA",
        "PER",
    }
)

# 본문(base ticker) 단독 매칭 최소 길이 — NFT auction 등 일반어 오탐 완화
BODY_BASE_ALIAS_MIN_LEN = 5

# match_type 컬럼 String(30) 한도 내
MATCH_TYPE_MAX_LEN = 30
