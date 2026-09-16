"""Canonical safe auto-recovery orchestrator.

DETECT → SNAPSHOT → CLASSIFY → RECONCILE → PRECHECK → RECOVER → OBSERVE
Fail-closed. Never fail-open. No forced BUY/SELL.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.common.logger import logger
from stock_platform.trading.safe_auto_recovery.circuit_breaker import (
    evaluate_circuit,
)
from stock_platform.trading.safe_auto_recovery.classification import (
    ClassificationResult,
    RecoveryClass,
    classify_incident,
)
from stock_platform.trading.safe_auto_recovery.incident_snapshot import (
    build_incident_snapshot,
    persist_incident,
)
from stock_platform.trading.safe_auto_recovery.precheck import (
    run_recovery_precheck,
)

_LOCKS: dict[int, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _uba_lock(uba: int) -> threading.Lock:
    with _LOCKS_GUARD:
        if uba not in _LOCKS:
            _LOCKS[uba] = threading.Lock()
        return _LOCKS[uba]


class SafeAutoRecoveryOrchestrator:
    def __init__(self, session: Session) -> None:
        self._session = session

    def evaluate_and_maybe_recover(
        self,
        *,
        user_broker_account_id: int,
        broker_code: str = "UPBIT",
        ops: dict[str, Any] | None = None,
        primary_blocker: str | None = None,
        blockers: list[str] | None = None,
        failure_event_type: str | None = None,
        first_zero: str | None = None,
        execute_recover: bool = True,
        actor: str = "SAFE_AUTO_RECOVERY",
    ) -> dict[str, Any]:
        uba = int(user_broker_account_id)
        lock = _uba_lock(uba)
        if not lock.acquire(blocking=False):
            return {
                "ok": False,
                "status": "LOCKED",
                "reason": "CONCURRENT_RECOVERY_SUPPRESSED",
            }
        try:
            return self._run(
                user_broker_account_id=uba,
                broker_code=broker_code,
                ops=ops or {},
                primary_blocker=primary_blocker,
                blockers=blockers,
                failure_event_type=failure_event_type,
                first_zero=first_zero,
                execute_recover=execute_recover,
                actor=actor,
            )
        finally:
            lock.release()

    def _run(
        self,
        *,
        user_broker_account_id: int,
        broker_code: str,
        ops: dict[str, Any],
        primary_blocker: str | None,
        blockers: list[str] | None,
        failure_event_type: str | None,
        first_zero: str | None,
        execute_recover: bool,
        actor: str,
    ) -> dict[str, Any]:
        recovery_id = f"rec-{user_broker_account_id}-{uuid.uuid4().hex[:10]}"
        precheck = run_recovery_precheck(
            self._session, user_broker_account_id=user_broker_account_id
        )
        root = str(primary_blocker or failure_event_type or "UNKNOWN")
        circuit = evaluate_circuit(
            self._session,
            user_broker_account_id=user_broker_account_id,
            root_cause=root,
        )
        unatt = ops.get("unattended") or {}
        unattended_active = bool(
            isinstance(unatt, dict)
            and (
                unatt.get("unattended_enabled")
                or str(unatt.get("status_code") or "").upper()
                in {"ON", "ACTIVE", "ENABLED"}
            )
        )
        activation_active = (
            str(ops.get("activation") or "").upper() == "ACTIVE"
        )
        classification = classify_incident(
            primary_blocker=primary_blocker,
            blockers=blockers or list(ops.get("blockers") or []),
            failure_event_type=failure_event_type,
            precheck=precheck,
            circuit_open=bool(circuit.get("open")),
            unattended_active=unattended_active,
            activation_active=activation_active,
        )
        recovery_meta: dict[str, Any] = {
            "recovery_id": recovery_id,
            "status": "SNAPSHOT",
            "attempt_count": int(circuit.get("attempt_count") or 0),
            "circuit": circuit,
            "triggered_new_live_order": False,
        }
        snapshot = build_incident_snapshot(
            user_broker_account_id=user_broker_account_id,
            broker_code=broker_code,
            primary_blocker=primary_blocker,
            failure_event_type=failure_event_type,
            first_zero=first_zero,
            ops=ops,
            precheck=precheck,
            classification=classification.to_dict(),
            recovery=recovery_meta,
        )
        persist_incident(self._session, snapshot)
        try:
            self._session.commit()
        except Exception:  # noqa: BLE001
            self._session.rollback()

        result: dict[str, Any] = {
            "ok": False,
            "recovery_id": recovery_id,
            "incident_id": snapshot["incident_id"],
            "classification": classification.to_dict(),
            "precheck": precheck,
            "circuit": circuit,
            "snapshot_evidence": snapshot.get("evidence_path"),
            "RECOVERY_TRIGGERED_NEW_LIVE_ORDER": "NO",
        }

        if not classification.auto_recover_allowed:
            result["status"] = "OPERATOR_REQUIRED"
            result["reason"] = classification.reason
            return result

        if not precheck.get("ok"):
            result["status"] = "PRECHECK_FAILED"
            result["reason"] = "PRECHECK_NOT_OK"
            return result

        if not execute_recover:
            result["status"] = "ELIGIBLE_DRY_RUN"
            result["ok"] = True
            return result

        # Class B: broker reconcile first (identifier heal / fill sync)
        if classification.recovery_class == RecoveryClass.B:
            recon = self._reconcile_broker_canonical(user_broker_account_id)
            result["reconcile"] = recon
            if not recon.get("ok"):
                result["status"] = "RECONCILE_FAILED_OPERATOR_REQUIRED"
                result["reason"] = recon.get("reason")
                return result
            # re-precheck after reconcile
            precheck = run_recovery_precheck(
                self._session, user_broker_account_id=user_broker_account_id
            )
            result["precheck_after_reconcile"] = precheck
            if not precheck.get("ok"):
                result["status"] = "PRECHECK_FAILED_AFTER_RECONCILE"
                return result

        restore = self._restore_live_arm_stack(
            user_broker_account_id=user_broker_account_id,
            ops=ops,
            actor=actor,
            correlation_id=recovery_id,
        )
        result["restore"] = restore
        if not restore.get("ok"):
            result["status"] = "RECOVER_FAILED"
            result["reason"] = restore.get("reason")
            self._mark_attempt(
                snapshot["incident_id"], status="RECOVER_FAILED"
            )
            return result

        result["ok"] = True
        result["status"] = "RECOVER_SUCCESS"
        self._mark_attempt(snapshot["incident_id"], status="RECOVER_SUCCESS")
        logger.info(
            "safe_auto_recovery_success",
            uba=user_broker_account_id,
            recovery_id=recovery_id,
            recovery_class=str(classification.recovery_class),
        )
        return result

    def _reconcile_broker_canonical(
        self, user_broker_account_id: int
    ) -> dict[str, Any]:
        """Class B — missing UUID heal + fill sync for open AUTO exits."""

        from sqlalchemy import text

        from stock_platform.broker.upbit.fill_sync_service import (
            UpbitFillSyncService,
        )

        rows = self._session.execute(
            text(
                """
                SELECT order_id, status_code, broker_order_id
                FROM trading.trading_order
                WHERE user_broker_account_id = :uba
                  AND UPPER(COALESCE(metadata_payload->>'order_source','')) = 'AUTO'
                  AND UPPER(status_code) IN (
                    'PENDING','ACCEPTED','SUBMITTED','AMBIGUOUS_SUBMISSION',
                    'REMOTE_LOOKUP_PENDING','PARTIAL','PARTIALLY_FILLED'
                  )
                ORDER BY order_id
                LIMIT 20
                """
            ),
            {"uba": int(user_broker_account_id)},
        ).mappings().all()
        synced: list[dict[str, Any]] = []
        for row in rows:
            oid = int(row["order_id"])
            try:
                # ensure identifier path exists for missing UUID
                if not row.get("broker_order_id"):
                    from stock_platform.broker.upbit.ambiguous_resolver import (
                        UpbitAmbiguousResolver,
                    )
                    from stock_platform.order.entities import TradingOrderEntity

                    order = self._session.get(TradingOrderEntity, oid)
                    if order is not None:
                        UpbitAmbiguousResolver(
                            self._session
                        ).ensure_identifier(order)
                        self._session.flush()
                res = UpbitFillSyncService(self._session).sync_by_order_id(
                    oid, actor="SAFE_AUTO_RECOVERY_CLASS_B"
                )
                synced.append(
                    {
                        "order_id": oid,
                        "ok": getattr(res, "ok", None),
                        "repr": repr(res)[:200],
                    }
                )
            except Exception as exc:  # noqa: BLE001
                self._session.rollback()
                return {
                    "ok": False,
                    "reason": type(exc).__name__,
                    "order_id": oid,
                    "synced": synced,
                }
        try:
            self._session.commit()
        except Exception as exc:  # noqa: BLE001
            self._session.rollback()
            return {"ok": False, "reason": type(exc).__name__, "synced": synced}
        return {"ok": True, "synced": synced}

    def _restore_live_arm_stack(
        self,
        *,
        user_broker_account_id: int,
        ops: dict[str, Any],
        actor: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        """LIVE/ARM/stack 복구 — ACTIVE lease면 canonical restore_from_active_lease 재사용.

        HTTP raw LIVE ON은 known AUTO ENTRY BUY를 허용하지 않아 ARM_EXPIRED 이후
        복구가 영구 실패할 수 있다. lease ACTIVE이면 unattended restore 경로를 우선한다.
        """

        detail: dict[str, Any] = {}

        # 1) ACTIVE unattended lease → canonical restore (ARM renew와 대칭 open-order gate)
        try:
            from stock_platform.trading.live_unattended_authorization_service import (
                LiveUnattendedAuthorizationService,
            )

            unatt = LiveUnattendedAuthorizationService(self._session)
            if unatt.get_active(int(user_broker_account_id)) is not None:
                restored = unatt.restore_from_active_lease(
                    int(user_broker_account_id),
                    actor=actor,
                    restore_stack=False,
                )
                detail["lease_restore"] = restored
                if restored.get("restored"):
                    try:
                        self._session.commit()
                    except Exception as exc:  # noqa: BLE001
                        self._session.rollback()
                        return {
                            "ok": False,
                            "reason": f"LEASE_RESTORE_COMMIT_{type(exc).__name__}",
                            "detail": detail,
                        }
                    self._start_stack_components_sync(
                        user_broker_account_id, detail
                    )
                    return {
                        "ok": True,
                        "detail": detail,
                        "path": "UNATTENDED_LEASE_RESTORE",
                    }
                detail["lease_restore_failed_reason"] = restored.get("reason")
        except Exception as exc:  # noqa: BLE001
            detail["lease_restore_error"] = type(exc).__name__

        http = self._restore_via_http(
            user_broker_account_id=user_broker_account_id,
            ops=ops,
            correlation_id=correlation_id,
        )
        if http.get("ok"):
            return http
        detail["http_fallback_reason"] = http.get("reason")

        from stock_platform.trading.live_arm_service import LiveArmService
        from stock_platform.trading.live_order_approval_service import (
            LiveOrderApprovalError,
            LiveOrderApprovalService,
        )

        # LIVE ON (in-process fallback — lease 없을 때만; open-order는 strict fail-closed)
        try:
            live = LiveOrderApprovalService(self._session).set_live_enabled(
                user_broker_account_id,
                enabled=True,
                actor=actor,
                reason="SAFE_AUTO_RECOVERY_CLASS_A_OR_B",
                correlation_id=correlation_id,
                run_id=correlation_id,
            )
            self._session.commit()
            detail["live"] = {
                "ok": True,
                "live_order_enabled": live.get("live_order_enabled"),
            }
        except LiveOrderApprovalError as exc:
            self._session.rollback()
            return {
                "ok": False,
                "reason": f"LIVE_ON_{exc.code}",
                "message": exc.message,
                "detail": detail,
            }
        except Exception as exc:  # noqa: BLE001
            self._session.rollback()
            return {
                "ok": False,
                "reason": f"LIVE_ON_{type(exc).__name__}",
                "detail": detail,
            }

        act_exp = ops.get("activation_expires_at")
        ttl = 3600
        try:
            if act_exp:
                exp = datetime.fromisoformat(
                    str(act_exp).replace("Z", "+00:00")
                )
                rem = int(
                    (exp - datetime.now(timezone.utc)).total_seconds()
                )
                if rem > 90:
                    ttl = rem - 30
                elif rem > 0:
                    ttl = max(60, rem)
        except ValueError:
            ttl = 3600
        try:
            arm = LiveArmService(self._session).arm(
                user_broker_account_id,
                ttl_seconds=int(ttl),
                actor=actor,
                reason="SAFE_AUTO_RECOVERY_CLASS_A_OR_B",
                correlation_id=correlation_id,
                run_id=correlation_id,
            )
            if isinstance(arm, dict) and "arm_token" in arm:
                arm = {**arm, "arm_token": "<redacted>"}
            self._session.commit()
            detail["arm"] = {"ok": True, "ttl_seconds": ttl, "result": arm}
        except Exception as exc:  # noqa: BLE001
            self._session.rollback()
            return {
                "ok": False,
                "reason": f"ARM_ON_{type(exc).__name__}",
                "partial": detail,
            }

        self._start_stack_components_sync(user_broker_account_id, detail)
        return {"ok": True, "detail": detail, "path": "ORM_FALLBACK"}

    def _restore_via_http(
        self,
        *,
        user_broker_account_id: int,
        ops: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        import json
        from urllib.error import HTTPError, URLError
        from urllib.request import Request, urlopen

        from stock_platform.auth.jwt_service import JwtTokenService
        from stock_platform.common.settings import get_settings

        try:
            tok, _ = JwtTokenService(get_settings()).create_access_token(
                user_id=7, username="admin", roles=["admin"]
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": f"TOKEN_{type(exc).__name__}"}

        base = "http://127.0.0.1:8000"
        uba = int(user_broker_account_id)

        def _req(method: str, path: str, body: dict[str, Any] | None = None):
            data = None
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {tok}",
            }
            if body is not None:
                data = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            req = Request(base + path, data=data, headers=headers, method=method)
            try:
                with urlopen(req, timeout=90) as resp:
                    raw = resp.read().decode("utf-8")
                    return int(resp.status), json.loads(raw) if raw else {}
            except HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = {"detail": raw[:500]}
                return int(exc.code), parsed
            except (URLError, TimeoutError, OSError) as exc:
                return 0, {"detail": str(exc)}

        live_http, live_body = _req(
            "PUT",
            f"/api/v1/admin/live-order/accounts/{uba}",
            {
                "live_order_enabled": True,
                "reason": "SAFE_AUTO_RECOVERY_CLASS_A_OR_B",
                "correlation_id": correlation_id,
            },
        )
        if live_http not in {200, 201}:
            return {
                "ok": False,
                "reason": f"HTTP_LIVE_{live_http}",
                "body": live_body,
            }

        act_exp = ops.get("activation_expires_at")
        ttl = 3600
        try:
            if act_exp:
                exp = datetime.fromisoformat(
                    str(act_exp).replace("Z", "+00:00")
                )
                rem = int(
                    (exp - datetime.now(timezone.utc)).total_seconds()
                )
                if rem > 90:
                    ttl = rem - 30
                elif rem > 0:
                    ttl = max(60, rem)
        except ValueError:
            ttl = 3600

        arm_http, arm_body = _req(
            "POST",
            f"/api/v1/admin/live-order/accounts/{uba}/arm",
            {
                "ttl_seconds": int(ttl),
                "reason": "SAFE_AUTO_RECOVERY_CLASS_A_OR_B",
                "correlation_id": correlation_id,
            },
        )
        if isinstance(arm_body, dict) and "arm_token" in arm_body:
            arm_body = {**arm_body, "arm_token": "<redacted>"}
        if arm_http not in {200, 201}:
            return {
                "ok": False,
                "reason": f"HTTP_ARM_{arm_http}",
                "body": arm_body,
                "partial_live": True,
            }

        stack: dict[str, Any] = {}
        for name, path, body in (
            (
                "outbox",
                "/api/v1/admin/autotrading/live-outbox-worker/start",
                {"confirmation_text": "START OUTBOX WORKER"},
            ),
            (
                "exit",
                "/api/v1/admin/autotrading/exit-monitor/start",
                {"confirmation_text": "START EXIT MONITOR"},
            ),
            (
                "runtime",
                f"/api/v1/admin/autotrading/uba/{uba}/strategy-runtime/start",
                {"strategy_id": 17483, "confirmation_text": "START RUNTIME"},
            ),
            (
                "runner",
                f"/api/v1/realtime-execution/{uba}/start",
                {
                    "mode": "LIVE",
                    "user_broker_account_id": uba,
                    "confirmation_text": "START LIVE EXECUTION",
                },
            ),
        ):
            st, body_r = _req("POST", path, body)
            stack[name] = {"http": st, "body": body_r}

        return {
            "ok": True,
            "path": "HTTP_CANONICAL",
            "detail": {
                "live": live_body,
                "arm": arm_body,
                "ttl_seconds": ttl,
                "stack": stack,
            },
        }

    def _start_stack_components_sync(
        self, user_broker_account_id: int, detail: dict[str, Any]
    ) -> None:
        """Best-effort component starts without creating orders."""

        try:
            from stock_platform.order.live_outbox_worker_runtime import (
                live_outbox_worker_runtime,
            )

            st = live_outbox_worker_runtime.status()
            if not bool(st.get("running")):
                live_outbox_worker_runtime.start()
                detail["outbox"] = "STARTED"
            else:
                detail["outbox"] = "ALREADY_RUNNING"
        except Exception as exc:  # noqa: BLE001
            detail["outbox_error"] = type(exc).__name__
        try:
            from stock_platform.position.exit_monitor_scheduler import (
                position_exit_monitor_scheduler,
            )

            position_exit_monitor_scheduler.start()
            detail["exit"] = "STARTED"
        except Exception as exc:  # noqa: BLE001
            detail["exit_error"] = type(exc).__name__

    def _mark_attempt(self, incident_id: str, *, status: str) -> None:
        from sqlalchemy import text

        try:
            self._session.execute(
                text(
                    """
                    UPDATE operation.autotrading_recovery_incident
                    SET status = :status,
                        attempt_count = COALESCE(attempt_count,0) + 1,
                        updated_at = :ts
                    WHERE incident_id = :incident_id
                    """
                ),
                {
                    "status": status,
                    "incident_id": incident_id,
                    "ts": datetime.now(timezone.utc),
                },
            )
            self._session.commit()
        except Exception:  # noqa: BLE001
            self._session.rollback()
