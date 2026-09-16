"""STEP N10 — coverage decision focused tests."""

from __future__ import annotations

from stock_platform.operation.upbit_news_combined_shadow.diagnostics import (
    MATCHED_COMPLETED_TARGET,
    NO_NEWS_COMPLETED_TARGET,
)
from stock_platform.operation.upbit_news_combined_shadow.pipeline_observation import (
    decide_topn_snapshot_recommendation,
)


def test_topn_recommended_only_when_abc() -> None:
    out = decide_topn_snapshot_recommendation(
        overlap_exists=True,
        pret0_eligible_exists=True,
        eligible_never_in_experiment=2,
        matched_symbols=0,
    )
    assert out["status"] == "RECOMMENDED"
    assert out["implement_now"] is False


def test_topn_observe_more_when_matched_growing() -> None:
    out = decide_topn_snapshot_recommendation(
        overlap_exists=True,
        pret0_eligible_exists=True,
        eligible_never_in_experiment=0,
        matched_symbols=1,
    )
    assert out["status"] == "OBSERVE_MORE"


def test_topn_not_required_without_overlap() -> None:
    out = decide_topn_snapshot_recommendation(
        overlap_exists=False,
        pret0_eligible_exists=False,
        eligible_never_in_experiment=0,
        matched_symbols=0,
    )
    assert out["status"] == "NOT_REQUIRED"


def test_milestone_thresholds_unchanged() -> None:
    assert MATCHED_COMPLETED_TARGET == 20
    assert NO_NEWS_COMPLETED_TARGET == 20
