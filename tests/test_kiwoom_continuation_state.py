from stock_platform.collectors.kiwoom.pagination import (
    ContinuationState,
)


def test_continuation_from_response_requires_next_key() -> None:
    state = ContinuationState.from_response(
        has_more=True,
        next_key="  abc  ",
    )
    assert state.has_more is True
    assert state.next_key == "abc"
    assert state.continue_yn == "Y"
    assert state.as_request_headers() == {
        "cont-yn": "Y",
        "next-key": "abc",
    }


def test_continuation_without_next_key_stops() -> None:
    state = ContinuationState.from_response(
        has_more=True,
        next_key=None,
    )
    assert state.has_more is False
    assert state.continue_yn is None
