# STEP 8-15A — Recovery Auto-Unpause Side Effect 제거

## 1. 목적

Recovery SUCCESS / ACTIVE_REVIEW=0 조건에서 Account Trading Pause가 자동 해제되던 안전 결함을 제거한다. Pause Resume는 수행하지 않는다.

## 2. Root Cause

| 항목 | 내용 |
|------|------|
| 파일 | `src/stock_platform/broker/recovery_runtime.py` |
| 함수 | Recovery cycle 완료 후 `RecoveryAccountLockService.release(..., keep_paused=...)` |
| 조건 | `keep_paused = trading_should_remain_paused or status in {FAILED, MANUAL_REVIEW, ...}` |
| Adapter 기본값 | `AdapterRecoveryResult.trading_should_remain_paused = False` (구버전) |
| 결과 | SUCCESS + conflicts=0 → `keep_paused=False` → `trading_paused=False` |
| 부가 | Runtime `resume_account_runtimes` 자동 호출 |

호출 순서: Scheduler/Manual Recovery → adapter.recover → runtime release(keep_paused=False) → DB UPDATE trading_paused=false. Admin Resume Audit 없음.

## 3. 수정 원칙

- Recovery는 Pause를 **설정**할 수 있다.
- Recovery는 Pause를 **해제할 수 없다**.
- 해제는 Admin `POST /api/v1/admin/recovery/accounts/{uba_id}/resume` 만 허용.

## 4. 변경 요약

- `recovery_lock.release`: `keep_paused=True`일 때만 Pause ON. False로 내리지 않음.
- `recovery_runtime`: 항상 `keep_paused=True`, Runtime 자동 Resume 제거.
- `AdapterRecoveryResult.trading_should_remain_paused` 기본값 `True` (fail-closed).
- Resume API: `reason`, `correlation_id` 필수 + DB Open/Submission Unknown/Cancel·Replace Pending 차단.

## 5. Resume API 계약

```http
POST /api/v1/admin/recovery/accounts/{uba_id}/resume
{"reason":"...","correlation_id":"..."}
```

사전조건: Admin 인증, ACTIVE_REVIEW=0, DB Open=0, Submission Unknown=0, Cancel/Replace Pending=0, Credential 허용, Kill Switch INACTIVE, Recovery not RUNNING.

Audit: `RECOVERY_ACCOUNT_RESUME` / 실패 시 `RECOVERY_ACCOUNT_RESUME_FAILED`.

## 6. Pause 소유권 (현재 Boolean)

단일 `trading_paused` Boolean. 장기적으로 Reason별 활성 집합을 권장하나, 본 STEP은 자동 Resume만 차단한다.

## 7. 운영 검증

`scripts/step8_15a_verify_no_auto_unpause.py` — UBA 58 Recovery cycle 후 `trading_paused=true` 유지 확인. Resume/주문 호출 없음.

## 8. STEP 8-16 인계

ACTIVE_REVIEW=0·HISTORICAL_PRESERVED=20·Pause ON 유지 확인 후, 별도 승인으로 Admin Resume만 검토.
