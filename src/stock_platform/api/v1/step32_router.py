"""Deprecated STEP32 compatibility API — P0 언마운트.

`api/router.py`에서 등록하지 않는다. 무인증 paper fill 우회 경로였으며
런타임에 노출되면 안 된다. 본선은 paper-accounts / risk / dashboard API를 사용한다.

이 파일은 tombstone으로만 유지한다. import해도 라우터는 마운트되지 않는다.
"""

from __future__ import annotations

from fastapi import APIRouter

# 의도적으로 엔드포인트 없음 — 과거 경로 재등록 방지
router = APIRouter(
    prefix="/api/v1",
    tags=["step32-deprecated"],
    deprecated=True,
)
