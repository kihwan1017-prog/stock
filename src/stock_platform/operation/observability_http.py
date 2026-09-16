"""관찰 HTTP와 critical mutation HTTP를 구분한다.

OBSERVABILITY FAILURE != TRADING SAFETY FAILURE.
urllib는 socket timeout을 TimeoutError로 던지며 URLError가 아니다.
"""

from __future__ import annotations

import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OBSERVABILITY_TIMEOUT = "OBSERVABILITY_TIMEOUT"
CRITICAL_MUTATION_TIMEOUT = "CRITICAL_MUTATION_TIMEOUT"
HTTP_OK = "HTTP_OK"
HTTP_ERROR = "HTTP_ERROR"
HTTP_UNAVAILABLE = "HTTP_UNAVAILABLE"

_TIMEOUT_TYPES = (TimeoutError, socket.timeout)


def is_timeout_exception(exc: BaseException) -> bool:
    """urllib/socket timeout 여부. URLError(reason=timeout)도 포함한다."""

    if isinstance(exc, _TIMEOUT_TYPES):
        return True
    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, _TIMEOUT_TYPES):
            return True
        text = str(reason or exc).lower()
        if "timed out" in text or "timeout" in text:
            return True
    text = str(exc).lower()
    return "timed out" in text or isinstance(exc, TimeoutError)


def classify_http_result(
    *,
    http_status: int,
    body: Any,
    kind: str,
) -> str:
    """kind=observability | critical_mutation | critical_read."""

    detail = ""
    if isinstance(body, dict):
        detail = str(body.get("detail") or "").lower()
    timed_out = http_status == 0 and "timeout" in detail
    if timed_out:
        if kind == "observability":
            return OBSERVABILITY_TIMEOUT
        return CRITICAL_MUTATION_TIMEOUT
    if 200 <= int(http_status) < 300:
        return HTTP_OK
    if http_status == 0:
        return HTTP_UNAVAILABLE
    return HTTP_ERROR


def observability_timeout_should_rollback() -> bool:
    """정보성 GET timeout만으로는 rollback하지 않는다."""

    return False


def request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 8.0,
) -> tuple[int, Any]:
    """TimeoutError를 예외로 올리지 않고 (0, {detail: timeout})로 반환한다."""

    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        import json

        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            parsed: Any = {}
            if raw:
                import json

                parsed = json.loads(raw)
            return int(resp.status), parsed
    except _TIMEOUT_TYPES:
        return 0, {"detail": "timeout"}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            import json

            parsed = json.loads(raw)
        except Exception:  # noqa: BLE001
            parsed = {"detail": raw[:400]}
        return int(exc.code), parsed
    except URLError as exc:
        if is_timeout_exception(exc):
            return 0, {"detail": "timeout"}
        return 0, {"detail": str(exc)}
