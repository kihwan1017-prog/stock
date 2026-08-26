"""UPBIT execution outage / restore epoch (process-local).

Runtime·Feed outage 구간과 복구 시각을 기록해
pre/during-outage WAITING이 복구 직후 REAL BUY로 흘러가지 않게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@dataclass
class _EpochState:
    outage_started_at: datetime | None = None
    restored_at: datetime | None = None
    last_outage_reason: str | None = None
    last_restore_actor: str | None = None
    outage_active: bool = False
    history: list[dict[str, Any]] = field(default_factory=list)


class UpbitExecutionRestoreEpoch:
    """프로세스 단위 SoT — DB 스키마 변경 없음."""

    def __init__(self) -> None:
        # mark_* → snapshot 중첩 호출용 (비재진입 Lock이면 데드락)
        self._lock = RLock()
        self._state = _EpochState()
        # 백엔드 restart 직후 mark_restored 전이라도 기동 이전 WAITING 차단
        self._process_started_at = _now()

    def mark_outage(self, reason: str) -> dict[str, Any]:
        """스택/ARM 장애 시작. 이미 outage면 started_at 유지."""

        now = _now()
        with self._lock:
            if not self._state.outage_active:
                self._state.outage_started_at = now
                self._state.outage_active = True
                self._state.last_outage_reason = (reason or "")[:200]
                self._state.history.append(
                    {
                        "event": "OUTAGE_START",
                        "at": now.isoformat(),
                        "reason": self._state.last_outage_reason,
                    }
                )
                # 히스토리 상한
                self._state.history = self._state.history[-20:]
            return self.snapshot()

    def mark_restored(self, *, actor: str | None = None) -> dict[str, Any]:
        """공식 stack restore 성공 시각. WAITING 재검증 기준점."""

        now = _now()
        with self._lock:
            self._state.restored_at = now
            self._state.outage_active = False
            self._state.last_restore_actor = (actor or "")[:120] or None
            self._state.history.append(
                {
                    "event": "RESTORED",
                    "at": now.isoformat(),
                    "actor": self._state.last_restore_actor,
                }
            )
            self._state.history = self._state.history[-20:]
            return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "outage_active": bool(self._state.outage_active),
                "outage_started_at": (
                    self._state.outage_started_at.isoformat()
                    if self._state.outage_started_at
                    else None
                ),
                "restored_at": (
                    self._state.restored_at.isoformat()
                    if self._state.restored_at
                    else None
                ),
                "last_outage_reason": self._state.last_outage_reason,
                "last_restore_actor": self._state.last_restore_actor,
                "process_started_at": self._process_started_at.isoformat(),
            }

    def is_pre_or_during_outage_waiting(
        self,
        waiting_updated_at: datetime | None,
        *,
        now: datetime | None = None,
    ) -> bool:
        """WAITING이 outage 이전·도중·복구 이전이면 True.

        - outage_active: WAITING BUY 금지
        - restored_at 이전(포함) updated_at: 복구 직후 재검증 전 금지
        - restored_at 이후 신규된 WAITING만 통과 가능
        """

        _ = now
        waiting = _aware(waiting_updated_at)
        with self._lock:
            if self._state.outage_active:
                return True
            restored = self._state.restored_at
            # restore 미기록(콜드스타트)이면 프로세스 기동 시각을 기준점으로 사용
            cutoff = restored if restored is not None else self._process_started_at
            if waiting is None:
                # cutoff 이력이 있는데 슬롯 시각 없음 → fail-closed (BUY 경로)
                return restored is not None
            return waiting <= cutoff


upbit_execution_restore_epoch = UpbitExecutionRestoreEpoch()
