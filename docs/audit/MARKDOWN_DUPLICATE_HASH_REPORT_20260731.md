# MARKDOWN DUPLICATE HASH REPORT — 2026-07-31

**PHASE 3A.** 알고리즘: **SHA-256** (전체 파일 바이트).  
줄바꿈 정규화 비교는 주요 basename 쌍에 추가.

---

## 1. Exact duplicate

| 항목 | 결과 |
|------|------|
| Exact duplicate groups | **0** |
| Exact duplicate files | **0** |
| CRLF-only twins (정규화 후 동일) | 조사한 주요 쌍에서 **0** |

→ `DELETE_ONLY_AFTER_ARCHIVE_AND_APPROVAL` **확정 0건**.

---

## 2. Same basename (경로만 다름)

| Basename | Count | Paths | Exact? | Classification |
|----------|-------|-------|--------|----------------|
| README.md | 28 | 루트·docs 각 폴더·frontend·ops·alembic… | N/A (인덱스) | ACTIVE_REFERENCE (각 KEEP) |
| INSTALL.md | 2 | root · docs/deployment/ | **No** | DUPLICATE_SEMANTIC |
| ARCHITECTURE.md | 2 | root · docs/architecture/ | **No** | DUPLICATE_SEMANTIC |
| API.md | 2 | root · docs/backend/ | **No** | DUPLICATE_SEMANTIC |
| FINAL_AUDIT_REPORT.md | 2 | root · docs/audit/ | **No** | DUPLICATE_SEMANTIC |
| INCIDENT_RESPONSE.md | 2 | root · docs/trading/ | 미정(라인 비교 권장) | DUPLICATE_SEMANTIC |
| RELEASE_CHECKLIST.md | 2 | root · docs/deployment/ | 미정 | DUPLICATE_SEMANTIC |
| README_USER_ADMIN_ARCHITECTURE_AUDIT.md | 2 | root · docs/architecture/ | **No** (127 vs 204 lines) | DUPLICATE_SEMANTIC |
| AGENTS.md | 2 | root · frontend/ | 상이 역할 | CANONICAL vs FE pointer |
| CLAUDE.md | 2 | root · frontend/ | FE는 `@AGENTS.md` | CANONICAL vs pointer |

---

## 3. Semantic pair detail (hash / lines)

| A (root) | Hash16 | Lines | B (docs) | Equal? | Notes |
|----------|--------|-------|----------|--------|-------|
| INSTALL.md | AF3963318217F383 | 107 | docs/deployment/INSTALL.md | **No** | 루트가 장문 — Archive 가치 High |
| ARCHITECTURE.md | FDE4BB696A63E260 | 42 | docs/architecture/ARCHITECTURE.md | **No** | |
| API.md | 37DBAAF4F2C9428E | 90 | docs/backend/API.md | **No** | |
| README_USER_ADMIN… | 38BA903378118A0A | 127 | docs/architecture/… | **No** | docs가 더 김 |
| FINAL_AUDIT_REPORT.md | 36CA21A07D5F8DC4 | 224 | docs/audit/FINAL_AUDIT_REPORT.md (0F3D5711CAAE6AAC, 78) | **No** | **둘 다 보존** |

OPERATIONS / RUNBOOK / SECURITY / BACKUP / RECOVERY / DB_SCHEMA / GO_LIVE / KNOWN_ISSUES: **docs 동명 twin 없음** (또는 trading INCIDENT만) → Semantic “복제”가 아니라 **루트 LEGACY 단독본**.

---

## 4. Semantic duplicate 처리 규칙 (재확인)

| 판정 | 조치 |
|------|------|
| Canonical로 통합 완료 + 고유 장문 이력 | `MOVE_TO_ARCHIVE` / `duplicates/` 또는 domain archive |
| 일부 고유 정보 | Archive · **삭제 금지** |
| Historical only | Archive |
| 수동 병합 필요 | `CONSOLIDATE_LATER` + `MANUAL_REVIEW` |

---

## 5. Canonical protected hashes (무결성 스냅샷)

| Path | SHA-256 prefix16 |
|------|------------------|
| AGENTS.md | 586C48673E1530AC |
| CLAUDE.md | F9B189AB783672A2 |
| README.md | 97776BF54E25D8EE |
| docs/CURRENT_WORK.md | B6BE5310FFDBA5C0 |
| docs/PROJECT_IMPLEMENTATION_STATUS.md | 7688BC09DFFABDF3 |
| docs/STEP_MASTER_STATUS.md | E35C31251D1BDC46 |
| docs/ROADMAP.md | 38526BDB6809C156 |
| docs/DECISION_LOG.md | 22F3148989949693 |
| docs/architecture/STRATEGY_LIFECYCLE_STEP12.md | 5D8C233DE19F9DC2 |

(AI_* 8종 해시는 PHASE3A Planning Report / 작업 로그에 기록됨.)

---

## 6. 결론

- **완전 동일 파일로 지울 대상 없음.**  
- Archive 가치는 **Semantic·Historical** 쪽에 집중.  
- Basename 충돌 시 목적지 파일명에 `root_` 접두 또는 하위 폴더 사용.
