# STRATEGY STEP12 CHANGE MAPPING — 2026-07-31

워킹트리 기준 STRAT-12 분해. Canonical: [docs/architecture/STRATEGY_LIFECYCLE_STEP12.md](../architecture/STRATEGY_LIFECYCLE_STEP12.md)  
**≠ AUDIT21-12 Paper.**

---

## 1. 전체 커밋 전략

| 질문 | 답 |
|------|----|
| Substep별 다수 커밋? | **비권장** — 선형 Migration + `admin_strategies.py`/`router.py` 공유 |
| 권장 | **CP-05 단일 Backend+Mig+Tests** · **CP-06 Frontend** |
| Completion | `WORKTREE_IMPLEMENTED_UNCOMMITTED` · Runtime 자동 연결 **없음** (P0-3) |

---

## 2. Substep 맵

| ID | 범위 | Backend | Migration | API | FE | Tests | Docs | Deps | Commit alone? |
|----|------|---------|-----------|-----|----|-------|------|------|---------------|
| STRAT-12-1 Request | request domain | `ai/strategy_request/` | bfc6, 27d47 | admin/user_strategy_requests | strategy-requests pages | test_step12_1* | STRATEGY doc | UBA mig | No |
| STRAT-12-2 Draft | draft+generation+review | strategy_draft* | 5b999, 89de, 6d736 | drafts/generations | strategy-drafts | test_step12_2_* | | 12-1 | No |
| STRAT-12-3 Approval | approval service | strategy_draft_approval/ | (in 6d736+) | draft_approvals | | test_step12_3 | | 12-2 | No |
| STRAT-12-4 Snapshot/Backtest | readiness/spec/rule | approval backtest_* · backtest/ | 417184 | via admin_strategies | | test_step12_4–7 | | 12-3 | No |
| STRAT-12-5–7 Perf/WF/QG | analytics gates | approval modules | f5e265, … | | | test_step12_8–10 | | | No |
| STRAT-12-8–9 Sens/MC | | | 57df, 6464 | | | test_step12_11–12 | | | No |
| STRAT-12-10 Portfolio | | | 55c454 | admin_portfolio_validations | portfolio-validations | test_step12_13 | | | No |
| STRAT-12-11 Explain | | | 339f8 | | | test_step12_14 | | | No |
| STRAT-12-12 Decision | | | d73cd | | | test_step12_15 | | | No |
| STRAT-12-13 Promotion | | | b2dd93, eba1e | | | test_step12_16* | | | No |
| STRAT-12-14 Activation | | | a1c3f9 | | | test_step12_17 | | | No |
| STRAT-12-15 Registry | | | c7e4, e2b6 | | | test_step12_18 | | Runtime gap P0-3 | No |
| STRAT-12-16 Deploy ready | | | f4a8 | | | test_step12_19 | | | No |
| STRAT-12-17 Op ready | | | a7f3 | | | test_step12_20 | | WT head | No |

Paper/Performance/Risk **실행 연동**은 게이트/리포트 수준 — 자동 Paper fill(P0-5)·Runtime(P0-3)과 혼동 금지.

---

## 3. 공유 파일

- `api/v1/admin_strategies.py` — 다수 STEP12 엔드포인트 추가  
- `api/router.py` — 라우터 include  
- `strategy_deployment/*` · `backtest/*` — provenance/ownership  
- FE `adminApi.ts` / `userApi.ts` / `routes.ts`

---

## 4. Completion state

| 층 | 상태 |
|----|------|
| Domain+API+Tests (WT) | VERIFIED_BY_TEST (로컬 파일 존재; 본 단계 미실행) |
| FE pages | WORKTREE untracked |
| Migrations | UNCOMMITTED chain |
| Runtime auto-start | NOT_IMPLEMENTED / DISCONNECTED |
| Docs Canonical | PHASE2 존재 |

---

## 5. 커밋 가능 여부

- **Backend+Mig+Tests 묶음:** Ready (CP-05)  
- **Frontend:** Ready after API (CP-06)  
- **Substep 단독:** Not ready (의존성)
