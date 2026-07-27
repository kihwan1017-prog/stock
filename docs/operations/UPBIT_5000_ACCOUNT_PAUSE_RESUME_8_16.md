# STEP 8-16 — UBA 58 Account Trading Pause Resume

## 1. 목적

Recovery Review 완료(HISTORICAL_PRESERVED=20, ACTIVE_REVIEW=0) 후 Account Trading Pause만 Admin Resume API로 해제한다. Trading Scheduler / Runtime / LIVE / ARM / 주문은 변경하지 않는다.

## 2. Admin 승인 경계

- 허용: `POST /api/v1/admin/recovery/accounts/{uba_id}/resume` 1회
- 금지: 직접 DB UPDATE, LIVE ON, ARM, Trading Scheduler Resume, Runtime Resume, 실주문, Import/Ignore

## 3. Resume 사전 조건

- ACTIVE_REVIEW=0, PENDING_REVIEW=0, ON_HOLD=0
- Broker/DB Open=0, Submission Unknown=0, Cancel/Replace Pending=0
- Credential VERIFIED, Kill Switch INACTIVE
- Recovery stale=false, 최근 계정 Recovery SUCCESS
- Trading Scheduler Desired=PAUSE / Actual=PAUSED
- LIVE OFF, ARM OFF
- reason·correlation_id 필수

`last_error_code=manual_review_required` 이면서 recovery_status=SUCCESS·ACTIVE_REVIEW=0 이면 **stale metadata**로 보고 Resume 가능(Resume 시 정리).

## 4. API 예시

```http
POST /api/v1/admin/recovery/accounts/58/resume
X-Admin-API-Key: <admin>
Content-Type: application/json

{
  "reason": "RECOVERY_REVIEW_COMPLETED_HISTORY_PRESERVED_OPERATOR_APPROVED",
  "correlation_id": "step8-16-resume-uba58-<hex>"
}
```

스크립트: `scripts/step8_16_account_pause_resume.py`

## 5. reason 정책

운영 승인 사유를 명시. STEP 8-16 표준:

`RECOVERY_REVIEW_COMPLETED_HISTORY_PRESERVED_OPERATOR_APPROVED`

## 6. correlation_id 정책

STEP/요청 단위 고유 ID. Audit·응답에 동일 값 기록.

## 7. Audit

이벤트: `RECOVERY_ACCOUNT_RESUME` (실패 시 `RECOVERY_ACCOUNT_RESUME_FAILED`)

포함: actor, uba_id, reason, correlation_id, before_trading_paused, resumed/already_resumed

## 8. Trading Scheduler와 차이

Account Pause Resume ≠ Trading Scheduler Resume. Scheduler는 Desired=PAUSE / Actual=PAUSED 유지.

## 9. Runtime Resume와 차이

Strategy Runtime 자동 Resume 없음. Recovery SUCCESS여도 `resume_account_runtimes` 호출 금지.

## 10. LIVE/ARM과 차이

Pause Resume는 LIVE/ARM을 켜지 않는다.

## 11. Recovery 자동 Pause 설정

Conflict·장애 시 Pause 설정 가능(`pause_account_for_conflicts`, keep_paused=True).

## 12. Recovery 자동 Pause 해제 금지

Admin Resume 외 경로에서 `trading_paused=false` 금지. SUCCESS 시에는 **acquire 직전 Pause 상태 복원**만 수행(기존 Pause→Pause 유지, Admin Resume 후→Resume 유지).

## 13. Idempotency

이미 `trading_paused=false`면 `already_resumed=true`, `resumed=false`로 상태 변경 없음. 운영에서는 성공 후 재호출하지 않는다.

## 14. 실패 시 대응

API 오류 코드를 확인하고 사전조건 해소 후 재시도. DB 직접 UPDATE 금지.

## 15. STEP 8-12A 인계

Pause Resume 완료·LIVE OFF·Scheduler PAUSED·Open=0 확인 후, 별도 승인으로 8-12A 재검증 가능. 8-12B/실주문은 자동 시작하지 않는다.
