# MENU M5-C0 — Upbit News Pipeline Tab Structure Precheck

**Mode:** PRECHECK / DESIGN ONLY · **Verdict:** `NEWS_PIPELINE_SECTION_REORGANIZE`  
**Date:** 2026-08-15  
**Baseline commit:** `c1af96e2cfe0edde66f642202f634a9f03d4956f`  
**Panel (HEAD):** `frontend/src/features/admin/upbit/UpbitNewsNoticeCollectorPanel.tsx`  
**Host:** `/admin/upbit` → 뉴스 파이프라인 tab (`news={<UpbitNewsNoticeCollectorPanel />}`)

> Production code **변경 없음** (NewsCollector **미수정**).  
> commit/push **없음**. M5-C 구현 **금지**.

---

## 0. Executive summary

HEAD 기준 **LOC 389**, `useState`/`useEffect` **0**, **useQuery 7** · **useMutation 4**, stage별 API는 **대체로 독립**이다.  
다만 UI는 **상단 버튼 한 줄에 N2–N5 액션이 섞이고**, Recent articles → N4 → (늦은) Collector+Mapping JSON → N5 순이라 **논리 파이프라인과 어긋난다**.

Technical(M5-B0)과 달리 data coupling은 **MEDIUM**(공유 GET 1개가 아님).  
그러나 **동일 파일에 PREEXISTING_WIP(rowKey)** 가 있어 지금 당장 COMPONENT_SPLIT은 충돌 위험이 크다.

**권장: OPTION B — SECTION_REORGANIZE** (파일 유지 · N2→N3→N4→N5 heading/순서만).  
Split은 WIP 정리 후 후속 후보.

---

## 1. Complexity (HEAD)

| Metric | Value |
|--------|------:|
| total LOC | **389** |
| JSX LOC (from `return`) | **227** |
| useState | **0** |
| useEffect | **0** |
| useQuery | **7** |
| useMutation | **4** |
| onClick handlers | **5** (collect / map / AI / signal / refresh-all) |
| API functions used | **11** |
| GET | **7** |
| POST mutation | **4** |
| AdminDataTable | **3** |
| AdminJsonCard | **3** |
| Typography.Title blocks | **3** (+ intro paragraph) |
| Practical complexity | **MEDIUM** (linear UI · many independent queries) |

비교: Technical panel LOC 219 / queries 1 / mutations 2.

---

## 2. Inventory (존재하는 것만)

### N2 Collection — YES
| Item | Present |
|------|---------|
| UPBIT Notice / Crypto tags (enabled/interval) | YES (`sources.UPBIT_NOTICE` / `CRYPTO_NEWS`) |
| collector enabled/running | YES |
| last_run / next_run / last_error | YES |
| recent articles table | YES |
| manual collect | YES `runUpbitNewsCollector` |
| source stats beyond tags | via Collector status JSON |

### N3 Symbol Mapping — YES (embedded)
| Item | Present |
|------|---------|
| mapping counters (universe/mapped/links) | YES from `st.symbol_mapping` |
| manual mapping run | YES `runUpbitNewsSymbolMapping` |
| mapped symbols in recent table | YES column |
| match_type / mapping_confidence | YES in Mapped Symbols tags |
| dedicated mapping status GET | **NO** (`getUpbitNewsSymbolMappingStatus` unused) |

### N3.1 Mapping Quality — YES (same section as N3)
| Item | Present |
|------|---------|
| TRUSTED / REVIEW_REQUIRED / AMBIGUOUS / REJECTED counters | YES header tags |
| per-row quality_status colors | YES |
| quality_reason / review_reason title | YES |
| separate N3.1 UI section | **NO** — N3와 동일 헤더/테이블 |

### N4 AI News Analysis — YES
| Item | Present |
|------|---------|
| status tags (enabled/model/COMPLETED/FAILED/SKIPPED) | YES |
| recent analyses table | YES |
| manual run (limit 5, force false) | YES |
| event/sentiment/impact/confidence/status columns | YES |
| affected_symbols / risk_flags columns | **NO** in table |
| Ollama label | model field only |
| BUY/SELL/ALLOW/APPLY buttons | **NO** (copy만 “없음” 명시) |

### N5 News Signal — YES
| Item | Present |
|------|---------|
| status tags VALID/LOW_CONF/STALE/INVALID | YES |
| recent signals + stats JSON | YES |
| manual run | YES |
| direction/strength/reliability/expires | YES |
| provenance column | **NO** dedicated |
| trading apply | **NO** |

### Pipeline Observation (N8–N10) — **NOT in this panel**
latency / backlog / capacity / overlap / FUTURE_SIGNAL_AT / sample_milestone → **`UpbitNewsCombinedShadowPanel` (A/B tab)**.  
News 탭에서 N6 상세 신규 **금지** (boundary OK).

---

## 3. Current vs logical UI order

**Current (HEAD render):**
1. Title + pipeline blurb  
2. Mixed tags (N2 enabled/running/notice/crypto + **N3.1 quality** + mapping counts)  
3. last_run line  
4. **All manual actions** (N2+N3+N4+N5) + refresh-all  
5. Recent articles (+ mapped symbols)  
6. **N4** heading + tags + AI table  
7. Collector+Mapping status JSON (**late**)  
8. AI status JSON  
9. **N5** heading + tags + signals table + stats JSON  

**Logical:** N2 → N3/N3.1 → N4 → N5  

**Gap:** actions/status JSON 순서 · N3 전용 heading 부재 · N4가 Collector JSON보다 앞.

---

## 4. API dependency matrix

| API | Method | Stage | Used |
|-----|--------|-------|------|
| `getUpbitNewsCollectorStatus` | GET `/news-collector/status` | N2+N3 embed | YES |
| `getUpbitNewsCollectorRecent` | GET `.../recent` | N2(+N3 rows) | YES |
| `runUpbitNewsCollector` | POST `.../run` | N2 | YES |
| `runUpbitNewsSymbolMapping` | POST `.../symbol-mapping/run` | N3 | YES |
| `getUpbitNewsSymbolMappingStatus` | GET | N3 | **NO** |
| `getUpbitNewsAnalysisStatus/Recent` | GET | N4 | YES |
| `runUpbitNewsAnalysis` | POST | N4 | YES |
| `getUpbitNewsSignalsStatus/Recent/Stats` | GET | N5 | YES |
| `runUpbitNewsSignals` | POST | N5 | YES |

PUT/DELETE: none.

---

## 5. Coupling

| Kind | Class | Notes |
|------|-------|-------|
| **Data** | **MEDIUM** | N4/N5 independent queries; N3 counters from N2 status; N2/N3 mutations invalidate collector only |
| **UI** | **HIGH** | one file · shared action row · interleaved sections |
| **Mutation** | **LOW–MEDIUM** | stage-local invalidate (refresh-all is explicit cross) |
| **Overall** | **MEDIUM** | split 가능하나 WIP·공유 refresh로 B 우선 |

---

## 6. Mutations (safety)

| UI | Endpoint | Stage | Confirm | Trading | Cross-refresh |
|----|----------|-------|---------|---------|---------------|
| 수동 수집 | POST collector/run | N2 | no | no | collector+recent |
| Symbol Mapping | POST mapping/run | N3 | no | no | collector+recent |
| AI Analysis | POST analysis/run | N4 | no | no | AI only |
| News Signal | POST signals/run | N5 | no | no | signals only |
| 새로고침 | GET refetch×7 | global | — | no | all |

LIVE/ARM/Scheduler mut: **0**.  
BUY/SELL/ALLOW/APPLY action buttons: **0**.

---

## 7. Existing WIP (WT vs HEAD)

| Class | Content |
|-------|---------|
| **COMMITTED_BASE** | HEAD `c1af96e` panel as analyzed |
| **PREEXISTING_WIP** | WT +7/−8: `rowKey` for articles/AI/signals · remove synthetic `key` in dataSource map (tsc-oriented) |
| **M5-C0 변경** | **0** (READ-ONLY) |

**WIP collision risk:** **HIGH** if M5-C edits same file before WIP commit/discard.  
권장: M5-C 전 WIP 선별 분리 또는 M5-C를 UI-order-only로 최소화.

---

## 8. Options

### A KEEP_SINGLE_PANEL
비용 0 · flow 미해결 · WIP 충돌 0.

### B SECTION_REORGANIZE ★
파일 유지 · N2→N3→N4→N5 heading/action/JSON 재배치 · API 0 · split 0.  
**권장** (M5-B와 동일 전략).

### C COMPONENT_SPLIT
4+ sections · API 독립성 양호 · **API duplication risk MEDIUM** unless parent owns queries.  
WIP 충돌·구현비↑ → **지금 비권장** (후속 M5-C2 후보).

| | A | B | C |
|--|---|---|---|
| cost | lowest | low | high |
| UX flow | weak | **fix** | fix |
| WIP risk | none | medium | high |
| API dup | 0 | 0 | medium unless parent-owned |

**component split 필요?** 당장 **NO**  
**parent-owned data?** split 시에만 권장 (미구현)

---

## 9. Desired UI flow (design only)

```text
N2 Collection (status · collect · recent)
 → N3/N3.1 Mapping (quality · map run · mapped columns)
 → N4 AI Analysis (status · run · recent · status JSON)
 → N5 News Signal (status · run · recent · stats)
```

N6 observation은 **A/B 탭** 유지.

---

## 10. Contracts / regression

| Check | Result |
|-------|--------|
| N4 INFORMATIONAL ONLY | YES (copy + no trade actions) |
| N5 ≠ trading signal | YES |
| N6 boundary | observation not in this panel |
| Scanner/Gate apply | none |
| M5-A tabs / mounts | unchanged this STEP |
| LIVE mut upbit | 0 |
| risk page | untouched |
| TradingOrder/Outbox | 0 |
| route/permission/API change needed for B | **NO** |

---

## 11. Next STEP (exactly one)

**STEP M5-C — News Pipeline SECTION_REORGANIZE only**  
(N2→N5 heading/order · no split · no policy/API · **WIP rowKey와 충돌 시 선별 전략 필수**)

승인 전 구현 금지.

---

## 12. Limitations

1. HEAD 분석 (WT WIP는 rowKey만 — 기능 inventory에 미포함).  
2. Collector status JSON 내부 N8 필드 존재 여부는 payload runtime 미검증.  
3. BUY/SELL 문자열은 **금지 안내 문구**에만 존재.
