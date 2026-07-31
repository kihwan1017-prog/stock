# AI DOCUMENTATION STANDARDIZATION PLAN — 2026-07-31

**PHASE 1 산출:** 설계만. AGENTS/CLAUDE/Rules **생성·수정하지 않음.**  
사용자 승인 후 PHASE 2에서 생성.

---

## 1. 목표

Cursor AI와 Claude Code가 **동일 SoT**로 작업하고, STEP 번호·범위 중복을 방지한다.

---

## 2. 권장 Canonical 구조

```
AGENTS.md                          # 전 AI 공통 SoT (요약+링크)
CLAUDE.md                          # Claude 읽기 순서만 (중복 규칙 금지)
README.md                          # 인간용 포털

.cursor/rules/
  00-project-core.mdc
  10-backend.mdc
  20-frontend.mdc
  30-database.mdc
  40-testing.mdc
  50-documentation.mdc
  90-trading-safety.mdc

docs/
  CURRENT_WORK.md                  # 진행 중만
  PROJECT_IMPLEMENTATION_STATUS.md # 구현 현황 SoT
  STEP_MASTER_STATUS.md            # STEP 상태 SoT
  ROADMAP.md
  DECISION_LOG.md
  AI_PROJECT_CONTEXT.md
  AI_ARCHITECTURE.md
  AI_DEVELOPMENT_WORKFLOW.md
  AI_CODING_RULE.md
  AI_DB_RULE.md
  AI_TEST_RULE.md
  AI_SECURITY_RULE.md
  AI_TRADING_SAFETY.md
  architecture/ api/ operations/ testing/ audit/
  archive/
    steps/
    completion-reports/
    superseded/
    legacy/
    duplicates/
```

규칙: **내용을 여러 파일에 복사하지 않고 Canonical로 링크.**

---

## 3. AI별 읽기 순서

### CLAUDE.md (설계)

1. `AGENTS.md`  
2. `docs/CURRENT_WORK.md`  
3. `docs/PROJECT_IMPLEMENTATION_STATUS.md`  
4. `docs/STEP_MASTER_STATUS.md`  
5. 작업 관련 상세 (`AI_*`, architecture, trading-safety)

### Cursor Rules (설계)

- `00` → core + AGENTS 링크  
- `10–50` → 도메인 최소 규칙  
- `90` → LIVE fail-closed, Broker 호출 금지 기본, Order 승인  

Rules에 AGENTS 본문 대량 복사 금지.

---

## 4. STEP 완료 시 필수 갱신

1. CURRENT_WORK.md  
2. PROJECT_IMPLEMENTATION_STATUS.md  
3. STEP_MASTER_STATUS.md  
4. ROADMAP.md  
5. DECISION_LOG.md  
6. 관련 architecture/api/operations  

완료보고 → `docs/archive/completion-reports/` (Canonical 아님).

---

## 5. PHASE 2에서 생성할 문서

- 루트 `CLAUDE.md` (신규)  
- `AGENTS.md` 보강 (기존 있을 경우 **승인 후** 편집)  
- `.cursor/rules/00–90`  
- `docs/CURRENT_WORK.md`, `PROJECT_IMPLEMENTATION_STATUS.md`, `STEP_MASTER_STATUS.md`, `ROADMAP.md`, `DECISION_LOG.md`  
- `docs/AI_*.md` 세트  
- STEP12 Canonical: `docs/ai/STEP12_*` 또는 `docs/development/STEP12_*`  

PHASE 1 초안 소스: `PROJECT_IMPLEMENTATION_STATUS_DRAFT_20260731.md`, `PROJECT_REMAINING_WORK_20260731.md`, `STEP_NUMBER_MAPPING_20260731.md`.

---

## 6. PHASE 3에서 이동할 문서

- 루트 FINAL_/README_AUDIT_* → `docs/archive/`  
- 루트 INSTALL/RUNBOOK 복제본 → archive 또는 docs 포인터화  
- 완료보고 산재 → `completion-reports/`  
- deprecated `alembic/versions` → `docs/migration-overlays` 또는 archive 명시  

**삭제 없음** — 이동만.

---

## 7. 사용자 승인 후 삭제 가능 후보

- 완전 동일 바이트 중복 파일 (PHASE3에서 해시 비교 후 목록화)  
- 빈 디렉터리 플레이스홀더  
- 확인된 깨진 임시 스크립트  

PHASE 1에서는 **삭제 확정 0건**.

---

## 8. Trading Safety (Rules 90에 넣을 핵심)

- 문서보다 소스  
- LIVE 기본 OFF / fail-closed  
- Broker·주문·실계좌 조회는 명시 승인 없이 금지  
- STEP12 승인 ≠ Runtime start ≠ Order  
- Paper E2E 없이 LIVE 100% 금지  

---

## 9. STOP

이 문서는 계획이다. PHASE 2 착수 전 **사용자 승인** 필요.
