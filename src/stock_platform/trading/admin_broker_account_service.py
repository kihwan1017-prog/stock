"""STEP 8-9C — Admin UserBrokerAccount CRUD (UPBIT/KIWOOM).

실주문·ARM·LIVE ON은 이 모듈에서 수행하지 않는다.
UPBIT 생성 시 권장 Risk(5000/1/1)만 계좌 오버레이로 적용한다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.auth.repository import AuthRepository
from stock_platform.risk_engine.resolved_policy import (
    ResolvedRiskPolicyResolver,
)
from stock_platform.risk_engine.user_risk_service import (
    UserRiskSettingService,
)
from stock_platform.trading.account_masking import hash_account_ref
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.ops_account_classification import (
    classify_uba_ops_class,
    is_ops_visible,
)
from stock_platform.trading.upbit_live_ops_constants import (
    upbit_live_recommended_risk_payload,
)
from stock_platform.trading.user_account_service import (
    UserAccountError,
    UserAccountService,
    broker_to_view,
)


_BROKER_TYPES = frozenset({"KIWOOM", "UPBIT"})


class AdminBrokerAccountService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._accounts = UserAccountService(session)

    def list_accounts(
        self,
        *,
        broker_code: str | None = None,
        owner_user_id: int | None = None,
        include_inactive: bool = True,
        include_deleted: bool = False,
        include_test_accounts: bool = False,
        enrich: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        stmt = select(UserBrokerAccount)
        if broker_code:
            code = broker_code.strip().upper()
            if code not in _BROKER_TYPES:
                raise UserAccountError(f"unsupported broker_code: {code}")
            stmt = stmt.where(
                func.upper(UserBrokerAccount.broker_code) == code
            )
        if owner_user_id is not None:
            stmt = stmt.where(
                UserBrokerAccount.user_id == int(owner_user_id)
            )
        if not include_inactive:
            stmt = stmt.where(UserBrokerAccount.is_active.is_(True))
        # STEP 2-5-1 — 관리자 목록은 기본적으로 삭제 계좌를 제외하고,
        # include_deleted=True를 명시했을 때만 포함한다.
        if not include_deleted:
            stmt = stmt.where(UserBrokerAccount.deleted_at.is_(None))

        # 운영 기본: REAL_OPERATION만. 테스트 계좌는 옵션으로만 노출.
        all_rows = list(
            self._session.scalars(
                stmt.order_by(UserBrokerAccount.user_broker_account_id)
            ).all()
        )
        usernames = self._usernames_for_rows(all_rows)
        classified: list[tuple[UserBrokerAccount, str]] = []
        for row in all_rows:
            ops_class = classify_uba_ops_class(
                uba_id=int(row.user_broker_account_id),
                broker_code=str(row.broker_code),
                account_alias=row.account_alias,
                username=usernames.get(int(row.user_id)),
                live_order_enabled=bool(row.live_order_enabled),
                last_synced_at=row.last_synced_at,
                deleted_at=row.deleted_at,
            )
            if is_ops_visible(
                ops_class, include_test_accounts=include_test_accounts
            ):
                classified.append((row, ops_class))

        total = len(classified)
        page = classified[
            max(0, offset) : max(0, offset) + min(max(limit, 1), 500)
        ]
        items: list[dict[str, Any]] = []
        for row, ops_class in page:
            base = broker_to_view(row).as_dict()
            if enrich:
                item = self._enrich(base, row)
            else:
                item = self._enrich_light(base, row)
            item["ops_class"] = ops_class
            items.append(item)
        # connection_status 치유 flush 반영 (enrich 경로만)
        if enrich:
            try:
                self._session.commit()
            except Exception:  # noqa: BLE001
                self._session.rollback()
        return {
            "items": items,
            "total": total,
            "include_test_accounts": bool(include_test_accounts),
        }

    def get_account(self, uba_id: int) -> dict[str, Any]:
        row = self._session.get(UserBrokerAccount, int(uba_id))
        if row is None:
            raise UserAccountError("User broker account not found")
        out = self._enrich(broker_to_view(row).as_dict(), row)
        usernames = self._usernames_for_rows([row])
        out["ops_class"] = classify_uba_ops_class(
            uba_id=int(row.user_broker_account_id),
            broker_code=str(row.broker_code),
            account_alias=row.account_alias,
            username=usernames.get(int(row.user_id)),
            live_order_enabled=bool(row.live_order_enabled),
            last_synced_at=row.last_synced_at,
            deleted_at=row.deleted_at,
        )
        return out

    def create_account(
        self,
        *,
        owner_user_id: int,
        broker_code: str,
        account_alias: str | None,
        account_number: str,
        currency_code: str = "KRW",
        is_default: bool = False,
        apply_recommended_risk: bool = True,
        actor: str,
    ) -> dict[str, Any]:
        code = (broker_code or "").strip().upper()
        if code not in _BROKER_TYPES:
            raise UserAccountError(f"unsupported broker_code: {code}")

        owner = AuthRepository(self._session).get_by_id(int(owner_user_id))
        if owner is None or getattr(owner, "deleted_at", None) is not None:
            raise UserAccountError("Owner user not found")

        # 중복을 선검사해 409로 명확히 반환 (부분 커밋 방지)
        try:
            ref_hash = hash_account_ref(account_number)
        except ValueError as exc:
            raise UserAccountError(str(exc)) from exc
        # STEP 2-5-1 — 삭제(soft-deleted)된 행은 "이미 연결됨"으로 보지 않는다.
        # (동일 계좌 재연결은 아래 _accounts.create_account → _create_broker의
        # revive 로직이 처리한다.)
        dup = self._session.scalar(
            select(UserBrokerAccount).where(
                UserBrokerAccount.user_id == int(owner_user_id),
                func.upper(UserBrokerAccount.broker_code) == code,
                UserBrokerAccount.account_ref_hash == ref_hash,
                UserBrokerAccount.deleted_at.is_(None),
            )
        )
        if dup is not None:
            raise UserAccountError("이미 연결된 Broker 계좌입니다.")

        # UBA + 권장 Risk 를 동일 트랜잭션에서 flush (라우터가 commit)
        try:
            view = self._accounts.create_account(
                int(owner_user_id),
                account_type=code,
                account_name=account_alias,
                account_number=account_number,
                currency_code=currency_code,
                is_default=is_default,
                auto_commit=False,
            )
            uba_id = int(view.account_id)
            risk_applied = False
            if apply_recommended_risk and code == "UPBIT":
                UserRiskSettingService(self._session).upsert_account(
                    uba_id,
                    upbit_live_recommended_risk_payload(),
                    actor=actor,
                )
                risk_applied = True
            row = self._session.get(UserBrokerAccount, uba_id)
            if row is None:
                raise UserAccountError("User broker account not found")
            # LIVE ON / ARM 금지 — 생성 시점 강제 OFF
            if bool(row.live_order_enabled) or bool(row.live_armed):
                row.live_order_enabled = False
                row.live_armed = False
                row.arm_token_hash = None
                row.arm_expires_at = None
                self._session.flush()
            out = self._enrich(broker_to_view(row).as_dict(), row)
            out["recommended_risk_applied"] = risk_applied
            out["created_by"] = actor
            return out
        except UserAccountError:
            self._session.rollback()
            raise
        except Exception as exc:  # noqa: BLE001
            self._session.rollback()
            raise UserAccountError(
                "Broker account create failed"
            ) from exc

    def update_account(
        self,
        uba_id: int,
        *,
        account_alias: str | None = None,
        is_active: bool | None = None,
        actor: str,
    ) -> dict[str, Any]:
        row = self._session.get(UserBrokerAccount, int(uba_id))
        if row is None:
            raise UserAccountError("User broker account not found")
        view = self._accounts.update_account(
            int(row.user_id),
            int(uba_id),
            account_type=str(row.broker_code).upper(),
            account_name=account_alias,
            is_active=is_active,
        )
        refreshed = self._session.get(UserBrokerAccount, int(uba_id))
        assert refreshed is not None
        out = self._enrich(view.as_dict(), refreshed)
        out["updated_by"] = actor
        return out

    def delete_account(self, uba_id: int, *, actor: str) -> dict[str, Any]:
        """Broker 연결 행 unlink (실계좌 자체 삭제 아님). LIVE/ARM 강제 OFF."""

        row = self._session.get(UserBrokerAccount, int(uba_id))
        if row is None:
            raise UserAccountError("User broker account not found")
        owner_id = int(row.user_id)
        broker = str(row.broker_code).upper()
        # 삭제 전 LIVE/ARM 정리
        row.live_order_enabled = False
        row.live_armed = False
        row.arm_token_hash = None
        row.arm_expires_at = None
        self._session.flush()
        result = self._accounts.delete_account(
            owner_id,
            int(uba_id),
            account_type=broker,
        )
        result["deleted_by"] = actor
        result["live_forced_off"] = True
        return result

    def apply_recommended_risk(
        self, uba_id: int, *, actor: str
    ) -> dict[str, Any]:
        row = self._session.get(UserBrokerAccount, int(uba_id))
        if row is None:
            raise UserAccountError("User broker account not found")
        if str(row.broker_code).upper() != "UPBIT":
            raise UserAccountError(
                "recommended risk applies to UPBIT accounts only"
            )
        UserRiskSettingService(self._session).upsert_account(
            int(uba_id),
            upbit_live_recommended_risk_payload(),
            actor=actor,
        )
        self._session.commit()
        return self.get_account(int(uba_id))

    def _usernames_for_rows(
        self, rows: list[UserBrokerAccount]
    ) -> dict[int, str]:
        user_ids = {int(r.user_id) for r in rows}
        if not user_ids:
            return {}
        out: dict[int, str] = {}
        for uid in user_ids:
            user = AuthRepository(self._session).get_by_id(uid)
            if user is not None:
                out[uid] = str(getattr(user, "username", "") or "")
        return out

    def _enrich_light(
        self, base: dict[str, Any], row: UserBrokerAccount
    ) -> dict[str, Any]:
        """목록 경량 필드 — risk/vault sync/recovery N+1 생략."""

        out = dict(base)
        out["user_broker_account_id"] = int(row.user_broker_account_id)
        out["deleted_at"] = (
            row.deleted_at.isoformat() if row.deleted_at else None
        )
        out["live_order_enabled"] = bool(row.live_order_enabled)
        out["live_armed"] = bool(row.live_armed)
        out["arm_expires_at"] = (
            row.arm_expires_at.isoformat() if row.arm_expires_at else None
        )
        out["connection_status"] = row.connection_status
        out["risk"] = None
        out["credential"] = {
            "registered": None,
            "verification_status": None,
            "masked_identifier": None,
            "vault_available": None,
        }
        out["trading_paused"] = None
        out["recovery_status"] = None
        out["paused_reason"] = None
        out["active_conflict_count"] = None
        return out

    def _enrich(
        self, base: dict[str, Any], row: UserBrokerAccount
    ) -> dict[str, Any]:
        out = self._enrich_light(base, row)
        try:
            policy = ResolvedRiskPolicyResolver(self._session).resolve(
                user_id=int(row.user_id),
                user_broker_account_id=int(row.user_broker_account_id),
            )
            out["risk"] = {
                "max_order_amount": str(policy.max_order_amount),
                "max_order_quantity": str(policy.max_order_quantity),
                "max_open_orders": int(policy.max_open_orders),
                "daily_order_limit": int(policy.daily_order_limit),
            }
        except Exception:  # noqa: BLE001
            out["risk"] = None
        try:
            from stock_platform.broker.credential_vault_service import (
                BrokerCredentialVaultService,
            )

            vault = BrokerCredentialVaultService(self._session)
            # VERIFIED↔PENDING 불일치 치유 후 목록에 반영
            vault.sync_uba_connection_status(
                int(row.user_broker_account_id)
            )
            cred = vault.status(
                int(row.user_broker_account_id),
                broker_code=str(row.broker_code).upper(),
            )
            out["credential"] = {
                "registered": bool(cred.connected),
                "verification_status": cred.verification_status,
                "masked_identifier": cred.masked_identifier,
                "vault_available": bool(cred.vault_available),
            }
            out["connection_status"] = row.connection_status
        except Exception:  # noqa: BLE001
            out["credential"] = {
                "registered": False,
                "verification_status": None,
                "masked_identifier": None,
                "vault_available": False,
            }
        # Recovery / Pause 요약 (목록용)
        try:
            from stock_platform.broker.recovery_account_state import (
                BrokerRecoveryAccountStateEntity,
            )
            from stock_platform.broker.recovery_conflict_constants import (
                ACTIVE_REVIEW_STATUSES,
            )
            from stock_platform.broker.recovery_conflict_entities import (
                BrokerRecoveryConflictEntity,
            )

            broker = str(row.broker_code).upper()
            uba_id = int(row.user_broker_account_id)
            state = self._session.scalar(
                select(BrokerRecoveryAccountStateEntity)
                .where(
                    BrokerRecoveryAccountStateEntity.user_broker_account_id
                    == uba_id,
                    BrokerRecoveryAccountStateEntity.broker_code == broker,
                )
                .limit(1)
            )
            active_conflicts = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(BrokerRecoveryConflictEntity)
                    .where(
                        BrokerRecoveryConflictEntity.user_broker_account_id
                        == uba_id,
                        BrokerRecoveryConflictEntity.review_status.in_(
                            list(ACTIVE_REVIEW_STATUSES)
                        ),
                    )
                )
                or 0
            )
            out["trading_paused"] = (
                bool(state.trading_paused) if state else False
            )
            out["recovery_status"] = (
                state.recovery_status if state else None
            )
            out["paused_reason"] = (
                state.last_error_summary if state else None
            )
            out["active_conflict_count"] = active_conflicts
        except Exception:  # noqa: BLE001
            out["trading_paused"] = None
            out["recovery_status"] = None
            out["paused_reason"] = None
            out["active_conflict_count"] = None
        return out

    def get_ops_status(self, uba_id: int) -> dict[str, Any]:
        """관리자 상세 — Conflict/Pause/Recovery/Runtime/Scheduler/Credential."""

        row = self._session.get(UserBrokerAccount, int(uba_id))
        if row is None:
            raise UserAccountError("User broker account not found")
        broker = str(row.broker_code).upper()
        base = self._enrich(broker_to_view(row).as_dict(), row)

        from stock_platform.broker.credential_vault_service import (
            BrokerCredentialVaultService,
        )
        from stock_platform.broker.recovery_account_state import (
            BrokerRecoveryAccountStateEntity,
        )
        from stock_platform.broker.recovery_conflict_service import (
            BrokerRecoveryConflictService,
        )
        from stock_platform.risk_engine.user_risk_service import (
            UserRiskSettingService,
        )

        vault = BrokerCredentialVaultService(self._session)
        vault.sync_uba_connection_status(int(uba_id))
        self._session.flush()
        cred = vault.status(int(uba_id), broker_code=broker)

        state = self._session.scalar(
            select(BrokerRecoveryAccountStateEntity)
            .where(
                BrokerRecoveryAccountStateEntity.user_broker_account_id
                == int(uba_id),
                BrokerRecoveryAccountStateEntity.broker_code == broker,
            )
            .limit(1)
        )
        conflicts = BrokerRecoveryConflictService(
            self._session
        ).list_conflicts(
            user_broker_account_id=int(uba_id),
            resolved=False,
            limit=20,
            offset=0,
        )
        conflict_items = []
        for c in conflicts:
            conflict_items.append(
                {
                    "conflict_id": int(c.broker_recovery_conflict_id),
                    "conflict_code": c.conflict_type,
                    "conflict_reason": c.pause_reason,
                    "review_status": c.review_status,
                    "risk_level": c.risk_level,
                    "external_order_id_masked": c.external_order_id_masked,
                }
            )

        risk = UserRiskSettingService(self._session).snapshot_account(
            int(uba_id)
        )
        scheduler_status = None
        try:
            from stock_platform.broker.recovery_scheduler import (
                broker_recovery_scheduler,
            )

            scheduler_status = broker_recovery_scheduler.status()
        except Exception:  # noqa: BLE001
            scheduler_status = {"available": False}

        runtime_status = {
            "live_order_enabled": bool(row.live_order_enabled),
            "live_armed": bool(row.live_armed),
            "uba_active": bool(row.is_active),
            "connection_status": row.connection_status,
        }

        try:
            self._session.commit()
        except Exception:  # noqa: BLE001
            self._session.rollback()

        return {
            **base,
            "credential_status": cred.verification_status,
            "credential": {
                "registered": bool(cred.connected),
                "verification_status": cred.verification_status,
                "masked_identifier": cred.masked_identifier,
                "last_verified_at": (
                    cred.last_verified_at.isoformat()
                    if cred.last_verified_at
                    else None
                ),
                "vault_available": bool(cred.vault_available),
            },
            "connection_status": row.connection_status,
            "trading_paused": (
                bool(state.trading_paused) if state else False
            ),
            "paused_reason": (
                state.last_error_summary if state else None
            ),
            "paused_error_code": (
                state.last_error_code if state else None
            ),
            "recovery_status": (
                state.recovery_status if state else None
            ),
            "auto_retry_enabled": (
                bool(state.auto_retry_enabled) if state else None
            ),
            "next_retry_at": (
                state.next_retry_at.isoformat()
                if state and state.next_retry_at
                else None
            ),
            "next_retry_reason": (
                state.next_retry_reason if state else None
            ),
            "active_conflict_count": len(conflict_items),
            "conflicts": conflict_items,
            "conflict_code": (
                conflict_items[0]["conflict_code"]
                if conflict_items
                else None
            ),
            "conflict_reason": (
                conflict_items[0]["conflict_reason"]
                if conflict_items
                else None
            ),
            "account_paused": bool(
                (risk or {}).get("account_paused")
                if isinstance(risk, dict)
                else False
            ),
            "runtime_status": runtime_status,
            "scheduler_status": scheduler_status,
            "live_order_enabled": bool(row.live_order_enabled),
            "live_armed": bool(row.live_armed),
        }
