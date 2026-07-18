from decimal import Decimal

from stock_platform.ai.reproducibility import (
    build_context_hash,
    compare_analysis_results,
)


def test_build_context_hash_is_stable() -> None:
    contexts = {
        "005930": {
            "news": ["호실적"],
            "disclosures": [],
        }
    }
    left = build_context_hash(
        source_candidate_run_id=10,
        model_name="qwen3.5:4b",
        prompt_version="ranker-v2",
        requested_limit=5,
        contexts=contexts,
    )
    right = build_context_hash(
        source_candidate_run_id=10,
        model_name="qwen3.5:4b",
        prompt_version="ranker-v2",
        requested_limit=5,
        contexts=contexts,
    )
    assert left == right
    assert len(left) == 64


def test_build_context_hash_changes_with_input() -> None:
    base = build_context_hash(
        source_candidate_run_id=10,
        model_name="qwen3.5:4b",
        prompt_version="ranker-v2",
        requested_limit=5,
        contexts={"005930": {"news": ["A"]}},
    )
    changed = build_context_hash(
        source_candidate_run_id=10,
        model_name="qwen3.5:4b",
        prompt_version="ranker-v2",
        requested_limit=5,
        contexts={"005930": {"news": ["B"]}},
    )
    assert base != changed


def test_compare_analysis_results_detects_diff() -> None:
    comparison = compare_analysis_results(
        baseline=[
            {
                "rank": 1,
                "symbol": "005930",
                "ai_score": Decimal("80"),
                "action": "REVIEW",
            },
            {
                "rank": 2,
                "symbol": "000660",
                "ai_score": Decimal("70"),
                "action": "WATCH",
            },
        ],
        reproduced=[
            {
                "rank": 1,
                "symbol": "000660",
                "ai_score": Decimal("75"),
                "action": "REVIEW",
            },
            {
                "rank": 2,
                "symbol": "035420",
                "ai_score": Decimal("68"),
                "action": "WATCH",
            },
        ],
    )
    assert comparison["identical"] is False
    assert comparison["removed_symbols"] == ["005930"]
    assert comparison["added_symbols"] == ["035420"]
    assert comparison["score_changed"][0]["symbol"] == "000660"
    assert comparison["rank_changed"][0]["symbol"] == "000660"
    assert comparison["action_changed"][0]["symbol"] == "000660"


def test_compare_analysis_results_identical() -> None:
    rows = [
        {
            "rank": 1,
            "symbol": "005930",
            "ai_score": "88.00",
            "action": "REVIEW",
        }
    ]
    comparison = compare_analysis_results(
        baseline=rows,
        reproduced=rows,
    )
    assert comparison["identical"] is True
