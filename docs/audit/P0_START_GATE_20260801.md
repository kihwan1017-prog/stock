# P0 START GATE — 2026-08-01

Candidate baseline: `48ad7fb` on `release/v1.1.0`  
선행: CP-01…CP-08 committed. Residual dirty 분류 및 flake 분석 완료.

**종합 Gate:** `48ad7fb`는 **문서·UBA·STEP12 코드 커밋 기준선**으로는 유효하나,  
Candidate Lifecycle 잔여 버그픽스(CP-09) 없이 STRAT12 expire/supersede 경로 및 관련 회귀는 **불완전**.

권장: **CP-09 승인·커밋 후**를 P0 실작업 기준선으로 승격.  
P0-1/P0-2/P0-5는 CP-09와 코드 충돌이 없으면 **별 브랜치/커밋으로 조건부 시작 가능**하나, dirty WT와 혼합 금지.

---

## P0-4 — Alembic Git/Head mismatch

| 항목 | 내용 |
|------|------|
| Required baseline | CP-04 + CP-05 migrations on Git |
| Residual dirty 영향 | **없음** |
| Migration 영향 | Git에 **22** revisions 추가 (UBA 3 + STRAT12 19). HEAD 파일 `a7f3e91c4d28_operation_readiness.py` 존재 |
| Alembic heads | **단일** `a7f3e91c4d28` |
| Chain | `dac603`→`2fab1d`→`84b4b4`→`bfc6ab7d28b2`→…→`a7f3e91c4d28` |
| Baseline mismatch | **Git 관점 해소** (이전 “WT only head” 문제 종료) |
| 운영 DB 적용 | **별도 Gate** — 본 Review에서 upgrade 미실행. 배포 전 `alembic upgrade` 승인 필요 |
| Required tests | migration_helpers / heads 정적 · step_2_5 · step12 샤딩 |
| Immediate start | “코딩으로 P0-4 수정” **불필요** — **CLOSED_AS_COMMITTED** (운영 적용은 OPEN) |
| Blocking | 운영 DB가 구 head면 배포 차단 (코드 작업과 분리) |

---

## P0-1 — Realtime `broker_code="KIWOOM"` hardcoding

| 항목 | 내용 |
|------|------|
| Required baseline | Clean tree 권장; UBA/STRAT12와 커밋 혼합 금지 |
| Residual dirty 영향 | lifecycle과 **무관**. 다만 WT dirty 있으면 커밋 혼선 위험 |
| Migration 영향 | 예상 없음 (확인 후) |
| Required tests | realtime/order unit + scope (Mock) |
| Immediate start | **조건부 YES** — CP-09를 먼저 처리하거나 **lifecycle 파일을 절대 stage하지 않는** 전용 커밋 |
| Blocking | LIVE OFF · 실주문 금지 · dirty 혼입 |

---

## P0-2 — Kiwoom Fill → Position disconnect

| 항목 | 내용 |
|------|------|
| Required baseline | STRAT12 비의존 |
| Residual dirty 영향 | 없음 (논리) |
| Migration 영향 | 설계 따름 |
| Required tests | mock WS + DB |
| Immediate start | **조건부 YES** (clean/dedicated commit) |
| Blocking | LIVE smoke는 별도 승인 |

---

## P0-3 — STEP12 → Runtime automatic linkage

| 항목 | 내용 |
|------|------|
| Required baseline | CP-05 코드 **필수** (`48ad7fb`에 포함됨) + **CP-09 강력 권장** |
| Residual dirty 영향 | lifecycle 전이 버그가 registration/readiness 전제 candidate 상태에 영향 가능 |
| Migration 영향 | STRAT12 mig 이미 Git |
| Required tests | step12_18/19 · operation readiness · runtime bootstrap (자동 start OFF) |
| Immediate start | **NO until CP-09** (권장 Gate) |
| Blocking | Registry 자동 start 기본 OFF 유지 · CP-09 |

---

## P0-5 — Paper Outbox auto-fill

| 항목 | 내용 |
|------|------|
| Required baseline | Paper 경로; STRAT12 비의존 |
| Residual dirty 영향 | 없음 |
| Migration 영향 | 예상 없음 |
| Required tests | Paper E2E (non-live) |
| Immediate start | **조건부 YES** |
| Blocking | Paper only · dirty 혼입 금지 |

---

## 시작 가능 요약

| P0 | Gate |
|----|------|
| P0-4 | **해소(Git)** / 운영 DB 적용은 별도 |
| P0-1 | 조건부 시작 (WT 정리 권장) |
| P0-2 | 조건부 시작 |
| P0-5 | 조건부 시작 |
| P0-3 | **CP-09 후** |

---

## 후속 Commit Package (계획만)

### CP-09 — Candidate Lifecycle Residual

| 필드 | 내용 |
|------|------|
| 필요 | **YES** |
| 대상 | `service.py`, `supersession.py` |
| 목적 | reason 마스킹 + candidate_id 조회 버그픽스 |
| 의존 | 없음 (이미 WT에 존재) |
| 테스트 | `test_step12_1a/2_1a/3/5/6` expire·supersede 소그룹; `test_step11_13_*` |
| Message 제안 | `fix(ai): correct candidate lifecycle reason masking and supersession lookup` |
| P0 전 필수 | **P0-3 YES** · 전체 기준선 승격 YES |
| 사용자 승인 | **필요** |

### CP-10 — Audit Residual

| 필드 | 내용 |
|------|------|
| 필요 | Optional |
| 대상 | `docs/audit/README_AUDIT_CODE_20260728.md` |
| 목적 | 인수 감사 원본 보존 |
| 의존 | 민감 패턴 육안 통과 |
| 테스트 | 문서 링크/민감 스캔 |
| Message 제안 | `docs(audit): add 2026-07-28 code acceptance audit` |
| P0 전 필수 | **NO** |
| 사용자 승인 | **필요** |

### CLEANUP-GATE — tmp log

| 필드 | 내용 |
|------|------|
| 필요 | Optional |
| 대상 | `tmp_step12_pytest.txt` |
| 목적 | 임시 로그 삭제 |
| P0 전 필수 | **NO** |
| 사용자 승인 | **필요** (삭제 금지 상태 유지 중) |

임의 CP-07A/B 등 추가 Package 생성하지 않음.
