# STEP 06 — Broker / Brokers 패키지 통합

> 작성일: 2026-07-22  
> 목표: 시세 REST(`brokers`)를 canonical `broker` 트리로 이전하고, 구경로는 동일 클래스 re-export로 유지한다.

---

## 1. 분석 결과

### 1.1 이전 구조

| 패키지 | 역할 | 문제 |
|--------|------|------|
| `stock_platform.broker` | 주문·계좌·WS·Paper·Live 게이트 | 주문 본선 |
| `stock_platform.brokers` | Kiwoom/Upbit **시세 REST** | 이름 혼동, 예외·핸들러 import 이중화 |

주문 어댑터와 시세 클라이언트를 **한 클래스로 합치지 않는다**.  
시세 구현만 `broker.*.market`으로 옮기고, `brokers`는 삭제하지 않는다.

### 1.2 Canonical 배치

```text
broker/
  kiwoom/          # 주문·WS·계좌
  kiwoom/market/   # 시세 REST (구 brokers.kiwoom)
  upbit/           # 주문·사설 API
  upbit/market/    # 시세 quotation (구 brokers.upbit)
  upbit/exceptions.py
  common/async_rate_limiter.py
  exceptions.py    # + UnsupportedBrokerFeatureError

brokers/           # 호환 래퍼만 (동일 클래스 identity)
```

---

## 2. 수정한 파일 (요지)

| 영역 | 내용 |
|------|------|
| `broker/kiwoom/market/*` | exceptions, constants, token, auth, client (신규 canonical) |
| `broker/upbit/market/client.py`, `broker/upbit/exceptions.py` | Upbit 시세·예외 canonical |
| `broker/common/async_rate_limiter.py` | 공통 rate limiter |
| `brokers/**` | re-export 래퍼로 교체 |
| `broker/upbit/{adapter,order_client,private_client}.py` | canonical exceptions / limiter |
| `broker/kiwoom/adapter.py` | `get_order` → `UnsupportedBrokerFeatureError` |
| `broker/exceptions.py` | `UnsupportedBrokerFeatureError` |
| `api/exception_handlers.py` | Kiwoom/Upbit 예외 canonical import |
| collectors / api v1 / scheduler / scripts | 시세 import → `broker.*.market` |
| `tests/test_broker_consolidation_step06.py` | identity·미지원 기능 검증 |

---

## 3. 주요 수정 내용

1. **시세 구현 이전:** `brokers` 본문을 `broker.kiwoom.market` / `broker.upbit.market`으로 이동
2. **호환 유지:** `from stock_platform.brokers...` 는 동일 클래스 객체 (`is` 동일) — `isinstance`·핸들러 유지
3. **생산 경로 이전:** sync/kiwoom/upbit API, daily collectors, instrument sync 등 canonical import
4. **미지원 기능:** Kiwoom `get_order` 의 `NotImplementedError` → `UnsupportedBrokerFeatureError` (`BrokerError` 하위)
5. **`brokers/` 폴더 유지:** 삭제하지 않음 (테스트·외부 스크립트 호환)

운영 Live 플래그(`KIWOOM_LIVE_ORDER_ENABLED` / `UPBIT_LIVE_ORDER_ENABLED`)는 변경하지 않음.

---

## 4. 테스트 결과

```powershell
pytest tests/test_broker_consolidation_step06.py tests/test_api_exceptions.py `
  tests/test_broker_factory.py tests/test_upbit_order_adapter.py `
  tests/test_upbit_client.py tests/test_kiwoom_client.py `
  tests/test_kiwoom_auth.py tests/test_kiwoom_daily_collector.py `
  tests/test_upbit_account_auth.py tests/test_upbit_daily_collector.py -q
# → 전부 통과

pytest -q
# → 3 failed, 522 passed, 3 skipped
```

| 실패 | 원인 | 후속 |
|------|------|------|
| `test_automatic_scheduler` | job 집합 하드코딩 드리프트 | STEP9 |
| `test_persistent_kill_switch_guard` | Fake에 `active_exchange_scope` 부재 | STEP8 |
| `test_unauthenticated_order_mutate_rejected` | 로컬 PG `stock_app` password 인증 실패 (환경) | STEP17/환경 — STEP6 회귀 아님 |

브로커 통합·예외 identity 관련 실패 **0**.

---

## 5. 남아 있는 문제

- 테스트·스크립트 일부는 의도적으로 `brokers.*` 호환 경로 사용 (삭제 금지)
- 주문 어댑터와 시세 클라이언트의 추가 정리(문서/공개 API 표)는 STEP7에서 주문 본선과 함께 검토
- PowerShell `Set-Content` 기본 인코딩으로 한글 파일이 깨질 수 있음 → UTF-8 Python 쓰기 권장

---

## 6. 다음 단계

명령서 순서상 **STEP7 주문·체결·Outbox**.  
잔여 실패 2건(+환경 1건)은 STEP8/9/17에서 처리.

---

## 7. 권장 커밋 메시지

```text
refactor(step06): consolidate market REST under broker with brokers compat wrappers
```
