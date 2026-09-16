# KIWOOM GO-LIVE READINESS PRECHECK

**MODE:** READ-ONLY · **STEP K-G0**  
**Date:** 2026-08-16  
**HEAD:** `3bbf0cd`  
**Verdict:** **`KIWOOM_LIVE_BLOCKED`**  
**JSON:** [KIWOOM_GO_LIVE_READINESS_PRECHECK.json](KIWOOM_GO_LIVE_READINESS_PRECHECK.json)

Upbit 대기와 병행. 재개발이 아니라 **현재 존재 기능 기준** 실거래 준비도 감사. LIVE/ARM/주문 실행 **금지**.

---

## K-1. Inventory

| Area | Status |
|------|--------|
| Kiwoom broker adapter | **IMPLEMENTED** |
| REST / token / HTTP | **IMPLEMENTED** |
| Credential vault | **IMPLEMENTED** |
| UBA / account | **IMPLEMENTED** |
| Balance / positions sync | **PARTIAL** (snapshot 위주) |
| Orders create/cancel/modify/status | **IMPLEMENTED** (LIVE 미검증) |
| Executions / WS bridge | **PARTIAL** |
| Recovery | **PARTIAL** (ambiguous Upbit-only) |
| Paper path | **PARTIAL** |
| Scheduler / runtime / preflight | **PARTIAL** (preflight Upbit-centric) |
| Risk / kill switch | **IMPLEMENTED** (server-side) |

Evidence roots: `broker/kiwoom/*`, `credential_vault_service.py`, `order/outbox_*`, `trading/runtime_control_gates.py`, `api/v1/admin_live_ops_readiness.py`, `api/v1/admin_runtime_preflight.py`.

---

## K-2. Account / UBA (실측 READ)

| UBA | user_id | is_active | connection_status | live_order_enabled | live_armed |
|-----|---------|-----------|-------------------|--------------------|------------|
| 1338 | 427 | true | DISCONNECTED | false | false |
| 1349 | 433 | true | DISCONNECTED | false | false |
| 1381 | 61 | true | CONNECTED | false | false |

- Kiwoom UBA linked credentials (`revoked_at IS NULL`): **0**  
- Risk settings rows for 1338/1349/1381: **0**  
- Sensitive credential values: **not printed**

| Flag | Value |
|------|-------|
| KIWOOM_ACCOUNT_READY | **READY_WITH_LIMITATIONS** (UBA 존재, LIVE/ARM OFF) |
| KIWOOM_CREDENTIAL_READY | **NO** (linked active credential 0) |
| KIWOOM_CONNECTION_READY | **READY_WITH_LIMITATIONS** (1381 CONNECTED only; others DISCONNECTED) |

---

## K-3. Broker adapter lifecycle

| Op | Verdict | Path |
|----|---------|------|
| create/submit | **PASS** | `KiwoomBrokerAdapter.submit_order` |
| cancel | **PASS** | `cancel_order` |
| modify/replace | **PASS** | `replace_order` |
| status query | **PASS** | `get_order` / inquiry |
| execution query / WS | **PARTIAL** | `ws_*` + ExecutionSync |
| balance / positions | **PARTIAL** | account sync → snapshots; trading Position WRITE gap |

---

## K-4. Paper

경로 존재: candidate/runtime → risk → Order/Outbox → `PaperBrokerAdapter` → paper fill → Position.  
Kiwoom 전용 paper E2E 증거 부족 · P0-5 무인 auto-fill 미완.

**KIWOOM_PAPER_READY = NO** (경로 PARTIAL; 무인 READY 아님).  
Blockers: P0-5 · paper/Kiwoom label 약함 · E2E 미검증.

---

## K-5. Order / Outbox (관찰만 · 수정 금지)

공용 TradingOrder/Outbox에 Outbox resolver → Factory/Mock Kiwoom 연결.  
Idempotency/retry/AMBIGUOUS/partial fill: 공용 worker + ExecutionSync.  
**본 PRECHECK에서 TradingOrder/Outbox 변경 없음.**

**KIWOOM_ORDER_PATH_READY = READY_WITH_LIMITATIONS**

---

## K-6. Risk

Server-side: `live_safety_pipeline`, kill switch, `runtime_control_gates` (pause/recovery/connection).  
UI-only 차단 아님.

**KIWOOM_RISK_READY = YES** (gates 존재; LIVE 승인 전제와 별개)

---

## K-7. Recovery

Kiwoom: account/pending sync · remote-only → conflict/manual.  
Upbit ambiguous not-submitted resolver는 **UPBIT only**.  
자동/수동 경계: Kiwoom는 수동 리뷰 비중 큼.

**KIWOOM_RECOVERY_READY = READY_WITH_LIMITATIONS**

---

## K-8. Preflight

`admin_live_ops_readiness` / `runtime_preflight_service.run_for_uba` → **UPBIT 중심**.  
Kiwoom 전용 readiness 표면 **MISSING**.

**KIWOOM_PREFLIGHT_READY = NO**

---

## K-9. Runtime control

LIVE/ARM/Scheduler fail-closed 코드 존재 (`runtime_control_gates`, factory, live outbox worker 기본 OFF).  
역순 종료 경로 문서/코드상 가능. **이번 STEP 실행 금지.**

**KIWOOM_RUNTIME_READY = READY_WITH_LIMITATIONS**

---

## K-10. Market session

KRX `Asia/Seoul` calendar · preopen/postclose recovery jobs · health: today session **CLOSED** (특수일).  
LIVE Kiwoom 주문과 calendar gate 연결됨.

**Market-session readiness = YES** (calendar UP)

---

## K-11. Credential ↔ connection

Vault `sync_uba_connection_status` 존재.  
현재: linked Kiwoom credential **0** vs UBA 1381 **CONNECTED** → **mismatch / drift 가능** (Upbit VERIFIED+pending 유사 클래스).

---

## K-12. Real order path (추적만)

Signal → RiskIntegratedRealtimeOrderExecutor → OrderExecution → Outbox → Factory → KiwoomAdapter.  
Gates: LIVE flags OFF · ARM OFF · kill/pause · connection.  
**P0-1** default broker still `"KIWOOM"` fallback.  
**P0-2** fill 이후 trading Position WRITE OPEN.

---

## K-13. Readiness matrix

| Key | Value |
|-----|-------|
| KIWOOM_ACCOUNT_READY | READY_WITH_LIMITATIONS |
| KIWOOM_CREDENTIAL_READY | **NO** |
| KIWOOM_CONNECTION_READY | READY_WITH_LIMITATIONS |
| KIWOOM_PAPER_READY | **NO** |
| KIWOOM_RISK_READY | YES |
| KIWOOM_RECOVERY_READY | READY_WITH_LIMITATIONS |
| KIWOOM_PREFLIGHT_READY | **NO** |
| KIWOOM_RUNTIME_READY | READY_WITH_LIMITATIONS |
| KIWOOM_ORDER_PATH_READY | READY_WITH_LIMITATIONS |
| KIWOOM_LIVE_READY | **NO** |

---

## K-14. Severity

### BLOCKER (실거래 차단)
1. **P0-2** Fill → TradingOrder → **Position/Balance/PnL WRITE** 단절  
2. Kiwoom linked **credential 부재** (실측 0) → LIVE 불가  
3. Canonical **LIVE NOT APPROVED** + flags OFF (운영 차단)

### HIGH
- Live-ops / preflight **Upbit-centric**  
- Kiwoom AMBIGUOUS / remote-only 자동화 부재  
- **P0-1** default `"KIWOOM"` residual (SHARED)

### MEDIUM
- Credential↔connection drift  
- Risk settings row 부재 (UBA 3건)  
- Paper 무인 P0-5

### LOW
- FE cosmetic / mock default (`use_mock=true`) 표기

---

## K-15. Parallel classification

| Task | Class |
|------|-------|
| P0-2 Position WRITE | **K_ONLY** · SAFE_PARALLEL vs U-TERM |
| Kiwoom preflight/live-ops | **K_ONLY** |
| Kiwoom ambiguous resolver | **K_ONLY** |
| P0-1 broker resolve commit | **SHARED** |
| TradingOrder/Outbox schema | **SHARED** |
| Kill/ARM/runtime gates change | **SHARED** |
| KRX calendar verify | **SAFE_PARALLEL** |
| Same endpoint as Upbit live-ops rewrite | **U_CONFLICT** |
| Shadow evaluator termination | **U_ONLY** |

---

## K-16. Waves (필요한 것만)

| Wave | Scope |
|------|-------|
| **K-A** | Account/credential/connection heal (UBA 실측 정합) |
| **K-B** | **P0-2 LIVE Position/Balance/PnL WRITE** |
| **K-C** | Kiwoom preflight + recovery ambiguous parity |
| **K-D** | Paper path harden (P0-5) — LIVE 비선행 |
| **K-E** | Small LIVE readiness (승인 후) |

불필요 wave 없음 — Paper를 LIVE보다 앞세울 필요는 있으나 GO-LIVE BLOCKER는 K-B(+credential).

---

## K-17. Verdict

**`KIWOOM_LIVE_BLOCKED`**

**Next K STEP (exactly one):** **`KIWOOM_P0-2_LIVE_POSITION_WRITE`**

(선행 계정/credential 정합은 K-A로 병행 READ/운영 가능하나, 코드 Next는 P0-2 장부 닫기.)

---

## Runtime safety (READ)

| Item | Value |
|------|-------|
| TradingOrder | **241** |
| Outbox | **52** |
| Upbit LIVE | **false** |
| Kiwoom LIVE | **false** (`use_mock=true`) |
| outbox_scheduler_running | **false** |
| kiwoom_order_ws running | **false** |
| production/DB mutation | **0** |
| commit/push | **NO** |
