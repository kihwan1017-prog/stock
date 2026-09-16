# CP-05 TEST FLAKE ANALYSIS — 2026-08-01

대상: `test_step12_*` non-live 일괄 실행 중 후반 ERROR 군집.  
범위: 읽기 전용 분석 + 안전한 pytest 재실행. 소스/tmp 수정·삭제 없음.

---

## 1. 증거 소스

| 소스 | 내용 |
|------|------|
| `tmp_step12_pytest.txt` | CP-05 당시 quiet 요약. ~91% 이후 ERROR 군집 (traceback 없음) |
| 2026-08-01 재실행 | `pytest -k step12_ -q --tb=short --maxfail=1` |
| 소그룹/단독 | 동일 실패 후보 파일·테스트 **PASS** |

---

## 2. 재현 결과

| 실행 | 결과 |
|------|------|
| `test_step12_5::test_provenance_valid_for_manual_draft` 단독 | **PASS** |
| `test_step12_5_backtest_readiness.py` 파일 전체 | **PASS** |
| early files(1~4) + 위 1건 | **PASS** |
| `test_step12_3` expire/supersede 필터 (WT dirty 포함) | **PASS** |
| `pytest -k step12_` 일괄 1회 | **FAIL/ERROR** (exit 1) |
| 일괄 + `--maxfail=1` | 첫 중단: `test_step12_5_backtest_readiness.py::test_provenance_not_found` **ERROR** |

일괄 재실행에서도 후반 파일(`5`→`9`)에서 ERROR가 연쇄. 단독/파일 단위는 통과 → **기능 회귀가 아닌 스위트 부하성**.

---

## 3. 최초 실패 Exception (재현)

```text
sqlalchemy.exc.OperationalError: (psycopg.OperationalError) connection failed:
connection to server at "127.0.0.1", port 5432 failed:
  … remaining connection slots are reserved for non-replication superuser connections
Multiple connection attempts failed.
```

(콘솔 로케일 깨짐 가능. 의미: PostgreSQL **connection slot 고갈** / superuser reserved slot만 남음.)

스택 핵심: `Session._connection_for_bind` → `pool.connect` → `psycopg.connection.connect`.

---

## 4. 요인 체크리스트

| 요인 | 판정 |
|------|------|
| Test ordering | 후반부에서만 발현 → 순서·누적과 상관 |
| Shared global state | Engine/Pool 공유 가능 |
| Database state leak (데이터) | 가능하나 직접 증거는 connection |
| Async event loop | 본 실패 스택에 없음 |
| Temp file collision | 증거 없음 |
| Environment configuration | 로컬 Postgres max_connections / pool 크기 |
| Rate limit | 무관 |
| Timing race | 부차 가능, 주원인 아님 |
| **Resource exhaustion** | **주원인 (DB connections)** |
| Non-flake functional | 단독 PASS로 기각 (본 ERROR에 한함) |
| Insufficient evidence | traceback 확보로 해소 |

부가: 일괄 요약에 `test_step12_4::test_definition_still_immutable_after_approval` **FAILED** 1건이 관측된 적 있음. 본 세션 maxfail=1에서는 connection ERROR가 먼저 차단되어 해당 FAILED를 재확인하지 못함 → **별도 MANUAL_REVIEW** (functional vs flake 미확정).

---

## 5. Flake 분류

**1차: `RESOURCE_EXHAUSTION`**  
**2차(기여): `DATABASE_STATE_LEAK`** (세션/커넥션 미반환 누적 가능)

`NON_FLAKE_FUNCTIONAL_FAILURE`로 일괄 ERROR 군집을 설명하지 않음.

---

## 6. Residual Dirty와의 관계

| 질문 | 답 |
|------|-----|
| Connection ERROR가 candidate_lifecycle dirty 때문인가? | **아니오** — pool checkout 단계에서 실패 |
| expire/reason 버그픽스가 일괄 ERROR를 유발하는가? | **아니오** |
| Dirty가 없으면 expire 테스트가 실패하는가? | **예** (별 이슈: `AttributeError` on `sanitize_for_log`) — flake와 **직교** |

---

## 7. CP-05 검증 신뢰도

| 모드 | 신뢰 |
|------|------|
| 파일/소그룹 step12 | 높음 (PASS 재확인) |
| 전체 `step12_*` 단일 프로세스 일괄 | **낮음** — 환경 connection 한도 |
| Clean tree (`48ad7fb` only, dirty 없음) | expire/supersede 경로 **기능 FAIL 예상** |

권장: 일괄 대신 **샤딩**(파일 그룹) 또는 pool/max_connections 조정 후 재검증. 본 단계에서는 테스트/앱 코드 수정 금지.

---

## 8. `tmp_step12_pytest.txt`

역사적 quiet 로그로 유지 가치는 낮음. Flake 원인은 본 문서로 대체.  
삭제: 사용자 **CLEANUP-GATE** 승인 후.

---

## 9. 결론

| 항목 | 값 |
|------|-----|
| Classification | `RESOURCE_EXHAUSTION` (+ connection leak 기여 가능) |
| Requires product fix before P0? | **Flake 자체는 NO** (인프라/테스트 격리) |
| Blocks baseline? | 일괄 green을 필수 조건으로 두면 YES; 샤딩 PASS를 허용하면 NO |
| Orthogonal blocker | CP-09 (lifecycle residual) **필수** |
