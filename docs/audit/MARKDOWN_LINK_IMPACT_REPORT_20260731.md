# MARKDOWN LINK IMPACT REPORT — 2026-07-31

**PHASE 3A — 링크 수정 수행 없음.** 이동 시 깨질 참조만 목록화.

스캔 범위: 전 Markdown + `.cursor/rules/*.mdc` + `ops/` + `scripts/` + `.github/` (존재 시).  
방법: 대상 **파일명** 문자열 매칭 (false positive 가능 — 3B에서 경로 단위 재확인).

---

## 1. 요약

| 항목 | 값 |
|------|-----|
| 고영향 (inbound ≥10) | INSTALL, ARCHITECTURE, API, OPERATIONS, RUNBOOK, KNOWN_ISSUES, RELEASE_CHECKLIST, PROJECT_FINAL_AUDIT |
| 중영향 (3–9) | SECURITY, BACKUP, RECOVERY, FINAL_AUDIT_REPORT, INCIDENT_RESPONSE, GO_LIVE, TOP_100, STEP docs 일부 |
| 저영향 (0–2) | README_FULL_SYSTEM_AUDIT, README_STEP57/58/61/62, README_STEP57_1 |
| CI (`.github`) MD 경로 참조 | **검출 없음** |
| 소스 `.py/.ts` 주석 전수 | 본 보고서에서 파일명 매칭 샘플만 — 3B Batch 전 `rg` 권장 |

---

## 2. 루트 이동 후보 → Inbound (발췌)

| Target | ≈Inbound | 대표 Referenced by | PHASE 3B 수정 후보 |
|--------|----------|--------------------|--------------------|
| INSTALL.md | 17 | README.md, docs/deployment/*, FINAL_PRODUCT_REPORT, README_STEP60 | README, deployment README, obsolete README |
| ARCHITECTURE.md | 16 | README, docs/architecture, docs/README, audit | README, docs/README |
| RUNBOOK.md | 18 | README, GO_LIVE, docs/manual/*, docs/operations, INSTALL | **고위험** — manual 한글 경로 포함 |
| KNOWN_ISSUES.md | 17 | CHANGELOG, API, INSTALL, RUNBOOK, RELEASE notes | CHANGELOG, README |
| API.md | 16 | README, docs/backend, FINAL_PRODUCT, README_AUDIT_* | README, backend README |
| PROJECT_FINAL_AUDIT.md | 14 | archive/steps README_STEP52–55, audit STEP01, README_ISSUES | archive steps (다수) |
| RELEASE_CHECKLIST.md | 10 | docs/deployment, INSTALL, GO_LIVE, release README | deployment |
| OPERATIONS.md | 10 | README, INSTALL, RUNBOOK, FINAL_PRODUCT | README |
| INCIDENT_RESPONSE.md | 9 | RUNBOOK, OPERATIONS, trading README | trading + root |
| FINAL_AUDIT_REPORT.md | 8 | docs/audit/README, docs/README, SECURITY, CHANGELOG | docs indexes |
| SECURITY.md | 8 | README, RUNBOOK, AI_SECURITY_RULE, INCIDENT | README, AI_SECURITY (상대경로 주의) |
| BACKUP.md / RECOVERY.md | 7 each | GO_LIVE, DEPLOY/ROLLBACK v1.1 | deployment |
| GO_LIVE_CHECKLIST.md | 5 | README, INSTALL, OPERATIONS | README |
| TOP_100_IMPROVEMENTS.md | 5 | SCORECARD, FINAL_*, SECURITY | low |
| README_STEP64.md | 3 | RELEASE_NOTE_v1.0, FINAL_PRODUCT, RECOVERY | |
| README_STEP60.md | 2 | docs/deployment, INSTALL | |
| README_FULL_SYSTEM_AUDIT.md | 0 | — | 링크 수정 최소 |

Canonical 파일(`AGENTS.md` 등)이 가리키는 경로는 주로 `docs/` Canonical — 루트 INSTALL 이동 시 **README.md** 갱신이 핵심.

---

## 3. AUDIT21 이동 시 영향

| 참조자 | 영향 |
|--------|------|
| docs/README.md | STEP01–21 Quick links **대량** |
| docs/audit/README.md | 표 전체 |
| docs/audit/STEP21_FINAL.md | 상호 링크 |
| docs/audit/FINAL_AUDIT_REPORT.md | |

**3B 필수:** `docs/README.md`, `docs/audit/README.md` 경로를 `docs/archive/audits/audit21/`로 일괄 치환.

---

## 4. Superseded draft 이동 시

| Target | Referenced by (예상) |
|--------|----------------------|
| PROJECT_IMPLEMENTATION_STATUS_DRAFT_20260731.md | PHASE2 report, foundation audit, IMPLEMENTATION_STATUS 본문 |
| PROJECT_REMAINING_WORK_20260731.md | ROADMAP, PHASE2 report |

Canonical 본문은 draft를 Historical로 링크 중 — 이동 후 상대경로 갱신.

---

## 5. Cursor Rules / AGENTS / CLAUDE

| 파일 | 루트 Historical 직접 의존 |
|------|---------------------------|
| AGENTS.md | Canonical `docs/*` 위주 — 루트 INSTALL 비의존 |
| CLAUDE.md | docs Canonical |
| .cursor/rules/* | AGENTS + docs AI_* |

→ Batch 1–5에서 Rules 수정 **최소**. README·docs 인덱스·상호 Historical 링크가 본체.

---

## 6. 스크립트 / 테스트 경로

권장 3B 검증 명령 (실행은 승인 후):

```powershell
rg -n "INSTALL\.md|RUNBOOK\.md|FINAL_AUDIT_REPORT|README_STEP6|STEP12_PAPER" `
  --glob '!node_modules/**' --glob '!.venv/**' --glob '!.next/**'
```

본 PHASE에서는 위 명령을 **계획만** 기록 (대규모 출력 생략).

---

## 7. 이동 후 깨짐 유형

1. **상대 링크:** `../INSTALL.md` → archive 깊이 변경  
2. **동일 basename:** root vs docs twin — 잘못된 파일로 해석  
3. **README 포털:** 루트 표 행 404  
4. **Archive steps 내부:** `PROJECT_FINAL_AUDIT.md` 루트 참조  

---

## 8. PHASE 3B 링크 수정 파일 우선순위

1. `README.md`  
2. `docs/README.md`  
3. `docs/audit/README.md`  
4. `docs/deployment/README.md` · `INSTALL.md`(docs) · `RELEASE_CHECKLIST.md`(docs)  
5. `docs/operations/README.md` · `docs/trading/README.md` · `docs/manual/*`  
6. 상호 참조 Historical (FINAL_*, README_STEP*, SCORECARD)  
7. (선택) 루트 포인터 스텁 — **신규 파일**이면 3B 승인 범위에 명시
