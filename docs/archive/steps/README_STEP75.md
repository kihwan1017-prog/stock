# README_STEP75 — Version 1.1.0 Production Release

## 목적

STEP65–74 사용자 기능을 포함한 **v1.1.0 Production Release Packaging**.  
신규 기능 개발 없음 (Release Freeze).

---

## Release 과정

1. Version 통일 → `1.1.0`
2. CHANGELOG / RELEASE_NOTE / Deploy / Rollback / Final Report
3. 검증: pytest STEP65–74, FE typecheck/test/build, alembic head
4. Branch `release/v1.1.0` · Tag `v1.1.0`
5. Migration Freeze · Prompt Freeze 선언

---

## 점검 결과

| 항목 | 결과 |
|------|------|
| pytest STEP65–74 | 89 passed |
| Vitest | 55 passed |
| next build | 성공 |
| alembic head | g3b4c5d6e7f8 |
| Security Critical/High | 0 |
| STEP74 판정 | CONDITIONAL APPROVAL |
| STEP75 결정 | **GO (CONDITIONAL)** |

---

## Known Issue

`docs/archive/steps/RELEASE_RISK_STEP74.md` 동일.

- Telegram DLQ
- Watchlist 그룹
- Trading/Strategies/Auto-trading 일부 미완
- E2E 미자동화
- postcss moderate

---

## 운영 방법

1. 배포 전 Backup
2. [docs/deployment/DEPLOY_v1.1.0.md](../../deployment/DEPLOY_v1.1.0.md)
3. Smoke: login → portfolio/watchlist/news/ai/notifications/settings/profile
4. 문제 시 [ROLLBACK_v1.1.0.md](../../deployment/ROLLBACK_v1.1.0.md)

---

## 향후 계획 (STEP76+)

- Telegram 실발송 워커 + DLQ
- Watchlist 그룹
- Playwright E2E
- Trading/Strategies 사용자 Self API 정리
- Refresh Token HttpOnly
- 2FA / 이메일 변경 / 탈퇴
- 부하 P95 측정
