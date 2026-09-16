"""Stale ACTIVE snapshot binding — 승인형 RETIRE.

기존 `retire_orphan`은 ORPHAN/REBIND_PENDING/INVALID 만 허용한다.
ACTIVE stale 잔존은 별도 안전 게이트 + 승인 phrase 로만 RETIRE 한다.
DB 직접 UPDATE / hard delete 금지. UBA1380 / snapshot 176 절대 보호.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from stock_platform.broker.account_models import BrokerAccountSnapshotEntity
from stock_platform.broker.snapshot_constants import BrokerSnapshotStatus
from stock_platform.common.settings import get_settings
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.outbox_entities import OrderOutbox
from stock_platform.order.outbox_models import OutboxStatus
from stock_platform.trading.account_models import UserBrokerAccount

APPROVAL_PHRASE = "RETIRE STALE SNAPSHOT BINDINGS"
RETIRE_REASON_CODE = "STALE_UNUSED_BINDING_RETIRED"
AUDIT_EVENT = "STALE_SNAPSHOT_BINDING_RETIRED"

# 현재 운영 ops 스냅샷 — 진단·RETIRE 대상에서 항상 제외
PROTECTED_SNAPSHOT_IDS: frozenset[int] = frozenset({176})
PROTECTED_UBA_IDS: frozenset[int] = frozenset({1380})

CLASS_SAFE = "SAFE_STALE_HISTORY"
CLASS_REFRESH = "SNAPSHOT_REFRESH_REQUIRED"
CLASS_ACTIVE = "ACTIVE_BINDING_REQUIRED"
CLASS_ORPHAN = "ORPHANED_BINDING"
CLASS_UNKNOWN = "UNKNOWN"
CLASS_PROTECTED = "PROTECTED_OPS_SNAPSHOT"

# 브로커 제출·체결 진행 중으로 보는 주문 상태 (CREATED 잔존은 제외)
_IN_FLIGHT_ORDER_STATUSES = frozenset(
    {
        "SUBMITTED",
        "ACCEPTED",
        "PARTIAL",
        "PARTIALLY_FILLED",
        "OPEN",
        "WORKING",
        "PENDING_SUBMIT",
        "SENDING",
    }
)

# Outbox 가 아직 처리 중이면 binding 소비자로 본다
_ACTIVE_OUTBOX_STATUSES = frozenset(
    {
        OutboxStatus.PENDING.value,
        OutboxStatus.PROCESSING.value,
        OutboxStatus.AMBIGUOUS.value,
    }
)


class StaleSnapshotBindingRetireError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        blockers: list[str] | None = None,
        http_status: int = 409,
        mutation: int = 0,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.blockers = list(blockers or [code])
        self.http_status = int(http_status)
        self.mutation = int(mutation)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class SnapshotTriageItem:
    snapshot_id: int
    classification: str
    current_status: str | None
    stale_age_seconds: float | None
    owner_uba: int | None
    broker_code: str | None
    generation: int | None
    consumer_count: int
    runtime_refs: int
    order_refs_inflight: int
    outbox_refs_active: int
    newer_snapshot: bool
    retire_allowed: bool
    block_reason: str | None
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "classification": self.classification,
            "current_status": self.current_status,
            "stale_age_seconds": self.stale_age_seconds,
            "owner_uba": self.owner_uba,
            "broker_code": self.broker_code,
            "generation": self.generation,
            "consumer_count": self.consumer_count,
            "runtime_refs": self.runtime_refs,
            "order_refs_inflight": self.order_refs_inflight,
            "outbox_refs_active": self.outbox_refs_active,
            "newer_snapshot": self.newer_snapshot,
            "retire_allowed": self.retire_allowed,
            "block_reason": self.block_reason,
            "evidence": dict(self.evidence),
        }


@dataclass
class StaleSnapshotRetirePreview:
    items: list[SnapshotTriageItem]
    allowlist: list[int]
    fingerprint: str | None
    approval_phrase: str = APPROVAL_PHRASE
    max_age_seconds: int = 3600
    mutation: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "items": [item.as_dict() for item in self.items],
            "allowlist": list(self.allowlist),
            "fingerprint": self.fingerprint,
            "approval_phrase_required": self.approval_phrase,
            "max_age_seconds": self.max_age_seconds,
            "retire_allowed_count": len(self.allowlist),
            "mutation": self.mutation,
        }


class StaleSnapshotBindingRetireService:
    """SAFE_STALE_HISTORY ACTIVE snapshot 만 승인형 RETIRE."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def preview(self, snapshot_ids: list[int]) -> StaleSnapshotRetirePreview:
        max_age = int(get_settings().settlement_price_max_age_seconds)
        items: list[SnapshotTriageItem] = []
        for sid in sorted({int(x) for x in snapshot_ids}):
            items.append(self._triage_one(sid, max_age_seconds=max_age))

        allowlist = [
            int(item.snapshot_id)
            for item in items
            if item.retire_allowed and item.classification == CLASS_SAFE
        ]
        fp = None
        if allowlist:
            fp = _fingerprint(self._fingerprint_body(items, allowlist))
        return StaleSnapshotRetirePreview(
            items=items,
            allowlist=allowlist,
            fingerprint=fp,
            max_age_seconds=max_age,
        )

    def apply(
        self,
        *,
        snapshot_ids: list[int],
        approval_phrase: str,
        fingerprint: str,
        actor: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        phrase = (approval_phrase or "").strip()
        if phrase != APPROVAL_PHRASE:
            raise StaleSnapshotBindingRetireError(
                "INVALID_APPROVAL_PHRASE",
                f"approval_phrase must be exactly {APPROVAL_PHRASE!r}",
                blockers=["INVALID_APPROVAL_PHRASE"],
                http_status=400,
                mutation=0,
            )

        preview = self.preview(list(snapshot_ids))
        requested = sorted({int(x) for x in snapshot_ids})
        # 요청 ID 중 SAFE 만 실제 대상 — 보호/비허용은 스킵 결과로 보고
        expected_allow = [
            sid for sid in requested if sid in set(preview.allowlist)
        ]
        if not expected_allow:
            # 전부 이미 RETIRED 이면 idempotent 성공
            already = []
            for sid in requested:
                row = self._session.get(BrokerAccountSnapshotEntity, sid)
                if (
                    row is not None
                    and row.snapshot_status == BrokerSnapshotStatus.RETIRED.value
                ):
                    already.append(sid)
            if already and len(already) == len(requested):
                return {
                    "code": "ALREADY_RETIRED",
                    "mutation": 0,
                    "results": [
                        {
                            "snapshot_id": sid,
                            "code": "ALREADY_RETIRED",
                            "final_status": BrokerSnapshotStatus.RETIRED.value,
                        }
                        for sid in already
                    ],
                    "fingerprint": fingerprint,
                    "audit_events": 0,
                }
            raise StaleSnapshotBindingRetireError(
                "NO_RETIRE_CANDIDATES",
                "no SAFE_STALE_HISTORY snapshots in request allowlist",
                blockers=["NO_RETIRE_CANDIDATES"],
                mutation=0,
            )

        live_fp = _fingerprint(
            self._fingerprint_body(preview.items, expected_allow)
        )
        if (fingerprint or "").strip() != live_fp:
            raise StaleSnapshotBindingRetireError(
                "FINGERPRINT_MISMATCH",
                "preview fingerprint does not match current diagnosis",
                blockers=["FINGERPRINT_MISMATCH"],
                http_status=409,
                mutation=0,
            )

        reason_code = (reason or RETIRE_REASON_CODE).strip() or RETIRE_REASON_CODE
        results: list[dict[str, Any]] = []
        mutation = 0
        audit_payloads: list[dict[str, Any]] = []

        for sid in expected_allow:
            item = next(i for i in preview.items if i.snapshot_id == sid)
            row = self._session.get(BrokerAccountSnapshotEntity, sid)
            if row is None:
                results.append(
                    {
                        "snapshot_id": sid,
                        "code": "NOT_FOUND",
                        "final_status": None,
                    }
                )
                continue
            if row.snapshot_status == BrokerSnapshotStatus.RETIRED.value:
                results.append(
                    {
                        "snapshot_id": sid,
                        "code": "ALREADY_RETIRED",
                        "final_status": BrokerSnapshotStatus.RETIRED.value,
                        "idempotent": True,
                    }
                )
                continue
            if int(row.broker_account_snapshot_id) in PROTECTED_SNAPSHOT_IDS:
                raise StaleSnapshotBindingRetireError(
                    "PROTECTED_SNAPSHOT",
                    f"snapshot {sid} is protected",
                    mutation=0,
                )
            if (
                row.user_broker_account_id is not None
                and int(row.user_broker_account_id) in PROTECTED_UBA_IDS
            ):
                raise StaleSnapshotBindingRetireError(
                    "PROTECTED_UBA",
                    f"UBA {row.user_broker_account_id} is protected",
                    mutation=0,
                )
            if not item.retire_allowed or item.classification != CLASS_SAFE:
                raise StaleSnapshotBindingRetireError(
                    "RETIRE_NOT_ALLOWED",
                    f"snapshot {sid} no longer SAFE_STALE_HISTORY",
                    blockers=[item.block_reason or "RETIRE_NOT_ALLOWED"],
                    mutation=0,
                )

            previous = str(row.snapshot_status)
            meta = dict(row.raw_data or {})
            meta["_retire"] = {
                "actor": actor,
                "reason": reason_code[:200],
                "classification": CLASS_SAFE,
                "fingerprint": live_fp,
                "stale_age_seconds": item.stale_age_seconds,
                "retired_at": _utcnow().isoformat(),
                "event": AUDIT_EVENT,
            }
            row.raw_data = meta
            row.snapshot_status = BrokerSnapshotStatus.RETIRED.value
            self._session.flush()
            mutation += 1
            result = {
                "snapshot_id": sid,
                "code": "RETIRED",
                "previous_status": previous,
                "final_status": BrokerSnapshotStatus.RETIRED.value,
                "uba": item.owner_uba,
                "broker_code": item.broker_code,
                "generation": item.generation,
                "stale_age_seconds": item.stale_age_seconds,
                "classification": CLASS_SAFE,
                "reason": reason_code,
            }
            results.append(result)
            audit_payloads.append(
                {
                    "snapshot_id": sid,
                    "uba": item.owner_uba,
                    "broker": item.broker_code,
                    "generation": item.generation,
                    "previous_status": previous,
                    "final_status": BrokerSnapshotStatus.RETIRED.value,
                    "stale_age": item.stale_age_seconds,
                    "classification": CLASS_SAFE,
                    "evidence": item.evidence,
                    "actor": actor,
                    "reason": reason_code,
                    "fingerprint": live_fp,
                    "timestamp": _utcnow().isoformat(),
                }
            )

        return {
            "code": "STALE_SNAPSHOT_BINDINGS_RETIRED",
            "mutation": mutation,
            "results": results,
            "fingerprint": live_fp,
            "audit_event": AUDIT_EVENT,
            "audit_payloads": audit_payloads,
            "audit_events": len(audit_payloads),
        }

    def _fingerprint_body(
        self,
        items: list[SnapshotTriageItem],
        allowlist: list[int],
    ) -> dict[str, Any]:
        by_id = {int(i.snapshot_id): i for i in items}
        rows = []
        for sid in sorted(allowlist):
            item = by_id[sid]
            # age 는 매초 변하므로 fingerprint 에는 시각 원본만 넣는다
            snap_time = (item.evidence or {}).get("snapshot_time")
            rows.append(
                {
                    "snapshot_id": sid,
                    "uba": item.owner_uba,
                    "broker": item.broker_code,
                    "generation": item.generation,
                    "status": item.current_status,
                    "snapshot_time": snap_time,
                    "classification": item.classification,
                }
            )
        return {
            "allowlist": sorted(allowlist),
            "reason_code": RETIRE_REASON_CODE,
            "rows": rows,
        }

    def _triage_one(
        self, snapshot_id: int, *, max_age_seconds: int
    ) -> SnapshotTriageItem:
        row = self._session.get(BrokerAccountSnapshotEntity, int(snapshot_id))
        if row is None:
            return SnapshotTriageItem(
                snapshot_id=int(snapshot_id),
                classification=CLASS_UNKNOWN,
                current_status=None,
                stale_age_seconds=None,
                owner_uba=None,
                broker_code=None,
                generation=None,
                consumer_count=0,
                runtime_refs=0,
                order_refs_inflight=0,
                outbox_refs_active=0,
                newer_snapshot=False,
                retire_allowed=False,
                block_reason="SNAPSHOT_NOT_FOUND",
            )

        sid = int(row.broker_account_snapshot_id)
        uba_id = (
            int(row.user_broker_account_id)
            if row.user_broker_account_id is not None
            else None
        )
        status = str(row.snapshot_status)
        gen = int(row.snapshot_generation or 1)
        broker = str(row.broker_code)
        ref_time = _as_aware(row.snapshot_time) or _as_aware(row.synchronized_at)
        age = None
        if ref_time is not None:
            age = (_utcnow() - ref_time).total_seconds()

        evidence: dict[str, Any] = {
            "snapshot_id": sid,
            "uba": uba_id,
            "broker": broker,
            "generation": gen,
            "status": status,
            "snapshot_time": ref_time.isoformat() if ref_time else None,
            "synchronized_at": (
                _as_aware(row.synchronized_at).isoformat()
                if row.synchronized_at
                else None
            ),
            "created_at": (
                _as_aware(row.created_at).isoformat() if row.created_at else None
            ),
        }

        if sid in PROTECTED_SNAPSHOT_IDS or (
            uba_id is not None and uba_id in PROTECTED_UBA_IDS
        ):
            return SnapshotTriageItem(
                snapshot_id=sid,
                classification=CLASS_PROTECTED,
                current_status=status,
                stale_age_seconds=age,
                owner_uba=uba_id,
                broker_code=broker,
                generation=gen,
                consumer_count=0,
                runtime_refs=0,
                order_refs_inflight=0,
                outbox_refs_active=0,
                newer_snapshot=False,
                retire_allowed=False,
                block_reason="PROTECTED_OPS_SNAPSHOT",
                evidence={**evidence, "protected": True},
            )

        if status == BrokerSnapshotStatus.RETIRED.value:
            return SnapshotTriageItem(
                snapshot_id=sid,
                classification=CLASS_SAFE,
                current_status=status,
                stale_age_seconds=age,
                owner_uba=uba_id,
                broker_code=broker,
                generation=gen,
                consumer_count=0,
                runtime_refs=0,
                order_refs_inflight=0,
                outbox_refs_active=0,
                newer_snapshot=False,
                retire_allowed=False,
                block_reason="ALREADY_RETIRED",
                evidence={**evidence, "already_retired": True},
            )

        if status != BrokerSnapshotStatus.ACTIVE.value:
            return SnapshotTriageItem(
                snapshot_id=sid,
                classification=CLASS_UNKNOWN,
                current_status=status,
                stale_age_seconds=age,
                owner_uba=uba_id,
                broker_code=broker,
                generation=gen,
                consumer_count=0,
                runtime_refs=0,
                order_refs_inflight=0,
                outbox_refs_active=0,
                newer_snapshot=False,
                retire_allowed=False,
                block_reason=f"STATUS_NOT_ACTIVE:{status}",
                evidence=evidence,
            )

        if age is None or age <= float(max_age_seconds):
            return SnapshotTriageItem(
                snapshot_id=sid,
                classification=CLASS_UNKNOWN,
                current_status=status,
                stale_age_seconds=age,
                owner_uba=uba_id,
                broker_code=broker,
                generation=gen,
                consumer_count=0,
                runtime_refs=0,
                order_refs_inflight=0,
                outbox_refs_active=0,
                newer_snapshot=False,
                retire_allowed=False,
                block_reason="NOT_STALE",
                evidence={**evidence, "max_age_seconds": max_age_seconds},
            )

        if uba_id is None:
            return SnapshotTriageItem(
                snapshot_id=sid,
                classification=CLASS_ORPHAN,
                current_status=status,
                stale_age_seconds=age,
                owner_uba=None,
                broker_code=broker,
                generation=gen,
                consumer_count=0,
                runtime_refs=0,
                order_refs_inflight=0,
                outbox_refs_active=0,
                newer_snapshot=False,
                retire_allowed=False,
                block_reason="MISSING_UBA_BINDING",
                evidence=evidence,
            )

        uba = self._session.get(UserBrokerAccount, uba_id)
        if uba is None:
            return SnapshotTriageItem(
                snapshot_id=sid,
                classification=CLASS_ORPHAN,
                current_status=status,
                stale_age_seconds=age,
                owner_uba=uba_id,
                broker_code=broker,
                generation=gen,
                consumer_count=0,
                runtime_refs=0,
                order_refs_inflight=0,
                outbox_refs_active=0,
                newer_snapshot=False,
                retire_allowed=False,
                block_reason="UBA_ROW_MISSING",
                evidence=evidence,
            )

        link_active = self._count_active_strategy_links(uba_id)
        runtime_refs = self._count_runtime_refs(uba_id)
        inflight_orders = self._count_inflight_orders(uba_id)
        active_outbox = self._count_active_outbox(uba_id)
        newer = self._has_newer_snapshot(uba_id=uba_id, generation=gen, sid=sid)
        cred = self._credential_summary(uba_id)
        recovery = self._recovery_summary(uba_id)
        open_conflicts = self._count_open_recovery_conflicts(uba_id)
        consumer_count = link_active + runtime_refs

        evidence.update(
            {
                "uba_is_active": bool(uba.is_active),
                "uba_deleted": uba.deleted_at is not None,
                "connection_status": uba.connection_status,
                "live_order_enabled": bool(uba.live_order_enabled),
                "live_armed": bool(uba.live_armed),
                "account_alias": uba.account_alias,
                "active_strategy_links": link_active,
                "runtime_refs": runtime_refs,
                "inflight_orders": inflight_orders,
                "active_outbox": active_outbox,
                "newer_snapshot": newer,
                "credential": cred,
                "recovery": recovery,
                "open_recovery_conflicts": open_conflicts,
            }
        )

        blockers: list[str] = []
        if bool(uba.live_order_enabled) or bool(uba.live_armed):
            blockers.append("LIVE_OR_ARM_ON")
        if link_active > 0:
            blockers.append("ACTIVE_STRATEGY_LINK")
        if runtime_refs > 0:
            blockers.append("ACTIVE_RUNTIME")
        if inflight_orders > 0:
            blockers.append("INFLIGHT_ORDERS")
        if active_outbox > 0:
            blockers.append("ACTIVE_OUTBOX")
        if open_conflicts > 0:
            blockers.append("OPEN_RECOVERY_CONFLICT")

        if blockers:
            return SnapshotTriageItem(
                snapshot_id=sid,
                classification=CLASS_ACTIVE,
                current_status=status,
                stale_age_seconds=age,
                owner_uba=uba_id,
                broker_code=broker,
                generation=gen,
                consumer_count=consumer_count,
                runtime_refs=runtime_refs,
                order_refs_inflight=inflight_orders,
                outbox_refs_active=active_outbox,
                newer_snapshot=newer,
                retire_allowed=False,
                block_reason=",".join(blockers),
                evidence=evidence,
            )

        uba_abandoned = (not bool(uba.is_active)) or (uba.deleted_at is not None)
        disconnected = str(uba.connection_status or "").upper() == "DISCONNECTED"
        no_usable_cred = not bool(cred.get("has_active_verified"))
        recovery_cred_missing = str(recovery.get("last_error_summary") or "") in {
            "credential_missing",
            "CREDENTIAL_MISSING",
        }
        recovery_paused = bool(recovery.get("trading_paused"))

        # 운영 대상이나 자격증명 있어 갱신만 필요하면 REFRESH
        if (
            bool(uba.is_active)
            and uba.deleted_at is None
            and bool(cred.get("has_active_verified"))
            and disconnected is False
        ):
            return SnapshotTriageItem(
                snapshot_id=sid,
                classification=CLASS_REFRESH,
                current_status=status,
                stale_age_seconds=age,
                owner_uba=uba_id,
                broker_code=broker,
                generation=gen,
                consumer_count=consumer_count,
                runtime_refs=runtime_refs,
                order_refs_inflight=inflight_orders,
                outbox_refs_active=active_outbox,
                newer_snapshot=newer,
                retire_allowed=False,
                block_reason="SNAPSHOT_REFRESH_REQUIRED",
                evidence=evidence,
            )

        # inactive/deleted 또는 credential 부재 + disconnected + (pause|cred_missing)
        safe = False
        if uba_abandoned and consumer_count == 0:
            safe = True
        elif (
            disconnected
            and no_usable_cred
            and consumer_count == 0
            and (recovery_cred_missing or recovery_paused or recovery.get("status") == "FAILED")
        ):
            safe = True

        if safe:
            return SnapshotTriageItem(
                snapshot_id=sid,
                classification=CLASS_SAFE,
                current_status=status,
                stale_age_seconds=age,
                owner_uba=uba_id,
                broker_code=broker,
                generation=gen,
                consumer_count=consumer_count,
                runtime_refs=runtime_refs,
                order_refs_inflight=inflight_orders,
                outbox_refs_active=active_outbox,
                newer_snapshot=newer,
                retire_allowed=True,
                block_reason=None,
                evidence=evidence,
            )

        return SnapshotTriageItem(
            snapshot_id=sid,
            classification=CLASS_UNKNOWN,
            current_status=status,
            stale_age_seconds=age,
            owner_uba=uba_id,
            broker_code=broker,
            generation=gen,
            consumer_count=consumer_count,
            runtime_refs=runtime_refs,
            order_refs_inflight=inflight_orders,
            outbox_refs_active=active_outbox,
            newer_snapshot=newer,
            retire_allowed=False,
            block_reason="INSUFFICIENT_SAFETY_EVIDENCE",
            evidence=evidence,
        )

    def _count_active_strategy_links(self, uba_id: int) -> int:
        from stock_platform.strategy_deployment.definition_entities import (
            AccountStrategyLinkEntity,
        )

        return int(
            self._session.scalar(
                select(func.count())
                .select_from(AccountStrategyLinkEntity)
                .where(
                    AccountStrategyLinkEntity.user_broker_account_id == int(uba_id),
                    AccountStrategyLinkEntity.is_active.is_(True),
                )
            )
            or 0
        )

    def _count_runtime_refs(self, uba_id: int) -> int:
        # 테이블 부재·권한 오류 시 0 — 호출 트랜잭션은 savepoint 로 보호
        try:
            with self._session.begin_nested():
                result = self._session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM trading.strategy_runtime_registry
                        WHERE target_user_broker_account_id = :uba
                          AND (
                            COALESCE(enabled, false) = true
                            OR COALESCE(running, false) = true
                            OR UPPER(COALESCE(status, '')) IN
                               ('ACTIVE','RUNNING','REGISTERED','ENABLED')
                          )
                        """
                    ),
                    {"uba": int(uba_id)},
                )
                return int(result.scalar() or 0)
        except Exception:
            return 0

    def _count_inflight_orders(self, uba_id: int) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(TradingOrderEntity)
                .where(
                    TradingOrderEntity.user_broker_account_id == int(uba_id),
                    TradingOrderEntity.status_code.in_(
                        sorted(_IN_FLIGHT_ORDER_STATUSES)
                    ),
                )
            )
            or 0
        )

    def _count_active_outbox(self, uba_id: int) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(OrderOutbox)
                .join(
                    TradingOrderEntity,
                    TradingOrderEntity.order_id == OrderOutbox.order_id,
                )
                .where(
                    TradingOrderEntity.user_broker_account_id == int(uba_id),
                    OrderOutbox.status_code.in_(sorted(_ACTIVE_OUTBOX_STATUSES)),
                )
            )
            or 0
        )

    def _has_newer_snapshot(
        self, *, uba_id: int, generation: int, sid: int
    ) -> bool:
        newer = self._session.scalar(
            select(func.count())
            .select_from(BrokerAccountSnapshotEntity)
            .where(
                BrokerAccountSnapshotEntity.user_broker_account_id == int(uba_id),
                BrokerAccountSnapshotEntity.broker_account_snapshot_id != int(sid),
                BrokerAccountSnapshotEntity.snapshot_generation > int(generation),
            )
        )
        return int(newer or 0) > 0

    def _credential_summary(self, uba_id: int) -> dict[str, Any]:
        try:
            with self._session.begin_nested():
                rows = (
                    self._session.execute(
                        text(
                            """
                            SELECT is_active, verification_status, revoked_at
                            FROM trading.broker_account_credential
                            WHERE user_broker_account_id = :uba
                            """
                        ),
                        {"uba": int(uba_id)},
                    )
                    .mappings()
                    .all()
                )
        except Exception:
            return {"has_active_verified": False, "rows": 0}

        has_active_verified = any(
            bool(r["is_active"])
            and str(r["verification_status"] or "").upper() == "VERIFIED"
            and r["revoked_at"] is None
            for r in rows
        )
        return {
            "has_active_verified": has_active_verified,
            "rows": len(rows),
        }

    def _recovery_summary(self, uba_id: int) -> dict[str, Any]:
        try:
            with self._session.begin_nested():
                row = (
                    self._session.execute(
                        text(
                            """
                            SELECT recovery_status, trading_paused,
                                   last_error_summary, auto_retry_enabled
                            FROM operation.broker_recovery_account_state
                            WHERE user_broker_account_id = :uba
                            LIMIT 1
                            """
                        ),
                        {"uba": int(uba_id)},
                    )
                    .mappings()
                    .first()
                )
        except Exception:
            return {}
        if not row:
            return {}
        return {
            "status": row["recovery_status"],
            "trading_paused": bool(row["trading_paused"]),
            "last_error_summary": row["last_error_summary"],
            "auto_retry_enabled": bool(row["auto_retry_enabled"]),
        }

    def _count_open_recovery_conflicts(self, uba_id: int) -> int:
        try:
            with self._session.begin_nested():
                result = self._session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM operation.broker_recovery_conflict
                        WHERE user_broker_account_id = :uba
                          AND review_status IN
                              ('OPEN','PENDING','NEEDS_REVIEW','ACTIVE','IN_REVIEW')
                        """
                    ),
                    {"uba": int(uba_id)},
                )
                return int(result.scalar() or 0)
        except Exception:
            return 0
