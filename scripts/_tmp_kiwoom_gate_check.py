"""Kiwoom transition validate 사전조건 (시크릿 미출력)."""

from stock_platform.common.settings import get_settings

s = get_settings()
checks = {
    "kiwoom_mock": s.kiwoom_use_mock,
    "kiwoom_live": s.kiwoom_live_order_enabled,
    "account_present": bool(s.kiwoom_account_number.strip()),
    "app_cred_present": bool(s.kiwoom_app_key.strip())
    and bool(s.kiwoom_secret_key.strip()),
    "ws_present": bool(s.kiwoom_order_ws_subscribe_json.strip()),
    "recovery_start_trading": s.kiwoom_recovery_start_trading,
    "live_activation_ttl_hours": s.live_activation_ttl_hours,
}
for key, value in checks.items():
    print(f"{key}={value!r}")
