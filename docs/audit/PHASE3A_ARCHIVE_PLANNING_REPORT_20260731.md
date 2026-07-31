# PHASE 3A ARCHIVE PLANNING REPORT — 2026-07-31

**역할:** Archive 이동 **계획만**. 기존 MD 이동·삭제·수정 **없음**.  
**Branch / Commit:** `release/v1.1.0` @ `3554ef8`  
**관련:** [MARKDOWN_ARCHIVE_MANIFEST_20260731.md](MARKDOWN_ARCHIVE_MANIFEST_20260731.md) · [PHASE3B_MOVE_BATCH_PLAN_20260731.md](PHASE3B_MOVE_BATCH_PLAN_20260731.md)

---

## 1. 최종 판정

**PASS_WITH_LIMITATIONS_PHASE3A_READY_FOR_BATCH_ARCHIVE**

제한:

1. Exact byte 중복 **0건** → 즉시 DELETE 후보 없음  
2. 루트 운영 문서(INSTALL/RUNBOOK 등) **링크 영향 큼** → Batch 4/5는 `MOVE_AFTER_LINK_UPDATE`  
3. Semantic duplicate는 자동 삭제 금지 · 수동 병합 필요  
4. `docs/CURRENT_WORK.md`가 아직 PHASE 2 Gate 문구(본 PHASE에서 **수정 금지**)  
5. PHASE1/2·Canonical 문서는 **UNTRACKED/MODIFIED 워킹트리** — Archive 대상 **아님**  
6. 제안 Archive 하위 폴더 중 일부는 **신규 생성 필요** (기존 `steps/`/`obsolete/`/`notes/`와 이름 충돌 없음)

---

## 2. 범위 준수

| 금지 항목 | 준수 |
|-----------|------|
| 기존 MD 수정·이동·삭제·개명 | 예 |
| 소스/Migration/테스트/DB/Runtime | 예 |
| git add/commit/push | 예 |
| 신규 audit 6종만 생성 | 예 |

---

## 3. 조사 요약

| 항목 | 수 |
|------|-----|
| 조사 Markdown (제외: node_modules/.venv/.next/dist/build/coverage/.git/.pytest_cache) | **382** |
| 루트 `*.md` | 54 |
| `docs/**/*.md` | 321 |
| 이미 `docs/archive/**` | 124 (`steps` 112 · `obsolete` 9 · `notes` 2 + README류) |
| `docs/audit/**` | 35 (본 PHASE3A 산출 전) |
| Exact duplicate groups (SHA-256) | **0** |
| Same basename (서로 다른 경로) | **10** 그룹 (README.md 폴더 인덱스 다수 포함) |
| Semantic duplicate (루트↔docs 내용 상이) | **≥10** 쌍 + 루트 단독 운영 문서 다수 |

상세: [MARKDOWN_DUPLICATE_HASH_REPORT_20260731.md](MARKDOWN_DUPLICATE_HASH_REPORT_20260731.md)

---

## 4. 분류 집계 (계획 기준)

| 분류 | 대략 수 | 비고 |
|------|---------|------|
| CANONICAL_PROTECTED | 17+ rules | AGENTS/CLAUDE/README + docs SoT + AI_* + STRATEGY_LIFECYCLE + `.cursor/rules` |
| ACTIVE_REFERENCE | ~120–140 | manual/development/ai/operations/trading/deployment/database/security + agent persona + CHANGELOG 등 |
| HISTORICAL_STEP (이미 archive) | ~112 | `docs/archive/steps/` — **재이동 불필요** |
| HISTORICAL_STEP (루트, 이동 후보) | 10 | `README_STEP56–64` 등 |
| HISTORICAL_COMPLETION_REPORT (후보) | ~18 | 루트 FINAL_*/README_AUDIT_*/SCORECARD 등 |
| HISTORICAL_AUDIT (유지) | ~12 | PHASE1/2 `*_20260731.md`, PHASE2 report |
| HISTORICAL_AUDIT (이동 후보) | ~22 | `AUDIT21` `docs/audit/STEP01–21` |
| SUPERSEDED | ~5 | Draft→Canonical, 루트 vs docs 구버전 |
| DUPLICATE_EXACT | 0 | — |
| DUPLICATE_SEMANTIC | ~15–25 | INSTALL/API/ARCHITECTURE 등 |
| ARCHIVE_CANDIDATE (신규 이동) | **~70** | Batch 1–5 |
| DELETE_CANDIDATE_AFTER_ARCHIVE | **0** 확정 | Exact dup 없음 |
| MANUAL_REVIEW_REQUIRED | ~15 | 루트 단독 운영 MD, account_digits 히스토리, CURRENT_WORK 갱신 |
| LEGACY_REFERENCE | 포함 | `alembic/versions/README.md` 등 |

---

## 5. Archive 목적지와 기존 구조

**기존:** `docs/archive/{steps,obsolete,notes}/`  
**제안 신규 (3B에서 mkdir):**

```text
docs/archive/
  completion-reports/
  audits/
  superseded/
  legacy/
  duplicates/
  installation/
  operations/
  testing/
  frontend/
  backend/
```

**충돌:** 기존 하위 이름과 **충돌 없음**. `docs/operations/`(Active)와 `docs/archive/operations/`는 별개 — 혼동 주의만 문서화.

임의로 `docs/archive` 밖 신규 트리를 만들지 않음.

---

## 6. 핵심 권장

1. **Batch 단위**로만 이동 (한 번에 전체 금지)  
2. Canonical·PHASE1/2·Active ops(`docs/operations`, `docs/deployment/CONFIGURATION.md` 등) **KEEP**  
3. 루트 포털은 README/AGENTS/CLAUDE/CHANGELOG/PROJECT_STATUS/persona **KEEP**; 나머지 루트 how-to/감사/STEP은 Archive  
4. AUDIT21 STEP12(Paper)는 `docs/archive/audits/`로 옮겨도 **STRAT-12와 병합하지 않음**  
5. 삭제 없음. Exact dup 발견 시에만 승인 후 DELETE 재검토  

---

## 7. Git / 워킹트리

| 상태 | 내용 |
|------|------|
| TRACKED_MODIFIED | `AGENTS.md`, `README.md`, `docs/README.md`, `docs/architecture/README.md`, `docs/audit/README.md` |
| UNTRACKED | PHASE2 Canonical 세트 · PHASE1 `*_20260731.md` 다수 · `CLAUDE.md` |
| Archive 후보 (루트 Historical) | 대부분 **TRACKED_UNMODIFIED** / COMMITTED_BASELINE |

워킹트리 전용 PHASE 문서를 Archive 대상으로 **확정하지 않음**.

---

## 8. 산출물

1. 본 파일  
2. [MARKDOWN_ARCHIVE_MANIFEST_20260731.md](MARKDOWN_ARCHIVE_MANIFEST_20260731.md)  
3. [MARKDOWN_LINK_IMPACT_REPORT_20260731.md](MARKDOWN_LINK_IMPACT_REPORT_20260731.md)  
4. [MARKDOWN_DUPLICATE_HASH_REPORT_20260731.md](MARKDOWN_DUPLICATE_HASH_REPORT_20260731.md)  
5. [MARKDOWN_SENSITIVE_CONTENT_REPORT_20260731.md](MARKDOWN_SENSITIVE_CONTENT_REPORT_20260731.md)  
6. [PHASE3B_MOVE_BATCH_PLAN_20260731.md](PHASE3B_MOVE_BATCH_PLAN_20260731.md)

---

## 9. STOP

PHASE 3A 종료. 실제 이동·링크 수정·소스 변경은 **사용자 승인 후 PHASE 3B**.
