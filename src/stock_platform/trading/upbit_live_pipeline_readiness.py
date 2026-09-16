"""Upbit LIVE 운영 준비 스냅샷 — 실주문 전송 없음.

시세→Hub→Signal→Risk→Shadow/Dry-run Candidate,
UBA·Credential·Kill·Pause, Fill 원장, Recovery, WS 상태를 조회한다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.trading.account_models import UserBrokerAccount


class UpbitLivePipelineReadinessService:
    """Upbit LIVE ops readiness (조회 전용, submit/cancel/replace 0)."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._settings = get_settings()

    def evaluate(
        self,
        *,
        user_broker_account_id: int | None = None,
    ) -> dict[str, Any]:
        uba_id = user_broker_account_id
        if uba_id is None:
            uba_id = self._session.execute(
                text(
                    """
                    SELECT user_broker_account_id
                    FROM trading.user_broker_account
                    WHERE broker_code='UPBIT' AND is_active IS TRUE
                      AND deleted_at IS NULL
                    ORDER BY user_broker_account_id
                    LIMIT 1
                    """
                )
            ).scalar()

        checks: dict[str, Any] = {}
        blockers: list[str] = []
        warnings: list[str] = []

        # --- UBA / ownership ---
        uba_row = None
        if uba_id:
            uba_row = self._session.get(UserBrokerAccount, int(uba_id))
        checks["uba"] = {
            "user_broker_account_id": int(uba_id) if uba_id else None,
            "found": uba_row is not None,
            "broker_code": getattr(uba_row, "broker_code", None),
            "user_id": getattr(uba_row, "user_id", None),
            "is_active": bool(getattr(uba_row, "is_active", False)),
            "live_order_enabled": bool(
                getattr(uba_row, "live_order_enabled", False)
            ),
            "live_armed": bool(getattr(uba_row, "live_armed", False)),
        }
        if uba_row is None:
            blockers.append("UPBIT_UBA_MISSING")
        elif str(getattr(uba_row, "broker_code", "")).upper() != "UPBIT":
            blockers.append("UBA_BROKER_MISMATCH")
        elif not bool(getattr(uba_row, "is_active", False)):
            blockers.append("UBA_INACTIVE")

        # --- Credential vault ---
        cred_ok = False
        cred_detail: dict[str, Any] = {"resolved": False}
        if uba_row is not None:
            try:
                from stock_platform.broker.credential_vault_service import (
                    BrokerCredentialVaultService,
                )

                resolved = BrokerCredentialVaultService(
                    self._session
                ).resolve_for_runtime(
                    int(uba_id),
                    expected_broker="UPBIT",
                    require_verified=True,
                    touch_last_used=False,
                )
                payload = dict(resolved.payload or {})
                access = str(payload.get("access_key") or "").strip()
                secret = str(payload.get("secret_key") or "").strip()
                cred_ok = bool(access and secret)
                cred_detail = {
                    "resolved": True,
                    "has_access_key": bool(access),
                    "has_secret_key": bool(secret),
                    "access_key_len": len(access),
                    "secret_key_len": len(secret),
                }
            except Exception as exc:  # noqa: BLE001
                cred_detail = {
                    "resolved": False,
                    "error": type(exc).__name__,
                }
                blockers.append("UPBIT_CREDENTIAL_UNRESOLVED")
        checks["credential"] = {**cred_detail, "ok": cred_ok}
        if uba_row is not None and not cred_ok and "UPBIT_CREDENTIAL_UNRESOLVED" not in blockers:
            blockers.append("UPBIT_CREDENTIAL_MISSING")

        # --- Kill / Pause ---
        kill_active = False
        try:
            from stock_platform.risk_engine.kill_switch_service import (
                KillSwitchService,
            )
            from stock_platform.trading.account_identity import (
                uba_kill_switch_scope,
            )

            svc = KillSwitchService(self._session)
            global_active = svc.is_active()
            uba_active = False
            if uba_id:
                uba_active = svc.is_active_for_scopes(
                    [uba_kill_switch_scope(int(uba_id))]
                )
            kill_active = bool(global_active or uba_active)
            checks["kill_switch"] = {
                "global_active": bool(global_active),
                "uba_active": bool(uba_active),
                "active": kill_active,
            }
        except Exception as exc:  # noqa: BLE001
            checks["kill_switch"] = {"error": type(exc).__name__}
            warnings.append("KILL_SWITCH_CHECK_FAILED")

        paused = False
        try:
            from stock_platform.broker.recovery_lock import (
                RecoveryAccountLockService,
            )

            if uba_id:
                paused = RecoveryAccountLockService(
                    self._session
                ).is_trading_paused(
                    user_broker_account_id=int(uba_id),
                    broker_code="UPBIT",
                )
            checks["pause"] = {"trading_paused": bool(paused)}
        except Exception as exc:  # noqa: BLE001
            checks["pause"] = {"error": type(exc).__name__}
            warnings.append("PAUSE_CHECK_FAILED")

        if kill_active:
            warnings.append("KILL_SWITCH_ACTIVE")
        if paused:
            warnings.append("ACCOUNT_PAUSED")

        # --- Shadow / Dry-run flags (실주문 Flag는 OFF 유지가 정상) ---
        shadow_on = bool(
            getattr(self._settings, "live_shadow_mode_enabled", False)
        )
        dry_on = bool(
            getattr(self._settings, "live_order_dry_run_enabled", False)
        )
        live_order_setting = bool(
            getattr(self._settings, "upbit_live_order_enabled", False)
        )
        checks["modes"] = {
            "live_shadow_mode_enabled": shadow_on,
            "live_order_dry_run_enabled": dry_on,
            "upbit_live_order_enabled": live_order_setting,
            "upbit_use_mock": bool(
                getattr(self._settings, "upbit_use_mock", True)
            ),
            "candidate_path": (
                "DRY_RUN"
                if dry_on
                else ("SHADOW" if shadow_on else "NONE")
            ),
        }
        if live_order_setting:
            warnings.append("UPBIT_LIVE_ORDER_FLAG_ON")
        if not shadow_on and not dry_on:
            warnings.append("NO_SHADOW_OR_DRY_RUN_FLAG")
        if bool(getattr(self._settings, "upbit_use_mock", True)):
            warnings.append("UPBIT_USE_MOCK_TRUE")

        # --- Pipeline module hooks ---
        hooks = {
            "fill_sync": False,
            "live_fill_ledger": False,
            "order_reconcile": False,
            "recovery_adapter": False,
            "dry_run": False,
            "shadow": False,
            "hub": False,
        }
        try:
            from stock_platform.broker.upbit.fill_sync_service import (
                UpbitFillSyncService,
            )

            hooks["fill_sync"] = hasattr(
                UpbitFillSyncService, "_apply_live_fill_ledger"
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            from stock_platform.broker.live_fill_ledger_service import (
                LiveFillLedgerService,
            )

            hooks["live_fill_ledger"] = hasattr(
                LiveFillLedgerService, "apply_execution"
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            from stock_platform.broker.upbit.order_reconcile_service import (
                UpbitOrderReconcileService,
            )

            hooks["order_reconcile"] = hasattr(
                UpbitOrderReconcileService, "reconcile_open_orders"
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            from stock_platform.broker.recovery_adapters.upbit import (
                UpbitRecoveryAdapter,
            )

            hooks["recovery_adapter"] = UpbitRecoveryAdapter is not None
        except Exception:  # noqa: BLE001
            pass
        try:
            from stock_platform.order.live_dry_run import is_live_dry_run_mode

            hooks["dry_run"] = callable(is_live_dry_run_mode)
        except Exception:  # noqa: BLE001
            pass
        try:
            from stock_platform.order.live_shadow import is_live_shadow_mode

            hooks["shadow"] = callable(is_live_shadow_mode)
        except Exception:  # noqa: BLE001
            pass
        try:
            from stock_platform.realtime.market_data_hub import (
                get_realtime_market_data_hub,
            )

            hooks["hub"] = get_realtime_market_data_hub is not None
        except Exception:  # noqa: BLE001
            pass
        checks["hooks"] = hooks
        for name, ok in hooks.items():
            if not ok:
                blockers.append(f"HOOK_MISSING_{name.upper()}")

        # --- Realtime WS / Hub status ---
        quote_ws: dict[str, Any] = {"running": False}
        try:
            from stock_platform.realtime.runtime import realtime_manager

            # status()는 async — sync 경로에서는 clients 맵만 조회
            clients = getattr(realtime_manager, "_clients", {}) or {}
            upbit_client_obj = clients.get("UPBIT")
            if upbit_client_obj is not None and hasattr(
                upbit_client_obj, "status"
            ):
                upbit_client = upbit_client_obj.status()
            else:
                upbit_client = {}
            connected = bool(upbit_client.get("connected"))
            running = bool(
                upbit_client.get("running")
                or upbit_client.get("connecting")
                or upbit_client_obj
            )
            # last_received_at 누락 시 AUTO LIVE가 NO_RECENT_QUOTE로 영구 BLOCK
            quote_ws = {
                "ok": connected,
                "running": running,
                "connected": connected,
                "received_count": upbit_client.get("received_count"),
                "reconnect_count": upbit_client.get("reconnect_count"),
                "last_received_at": upbit_client.get("last_received_at"),
                "symbols": upbit_client.get("symbols"),
                "last_error": upbit_client.get("last_error"),
            }
        except Exception as exc:  # noqa: BLE001
            quote_ws = {"error": type(exc).__name__}
        checks["quote_ws"] = quote_ws

        hub: dict[str, Any] = {}
        try:
            from stock_platform.realtime.market_data_hub import (
                get_realtime_market_data_hub,
            )

            hub = get_realtime_market_data_hub().status()
            # feed evaluator는 ok/running/dispatch_running 중 하나 필요
            if isinstance(hub, dict):
                hub = {
                    **hub,
                    "ok": bool(hub.get("dispatch_running")),
                    "running": bool(hub.get("dispatch_running")),
                }
        except Exception as exc:  # noqa: BLE001
            hub = {"error": type(exc).__name__}
        checks["hub_status"] = hub

        # --- Recent shadow/dry-run candidates (read-only) ---
        recent_candidates = 0
        if uba_id:
            try:
                recent_candidates = int(
                    self._session.execute(
                        text(
                            """
                            SELECT COUNT(*) FROM trading.trading_order
                            WHERE user_broker_account_id=:u
                              AND created_at >= NOW() - INTERVAL '1 day'
                              AND (
                                reject_code IN ('DRY_RUN_BLOCKED', 'LIVE_SHADOW_MODE')
                                OR metadata_payload->>'shadow_mode'='LIVE_SHADOW'
                                OR metadata_payload->>'dry_run_mode'='LIVE_DRY_RUN'
                              )
                            """
                        ),
                        {"u": int(uba_id)},
                    ).scalar_one()
                )
            except Exception:  # noqa: BLE001
                recent_candidates = 0
        checks["recent_candidates_24h"] = recent_candidates

        # --- Broker mutate guard ---
        checks["order_mutate_policy"] = {
            "submit_allowed": False,
            "cancel_allowed": False,
            "replace_allowed": False,
            "note": "ops readiness never calls broker mutate APIs",
        }

        # Dry-run ops ready: credential+uba+hooks, live order flag OFF preferred
        ops_ready = len(blockers) == 0
        return {
            "broker": "UPBIT",
            "ops_ready": ops_ready,
            "blockers": blockers,
            "warnings": warnings,
            "checks": checks,
            "flow": [
                "quote",
                "hub",
                "signal",
                "risk",
                "shadow_or_dry_run_candidate",
                "fill_ledger",
                "recovery_reconcile",
                "dashboard",
            ],
            "execute_live_allowed_here": False,
        }
