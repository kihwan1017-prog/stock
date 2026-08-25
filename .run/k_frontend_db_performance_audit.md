# Frontend Load + DB Index Performance Audit

**Date (KST):** 2026-08-25  
**Scope:** Admin FE → API → SQL; evidenced indexes/query/FE fetch only  
**REAL_TRADING_MUTATION:** 0

## FINAL_VERDICT

`FRONTEND_DB_PERF_PARTIAL_IMPROVED`

인덱스 1개(EXPLAIN 근거) + asset-context SQL pagination + `/health` 병렬/캐시 + monitoring alerts SQL filter + FE staleTime 적용.  
workers=1 블로킹이 핵심 병목이었고, 재시작 후 concurrent API가 더 이상 health에 묶이지 않음.

## SLOWEST_PAGES_TOP5 (auth browser, net ≈ render−3.5s settle)

| Page | net_ms | APIs | max_api_ms | notes |
|------|--------|------|------------|-------|
| /admin/monitoring | ~255 | 10 | 924 | health+overview+alerts+ops×2 |
| /admin/portfolio | ~214 | 6 | 794 | ownership×2 |
| /admin/upbit/autotrading | ~238 | 9 | 576 | tab polls |
| /admin/orders | ~206 | 5 | 1078 | orders payload ~54KB |
| /admin/research?market=KIWOOM | ~200 | 3 | 1259 | settle variance |

## SLOWEST_APIS_TOP10 (after, n=5)

| API | P50 | P95 | PAYLOAD_KB |
|-----|-----|-----|------------|
| /health | 43.7 | 943.2 | 21.3 (cold miss on TTL) |
| /admin/upbit/research/experiments | 277.5 | 649.6 | 2.3 |
| /admin/autotrading/uba/1381/ops-status | 155.1 | 606.5 | 10.7 |
| /admin/upbit/opportunity-scanner/status | 318.4 | 340.2 | 57.8 |
| /api/v1/monitoring/overview | 28.4 | 328.1 | 42.6 |
| /admin/autotrading/.../horizon-auto-renew/preview | 105.1 | 227.9 | 1.7 |
| /admin/upbit/dual-llm/comparison | 128.4 | 216.0 | 1.0 |
| /admin/autotrading/uba/1380/ops-status | 146.5 | 201.8 | 10.8 |
| /admin/.../collection-status | 164.1 | 179.8 | 6.0 |
| /admin/symbol-ownership/1380 | 89.2 | 177.4 | 3.6 |

## SLOWEST_SQL_TOP10 (evidence)

1. `upbit_asset_context_snapshot ORDER BY observed_at DESC LIMIT n` — **BEFORE** Seq Scan + external merge Disk 12MB, 18–75ms; **AFTER** Index Scan `ix_upbit_asset_ctx_observed_at`, 0.05–1.4ms  
2. `audit_event` recent by PK — Index Scan Backward, ~0.05ms (not DB-bound; FE was blocked by /health)  
3. `audit_event WHERE event_type LIKE 'MONITORING_ALERT%'` — Seq Scan 25ms (8 rows / 110k); acceptable, exact-prefix index already exists for equality  
4. Large tables (size) but **not** on admin list hot path: `market.trade_tick` 841MB, `price_daily` 151MB, `candle_minute` 77MB, `audit_event` 53MB, `ai.execution_request` 50MB  

## INDEXES_ADDED

| table | index | columns | reason | before_ms | after_ms |
|-------|-------|---------|--------|-----------|----------|
| operation.upbit_asset_context_snapshot | ix_upbit_asset_ctx_observed_at | observed_at DESC | list ORDER BY observed_at; Seq+disk sort | 18.4 (LIMIT20) / 75.3 (LIMIT5000) | 0.05 / 1.37 |

Applied: `CREATE INDEX CONCURRENTLY` on live DB.  
Alembic file: `database/alembic/versions/perf_acs_obs_20260825_asset_context_observed_index.py` (down_revision `v2w3x4y5z6a7`).  
Index size ≈ 296 kB.

## INDEXES_NOT_ADDED

| candidate | reason |
|-----------|--------|
| audit_event (event_type, created_at) duplicate | already exists `ix_audit_event_type_created` |
| trading_order (uba, created_at) | orders list P50~30ms; no EXPLAIN pain |
| trade_tick / price_daily extra indexes | not on audited admin list paths |
| mass composite guesses | forbidden without EXPLAIN |

## QUERY_OPTIMIZATIONS

- `list_asset_context`: rank 필터 없을 때 SQL `COUNT` + `OFFSET/LIMIT` (5000-row prefetch 제거)
- `monitoring/alerts`: `event_type LIKE 'MONITORING_ALERT%'` SQL filter (최근 N건 Python 필터 제거)
- `SystemHealthService.build`: 외부 HTTP `asyncio.gather` 병렬 + 5s TTL 캐시
- `health/live`: `inspect.getsource` 결과 `lru_cache`

## N_PLUS_ONE_FIXED

- monitoring alerts: over-fetch+filter → single filtered query  
- FE: monitoring page 동일 API 중복은 없었음; 병목은 workers=1 + `/health` 직렬 블로킹

## PAGINATION_CHANGES

- asset-context: OFFSET pagination만 SQL로 정렬 유지 (contract 유지). deep page keyset은 미적용 (페이지 깊이 작음).

## PAYLOAD_REDUCTION

- list still returns `value_json` (FE drawer 사용). summary-only split은 **검토만** (breaking 위험).  
- orders ~54KB / outbox ~25KB — 추가 trim 미적용.

## FRONTEND_FETCH_OPTIMIZATION

- `SystemStatusDashboard`: staleTime + `/health` 60s poll + `refetchOnWindowFocus:false`
- Research / Dual LLM / collection status·summary: staleTime + no focus refetch

## BEFORE_AFTER_PAGE_LOAD

| metric | before | after |
|--------|--------|-------|
| monitoring max_api (waterfall) | ~1.7s (health-blocked cluster) | ~0.9s |
| concurrent /version during /health | ~blocked to ~1s+ | 18ms |
| net page settle (excl. 3.5s wait) | ~0.2–1.5s under health block | ~200–255ms shell |

## BEFORE_AFTER_API_P95

| API | before P95 | after P95 |
|-----|------------|-----------|
| /health | 4345 | 943 (cold) / ~50 cached P50 |
| /version | 1073 | 28 |
| /monitoring/alerts | 2190 | 61 |
| asset-context | 766 | 39 |
| uba/1380/ops-status | 1026 | 202 |
| portfolio (uba) | 1163 (2026-08-22 baseline) | 70 |

## DB_SIZE_IMPACT

+~296 kB index on asset_context (~18 MB table).

## TESTS

- `pytest tests/test_frontend_db_perf_asset_context_list.py` → 2 passed  
- `npm run check:frontend` → PASS (antd-compat, lint, typecheck, 41 focused tests)

## FRONTEND_CHECK

PASS

## AUTH_BROWSER_VERIFY

DONE (session refresh + playwright chromium)

## CONSOLE_ERRORS

0 real app errors. Playwright typed antd deprecation `Warning: [antd: …]` as console error (List/Drawer) — **pre-existing UI deprecation**, not runtime failure.

## CONSOLE_WARNINGS

0 (antd deprecations counted under errors by browser harness)

## DB_MIGRATION

- Live: CONCURRENTLY applied  
- Alembic revision file added; **not stamped** (multi-head / P0-4 alembic graph). Stamp/upgrade는 별도 merge 작업 필요.

## GIT_COMMIT

NO (미요청 — working tree only)

## REAL_TRADING_MUTATION

0 (backend restart 후 UBA1380 LIVE=ON ARM=ON runtime=RUNNING 확인, 주문/정책 mutate 없음)

## SYSTEM_BUG_ACTIVE

- Alembic multi-head / version table drift (P0-4)  
- antd List/Drawer deprecation warnings  
- `/health` cold path still ~0.8–0.9s (external probes; cached 5s)

## LIMITATIONS

- pg_stat_statements 미설치 → API latency는 HTTP probe 기반  
- research latency script의 `?limit=` 는 asset API의 `page_size`와 불일치(기본 20) — after 재측정은 `page_size=50`도 확인  
- scanner/status·experiments·1381 ops-status는 아직 P95≥300ms (후속)  
- Frontend HMR이 FE staleTime을 반영했는지 환경 의존

## NEXT_ACTION

`REVIEW_FRONTEND_DB_PERFORMANCE_WITH_CHATGPT`

## Evidence

- `.run/k_frontend_db_performance_audit.json`
- `.run/k_frontend_db_performance_audit.md`
- `.run/_fe_db_api_latency.json`
- `.run/_fe_db_browser_pages.json`
