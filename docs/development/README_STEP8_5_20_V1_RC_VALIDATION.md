# STEP 8-5-20 — v1.0 RC Validation

## 목표

신규 기능 없이 v1.0 Release Candidate 통합 검증·최소 결함 수정·문서화.

## 본 STEP 코드 변경 (최소)

1. **Migration `h1b2c3d4e5f6`** — `broker_pending_order` UBA NOT NULL + FK RESTRICT + Unique(UBA, broker_order_id) + masked_account_ref  
2. Pending sync/API/Recovery — UBA 경로만 허용  
3. **LIVE Health Gate** — CRITICAL 시 `assert_live_orders_allowed` Fail Closed (`execution_service` / `trading_guards`)  
4. Snapshot Unique — **변경 없음** (ACTIVE UBA partial unique 유지)  
5. Position Limit UI — **추가 안 함** (v1.1 Medium)

## 테스트

- Backend: 832 passed / 0 failed / 0 skipped  
- 핵심 스위트 3회 반복 OK  
- Frontend: vitest 98 / tsc / eslint / build OK  

## 문서

- `docs/release/V1_0_RC_VALIDATION_REPORT.md`
- `docs/release/V1_0_RELEASE_CHECKLIST.md`
- `docs/release/V1_0_RELEASE_NOTES.md`
- `docs/operations/LIVE_TRADING_ACTIVATION_CHECKLIST.md`
- `docs/operations/INCIDENT_RESPONSE_CHECKLIST.md`
- `docs/operations/BACKUP_RESTORE_VERIFICATION.md`

## RC 판정

**GO CONDITIONAL** — Paper / LIVE-OFF / VPN.  
고객 Live·공개망은 Known Critical 해소 전 NO-GO.
