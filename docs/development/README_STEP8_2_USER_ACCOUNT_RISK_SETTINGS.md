# STEP 8-2 — 회원별·계좌별 투자한도 및 손절·익절 설정

작성일: 2026-07-23

## 1. 기존 리스크 구조

| 구성요소 | 역할 |
|----------|------|
| `risk_engine.RealtimeRiskEngine` + `realtime_risk_policy` | 주문 가드 코드 기본 정책 |
| `DatabaseBackedRiskOrderGuard` | 주문 전 리스크 검사 |
| `strategy.risk_policy` | 사이징·손절/익절 템플릿 (user FK 없음) |
| `PersistentKillSwitchGuard` | 전역 킬스위치 |
| `PositionExitMonitorLoader` | Paper 포지션 청산 임계값 |

회원/계좌급 CRUD 테이블은 없었음.

## 2. 발견한 우회 경로와 조치

| 경로 | 조치 |
|------|------|
| `POST /api/v1/broker/orders` Adapter 직행 | **400 차단** → order-execution 강제 |
| `SafeRealtimeOrderExecutor` (Safety만) | **Risk Engine 강제 추가** |
| `OrderExecutionService` | ResolvedRiskPolicy + user/UBA 컨텍스트 전달 |
| Paper `require_order_safety` | `user_id` 전달 |
| Exit monitor `skip_risk_checks=True` | **False로 변경**, `order_source=EXIT` + `is_risk_reducing=True` |
| `POST /orders` 직접 생성 | 기존 400 유지 |
| Outbox worker | 이미 queued 주문 송신만 (생성 시 가드 의존) |
| `paper_e2e` skip | 테스트 전용으로 문서화 유지 |

## 3. 선택한 DB 설계

신규 테이블 (trading 스키마):

1. `system_risk_setting` — singleton `DEFAULT`
2. `user_risk_setting` — `user_id` UNIQUE, NULL 필드 = 시스템 상속
3. `user_broker_account_risk_setting` — UBA UNIQUE, NULL = 상위 상속

비율 단위: **fraction** (`5% = 0.050000`). 금액: `NUMERIC(20,2)`.

기존 `strategy.risk_policy`는 템플릿으로 유지. Migration backfill 시 활성 policy의 stop/take/trailing을 시스템 행에 반영.

## 4. 사용자 기본 설정

`trading.user_risk_setting` — 사용자당 1행.

## 5. 계좌별 설정

`trading.user_broker_account_risk_setting` — 키움·업비트 UBA당 1행.

## 6. Paper 적용 방식

**선택: 사용자 기본 설정만 Paper에 적용 (옵션 4).**

Paper를 `UserBrokerAccount`에 억지 연결하지 않음. Paper 주문 가드는 `user_id`로 ResolvedRiskPolicy(시스템→사용자)를 사용.

## 7. 설정 우선순위

```text
system_risk_setting
  → user_risk_setting (NULL 제외 덮어쓰기)
  → user_broker_account_risk_setting (NULL 제외 덮어쓰기)
  → RiskPolicy.to_engine_policy (+ KRX 시간 등 시장 규칙)
```

공통 진입점: `ResolvedRiskPolicyResolver` / `UserRiskSettingService.resolve`.

## 8. Risk Engine 연결

- `DatabaseBackedRiskOrderGuard`가 Resolver로 정책 로드
- 신규 규칙: 거래권한, 일일주문한도, 총투자한도, 종목한도, 중복매수
- 적용 위치: order-execution, paper-orders, RiskIntegrated/Safe realtime, exit monitor

## 9. 손절·익절·트레일링 연결 상태

| 항목 | 상태 |
|------|------|
| DB/API 저장 | **구현** |
| PositionExitMonitor 임계값 | **실제 연결** (Paper user_id → ResolvedRiskPolicy) |
| LIVE 키움/업비트 실시간 감시 | 후속 Scheduler/Recovery (STEP 8-4) — Mock 없음 |
| 중복 청산 방지 | 기존 exit monitor idempotency_key 유지 |

## 10. USER API

```text
GET  /api/v1/user/risk-settings
PUT  /api/v1/user/risk-settings
GET  /api/v1/user/accounts/{user_broker_account_id}/risk-settings
PUT  /api/v1/user/accounts/{user_broker_account_id}/risk-settings
```

본인 UBA만 (`assert_broker_account_access`).

## 11. ADMIN API

```text
GET/PUT /api/v1/admin/risk-settings/system
GET/PUT /api/v1/admin/risk-settings/users/{user_id}
GET/PUT /api/v1/admin/risk-settings/accounts/{user_broker_account_id}
POST    /api/v1/admin/risk-settings/users/{user_id}/trading-flags
GET     /api/v1/admin/risk-settings/accounts-by-user/{user_id}
```

`require_admin` (DB Role 재검증).

## 12. Frontend 연결

- `/user/risk` — 킬스위치 읽기 전용 + 사용자/계좌 설정 저장
- `/admin/risk` — 시스템 정책 + 회원 플래그(매수차단·매도전용·자동매매중지)

Mock 없음. UI % ↔ API fraction 변환.

## 13. 감사 로그

`AuditLogService` 이벤트:

- `USER_RISK_SETTINGS_UPDATE`
- `ACCOUNT_RISK_SETTINGS_UPDATE`
- `SYSTEM_RISK_SETTINGS_UPDATE`
- `ADMIN_USER_RISK_SETTINGS_UPDATE`
- `ADMIN_ACCOUNT_RISK_SETTINGS_UPDATE`
- `ADMIN_USER_BUY_BLOCK` / `SELL_ONLY_ENABLE` / `AUTO_TRADING_STOP`

detail에 before/after (시크릿 없음).

## 14. Migration ID

```text
q4e5f6a7b8c9
down_revision: p3d4e5f6a7b8
```

## 15. 변경 파일 (요약)

- Migration `q4e5f6a7b8c9_*`
- `risk_engine/user_risk_entities.py`, `resolved_policy.py`, `user_risk_service.py`
- `order_guard.py`, `rules.py`, `engine.py`, `models.py`
- API `user_risk_settings.py`, `admin_risk_settings.py`
- 주문/실시간/exit/broker bypass 차단
- FE user/admin risk pages + API helpers
- tests `test_step8_2_*`

## 16. 테스트 결과

- Migration downgrade → upgrade: 성공
- STEP8-2 unit + integration: 통과
- 관련 주문/Paper/STEP8-1 테스트: 통과
- Frontend vitest: 27 files / 73 tests 통과
- Frontend typecheck: `menu.test.ts` 기존 경로 타입 오류 2건 (본 STEP 비관련)
- Frontend production build: **성공**

## 17. 운영 DB 적용

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

## 18. 미구현·후속

- LIVE 실계좌 포지션 exit 모니터 (UBA 단위) — Scheduler 후속
- 종목 비중(%) 실시간 평가 고도화 (현재 금액 한도 + 기존 investment ratio)
- STEP 8-3 전략 소유권 / STEP 8-4 통합 Recovery
