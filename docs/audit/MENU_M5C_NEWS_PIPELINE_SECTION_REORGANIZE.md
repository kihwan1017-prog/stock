# MENU M5-C — News Pipeline SECTION_REORGANIZE

**Mode:** APPLY (UI order only) · **Verdict:** `NEWS_PIPELINE_SECTION_REORGANIZE_READY_WITH_LIMITATIONS`  
**Date:** 2026-08-15  
**Baseline:** M5-C0 `NEWS_PIPELINE_SECTION_REORGANIZE` · M5-B `c1af96e`  
**File:** `frontend/src/features/admin/upbit/UpbitNewsNoticeCollectorPanel.tsx`

> Component split **없음**. API/mutation/policy **변경 없음**.  
> commit/push **금지** (SELECTIVE COMMIT 별도 · rowKey WIP 혼합 주의).

---

## 1. WIP baseline (수정 전)

| Class | Content |
|-------|---------|
| **PREEXISTING_WIP** | article/analysis/signal `rowKey` · articles `dataSource={items}` · AI/signal map without synthetic `key` (+7/−8 vs HEAD) |
| **M5-C 예정** | section heading/order · action 분리 |

---

## 2. BEFORE / AFTER

| BEFORE | AFTER |
|--------|-------|
| mixed tags + all actions | **뉴스 수집** (N2 tags · collect · refresh · recent table) |
| recent table | **심볼 매핑 · 품질** (N3.1 counters · mapping run · Collector+Mapping JSON) |
| N4 | **AI 뉴스 분석** (tags · run · table · AI status JSON) |
| collector JSON late · N5 | **News Signal** (tags · run · table · stats) |

---

## 3. Contracts unchanged

| Item | Before | After |
|------|--------|-------|
| LOC | 389 (HEAD) / ~390 WT | **408** |
| useQuery / useMutation | 7 / 4 | 7 / 4 |
| onClick | 5 | 5 |
| API fns | 11 | 11 |
| useState / useEffect | 0 / 0 | 0 / 0 |
| Split files | none | none |

---

## 4. Diff classification (vs HEAD after M5-C)

| Class | Status |
|-------|--------|
| **PREEXISTING_WIP** | **preserved** (3× rowKey + article dataSource + comment) |
| **M5C_SECTION_REORGANIZE** | headings · action placement · order |
| **UNEXPECTED** | **0** |

---

## 5. Safety / regression

N4 INFORMATIONAL · N5 ≠ trading · N6 → A/B tab only.  
Scanner/Gate apply 없음. LIVE/ARM/Scheduler mut 0.  
M5-A tabs · M5-B Technical markers · mounts=1.

---

## 6. Tests

`upbitNewsPipelineSectionOrder.test.ts` — **3 passed**.  
eslint PASS. tsc M5-C 신규 0 (기존 rowKey WIP는 의도적 유지).

---

## 7. Changed files (working tree)

| File | Role |
|------|------|
| `UpbitNewsNoticeCollectorPanel.tsx` | M5-C order + **preserved WIP** |
| `upbitNewsPipelineSectionOrder.test.ts` | **new** |
| `MENU_M5C_NEWS_PIPELINE_SECTION_REORGANIZE.md` | this |
| Canonical + audit README | status |

---

## 8. Limitations

1. Recent articles table는 N2에 유지(Mapped Symbols 컬럼 포함) — N3는 counters/action/JSON.  
2. 동일 파일에 WIP+M5-C 공존 → **SELECTIVE COMMIT 시 분리 전략 필수**.  
3. Confirm modal 미추가.

---

## 9. Next STEP (exactly one)

**M5-C SELECTIVE COMMIT** (WIP vs M5-C 분리 또는 명시적 포함 승인)  
자동 commit 금지. M5-D 금지.
