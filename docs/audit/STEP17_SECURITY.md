# STEP 17 — 전체 API 보안 감사

## Critical 수정
- **미인증** POST /api/v1/upbit/instruments/sync 등이 200 → router 
equire_admin
- 보안 스모크 테스트 DB 독립(dependency override)

## 확인
주문·계좌 ownership(STEP4/7/12), Kill Switch admin+audit(STEP8), Live gates, refresh cookie, rate limit, sanitize.

## 권장 커밋
ix(step17): require admin for upbit sync and harden security smoke tests
