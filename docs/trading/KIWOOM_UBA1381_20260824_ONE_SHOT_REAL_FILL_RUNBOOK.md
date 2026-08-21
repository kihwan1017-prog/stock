# KIWOOM UBA1381 — 2026-08-24 ONE-SHOT REAL FILL RUNBOOK

**목적:** 다음 KRX 거래일(2026-08-24) 장중 운영자가 **한 번에** FIRST REAL FILL + binding + Strategy PnL + protective exit 경로를 증명한다.  
**금지:** 자동 스케줄러/에이전트 자동 실행. REAL 주문은 운영자 명시 승인 후에만.

**전제 (2026-08-21 기준):**
- UBA1381 V2: `daily_submit_limit=5`, `daily_filled_entry_limit=1`, opted-in
- V1 `daily_order_limit=1` 유지 (변경 금지)
- 오늘(08-21) policy = V1 / 08-24 policy = V2
- UBA1380 격리 유지 (mutation 금지)

---

## 0. 사전 체크 (주문 전)

1. Backend health UP, FE admin 로그인
2. `/admin/risk` user_id=61 → UBA1381 V2 stored **5 / 1**, legacy daily_order_limit **1**
3. DB READ-BACK:
   - `trading.user_broker_account_risk_setting` (1381) submit=5 filled=1
4. Kill Switch OFF (UBA:1381 / GLOBAL)
5. 수동 보유 11종목은 MANUAL 유지 — strategy binding으로 바꾸지 말 것

## 1. Preflight

```text
GET /api/v1/admin/autotrading/uba/1381/readiness
```

확인: risk.order_limit_policy_version_next_krx = `ORDER_LIMIT_V2_SUBMIT_AND_FILLED_ENTRY`  
(장중 today policy도 V2여야 함 — KST date >= 2026-08-22)

## 2. Account sync

운영 스크립트/관리자 계좌 조회로 잔고·포지션 스냅샷 갱신 (조회만).

## 3. Strategy PnL

```text
GET /api/v1/risk/daily-loss/strategy-owned?user_broker_account_id=1381&strategy_id=17579
```

manual MTM이 strategy loss에 섞이지 않는지 확인.

## 4. V2 5/1 확인

- submit usage / limit
- filled-entry usage / limit
- 기대: 장 시작 전 0/5, 0/1

## 5. KRX OPEN + REAL feed

- KIWOOM market realtime WS RUNNING
- symbol `034310` registered / ticks flowing

## 6. Warmup

- MA evaluator `warmup_status=READY` (completed daily closes ≥ long_window+1)
- WARMING_UP이면 주문 금지 — daily seed 완료 후 재확인

## 7. Activation → LIVE → ARM JIT → runtime

순서 고정:
1. Live activation create (TTL)
2. LIVE ON
3. ARM ON (JIT, 짧은 TTL)
4. Scoped runtime START (strategy 17579 / deployment 869)
5. Live outbox worker RUNNING

## 8. Marketable LIMIT 1주 ENTRY

- REAL BUY LIMIT 1주 (시장가 근접)
- 기대: ACCEPTED → (가능 시) FILL
- V2: submit 1/5; fill 시 filled 1/1

## 9. Binding + Strategy PnL

- `operation.strategy_position_binding` OPEN 1건 (entry_order_id 일치)
- Strategy PnL에만 반영
- duplicate fill replay → binding 중복 없음

## 10. Protective exit 확인

환경:
```text
POSITION_EXIT_MONITOR_LIVE_KIWOOM_ENABLED=true
```
(기본 OFF — 이 스텝에서만 ON 후 재시작 1회 허용)

- SL/TP/Trailing 또는 운영자 controlled SELL
- EXIT는 V2 ENTRY quota에 **미포함**

## 11. Post-fill reconcile

- BUY/SELL fill 후 POSITION_SYNC_PENDING 재시도 허용
- 즉시 false POSITION_MISMATCH terminal/Kill 금지

## 12. 종료

1. DISARM
2. LIVE OFF
3. runtime STOP
4. `POSITION_EXIT_MONITOR_LIVE_KIWOOM_ENABLED` 원복(OFF) 권장
5. 증거 JSON/로그 보관 (order_id, broker_order_id, binding_id, pnl snapshot)

---

## Abort conditions

- Kill active / Conflict / Recovery paused
- Warmup not READY
- V2 not opted-in or limits ≠ 5/1
- UBA1380 영향이 보이면 즉시 STOP

## Success criterion

`KIWOOM_FIRST_REAL_FILL_AND_EXIT_PROOF` — FILL + OPEN binding + Strategy PnL + (protective or controlled) EXIT 경로 증거.
