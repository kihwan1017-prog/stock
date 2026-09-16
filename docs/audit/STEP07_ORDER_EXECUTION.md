# STEP 07 — 주문·체결·포지션 처리 검증

> 작성일: 2026-07-22  
> 목표: 주문 생성 → Outbox → Broker → 체결까지 정합성을 검증·보강하고, 필수 실패 시나리오 갭을 줄인다.

---

## 1. 분석 결과

### 1.1 이중 트랙

| 트랙 | 진입점 | 테이블 | 체결·잔고 |
|------|--------|--------|-----------|
| TradingOrder (본선) | `/api/v1/order-execution/submit` | `trading_order` + `order_outbox` | WS/`ExecutionSyncService` (포지션 자동 연동 없음) |
| PaperOrder (시뮬) | `/api/v1/paper-orders` | paper_* | `PaperExecutionService`가 잔고 반영 |

본 STEP은 **TradingOrder Outbox 본선**을 우선 다룬다.

### 1.2 검증 흐름 (현재)

```text
인증·소유권 → Kill Switch/Risk → Idempotency Key
→ TradingOrder CREATED→PENDING + Outbox (단일 commit)
→ Worker claim → Broker submit → SENT→ACCEPTED
→ 체결 이벤트 → ExecutionSyncService → PARTIAL/FILLED
→ Cancel(직접) / Replace(Kill Switch 후 직접)
```

### 1.3 시나리오 커버 (STEP7 후)

| 시나리오 | 상태 |
|----------|------|
| 동일 Idempotency Key | Outbox UNIQUE + IDEMPOTENT_REPLAY |
| DB 성공 후 Broker 실패 | Outbox retry → 소진 시 주문 FAILED |
| Broker 성공 후 DB 실패 | Idempotency COMPLETED → 재전송 없이 주문 재적용 |
| PROCESSING 고착(재시작) | `reclaim_stale_processing` (5분) |
| 부분 체결 | filled 누적 + remaining 재계산 |
| 체결 순서 역전 | event.remaining 무시, filled 기준 remaining |
| 중복 체결 | `broker_execution_id` UNIQUE |
| 취소 | Kill Switch와 무관하게 허용 (리스크 축소) |
| 정정 | Kill Switch 검사 + remaining = qty − filled |
| Paper/Upbit mock 재시도 | `client_order_id` 기반 안정 broker_order_id |
| Kiwoom/Upbit submit | InMemory idempotency `execute_once` |
| TradingOrder → Position/PnL | **미연동 (후속)** — Paper 트랙·계좌 sync 경로 |

---

## 2. 수정한 파일

| 파일 | 내용 |
|------|------|
| `order/repository.py`, `order/service.py`, `order/execution_service.py` | create `commit=False`로 주문+Outbox 단일 트랜잭션 |
| `order/outbox_repository.py` | `reclaim_stale_processing` |
| `order/outbox_worker.py` | COMPLETED 재적용, 최종 실패 시 주문 FAILED, stale reclaim |
| `order/outbox_dispatcher.py` | submit에 idempotency_key 전달 |
| `trading/execution_sync_service.py` | remaining = order_qty − filled |
| `order/cancel_replace_service.py` | 정정 Kill Switch, remaining 보정 |
| `order/models.py` | TERMINAL에 FAILED/REPLACED |
| `broker/paper/adapter.py`, `broker/upbit/adapter.py`, `broker/kiwoom/adapter.py` | submit 멱등·안정 ID |
| `tests/test_order_execution_step07.py` | 신규 |
| `docs/audit/STEP07_ORDER_EXECUTION.md` | 본 문서 |

---

## 3. 주요 수정 내용

1. **원자적 enqueue:** 주문 create가 먼저 commit되지 않아 orphan CREATED 감소  
2. **Outbox↔주문 정합:** 재시도 소진 시 PENDING/SENT → FAILED  
3. **Split-brain 완화:** Broker 성공이 idempotency에 남으면 DB만 재적용  
4. **Crash recovery:** PROCESSING + locked_at 초과 → RETRY  
5. **체결 역전 방어:** remaining을 이벤트 값으로 덮어쓰지 않음  
6. **정정 안전:** Kill Switch + 부분체결 remaining 보정  

Live 주문 플래그는 변경하지 않음.

---

## 4. 테스트 결과

```powershell
pytest tests/test_order_execution_step07.py ... -q  # 관련 묶음 통과
pytest -q
# → 3 failed, 529 passed, 3 skipped
```

잔여 실패 (본 STEP 비대상):

- `test_automatic_scheduler` → STEP9  
- `test_persistent_kill_switch_guard` → STEP8  
- `test_unauthenticated_order_mutate_rejected` → 로컬 PG password(환경)

---

## 5. 남아 있는 문제

- TradingOrder 체결 후 **포지션/잔고/PnL 자동 반영** 미구현 (계좌 sync·Paper 경로와 분리)  
- Cancel/Replace는 여전히 **동기 Broker 호출** (Outbox CANCEL/REPLACE 타입은 존재하나 API 미사용)  
- ACCEPTED 장기 미체결 타임아웃은 PENDING/SENT만 처리 (`OrderTimeoutService`)  
- 프로세스 재시작 시 InMemory broker idempotency는 소실 → PostgreSQL idempotency가 1차 방어

---

## 6. 다음 단계

명령서 순서상 **STEP8 Risk Engine과 Kill Switch**.

---

## 7. 권장 커밋 메시지

```text
fix(step07): harden order outbox recovery, fill ordering, and submit idempotency
```
