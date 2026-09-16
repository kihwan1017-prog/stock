# STEP 8-8A — Post-Fill 재검증 및 전체 회귀

## 목적

`SNAPSHOT_STALE_SKIP`을 최종 성공으로 두지 않고, DB 영속 재검증 큐로 전환한다.  
무기한 SKIP 금지 · Fail Closed · 실주문 금지.

## 상태 흐름

```
PENDING → WAITING_SNAPSHOT → VERIFYING → VERIFIED
                              ↘ MISMATCH / FAILED / EXPIRED (Kill Switch)
```

## 설정 (env)

| Key | 기본 |
|-----|------|
| `POST_FILL_VERIFY_RETRY_DELAYS_SECONDS` | `2,5,10,20` |
| `POST_FILL_VERIFY_MAX_ATTEMPTS` | `5` |
| `POST_FILL_VERIFY_TTL_SECONDS` | `60` |
| `POST_FILL_VERIFY_POLL_SECONDS` | `2` |

## Alembic

`m0a1b2c3d4e5` — `trading.post_fill_verification`  
Unique: `idempotency_key` = `order:{id}:exec:{id}`

## 관련 코드

- `order/post_fill_verification_service.py`
- `order/post_fill_verification_scheduler.py`
- `order/post_fill_broker_sync.py`
- `order/post_fill_runner.py`
- `tests/test_step8_8a_post_fill_verification.py`
