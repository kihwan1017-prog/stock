"""공통 API 에러 코드 카탈로그.

HTTP 상태와 내부 코드를 분리한다.
클라이언트가 분기할 때는 code 를 우선하고, http 는 전송 계층 힌트다.
"""

from __future__ import annotations

# 클라이언트/문서 공유용. HTTP_* 남발 대신 Domain 코드를 우선한다.
ERROR_CATALOG: dict[str, dict[str, str]] = {
    "VALIDATION_ERROR": {
        "http": "422",
        "message": "요청 본문/파라미터가 유효하지 않습니다.",
    },
    "UNAUTHORIZED": {
        "http": "401",
        "message": "인증이 필요합니다.",
    },
    "FORBIDDEN": {
        "http": "403",
        "message": "권한이 없습니다.",
    },
    "PERMISSION_DENIED": {
        "http": "403",
        "message": "권한이 없습니다.",
    },
    "NOT_FOUND": {
        "http": "404",
        "message": "리소스를 찾을 수 없습니다.",
    },
    "CONFLICT": {
        "http": "409",
        "message": "상태 충돌(Kill Switch/중복 등).",
    },
    "RATE_LIMITED": {
        "http": "429",
        "message": "요청이 너무 많습니다.",
    },
    "DOMAIN_ERROR": {
        "http": "400",
        "message": "도메인 규칙 위반.",
    },
    "EXTERNAL_API_ERROR": {
        "http": "502",
        "message": "외부 API 연동 오류.",
    },
    "BROKER_ERROR": {
        "http": "502",
        "message": "증권사/브로커 연동 오류.",
    },
    "KIWOOM_API_ERROR": {
        "http": "502",
        "message": "키움증권 API 연동 오류.",
    },
    "UPBIT_API_ERROR": {
        "http": "502",
        "message": "업비트 API 연동 오류.",
    },
    "DART_API_ERROR": {
        "http": "502",
        "message": "DART 공시 API 연동 오류.",
    },
    "OLLAMA_API_ERROR": {
        "http": "502",
        "message": "Ollama LLM API 연동 오류.",
    },
    "NAVER_API_ERROR": {
        "http": "502",
        "message": "네이버 뉴스 API 연동 오류.",
    },
    "INTERNAL_ERROR": {
        "http": "500",
        "message": "내부 서버 오류.",
    },
}


def error_envelope(
    *,
    code: str,
    message: str,
    request_id: str | None = None,
    detail: dict | list | str | None = None,
) -> dict:
    """성공/실패 공통 Envelope의 error 부분."""

    body: dict = {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if request_id:
        body["request_id"] = request_id
    if detail is not None:
        body["error"]["detail"] = detail
    return body


def success_envelope(
    data: object,
    *,
    request_id: str | None = None,
    meta: dict | None = None,
) -> dict:
    """성공 응답 Envelope (페이징 meta 포함 가능)."""

    body: dict = {"ok": True, "data": data}
    if request_id:
        body["request_id"] = request_id
    if meta:
        body["meta"] = meta
    return body


def resolve_error_code(code: str, *, fallback: str = "DOMAIN_ERROR") -> str:
    """알 수 없는 코드는 fallback 으로 정규화한다."""

    if code in ERROR_CATALOG:
        return code
    return fallback
