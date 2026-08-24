# Upbit Research Collection Runtime + Scheduler Audit

**Date:** 2026-08-24  
**Scope:** UBA1380 research panel Not Found / zero counts — Backend → Scheduler → DB → API → FE  
**Safety:** REAL/LIVE/ARM/Risk/Slot/UBA1381 미변경. UBA1380 자동매매 stop 없음.

## FINAL_VERDICT

`FIXED_ROUTE_AND_SCHEDULER_IMPLEMENTED`

## STEP 1 — Not Found

| Field | Value |
|-------|-------|
| RESEARCH_STATUS_REQUEST_URL | `/api/v1/admin/autotrading/uba/{id}/research/collection-status` |
| FE query | `adminApi.getAdminUbaResearchCollectionStatus` → `/admin/autotrading/uba/{id}/research/collection-status` (+ `/api/v1` prefix) |
| Backend route | `admin_autotrading_readiness.py` · prefix `/api/v1/admin/autotrading` |
| ROUTE_REGISTERED | YES (source) |
| Before restart HTTP | **404** |
| After restart (no auth) | **401** (route loaded) |
| OpenAPI | path present |
| FIRST_BROKEN_STAGE | `RUNNING_BACKEND_ROUTE_NOT_LOADED` |
| ROOT_CAUSE / NOT_FOUND_ROOT_CAUSE | 실행 중 backend가 신규 route 미로드(stale process). FE URL은 정상. 404 → UI 0 fallback. |

## STEP 2 — DB

| Metric | Value |
|--------|-------|
| DATA_LOST | **NO** |
| UI_FALLBACK_ZERO | **YES** (404로 인한 표시) |
| ACTUAL_CLEAN_COUNT | **37** |
| LEGACY_COUNT | **459** |
| BACKFILL_COUNT | **17** |
| market snapshots | OK after collect |
| asset snapshots | OK (KRW) |
| news 24h | 16 OK |
| llm | 0 WAITING (후보 대기) |

## STEP 3–4 — Scheduler

| SOURCE | COLLECTOR | TRIGGER | SCHEDULED | INTERVAL | PERSISTENCE | USED_BY_LLM |
|--------|-----------|---------|-----------|----------|-------------|-------------|
| Market Context | `UpbitMarketContextResearchScheduler` | INTERVAL | YES | 600s | `operation.upbit_market_context_snapshot` | YES |
| Asset Context | same job | INTERVAL | YES | 600s | `operation.upbit_asset_context_snapshot` | YES |
| News | `UpbitNewsNoticeCollectorScheduler` | INTERVAL | YES (notice default ON) | 900s | `news.news_article` | YES |
| Upbit Notice | same | INTERVAL | YES | 900s | news | YES |
| Fear & Greed | research scheduler FNG job | INTERVAL | YES | 3600s | market snapshot | YES |
| Asset Description | TTL cache in collect | TTL | on collect | **7d TTL** (기존 유지) | `upbit_asset_description_cache` | YES |
| CLEAN Forward | Scanner + Shadow evaluator | LIFECYCLE | NO fake timer | — | `trading.upbit_opportunity_shadow` | — |
| LLM Context | `maybe_analyze_shadow_candidate` | CANDIDATE | NO periodic | — | `upbit_llm_context_analysis` | — |

- collect-once API ≠ 자동 scheduler (혼동 금지) — 둘 다 `collect_runner` 공유.
- Backend log: `upbit_market_context_research_scheduler_started` (600/3600).

## Cadence decisions

- Market/Asset: **600s** (권장 10분 채택)
- Notice: **900s** (권장 15분; 기존 기본 300s → 권장으로 정렬, 공지 기본 ON)
- Crypto news: 기존 **OFF** 유지 (Naver 키 의존)
- F&G: **3600s** (권장 60분 + TTL 1h)
- Description TTL: **7d** 기존 유지

## STEP 5–6 — API / UI

- Aggregate API에 `scheduler`, `next_run_at`, statuses(OK/STALE/ERROR/WAITING/DISABLED), experiment 유지
- FE: 자동수집/Scheduler/다음 실행 표시, CLEAN 축적 안내, 개발자 탭에 API path
- 상단 문구: 「실계좌 포트폴리오 자동매매 설정」 / 「안전 통합 제어…」 (endpoint는 Tooltip)

## STEP 7 — Frontend gate

- `check:antd-compat` / `lint` / `typecheck` / `test:ui:focused` / `check:frontend` → PASS
- Authenticated browser render → **LIMITED** (유효 admin 토큰 없음; console 0 미검증)

## STEP 8 — Backend tests

- `tests/test_upbit_research_collection_runtime_scheduler.py` PASS
- existing `test_upbit_research_collection_status.py` PASS

## STEP 9 — Safety mutations

| Flag | Value |
|------|-------|
| REAL_ORDER_MUTATION | 0 |
| LIVE_ARM_MUTATION | 0 |
| RISK_MUTATION | 0 |
| SLOT_MUTATION | 0 |
| UBA1381_MUTATION | 0 |

Research failure = fail-open (REAL 경로 미차단).

## Ops

- BACKEND_RESTART_COUNT: **1** (route load + scheduler start)
- SYSTEM_BUG_ACTIVE: **NO** (route 404 해소)
- REMAINING_LIMITATIONS: LLM은 신규 Shadow 후보 시에만 축적(현재 0건). Crypto news 기본 OFF. Browser auth verify LIMITED.
- NEXT_ACTION: 관리자 로그인 후 `/admin/upbit/autotrading` 패널 실측 확인; CLEAN은 Scanner 후보 발생에 따라 증가.
