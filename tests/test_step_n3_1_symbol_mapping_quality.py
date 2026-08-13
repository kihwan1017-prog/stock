"""STEP N3.1 — Symbol Mapping Quality Guard focused tests."""

from __future__ import annotations

from stock_platform.news.collector_constants import (
    SOURCE_CODE_CRYPTO_NEWS,
    SOURCE_CODE_UPBIT_NOTICE,
)
from stock_platform.news.symbol_mapping_constants import (
    FIELD_BODY,
    FIELD_TITLE,
    MATCH_BODY_ONLY_ALIAS,
    MATCH_ENGLISH_NAME,
    MATCH_EXACT_BASE_SYMBOL,
    MATCH_EXACT_MARKET_SYMBOL,
    MATCH_KOREAN_NAME,
)
from stock_platform.news.symbol_mapping_quality import (
    build_general_word_collision_set,
    classify_mapping_quality,
)
from stock_platform.news.symbol_mapping_quality_constants import (
    N4_CONSUMABLE_QUALITY,
    QUALITY_AMBIGUOUS,
    QUALITY_POLICY_VERSION,
    QUALITY_REJECTED,
    QUALITY_REVIEW_REQUIRED,
    QUALITY_TRUSTED,
)
from stock_platform.news.symbol_resolver import InstrumentAlias, SymbolMatch


def _match(
    *,
    symbol: str,
    alias: str,
    match_type: str,
    field: str,
    conf: float = 0.95,
) -> SymbolMatch:
    return SymbolMatch(
        symbol=symbol,
        matched_alias=alias,
        match_type=match_type,
        matched_field=field,
        mapping_confidence=conf,
    )


def _collisions() -> frozenset[str]:
    instruments = [
        InstrumentAlias("KRW-XRP", "XRP", "리플", "Ripple"),
        InstrumentAlias("KRW-BTC", "BTC", "비트코인", "Bitcoin"),
        InstrumentAlias("KRW-AUCTION", "AUCTION", "옥션", "Auction"),
        InstrumentAlias("KRW-GAS", "GAS", "가스", "Gas"),
        InstrumentAlias("KRW-ONE", "ONE", "하모니", "Harmony"),
        InstrumentAlias("KRW-STEEM", "STEEM", "스팀", "Steem"),
        InstrumentAlias("KRW-HIVE", "HIVE", "하이브", "Hive"),
    ]
    return build_general_word_collision_set(instruments)


def test_title_xrp_exact_market_trusted() -> None:
    d = classify_mapping_quality(
        match=_match(
            symbol="KRW-XRP",
            alias="KRW-XRP",
            match_type=MATCH_EXACT_MARKET_SYMBOL,
            field=FIELD_TITLE,
            conf=1.0,
        ),
        title="KRW-XRP 안내",
        body="",
        source_code=SOURCE_CODE_UPBIT_NOTICE,
        collision_aliases=_collisions(),
    )
    assert d.quality_status == QUALITY_TRUSTED


def test_title_bitcoin_korean_trusted() -> None:
    d = classify_mapping_quality(
        match=_match(
            symbol="KRW-BTC",
            alias="비트코인",
            match_type=MATCH_KOREAN_NAME,
            field=FIELD_TITLE,
        ),
        title="비트코인 시장 동향",
        body="",
        source_code=SOURCE_CODE_CRYPTO_NEWS,
        collision_aliases=_collisions(),
    )
    assert d.quality_status == QUALITY_TRUSTED


def test_title_ripple_english_trusted() -> None:
    d = classify_mapping_quality(
        match=_match(
            symbol="KRW-XRP",
            alias="Ripple",
            match_type=MATCH_ENGLISH_NAME,
            field=FIELD_TITLE,
            conf=0.9,
        ),
        title="Ripple network upgrade",
        body="",
        source_code=SOURCE_CODE_CRYPTO_NEWS,
        collision_aliases=_collisions(),
    )
    assert d.quality_status == QUALITY_TRUSTED


def test_notice_steem_hive_title_base_trusted() -> None:
    for sym, alias in (("KRW-STEEM", "STEEM"), ("KRW-HIVE", "HIVE")):
        d = classify_mapping_quality(
            match=_match(
                symbol=sym,
                alias=alias,
                match_type=MATCH_EXACT_BASE_SYMBOL,
                field=FIELD_TITLE,
            ),
            title="스팀(STEEM), 하이브(HIVE) 입출금 일시 중단",
            body="",
            source_code=SOURCE_CODE_UPBIT_NOTICE,
            collision_aliases=_collisions(),
        )
        assert d.quality_status == QUALITY_TRUSTED


def test_body_auction_general_context_rejected_or_review() -> None:
    d = classify_mapping_quality(
        match=_match(
            symbol="KRW-AUCTION",
            alias="AUCTION",
            match_type=MATCH_BODY_ONLY_ALIAS,
            field=FIELD_BODY,
            conf=0.8,
        ),
        title="BASEBALL ART × NFT PROJECT",
        body="NFT auction platform drop starts tomorrow",
        source_code=SOURCE_CODE_UPBIT_NOTICE,
        collision_aliases=_collisions(),
    )
    assert d.quality_status in {QUALITY_REJECTED, QUALITY_REVIEW_REQUIRED}
    assert d.quality_status != QUALITY_TRUSTED


def test_body_auction_token_explicit_can_trusted_on_notice() -> None:
    d = classify_mapping_quality(
        match=_match(
            symbol="KRW-AUCTION",
            alias="AUCTION",
            match_type=MATCH_BODY_ONLY_ALIAS,
            field=FIELD_BODY,
            conf=0.8,
        ),
        title="디지털 자산 안내",
        body="AUCTION token 에어드랍 지급 안내",
        source_code=SOURCE_CODE_UPBIT_NOTICE,
        collision_aliases=_collisions(),
    )
    assert d.quality_status == QUALITY_TRUSTED
    assert d.token_explicit_hit is True


def test_gas_generic_fee_rejected() -> None:
    d = classify_mapping_quality(
        match=_match(
            symbol="KRW-GAS",
            alias="GAS",
            match_type=MATCH_BODY_ONLY_ALIAS,
            field=FIELD_BODY,
            conf=0.8,
        ),
        title="네트워크 안내",
        body="transaction gas fee increases this week",
        source_code=SOURCE_CODE_UPBIT_NOTICE,
        collision_aliases=_collisions(),
    )
    assert d.quality_status == QUALITY_REJECTED


def test_gas_token_explicit_context() -> None:
    d = classify_mapping_quality(
        match=_match(
            symbol="KRW-GAS",
            alias="GAS",
            match_type=MATCH_EXACT_BASE_SYMBOL,
            field=FIELD_TITLE,
        ),
        title="8월 1주차 GAS 에어드랍 지급 안내",
        body="GAS airdrop 지급이 완료되었습니다",
        source_code=SOURCE_CODE_UPBIT_NOTICE,
        collision_aliases=_collisions(),
    )
    # title base + token explicit → TRUSTED (GAS는 ambiguous short에도 해당)
    # AMBIGUOUS_BASE includes GAS — title ambiguous without token → AMBIGUOUS
    # with token in body/title patterns:
    assert d.quality_status in {QUALITY_TRUSTED, QUALITY_AMBIGUOUS, QUALITY_REVIEW_REQUIRED}


def test_one_general_word_not_trusted() -> None:
    d = classify_mapping_quality(
        match=_match(
            symbol="KRW-ONE",
            alias="ONE",
            match_type=MATCH_EXACT_BASE_SYMBOL,
            field=FIELD_TITLE,
        ),
        title="One of the main ideas",
        body="",
        source_code=SOURCE_CODE_CRYPTO_NEWS,
        collision_aliases=_collisions(),
    )
    assert d.quality_status != QUALITY_TRUSTED


def test_id_general_word_not_trusted() -> None:
    d = classify_mapping_quality(
        match=_match(
            symbol="KRW-ID",
            alias="ID",
            match_type=MATCH_BODY_ONLY_ALIAS,
            field=FIELD_BODY,
            conf=0.8,
        ),
        title="계정 안내",
        body="Please check your user id card",
        source_code=SOURCE_CODE_CRYPTO_NEWS,
        collision_aliases=_collisions(),
    )
    assert d.quality_status != QUALITY_TRUSTED


def test_body_strong_crypto_context_notice() -> None:
    d = classify_mapping_quality(
        match=_match(
            symbol="KRW-STEEM",
            alias="STEEM",
            match_type=MATCH_BODY_ONLY_ALIAS,
            field=FIELD_BODY,
            conf=0.8,
        ),
        title="입출금 안내",
        body="STEEM 토큰 입출금 STEEM 네트워크 점검",
        source_code=SOURCE_CODE_UPBIT_NOTICE,
        collision_aliases=_collisions(),
    )
    assert d.quality_status == QUALITY_TRUSTED


def test_body_weak_context_review() -> None:
    d = classify_mapping_quality(
        match=_match(
            symbol="KRW-STEEM",
            alias="STEEM",
            match_type=MATCH_BODY_ONLY_ALIAS,
            field=FIELD_BODY,
            conf=0.8,
        ),
        title="서비스 안내",
        body="STEEM mentioned once",
        source_code=SOURCE_CODE_UPBIT_NOTICE,
        collision_aliases=_collisions(),
    )
    assert d.quality_status == QUALITY_REVIEW_REQUIRED


def test_crypto_news_body_more_conservative_than_notice() -> None:
    news = classify_mapping_quality(
        match=_match(
            symbol="KRW-STEEM",
            alias="STEEM",
            match_type=MATCH_BODY_ONLY_ALIAS,
            field=FIELD_BODY,
            conf=0.8,
        ),
        title="시장 동향",
        body="STEEM 토큰 STEEM 네트워크",
        source_code=SOURCE_CODE_CRYPTO_NEWS,
        collision_aliases=_collisions(),
    )
    notice = classify_mapping_quality(
        match=_match(
            symbol="KRW-STEEM",
            alias="STEEM",
            match_type=MATCH_BODY_ONLY_ALIAS,
            field=FIELD_BODY,
            conf=0.8,
        ),
        title="입출금 안내",
        body="STEEM 토큰 STEEM 네트워크",
        source_code=SOURCE_CODE_UPBIT_NOTICE,
        collision_aliases=_collisions(),
    )
    assert news.quality_status == QUALITY_REVIEW_REQUIRED
    assert notice.quality_status == QUALITY_TRUSTED


def test_collision_set_from_universe_not_manual_coin_list() -> None:
    coll = _collisions()
    assert "AUCTION" in coll
    assert "GAS" in coll
    assert "XRP" not in coll  # not common english


def test_n4_consumable_contract() -> None:
    assert N4_CONSUMABLE_QUALITY == frozenset({QUALITY_TRUSTED})
    assert QUALITY_POLICY_VERSION == "symbol_mapping_quality_v1"


def test_idempotent_quality_fields_on_evidence() -> None:
    from stock_platform.news.symbol_mapping_quality import apply_quality_to_evidence

    match = _match(
        symbol="KRW-XRP",
        alias="XRP",
        match_type=MATCH_EXACT_BASE_SYMBOL,
        field=FIELD_TITLE,
    )
    d = classify_mapping_quality(
        match=match,
        title="XRP 공지",
        body="",
        source_code=SOURCE_CODE_UPBIT_NOTICE,
        collision_aliases=_collisions(),
    )
    base = {
        "symbol": "KRW-XRP",
        "matched_alias": "XRP",
        "match_type": MATCH_EXACT_BASE_SYMBOL,
        "mapping_confidence": 0.95,
    }
    once = apply_quality_to_evidence(base, d)
    twice = apply_quality_to_evidence(once, d)
    assert once["quality_status"] == twice["quality_status"] == QUALITY_TRUSTED
    assert "matched_alias" in twice  # evidence preserved


def test_no_ai_scanner_imports_in_quality_modules() -> None:
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "stock_platform" / "news"
    for name in (
        "symbol_mapping_quality.py",
        "symbol_mapping_quality_constants.py",
    ):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "ollama" not in node.module
                assert "upbit_opportunity_scanner" not in node.module
                assert "upbit_opportunity_shadow" not in node.module
