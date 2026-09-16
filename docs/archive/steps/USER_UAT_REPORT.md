# USER_UAT_REPORT — STEP74

## 요약

| 시나리오 | 자동화 | 수동 | 결과 |
|----------|--------|------|------|
| A 신규 일반 사용자 | API/서비스 단위 | 체크리스트 | CONDITIONAL PASS* |
| B 기존 거래 사용자 | API/서비스 단위 | 체크리스트 | CONDITIONAL PASS* |
| C 권한 공격 | 401/OpenAPI/소유권 테스트 | 체크리스트 | PASS (코드 검증) |

\* Playwright E2E 미실행 — 수동 UAT 완료 후 Full PASS로 승격.

---

## 기능별 결과

| 기능 | STEP | API | FE | 테스트 | 비고 |
|------|------|-----|----|--------|------|
| 계좌 | 65 | OK | `/user/account` | test_step65 | Ownership |
| 포트폴리오 | 66 | OK | `/user/portfolio` | test_step66 | Snapshot |
| 관심종목 | 67 | OK | `/user/watchlist` | test_step67 | 그룹 없음 |
| 뉴스 | 68 | OK | `/user/news` | test_step68 | |
| 공시+AI요약 | 69 | OK | `/user/disclosures` | test_step69 | |
| AI 추천 | 70 | OK | `/user/ai` | test_step70 | admin Ollama 분리 |
| 알림 | 71 | OK | `/user/notifications` | test_step71 | Quiet Time 적용 |
| 설정 | 72 | OK | `/user/settings` | test_step72 | |
| 프로필/세션 | 73 | OK | `/user/profile` | test_step73 | |
| 통합/경계 | 74 | OK | — | test_step74 | |

---

## 실패·제한 시나리오

1. Watchlist “그룹 생성” — **기능 없음** (flat item만). 시나리오 A-6은 N/A.
2. Telegram 실제 발송/DLQ — QUEUED까지. 시나리오 알림 Telegram E2E 제한.
3. `/user/trading|strategies|auto-trading` — UnimplementedNotice / admin API 혼재.
4. 자동 E2E-01~08 — 미실행.

---

## 수동 검증

`UAT_CHECKLIST_STEP74.md` 항목을 Test 환경에서 수행한다.  
운영 사용자·운영 데이터 사용 금지.
