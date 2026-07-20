# README_STEP74 — User Integration Audit, UAT, Security & Performance

## 목적

STEP65~STEP73 사용자 기능을 하나의 서비스 흐름으로 통합 검증하고  
Production Release 가능 여부를 판정한다.

**최종 판정: CONDITIONAL APPROVAL**

---

## 검증 환경

| 항목 | 값 |
|------|-----|
| OS | Windows 11 |
| Python | `.venv` (3.12) |
| Frontend | Next.js 16 / Vitest 4 |
| DB Migration | Alembic head `g3b4c5d6e7f8` (자동 적용 안 함) |
| 외부 Broker 주문 | 실행하지 않음 |
| Playwright E2E | 미실행 (체크리스트로 대체) |

---

## 검증 범위 (STEP65–73)

계좌 · 포트폴리오 · 관심종목 · 뉴스 · 공시 · AI 요약/추천 · 알림 · 설정 · 프로필/세션/연결

범위 외(명시적 잔여): `/user/trading`, `/user/strategies`, `/user/auto-trading` UnimplementedNotice

---

## 테스트 결과 (실행 기준)

### Backend

```text
pytest tests/test_step65_user_accounts.py
       tests/test_step66_portfolio_snapshot.py
       tests/test_step67_watchlist.py
       tests/test_step68_user_news.py
       tests/test_step69_user_disclosures.py
       tests/test_step70_user_ai_recommendation.py
       tests/test_step71_user_notifications.py
       tests/test_step72_user_preferences.py
       tests/test_step73_user_profile.py
       tests/test_step74_user_integration_audit.py
→ 89 passed
```

- FastAPI import OK, OpenAPI paths **297**
- Alembic heads: **단일 head `g3b4c5d6e7f8`**

### Frontend

| 명령 | 결과 |
|------|------|
| `npm run typecheck` | 성공 |
| `npm run test` | **24 files / 55 tests passed** |
| `npm run build` | 성공 (exit 0) |
| `npm audit --omit=dev` | moderate 2 (postcss via next) — 강제 Major 미적용 |

### E2E

Playwright 자동 E2E는 이번 STEP에서 **실행하지 않음**.  
`UAT_CHECKLIST_STEP74.md`로 수동 검증 절차를 제공한다.

---

## 이번 STEP에서 수정한 결함

| ID | 등급 | 문제 | 수정 |
|----|------|------|------|
| F74-01 | Medium | `userApi`에 미사용 admin `/ollama`, `/settings` 래퍼 잔존 | 함수 제거 |
| F74-02 | Medium | Quiet Time이 저장만 되고 Telegram 억제 미적용 | Dispatcher에 Quiet Time + CRITICAL 예외 적용 |

---

## 보안 요약

- Critical: **0**
- High (STEP65–73 범위): **0**
- `user_*` API: JWT `user_id`만 사용, Body user_id 없음
- `dangerouslySetInnerHTML` 없음
- Profile Token 표시 없음
- NEXT_PUBLIC에 Secret 없음
- 상세: `SECURITY_REVIEW_STEP74.md`

---

## 성능 요약

자동 부하 측정(P95)은 미수행.  
스모크: OpenAPI 생성·테스트 스위트 수초 내 완료.  
N+1·Pagination은 코드 리뷰 수준 — 상세 `PERFORMANCE_REPORT_STEP74.md`.

---

## 남은 위험 (Medium/Low)

- Telegram QUEUED→SENT/DLQ worker 미구현
- Watchlist 그룹 테이블 없음 (flat item)
- Trading/Strategies/Auto-trading 일부 admin realtime API 의존 → 일반 유저 403 UX
- npm postcss moderate (next 종속, force upgrade 위험)
- Playwright E2E 미자동화
- 오류 응답 code 표준화 일부만 존재

→ `RELEASE_RISK_STEP74.md`

---

## Production Score (10점 만점)

| 영역 | 점수 | 근거 |
|------|------|------|
| Authentication | 8 | bcrypt, refresh reuse 차단, rate limit |
| Authorization | 8 | JWT+RBAC, admin 경계 유지 |
| Account Ownership | 9 | STEP65 assert + tests |
| Portfolio | 7 | Snapshot/이력 존재, 브로커 NAV 후속 |
| Watchlist | 8 | flat CRUD+ownership, 그룹 없음 |
| News | 8 | state 분리, API 존재 |
| Disclosure | 8 | AI 요약 사용자 API |
| AI | 8 | 후보 검증, admin Ollama 분리 |
| Notification | 7 | Inbox+quiet time, DLQ 후속 |
| Settings | 9 | Self preferences |
| Profile | 8 | 세션/마스킹 |
| Database | 8 | 단일 head, FK |
| Performance | 6 | 부하 미측정 |
| Monitoring | 7 | health 존재, 사용자 노출 제한 |
| Documentation | 8 | STEP65–74 README |
| Operations | 7 | Windows 비Docker 문서 존재 |

**총점: 124 / 160 (약 77.5%)**

---

## Release 판정

### CONDITIONAL APPROVAL

조건:

1. Critical/High (STEP65–73 범위) 0
2. 핵심 pytest 89 passed + FE build 성공
3. Medium 잔여는 문서화·우회 가능
4. 실제 Broker 주문·Telegram DLQ·Watchlist 그룹·Playwright E2E는 STEP75+

STEP75(전체 제품/운영 강화) 진행 **가능**.

---

## 관련 문서

- `USER_UAT_REPORT.md`
- `SECURITY_REVIEW_STEP74.md`
- `PERFORMANCE_REPORT_STEP74.md`
- `RELEASE_RISK_STEP74.md`
- `UAT_CHECKLIST_STEP74.md`
