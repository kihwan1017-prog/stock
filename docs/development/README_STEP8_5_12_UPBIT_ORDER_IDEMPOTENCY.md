# STEP 8-5-12 — Upbit 주문 식별자·중복 방지·AMBIGUOUS 해소

## 1. 기존 Upbit 주문 식별 구조

| 필드 | 위치 | 용도 |
|------|------|------|
| `client_order_id` | `trading.trading_order` | 로컬 Unique (`ORD-…`) |
| `broker_order_id` | 동일 | Upbit UUID |
| `identifier` (전송) | `UpbitOrderMapper` | create 시 `client_order_id` 또는 `upbit_client_identifier` |
| Outbox `idempotency_key` | `trading.order_outbox` | 워커 중복 방지 |
| `operation.idempotency_key` | PG | 요청 해시 멱등 |

## 2. 업비트 Identifier 지원 조사

공식 API:

- **생성** `POST /v1/orders` — body `identifier` (계정 Unique, 재사용 불가, 최대 36자)
- **조회** `GET /v1/order` — `uuid` **또는** `identifier`
- **취소** `DELETE /v1/order` — `uuid` 또는 `identifier`

본 STEP에서 `UpbitOrderRestClient.get_order` / `cancel_order`에 identifier 인자 추가.

## 3. Identifier 생성 규칙

`UpbitClientOrderIdentifierFactory`

```text
spu-{sha256(broker|uba|order_id|generation)[:32]}  # 총 36자
```

- Python `hash()` 미사용 (SHA-256)
- Credential·계좌번호·이메일 미포함

## 4. 논리 주문 Generation

`submission_generation` (기본 1). 정정/재제출 승인 시에만 증가. Recovery 조회는 증가 안 함.

## 5. DB 영속화

`trading_order` 신규 컬럼 + `trading.order_submission_attempt`.
UBA+identifier partial unique.

## 6. 주문 Transaction 경계

```text
claim SUBMITTING → ensure_identifier → flush → create_order
```

외부 전송 전 Identifier DB 확정.

## 7. 동시 Submit 차단

`UPDATE … WHERE status IN (CREATED,PENDING) SET SUBMITTING` 원자적 전이.

## 8. Submission Attempt

`order_submission_attempt` — 민감 Payload 미저장.

## 9. 정상 응답 처리

UUID 연결, identifier 일치, market/side 검증, UUID 타주문 충돌 시 Identity Conflict.

## 10–12. Timeout / 429 / 5xx

Adapter가 `BrokerOrderStatus.AMBIGUOUS` 반환 → Outbox가 재전송 없이 Ambiguous 마킹 + Lookup 예약.

## 13–16. Lookup / NOT_FOUND / Match / Conflict

`UpbitAmbiguousOrderResolver` — FOUND_MATCHED / NOT_FOUND_TRANSIENT|FINAL / CONFLICT.
최종 미발견 후 자동 재제출 금지 → Manual Review.

## 17. 주문 상태 머신

추가: SUBMITTING, AMBIGUOUS_SUBMISSION, REMOTE_LOOKUP_PENDING, IDENTITY_CONFLICT, MANUAL_REVIEW_REQUIRED.

## 18–19. Recovery / Scheduler

기존 Recovery Retry와 Admin Lookup 연계. 긴 Retry-After는 DEFER(next_remote_lookup_at).

## 20–22. Signal / Fingerprint

`source_signal_id`, `source_signal_fingerprint`, `order_fingerprint` 컬럼.

## 23–24. USER / API Idempotency

기존 Outbox + PG idempotency 재사용. `UPBIT_ORDER_IDEMPOTENCY_*` 설정.
강제 UUID 수동 연결 API 없음.

## 25. 재제출

기본 `UPBIT_ORDER_AUTO_RESUBMIT_ENABLED=false`.
관리자 approve → 새 Generation/Identifier 준비만 (자동 전송 없음). 오래된 MARKET 차단.

## 26–28. API / Frontend / Health

- Admin `/api/v1/admin/upbit/ambiguous-orders*`
- `/admin/upbit` Ambiguous 패널
- USER 상태 라벨 (확인 중 / 재확인 예정 / 관리자 확인 필요)
- Health `upbit_ambiguous_orders`

## 29. Audit

Identifier 생성, Ambiguous, Lookup, Match, Conflict, Resubmit 승인/거절.

## 30. Migration

`a4b5c6d7e8f9` ← `z3d4e5f6a7b8`

## 31. Backfill

신규 Upbit 주문만 Identifier 적용. 과거 주문에 가짜 Identifier 생성 금지. Paper/Kiwoom 미적용.

## 32. 설정

`.env.example` — UPBIT_CLIENT_ORDER_IDENTIFIER_* / AMBIGUOUS_* / AUTO_RESUBMIT=false

## 33. 변경 파일

- `broker/upbit/client_order_identifier.py`, `ambiguous_*.py`, `order_client.py`, `adapter.py`, `order_mapper.py`
- `order/models.py`, `state_machine.py`, `entities.py`, `outbox_*.py`
- `api/v1/admin_upbit_ambiguous_orders.py`, settings, health
- FE admin upbit panel, BrokerOrdersView
- migration `a4b5c6d7e8f9`, tests

## 34. 테스트 결과

```text
Backend pytest: 714 passed / 0 failed / 3 skipped
Frontend Vitest: 85/85
TypeScript: 통과
Lint: 0 errors / 0 warnings
Production Build: 성공
Alembic down/up (a4b5c6d7e8f9 ↔ z3d4e5f6a7b8): 성공
Alembic Head: a4b5c6d7e8f9 (single head)
```

(신규: `tests/test_step8_5_12_upbit_order_idempotency.py` 9 passed)

## 35. 운영 적용

```powershell
alembic upgrade head
```

## 36. 남은 문제

- Ambiguous 전용 APScheduler Job는 Admin Lookup + Outbox 경로 우선; 별도 cron Job는 후속 가능
- USER request_token Idempotency-Key HTTP 헤더 전면 도입은 기존 Outbox로 대체
- Kiwoom Identifier는 범위 외
