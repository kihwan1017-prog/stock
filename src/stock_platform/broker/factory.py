from stock_platform.broker.adapter import BrokerAdapter
from stock_platform.broker.credential_adapter_factory import (
    build_kiwoom_adapter_for_uba,
    build_upbit_adapter_for_uba,
    is_system_shared_credential_ref,
    parse_user_broker_credential_ref,
)
from stock_platform.broker.kiwoom.adapter import KiwoomBrokerAdapter
from stock_platform.broker.live_transition_guard import (
    LiveTradingTransitionGuard,
)
from stock_platform.broker.models import BrokerEnvironment
from stock_platform.broker.paper.adapter import PaperBrokerAdapter
from stock_platform.broker.upbit.adapter import UpbitBrokerAdapter
from stock_platform.common.settings import get_settings


class BrokerAdapterFactory:
    @staticmethod
    def create(
        environment: BrokerEnvironment,
        broker_code: str,
        *,
        session=None,
        user_broker_account_id: int | None = None,
        credential_ref: str | None = None,
        uses_system_shared_credential: bool = False,
    ) -> BrokerAdapter:
        code = (broker_code or "").strip().upper()
        settings = get_settings()

        if environment == BrokerEnvironment.PAPER:
            # PAPER 환경에서도 업비트 mock 어댑터로 경로 검증 가능
            if code == "UPBIT":
                return UpbitBrokerAdapter(settings=settings)
            return PaperBrokerAdapter()

        if environment != BrokerEnvironment.LIVE:
            raise ValueError(
                f"Unsupported environment: {environment}"
            )

        if not settings.global_live_order_enabled:
            raise PermissionError(
                "GLOBAL_LIVE_ORDER_ENABLED must be true"
            )

        if session is None:
            raise PermissionError(
                "Live adapter requires DB session for "
                "transition approval check"
            )

        # 키움 LIVE 경로만 환경 불일치 Fail Closed
        if code == "KIWOOM":
            from stock_platform.broker.live_config_gate import (
                evaluate_live_flag_consistency,
                record_live_config_audit,
            )

            cfg = evaluate_live_flag_consistency()
            if cfg.code in {
                "LIVE_MOCK_CONFLICT",
                "LIVE_FLAG_MISMATCH_KIWOOM",
            }:
                record_live_config_audit(
                    session, actor="BROKER_FACTORY", result=cfg
                )
                raise PermissionError(f"{cfg.code}: {cfg.message}")

        LiveTradingTransitionGuard(session).require_active()

        uba_id = user_broker_account_id
        if uba_id is None:
            uba_id = parse_user_broker_credential_ref(credential_ref)

        # 사용자 UBA LIVE → Vault 필수 (env 자동 대체 금지)
        if uba_id is not None and not uses_system_shared_credential:
            if is_system_shared_credential_ref(credential_ref):
                raise PermissionError(
                    "User LIVE order cannot use SYSTEM_SHARED credential"
                )
            if code == "KIWOOM":
                if not settings.kiwoom_live_order_enabled:
                    raise PermissionError(
                        "KIWOOM_LIVE_ORDER_ENABLED must be true"
                    )
                return build_kiwoom_adapter_for_uba(session, int(uba_id))
            if code == "UPBIT":
                if not settings.upbit_live_order_enabled:
                    raise PermissionError(
                        "UPBIT_LIVE_ORDER_ENABLED must be true"
                    )
                return build_upbit_adapter_for_uba(session, int(uba_id))
            raise ValueError(
                f"Unsupported broker: environment={environment}, "
                f"broker={broker_code}"
            )

        # 명시적 운영 공용(SYSTEM_ENV) 경로만 env Credential 허용
        if code == "KIWOOM":
            if not settings.kiwoom_live_order_enabled:
                raise PermissionError(
                    "KIWOOM_LIVE_ORDER_ENABLED must be true"
                )
            return KiwoomBrokerAdapter()

        if code == "UPBIT":
            if not settings.upbit_live_order_enabled:
                raise PermissionError(
                    "UPBIT_LIVE_ORDER_ENABLED must be true"
                )
            return UpbitBrokerAdapter(settings=settings)

        raise ValueError(
            f"Unsupported broker: environment={environment}, "
            f"broker={broker_code}"
        )
