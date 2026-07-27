"""STEP 8-5-8 — Remaining-Req / Retry-After Header Parser."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Mapping

_REMAINING_PART = re.compile(
    r"(?P<key>[a-zA-Z_]+)\s*=\s*(?P<value>[^;]+)"
)


@dataclass(frozen=True, slots=True)
class UpbitRateLimitSnapshot:
    group: str | None
    remaining_minute: int | None
    remaining_second: int | None
    retry_after_seconds: float | None
    response_date: datetime | None
    parsed_at: datetime
    raw_remaining_masked: str | None
    parse_ok: bool
    parse_error: str | None = None


class UpbitRateLimitHeaderParser:
    """Upbit Remaining-Req / Retry-After / Date 파서."""

    def __init__(self, *, retry_after_max_seconds: float = 300.0) -> None:
        if retry_after_max_seconds <= 0:
            raise ValueError("retry_after_max_seconds must be > 0")
        self._retry_after_max = float(retry_after_max_seconds)

    def parse(
        self,
        headers: Mapping[str, str] | None,
        *,
        now: datetime | None = None,
    ) -> UpbitRateLimitSnapshot:
        parsed_at = now or datetime.now(timezone.utc)
        if parsed_at.tzinfo is None:
            parsed_at = parsed_at.replace(tzinfo=timezone.utc)

        if not headers:
            return UpbitRateLimitSnapshot(
                group=None,
                remaining_minute=None,
                remaining_second=None,
                retry_after_seconds=None,
                response_date=None,
                parsed_at=parsed_at,
                raw_remaining_masked=None,
                parse_ok=True,
            )

        # httpx Headers는 case-insensitive
        remaining_raw = self._get(headers, "Remaining-Req")
        retry_raw = self._get(headers, "Retry-After")
        date_raw = self._get(headers, "Date")

        group: str | None = None
        rem_min: int | None = None
        rem_sec: int | None = None
        parse_error: str | None = None
        parse_ok = True

        if remaining_raw:
            try:
                group, rem_min, rem_sec = self._parse_remaining(
                    remaining_raw
                )
            except ValueError as exc:
                parse_ok = False
                parse_error = str(exc)

        response_date = None
        if date_raw:
            try:
                response_date = parsedate_to_datetime(date_raw)
                if response_date.tzinfo is None:
                    response_date = response_date.replace(
                        tzinfo=timezone.utc
                    )
            except (TypeError, ValueError, IndexError):
                response_date = None

        retry_after = None
        if retry_raw:
            try:
                retry_after = self.parse_retry_after(
                    retry_raw,
                    response_date=response_date,
                    now=parsed_at,
                )
            except ValueError as exc:
                parse_ok = False
                parse_error = (
                    f"{parse_error}; {exc}" if parse_error else str(exc)
                )

        masked = None
        if remaining_raw:
            # Secret 없음 — 길이만 제한
            masked = remaining_raw[:120]

        return UpbitRateLimitSnapshot(
            group=group,
            remaining_minute=rem_min,
            remaining_second=rem_sec,
            retry_after_seconds=retry_after,
            response_date=response_date,
            parsed_at=parsed_at,
            raw_remaining_masked=masked,
            parse_ok=parse_ok,
            parse_error=parse_error,
        )

    def parse_retry_after(
        self,
        value: str,
        *,
        response_date: datetime | None = None,
        now: datetime | None = None,
    ) -> float:
        """초 단위 또는 HTTP-date → 대기 초. 상한 적용."""

        raw = (value or "").strip()
        if not raw:
            raise ValueError("empty Retry-After")

        # 정수/소수 초
        try:
            seconds = float(raw)
            if seconds < 0:
                seconds = 0.0
            return min(seconds, self._retry_after_max)
        except ValueError:
            pass

        try:
            target = parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError) as exc:
            raise ValueError(f"invalid Retry-After date: {raw[:40]}") from exc

        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)

        base = response_date or now or datetime.now(timezone.utc)
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)

        delta = (target - base).total_seconds()
        if delta < 0:
            delta = 0.0
        return min(delta, self._retry_after_max)

    @staticmethod
    def _parse_remaining(
        raw: str,
    ) -> tuple[str | None, int | None, int | None]:
        """
        예: group=default; min=1800; sec=29
        순서·공백에 과도하게 의존하지 않음.
        """

        parts = {
            m.group("key").strip().lower(): m.group("value").strip()
            for m in _REMAINING_PART.finditer(raw)
        }
        group = parts.get("group")
        rem_min = None
        rem_sec = None
        if "min" in parts:
            rem_min = int(parts["min"])
            if rem_min < 0:
                raise ValueError("remaining min negative")
        if "sec" in parts:
            rem_sec = int(parts["sec"])
            if rem_sec < 0:
                raise ValueError("remaining sec negative")
        return group, rem_min, rem_sec

    @staticmethod
    def _get(headers: Mapping[str, str], name: str) -> str | None:
        if hasattr(headers, "get"):
            # Case-insensitive fallback
            value = headers.get(name)
            if value is not None:
                return str(value)
            lower = {str(k).lower(): v for k, v in headers.items()}
            found = lower.get(name.lower())
            return str(found) if found is not None else None
        return None
