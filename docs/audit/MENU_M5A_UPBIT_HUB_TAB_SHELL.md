# MENU M5-A — Upbit Hub Tab Shell + Overview Reorder

**Mode:** APPLY (UI layout only) · **Verdict:** `UPBIT_HUB_TAB_SHELL_READY_WITH_LIMITATIONS`  
**Date:** 2026-08-15  
**Baseline:** M5-0 `UPBIT_HUB_DESIGN_READY_WITH_LIMITATIONS` · OPTION B  
**Route:** `/admin/upbit` (unchanged)

> Panel 내부 production logic 변경 없음.  
> Backend/API/permission/menu/AuthGuard mutation = 0.  
> LIVE/ARM/Scheduler mutation = 0.  
> Ambiguous / NewsCollector **파일 WIP 미수정**.  
> commit/push = 사용자 승인 후.

---

## 1. BEFORE / AFTER

| | BEFORE | AFTER |
|--|--------|-------|
| Layout | 세로 스택 단일 스크롤 | in-page **Tabs** (5) |
| Order | Live → Scanner → **Combined(N6)** → Collector(N2–N5) → ops → Ambiguous | Overview → Technical → **News** → **A/B** → Ops |
| N6 before N2 | **YES (문제)** | **NO (해소)** |
| LIVE CONTROL | accounts only | 유지 |
| LIVE READ | page top | Overview |

---

## 2. Tab mapping

| Tab key | Label | Contents |
|---------|-------|----------|
| `overview` | 개요 | Hub 설명 · `UpbitLiveStatusReadSummary` · 섹션 안내 버튼(탭 전환만) |
| `technical` | Technical | `UpbitOpportunityScannerPanel` (내부 미분해) |
| `news` | 뉴스 파이프라인 | `UpbitNewsNoticeCollectorPanel` (N2–N5 미분해) |
| `ab` | A/B 실험 | `UpbitNewsCombinedShadowPanel` |
| `ops` | 운영·정합 | `UpbitHubOpsSection` = 연결/잔고/체결·rate·snapshot + `UpbitAmbiguousOrdersPanel` |

---

## 3. Page-level ops placement

| Action | BEFORE | AFTER |
|--------|--------|-------|
| 계좌 관리 link | header | header (유지) |
| UBA ID / 연결 테스트 / 잔고·체결 동기화 | header | **Ops** |
| account status / rate / snapshot | page stack | **Ops** |
| Ambiguous | page bottom | **Ops** |

Mutation handlers·API 시그니처는 기존 page와 **동일** (Ops section으로 이동만).

---

## 4. Keep-alive / side effect audit

| Panel | useEffect auto-mutation | Mount GET | refetchInterval |
|-------|-------------------------|-----------|-----------------|
| LiveSummary | none | yes | no |
| Scanner | none | yes | 30s |
| Collector | none | yes | 30–60s |
| Combined | none | yes | 30–60s |
| Ambiguous | none | yes | 15s |
| Ops section | none (button only) | yes when Ops visited | no |

**정책:** 첫 방문 전 unmount → Overview에서 Scanner/News/A-B/Ops **GET 없음**.  
방문 후 `display:none` keep-alive → remount로 interval 재시작 **방지**.  
Tab `onChange` = `selectTab` only → **mutation auto-call 없음**.

---

## 5. Regression

| Check | Result |
|-------|--------|
| `AdminUpbitLiveUbaPanel` mount = 1 (accounts) | PASS |
| upbit LIVE/ARM/Scheduler mut strings | 0 |
| risk page untouched | PASS |
| Scanner/Shadow/Cohort panel file | untouched |
| NewsCollector / Ambiguous panel file | **untouched** (WIP 보호) |
| Combined panel file | untouched |
| route `/admin/upbit` | unchanged |
| `menu:upbit` | unchanged |
| AuthGuard | unchanged |
| backend/API | 0 |

---

## 6. Tests

- `upbitHubTabs.test.ts` — Tabs/labels/mapping/N6 order/LIVE/menu  
- `upbitLiveControlSingleMount.test.ts` — Ambiguous → Ops section 참조로 최소 갱신  
- vitest focused: **13 passed**  
- eslint changed files: PASS  
- tsc: M5-A 신규 오류 **0** (기존 `live-validation/upbit` WIP만 잔존)

---

## 7. Changed files

| File | Role |
|------|------|
| `frontend/src/app/(admin)/admin/upbit/page.tsx` | Tab host (thin) |
| `frontend/src/features/admin/upbit/UpbitHubTabs.tsx` | **new** shell |
| `frontend/src/features/admin/upbit/UpbitHubOpsSection.tsx` | **new** ops move |
| `frontend/src/features/admin/upbit/upbitHubTabConfig.ts` | **new** keys/labels |
| `frontend/src/features/admin/upbit/upbitHubTabs.test.ts` | **new** |
| `frontend/src/features/admin/upbit/upbitLiveControlSingleMount.test.ts` | Ambiguous path assert |

**Not changed:** OpportunityScanner / NewsCollector / CombinedShadow / Ambiguous panel sources.

---

## 8. Limitations / DEFER

1. URL `?tab=` 없음 — refresh 시 Overview (허용)  
2. Technical 라벨 영문 유지 (기술지표 메뉴와 혼동 방지)  
3. Tab click DOM render test 없음 (정적 소스 테스트)  
4. Ops 방문 후 keep-alive 시 rate/Ambiguous interval 지속 (이전 전체 스택과 유사)  
5. M5-B/C panel 내부 분해 **DEFER**

---

## 9. Next STEP (exactly one)

**M5-B — Technical section 정리 (Scanner/Shadow/Cohort UI 섹션 정리; policy 변경 금지)**  
승인 전 구현 금지.
