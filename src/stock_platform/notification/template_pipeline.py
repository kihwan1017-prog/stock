"""Notification Template Pipeline — normalize → render → channel format.

정형 이벤트는 LLM을 호출하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from stock_platform.notification.builtin_templates import builtin_template_for
from stock_platform.notification.masking import mask_sensitive
from stock_platform.notification.normalizer import (
    event_category,
    normalize_variables,
    required_fields_for,
)
from stock_platform.notification.template_renderer import (
    extract_placeholders,
    render_template,
    render_template_with_optional_lines,
)

# AI HOLD 무변경 등 spam 억제용 in-process dedupe
_state_dedupe: dict[str, float] = {}
_STATE_TTL_SECONDS = 900.0


@dataclass(slots=True)
class RenderedNotification:
    event_type: str
    category: str
    severity: str
    locale: str
    title: str
    body: str
    short_body: str
    variables: dict[str, Any]
    original_payload: dict[str, Any]
    template_id: int | None = None
    template_version: int | None = None
    missing_variables: list[str] = field(default_factory=list)
    required_missing: list[str] = field(default_factory=list)
    suppressed: bool = False
    suppress_reason: str | None = None
    source: str = "builtin"  # builtin | db | fallback
    diagnostic_code: str | None = None


def should_suppress_state_event(
    *,
    event_type: str,
    variables: dict[str, Any],
    detail: dict[str, Any],
) -> tuple[bool, str | None]:
    """상태 전이 없는 반복 알림 억제."""

    import time

    et = event_type.upper()
    if str(detail.get("kind") or "").upper() in {"TICK", "HEARTBEAT"}:
        return True, "TICK_OR_HEARTBEAT"

    if et == "AI_GATE_RECOMMENDATION_CHANGED":
        prev = str(variables.get("previous_recommendation_ko") or "")
        new = str(variables.get("new_recommendation_ko") or "")
        if prev == new and prev not in {"-", ""}:
            return True, "AI_RECOMMENDATION_UNCHANGED"
        key = (
            f"AI|{variables.get('uba_id')}|{variables.get('symbol')}|"
            f"{prev}->{new}"
        )
        now = time.time()
        last = _state_dedupe.get(key)
        if last and now - last < 30:
            return True, "AI_CHANGE_DEDUPE_30S"
        _state_dedupe[key] = now
        return False, None

    if et in {"UPBIT_SCANNER_CANDIDATE", "UPBIT_SCANNER_SHADOW_RESULT"}:
        nested = detail.get("candidate")
        nested_rec = (
            nested.get("recommendation")
            if isinstance(nested, dict)
            else None
        )
        rec = str(
            detail.get("ai_recommendation")
            or detail.get("recommendation")
            or nested_rec
            or ""
        ).upper()
        # summary(candidates[])는 HOLD-only여도 운영 가시성 유지
        if rec == "HOLD" and not detail.get("candidates"):
            key = (
                f"SCAN_HOLD|{variables.get('symbol')}|"
                f"{variables.get('uba_id')}"
            )
            now = time.time()
            last = _state_dedupe.get(key)
            if last and now - last < _STATE_TTL_SECONDS:
                return True, "SCANNER_HOLD_SUPPRESS"
            _state_dedupe[key] = now
    return False, None


def _fallback_body(event_type: str, missing: list[str]) -> str:
    return (
        f"⚠️ 자동매매 이벤트\n"
        f"유형: {str(event_type).upper()}\n"
        f"상세 정보 일부를 불러오지 못했습니다.\n"
        f"누락: {', '.join(missing) if missing else 'unknown'}"
    )


def render_notification(
    *,
    event_type: str,
    title: str,
    message: str,
    detail: dict[str, Any] | None,
    channel: str = "TELEGRAM",
    locale: str = "ko-KR",
    db_template: dict[str, Any] | None = None,
) -> RenderedNotification:
    """DB template 우선, 없으면 builtin. LLM 호출 없음."""

    payload = mask_sensitive(dict(detail or {}))
    variables = normalize_variables(
        event_type=event_type,
        title=title,
        message=message,
        detail=payload,
    )
    suppressed, reason = should_suppress_state_event(
        event_type=event_type,
        variables=variables,
        detail=payload,
    )
    if suppressed:
        return RenderedNotification(
            event_type=str(event_type).upper(),
            category=event_category(event_type),
            severity="INFO",
            locale=locale,
            title=title,
            body=message,
            short_body=message,
            variables=variables,
            original_payload=payload,
            suppressed=True,
            suppress_reason=reason,
        )

    source = "db"
    if db_template and db_template.get("enabled", True):
        title_tpl = str(db_template.get("title_template") or "")
        body_tpl = str(db_template.get("body_template") or "")
        short_tpl = str(
            db_template.get("short_body_template") or body_tpl
        )
        severity = str(db_template.get("severity") or "INFO")
        template_id = db_template.get("message_template_id") or db_template.get(
            "template_id"
        )
        template_version = db_template.get("version")
        category = str(
            db_template.get("category") or event_category(event_type)
        )
    else:
        source = "builtin"
        builtin = builtin_template_for(event_type)
        title_tpl = str(builtin["title_template"])
        body_tpl = str(builtin["body_template"])
        short_tpl = str(builtin.get("short_body_template") or body_tpl)
        severity = str(builtin.get("severity") or "INFO")
        template_id = None
        template_version = 1
        category = str(builtin.get("category") or event_category(event_type))

    required = required_fields_for(event_type)
    use_body = short_tpl if channel.upper() == "TOSS" else body_tpl
    rendered_title, miss_t = render_template(title_tpl, variables)
    rendered_body, miss_b, required_missing = render_template_with_optional_lines(
        use_body,
        variables,
        required_fields=required,
    )
    short_body, miss_s, _ = render_template_with_optional_lines(
        short_tpl,
        variables,
        required_fields=required,
    )
    missing = list(dict.fromkeys([*miss_t, *miss_b, *miss_s]))

    diagnostic = None
    if required_missing:
        diagnostic = "TEMPLATE_REQUIRED_FIELD_MISSING"
        source = "fallback"
        rendered_body = _fallback_body(event_type, required_missing)
        short_body = rendered_body
        # title은 템플릿 유지하되 비어 있으면 안전 타이틀
        if not rendered_title or rendered_title.strip() in {"-", ""}:
            rendered_title = f"⚠️ {str(event_type).upper()}"

    return RenderedNotification(
        event_type=str(event_type).upper(),
        category=category,
        severity=severity,
        locale=locale,
        title=rendered_title,
        body=rendered_body,
        short_body=short_body,
        variables=variables,
        original_payload=payload,
        template_id=int(template_id) if template_id is not None else None,
        template_version=int(template_version)
        if template_version is not None
        else None,
        missing_variables=missing,
        required_missing=required_missing,
        source=source,
        diagnostic_code=diagnostic,
    )


def preview_template(
    *,
    title_template: str,
    body_template: str,
    event_type: str = "ORDER_FILLED",
    sample_detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Admin preview — arbitrary code execution 없음."""

    sample = sample_detail or {
        "broker_code": "UPBIT",
        "symbol": "KRW-XRP",
        "side": "BUY",
        "amount_krw": 10000,
        "avg_price": 1605,
        "filled_qty": 6.23,
        "strategy_name": "전체시장 포트폴리오",
        "position_status": "OPEN",
        "previous_recommendation": "HOLD",
        "new_recommendation": "ALLOW",
        "confidence": 0.95,
    }
    rendered = render_notification(
        event_type=event_type,
        title="",
        message="",
        detail=sample,
        channel="TELEGRAM",
        db_template={
            "enabled": True,
            "title_template": title_template,
            "body_template": body_template,
            "short_body_template": body_template,
            "severity": "INFO",
        },
    )
    return {
        "title": rendered.title,
        "body": rendered.body,
        "variables": rendered.variables,
        "placeholders": extract_placeholders(
            f"{title_template}\n{body_template}"
        ),
        "missing_variables": rendered.missing_variables,
        "required_missing": rendered.required_missing,
        "diagnostic_code": rendered.diagnostic_code,
        "original_payload": mask_sensitive(sample),
    }
