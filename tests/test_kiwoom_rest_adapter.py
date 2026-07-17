"""KiwoomBrokerAdapter 생성자 시그니처 변경으로 보류.

현재 어댑터는 keyword-only config/rest_client를 받는다.
STEP36/38에서 HTTP mock 기반 테스트를 재작성한다.
"""

import pytest

pytestmark = pytest.mark.skip(
    reason=(
        "KiwoomBrokerAdapter constructor changed; "
        "rewrite with keyword args / RestClient mock"
    )
)


def test_submit_mock_order() -> None:
    assert False
