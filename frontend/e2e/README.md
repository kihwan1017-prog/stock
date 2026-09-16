# Playwright E2E 스캐폴드 (P2)

진짜 FE/BE E2E는 기본 CI 게이트에 연결하지 않습니다. 로컬/야간에서 실행하세요.

## 설치

```bash
cd frontend
npm i -D @playwright/test
npx playwright install chromium
```

## 실행

```bash
# FE 기동 후
npm run test:e2e
```

환경변수: `E2E_BASE_URL` (기본 `http://127.0.0.1:3000`)

## 시나리오 우선순위

1. 로그인 페이지 스모크 (`e2e/smoke.spec.ts`)
2. 로그인 → 계좌 선택 → Paper 주문
3. Kill Switch 확인
