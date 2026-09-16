# AI_TEST_RULE

**최종 갱신:** 2026-07-31 · Cursor `40-testing.mdc`

---

## 계층

| 계층 | 용도 |
|------|------|
| Unit | 순수 로직 |
| Service | 도메인 서비스 |
| API | FastAPI 라우트 |
| PostgreSQL | 스키마·트랜잭션·SKIP LOCKED |
| Concurrency | 락·레이스 |
| Frontend | vitest / 컴포넌트 |
| E2E Paper | Outbox→Fill→Position (목표) |
| LIVE Smoke | **별도 승인** · `live` 마커 |

## 필수

- 기본: `pytest -m "not external and not live and not live_ai"`  
- Broker 실호출 금지  
- SQLite만으로 DB 완료 금지  
- 회귀 실패를 통과로 보고하지 않음  
- Paper E2E ≠ LIVE 승인

## 보고 형식

```text
명령:
결과: PASS/FAIL (건수)
스킵 마커:
미실행 이유:
P0 관련 커버리지:
```
