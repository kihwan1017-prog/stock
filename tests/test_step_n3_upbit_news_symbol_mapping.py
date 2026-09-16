"""STEP N3 — News Symbol Mapping focused tests (AI/Scanner 없음)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.news.symbol_mapping_constants import (
    AMBIGUOUS_BASE_TICKERS,
    MATCH_ENGLISH_NAME,
    MATCH_EXACT_BASE_SYMBOL,
    MATCH_EXACT_MARKET_SYMBOL,
    MATCH_KOREAN_NAME,
    RESOLVER_VERSION,
    STATUS_AMBIGUOUS,
    STATUS_MAPPED,
    STATUS_UNMAPPED,
)
from stock_platform.news.symbol_resolver import (
    AliasEntry,
    InstrumentAlias,
    build_alias_entries,
    resolve_symbols,
)


def _universe() -> list[AliasEntry]:
    instruments = [
        InstrumentAlias("KRW-XRP", "XRP", "리플", "Ripple"),
        InstrumentAlias("KRW-BTC", "BTC", "비트코인", "Bitcoin"),
        InstrumentAlias("KRW-ETH", "ETH", "이더리움", "Ethereum"),
        InstrumentAlias("KRW-STEEM", "STEEM", "스팀", "Steem"),
        InstrumentAlias("KRW-HIVE", "HIVE", "하이브", "Hive"),
        InstrumentAlias("KRW-ONE", "ONE", "하모니", "Harmony"),
        InstrumentAlias("KRW-ME", "ME", "매직에덴", "Magic Eden"),
        InstrumentAlias("KRW-SOL", "SOL", "솔라나", "Solana"),
    ]
    return build_alias_entries(instruments)


def test_exact_market_symbol_krw_xrp() -> None:
    r = resolve_symbols(
        title="KRW-XRP 마켓 안내",
        body="",
        aliases=_universe(),
    )
    assert r.status == STATUS_MAPPED
    assert any(m.symbol == "KRW-XRP" and m.match_type == MATCH_EXACT_MARKET_SYMBOL for m in r.mappings)


def test_base_symbol_xrp() -> None:
    r = resolve_symbols(title="XRP 입출금 재개", body="", aliases=_universe())
    assert any(
        m.symbol == "KRW-XRP" and m.match_type == MATCH_EXACT_BASE_SYMBOL
        for m in r.mappings
    )


def test_english_name_ripple() -> None:
    r = resolve_symbols(title="Ripple network upgrade", body="", aliases=_universe())
    assert any(
        m.symbol == "KRW-XRP" and m.match_type == MATCH_ENGLISH_NAME
        for m in r.mappings
    )


def test_korean_name_ripple() -> None:
    r = resolve_symbols(title="리플 가격 동향", body="", aliases=_universe())
    assert any(
        m.symbol == "KRW-XRP" and m.match_type == MATCH_KOREAN_NAME
        for m in r.mappings
    )


def test_btc_and_eth_mapping() -> None:
    r = resolve_symbols(
        title="BTC·ETH 시장 동향",
        body="",
        aliases=_universe(),
    )
    symbols = {m.symbol for m in r.mappings}
    assert "KRW-BTC" in symbols
    assert "KRW-ETH" in symbols


def test_multi_symbol_mapping() -> None:
    r = resolve_symbols(
        title="스팀(STEEM), 하이브(HIVE) 입출금 일시 중단",
        body="",
        aliases=_universe(),
    )
    symbols = {m.symbol for m in r.mappings}
    assert "KRW-STEEM" in symbols
    assert "KRW-HIVE" in symbols
    assert len(symbols) >= 2


def test_title_priority_over_body() -> None:
    r = resolve_symbols(
        title="XRP 공지",
        body="STEEM 는 본문에만 등장",
        aliases=_universe(),
    )
    by_sym = {m.symbol: m for m in r.mappings}
    assert by_sym["KRW-XRP"].matched_field == "TITLE"
    assert by_sym["KRW-STEEM"].matched_field == "BODY"


def test_body_mapping_only() -> None:
    r = resolve_symbols(
        title="서비스 안내",
        body="SOLANA 네트워크 점검",  # 짧은 SOL base body 단독 금지 → english/long만
        aliases=_universe(),
    )
    # Solana english name → body mapping 허용
    assert any(m.symbol == "KRW-SOL" for m in r.mappings)


def test_body_short_base_ticker_blocked() -> None:
    r = resolve_symbols(
        title="서비스 안내",
        body="SOL 네트워크 점검",
        aliases=_universe(),
    )
    # SOL(3글자) body-only base 매칭 금지
    assert not any(m.symbol == "KRW-SOL" for m in r.mappings)


def test_case_insensitive_ticker() -> None:
    r = resolve_symbols(title="btc rising", body="", aliases=_universe())
    assert any(m.symbol == "KRW-BTC" for m in r.mappings)


def test_token_boundary_no_substring() -> None:
    # XBTCY 같은 문자열 내부 BTC 부분매칭 금지
    r = resolve_symbols(title="XBT CY token", body="", aliases=_universe())
    # "BTC" as standalone token absent
    assert not any(m.symbol == "KRW-BTC" for m in r.mappings)


def test_short_ticker_false_positive_in_sentence() -> None:
    assert "ONE" in AMBIGUOUS_BASE_TICKERS
    assert "ME" in AMBIGUOUS_BASE_TICKERS
    assert "ID" in AMBIGUOUS_BASE_TICKERS
    assert "ON" in AMBIGUOUS_BASE_TICKERS

    r = resolve_symbols(
        title="One of the main ideas in the market",
        body="Contact me on ID portal",
        aliases=_universe(),
    )
    # base-only ONE/ME/ID/ON 자동 링크 금지
    assert not any(m.symbol in {"KRW-ONE", "KRW-ME"} for m in r.mappings)
    assert r.status in {STATUS_AMBIGUOUS, STATUS_UNMAPPED, "PARTIAL"}


def test_ambiguous_ticker_with_clear_name_still_maps_name() -> None:
    r = resolve_symbols(
        title="하모니(ONE) 거래지원 안내",
        body="",
        aliases=_universe(),
    )
    # 한글명으로 매핑 가능
    assert any(m.symbol == "KRW-ONE" for m in r.mappings)


def test_inactive_market_excluded_from_aliases() -> None:
    instruments = [
        InstrumentAlias("KRW-BTC", "BTC", "비트코인", "Bitcoin", is_active=True),
        InstrumentAlias("KRW-OLD", "OLD", "올드코인", "Oldcoin", is_active=False),
    ]
    aliases = build_alias_entries(instruments)
    assert all(a.symbol != "KRW-OLD" for a in aliases)


def test_unknown_symbol_unmapped() -> None:
    r = resolve_symbols(
        title="존재하지않는코인XYZ 상장?",
        body="",
        aliases=_universe(),
    )
    assert r.status == STATUS_UNMAPPED
    assert r.mappings == []


def test_idempotent_link_upsert() -> None:
    from stock_platform.news.repository import NewsRepository

    session = MagicMock()
    existing = SimpleNamespace(
        match_type=MATCH_EXACT_BASE_SYMBOL,
        relevance_score=Decimal("0.95"),
    )
    session.scalar.return_value = existing
    repo = NewsRepository(session)
    action = repo.upsert_symbol_mapping_link(
        article_id=1,
        market_code="UPBIT",
        symbol="KRW-XRP",
        match_type=MATCH_EXACT_BASE_SYMBOL,
        relevance_score=Decimal("0.95"),
    )
    assert action == "duplicate"


def test_placeholder_symbol_rejected() -> None:
    from stock_platform.news.repository import NewsRepository

    repo = NewsRepository(MagicMock())
    action = repo.upsert_symbol_mapping_link(
        article_id=1,
        market_code="UPBIT",
        symbol="_NOTICE_",
        match_type="PROVIDER",
        relevance_score=Decimal("1.0"),
    )
    assert action == "duplicate"


def test_edited_article_prefers_higher_confidence_update() -> None:
    from stock_platform.news.repository import NewsRepository

    session = MagicMock()
    existing = SimpleNamespace(
        match_type="BODY_ONLY_ALIAS",
        relevance_score=Decimal("0.80"),
    )
    session.scalar.return_value = existing
    repo = NewsRepository(session)
    action = repo.upsert_symbol_mapping_link(
        article_id=1,
        market_code="UPBIT",
        symbol="KRW-BTC",
        match_type=MATCH_EXACT_BASE_SYMBOL,
        relevance_score=Decimal("0.95"),
    )
    assert action == "updated"
    assert existing.match_type == MATCH_EXACT_BASE_SYMBOL


def test_upbit_notice_and_crypto_news_sources_supported() -> None:
    from stock_platform.news.collector_constants import (
        SOURCE_CODE_CRYPTO_NEWS,
        SOURCE_CODE_UPBIT_NOTICE,
    )

    assert SOURCE_CODE_UPBIT_NOTICE == "UPBIT_NOTICE"
    assert SOURCE_CODE_CRYPTO_NEWS == "CRYPTO_NEWS"


def test_no_ai_or_scanner_imports_in_n3_modules() -> None:
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "stock_platform" / "news"
    files = [
        root / "symbol_resolver.py",
        root / "symbol_mapper.py",
        root / "symbol_universe.py",
        root / "symbol_mapping_constants.py",
    ]
    banned = {
        "stock_platform.ai.ollama_client",
        "stock_platform.operation.upbit_opportunity_scanner",
        "stock_platform.operation.upbit_opportunity_shadow",
        "stock_platform.order",
    }
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for b in banned:
                    assert not node.module.startswith(b), path.name


def test_scanner_modules_do_not_import_symbol_mapper() -> None:
    import ast
    from pathlib import Path

    root = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "stock_platform"
        / "operation"
    )
    paths = [
        root / "upbit_opportunity_scanner" / "scheduler.py",
        root / "upbit_opportunity_shadow" / "evaluator_scheduler.py",
    ]
    for path in paths:
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "symbol_mapper" not in node.module
                assert "symbol_resolver" not in node.module


def test_resolver_version_constant() -> None:
    assert RESOLVER_VERSION == "upbit_symbol_resolver_v1"


def test_map_article_backfill_stats_shape() -> None:
    from stock_platform.news.symbol_mapper import MappingRunStats

    stats = MappingRunStats()
    assert stats.articles_scanned == 0
    assert stats.resolver_version == RESOLVER_VERSION
