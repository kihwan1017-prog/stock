# PHASE 2 DOCUMENTATION STANDARDIZATION 완료보고

**일자:** 2026-07-31  
**Branch:** `release/v1.1.0`  
**Commit baseline:** `3554ef8`  
**범위:** Canonical 문서·Cursor Rules·루트 AGENTS/CLAUDE/README 표준화만 (소스/Archive/커밋 없음)

---

## 1. 최종 판정

**PASS_WITH_LIMITATIONS_PHASE2_READY_FOR_ARCHIVE_PLANNING**

제한사항:

- 기존 Historical 문서(루트 STEP README, audit STEP, 완료보고)는 아직 Archive 미이동 (PHASE 3)
- PHASE1 `PROJECT_REMAINING_WORK`의 P0 번호와 Canonical P0가 다름 → Canonical(PHASE2) 고정, PHASE1은 Historical
- 링크 검사는 상대 경로 위주; 루트 `/reference/…` 스타일 링크는 스킵
- 구현률은 추정치 유지 (소스 테스트 미실행 — PHASE2 비필수)

---

## 2. 범위 준수

| 항목 | 준수 |
|------|------|
| Python/TS/SQL/Migration/테스트 수정 | 예 (미수행) |
| 기존 MD 삭제·이동·이름변경·Archive | 예 (미수행) |
| 신규 Canonical MD / Cursor Rules | 예 |
| AGENTS/README 병합 | 예 |
| Broker/Runtime/주문/git commit·push | 예 (미수행) |
| `docs/README.md` / `architecture/README.md` 링크 추가 | 예 (인덱스 갱신, 이동 아님) |

---

## 3. 생성 문서

### 루트

- `CLAUDE.md` (신규)

### Cursor Rules

- `.cursor/rules/00-project-core.mdc`
- `.cursor/rules/10-backend.mdc`
- `.cursor/rules/20-frontend.mdc`
- `.cursor/rules/30-database.mdc`
- `.cursor/rules/40-testing.mdc`
- `.cursor/rules/50-documentation.mdc`
- `.cursor/rules/90-trading-safety.mdc`

### Canonical / AI

- `docs/CURRENT_WORK.md`
- `docs/PROJECT_IMPLEMENTATION_STATUS.md`
- `docs/STEP_MASTER_STATUS.md`
- `docs/ROADMAP.md`
- `docs/DECISION_LOG.md`
- `docs/AI_PROJECT_CONTEXT.md`
- `docs/AI_ARCHITECTURE.md`
- `docs/AI_DEVELOPMENT_WORKFLOW.md`
- `docs/AI_CODING_RULE.md`
- `docs/AI_DB_RULE.md`
- `docs/AI_TEST_RULE.md`
- `docs/AI_SECURITY_RULE.md`
- `docs/AI_TRADING_SAFETY.md`
- `docs/architecture/STRATEGY_LIFECYCLE_STEP12.md`
- `docs/audit/PHASE2_DOCUMENTATION_STANDARDIZATION_REPORT_20260731.md` (본 파일)

---

## 4. 수정 문서

| 파일 | 변경 요지 |
|------|-----------|
| `AGENTS.md` | 프로젝트 SoT(§1–14) 선두 배치; 기존 persona/memory 섹션은 §15로 보존·하위 |
| `README.md` | NOT READY 경고 · Canonical 링크 · P0 · 스택/진입 유지, 전체 사양서화 방지 |
| `docs/README.md` | Canonical SoT 표 추가 |
| `docs/architecture/README.md` | STRATEGY_LIFECYCLE_STEP12 링크 |

**유지:** `.cursor/rules/documentation-structure.mdc` (삭제·대체 없음) · `frontend/CLAUDE.md` (`@AGENTS.md` 포인터)

---

## 5. 기존 문서와 병합한 내용

### AGENTS.md (전)

- OpenClaw식 Session/Memory/Red Lines/Heartbeat + 짧은 documentation-structure 포인터

### AGENTS.md (후)

- 상단: 목적·스택·SoT 순서·Canonical 맵·Gate·안전·P0·문서/Git 규칙
- 하단: persona continuity (충돌 시 상단 우선)

### README.md

- v1.1.0 포털 유지 + 운영 미준비 경고·Canonical 표·안전 주의 강화
- Historical 릴리즈 링크 보존

### CLAUDE.md

- 루트에 신규 Bootstrap (frontend CLAUDE와 역할 분리)

---

## 6. Canonical Source of Truth 구조

```text
README.md
  → AGENTS.md
       → CURRENT_WORK.md
       → PROJECT_IMPLEMENTATION_STATUS.md
       → STEP_MASTER_STATUS.md
       → ROADMAP.md
       → DECISION_LOG.md / AI_* / STRATEGY_LIFECYCLE_STEP12
CLAUDE.md → AGENTS.md (읽기 순서)
Cursor Rules → AGENTS.md (짧은 도메인 규칙만)
```

완료보고 = Historical. SoT 아님.

---

## 7. AGENTS.md 적용 내용

- SoT 우선순위 · 작업 전 읽기 · Gate · Backend/FE/DB/테스트 요약 · 문서 4종 필수 갱신
- LIVE/PAPER · Scope · 금지 작업 · 완료보고 규칙
- P0-1…P0-5 고정
- Persona 섹션 보존

---

## 8. CLAUDE.md 적용 내용

- AGENTS 최상위 선언
- 읽기 순서 1–5
- Audit→…→User Approval
- 백그라운드/권한 확대 해석 금지
- Broker/완료 판단/보고 양식
- 공통 규칙 비복제

---

## 9. Cursor Rules 적용 내용

| Rule | 역할 |
|------|------|
| 00 | AGENTS 우선 · 범위 · Gate |
| 10 | Backend session/scope/broker |
| 20 | Frontend RBAC/stub |
| 30 | Alembic single head |
| 40 | 테스트 계층 · no live broker |
| 50 | Canonical vs Historical |
| 90 | Trading safety always |

`documentation-structure.mdc`와 공존.

---

## 10. 현재 구현 현황

| 지표 | 값 |
|------|-----|
| 개발 구현률 | ~76% (추정) |
| Paper 준비도 | ~72% (추정) |
| LIVE 준비도 | ~48% (추정) |
| 운영 가능 | **NOT READY** |
| LIVE | **NOT APPROVED** |
| Paper 무인 | **NOT READY** |

---

## 11. P0 Blocking

| ID | 내용 |
|----|------|
| P0-1 | Realtime `broker_code="KIWOOM"` 하드코딩 |
| P0-2 | Kiwoom Fill → TradingOrder → Position/Balance/P&L 단절 |
| P0-3 | STEP12 ↔ Scoped Runtime 불일치·자동 연결 부재 |
| P0-4 | 커밋 Alembic Head ↔ 워킹트리 Head 불일치 |
| P0-5 | Paper Outbox ACCEPTED → 자동 Fill 부재 |

---

## 12. STEP Mapping

- Namespace: MAIN/HIST · AUDIT21 · STRATEGY(`STRAT-12`) · DEV-8 · AI-11
- Audit STEP12(Paper) ≠ Strategy STEP12 — [STEP_MASTER_STATUS.md](../STEP_MASTER_STATUS.md)
- AI-11.13: COMMITTED · STRAT-12.1–20: WORKTREE

---

## 13. STEP12 Canonical 정리

- [architecture/STRATEGY_LIFECYCLE_STEP12.md](../architecture/STRATEGY_LIFECYCLE_STEP12.md)
- 12-1…20 맵 · API/FE/Tests/Migration · Runtime GAP(P0-3) · 실행 WRITE 0

---

## 14. 문서 링크 검사 결과

- 생성 대상 파일: **전부 존재**
- 상대 링크: PHASE2 보고서 생성 후 CLAUDE/CURRENT_WORK → 본 보고서 링크 **해소**
- Cursor rule → `../../AGENTS.md` 등 상대 경로 사용
- CURRENT_WORK / ROADMAP / README에 종합 수치·P0 ID 정합 보강

---

## 15. 민감정보 검사 결과

- API 키·비밀번호·토큰 값 **미기록**
- 시크릿 **경로 관례**만 README에 유지 (기존과 동일, 값 없음)

---

## 16. 충돌 또는 제한사항

1. PHASE1 remaining-work P0 번호 ≠ Canonical P0 → DEC-20260731-11로 Canonical 고정  
2. README/릴리즈의 STEP74 CONDITIONAL APPROVAL ≠ 자동매매 READY (Canonical이 우선)  
3. `docs/README.md` 상단 Canonical 추가 — 하위 audit STEP 링크 목록은 Historical로 잔존 (PHASE3 후보)

---

## 17. PHASE 3 Archive 후보

이동만 (삭제 금지), 승인 후:

- 루트 비포털 how-to/완료성 문서 중복분
- 오래된 완료보고 → `docs/archive/completion-reports/`
- PHASE1 draft가 Canonical로 승격된 뒤 audit draft에 SUPERSEDED 배너(이동 또는 배너만)
- 루트 `alembic/versions` 문서화/ARCHIVE 표기 (코드 삭제는 별도 승인)

---

## 18. 삭제 후보

**삭제 수행하지 않음.** 후보만:

- 내용이 Canonical과 100% 중복인 초안(승격 후)
- 깨진 전용 임시 메모 (확인 후)

---

## 19. Git 상태

- Branch: `release/v1.1.0` (tracking origin)
- HEAD: `3554ef8`
- 본 PHASE로 **문서·rules만** 추가/수정. **commit/push 없음**
- 기존 워킹트리 STEP12/FE/Migration WIP는 그대로 dirty

---

## 20. 다음 권장 작업

1. 사용자: PHASE 2 판정 승인  
2. PHASE 3: Archive 계획 수립·이동 (소스 변경 없이)  
3. 별도 승인 후: P0-4 커밋 경계 → P0-1/P0-5 → P0-3 Runtime 정합  
4. 소스 P0 수정은 **문서 PHASE와 분리된 Gate**

---

**STOP GATE:** PHASE 2 종료. Archive·소스·P0 구현·commit/push·다음 STEP 개발은 사용자 승인 전 금지.
