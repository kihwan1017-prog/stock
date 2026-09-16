"""Superseded by test_live_smoke_uba_ownership_db_rollback.py

PaperAccount 치환 우회는 금지. UBA-only 실 DB rollback 은 신규 파일 사용.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_legacy_paper_substitute_path_removed() -> None:
    pytest.skip(
        "replaced by tests/test_live_smoke_uba_ownership_db_rollback.py "
        "(UBA-only, no PaperAccount substitute)"
    )
