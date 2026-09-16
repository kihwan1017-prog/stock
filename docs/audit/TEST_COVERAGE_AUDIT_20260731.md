# TEST COVERAGE AUDIT — 2026-07-31

읽기 전용. 실 Broker / live_ai / live 마커 테스트 **미실행**.

---

## 1. 수집 규모

| 구분 | 규모 |
|------|------|
| Backend `tests/test_*.py` | **276** 파일 |
| Frontend vitest `*.test.*` | **40** |
| E2E | `frontend/e2e/smoke.spec.ts` (1) |
| pytest 기본 addopts | `-m "not external and not live and not live_ai"` (`pytest.ini`) |
| conftest | LIVE flags false, USE_MOCK true |

이전 세션에서 커밋 기준 전체 suite는 **1412 passed** 기록이 있음.  
워킹트리에 STEP12 테스트 ~25+ 추가되어 **수집 수는 증가**했을 가능성 — 본 PHASE에서는 전수 실행하지 않음.

---

## 2. 분류

| 카테고리 | ~파일 | 비고 |
|----------|------|------|
| Unit/Domain | 다수 | kiwoom/upbit mapper MockTransport |
| Service/API | 다수 | FastAPI TestClient |
| PostgreSQL Integration | step8 migration, ownership | `-m integration` |
| Concurrency | outbox fencing | step8_5_22 |
| Frontend | 40 | components/utils |
| Paper | paper_execution, paper E2E 일부 | |
| Broker Mock | kiwoom/upbit clients | |
| Runtime/Scheduler | step8_5_5, step9, step10_2 | |
| Order/Execution | outbox, execution | |
| Recovery | step8_5_3, 8_11, 8_12 | |
| Security | step62, step40 recovery security | |
| AI STEP11 | 13 | |
| Strategy STEP12 | ~25 | 미커밋 |
| Ops | telegram, dashboard, rehearsal | |

---

## 3. 실행 금지 / 주의

| 패턴 | 조치 |
|------|------|
| `-m live` / `live_ai` | 실행 금지 (본 PHASE) |
| Upbit/Kiwoom live smoke 파일명 | 기본 suite에서 mock 여부 확인 후 |
| External network AI | skip |
| Real credential vault decrypt against prod | skip |

---

## 4. 누락된 핵심 테스트

1. **Market → Signal → Outbox → Fill → Position** 단일 E2E (Paper)  
2. **Upbit scoped signal** with correct broker_code (현재 하드코딩 버그 재현 테스트)  
3. **Kiwoom WS fill → TradingOrder**  
4. **STEP12 Registration → active runtime → order** (의도적 비연결이므로 “게이트 테스트”로 명시)  
5. Frontend e2e beyond smoke  
6. STEP12 canonical docs 부재 → 문서 테스트 N/A  

---

## 5. 판정

- 단위/통합 커버리지는 **플랫폼 중상~상**  
- 자동매매 **end-to-end 증거 부족** → LIVE 100% 불가  
- 기본 pytest는 Broker 실호출 없이 설계됨 (양호)
