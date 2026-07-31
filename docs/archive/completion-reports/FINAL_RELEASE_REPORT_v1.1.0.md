# FINAL_RELEASE_REPORT — v1.1.0

**일자:** 2026-07-21  
**릴리즈 결정:** **GO (CONDITIONAL)**  
**근거:** STEP74 CONDITIONAL APPROVAL + STEP75 Freeze/Packaging 완료

---

## 1. Architecture

- FastAPI + Next.js + PostgreSQL (Windows, 비Docker)
- Admin Ops와 User Self (`/api/v1/user/*`) 분리
- Broker: Kiwoom/Upbit · AI: Ollama · Notify: Publisher + Inbox

## 2. Security

| 항목 | 상태 |
|------|------|
| JWT / Refresh reuse | OK |
| Ownership / IDOR (user_*) | OK |
| Rate Limit | OK |
| Secret 마스킹 | OK |
| XSS (dangerouslySetInnerHTML) | 없음 |
| Prompt Injection 방어 | STEP69/70 |
| STEP62/74 리뷰 | 반영 |

Critical/High (사용자 범위): **0**

## 3. Performance

- STEP58 최적화 유지
- STEP74 P95 부하 미측정 (스모크만)
- Build/Test 로컬 통과

## 4. Coverage / Tests (실행 결과)

| Suite | 결과 |
|-------|------|
| pytest STEP65–74 | **89 passed** |
| Vitest | **55 passed** |
| `npm run typecheck` | 성공 |
| `npm run build` | 성공 |
| Alembic heads | `g3b4c5d6e7f8` 단일 |
| OpenAPI paths | 297 |
| Playwright E2E | 미실행 |
| Coverage % 전체 | 미집계 (영역별 단위 테스트 우선) |

## 5. Build

- Backend: import + OpenAPI OK
- Frontend: production build OK
- Version: Backend default `1.1.0` · FE `1.1.0` · `.env.example` `APP_VERSION=1.1.0`

## 6. Deployment

- [DEPLOY_v1.1.0.md](docs/deployment/DEPLOY_v1.1.0.md)
- [ROLLBACK_v1.1.0.md](docs/deployment/ROLLBACK_v1.1.0.md)
- Migration 수동 · Backup 필수

## 7. Risk

[RELEASE_RISK_STEP74.md](docs/archive/steps/RELEASE_RISK_STEP74.md)

주요: Telegram DLQ · Watchlist 그룹 · Trading UI · npm postcss moderate · E2E 미자동화

## 8. Release Score (100)

| 영역 | 점수 |
|------|------|
| Architecture | 14/15 |
| Security | 14/15 |
| Performance | 10/15 |
| Documentation | 13/15 |
| Operations | 12/15 |
| Maintainability | 12/15 |
| AI | 11/15 |
| Trading (User Paper/Self) | 11/15 |
| **합계** | **97/120 → 정규화 약 81/100** |

## 9. Decision

### GO (CONDITIONAL)

허용 범위:

- 사설망 · 단일 운영자 · Live OFF · Paper + User Self 기능

비허용:

- 공개망 실고객 SaaS Live
- Telegram 실발송을 SLA로 약속하는 운영

## 10. Tag / Branch

- Branch: `release/v1.1.0`
- Tag: `v1.1.0`
