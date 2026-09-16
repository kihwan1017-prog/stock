# STEP 8-4 — Upbit·Paper 통합 Recovery Runtime

작성일: 2026-07-23

## 1. 기존 Recovery 구조

| 구성요소 | 역할 |
|----------|------|
| `BrokerRecoveryManager` | 단일 `asyncio.Lock` + 키움 env 계좌 전용 |
| `BrokerRecoveryService` | KIWOOM 계좌/미체결/WS/런타임 단계 |
| `operation.broker_recovery_run/step` | 실행 이력 |
| Upbit `sync` / `reconcile-orders` | 별도 Admin API·FE 버튼 |
| Paper | Recovery 없음 |
| `KiwoomOrderRecoveryService` | trading_order 복구 (Manager 미연결) |

## 2. 키움 중심 구조의 문제

- 업비트·Paper가 Runtime에 없음
- 환경변수 단일 계좌 (`KIWOOM_ACCOUNT_NUMBER`)에 의존
- 계좌별 실패 격리·Lock·거래 일시차단 부재
- Status API가 DB 이력을 읽지 않음
- Startup에서 스케줄러를 Recovery가 켤 수 있음 (자동매매 선행 위험)

## 3. 공통 Recovery 인터페이스

`stock_platform.broker.recovery_adapter`

- `AccountRecoveryContext` — `user_id` + paper/UBA + `broker_code` + `market_type` + `scope_key`
- `AdapterRecoveryResult` — 공통 카운터·errors/warnings·`trading_should_remain_paused`
- `RecoveryAdapter` Protocol — `supports` / `recover`

## 4. BrokerRecoveryManager

`recovery_runtime.BrokerRecoveryManager` 확장 (중복 Manager 없음):

- Adapter 선택
- 활성 계좌 discover (Paper + UBA + 레거시 KIWOOM 시스템 슬롯)
- 계좌별 `recover_account` + 전체 `recover_all` (병렬 semaphore)
- 레거시 `recover()` — 기존 Kiwoom `BrokerRecoveryService` + 통합 계좌 복구
- Timeout / 실패 격리 / status에 DB latest + account_states

## 5. 계좌 격리 방식

식별 단위: `user_id | paper_account_id 또는 user_broker_account_id | broker_code | market_type`

결과·Lock·pause 상태가 계좌 스코프에만 기록된다.

## 6. Recovery 실행 순서

```text
계좌 확인 → Lock 획득 → trading_paused=True
→ Adapter.recover (미체결·체결·잔고·포지션)
→ 이력 저장 → 성공 시 pause 해제 / 실패·manual_review 시 pause 유지
→ Lock 해제
```

## 7. 키움 구현

`KiwoomRecoveryAdapter` — 기존 `KiwoomAccountSyncService` + `KiwoomPendingOrderService` + (가능 시) `KiwoomOrderRecoveryService` 래핑.

UBA 경로에서 환경변수 공용 계좌 오사용 경고. 레거시 `BrokerRecoveryService` 회귀 테스트 유지.

## 8. 업비트 구현

`UpbitRecoveryAdapter` — `UpbitAccountSyncService` + `UpbitOrderReconcileService`.

정책: **외부에만 존재하는 주문은 자동 내부 생성하지 않음** → `manual_review` / conflict. Rate limit 시 retry_required.

## 9. Stock Paper 구현

`StockPaperRecoveryAdapter` — orders+trades로 체결 합계·상태·평균가 정합, 포지션 재계산 대조. 원장 변경 시 before/after 기록.

## 10. Crypto Paper 구현

`CryptoPaperRecoveryAdapter` — 동일 로직, `UPBIT/CRYPTO` exchange 필터.

## 11. Lock·동시성

- 프로세스 내: 계좌 `scope_key`별 `asyncio.Lock`
- DB: `operation.broker_recovery_account_state` (`trading_paused`, `lock_expires_at`, TTL 만료 orphan 처리)
- 전역 단일 실행: Manager `_running` → 409
- 다중 인스턴스: DB lock TTL로 완화, 완전 분산 Lock은 후속 (문서화)

## 12. Timeout·Retry·Rate Limit

- 계좌별 `timeout_seconds` (기본 60)
- 전체 `overall_timeout_seconds` / startup 150s
- Upbit Adapter: 429/rate 메시지 시 `retry_required`
- 자동 step retry 루프는 없음 — 실패 계좌 pause 후 수동/스케줄 재시도

## 13. 실행 이력

기존 `operation.broker_recovery_run` 확장 + `broker_recovery_step`.

신규 컬럼: trigger_type, broker_code, user_id, paper/uba id, requested_by, 카운터들.

## 14. 서버 시작 순서

```text
settings → DB → auth bootstrap
→ broker recovery (timeout)
→ strategy runtime
→ schedulers
```

Recovery의 레거시 경로에서 `start_scheduler=False` (lifecycle이 스케줄러 담당).

## 15. Scheduler

별도 Recovery cron은 이번 STEP에서 추가하지 않음. 관리자 수동 + Startup 복구. 장 전/후·주기 정합은 후속.

## 16. 관리자 API

| Path | 설명 |
|------|------|
| `GET /api/v1/admin/recovery/status` | 메모리+DB 상태 |
| `GET /api/v1/admin/recovery/runs` | 이력 |
| `GET /api/v1/admin/recovery/runs/{id}` | 상세 (마스킹) |
| `POST /api/v1/admin/recovery/run` | 전체/필터 |
| `POST .../accounts/{id}/run` | 계좌 |
| `POST .../brokers/{code}/run` | Broker |

레거시: `POST/GET /api/v1/broker/recovery/*` 유지 (409 중복).

`require_admin` + 감사 로그.

## 17. Frontend

`/admin/recovery` — 통합 status·이력·Broker/계좌 실행 버튼. Mock 없음.

## 18. 전략 Runtime 연계

- Recovery 중 `trading_paused` → `require_order_safety`에서 신규 주문 차단 (위험축소 SELL 예외)
- 실패/manual_review 계좌 pause 유지
- 레거시 전역 strategy runtime 슬롯은 STEP 8-3과 동일하게 호환용으로 잔존 (Recovery와 직접 충돌하는 전역 자동주문 시작은 startup에서 scheduler 위임)

## 19. 백테스트 잔여 보강

- USER `/user/backtests/*` 는 전략 성과 테이블과 별개 (stateless)
- Admin `strategy-performance` create_run 시 `requested_by_user_id=admin.user_id` 기록
- USER 성과 조회 소유권 가드는 STEP 8-3 유지
- 대규모 백테스트 리팩터링 없음

## 20. DB Migration

```text
r5e6f7a8b9c0 → s6f7a8b9c0d1
```

파일: `database/alembic/versions/s6f7a8b9c0d1_unified_recovery_runtime.py`

- `broker_recovery_run` 컬럼 확장
- `broker_recovery_account_state` 신규 + partial unique indexes

## 21. 감사 로그

ADMIN Recovery 전체/Broker/계좌 실행 시 `ADMIN_RECOVERY_*` 이벤트. Secret 미포함.

## 22. 변경 파일 (주요)

- `broker/recovery_adapter.py`, `recovery_lock.py`, `recovery_account_state.py`
- `broker/recovery_adapters/*`
- `broker/recovery_runtime.py`, `recovery_entities.py`, `recovery_repository.py`
- `api/v1/admin_recovery.py`, `broker_recovery.py`, `lifecycle.py`, `trading_guards.py`
- FE `admin/recovery/page.tsx`, `adminApi.ts`
- Migration `s6f7a8b9c0d1_*`
- tests `test_step8_4_*`

## 23. 테스트 결과

- Backend: `test_step8_4_*`, `test_broker_recovery_service`, `test_application_lifecycle` 통과
- Migration down/up 성공
- Frontend vitest 73/73, production build 성공
- `tsc`: 기존 `menu.test.ts` 2건 잔존 (본 STEP 무관)

## 24. 운영 적용 방법

```powershell
cd d:\Projects\stock-platform
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

롤백: `alembic downgrade r5e6f7a8b9c0`

## 25. 남은 문제

1. 다중 인스턴스 완전 분산 Lock (DB advisory/row lock 강화) 후속
2. UBA별 실제 키움/업비트 credential vault 연동 미완 — env 공유 경고만
3. Recovery 전용 Scheduler (장 전후/주기) 미추가
4. Upbit remote-only 주문의 Admin 수동 승인 UI 후속
5. 레거시 전역 strategy runtime 슬롯 완전 제거는 미실시
