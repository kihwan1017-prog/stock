# STEP 05 — 예외 계층과 API 오류 매핑

> 작성일: 2026-07-22  
> 목표: 외부/브로커 예외를 정확한 API 오류 코드로 반환하고 민감정보를 마스킹한다.

---

## 1. 분석 결과

### 1.1 문제 원인

| 증상 | 원인 |
|------|------|
| `ExternalApiError` → `DOMAIN_ERROR` | `EXTERNAL_API_ERROR`가 `ERROR_CATALOG`에 없어 fallback |
| Kiwoom/Upbit/DART/Ollama → `BROKER_ERROR` | 핸들러가 세분 코드 대신 일괄 `BROKER_ERROR` |
| 테스트 5건 실패 | 구현이 테스트·설계 계약을 미충족 |

### 1.2 예외 계층 (유지·정리)

```text
DomainError
  ├─ ValidationError          (422 VALIDATION_ERROR)
  ├─ NotFoundError            (404 NOT_FOUND)
  ├─ ConflictError            (409 CONFLICT)
  ├─ PermissionDeniedError    (403 PERMISSION_DENIED)
  └─ ExternalApiError         (502 EXTERNAL_API_ERROR)

BrokerError (주문 본선 broker 패키지)     → 502 BROKER_ERROR
KiwoomError (시세/REST brokers.kiwoom)   → 502 KIWOOM_API_ERROR
UpbitError                               → 502 UPBIT_API_ERROR
DartError                                → 502 DART_API_ERROR
OllamaError                              → 502 OLLAMA_API_ERROR
NaverNewsError                           → 502 NAVER_API_ERROR
```

HTTP 상태와 내부 `code`는 분리한다. 클라이언트의 분기 기준은 `code`.

---

## 2. 수정한 파일

| 파일 | 내용 |
|------|------|
| `src/stock_platform/common/error_catalog.py` | 외부 API·브로커 세분 코드 추가, `resolve_error_code` |
| `src/stock_platform/api/exception_handlers.py` | 서비스별 코드 매핑, 마스킹, 서버 로그 |
| `tests/test_api_exceptions.py` | 카탈로그·Naver·Permission·마스킹 검증 보강 |
| `docs/audit/STEP05_EXCEPTION_MAPPING.md` | 본 문서 |

---

## 3. 주요 수정 내용

1. **카탈로그 추가:** `EXTERNAL_API_ERROR`, `KIWOOM_API_ERROR`, `UPBIT_API_ERROR`, `DART_API_ERROR`, `OLLAMA_API_ERROR`, `NAVER_API_ERROR`, `PERMISSION_DENIED`
2. **핸들러:** 예외 타입별 전용 `code` 반환 (더 이상 전부 `BROKER_ERROR`로 접지 않음)
3. **민감정보:** 응답 `message`/`detail`에 `sanitize_error_message` 적용
4. **로그:** 외부 오류는 warning 로그에 타입·마스킹된 메시지 기록
5. **DomainError:** `resolve_error_code`로 카탈로그 검증 후 코드 확정

### 응답 형식 (호환)

```json
{
  "ok": false,
  "error": { "code": "KIWOOM_API_ERROR", "message": "..." },
  "request_id": "...",
  "code": "KIWOOM_API_ERROR",
  "message": "...",
  "detail": null
}
```

레거시 top-level `code`/`message`와 envelope를 병행한다.

---

## 4. 테스트 결과

```powershell
pytest tests/test_api_exceptions.py -q
# → 12 passed

pytest -q
# → 잔여 실패 2건만 (Scheduler, Kill Switch Fake)
```

| | STEP4 후 | STEP5 후 |
|--|----------|----------|
| 예외 관련 실패 | 5 | **0** |
| 전체 잔여 실패 | 7 | **2** |

잔여:

- `test_automatic_scheduler` → STEP9
- `test_persistent_kill_switch_guard` → STEP8

---

## 5. 매핑 표

| 예외 | HTTP | code | 민감정보 |
|------|------|------|-----------|
| `NotFoundError` | 404 | `NOT_FOUND` | sanitize |
| `ExternalApiError` | 502 | `EXTERNAL_API_ERROR` | sanitize |
| `BrokerError` | 502 | `BROKER_ERROR` | sanitize + log |
| `KiwoomError` | 502 | `KIWOOM_API_ERROR` | sanitize + log |
| `UpbitError` | 502 | `UPBIT_API_ERROR` | sanitize + log |
| `DartError` | 502 | `DART_API_ERROR` | sanitize + log |
| `OllamaError` | 502 | `OLLAMA_API_ERROR` | sanitize + log |
| `NaverNewsError` | 502 | `NAVER_API_ERROR` | sanitize + log |
| `PermissionDeniedError` | 403 | `PERMISSION_DENIED` | sanitize |
| 미처리 `Exception` | 500 | `INTERNAL_ERROR` | prod는 일반 메시지 |

---

## 6. 남아 있는 문제

- Upbit/Kiwoom **RateLimit** 예외를 429 `RATE_LIMITED`로 세분할지 여부는 후속(현재 테스트·계약은 502 + 서비스 코드)
- 브로커 주문 거절(`BrokerOrderRejectedError`)을 409/422로 나눌지는 주문 STEP7에서 검토

---

## 7. 다음 단계

명령서 순서상 **STEP6 Broker 통합**.  
잔여 실패 2건은 STEP8/9에서 처리.

---

## 8. 권장 커밋 메시지

```text
fix(step05): map external and broker exceptions to specific API error codes
```
