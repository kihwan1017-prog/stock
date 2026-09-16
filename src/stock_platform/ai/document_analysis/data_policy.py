"""STEP 11-6 — 문서 데이터 등급 → Provider 전송 정책."""

from __future__ import annotations

from typing import Any

from stock_platform.ai.document_analysis.constants import DATA_CLASSIFICATIONS

# classification → 허용 provider_code 집합
PROVIDER_POLICY: dict[str, frozenset[str]] = {
    "PUBLIC": frozenset(
        {"mock", "ollama", "openai", "claude", "gemini", "compatible"}
    ),
    "INTERNAL": frozenset({"mock", "ollama", "openai", "claude"}),
    "CONFIDENTIAL": frozenset({"mock", "ollama"}),
    "RESTRICTED": frozenset({"mock"}),
}


def classify_document(
    *,
    document_type: str,
    has_internal_notes: bool = False,
    has_user_memo: bool = False,
    forced: str | None = None,
) -> str:
    if forced and forced in DATA_CLASSIFICATIONS:
        return forced
    if has_internal_notes or has_user_memo:
        return "INTERNAL"
    # 공개 뉴스/공시 메타는 PUBLIC
    if document_type in {"NEWS", "DISCLOSURE"}:
        return "PUBLIC"
    return "INTERNAL"


def provider_allowed(
    *,
    classification: str,
    provider_code: str,
    execution_mode: str,
) -> dict[str, Any]:
    allowed = PROVIDER_POLICY.get(classification, frozenset({"mock"}))
    code = (provider_code or "mock").lower()
    # MOCK 모드는 mock만
    if execution_mode == "MOCK":
        ok = code == "mock"
        return {
            "allowed": ok,
            "classification": classification,
            "provider_code": code,
            "reason": None if ok else "MOCK_MODE_REQUIRES_MOCK",
        }
    if execution_mode == "DRY_RUN":
        return {
            "allowed": True,
            "classification": classification,
            "provider_code": code,
            "reason": None,
        }
    # EXTERNAL
    if code not in allowed:
        return {
            "allowed": False,
            "classification": classification,
            "provider_code": code,
            "reason": "DATA_POLICY_BLOCKED",
            "allowed_providers": sorted(allowed),
        }
    # Ollama는 로컬로 취급 (외부 SaaS와 분리)
    return {
        "allowed": True,
        "classification": classification,
        "provider_code": code,
        "is_local_ollama": code == "ollama",
        "reason": None,
    }
