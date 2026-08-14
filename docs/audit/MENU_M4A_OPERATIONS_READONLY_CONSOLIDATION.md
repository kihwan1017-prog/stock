# MENU M4-A — READ-ONLY Operations Status / Dashboard Consolidation

**Mode:** APPLY (labels / headings / cross-links only)  
**Verdict:** `MENU_M4A_READY_WITH_LIMITATIONS`  
**Date:** 2026-08-14  
**Input:** [MENU_M4_OPERATIONS_PRECHECK.md](./MENU_M4_OPERATIONS_PRECHECK.md)  
**Baseline:** M3-B `90bbaef` + M4-0 `OPERATIONS_CONSOLIDATION_DESIGN_READY`

> CONTROL 이동 없음. `/admin/operations`를 `AUTOTRADING_OPERATIONS_HUB`로 바꾸지 않음.  
> commit/push 하지 않음. M4-B / M4-C 자동 진행 금지.

---

## 1. M4-0 설계 ↔ 실제 변경 대응표

| Canonical ownership (M4-0) | Route | M4-A 조치 | CONTROL |
|----------------------------|-------|-----------|---------|
| Runtime | `/admin/trading` | 제목/메뉴 **자동매매 Runtime**. 주문·Outbox / Pre-flight / 거래 운영 현황 링크 | 유지 (Start/Stop 4) |
| Scheduler jobs | `/admin/scheduler` | Launchpad 타일 제목 **스케줄러**. RUN/PAUSE 복제 없음 | 유지 (해당 페이지) |
| Preflight | `/admin/operations/preflight` | cross-link만 | 미수정 |
| Outbox | `/admin/orders` | 타일·trading 링크. detail/control 복제 없음 | 유지 |
| Risk / Kill | `/admin/risk` | 제목 **리스크 관리**. 교차링크만 | 유지 (Kill ON/OFF) |
| Recovery | `/admin/recovery` | KEEP_SEPARATE. 설명 + 교차링크 | 유지 |
| Infrastructure Health | `/admin/monitoring` | 인프라 상세 설명. sidebar 1회 | 없음 |
| Trading Operations RO | `/admin/operations-dashboard` | 제목 **거래 운영 현황**. canonical 링크 바 | 없음 |
| LIVE / ARM / Trading Scheduler | UBA panel (`/admin/upbit`) | 타일 **계좌 LIVE 제어** → upbit. control 복제 없음 | 유지 (UBA) |
| System Operations Launchpad | `/admin/operations` | 제목 **시스템 운영**. 허브 설명 + canonical 링크 | mutation 0 |

`/admin/operations`를 자동매매 허브로 변경하지 않음.

---

## 2. 페이지별 before / after

### `/admin/operations`

| | before | after |
|--|--------|-------|
| role | 운영센터 (혼재) | **SYSTEM_OPS_LAUNCHPAD** |
| title | 운영센터 | 시스템 운영 |
| mutation control | 0 | **0** |
| cross-links | 타일 일부 (health+monitor 둘 다 monitoring) | canonical 9링크 + 타일 재사용 (health≠monitor) |

### `/admin/trading`

| | before | after |
|--|--------|-------|
| role | Runtime CONTROL (메뉴: 자동매매관리) | **Runtime + Realtime Hub CONTROL** |
| title | (페이지 기존 Runtime 성격) | 자동매매 Runtime |
| mutation control | 전략/체결 Start·Stop 4 | **4** (동일) |
| cross-links | 없음/약함 | 주문·Outbox, Pre-flight, 거래 운영 현황 |

### `/admin/operations-dashboard`

| | before | after |
|--|--------|-------|
| role | 통합 모니터링 (혼동) | **TRADING_OPERATIONS_READ_ONLY_DASHBOARD** |
| title | 통합 모니터링 | 거래 운영 현황 |
| mutation control | 0 (새로고침만) | **0** |
| cross-links | 계좌 관리 | + canonical 링크 (자기 자신 제외) |

### `/admin/monitoring`

| | before | after |
|--|--------|-------|
| role | 시스템 모니터링 | **Infrastructure / System Monitoring Detail** |
| title | 시스템 모니터링 | 시스템 모니터링 (유지) |
| mutation control | 0 | **0** |
| cross-links | — | 시스템 운영, 거래 운영 현황 |

### `/admin/recovery`

| | before | after |
|--|--------|-------|
| role | KEEP_SEPARATE HIGH mutation | 동일 |
| title | 장애 복구 | 장애 복구 |
| mutation control | Recovery 실행 버튼 유지 | **동일** |
| cross-links | — | 시스템 운영, 거래 운영 현황 |

### `/admin/risk`

| | before | after |
|--|--------|-------|
| role | Risk/Kill canonical | 동일 (의도) |
| title / links | M4-A 문구·교차링크 작성됨 | **본 커밋 제외** — LIVE/ARM `reason`/`correlation_id` WIP와 동일 파일에 혼재 |
| mutation control | Kill ON/OFF + LIVE toggle WIP | 커밋에 포함하지 않음 |
| follow-up | — | risk page M4-A heading/links만 분리 후 후속 커밋 후보 |

---

## 3. Label 변경 목록

| 위치 | before | after |
|------|--------|-------|
| menu `operations` | 운영센터 | 시스템 운영 |
| menu `trading` | 자동매매관리 | 자동매매 Runtime |
| menu `operations-dashboard` | 통합 모니터링 | 거래 운영 현황 |
| breadcrumb `routes.ts` | 동일 3건 | 동일 after |
| tile `health` | Health Check → monitoring | 시스템 모니터링 → `/admin/monitoring` |
| tile `monitor` | System Monitor → monitoring | 거래 운영 현황 → `/admin/operations-dashboard` |
| tile `live-activation` | LIVE Activation → kiwoom | 계좌 LIVE 제어 → `/admin/upbit` |
| tile `scheduler` | (기존) | 스케줄러 |
| ops dashboard `pageTitle` | 통합 모니터링 | 거래 운영 현황 |
| operations 하단 버튼 | System Monitor | 시스템 모니터링 |

신규 타일 (navigation only): `runtime`, `recovery`, `risk`, `orders`.

---

## 4. Cross-link 추가 (READ-only)

`OPERATION_CANONICAL_LINKS`:

1. 시스템 모니터링 → `/admin/monitoring`
2. 거래 운영 현황 → `/admin/operations-dashboard`
3. 자동매매 Runtime → `/admin/trading`
4. Pre-flight → `/admin/operations/preflight`
5. 스케줄러 → `/admin/scheduler`
6. 주문·Outbox → `/admin/orders`
7. 리스크 관리 → `/admin/risk`
8. 장애 복구 → `/admin/recovery`
9. 계좌 LIVE 제어 → `/admin/upbit`

장착: operations extra, operations-dashboard extra (self 제외).  
trading: 주문·Outbox / Pre-flight / 거래 운영 현황.  
monitoring / recovery / risk: 허브·대시보드 왕복 링크.

---

## 5. Duplicate READ 표현

| 이슈 (M4-0 TRUE_DUPLICATE) | M4-A |
|----------------------------|------|
| health+monitor 타일 둘 다 `/admin/monitoring` | **해소** — monitor → ops-dashboard |
| GET `/health` operations + monitoring | operations는 **요약 카드** + 상세 링크. **query 자체 제거는 DEFER** |
| LIVE/ARM dual mount accounts+upbit | **미변경** (M4-C) |

---

## 6. 불변 확인

| 항목 | 결과 |
|------|------|
| LIVE/ARM control | 0 이동 · 0 복제 |
| Runtime Start/Stop | 4 → 4 |
| Scheduler RUN/PAUSE on operations | 0 |
| Kill Switch | risk 페이지에만 유지 |
| Recovery mutation | recovery 페이지만 |
| Worker control | 추가 없음 |
| route path | 0 변경 |
| permission key | 0 변경 |
| AuthGuard | 0 변경 |
| backend/API | 0 변경 |
| `/admin/upbit` panels | 0 변경 |
| User menu/page | 0 변경 |
| monitoring sidebar | **1** |
| strategy workflow menu | 유지 |
| duplicate menu routes | **0** |

---

## 7. Tests

- eslint 변경 파일: pass (`--max-warnings=0`)
- vitest focused 5 files / 23 tests: pass
- typecheck: 기존 WIP 3건만 (`live-validation/upbit`, `UpbitNewsNoticeCollectorPanel`). M4-A 신규 오류 없음

---

## 8. DEFER

- Operations 메뉴 그룹 재배치 → **M4-B**
- `AdminUpbitLiveUbaPanel` 단일 마운트 → **M4-C**
- GET `/health` 호출을 monitoring만 남기기
- shared HealthSummary 컴포넌트 추출
- operations 하단 Batch·Environment 영문 버튼 잔여 (System Monitor만 한글화)

---

## 9. Next STEP (exactly one)

**M4-B — Operations menu regroup** (자동매매 운영 vs 시스템 운영). 승인 전 자동 진행 금지.
