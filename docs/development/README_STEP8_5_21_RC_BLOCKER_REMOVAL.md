# STEP 8-5-21 — RC Blocker Removal & Small LIVE Prep

## 목표

소액 LIVE 전 Blocker 제거·검증. 신규 기능 최소화.

## 수행

1. 운영 env 안전값 정렬 (`GLOBAL/KIWOOM/UPBIT LIVE OFF`, `KIWOOM_USE_MOCK=true`)
2. LIVE Activation `expires_at` (무기한 금지) — Migration `i2c3d4e5f6a7`
3. 환경값 불일치 Fail Closed + Health `live_flag_consistency`
4. LIVE Dry Run API (`POST /broker/live-transition/dry-run`)
5. Telegram webhook Secret 미설정 시 Fail Closed (KI-SEC-15)
6. Outbox LIVE 재전송 억제 (broker_order_id 존재 시)
7. 실 Backup + checksum; Restore는 DBA(`PGPASSWORD_ADMIN`) 필요
8. 빈 DB 스크립트 제공 (`ops/create_rc_verify_db.sql`)

## 판정

- Paper: **승인**
- 소액 LIVE: **조건부 보류** (빈 DB/Restore DBA 미완, Telegram webhook secret 운영 설정 필요, KI-TRD-02 잔여 레이스)
- 공개망: **비승인**
