"""STEP N3 — deterministic UPBIT KRW symbol resolver (AI 없음)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from stock_platform.news.symbol_mapping_constants import (
    AMBIGUOUS_BASE_TICKERS,
    BODY_BASE_ALIAS_MIN_LEN,
    CONF_BODY_ONLY,
    CONF_ENGLISH_NAME,
    CONF_EXACT_BASE,
    CONF_EXACT_MARKET,
    CONF_KOREAN_NAME,
    FIELD_BODY,
    FIELD_TITLE,
    MATCH_BODY_ONLY_ALIAS,
    MATCH_ENGLISH_NAME,
    MATCH_EXACT_BASE_SYMBOL,
    MATCH_EXACT_MARKET_SYMBOL,
    MATCH_KOREAN_NAME,
    RESOLVER_VERSION,
    STATUS_AMBIGUOUS,
    STATUS_MAPPED,
    STATUS_PARTIAL,
    STATUS_UNMAPPED,
)


@dataclass(frozen=True, slots=True)
class InstrumentAlias:
    symbol: str  # KRW-XRP
    base: str  # XRP
    korean_name: str
    english_name: str
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class AliasEntry:
    symbol: str
    alias: str
    match_type: str
    mapping_confidence: float
    is_ambiguous_ticker: bool = False


@dataclass(slots=True)
class SymbolMatch:
    symbol: str
    matched_alias: str
    match_type: str
    matched_field: str
    mapping_confidence: float
    resolver_version: str = RESOLVER_VERSION


@dataclass(slots=True)
class ResolveResult:
    status: str
    mappings: list[SymbolMatch] = field(default_factory=list)
    ambiguous: list[dict] = field(default_factory=list)
    resolver_version: str = RESOLVER_VERSION


def extract_base_asset(market_symbol: str) -> str:
    sym = str(market_symbol or "").strip().upper()
    if "-" in sym:
        return sym.split("-", 1)[1]
    return sym


def build_alias_entries(instruments: Iterable[InstrumentAlias]) -> list[AliasEntry]:
    """Alias source: market symbol → base → korean → english. 수동 사전 최소화."""

    entries: list[AliasEntry] = []
    for inst in instruments:
        if not inst.is_active:
            continue
        symbol = inst.symbol.strip().upper()
        if not symbol.startswith("KRW-"):
            continue
        base = extract_base_asset(symbol)
        if not base:
            continue

        entries.append(
            AliasEntry(
                symbol=symbol,
                alias=symbol,
                match_type=MATCH_EXACT_MARKET_SYMBOL,
                mapping_confidence=CONF_EXACT_MARKET,
            )
        )

        ambiguous = (
            base in AMBIGUOUS_BASE_TICKERS or len(base) <= 2
        )
        entries.append(
            AliasEntry(
                symbol=symbol,
                alias=base,
                match_type=MATCH_EXACT_BASE_SYMBOL,
                mapping_confidence=CONF_EXACT_BASE,
                is_ambiguous_ticker=ambiguous,
            )
        )

        korean = (inst.korean_name or "").strip()
        if korean and len(korean) >= 2:
            entries.append(
                AliasEntry(
                    symbol=symbol,
                    alias=korean,
                    match_type=MATCH_KOREAN_NAME,
                    mapping_confidence=CONF_KOREAN_NAME,
                )
            )

        english = (inst.english_name or "").strip()
        if english and len(english) >= 3:
            entries.append(
                AliasEntry(
                    symbol=symbol,
                    alias=english,
                    match_type=MATCH_ENGLISH_NAME,
                    mapping_confidence=CONF_ENGLISH_NAME,
                )
            )

    return entries


def _latin_token_pattern(alias: str) -> re.Pattern[str]:
    # 영문/숫자 ticker·이름 — word boundary (문자·숫자 경계)
    escaped = re.escape(alias)
    return re.compile(
        rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def _korean_phrase_pattern(alias: str) -> re.Pattern[str]:
    # 한글명 — 연속 phrase. 앞뒤가 한글이면 오탐 가능 → 한글 경계 제한
    escaped = re.escape(alias)
    return re.compile(
        rf"(?<![가-힣]){escaped}(?![가-힣])",
    )


def _alias_matches_text(alias: str, text: str, *, match_type: str) -> bool:
    if not alias or not text:
        return False
    if match_type == MATCH_KOREAN_NAME:
        return _korean_phrase_pattern(alias).search(text) is not None
    # market / base / english — latin token boundary
    return _latin_token_pattern(alias).search(text) is not None


def resolve_symbols(
    *,
    title: str,
    body: str | None,
    aliases: list[AliasEntry],
) -> ResolveResult:
    """title 우선. 명시된 symbol만. ambiguous ticker는 Fail Closed."""

    title_text = (title or "").strip()
    body_text = (body or "").strip()
    if not title_text and not body_text:
        return ResolveResult(status=STATUS_UNMAPPED)

    # 긴 alias 우선 — "Bitcoin Cash" vs "Bitcoin"
    ordered = sorted(
        aliases,
        key=lambda a: (len(a.alias), a.mapping_confidence),
        reverse=True,
    )

    # alias 충돌: 동일 alias 문자열이 여러 symbol에 매핑되면 ambiguous
    alias_owners: dict[str, set[str]] = {}
    for entry in ordered:
        key = entry.alias.casefold()
        alias_owners.setdefault(key, set()).add(entry.symbol)

    best_by_symbol: dict[str, SymbolMatch] = {}
    ambiguous_hits: list[dict] = []
    seen_ambiguous: set[str] = set()

    def consider(entry: AliasEntry, field: str) -> None:
        text = title_text if field == FIELD_TITLE else body_text
        if not _alias_matches_text(entry.alias, text, match_type=entry.match_type):
            return

        owners = alias_owners.get(entry.alias.casefold()) or {entry.symbol}
        if len(owners) > 1:
            key = entry.alias.casefold()
            if key not in seen_ambiguous:
                seen_ambiguous.add(key)
                ambiguous_hits.append(
                    {
                        "alias": entry.alias,
                        "reason": "MULTI_SYMBOL_ALIAS",
                        "candidates": sorted(owners),
                        "matched_field": field,
                    }
                )
            return

        # 짧은/모호 ticker — market symbol·이름 매칭만 허용
        if entry.is_ambiguous_ticker and entry.match_type == MATCH_EXACT_BASE_SYMBOL:
            key = f"{entry.symbol}|{entry.alias}"
            if key not in seen_ambiguous:
                seen_ambiguous.add(key)
                ambiguous_hits.append(
                    {
                        "alias": entry.alias,
                        "symbol": entry.symbol,
                        "reason": "AMBIGUOUS_SHORT_TICKER",
                        "matched_field": field,
                        "note": "base-only auto-link forbidden",
                    }
                )
            return

        conf = float(entry.mapping_confidence)
        match_type = entry.match_type
        if field == FIELD_BODY:
            # 본문 base ticker 단독은 길이 제한 — 일반 영단어 오탐 완화
            if entry.match_type == MATCH_EXACT_BASE_SYMBOL:
                if len(entry.alias) < BODY_BASE_ALIAS_MIN_LEN:
                    return
            conf = min(conf, CONF_BODY_ONLY)
            if entry.match_type != MATCH_EXACT_MARKET_SYMBOL:
                match_type = MATCH_BODY_ONLY_ALIAS

        candidate = SymbolMatch(
            symbol=entry.symbol,
            matched_alias=entry.alias,
            match_type=match_type[:30],
            matched_field=field,
            mapping_confidence=round(conf, 4),
        )
        prev = best_by_symbol.get(entry.symbol)
        if prev is None:
            best_by_symbol[entry.symbol] = candidate
            return
        # title > body, 그다음 confidence
        prev_rank = (
            1 if prev.matched_field == FIELD_TITLE else 0,
            prev.mapping_confidence,
        )
        new_rank = (
            1 if field == FIELD_TITLE else 0,
            conf,
        )
        if new_rank > prev_rank:
            best_by_symbol[entry.symbol] = candidate

    for entry in ordered:
        consider(entry, FIELD_TITLE)
    for entry in ordered:
        # 이미 title에서 잡힌 symbol은 body로 덮지 않음 (consider가 rank 비교)
        consider(entry, FIELD_BODY)

    mappings = sorted(
        best_by_symbol.values(),
        key=lambda m: (-m.mapping_confidence, m.symbol),
    )

    if mappings and ambiguous_hits:
        status = STATUS_PARTIAL
    elif mappings:
        status = STATUS_MAPPED
    elif ambiguous_hits:
        status = STATUS_AMBIGUOUS
    else:
        status = STATUS_UNMAPPED

    return ResolveResult(
        status=status,
        mappings=mappings,
        ambiguous=ambiguous_hits,
    )
