# WORKTREE CHANGE MANIFEST — 2026-07-31

**읽기 전용.** 전체 경로 목록 + Work Package. 실제 restore/split 없음.  
Git: `TRACKED_MODIFIED` · `TRACKED_DELETED` · `UNTRACKED` · `ARCHIVE_MOVE` · `RENAME_CANDIDATE`

Archive B1: 루트 `D` + `docs/archive/completion-reports/` `??` = **ARCHIVE_MOVE** (rename 미 staging).

---

## A. WP-DOC-FOUNDATION (PHASE 1)

| Path | Git | Action | Evidence |
|------|-----|--------|----------|
| docs/audit/PROJECT_FOUNDATION_AUDIT_20260731.md | UNTRACKED | INCLUDE | PHASE1 |
| docs/audit/AUTOTRADING_EXECUTION_FLOW_AUDIT_20260731.md | UNTRACKED | INCLUDE | PHASE1 |
| docs/audit/SOURCE_COMPONENT_INVENTORY_20260731.md | UNTRACKED | INCLUDE | PHASE1 |
| docs/audit/DATABASE_MIGRATION_AUDIT_20260731.md | UNTRACKED | INCLUDE | PHASE1 |
| docs/audit/TEST_COVERAGE_AUDIT_20260731.md | UNTRACKED | INCLUDE | PHASE1 |
| docs/audit/MARKDOWN_DOCUMENT_AUDIT_20260731.md | UNTRACKED | INCLUDE | PHASE1 |
| docs/audit/STEP_NUMBER_MAPPING_20260731.md | UNTRACKED | INCLUDE | PHASE1 |
| docs/audit/AI_DOCUMENTATION_STANDARDIZATION_PLAN_20260731.md | UNTRACKED | INCLUDE | PHASE1 |
| docs/audit/PROJECT_IMPLEMENTATION_STATUS_DRAFT_20260731.md | UNTRACKED | INCLUDE | draft hist |
| docs/audit/PROJECT_REMAINING_WORK_20260731.md | UNTRACKED | INCLUDE | superseded later |
| docs/audit/README_AUDIT_CODE_20260728.md | UNTRACKED | HOLD_FOR_REVIEW | pg_url 패턴 이력 |

**Can commit independently:** YES (CP-01) · Risk: Low

---

## B. WP-DOC-CANONICAL (PHASE 2)

| Path | Git | Action |
|------|-----|--------|
| AGENTS.md | TRACKED_MODIFIED | INCLUDE |
| README.md | TRACKED_MODIFIED | INCLUDE (Archive 링크는 CP-03와 겹침 → **MULTI with CP-03**) |
| CLAUDE.md | UNTRACKED | INCLUDE |
| .cursor/rules/00–50,90-*.mdc | UNTRACKED | INCLUDE |
| docs/CURRENT_WORK.md | UNTRACKED | INCLUDE → **CP-03 권장** (Batch1 Gate 반영) |
| docs/PROJECT_IMPLEMENTATION_STATUS.md | UNTRACKED | INCLUDE |
| docs/STEP_MASTER_STATUS.md | UNTRACKED | INCLUDE |
| docs/ROADMAP.md | UNTRACKED | INCLUDE |
| docs/DECISION_LOG.md | UNTRACKED | INCLUDE |
| docs/AI_*.md (8) | UNTRACKED | INCLUDE |
| docs/architecture/STRATEGY_LIFECYCLE_STEP12.md | UNTRACKED | INCLUDE |
| docs/audit/PHASE2_DOCUMENTATION_STANDARDIZATION_REPORT_20260731.md | UNTRACKED | INCLUDE |
| docs/README.md · architecture/README.md · audit/README.md | TRACKED_MODIFIED | INCLUDE (Canonical 인덱스) |

**Risk:** Low · README는 Archive 경로 포함 → CP-02+CP-03 동시 또는 CP-03에 README 링크 부분 포함.

---

## C. WP-DOC-ARCHIVE-B1 (PHASE 3A/3B)

### Deleted (root) → now under completion-reports/

16 files: FINAL_* · README_AUDIT_* · README_FINAL/FULL_* · PROJECT_FINAL_AUDIT · PRODUCTION_SCORECARD · RELEASE_NOTE* · RELEASE_RISK

| Git | Action |
|-----|--------|
| TRACKED_DELETED + UNTRACKED dest | INCLUDE_IN_PACKAGE 동일 CP-03 |

### Link fix companions

| Path | Git | Action |
|------|-----|--------|
| CHANGELOG.md | M | INCLUDE CP-03 |
| OPERATIONS.md | M | INCLUDE CP-03 |
| SECURITY.md | M | INCLUDE CP-03 |
| TOP_100_IMPROVEMENTS.md | M | INCLUDE CP-03 |
| README_ISSUES.md | M | INCLUDE CP-03 |
| docs/audit/PHASE3A_* · PHASE3B_* · MARKDOWN_*ARCHIVE* | UNTRACKED | INCLUDE |

**독립 커밋:** YES with link fixes · Risk: Med (포털 링크)

---

## D. WP-UBA-DATABASE

| Path | Git | Related Mig | Tests | Action |
|------|-----|-------------|-------|--------|
| database/.../dac603609696_uba_soft_delete.py | UNTRACKED | dac603 | test_step_2_5_1 | INCLUDE CP-04 |
| database/.../2fab1d256681_trading_order_account_fk.py | UNTRACKED | 2fab1d | test_step_2_5_2 | INCLUDE |
| database/.../84b4b4a8c996_settlement_ledger_account_fks.py | UNTRACKED | 84b4b4 | test_step_2_5_3 | INCLUDE |
| order/entities.py | M | 2fab1d | | INCLUDE |
| settlement/entities.py · runner.py | M | 84b4b4 | | INCLUDE |
| trading/account_models.py · *account_service* · admin_broker_accounts · admin_settlements | M | dac603+ | | INCLUDE |
| tests/test_step_2_5_*.py | UNTRACKED | | | INCLUDE |

**Can commit independently:** YES **before** STRAT-12 mig · **Required order:** after CP-03, before CP-05 · Risk: High (FK/backfill)

---

## E. WP-MIGRATION-CHAIN / STRAT-12 migrations

19 STEP12-related + chain (excl. 3 UBA above if split):

`bfc6…` → `27d47…` → `5b999…` → `89de…` → `6d736…` → `417184…` → `f5e265…` → `57df…` → `6464…` → `55c454…` → `339f8…` → `d73cd…` → `b2dd93…` → `eba1e…` → `a1c3f9…` → `c7e4a2…` → `e2b6d1…` → `f4a8c2…` → `a7f3e91c4d28`

| Path | Action |
|------|--------|
| 위 revision 파일들 | INCLUDE CP-05 (UBA 제외 시) |
| tests/migration_helpers.py | INCLUDE CP-04 or CP-05 (head 동적) |

---

## F. WP-STRAT12-BACKEND

| Area | Paths (대표) | STEP | Action |
|------|--------------|------|--------|
| Domain | `ai/strategy_request/`, `strategy_draft/`, `strategy_draft_generation/`, `strategy_draft_approval/` | 12.1–20 | INCLUDE CP-05 |
| API | `admin_strategy_*.py`, `user_strategy_*.py`, `admin_portfolio_validations.py` | | INCLUDE |
| Shared | `api/v1/admin_strategies.py` (대량), `backtest/*`, `performance/backtest_analytics.py`, `strategy_deployment/*` | | INCLUDE · REVIEW |
| Tests | `tests/test_step12_*.py` (~25) | | INCLUDE |
| MULTI | `api/router.py`, `deps_admin.py`, `operation/audit_repository.py` | | SPLIT_REQUIRED / 동일 CP-05 |

**부분 Substep 커밋:** Migration 선형·공유 라우터로 **비권장** · Risk: High

---

## G. WP-STRAT12-FRONTEND

| Path | Git | Action |
|------|-----|--------|
| frontend/.../admin/strategy-requests/ · strategy-drafts/ · portfolio-validations/ | UNTRACKED | INCLUDE CP-06 |
| frontend/.../user/strategy-requests/ · strategy-drafts/ | UNTRACKED | INCLUDE |
| adminApi.ts / userApi.ts / routes.ts / queryKeys.ts | M | MULTI — STRAT12 엔드포인트만 CP-06, Form 무관 변경은 CP-07 |

---

## H. WP-FRONTEND-UNRELATED

Form/`App.useApp` 등:

`admin/accounts`, `admin/ai/*` (message), `admin/risk`, `user/risk`, `user/settings`, SettingsEditor, MarketCalendar, Recovery*, AccountsView, BrokerCredential, ProfileWorkspace, AdminUpbitLiveUbaPanel

| Action | Can independent |
|--------|-----------------|
| INCLUDE CP-07 | YES · Risk: Low · STEP12 비의존 |

---

## I. WP-LEGACY-UNRELATED / HOLD

| Path | Notes | Action |
|------|-------|--------|
| ai/candidate_lifecycle/* · providers/* · prompt/seed_data.py | STEP11 후속 또는 draft seed | MANUAL_DECISION — seed면 CP-05 |
| tests/test_step11_* · test_step10_2 · test_step8_5_22_* | 소규모 (±4줄) — helpers/head | INCLUDE with CP-04/05 |
| docs/audit WORKTREE_* (본 세트) | 다음 커밋 | INCLUDE 후속 CP-DOC |

---

## J. MULTI_PACKAGE_FILE

| Path | Packages | Action |
|------|----------|--------|
| api/router.py | STRAT12 + maybe UBA | CP-05 (전체) |
| api/deps_admin.py | STRAT12 | CP-05 |
| adminApi.ts / userApi.ts | STRAT12 + FE | CP-06 우선, 잔여 CP-07 |
| routes.ts / queryKeys.ts | STRAT12 + FE | same |
| operation/audit_repository.py | STRAT12 audit events? | CP-05 REVIEW |
| README.md | Canonical + Archive links | CP-02+03 |

---

## K. Sensitive / Accidental

| Item | Result | Action |
|------|--------|--------|
| .env / secrets / dumps | status에 **없음** | — |
| High-risk secret assign | 0 (값) | — |
| routes.ts pattern hit | 오탐 가능 | HOLD 육안 |
| CRLF warnings | 다수 — 내용 변경과 별개 | 커밋 시 core.autocrlf 인지 |
| admin_strategies 3546+ | 기능 확장 | REVIEW not RESTORE |
| Build/cache | 미포함 | EXCLUDE |

---

## L. Recommended action legend

INCLUDE_IN_PACKAGE · SPLIT_REQUIRED · HOLD_FOR_REVIEW · EXCLUDE_FROM_COMMIT · MANUAL_DECISION_REQUIRED

**RESTORE_CANDIDATE:** 없음 (의도적 Archive 이동·STEP12 WIP).
