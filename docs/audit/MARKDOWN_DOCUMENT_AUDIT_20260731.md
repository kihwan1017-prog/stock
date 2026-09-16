# MARKDOWN DOCUMENT AUDIT — 2026-07-31

읽기 전용. **삭제·이동·기존 MD 수정 없음.**

---

## 1. 규모

| 위치 | 대략 |
|------|------|
| 루트 `*.md` | ~53 |
| `docs/**/*.md` | ~296 |
| 합계 | ~350 |

제외: node_modules, .venv, .next, dist, coverage.

---

## 2. 분류 요약

| 분류 | 예 | 권장 |
|------|----|------|
| CANONICAL 후보 | `docs/README.md`, `docs/manual/`, `docs/development/README_STEP8_*`, `docs/ai/STEP11_*`, `docs/operations/`, `docs/trading/`, `docs/deployment/`, `docs/database/`, root `README.md`+`AGENTS.md` | KEEP → PHASE2에서 SoT 확정 |
| ACTIVE_REFERENCE | `docs/architecture/`, `docs/backend/`, `docs/security/`, `docs/testing/` | KEEP |
| HISTORICAL | `docs/archive/steps/README_STEP*` (~112), audit STEP01–21 | ARCHIVE 유지 |
| SUPERSEDED / DUPLICATE | 루트 `FINAL_*`, `README_AUDIT_*`, `ARCHITECTURE.md`/`INSTALL.md` 등 docs 복제본 | ARCHIVE_CANDIDATE |
| GENERATED_REPORT | `docs/audit/README_AUDIT_CODE_20260728.md`, 본 PHASE `*_20260731.md` | KEEP in audit/ |
| OUTDATED | routes.ts “ComingSoon”과 불일치하는 구 문서 문구 | 수정은 PHASE3+ |
| DELETE_CANDIDATE | (즉시 삭제 금지) 확인된 완전 중복·빈 파일만 후보로 표시 | 사용자 승인 후 |
| GAP | **STEP12 Canonical MD 없음** (테스트·코드만) | PHASE2에서 생성 |

---

## 3. 루트 문서 처리 방향 (제안만)

| 파일군 | 제안 |
|--------|------|
| AGENTS/SOUL/IDENTITY/USER/TOOLS/HEARTBEAT | KEEP (agent portal) |
| README/CHANGELOG/PROJECT_STATUS | KEEP |
| INSTALL/RUNBOOK/OPERATIONS/… (루트) | docs/ 와 중복 → ARCHIVE or 루트는 포인터만 (PHASE3) |
| README_STEP56–64, SECURITY_AUDIT_STEP62 | archive/steps 또는 obsolete |
| README_AUDIT_*, FINAL_*, PROJECT_FINAL_AUDIT | archive/audit-reports |

---

## 4. Cursor / Claude

| 경로 | 상태 |
|------|------|
| `AGENTS.md` | 존재 — PHASE2에서 SoT 강화 |
| `frontend/CLAUDE.md` | FE 국소 — 루트 CLAUDE.md 부재 |
| `.cursor/rules/documentation-structure.mdc` | 존재 — 확장 예정 (PHASE2) |

---

## 5. 내부 링크 / 민감정보

- `docs/README.md`가 도메인 인덱스 역할 — Canonical 후보  
- 민감정보: 감사 문서에 Secret 값 출력 금지 (준수). 일부 운영 문서에 경로 예시 존재 가능 → PHASE3 마스킹 점검

---

## 6. 수치 (대략)

| 항목 | 수 |
|------|----|
| Canonical/Active 후보 | ~40–60 |
| Historical/Archive | ~130+ |
| Superseded/Duplicate (루트 중심) | ~25–40 |
| Audit (기존+본 PHASE) | ~24 + 10 |
| Delete 후보 | 0 (확정 삭제 없음; 승인 대기) |
