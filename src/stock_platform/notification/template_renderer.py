"""안전한 {placeholder} 템플릿 렌더러 — Jinja/eval 금지."""

from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_DASH_ONLY_VALUE_RE = re.compile(r"^[^:\n]+:\s*-\s*$")


def extract_placeholders(template: str) -> list[str]:
    return list(dict.fromkeys(_PLACEHOLDER_RE.findall(template or "")))


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def render_template(
    template: str,
    variables: dict[str, Any],
    *,
    missing_default: str = "-",
) -> tuple[str, list[str]]:
    """허용 변수만 치환. 누락 시 missing_default, 전체 실패하지 않음."""

    missing: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables or _is_blank(variables[key]):
            missing.append(key)
            return missing_default
        return str(variables[key])

    rendered = _PLACEHOLDER_RE.sub(_replace, template or "")
    uniq = list(dict.fromkeys(missing))
    return rendered, uniq


def render_template_with_optional_lines(
    template: str,
    variables: dict[str, Any],
    *,
    required_fields: frozenset[str] | set[str] | None = None,
    missing_default: str = "-",
) -> tuple[str, list[str], list[str]]:
    """줄 단위 렌더.

    - 줄의 placeholder가 전부 비어 있으면 해당 줄 자체를 숨김
    - 렌더 결과가 '라벨: -' 형태면 숨김
    - required_fields 누락 목록을 별도 반환
    """

    required = set(required_fields or ())
    missing_all: list[str] = []
    required_missing: list[str] = []
    out_lines: list[str] = []

    for raw_line in (template or "").split("\n"):
        placeholders = extract_placeholders(raw_line)
        if not placeholders:
            out_lines.append(raw_line)
            continue

        line_blank = [
            key
            for key in placeholders
            if key not in variables or _is_blank(variables.get(key))
        ]
        if len(line_blank) == len(placeholders):
            missing_all.extend(line_blank)
            for key in line_blank:
                if key in required and key not in required_missing:
                    required_missing.append(key)
            continue

        rendered, miss = render_template(
            raw_line,
            variables,
            missing_default=missing_default,
        )
        missing_all.extend(miss)
        for key in miss:
            if key in required and key not in required_missing:
                required_missing.append(key)

        # 의미 없는 "-" 단독 값 줄 제거
        if _DASH_ONLY_VALUE_RE.match(rendered.strip()):
            continue
        # placeholder-only 줄이 비어 있으면 제거
        if not rendered.strip():
            continue
        out_lines.append(rendered)

    # 연속 빈 줄 압축
    compact: list[str] = []
    prev_blank = False
    for line in out_lines:
        is_blank = not line.strip()
        if is_blank and prev_blank:
            continue
        compact.append(line)
        prev_blank = is_blank

    body = "\n".join(compact).strip("\n")
    return body, list(dict.fromkeys(missing_all)), required_missing
