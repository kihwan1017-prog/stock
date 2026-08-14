# MENU M4-0 — Admin Operations Consolidation Precheck

**Mode:** DESIGN / PRECHECK ONLY · **Verdict:** `OPERATIONS_CONSOLIDATION_DESIGN_READY`  
**Date:** 2026-08-14  
**Baseline:** `90bbaef8d1df07ffbe73895a3adf92d168b07b3b` (M3-B)  
**Input:** M1 inventory · M2 IA · M3-A/M3-B committed menu

> Production menu/page/route/component/API **변경 없음**.  
> M2의 “`/admin/operations` = 자동매매 허브” 가정은 **현재 소스와 불일치** → 본 문서가 조정안.

---

## 0. 조사 범위

**Core (6):** `/admin/operations` · `/admin/trading` · `/admin/operations-dashboard` · `/admin/monitoring` · `/admin/recovery` · `/admin/risk`

**Xref (6):** `/admin/operations/preflight` · `/admin/scheduler` · `/admin/live-validation/upbit` · `/admin/accounts` · `/admin/upbit` · `/admin/dashboard` (+ orders/outbox 참조)

조사 route 수: **12** (core 6 + xref 6)

---

## 1. 페이지 Inventory (요약)

| route | page | primary | secondary | mutation | menu | permission |
|-------|------|---------|-----------|----------|------|------------|
| `/admin/operations` | `operations/page.tsx` | 시스템 운영 **런치패드** (health/DB/backup/broker 요약 + 타일) | Scheduler job 태그, audit 5건 | **READ_ONLY** | 리스크·운영 → 운영센터 | `menu:scheduler` |
| `/admin/trading` | `trading/page.tsx` | **Scope Runtime + Realtime Hub 제어** | deprecated JSON status | **HIGH** (runtime pause/resume/stop, hub reconnect) | 거래 → 자동매매관리 | `menu:trading` |
| `/admin/operations-dashboard` | `operations-dashboard/page.tsx` | 거래 운영 **조회 전용** 대시보드 (STEP 8-11A) | 계좌/주문/리스크/스케줄러/포지션/알림/감사 탭 | **READ_ONLY** (명시: LIVE/ARM/주문/Resume 없음) | 리스크·운영 → 통합 모니터링 | `menu:scheduler` |
| `/admin/monitoring` | `monitoring/page.tsx` | 인프라 **시스템 모니터링** (STEP61 overview/live/ready) | broker/scheduler/AI/risk JSON 섹션 | **READ_ONLY** | 운영관리 → 시스템 모니터링 | `menu:monitoring` |
| `/admin/recovery` | `recovery/page.tsx` | Broker/Paper **Recovery 실행·Conflict·Lock** | Recovery Scheduler enable/run-now | **HIGH** | 리스크·운영 → 장애 복구 | (menu permission 없음, admin role) |
| `/admin/risk` | `risk/page.tsx` | Kill Switch · 시스템/유저 리스크 설정 | LIVE 승인 토글, 거래 플래그, account_paused | **HIGH** | 리스크·운영 → 리스크 관리 | `menu:risk` |
| `/admin/operations/preflight` | `preflight/page.tsx` + `RuntimePreflightPanel` | LIVE ON 전 점검 **READ** | LIVE ON 버튼은 **disabled dummy** (실제어 아님) | **READ_ONLY** | 리스크·운영 → Pre-flight | `menu:scheduler` |
| `/admin/scheduler` | `scheduler/page.tsx` | Jobs execute / run-now | Market calendar | **MEDIUM–HIGH** (`ops:execute`) | 리스크·운영 → 스케줄러 | `menu:scheduler` |
| `/admin/accounts` + `/admin/upbit` | 동일 `AdminUpbitLiveUbaPanel` | **LIVE ON/OFF · ARM/DISARM · Trading Scheduler RUN/PAUSE** | Worker/Outbox **상태만** | **HIGH** (두 페이지에 **동일 컴포넌트 이중 마운트**) | 계좌 / 업비트 계좌 | `menu:accounts` / `menu:upbit` |

주요 컴포넌트:

- operations: `OPERATION_CENTER_TILES` (딥링크만)
- trading: `AdminRuntimePanel`, `AdminRealtimeHubPanel`
- ops-dashboard: 페이지 내 Tabs (overview/accounts/orders/risk/schedulers/positions/alerts/audit)
- recovery: `RecoverySchedulerPanel`, `RecoveryConflictPanel`, `RecoveryDistributedLockPanel`
- dashboard home: `OperationsCenterDashboard` (별도 API `GET operations-center summary`, RO)

---

## 2. Feature Matrix (core 6 + 핵심 xref)

값: `NONE` · `READ_ONLY` · `CONTROL` · `DUPLICATE_READ` · `DUPLICATE_CONTROL`

| Feature | operations | trading | ops-dashboard | monitoring | recovery | risk | accounts/upbit |
|---------|------------|---------|---------------|------------|----------|------|----------------|
| HEALTH | DUPLICATE_READ (`GET /health`) | NONE | READ_ONLY (overview DB/broker) | DUPLICATE_READ (`GET /health` + overview) | NONE | NONE | NONE |
| SYSTEM_STATUS | READ_ONLY | NONE | READ_ONLY | READ_ONLY | NONE | NONE | NONE |
| MARKET_FEED | NONE | CONTROL (Realtime Hub reconnect/rewarm) | NONE | NONE | NONE | NONE | READ_ONLY (status) |
| RUNTIME_STATUS | NONE | CONTROL | READ_ONLY (counts) | NONE | NONE | NONE | READ_ONLY |
| RUNTIME_CONTROL | NONE | **CONTROL** (canonical) | NONE | NONE | NONE | NONE | NONE (UBA LIVE ≠ scope runtime) |
| SCHEDULER_STATUS | READ_ONLY (job tags) | NONE | READ_ONLY (trading/tracking/post_fill/recovery) | READ_ONLY | READ_ONLY | NONE | READ_ONLY (trading sched) |
| SCHEDULER_CONTROL | NONE | NONE | NONE | NONE | CONTROL (recovery jobs) | NONE | **CONTROL** trading RUN/PAUSE |
| LIVE_PREFLIGHT | tile link | NONE | NONE | NONE | NONE | NONE | gates LIVE ON |
| LIVE_CONTROL | NONE | NONE | NONE | NONE | NONE | **DUPLICATE_CONTROL** (`setAdminLiveOrderEnabled`) | **DUPLICATE_CONTROL** (동일 API + ARM 시퀀스) |
| ARM_CONTROL | NONE | NONE | NONE | NONE | NONE | NONE | **DUPLICATE_CONTROL** (accounts+upbit) |
| WORKER_STATUS | NONE | NONE | NONE | NONE | NONE | NONE | READ_ONLY |
| WORKER_CONTROL | NONE | NONE | NONE | NONE | NONE | NONE | **NONE** (FE mutation 없음) |
| OUTBOX_STATUS | NONE | NONE | READ_ONLY (orders tab) | READ_ONLY (orders today) | NONE | NONE | READ_ONLY |
| OUTBOX_FENCING | NONE | NONE | NONE | NONE | NONE | NONE | 상태 표시 |
| AMBIGUOUS_ORDER | NONE | NONE | NONE | NONE | NONE | NONE | CONTROL (`/admin/upbit` only) |
| RECOVERY | link | NONE | READ_ONLY (recovery sched state) | NONE | **CONTROL** | NONE | NONE |
| RECONCILIATION | NONE | NONE | NONE | NONE | CONTROL (conflict import) | NONE | NONE |
| ACCOUNT_CONNECTION | READ_ONLY (broker card) | NONE | READ_ONLY | READ_ONLY (broker) | CONTROL (account recovery) | READ_ONLY (live accounts) | CONTROL (credential/LIVE) |
| CREDENTIAL_STATUS | READ_ONLY | NONE | READ_ONLY | NONE | NONE | NONE | CONTROL |
| RISK_SUMMARY | NONE | NONE | READ_ONLY | READ_ONLY | NONE | CONTROL | NONE |
| RISK_CONFIG | NONE | NONE | NONE | NONE | NONE | **CONTROL** | NONE |
| KILL_SWITCH | NONE | NONE | READ_ONLY (tag) | NONE | NONE | **CONTROL** | NONE |
| PAUSE_RESUME | NONE | CONTROL (runtime) | NONE | NONE | CONTROL (conflict resume) | CONTROL (`account_paused`) | CONTROL (trading pause via LIVE/sched) |
| AUDIT | READ_ONLY (5 events) | NONE | READ_ONLY | READ_ONLY (alerts) | NONE | NONE | NONE |
| NOTIFICATION | tile → telegram | NONE | READ_ONLY | READ_ONLY (telegram) | NONE | NONE | NONE |
| BROKER_STATUS | READ_ONLY | NONE | READ_ONLY | READ_ONLY | CONTROL | NONE | CONTROL |

---

## 3. 중복 분류

| ID | 대상 | Class | 근거 |
|----|------|-------|------|
| D1 | `AdminUpbitLiveUbaPanel` on `/admin/accounts` **and** `/admin/upbit` | **TRUE_DUPLICATE** | 동일 컴포넌트·동일 API·동일 LIVE/ARM/Scheduler 제어 |
| D2 | `setAdminLiveOrderEnabled` on **risk** + **UBA panel** | **TRUE_DUPLICATE** | 동일 LIVE 플래그 mutation. Risk는 시퀀스/ARM 게이트 약함 |
| D3 | `GET /health` operations + monitoring | **TRUE_DUPLICATE** | 동일 API 반복 표시 |
| D4 | ops-dashboard vs monitoring health | **SUMMARY_VS_DETAIL** | 다른 API (`ops-dashboard/overview` vs `monitoring/overview`) |
| D5 | `/admin/dashboard` OperationsCenterDashboard vs ops-dashboard | **SUMMARY_VS_DETAIL** | 또 다른 summary API |
| D6 | operations job tags vs `/admin/scheduler` | **SUMMARY_VS_DETAIL** + **STATUS_VS_CONTROL** | 목록 vs execute |
| D7 | ops-dashboard runtime counts vs trading `AdminRuntimePanel` | **STATUS_VS_CONTROL** | |
| D8 | Preflight dummy LIVE ON vs UBA LIVE ON | **STATUS_VS_CONTROL** | Preflight는 점검만 |
| D9 | ops-dashboard kill tag vs risk Kill Switch | **STATUS_VS_CONTROL** | |
| D10 | ops-dashboard risk tab vs `/admin/risk` | **SUMMARY_VS_DETAIL** | |
| D11 | Recovery scheduler vs jobs scheduler vs trading scheduler | **DIFFERENT_SCOPE** | |
| D12 | Scope runtime vs UBA LIVE | **DIFFERENT_SCOPE** | |
| D13 | operations tiles | **CROSS_DOMAIN_REFERENCE** | 딥링크 허브 |
| D14 | Worker enabled/running on UBA status | **STATUS_VS_CONTROL** | FE control 없음 |

집계: TRUE_DUPLICATE **3** · SUMMARY_VS_DETAIL **4** (D4–D6,D10; D6 dual) · STATUS_VS_CONTROL **5** · CROSS_DOMAIN_REFERENCE **1+** · DIFFERENT_SCOPE **2+**

상세 카운트(보고용): TRUE=3, SUMMARY_VS_DETAIL=8 (탭/카드 단위 포함), STATUS_VS_CONTROL=6, CROSS=4, DIFFERENT_SCOPE=5

---

## 4. 페이지 판정

### `/admin/operations`

**SYSTEM_OPS_LAUNCHPAD** (자동매매 허브 **아님**).

Primary: health/DB/migration/backup/broker 요약 + 전용 화면 타일.  
Preflight/scheduler/runtime/LIVE/recovery **제어 없음** (링크만).

`AUTOTRADING_OPERATIONS_HUB`로 쓰려면 LIVE/ARM/Runtime을 **이 페이지로 옮기는 HIGH 작업**이 필요. **권장: 옮기지 말고** 시스템 런치패드로 KEEP. 자동매매 허브는 `trading` + `operations-dashboard` + `preflight` 그룹으로 구성.

### `/admin/trading`

**Realtime runtime control**이지 **주문 관리가 아님**.

혼합: Runtime CONTROL + Hub CONTROL + deprecated JSON.  
주문/Outbox는 `/admin/orders`.  
M4: 이 페이지를 “자동매매 런타임” canonical로 KEEP. 주문 기능은 여기로 가져오지 않음.

### `/admin/operations-dashboard`

**Canonical read-only trading operations dashboard** (legacy 아님, health mirror만도 아님).

API 전용 (`/admin/operations-dashboard/*`). monitoring과 **다른 계약**.  
MERGE/HIDE 후보는 **메뉴 혼동**(둘 다 “모니터링”)뿐. route 삭제 금지.  
권장: KEEP_CANONICAL RO · 라벨을 “거래 운영 현황” 쪽으로 (M4-B).

### `/admin/monitoring`

**System monitoring detail** (인프라). ops-dashboard와 TRUE_DUPLICATE 아님.

M4 목표: **System Operations detail** 유지. Operations Hub의 탭으로 흡수하지 말 것 (API/목적이 다름).

### `/admin/recovery`

**KEEP_SEPARATE** (독립 route 우선). HIGH mutation (run-all, broker/account recovery, conflict approve/import, scheduler enable/run-now). Operations 탭 병합 금지.

### `/admin/risk`

Canonical: Kill Switch + risk config.  
Operations = summary only (ops-dashboard risk 탭).  
**예외:** Risk 페이지의 LIVE 토글은 UBA 패널과 TRUE_DUPLICATE → M4-C에서 Risk에서는 제거/비활성 후보 (page 기능 삭제가 아니라 mutation surface 단일화).

---

## 5. Canonical ownership (mutation 1 surface)

| 기능 | Canonical | 비고 |
|------|-----------|------|
| Runtime control | `/admin/trading` (`AdminRuntimePanel`) | |
| Realtime/Feed control | `/admin/trading` (`AdminRealtimeHubPanel`) | |
| Scheduler jobs execute | `/admin/scheduler` | |
| Trading Scheduler RUN/PAUSE | **UBA panel** — 마운트 **1곳만** (권장 `/admin/upbit` 또는 accounts 중 하나) | 현재 2곳 |
| Preflight | `/admin/operations/preflight` | RO |
| LIVE/ARM | **UBA panel 1 마운트** | Risk LIVE 토글은 비권장 중복 |
| Worker | status: UBA panel · **control FE 없음** | 후속, 새로 만들지 말 것(본 STEP) |
| Outbox list/fencing UI | `/admin/orders` | Ambiguous는 `/admin/upbit` (M5) |
| Risk config / Kill | `/admin/risk` | |
| Recovery | `/admin/recovery` | |
| Health (infra) | `/admin/monitoring` | |
| Health (trading ops RO) | `/admin/operations-dashboard` | |
| System launchpad | `/admin/operations` | |
| Order history | `/admin/orders` | |

---

## 6. Target Operations IA (코드 기준 조정)

M2 Admin top 9와 연결하되, **operations 페이지를 자동매매 허브로 재사용하지 않음**.

```text
운영 대시보드          → /admin/dashboard (OperationsCenterDashboard RO)
회원·권한
계좌                   → 전체/키움/업비트  (LIVE/ARM는 여기 또는 업비트 1곳)
시장 데이터
전략·후보              (M3-B 유지)
자동매매 운영          ← M4-B 그룹 (신규 top-level 대신 기존 리스크·운영 재배치 가능)
  ├─ 거래 운영 현황    /admin/operations-dashboard   RO
  ├─ 런타임·시세허브   /admin/trading                 CONTROL
  ├─ Pre-flight        /admin/operations/preflight    RO
  └─ (LIVE/ARM 링크)   /admin/upbit 또는 accounts     CONTROL — M5와 충돌 주의
거래·주문
  ├─ 주문/Outbox       /admin/orders
  ├─ 거래내역
  └─ 잔고·손익
리스크·안전
  ├─ 리스크/Kill       /admin/risk
  └─ LIVE 검증         /admin/live-validation/upbit
시스템 운영
  ├─ 운영센터          /admin/operations              launchpad
  ├─ 시스템 모니터링   /admin/monitoring
  ├─ 스케줄러/배치
  ├─ 장애 복구         /admin/recovery
  └─ 알림/Telegram
내 정보
```

menu.tsx 수정은 **M4-B**. 본 STEP 금지.

---

## 7. Route 정책 (mutation 금지 · 판정만)

| route | policy |
|-------|--------|
| `/admin/operations` | KEEP_CANONICAL (system launchpad) |
| `/admin/trading` | KEEP_CANONICAL (runtime hub) |
| `/admin/operations-dashboard` | KEEP_CANONICAL (RO trading ops) |
| `/admin/monitoring` | KEEP_CANONICAL (system health) |
| `/admin/recovery` | KEEP_CANONICAL |
| `/admin/risk` | KEEP_CANONICAL |
| `/admin/operations/preflight` | KEEP_DETAIL |
| `/admin/scheduler` | KEEP_DETAIL |
| `/admin/batch` | KEEP_DETAIL |
| `/admin/dashboard` | KEEP_DETAIL (RO summary; ops-dashboard와 SUMMARY) |
| `/admin/orders` | KEEP_CANONICAL (outbox) |
| `/admin/upbit` | KEEP_CANONICAL (M5 hub; LIVE panel 이중 마운트만 M4-C 정리) |
| `/admin/accounts` | KEEP_CANONICAL |
| `/admin/live-validation/upbit` | KEEP_DETAIL |

HIDE_FROM_MENU / REDIRECT_CANDIDATE / DEPRECATE_LATER: **없음** (기능 삭제 0).

---

## 8. Component 후보

| Component | 판정 |
|-----------|------|
| `AdminUpbitLiveUbaPanel` | REUSE_AS_IS · **단일 마운트** |
| `RuntimePreflightPanel` | KEEP_PAGE_LOCAL |
| `AdminRuntimePanel` | KEEP_PAGE_LOCAL |
| `AdminRealtimeHubPanel` | KEEP_PAGE_LOCAL |
| ops-dashboard tabs | KEEP_PAGE_LOCAL (M4-A에서 추출 금지) |
| `OperationsCenterDashboard` | KEEP_PAGE_LOCAL |
| Recovery* panels | KEEP_PAGE_LOCAL |
| HealthSummary | EXTRACT_SHARED **후속** (M4-A 범위 초과) |

---

## 9. API

UI IA 우선. Backend consolidation **불필요** (M4).

중복 호출:

- `GET /health` — operations, monitoring
- `GET /admin/live-order/accounts/{id}` LIVE PUT — risk + UBA panel
- ops-dashboard `*` vs operations-center summary vs monitoring overview — **의도적 다른 aggregator**

---

## 10. HIGH duplicate mutation

| Control | Surfaces | Canonical 목표 |
|---------|----------|----------------|
| LIVE ON/OFF | UBA×2 + risk toggle | UBA **1** |
| ARM ON/OFF | UBA×2 | UBA **1** |
| Trading Scheduler RUN/PAUSE | UBA×2 | UBA **1** |
| Kill Switch | risk only | risk |
| Scope Runtime pause/resume/stop | trading only | trading |
| Recovery apply / conflict | recovery only | recovery |
| Job execute | scheduler only | scheduler |
| Preflight LIVE 버튼 | dummy disabled | 제어 아님 |
| Worker start/stop | **없음** | 유지(추가 금지) |

---

## 11. Mutation risk (대표)

| Control | Risk |
|---------|------|
| health/status/ops-dashboard | READ_ONLY |
| Preflight refresh | READ_ONLY |
| Realtime hub reconnect | MEDIUM |
| Job execute / scheduler run-now | MEDIUM–HIGH |
| Runtime pause/resume/stop | HIGH |
| LIVE / ARM / Trading Scheduler RUN | HIGH |
| Kill Switch | HIGH |
| Recovery run / conflict approve | HIGH |
| account_paused / buy_enabled | HIGH |
| Risk settings save | MEDIUM |

HIGH control은 summary 화면과 분리 유지 (ops-dashboard는 이미 RO).

---

## 12. Implementation split

| Wave | 내용 | Risk |
|------|------|------|
| **M4-A** | RO 정리: ops-dashboard 라벨 명확화, operations↔monitoring↔dashboard 교차링크, TRUE_DUPLICATE 문서화. **제어 이동 없음** | LOW |
| **M4-B** | 메뉴 재배치만 (자동매매 운영 그룹). route/page 이동 없음 | LOW–MED |
| **M4-C** | LIVE/ARM 패널 단일 마운트 + Risk LIVE 토글 canonical화. Recovery/Kill 병합 금지 | HIGH |

M5(`/admin/upbit` 탭)와 M4-C는 충돌 가능 → M4-C는 “이중 마운트 제거”만, 업비트 허브 재설계는 M5.

---

## 13. 기능 삭제 후보

**0.** HIDE/DEPRECATE route 없음. Worker control 신설 금지.

보호: LIVE/ARM, Scheduler, Runtime, Worker(status), Preflight, Recovery, Risk, Kill, Outbox, Ambiguous, Feed, Scanner/Shadow/News — **유지**.

---

## 14. 자동매매 상태 (문서 snapshot, API 미호출)

- LIVE **NOT APPROVED** · ARM/Runtime 무단 변경 없음
- Technical Shadow: VALID≈32, next gate n≈50, TP apply 금지
- News A/B: `NEWS_AB_SAMPLE_ACCUMULATING`

---

## 15. Next

**M4-A** — READ-only operations status/dashboard consolidation (라벨·교차링크).  
승인 전 구현 금지.
