# RESIDUAL DIRTY CLASSIFICATION — 2026-08-01

Baseline HEAD: `48ad7fb` (`release/v1.1.0`)  
범위: 읽기 전용 분류. 수정·restore·commit 없음.

---

## 잔여 Dirty 목록

| Path | Git | 패키지 후보 |
|------|-----|-------------|
| `src/stock_platform/ai/candidate_lifecycle/service.py` | Modified | CP-09 |
| `src/stock_platform/ai/candidate_lifecycle/supersession.py` | Modified | CP-09 |
| `docs/audit/README_AUDIT_CODE_20260728.md` | Untracked | CP-10 (검토 후) |
| `tmp_step12_pytest.txt` | Untracked | CLEANUP-GATE |

---

## 5.1 `candidate_lifecycle/service.py`

| 항목 | 내용 |
|------|------|
| Git status | `M` vs `48ad7fb` |
| Diff | +8 / −2 (실질: import + reason 마스킹 1줄) |
| 변경 symbol | `_apply_status` (또는 status transition 경로)에서 `sanitize_for_log` → `mask_pii` |
| 목적 | 문자열 `reason`에 dict 전용 `sanitize_for_log()`를 호출하면 `AttributeError: 'str' object has no attribute 'items'` 발생. expire/supersede/revoke(reason 있는 전이)가 항상 실패. |
| 추정 STEP | STEP12-1A 주석 (Candidate Lifecycle 버그픽스; STEP11 모듈 위 수정) |
| STEP11 관련 | 파일 소속은 STEP11-13 lifecycle 도메인 |
| STRAT12 관련 | STEP12 review/approval 게이트·테스트가 `expire(..., reason=...)` 호출 |
| CP-05 누락 | **예** — CP-05에 lifecycle 서비스 버그픽스가 포함되지 않음 |
| Committed 호출 | `strategy_draft_approval/service.py` 등이 `AICandidateLifecycleService` import; expire 경로 사용 |
| 테스트 사용 | `test_step12_1a`, `2_1a`, `3`, `5`, `6` 등에서 `expire`/`supersede`/`approve_revocation` + `reason=` |
| Migration | 없음 |
| API | Admin/user lifecycle API가 reason 문자열을 넘기면 동일 버그 |
| Runtime | 직접 runtime start와 무관; candidate 상태 전이 실패로 STRAT12 게이트 영향 |
| 독립 Commit | **가능** (2파일 묶음 CP-09) |
| 삭제/복원 | 복원(되돌리기) 비권장 — 기능 버그 수정 |
| **권장 처리** | **`REQUIRED_FOLLOWUP_COMMIT`** (+ `SHOULD_HAVE_BEEN_IN_CP05`) |

정적 재현(커밋된 헬퍼만):

```text
sanitize_for_log("테스트 만료") → AttributeError: 'str' object has no attribute 'items'
```

`git show HEAD:.../service.py`는 여전히 `sanitize_for_log(reason)` 사용.

---

## 5.2 `candidate_lifecycle/supersession.py`

| 항목 | 내용 |
|------|------|
| Git status | `M` vs `48ad7fb` |
| Diff | +18 / −2 |
| 변경 symbol | `validate_supersession_pair` — `session.get(Entity, candidate_id)` → `select().where(candidate_id==...)` |
| 목적 | PK는 `lifecycle_id`, 비즈니스 키는 `candidate_id`. `session.get`은 PK 조회라 MISSING 오탐/오조회 |
| 추정 STEP | STEP12-1A (주석이 `strategy_request/service.py` 동일 주의사항 언급) |
| STEP11 관련 | 모듈 소속 STEP11-13 |
| STRAT12 관련 | supersede 동시성/게이트 테스트가 `supersede()` → `validate_supersession_pair` 사용 |
| CP-05 누락 | **예** |
| Committed 호출 | supersede 경로 |
| 테스트 | `test_step12_*` supersede 동시성 등 |
| Migration/API/Runtime | Migration 없음; supersede API·STRAT12 게이트에 영향 |
| 독립 Commit | service.py와 함께 CP-09 |
| 삭제/복원 | 비권장 |
| **권장 처리** | **`REQUIRED_FOLLOWUP_COMMIT`** (+ `SHOULD_HAVE_BEEN_IN_CP05`) |

`lifecycle_id == candidate_id`인 행에서는 우연히 통과할 수 있어 **간헐적 통과** 가능. service.py reason 버그와 달리 항상 실패는 아님.

---

## 5.3 `docs/audit/README_AUDIT_CODE_20260728.md`

| 항목 | 내용 |
|------|------|
| 목적 | 2026-07-28 코드 기준 인수 감사 (읽기 전용 조사 결과) |
| 관련 | PHASE1/Archive 계획에서 HOLD / MANUAL_REVIEW |
| Canonical 반영 | 핵심 수치·P0는 PHASE2 Canonical에 재작성됨. 본 문서는 상세 인수 감사 원본 |
| 참조 | `MARKDOWN_*`, `WORKTREE_CHANGE_MANIFEST`, `COMMIT_BOUNDARY_PLAN` 등에서 HOLD로 언급 |
| Historical | 높음 (baseline `3554ef8` 시점 스냅샷) |
| 민감 | `postgresql://...` **스키마 언급**(자격증명 값 없음으로 육안). 과거 `pg_url_creds` 패턴 플래그 → 승인 전 재확인 |
| CP-01/08 누락 | 의도적 HOLD (누락 사고 아님) |
| Archive | 향후 `archive/audits/` Batch 후보 |
| **판정** | **`KEEP_UNTRACKED_PENDING_REVIEW`** → 육안 통과 시 `INCLUDE_IN_FOLLOWUP_AUDIT_COMMIT` (CP-10) 또는 `MOVE_IN_FUTURE_ARCHIVE_BATCH` |

---

## 5.4 `tmp_step12_pytest.txt`

| 항목 | 내용 |
|------|------|
| 목적 | CP-05 검증 중 step12 일괄 pytest quiet 요약 로그 |
| 테스트 로그 | 예 (progress dots + ERROR 목록, traceback 거의 없음) |
| 소스/문서 참조 | 코드에서 참조 **0** |
| 민감 | Credential 값 미포함(요약만). URL/비번 없음 |
| 재현 유일 근거 | **아님** — 본 Baseline Review에서 동일 증상 재현·traceback 확보 |
| Commit | **불필요** |
| **판정** | **`TEMPORARY_DELETE_CANDIDATE`** (사용자 승인 후 CLEANUP-GATE). Flake 문서화 완료 전 당분간 `KEEP_UNTIL_FLAKE_RESOLVED`도 허용 |

---

## Dirty ↔ CP-05 테스트 의존 (요약)

판정: **`CP05_TESTS_CONFIRMED_DEPENDENT_ON_RESIDUAL_DIRTY`**

근거:

1. HEAD 코드는 `sanitize_for_log(reason: str)` 호출.
2. `sanitize_for_log`는 `dict`만 처리 → 문자열 시 `AttributeError`.
3. 다수 `test_step12_*`가 `expire`/`supersede`/`approve_revocation`에 `reason="..."` 전달.
4. 워킹트리 수정본(`mask_pii`)에서는 해당 테스트 소그룹 **PASS**.
5. CP-05 커밋 시점에도 동일 dirty가 워킹트리에 존재했음 → 검증이 clean tree가 아님.

supersession PK 조회 버그도 supersede 경로에 영향 가능(간헐).

---

## 권장 후속 Package

| ID | 필요 | P0 전 필수 | 비고 |
|----|------|------------|------|
| CP-09 | **YES** | **YES** (STRAT12/P0-3 회귀 신뢰성) | lifecycle 2파일 |
| CP-10 | Optional | NO | README_AUDIT 육안 후 |
| CLEANUP-GATE | Optional | NO | tmp 삭제 승인 |
