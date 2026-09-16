# PHASE 3B MOVE BATCH PLAN — 2026-07-31

**전제:** PHASE 3A Manifest 승인 후 실행. **한 번에 전체 이동 금지.**  
**본 문서는 계획만** — 이동·링크 수정 미수행.

참조: [MARKDOWN_ARCHIVE_MANIFEST_20260731.md](MARKDOWN_ARCHIVE_MANIFEST_20260731.md) · [MARKDOWN_LINK_IMPACT_REPORT_20260731.md](MARKDOWN_LINK_IMPACT_REPORT_20260731.md)

---

## 공통 규칙 (모든 Batch)

1. 사전: `git status` · 대상 해시 기록 · 동명 충돌 검사  
2. `docs/archive/<dest>/` mkdir (없을 때만)  
3. `git mv` 선호 (history 유지) — 승인된 커밋 Gate에서만  
4. 링크 수정은 **별도 커밋** 또는 동일 Batch 내 명시  
5. 검증: 상대 링크 스크립트 · `rg` 옛 경로  
6. Rollback: `git mv` 역방향 / `git checkout` (승인된 범위)  
7. Canonical·PHASE1/2·Active domain **금지**  
8. STRAT-12 ≠ AUDIT21-12 병합 금지  

**사용자 승인:** Batch마다 **개별 승인** 권장.

---

## Batch 1 — 완료보고 · Historical 제품/감사 (루트)

| 항목 | 값 |
|------|-----|
| 대상 수 | ~20 |
| 예 | FINAL_*, README_AUDIT_*, PRODUCTION_SCORECARD, TOP_100, PROJECT_REFACTOR_PLAN, RELEASE_NOTE*, RELEASE_RISK, README_ISSUES, (선택) RELEASE_CHECKLIST |
| 목적지 | `docs/archive/completion-reports/` |
| 위험도 | **Medium** (README·CHANGELOG 링크) |
| 링크 수정 | README.md, CHANGELOG.md, 상호 FINAL_* |
| 충돌 | `FINAL_AUDIT_REPORT.md` vs docs/audit — 파일명 분리 |
| Rollback | completion-reports → 루트 |
| 검증 | README 링크 · hash 불변 |
| 승인 | **필수** |

---

## Batch 2 — 과거 STEP (루트 README_STEP*)

| 항목 | 값 |
|------|-----|
| 대상 수 | ~10 |
| 예 | README_STEP56–64, SECURITY_AUDIT_STEP62 |
| 목적지 | `docs/archive/steps/` 또는 `steps/root-portal/` (충돌 시) |
| 위험도 | **Medium–High** (동명 충돌) |
| 링크 수정 | INSTALL, RELEASE notes, docs/deployment README |
| 충돌 | **사전 `Test-Path` 필수** |
| Rollback | 역 mv |
| 검증 | archive/steps README 인덱스 (있으면) |
| 승인 | **필수** |

Namespace: MAIN/REL only.

---

## Batch 3 — 대체된 Audit

| 항목 | 값 |
|------|-----|
| 대상 수 | ~24 (AUDIT21 ~21 + drafts 2 + optional older reports) |
| 예 | `docs/audit/STEP01`–`STEP21`, STATUS_DRAFT, REMAINING_WORK; optional FINAL_AUDIT (docs), README_AUDIT_CODE_20260728 (수동 후) |
| 목적지 | `docs/archive/audits/audit21/` · `docs/archive/superseded/` |
| 위험도 | **High** (docs/README · audit/README 대량) |
| 링크 수정 | docs/README.md, docs/audit/README.md, STEP21_FINAL |
| 충돌 | 낮음 (신규 폴더) |
| Rollback | audits → docs/audit |
| 검증 | docs/README Quick links |
| 승인 | **필수** · AUDIT21-12 Paper 라벨 유지 |
| Keep | 모든 `*_20260731` PHASE1/2 foundation · PHASE2/3A reports |

---

## Batch 4 — 중복 설치·API·아키텍처

| 항목 | 값 |
|------|-----|
| 대상 수 | ~6 |
| 예 | root INSTALL, ARCHITECTURE, API, README_USER_ADMIN_*, INCIDENT_RESPONSE, RELEASE_CHECKLIST |
| 목적지 | `docs/archive/duplicates/` 또는 installation/backend/operations |
| 위험도 | **High** (포털 링크) |
| 링크 수정 | README → docs/deployment/INSTALL 등 **Active twin** |
| 충돌 | basename — `root_` 접두 권장 |
| Rollback | 역 mv |
| 검증 | README 설치 섹션 클릭 경로 |
| 승인 | **필수** |

---

## Batch 5 — Legacy · Semantic (루트 단독 운영 MD)

| 항목 | 값 |
|------|-----|
| 대상 수 | ~8 |
| 예 | OPERATIONS, RUNBOOK, SECURITY, BACKUP, RECOVERY, DB_SCHEMA, GO_LIVE_CHECKLIST, KNOWN_ISSUES |
| 목적지 | `docs/archive/operations/` · `archive/backend/` (DB_SCHEMA) |
| 위험도 | **Highest** (RUNBOOK inbound ~18) |
| 링크 수정 | README, manual, operations README — 또는 **포인터 스텁** 정책 |
| 충돌 | 낮음 |
| Rollback | 역 mv + 스텁 제거 |
| 검증 | 수동 주요 진입 링크 |
| 승인 | **필수** · RUNBOOK은 **MANUAL_REVIEW 통과 후** |

---

## 권장 실행 순서

```text
Batch 1 → 검증/승인
Batch 2 → 충돌 해결 → 검증/승인
Batch 3 → docs 인덱스 → 검증/승인
Batch 4 → README 포털 → 검증/승인
Batch 5 → RUNBOOK 정책 결정 → 검증/승인
```

P0 소스 수정·STEP12 커밋과 **섞지 말 것**.

---

## PHASE 3B 권장 범위 (첫 승인)

**최소 안전 범위:** Batch 1만 (완료보고) + 링크 수정 최소 세트.  
Batch 2–5는 후속 승인.

---

## 검증 명령 초안 (3B용)

```powershell
# 이동 후 옛 루트 경로 잔존 참조
rg -n "\]\(INSTALL\.md\)|\]\(RUNBOOK\.md\)|\]\(FINAL_AUDIT_REPORT\.md\)" --glob '*.md'

# archive 목적지 존재
Test-Path docs/archive/completion-reports
```

---

## STOP (3A)

이 계획을 실행하지 않은 채 사용자 승인을 기다린다.
