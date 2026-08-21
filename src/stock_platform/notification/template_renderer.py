"""안전한 {placeholder} 템플릿 렌더러 — Jinja/eval 금지."""

from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def extract_placeholders(template: str) -> list[str]:
    return list(dict.fromkeys(_PLACEHOLDER_RE.findall(template or "")))


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
        if key not in variables or variables[key] is None or variables[key] == "":
            missing.append(key)
            return missing_default
        return str(variables[key])

    rendered = _PLACEHOLDER_RE.sub(_replace, template or "")
    # 중복 제거 유지 순서
    uniq = list(dict.fromkeys(missing))
    return rendered, uniq
