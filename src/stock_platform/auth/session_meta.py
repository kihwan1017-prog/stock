"""User-Agent / IP 세션 메타 파싱 — STEP73 (외부 라이브러리 없이)."""

from __future__ import annotations

from fastapi import Request

from stock_platform.common.rate_limit import client_ip


def parse_user_agent(user_agent: str | None) -> dict[str, str | None]:
    ua = (user_agent or "").strip()
    if not ua:
        return {
            "device_name": "Unknown device",
            "browser_name": None,
            "operating_system": None,
            "user_agent": None,
        }

    browser = "Other"
    lower = ua.lower()
    if "edg/" in lower:
        browser = "Edge"
    elif "chrome/" in lower and "chromium" not in lower:
        browser = "Chrome"
    elif "firefox/" in lower:
        browser = "Firefox"
    elif "safari/" in lower and "chrome/" not in lower:
        browser = "Safari"

    os_name = "Other"
    if "windows" in lower:
        os_name = "Windows"
    elif "android" in lower:
        os_name = "Android"
    elif "iphone" in lower or "ipad" in lower:
        os_name = "iOS"
    elif "mac os" in lower or "macintosh" in lower:
        os_name = "macOS"
    elif "linux" in lower:
        os_name = "Linux"

    device = f"{os_name} · {browser}"
    return {
        "device_name": device[:100],
        "browser_name": browser,
        "operating_system": os_name,
        "user_agent": ua[:400],
    }


def session_meta_from_request(request: Request) -> dict[str, str | None]:
    ua = request.headers.get("user-agent")
    meta = parse_user_agent(ua)
    meta["ip_address"] = client_ip(request)
    return meta
