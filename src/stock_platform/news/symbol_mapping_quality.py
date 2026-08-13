"""STEP N3.1 — deterministic Mapping Quality Guard (AI 금지)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from stock_platform.news.collector_constants import (
    SOURCE_CODE_CRYPTO_NEWS,
    SOURCE_CODE_UPBIT_NOTICE,
)
from stock_platform.news.symbol_mapping_constants import (
    AMBIGUOUS_BASE_TICKERS,
    FIELD_BODY,
    FIELD_TITLE,
    MATCH_BODY_ONLY_ALIAS,
    MATCH_ENGLISH_NAME,
    MATCH_EXACT_BASE_SYMBOL,
    MATCH_EXACT_MARKET_SYMBOL,
    MATCH_KOREAN_NAME,
)
from stock_platform.news.symbol_mapping_quality_constants import (
    COMMON_ENGLISH_LEXICON,
    CRYPTO_CONTEXT_KEYWORDS,
    NEGATIVE_CONTEXT_PATTERNS,
    QUALITY_AMBIGUOUS,
    QUALITY_POLICY_VERSION,
    QUALITY_REJECTED,
    QUALITY_REVIEW_REQUIRED,
    QUALITY_TRUSTED,
    TOKEN_EXPLICIT_PATTERNS,
)
from stock_platform.news.symbol_resolver import InstrumentAlias, SymbolMatch


@dataclass(frozen=True, slots=True)
class QualityDecision:
    quality_status: str
    quality_reason: str
    review_required: bool
    review_reason: str | None
    quality_policy_version: str = QUALITY_POLICY_VERSION
    general_word_collision: bool = False
    crypto_context_hit: bool = False
    negative_context_hit: bool = False
    token_explicit_hit: bool = False


def is_latin_single_word(value: str) -> bool:
    text = (value or "").strip()
    if not text or " " in text or "-" in text:
        return False
    return bool(re.fullmatch(r"[A-Za-z]{2,20}", text))


def build_general_word_collision_set(
    instruments: Iterable[InstrumentAlias],
) -> frozenset[str]:
    """DB universe latin alias ∩ 일반 영어 어휘 — 코인 전용 blacklist 금지."""

    universe_latin: set[str] = set()
    for inst in instruments:
        for raw in (inst.base, inst.english_name):
            token = (raw or "").strip()
            if not token:
                continue
            # english_name 첫 토큰도 후보
            parts = re.split(r"[\s/_]+", token)
            for part in parts[:2]:
                if is_latin_single_word(part):
                    universe_latin.add(part.upper())
    return frozenset(universe_latin & COMMON_ENGLISH_LEXICON)


def _window_has_crypto_context(text: str, alias: str, *, radius: int = 48) -> bool:
    if not text or not alias:
        return False
    lower = text.lower()
    alias_l = alias.lower()
    # 전체 텍스트에 crypto keyword + alias 동시 존재 + 인접 window
    positions = [m.start() for m in re.finditer(re.escape(alias_l), lower)]
    if not positions:
        return False
    for pos in positions:
        start = max(0, pos - radius)
        end = min(len(lower), pos + len(alias_l) + radius)
        window = lower[start:end]
        for kw in CRYPTO_CONTEXT_KEYWORDS:
            if kw.lower() in window:
                return True
    # 전역 보조: alias 2회 이상 + crypto keyword 본문 존재
    if len(positions) >= 2:
        for kw in CRYPTO_CONTEXT_KEYWORDS:
            if kw.lower() in lower:
                return True
    return False


def _alias_count(text: str, alias: str) -> int:
    if not text or not alias:
        return 0
    return len(re.findall(re.escape(alias), text, flags=re.IGNORECASE))


def _patterns_hit(text: str, patterns: tuple[str, ...] | None) -> bool:
    if not text or not patterns:
        return False
    for pat in patterns:
        if re.search(pat, text, flags=re.IGNORECASE):
            return True
    return False


def classify_mapping_quality(
    *,
    match: SymbolMatch,
    title: str,
    body: str,
    source_code: str,
    collision_aliases: frozenset[str],
    article_ambiguous: bool = False,
) -> QualityDecision:
    """단일 mapping 품질 분류 — N4는 TRUSTED만 기본 소비."""

    source = (source_code or "").upper()
    alias = (match.matched_alias or "").strip()
    alias_key = alias.upper()
    field = (match.matched_field or "").upper()
    match_type = (match.match_type or "").upper()
    combined = f"{title or ''}\n{body or ''}"

    is_collision = alias_key in collision_aliases or (
        is_latin_single_word(alias) and alias_key in COMMON_ENGLISH_LEXICON
    )
    # ambiguous short ticker는 collision 취급 강화
    if alias_key in AMBIGUOUS_BASE_TICKERS:
        is_collision = True

    crypto_hit = _window_has_crypto_context(combined, alias)
    neg_hit = _patterns_hit(
        combined, NEGATIVE_CONTEXT_PATTERNS.get(alias_key)
    )
    token_hit = _patterns_hit(
        combined, TOKEN_EXPLICIT_PATTERNS.get(alias_key)
    )
    alias_repeats = _alias_count(title, alias) + _alias_count(body, alias)
    title_has_alias = _alias_count(title, alias) > 0

    # --- AMBIGUOUS ---
    if article_ambiguous and match_type == MATCH_EXACT_BASE_SYMBOL and (
        alias_key in AMBIGUOUS_BASE_TICKERS
    ):
        return QualityDecision(
            quality_status=QUALITY_AMBIGUOUS,
            quality_reason="AMBIGUOUS_SHORT_TICKER",
            review_required=True,
            review_reason="short_ticker_without_clear_coin_context",
            general_word_collision=is_collision,
            crypto_context_hit=crypto_hit,
            negative_context_hit=neg_hit,
            token_explicit_hit=token_hit,
        )

    # --- REJECTED: 일반어 + 부정 context, token 명시 없음 ---
    if is_collision and neg_hit and not token_hit:
        return QualityDecision(
            quality_status=QUALITY_REJECTED,
            quality_reason="GENERAL_ENGLISH_NEGATIVE_CONTEXT",
            review_required=False,
            review_reason=None,
            general_word_collision=True,
            crypto_context_hit=crypto_hit,
            negative_context_hit=True,
            token_explicit_hit=False,
        )

    # --- TITLE explicit → TRUSTED ---
    if field == FIELD_TITLE:
        if match_type == MATCH_EXACT_MARKET_SYMBOL:
            return _trusted("TITLE_EXACT_MARKET_SYMBOL", is_collision, crypto_hit, neg_hit, token_hit)
        if match_type == MATCH_EXACT_BASE_SYMBOL:
            if alias_key in AMBIGUOUS_BASE_TICKERS and not token_hit:
                return QualityDecision(
                    quality_status=QUALITY_AMBIGUOUS,
                    quality_reason="TITLE_AMBIGUOUS_BASE",
                    review_required=True,
                    review_reason="ambiguous_base_in_title",
                    general_word_collision=is_collision,
                    crypto_context_hit=crypto_hit,
                    negative_context_hit=neg_hit,
                    token_explicit_hit=token_hit,
                )
            return _trusted("TITLE_EXACT_BASE_SYMBOL", is_collision, crypto_hit, neg_hit, token_hit)
        if match_type == MATCH_KOREAN_NAME:
            return _trusted("TITLE_KOREAN_NAME", is_collision, crypto_hit, neg_hit, token_hit)
        if match_type == MATCH_ENGLISH_NAME:
            if is_collision and not token_hit and not crypto_hit:
                return QualityDecision(
                    quality_status=QUALITY_REVIEW_REQUIRED,
                    quality_reason="TITLE_ENGLISH_GENERAL_WORD",
                    review_required=True,
                    review_reason="english_name_general_word_collision",
                    general_word_collision=True,
                    crypto_context_hit=crypto_hit,
                    negative_context_hit=neg_hit,
                    token_explicit_hit=token_hit,
                )
            return _trusted("TITLE_ENGLISH_NAME", is_collision, crypto_hit, neg_hit, token_hit)

    # --- BODY_ONLY / body field ---
    is_body = field == FIELD_BODY or match_type == MATCH_BODY_ONLY_ALIAS
    if is_body:
        # CRYPTO_NEWS body plain → 더 보수적
        if source == SOURCE_CODE_CRYPTO_NEWS:
            if token_hit and crypto_hit:
                return QualityDecision(
                    quality_status=QUALITY_REVIEW_REQUIRED,
                    quality_reason="CRYPTO_NEWS_BODY_TOKEN_CONTEXT",
                    review_required=True,
                    review_reason="crypto_news_body_requires_human_or_title_confirm",
                    general_word_collision=is_collision,
                    crypto_context_hit=True,
                    negative_context_hit=neg_hit,
                    token_explicit_hit=True,
                )
            if is_collision:
                return QualityDecision(
                    quality_status=QUALITY_REJECTED
                    if neg_hit
                    else QUALITY_REVIEW_REQUIRED,
                    quality_reason=(
                        "CRYPTO_NEWS_BODY_GENERAL_WORD"
                        if not neg_hit
                        else "CRYPTO_NEWS_BODY_NEGATIVE"
                    ),
                    review_required=not neg_hit,
                    review_reason="crypto_news_body_general_word",
                    general_word_collision=True,
                    crypto_context_hit=crypto_hit,
                    negative_context_hit=neg_hit,
                    token_explicit_hit=token_hit,
                )
            return QualityDecision(
                quality_status=QUALITY_REVIEW_REQUIRED,
                quality_reason="CRYPTO_NEWS_BODY_ONLY",
                review_required=True,
                review_reason="crypto_news_body_only_default",
                general_word_collision=is_collision,
                crypto_context_hit=crypto_hit,
                negative_context_hit=neg_hit,
                token_explicit_hit=token_hit,
            )

        # UPBIT_NOTICE body
        if source == SOURCE_CODE_UPBIT_NOTICE:
            if token_hit or (crypto_hit and alias_repeats >= 2 and not is_collision):
                return _trusted(
                    "NOTICE_BODY_STRONG_CONTEXT",
                    is_collision,
                    crypto_hit,
                    neg_hit,
                    token_hit,
                )
            if is_collision and not token_hit:
                return QualityDecision(
                    quality_status=QUALITY_REJECTED if neg_hit else QUALITY_REVIEW_REQUIRED,
                    quality_reason=(
                        "NOTICE_BODY_GENERAL_WORD_COLLISION"
                        if not neg_hit
                        else "NOTICE_BODY_NEGATIVE_CONTEXT"
                    ),
                    review_required=not neg_hit,
                    review_reason="notice_body_general_english_collision",
                    general_word_collision=True,
                    crypto_context_hit=crypto_hit,
                    negative_context_hit=neg_hit,
                    token_explicit_hit=token_hit,
                )
            if crypto_hit or title_has_alias:
                return QualityDecision(
                    quality_status=QUALITY_REVIEW_REQUIRED,
                    quality_reason="NOTICE_BODY_WITH_CONTEXT",
                    review_required=True,
                    review_reason="notice_body_needs_review",
                    general_word_collision=is_collision,
                    crypto_context_hit=crypto_hit,
                    negative_context_hit=neg_hit,
                    token_explicit_hit=token_hit,
                )

        # 기본 BODY_ONLY
        return QualityDecision(
            quality_status=QUALITY_REVIEW_REQUIRED,
            quality_reason="BODY_ONLY_DEFAULT",
            review_required=True,
            review_reason="body_only_not_auto_trusted",
            general_word_collision=is_collision,
            crypto_context_hit=crypto_hit,
            negative_context_hit=neg_hit,
            token_explicit_hit=token_hit,
        )

    # fallback
    return QualityDecision(
        quality_status=QUALITY_REVIEW_REQUIRED,
        quality_reason="UNCLASSIFIED_REVIEW",
        review_required=True,
        review_reason="fallback_review",
        general_word_collision=is_collision,
        crypto_context_hit=crypto_hit,
        negative_context_hit=neg_hit,
        token_explicit_hit=token_hit,
    )


def _trusted(
    reason: str,
    is_collision: bool,
    crypto_hit: bool,
    neg_hit: bool,
    token_hit: bool,
) -> QualityDecision:
    return QualityDecision(
        quality_status=QUALITY_TRUSTED,
        quality_reason=reason,
        review_required=False,
        review_reason=None,
        general_word_collision=is_collision,
        crypto_context_hit=crypto_hit,
        negative_context_hit=neg_hit,
        token_explicit_hit=token_hit,
    )


def apply_quality_to_evidence(
    evidence: dict,
    decision: QualityDecision,
) -> dict:
    """기존 evidence 보존 + quality 필드 부여."""

    out = dict(evidence)
    out["quality_status"] = decision.quality_status
    out["quality_reason"] = decision.quality_reason
    out["quality_policy_version"] = decision.quality_policy_version
    out["review_required"] = decision.review_required
    out["review_reason"] = decision.review_reason
    out["general_word_collision"] = decision.general_word_collision
    out["crypto_context_hit"] = decision.crypto_context_hit
    out["negative_context_hit"] = decision.negative_context_hit
    out["token_explicit_hit"] = decision.token_explicit_hit
    return out
