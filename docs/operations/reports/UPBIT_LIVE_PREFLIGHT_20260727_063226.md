# Upbit LIVE Preflight — STEP 8-9B (20260727_063226)

- checked_at: `2026-07-26T21:32:26.059594+00:00`
- verdict: **NOT_READY**
- execute_live_ran: `False`
- release_blocker_count: `2`

## 1. DB
```json
{
  "connected": true,
  "database": "stock_platform",
  "db_user": "stock_app",
  "alembic_head": "o4e5f6a7b8c9",
  "uba_total": 0,
  "expected_alembic": "o4e5f6a7b8c9",
  "alembic_ok": true
}
```

## 2. UBA 후보 (마스킹)
```json
[]
```

> 대상 UBA는 운영자가 직접 선택. 자동 선택 금지.

## 3. Kill Switch / System
```json
{
  "kill_switch": {
    "status": "INACTIVE",
    "reason": null
  },
  "system": {
    "upbit_use_mock": true,
    "upbit_live_order_enabled_setting": false,
    "env_upbit_keys_configured": false,
    "post_fill_verify_enabled": true,
    "post_fill_verify_ttl_seconds": 60,
    "upbit_live_track_enabled": true,
    "upbit_live_track_poll_seconds": 2,
    "upbit_live_smoke_order_watch_seconds": 60,
    "upbit_live_smoke_auto_cancel": true,
    "arm_ttl_default_seconds": 300,
    "max_smoke_amount": "10000",
    "trading_scheduler_treat_paused_flag": false
  }
}
```

## 4. Risk / Open / Post-fill
```json
{
  "db_open_orders_upbit": 0,
  "unknown_runs": 0,
  "manual_review_runs": 0,
  "pending_post_fill": 0,
  "waiting_snapshot": 0,
  "mismatch_post_fill": 0,
  "expired_post_fill": 0,
  "failed_post_fill": 0,
  "live_validation_by_status": {},
  "manual_review_flag_count": 0,
  "post_fill_by_status": {},
  "pending_post_fill_stale_ttl": 0
}
```

## 5. Market Quotes & Limit Candidates
```json
[
  {
    "market": "KRW-BTC",
    "trade_price": "94409000.0",
    "bid_1": "94409000",
    "ask_1": "94433000",
    "tick_size": "1000",
    "acc_trade_volume_24h": "321.55202752",
    "qty_for_5000": "0.00005295",
    "estimated_amount": "5000.2274",
    "estimated_fee": "2.5001",
    "min_notional_ok": true,
    "slippage_note": "candidates evaluated vs trade_price",
    "orderable": true,
    "candidates": [
      {
        "label": "ask_1",
        "limit_price": "94433000",
        "quantity": "0.00005295",
        "estimated_amount": "5000.2274",
        "estimated_fee": "2.5001",
        "fill_likelihood": "즉시체결 가능성 높음",
        "unfilled_likelihood": "낮음",
        "auto_cancel_seconds": 60,
        "slippage_ok": true,
        "min_notional_ok": true,
        "orderable": true
      },
      {
        "label": "ask_1_minus_1tick",
        "limit_price": "94432000",
        "quantity": "0.00005295",
        "estimated_amount": "5000.1744",
        "estimated_fee": "2.5001",
        "fill_likelihood": "중간 — 호가 개선 시 체결",
        "unfilled_likelihood": "중간~높음",
        "auto_cancel_seconds": 60,
        "slippage_ok": true,
        "min_notional_ok": true,
        "orderable": true
      },
      {
        "label": "within_slippage_cap",
        "limit_price": "94433000",
        "quantity": "0.00005295",
        "estimated_amount": "5000.2274",
        "estimated_fee": "2.5001",
        "fill_likelihood": "한도 내 — 가격에 따라 가변",
        "unfilled_likelihood": "가변",
        "auto_cancel_seconds": 60,
        "slippage_ok": true,
        "min_notional_ok": true,
        "orderable": true
      }
    ],
    "error": null
  },
  {
    "market": "KRW-ETH",
    "trade_price": "2798000.0",
    "bid_1": "2796000",
    "ask_1": "2797000",
    "tick_size": "1000",
    "acc_trade_volume_24h": "8533.96086903",
    "qty_for_5000": "0.00178763",
    "estimated_amount": "5000.0011",
    "estimated_fee": "2.5000",
    "min_notional_ok": true,
    "slippage_note": "candidates evaluated vs trade_price",
    "orderable": true,
    "candidates": [
      {
        "label": "ask_1",
        "limit_price": "2797000",
        "quantity": "0.00178763",
        "estimated_amount": "5000.0011",
        "estimated_fee": "2.5000",
        "fill_likelihood": "즉시체결 가능성 높음",
        "unfilled_likelihood": "낮음",
        "auto_cancel_seconds": 60,
        "slippage_ok": true,
        "min_notional_ok": true,
        "orderable": true
      },
      {
        "label": "ask_1_minus_1tick",
        "limit_price": "2796000",
        "quantity": "0.00178827",
        "estimated_amount": "5000.0029",
        "estimated_fee": "2.5000",
        "fill_likelihood": "중간 — 호가 개선 시 체결",
        "unfilled_likelihood": "중간~높음",
        "auto_cancel_seconds": 60,
        "slippage_ok": true,
        "min_notional_ok": true,
        "orderable": true
      },
      {
        "label": "within_slippage_cap",
        "limit_price": "2797000",
        "quantity": "0.00178763",
        "estimated_amount": "5000.0011",
        "estimated_fee": "2.5000",
        "fill_likelihood": "한도 내 — 가격에 따라 가변",
        "unfilled_likelihood": "가변",
        "auto_cancel_seconds": 60,
        "slippage_ok": true,
        "min_notional_ok": true,
        "orderable": true
      }
    ],
    "error": null
  },
  {
    "market": "KRW-XRP",
    "trade_price": "1607.0",
    "bid_1": "1607",
    "ask_1": "1608",
    "tick_size": "5",
    "acc_trade_volume_24h": "14647592.1267477",
    "qty_for_5000": "3.11526480",
    "estimated_amount": "5000.0000",
    "estimated_fee": "2.5000",
    "min_notional_ok": true,
    "slippage_note": "candidates evaluated vs trade_price",
    "orderable": true,
    "candidates": [
      {
        "label": "ask_1",
        "limit_price": "1605",
        "quantity": "3.11526480",
        "estimated_amount": "5000.0000",
        "estimated_fee": "2.5000",
        "fill_likelihood": "즉시체결 가능성 높음",
        "unfilled_likelihood": "낮음",
        "auto_cancel_seconds": 60,
        "slippage_ok": true,
        "min_notional_ok": true,
        "orderable": true
      },
      {
        "label": "ask_1_minus_1tick",
        "limit_price": "1600",
        "quantity": "3.12500000",
        "estimated_amount": "5000.0000",
        "estimated_fee": "2.5000",
        "fill_likelihood": "중간 — 호가 개선 시 체결",
        "unfilled_likelihood": "중간~높음",
        "auto_cancel_seconds": 60,
        "slippage_ok": true,
        "min_notional_ok": true,
        "orderable": true
      },
      {
        "label": "within_slippage_cap",
        "limit_price": "1605",
        "quantity": "3.11526480",
        "estimated_amount": "5000.0000",
        "estimated_fee": "2.5000",
        "fill_likelihood": "한도 내 — 가격에 따라 가변",
        "unfilled_likelihood": "가변",
        "auto_cancel_seconds": 60,
        "slippage_ok": true,
        "min_notional_ok": true,
        "orderable": true
      }
    ],
    "error": null
  }
]
```

## 6. ARM Readiness (미실행)
```json
{
  "live_approval_possible": true,
  "arm_possible_when_live_on": true,
  "arm_ttl_seconds_default": 300,
  "admin_role_required": true,
  "arm_token_security": "one-time hash only; plaintext never stored/logged",
  "rearm_invalidates_previous_token": true,
  "disarm_supported": true,
  "expire_turns_live_off": true,
  "armed_this_step": false,
  "arm_token_created": false,
  "note": "STEP 8-9B에서는 ARM을 실행하지 않음"
}
```

## 7. DRY RUN Commands (PowerShell)
### KRW-BTC / ask_1
```powershell
python scripts/run_upbit_live_smoke_test.py `
  --uba-id <UBA_ID> `
  --market KRW-BTC `
  --side BUY `
  --amount 5000 `
  --limit-price 94433000 `
  --dry-run
```

### KRW-BTC / ask_1_minus_1tick
```powershell
python scripts/run_upbit_live_smoke_test.py `
  --uba-id <UBA_ID> `
  --market KRW-BTC `
  --side BUY `
  --amount 5000 `
  --limit-price 94432000 `
  --dry-run
```

### KRW-BTC / within_slippage_cap
```powershell
python scripts/run_upbit_live_smoke_test.py `
  --uba-id <UBA_ID> `
  --market KRW-BTC `
  --side BUY `
  --amount 5000 `
  --limit-price 94433000 `
  --dry-run
```

### KRW-ETH / ask_1
```powershell
python scripts/run_upbit_live_smoke_test.py `
  --uba-id <UBA_ID> `
  --market KRW-ETH `
  --side BUY `
  --amount 5000 `
  --limit-price 2797000 `
  --dry-run
```

### KRW-ETH / ask_1_minus_1tick
```powershell
python scripts/run_upbit_live_smoke_test.py `
  --uba-id <UBA_ID> `
  --market KRW-ETH `
  --side BUY `
  --amount 5000 `
  --limit-price 2796000 `
  --dry-run
```

### KRW-ETH / within_slippage_cap
```powershell
python scripts/run_upbit_live_smoke_test.py `
  --uba-id <UBA_ID> `
  --market KRW-ETH `
  --side BUY `
  --amount 5000 `
  --limit-price 2797000 `
  --dry-run
```

### KRW-XRP / ask_1
```powershell
python scripts/run_upbit_live_smoke_test.py `
  --uba-id <UBA_ID> `
  --market KRW-XRP `
  --side BUY `
  --amount 5000 `
  --limit-price 1605 `
  --dry-run
```

### KRW-XRP / ask_1_minus_1tick
```powershell
python scripts/run_upbit_live_smoke_test.py `
  --uba-id <UBA_ID> `
  --market KRW-XRP `
  --side BUY `
  --amount 5000 `
  --limit-price 1600 `
  --dry-run
```

### KRW-XRP / within_slippage_cap
```powershell
python scripts/run_upbit_live_smoke_test.py `
  --uba-id <UBA_ID> `
  --market KRW-XRP `
  --side BUY `
  --amount 5000 `
  --limit-price 1605 `
  --dry-run
```

## 8. DRY RUN Results
```json
[
  {
    "status": "BLOCKER",
    "ready": false,
    "blockers": [
      "DRY_RUN_NOT_EXECUTED: UPBIT UBA 후보 0건"
    ],
    "warnings": [],
    "note": "UBA 생성·Credential 등록 후 --run-dry-run --uba-id ... 로 재실행"
  }
]
```

## 9. Blockers / Warnings
```json
{
  "blockers": [
    "UBA: 운영 DB에 UPBIT UserBrokerAccount 후보가 0건",
    "UPBIT_USE_MOCK=true (LIVE 실주문 전 mock 해제 필요)"
  ],
  "warnings": [
    "UPBIT_LIVE_ORDER_ENABLED=false (실주문 전 명시적 활성화 필요)",
    "ENV_UPBIT_KEYS_NOT_CONFIGURED (UBA Vault Credential이 주 경로)",
    "실주문 명령 템플릿 미생성 — Release 게이트 미충족"
  ]
}
```

## 10. Live Command Template (실행 금지)
```json
null
```

## 11. Post-execution Checks
```json
{
  "powershell": [
    "# live_validation_run 최근 조회",
    ".venv\\Scripts\\python -c \"from sqlalchemy import text; from stock_platform.database.session import get_session_factory; s=get_session_factory()(); rows=s.execute(text('SELECT run_id,status_code,broker_order_status,manual_review_required,created_at FROM trading.live_validation_run ORDER BY created_at DESC LIMIT 5')).mappings().all(); print([dict(r) for r in rows]); s.close()\"",
    "# Kill Switch / LIVE / ARM 상태 점검은 Admin UI 또는 기존 조회 API 사용",
    "# Broker 미체결: Upbit Open API list_orders(state=wait) — 주문/취소 호출 금지"
  ],
  "sql_readonly": [
    "SELECT run_id, status_code, broker_order_status, manual_review_required, created_at FROM trading.live_validation_run ORDER BY created_at DESC LIMIT 20;",
    "SELECT status_code, count(*) FROM trading.post_fill_verification GROUP BY 1;",
    "SELECT user_broker_account_id, live_order_enabled, live_armed, arm_expires_at FROM trading.user_broker_account WHERE upper(broker_code)='UPBIT';",
    "SELECT active, reason, activated_at FROM operation.kill_switch WHERE scope_code='GLOBAL' LIMIT 1;",
    "SELECT order_id, status_code, broker_order_id, created_at FROM trading.trading_order WHERE broker_code='UPBIT' ORDER BY created_at DESC LIMIT 20;"
  ],
  "manual_checks": [
    "Telegram 알림 수신 여부",
    "LIVE OFF / DISARM 확인",
    "Runtime Pause / 거래 Scheduler Pause 유지",
    "Tracking Scheduler 정상(미확정 주문 폴링)",
    "Audit 이벤트 존재"
  ]
}
```

## 12. Emergency Procedures
```json
{
  "UNKNOWN": [
    "추가 주문 금지",
    "Admin Live Validation 대시보드에서 Broker 재조회",
    "Manual Review Required 표시 확인",
    "Kill Switch 검토"
  ],
  "CANCEL_FAILED": [
    "Kill Switch ON (Admin Risk API)",
    "LIVE OFF / DISARM (정상 API)",
    "거래 Scheduler Pause 유지",
    "Broker 콘솔에서 미체결 수동 확인"
  ],
  "PARTIAL_FILL": [
    "Post-fill Verification 상태 조회",
    "부분 체결 잔량 자동취소 여부 확인",
    "추가 주문 금지"
  ],
  "BROKER_DOWN": [
    "신규 주문 금지",
    "Kill Switch 검토",
    "Tracker/Recovery Scheduler 상태 확인"
  ],
  "POST_FILL_MISMATCH": [
    "Manual Review",
    "잔고 스냅샷 재동기화(조회/sync API)",
    "추가 주문 금지"
  ],
  "POST_FILL_EXPIRED": [
    "TTL/재시도 설정 확인",
    "Manual Review",
    "추가 주문 금지"
  ],
  "LIVE_OFF_FAILED": [
    "Admin API 재시도",
    "Kill Switch ON",
    "ARM expire / DISARM API"
  ],
  "DISARM_FAILED": [
    "Admin DISARM 재시도",
    "ARM TTL 만료 대기(자동 LIVE OFF)",
    "Kill Switch 검토"
  ],
  "TRACKER_STOPPED": [
    "upbit_live_track_enabled 설정 확인",
    "프로세스/스케줄러 재기동(정상 기동 경로)",
    "미확정 주문 Manual Review"
  ],
  "TELEGRAM_MISSING": [
    "publisher 설정·dry-run 점검",
    "Audit 로그로 이벤트 대체 확인"
  ],
  "note": "DB 직접 UPDATE/DELETE SQL은 제공하지 않음"
}
```

## 13. UBA Detail (운영자 선택용 — 시크릿 없음)
```json
[]
```

## Notes
- 실주문(--execute-live) 미실행
- ARM 미실행 / arm_token 미생성
- UBA·Market 자동 선택 금지 — 운영자 수동 선택
