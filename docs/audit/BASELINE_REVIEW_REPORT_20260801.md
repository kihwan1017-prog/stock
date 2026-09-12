# BASELINE REVIEW REPORT — 2026-08-01

## Verdict

**`PASS_WITH_LIMITATIONS_BASELINE_READY_AFTER_CP09`**

부판정(의존성): **`CP05_TESTS_CONFIRMED_DEPENDENT_ON_RESIDUAL_DIRTY`**  
Flake: **`RESOURCE_EXHAUSTION`** (PostgreSQL connection slots) — 제품 기능 실패와 구분.

Candidate baseline `48ad7fb`는 CP-01…CP-08 구조·Alembic Git head·UBA/STRAT12 커밋 경계는 유효하다.  
그러나 `candidate_lifecycle` 잔여 수정이 STRAT12 테스트·expire/supersede 경로에 **필수**이므로, P0 기준선 승격 전 **CP-09**를 권장한다.

---

## 1. Scope compliance

| 금지 항목 | 준수 |
|-----------|------|
| 소스 수정/이동/삭제 | YES |
| git add/commit/push/restore/reset | YES |
| Migration upgrade / Broker / Runtime | YES |
| 신규 보고서 4종만 생성 | YES |
| 기존 문서 수정 | YES (미수정) |

---

## 2. Branch / HEAD

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| Previous baseline | `3554ef8` |
| Candidate baseline | `48ad7fb` (`48ad7fb52414611a0e54dd1bbfc9b1f5bf1437db`) |
| Staged | 0 |
| Merge/rebase | 없음 |
| Push | 0 |

---

## 3. CP-01…CP-08 구조 검증

| CP | Hash | Parent | Message | 일치 |
|----|------|--------|---------|------|
| 01 | `194b302` | `3554ef8` | docs(audit): add project foundation assessment | 10 audit docs only |
| 02 | `4086045` | `194b302` | docs: establish canonical project guidance | Canonical/rules (README·CURRENT_WORK는 CP-03) |
| 03 | `98f4c6c` | `4086045` | docs(archive): preserve historical completion reports | R100×16 + links + PHASE3A/B |
| 04 | `7d7452f` | `98f4c6c` | feat(trading): enforce broker account ownership | UBA 3 mig + entities/tests |
| 05 | `3badeed` | `7d7452f` | feat(ai): add strategy lifecycle workflow | STRAT12 19 mig + BE (117 files) |
| 06 | `391d849` | `3badeed` | feat(frontend): add strategy lifecycle management | STRAT12 FE 9 files |
| 07 | `beea255` | `391d849` | fix(frontend): improve Ant Design Form… | Form/useApp 23 files |
| 08 | `48ad7fb` | `beea255` | docs(audit): record worktree commit boundaries | audit 6 only · **소스 0** |

검증 포인트:

- CP-04 **앞** → CP-05 **뒤** ✓  
- CP-05 `bfc6ab7d28b2.down_revision = 84b4b4a8c996` (CP-04 말단) ✓  
- CP-06는 CP-05 API 이후 ✓  
- CP-03: rename + 링크 동일 커밋 ✓  
- CP-08: docs/audit만 ✓  
- 중간 커밋 import/mig chain: UBA→STRAT12 단일 체인 ✓  
- CP-05에 `candidate_lifecycle/{service,supersession}.py` **미포함** (잔여 dirty로 남음)

민감정보: 커밋 메타/파일명 수준 검사에서 실 Secret 미검출.

---

## 4. Alembic

| 항목 | 값 |
|------|-----|
| Heads | 1 × `a7f3e91c4d28` |
| Since `3554ef8` | **22** migration files on Git |
| CP-04 | `dac603`, `2fab1d`, `84b4b4` |
| CP-05 | `bfc6` … `a7f3` (19) |
| P0-4 Git mismatch | **해소** |
| 운영 DB upgrade | 미실행 (별도 Gate) |

---

## 5. Residual dirty (요약)

상세: [RESIDUAL_DIRTY_CLASSIFICATION_20260801.md](./RESIDUAL_DIRTY_CLASSIFICATION_20260801.md)

| 파일 | 판정 |
|------|------|
| `candidate_lifecycle/service.py` | `REQUIRED_FOLLOWUP_COMMIT` / `SHOULD_HAVE_BEEN_IN_CP05` |
| `candidate_lifecycle/supersession.py` | 동일 |
| `README_AUDIT_CODE_20260728.md` | `KEEP_UNTRACKED_PENDING_REVIEW` |
| `tmp_step12_pytest.txt` | `TEMPORARY_DELETE_CANDIDATE` |

---

## 6. CP-05 tests vs residual dirty

**`CP05_TESTS_CONFIRMED_DEPENDENT_ON_RESIDUAL_DIRTY`**

- HEAD: `sanitize_for_log(reason)`  
- `sanitize_for_log`는 dict 전용 → 문자열 시 `AttributeError`  
- `test_step12_*` 다수가 `expire`/`supersede`에 `reason=` 전달  
- WT(`mask_pii`)에서 해당 소그룹 PASS  
- CP-05 검증 당시에도 동일 dirty 존재

---

## 7. STEP12 일괄 flake

상세: [CP05_TEST_FLAKE_ANALYSIS_20260801.md](./CP05_TEST_FLAKE_ANALYSIS_20260801.md)

| 항목 | 값 |
|------|-----|
| Classification | `RESOURCE_EXHAUSTION` |
| Exception | `sqlalchemy.exc.OperationalError` / psycopg connection slot 고갈 |
| Solo/file | PASS |
| Full batch | ERROR 연쇄 |
| Dirty 인과 | 없음 (직교) |

---

## 8. Backend / Frontend 검증

| Suite | Result |
|-------|--------|
| Collection `step12_` | PASS (collect-only) |
| `test_step_2_5_*` | **PASS** |
| step12 expire/supersede 소그룹 | **PASS** (WT dirty 포함) |
| step12 file `test_step12_5` | **PASS** |
| step12 일괄 | **FLAKY** / RESOURCE_EXHAUSTION |
| Frontend Vitest/build | CP-06/07 시점 **PASS** (본 Review 재실행 생략) |

---

## 9. P0 Gate 요약

상세: [P0_START_GATE_20260801.md](./P0_START_GATE_20260801.md)

| P0 | 시작 |
|----|------|
| P0-4 | Git **해소** (운영 DB는 별도) |
| P0-1 | 조건부 YES |
| P0-2 | 조건부 YES |
| P0-5 | 조건부 YES |
| P0-3 | **CP-09 후** |

---

## 10. Follow-up packages (계획만)

| Package | 필수 | 승인 |
|---------|------|------|
| CP-09 lifecycle residual | YES (기준선 승격) | 필요 |
| CP-10 README_AUDIT | Optional | 필요 |
| CLEANUP-GATE tmp | Optional | 필요 |

Commit/삭제/구현: **본 단계 미수행**.

---

## 11. Generated reports

1. `docs/audit/BASELINE_REVIEW_REPORT_20260801.md` (본 문서)  
2. `docs/audit/RESIDUAL_DIRTY_CLASSIFICATION_20260801.md`  
3. `docs/audit/CP05_TEST_FLAKE_ANALYSIS_20260801.md`  
4. `docs/audit/P0_START_GATE_20260801.md`

---

## 12. Final Git state (after report create)

예상 dirty:

- `M` candidate_lifecycle ×2  
- `??` README_AUDIT_CODE_20260728.md  
- `??` tmp_step12_pytest.txt  
- `??` 본 Baseline Review 보고서 4종  

Staged=0 · Push=0.

---

## 13. Next recommended actions

1. 사용자 승인 후 **CP-09** 명시적 stage/commit  
2. (선택) README_AUDIT 육안 → CP-10 또는 Archive Batch  
3. (선택) tmp 삭제 CLEANUP-GATE  
4. CP-09 후 baseline tag/note → P0-1/5/2 → P0-3  
5. step12 일괄은 샤딩 또는 DB connection 한도 조정 후 재검증  

**STOP GATE:** 추가 commit/push/P0 구현/Batch2/migration/runtime 금지.
