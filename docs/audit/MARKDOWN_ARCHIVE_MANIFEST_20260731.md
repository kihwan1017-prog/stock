# MARKDOWN ARCHIVE MANIFEST — 2026-07-31

**PHASE 3A — 이동 수행 없음.**  
**판정 근거:** 역할·STEP 매핑·링크·해시·Git 상태.  
**SoT:** [PHASE3A_ARCHIVE_PLANNING_REPORT_20260731.md](PHASE3A_ARCHIVE_PLANNING_REPORT_20260731.md)

범례 — Recommended action: `KEEP_IN_PLACE` · `MOVE_TO_ARCHIVE` · `MOVE_AFTER_LINK_UPDATE` · `CONSOLIDATE_LATER` · `DELETE_ONLY_AFTER_ARCHIVE_AND_APPROVAL` · `MANUAL_REVIEW`

Git: `COMMITTED_BASELINE` / `TRACKED_UNMODIFIED` / `TRACKED_MODIFIED` / `UNTRACKED` / `WORKTREE_ONLY`

---

## A. CANONICAL_PROTECTED (이동 금지)

| Source | Classification | Git | Action | Notes |
|--------|----------------|-----|--------|-------|
| AGENTS.md | CANONICAL_PROTECTED | TRACKED_MODIFIED | KEEP_IN_PLACE | AI SoT |
| CLAUDE.md | CANONICAL_PROTECTED | UNTRACKED | KEEP_IN_PLACE | Bootstrap |
| README.md | CANONICAL_PROTECTED | TRACKED_MODIFIED | KEEP_IN_PLACE | 포털 |
| docs/CURRENT_WORK.md | CANONICAL_PROTECTED | UNTRACKED | KEEP_IN_PLACE | 문구 갱신은 추후 승인 |
| docs/PROJECT_IMPLEMENTATION_STATUS.md | CANONICAL_PROTECTED | UNTRACKED | KEEP_IN_PLACE | |
| docs/STEP_MASTER_STATUS.md | CANONICAL_PROTECTED | UNTRACKED | KEEP_IN_PLACE | |
| docs/ROADMAP.md | CANONICAL_PROTECTED | UNTRACKED | KEEP_IN_PLACE | |
| docs/DECISION_LOG.md | CANONICAL_PROTECTED | UNTRACKED | KEEP_IN_PLACE | |
| docs/AI_*.md (8) | CANONICAL_PROTECTED | UNTRACKED | KEEP_IN_PLACE | |
| docs/architecture/STRATEGY_LIFECYCLE_STEP12.md | CANONICAL_PROTECTED | UNTRACKED | KEEP_IN_PLACE | STRAT-12 |
| .cursor/rules/*.mdc | CANONICAL_PROTECTED | mixed | KEEP_IN_PLACE | documentation-structure 포함 |

**Canonical 보호 수:** 17 MD + Cursor rules 세트.

---

## B. ACTIVE_REFERENCE (현 위치 유지 — 요약)

이동 후보 **아님**. 대표 경로:

- `docs/manual/**`, `docs/development/README_STEP8_*`, `docs/ai/STEP11_*`, `docs/operations/**`, `docs/trading/**`
- `docs/deployment/CONFIGURATION.md`, `DEPLOY_v1.1.0.md`, `ROLLBACK_v1.1.0.md`, `docs/deployment/INSTALL.md` (Canonical 설치 링크 대상)
- `docs/database/**`, `docs/security/**`, `docs/backend/**`, `docs/frontend/**`, `docs/release/**`
- `docs/architecture/ARCHITECTURE.md`, `DOMAIN_PACKAGE_MAP.md`, Kiwoom/Upbit 분석 MD
- `CHANGELOG.md`, `PROJECT_STATUS.md`, `THIRD_PARTY_NOTICES.md`
- Agent: `SOUL.md`, `IDENTITY.md`, `USER.md`, `TOOLS.md`, `HEARTBEAT.md`
- `frontend/README.md`, `frontend/CLAUDE.md`, `frontend/AGENTS.md` (포인터)
- `ops/README.md`, `docs/README.md` (인덱스 — TRACKED_MODIFIED)
- PHASE1/2 최신 audit: `PROJECT_FOUNDATION_AUDIT_*`, `AUTOTRADING_*`, `*_20260731.md` (draft 제외 권고는 §D), `PHASE2_*`

**Active 유지 추정:** ~120–140.

---

## C. 이미 Archive된 HISTORICAL (재이동 불필요)

| Path | Count | Action |
|------|-------|--------|
| docs/archive/steps/*.md | 112 | KEEP_IN_PLACE (`HISTORICAL_STEP` / MAIN) |
| docs/archive/obsolete/** | 9 | KEEP_IN_PLACE |
| docs/archive/notes/** | 2 | KEEP_IN_PLACE |
| docs/archive/README.md | 1 | KEEP_IN_PLACE |

---

## D. MOVE 후보 — Batch 1 Completion / Product Reports

공통: Classification `HISTORICAL_COMPLETION_REPORT` 또는 `HISTORICAL_AUDIT` · Destination `docs/archive/completion-reports/` · Exact duplicate `none` · Manual approval **YES** · Rollback = `git mv` 역방향 또는 백업 복사.

| Source | Title (약) | Class | STEP | Canonical replacement | Dest | Reason | Hist value | Inbound (approx) | Link upd | Hash16 | Action | Sens |
|--------|------------|-------|------|----------------------|------|--------|------------|------------------|----------|--------|--------|------|
| FINAL_AUDIT_REPORT.md | Final audit | HISTORICAL_COMPLETION_REPORT | REL/AUDIT | PROJECT_IMPLEMENTATION_STATUS | completion-reports/ | 루트 완료성 주장 | High | ~8 | YES | 36CA21A07D5F8DC4 | MOVE_AFTER_LINK_UPDATE | low |
| FINAL_PRODUCT_REPORT.md | Product report | HISTORICAL_COMPLETION_REPORT | REL | same | completion-reports/ | Historical | Med | ~1 | YES | B0D79D521767330A | MOVE_TO_ARCHIVE | low |
| FINAL_RELEASE_REPORT_v1.1.0.md | v1.1 release | HISTORICAL_COMPLETION_REPORT | REL-75 | CHANGELOG / release docs | completion-reports/ | Release archive | High | ~2 | YES | 57806FE9AF41DF8F | MOVE_AFTER_LINK_UPDATE | low |
| PROJECT_FINAL_AUDIT.md | Project final audit | HISTORICAL_AUDIT | MAIN | IMPLEMENTATION_STATUS | completion-reports/ | Pre-canonical | High | ~14 | YES | 1803E5BDF2A829E0 | MOVE_AFTER_LINK_UPDATE | low |
| README_FINAL_AUDIT.md | Final audit readme | HISTORICAL_AUDIT | — | same | completion-reports/ | Duplicate role | Med | ~1 | YES | 9AFBC4A47057693A | MOVE_TO_ARCHIVE | low |
| README_FULL_SYSTEM_AUDIT.md | Full system audit | HISTORICAL_AUDIT | — | PHASE1 foundation | completion-reports/ | Orphan inbound 0 | Med | 0 | NO | 03B724C11723C94B | MOVE_TO_ARCHIVE | low |
| README_AUDIT_01.md | Audit 01 | HISTORICAL_AUDIT | — | docs/audit PHASE1 | completion-reports/ | Root audit | Med | ~3 | YES | 6B0A4B5B39CC60E0 | MOVE_AFTER_LINK_UPDATE | low |
| README_AUDIT_API.md | Audit API | HISTORICAL_AUDIT | — | docs/backend + audit | completion-reports/ | | Med | ~3 | YES | 336E19CB1CB84F37 | MOVE_AFTER_LINK_UPDATE | low |
| README_AUDIT_DB.md | Audit DB | HISTORICAL_AUDIT | — | docs/database | completion-reports/ | | Med | ~2 | YES | F29BD52EEB7B5C29 | MOVE_TO_ARCHIVE | low |
| README_AUDIT_TEST.md | Audit test | HISTORICAL_AUDIT | — | AI_TEST_RULE | completion-reports/ | | Med | ~3 | YES | BB43EC6D7BE57CEC | MOVE_AFTER_LINK_UPDATE | low |
| PRODUCTION_SCORECARD.md | Scorecard | SUPERSEDED | — | IMPLEMENTATION_STATUS | completion-reports/ | Scores outdated | Med | ~3 | YES | C30838D5CAC51B85 | MOVE_AFTER_LINK_UPDATE | low |
| TOP_100_IMPROVEMENTS.md | Top 100 | LEGACY_REFERENCE | — | ROADMAP | completion-reports/ | Wishlist hist | Med | ~5 | YES | 5E0FC697B66D085F | MOVE_AFTER_LINK_UPDATE | low |
| PROJECT_REFACTOR_PLAN.md | Refactor plan | LEGACY_REFERENCE | HIST-55+ | ROADMAP / DECISION_LOG | completion-reports/ | Plan hist | High | ~4 | YES | 48A7F29D1AFC717D | MOVE_AFTER_LINK_UPDATE | low |
| README_ISSUES.md | Issues index | LEGACY_REFERENCE | — | KNOWN / KI_* | completion-reports/ | Pointer hist | Low | ~2 | YES | 69F3BB7F5430A196 | MOVE_TO_ARCHIVE | low |
| RELEASE_NOTE.md | Generic RN | HISTORICAL_COMPLETION_REPORT | — | versioned notes | completion-reports/ | Stub 5 lines | Low | ~2 | YES | B3C4A101E4BC82E0 | MOVE_TO_ARCHIVE | low |
| RELEASE_NOTE_v1.0.0.md | RN 1.0 | HISTORICAL_COMPLETION_REPORT | REL | CHANGELOG | completion-reports/ | | Med | — | YES | AC3499DDCACE1FD9 | MOVE_AFTER_LINK_UPDATE | low |
| RELEASE_NOTE_v1.0.0_RC1.md | RN RC1 | HISTORICAL_COMPLETION_REPORT | REL | CHANGELOG | completion-reports/ | | Med | — | YES | 03206E018EB52D06 | MOVE_TO_ARCHIVE | low |
| RELEASE_NOTE_v1.1.0.md | RN 1.1 | HISTORICAL_COMPLETION_REPORT | REL-75 | KEEP link from README optional | completion-reports/ | Still linked by README | High | README | YES | B3E1A660045E1DAE | MOVE_AFTER_LINK_UPDATE | low |
| RELEASE_RISK.md | Release risk | HISTORICAL_COMPLETION_REPORT | — | AI_TRADING_SAFETY | completion-reports/ | | Med | ~2 | YES | 6F3E06FF36753FA7 | MOVE_TO_ARCHIVE | low |
| RELEASE_CHECKLIST.md | Release checklist | DUPLICATE_SEMANTIC | — | docs/deployment/RELEASE_CHECKLIST.md | completion-reports/ or duplicates/ | Basename pair | Med | ~10 | YES | 7B60D3A73360A3E9 | MOVE_AFTER_LINK_UPDATE | low |

각 행 공통 필드 보충:

- **Referenced by / Links contained:** [MARKDOWN_LINK_IMPACT_REPORT_20260731.md](MARKDOWN_LINK_IMPACT_REPORT_20260731.md)  
- **Filename collision:** `FINAL_AUDIT_REPORT.md` ↔ `docs/audit/FINAL_AUDIT_REPORT.md` (내용 상이) → archive 시 `root_FINAL_AUDIT_REPORT.md` 또는 `completion-reports/root/` 하위 권장  
- **Rollback path:** `docs/archive/completion-reports/<name>` → 원 루트 경로  

---

## E. MOVE 후보 — Batch 2 Root STEP (MAIN / REL)

Destination: `docs/archive/steps/` (기존). **Filename collision:** archive에 동명 `README_STEP56.md` 등 존재 가능 → 이동 전 **충돌 검사 필수**. 충돌 시 `docs/archive/steps/root-portal/README_STEP56.md` 등 하위 폴더.

| Source | Class | Related STEP | Dest | Reason | Inbound | Collision risk | Hash16 | Action |
|--------|-------|--------------|------|--------|---------|----------------|--------|--------|
| README_STEP56.md | HISTORICAL_STEP | HIST-56 / MAIN | archive/steps/ | 루트 잔존 STEP | ~2 | CHECK | 04B7D35A63EAB11B | MOVE_AFTER_LINK_UPDATE |
| README_STEP57.md | HISTORICAL_STEP | HIST-57 | archive/steps/ | | 0 | CHECK | 89F6E9F7AB1CC83B | MOVE_TO_ARCHIVE |
| README_STEP57_1_REMOVE_OPENCLAW.md | HISTORICAL_STEP | HIST-57.1 | archive/steps/ | | 0 | LOW | 1CC10611F2024F39 | MOVE_TO_ARCHIVE |
| README_STEP58.md | HISTORICAL_STEP | HIST-58 | archive/steps/ | | 0 | CHECK | D3ACE89AD17B4DE6 | MOVE_TO_ARCHIVE |
| README_STEP59.md | HISTORICAL_STEP | HIST-59 | archive/steps/ | | ~1 | CHECK | 8EF684DEFD13B689 | MOVE_AFTER_LINK_UPDATE |
| README_STEP60.md | HISTORICAL_STEP | HIST-60 | archive/steps/ | Deploy hist | ~2 | CHECK | 9FAAAD35955A4E41 | MOVE_AFTER_LINK_UPDATE |
| README_STEP61.md | HISTORICAL_STEP | HIST-61 | archive/steps/ | | 0 | CHECK | B01FEB16357D9D7B | MOVE_TO_ARCHIVE |
| README_STEP62.md | HISTORICAL_STEP | HIST-62 / REL-62 | archive/steps/ | | 0 | CHECK | 8EAE472EC0BFA60F | MOVE_TO_ARCHIVE |
| README_STEP64.md | HISTORICAL_STEP | HIST-64 | archive/steps/ | | ~3 | CHECK | F17F9F753B8C8FE6 | MOVE_AFTER_LINK_UPDATE |
| SECURITY_AUDIT_STEP62.md | HISTORICAL_AUDIT | REL-62 | archive/steps/ or audits/ | Security hist | ~3 | LOW | 49AA67524C689A2B | MOVE_AFTER_LINK_UPDATE |

**Namespace:** MAIN/REL. **STRATEGY STRAT-12와 무관.** Audit Paper STEP12와 병합 금지.

---

## F. MOVE 후보 — Batch 3 Superseded / AUDIT21

### F1. Keep in `docs/audit/` (이동 금지)

PHASE1/2: `PROJECT_FOUNDATION_AUDIT_20260731.md`, `AUTOTRADING_EXECUTION_FLOW_AUDIT_20260731.md`, `SOURCE_COMPONENT_INVENTORY_*`, `DATABASE_MIGRATION_*`, `TEST_COVERAGE_*`, `MARKDOWN_DOCUMENT_AUDIT_*`, `STEP_NUMBER_MAPPING_*`, `AI_DOCUMENTATION_STANDARDIZATION_PLAN_*`, `PHASE2_*`, `PHASE3A_*`(본 세트), `TEST_COVERAGE_*` 등.

### F2. Superseded drafts → `docs/archive/audits/superseded-20260731/` 또는 `docs/archive/superseded/`

| Source | Class | Canonical replacement | Action | Hash16 |
|--------|-------|----------------------|--------|--------|
| docs/audit/PROJECT_IMPLEMENTATION_STATUS_DRAFT_20260731.md | SUPERSEDED | PROJECT_IMPLEMENTATION_STATUS.md | MOVE_AFTER_LINK_UPDATE | 5D4E2D1EDE324829 |
| docs/audit/PROJECT_REMAINING_WORK_20260731.md | SUPERSEDED | ROADMAP.md (P0 ID는 Canonical 우선) | MOVE_AFTER_LINK_UPDATE | 827B565C2E9DD273 |

### F3. AUDIT21 STEP01–21 → `docs/archive/audits/audit21/`

| Pattern | Count | Class | Related | Canonical | Action |
|---------|-------|-------|---------|-----------|--------|
| docs/audit/STEP01_*.md … STEP21_*.md | 21+ | HISTORICAL_AUDIT | AUDIT21-* | PHASE1 foundation / domain docs | MOVE_AFTER_LINK_UPDATE |
| 포함 STEP12_PAPER_TRADING.md | 1 | HISTORICAL_AUDIT | **AUDIT21-12** | ≠ STRAT-12 | MOVE_AFTER_LINK_UPDATE · **병합 금지** |

`docs/README.md` · `docs/audit/README.md` 링크 대량 수정 필요.

### F4. Older audit reports

| Source | Class | Dest | Action | Hash16 |
|--------|-------|------|--------|--------|
| docs/audit/FINAL_AUDIT_REPORT.md | HISTORICAL_AUDIT | archive/audits/ | MOVE_AFTER_LINK_UPDATE (docs/README) | 0F3D5711CAAE6AAC |
| docs/audit/README_AUDIT_CODE_20260728.md | HISTORICAL_AUDIT | archive/audits/ | MANUAL_REVIEW (pg_url pattern) | 8B02D1D816835E10 |
| docs/audit/FINAL_AUDIT_REPORT vs root | DUPLICATE_SEMANTIC | 각각 보존 | CONSOLIDATE_LATER | 상이 해시 |

---

## G. MOVE 후보 — Batch 4 Install / Ops / API basename duplicates

Destination: `docs/archive/duplicates/` 또는 성격별 `installation/` / `backend/` / `operations/`.

| Source | Class | Docs twin | Norm/hash equal? | Dest proposal | Action | Hash16 |
|--------|-------|-----------|------------------|---------------|--------|--------|
| INSTALL.md | DUPLICATE_SEMANTIC | docs/deployment/INSTALL.md | **No** (107 vs 22 lines) | archive/installation/root_INSTALL.md | MOVE_AFTER_LINK_UPDATE | AF3963318217F383 |
| ARCHITECTURE.md | DUPLICATE_SEMANTIC | docs/architecture/ARCHITECTURE.md | No | archive/duplicates/ | MOVE_AFTER_LINK_UPDATE | FDE4BB696A63E260 |
| API.md | DUPLICATE_SEMANTIC | docs/backend/API.md | No | archive/backend/ | MOVE_AFTER_LINK_UPDATE | 37DBAAF4F2C9428E |
| README_USER_ADMIN_ARCHITECTURE_AUDIT.md | DUPLICATE_SEMANTIC | docs/architecture/… | No (127 vs 204) | archive/audits/ | MOVE_AFTER_LINK_UPDATE | 38BA903378118A0A |
| INCIDENT_RESPONSE.md | DUPLICATE_SEMANTIC | docs/trading/INCIDENT_RESPONSE.md | (compare 3B) | archive/operations/ | MOVE_AFTER_LINK_UPDATE | 44855B13B93A37EE |
| RELEASE_CHECKLIST.md | DUPLICATE_SEMANTIC | docs/deployment/… | (see Batch1) | duplicates/ | MOVE_AFTER_LINK_UPDATE | 7B60D3A73360A3E9 |

**Canonical replacement:** 항상 **docs/** 쪽 Active 문서. 루트는 Historical 장문본일 수 있음 → 삭제 말고 Archive.

---

## H. MOVE 후보 — Batch 5 Legacy root ops (docs twin 없음 또는 Active는 docs/operations)

| Source | Class | Canonical / Active | Dest | Reason | Inbound | Action | Hash16 | Sens |
|--------|-------|-------------------|------|--------|---------|--------|--------|------|
| OPERATIONS.md | LEGACY_REFERENCE | docs/operations/** | archive/operations/ | 루트 운영 포털 잔존 | ~10 | MOVE_AFTER_LINK_UPDATE | 23E56445B758B17A | secrets_path |
| RUNBOOK.md | LEGACY_REFERENCE / ACTIVE_REF mixed | docs/operations + manual | archive/operations/ | 링크 많음 | ~18 | MANUAL_REVIEW then MOVE_AFTER_LINK_UPDATE | 8AE4D17BCAD0A9A8 | — |
| SECURITY.md | LEGACY_REFERENCE | docs/security + AI_SECURITY | archive/operations/ | | ~8 | MOVE_AFTER_LINK_UPDATE | D9E4A2ABF9EBC9E7 | secrets_path |
| BACKUP.md | LEGACY_REFERENCE | docs/deployment / ops | archive/operations/ | | ~7 | MOVE_AFTER_LINK_UPDATE | 26D7805E715EF8F8 | — |
| RECOVERY.md | LEGACY_REFERENCE | docs/operations recovery | archive/operations/ | | ~7 | MOVE_AFTER_LINK_UPDATE | 592F3E71A54CAEE9 | secrets_path |
| DB_SCHEMA.md | LEGACY_REFERENCE | docs/database/** | archive/backend/ | | ~3 | MOVE_AFTER_LINK_UPDATE | E30887ACDAAB6865 | — |
| GO_LIVE_CHECKLIST.md | LEGACY_REFERENCE | docs/operations LIVE checklists | archive/operations/ | | ~5 | MOVE_AFTER_LINK_UPDATE | B9A95C950C301BAE | — |
| KNOWN_ISSUES.md | LEGACY_REFERENCE | docs/security KI_* / trading KI_* | archive/operations/ | | ~17 | MOVE_AFTER_LINK_UPDATE | 6A73E3C1D2729030 | — |

**RUNBOOK.md:** README·manual이 직접 링크 — 3B에서 루트에 **포인터 스텁**을 둘지(수정) vs README만 갱신할지 **수동 승인**. PHASE 3A는 기존 파일 수정 금지이므로 스텁 생성은 3B 범위.

---

## I. DELETE 후보

| 항목 | 수 | Action |
|------|----|--------|
| Exact duplicate | 0 | — |
| DELETE_ONLY_AFTER_ARCHIVE_AND_APPROVAL | **0** 확정 | Semantic만 Archive |

---

## J. MANUAL_REVIEW_REQUIRED (이동 전)

| Item | Reason |
|------|--------|
| RUNBOOK.md 처리 방식 | 고트래픽 링크 · Active 대체 문서 분산 |
| docs/audit/README_AUDIT_CODE_20260728.md | `pg_url_creds` 패턴 플래그 |
| archive/steps 동명 충돌 | 루트 README_STEP* vs 기존 archive |
| FINAL_AUDIT_REPORT 이중 | root vs docs/audit 내용 상이 — 둘 다 보존 |
| frontend/AGENTS.md | 루트 AGENTS와 역할 — KEEP 권장 |
| CURRENT_WORK.md PHASE2 문구 | Canonical이나 본 PHASE 수정 금지 → 승인 후 갱신 |
| account_digits in archive STEP29_* | 이미 archive · 값 노출 없이 보존 |

---

## K. 이동 금지 요약

- 전 §A Canonical  
- Active domain docs (`docs/development`, `docs/ai` STEP11, `docs/operations`, …)  
- PHASE1/2 decision audits (`*_20260731` foundation 등)  
- 이미 `docs/archive/steps|obsolete|notes`  
- Persona / CHANGELOG / PROJECT_STATUS  

---

## L. Manifest 필드 템플릿 (3B 실행 시 체크리스트)

각 이동 파일에 대해 3B가 확인할 항목:

1. Source path / Proposed destination / Filename collision resolved  
2. Referenced by list updated  
3. Links contained retargeted or left as historical relative  
4. Content hash recorded pre-move  
5. Rollback path documented  
6. Manual approval checkbox  

전체 inbound 목록은 Link Impact 보고서 참조.
