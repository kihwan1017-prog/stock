# STEP 8-1 — UserBrokerAccount 단위 주문 격리

작성일: 2026-07-23

## 1. 기존 계좌·주문 구조

| 구분 | 저장소 | 식별자 |
|------|--------|--------|
| Paper | `trading.paper_account` | `account_id` (+ `user_id`) |
| 키움·업비트 연결 | `trading.user_broker_account` | `user_broker_account_id` (+ `user_id`, `broker_code`, hash/mask) |
| 주문 | `trading.trading_order` | `account_id`(Paper 논리 ID, FK 없음) |
| Broker 스냅샷 | `broker_*_snapshot` | `broker_code` + `account_number` |
| Paper 포지션/잔고 | `paper_position` / `paper_account.available_cash` | `account_id` |

Adapter(키움·업비트)는 서버 환경변수 공용 credential로 API를 호출하며, 주문 테이블에는 사용자 연결 계좌 FK가 없었다.

## 2. 발견한 문제

1. LIVE 키움·업비트 주문이 `broker_code` / Paper `account_id` 수준으로만 구분됨
2. `assert_broker_account_access` 가 주문 경로에 미연결
3. 동일 외부 주문번호(`broker_order_id`)가 계좌 간 충돌 가능
4. Adapter가 사용자 연결 계좌 메타를 받지 않음 (env 단일 계좌와 혼동 위험)

## 3. 선택한 계좌 FK

```text
trading.trading_order.user_broker_account_id
  → trading.user_broker_account.user_broker_account_id
  (nullable, ON DELETE SET NULL)
```

- Paper 전용 주문: `user_broker_account_id = NULL`, 기존 `account_id` 유지
- LIVE 키움·업비트: `user_broker_account_id` 필수
- Paper와 UBA를 동일 테이블로 강제 통합하지 않음

## 4. DB 변경 내용

- 컬럼: `user_broker_account_id BIGINT NULL`
- FK: `fk_trading_order_user_broker_account`
- Index: `ix_trading_order_user_broker_account_id`, `ix_trading_order_uba_status`
- Unique(partial): `uq_trading_order_uba_broker_order_id`  
  `(user_broker_account_id, broker_order_id) WHERE both NOT NULL`

포지션 Unique는 기존 구조를 유지:

- Paper: `account_id + exchange_code + symbol` (`uq_paper_position_account_symbol`)
- Broker snapshot: `broker_code + account_number + exchange + symbol`  
  (시스템 공용 credential 동기화 키 — STEP 8-4 Recovery에서 UBA 연계 검토)

## 5. Migration ID

```text
p3d4e5f6a7b8
down_revision: o2c3d4e5f6a7
파일: database/alembic/versions/p3d4e5f6a7b8_trading_order_user_broker_account.py
```

`upgrade()` / `downgrade()` 모두 구현.

## 6. Backfill 방식

우선순위(요청 명세 준수):

1. 기존 trading_account_id 등 동일 FK — **없음** (해당 컬럼 부재)
2. 주문 `account_id` → `paper_account.user_id` + `broker_code` 일치 UBA
3. 해당 사용자·브로커 UBA가 **정확히 1개**일 때만 자동 연결
4. 그 외(0개·복수·user_id NULL)는 **연결하지 않음**

## 7. Backfill 결과 (로컬 운영 DB 적용 시)

| 항목 | 건수 |
|------|------|
| Backfill 대상 (KIWOOM/UPBIT, UBA NULL) | 0 |
| 자동 연결 성공 | 0 |
| 연결 불가능 | 0 |

로컬에 실계좌 주문이 없어 no-op. 운영 적용 시 migration 로그  
`STEP8-1 backfill: target=…, success=…, unlinkable=…` 를 확인한다.

연결 불가능 사유 예시:

- paper `user_id` 없음
- 동일 브로커 UBA 0개 또는 2개 이상
- broker_code가 PAPER/기타

## 8. 소유권 검사 위치

| 위치 | 검사 |
|------|------|
| `POST /order-execution/submit` | Paper 소유권 + LIVE 시 UBA 활성/소유/broker 일치 |
| `GET /orders`, `GET /orders/{id}` | `assert_order_resource_access` (UBA 우선, 없으면 Paper) |
| `POST /orders/{id}/cancel|replace` | 동일 |
| `GET /executions` | `account_id` 또는 `user_broker_account_id` + 소유권 |
| Adapter LIVE submit/replace | `require_user_broker_context_for_live` |

기준: `AuthenticatedUser.user_id == UserBrokerAccount.user_id` (ADMIN 전체 허용)

## 9. Kiwoom 반영

- `BrokerOrderRequest`에 UBA·account_type·credential_ref·owner_user_id 전달
- `KiwoomBrokerAdapter.submit_order` / `replace_order` 에서 LIVE 시 UBA 필수 검증
- API 인증은 기존 서버 공용 credential (`uses_system_shared_credential=True`)  
  → **env 계좌를 사용자 계좌로 취급하지 않음**
- Live 안전 플래그(`KIWOOM_LIVE_ORDER_ENABLED` 등) 변경 없음

## 10. Upbit 반영

- 동일 컨텍스트 필드 + `require_user_broker_context_for_live`
- Mock/Live 게이트·`UPBIT_LIVE_ORDER_ENABLED` 변경 없음

## 11. Paper 영향

- Paper 주문은 `user_broker_account_id=NULL` 허용
- `account_id` 경로·Paper 엔진 회귀 유지
- UBA 테이블과 Paper 강제 통합 없음

## 12. 변경 파일

- Migration: `p3d4e5f6a7b8_…`
- Entity/Repo/Command/Execution/Outbox/CancelReplace
- `auth/account_ownership.py`
- `broker/models.py`, `broker/order_account_context.py`
- Kiwoom/Upbit adapter
- API: `order_execution`, `orders`, `order_cancel_replace`, `executions`
- FE: `BrokerOrdersView`, `userApi`/`adminApi` list·submit 파라미터
- Tests: `test_step8_1_*`

## 13. 테스트 결과

- Migration downgrade → upgrade: 성공 (backfill target=0/success=0/unlinkable=0)
- `tests/test_step8_1_broker_account_order_isolation.py` + migration integration: 통과
- Paper/주문 회귀 (`test_paper_*`, `test_order_execution_*`, `test_broker_order_service` 등): 통과
- Frontend `vitest`: 27 files / 73 tests 통과

## 14. 운영 적용 방법

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

적용 후:

1. backfill 로그의 target/success/unlinkable 확인
2. unlinkable > 0 이면 수동 매핑 전 임의 연결 금지
3. LIVE 주문 클라이언트는 `user_broker_account_id` 필수 전달

## 15. 남은 문제

- Broker snapshot/잔고 테이블의 UBA FK는 STEP 8-4 Recovery에서 연계 권장
- 회원별 암호화 credential 저장은 현 UBA 모델에 없음 (공용 credential + UBA 식별 분리)
- STEP 8-2 리스크 설정 / 8-3 전략 소유권 / 8-4 통합 Recovery 는 별도 지시 후 진행
