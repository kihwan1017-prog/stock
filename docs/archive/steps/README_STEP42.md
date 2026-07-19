# README_STEP42 — User Dashboard

## 1. 목표

User Web **Dashboard**를 Admin과 동일한 Ant Design 스타일로 구현하고,  
기존 Backend API만 연결한다. API가 없는 기능은 TODO로 남긴다.

STEP42는 **신규 Backend API를 만들지 않는다.**

---

## 2. 구현 범위

| 섹션 | 상태 | 데이터 소스 |
|------|------|-------------|
| 총 자산 | ✅ 연결 | `GET /api/v1/dashboard/admin-summary` → `kpis.total_equity` |
| 평가 손익 | ✅ 연결 | `kpis.unrealized_pnl` |
| 실현 손익 | ✅ 연결 | `kpis.realized_pnl` |
| 일일 수익률 | ✅ 연결 | `kpis.today_return_rate` (+ `today_pnl`) |
| 보유 종목 요약 | ✅ 연결 | `GET /api/v1/paper-accounts/{id}/positions` |
| 최근 주문 | ✅ 연결 | `GET /api/v1/paper-orders` (우선) · fallback `GET /api/v1/orders` |
| 최근 체결 | ✅ 연결 | `GET /api/v1/executions` |
| 실행 중 전략 | ✅ 연결 | `GET /api/v1/strategy-deployments/active` (+ summary `active_strategies`) |
| AI 추천 종목 | ✅ 연결 | `GET /api/v1/candidates/top/{exchange}` |
| 주요 뉴스 | ✅ 연결 | `GET /api/v1/news/{exchange}/{symbol}` |
| 주요 공시 | ✅ 연결 | `GET /api/v1/dart/disclosures` |
| 관심종목 | ⏳ TODO | Backend watchlist API 없음 → `UnimplementedNotice` |

### 기본 컨텍스트 (회원 스코프 API 전)

- Paper `account_id = 1`
- `market_code / exchange = KRX`
- `mode = PAPER`
- 뉴스·공시 심볼: AI 추천 1위 → 보유 1위 → `005930` (`pickFocusSymbol`)

---

## 3. 규칙

1. 기존 Backend API만 사용한다.
2. API가 없으면 `UnimplementedNotice` + TODO 주석으로 남긴다.
3. FastAPI에 임의 엔드포인트를 추가하지 않는다.
4. UI는 Admin Dashboard와 동일한 Card / Statistic / Table / Tag / Breadcrumb 패턴을 사용한다.

---

## 4. 주요 파일

```text
README_STEP42.md
frontend/src/features/user/components/UserPageShell.tsx
frontend/src/app/(user)/user/dashboard/page.tsx
frontend/src/features/user/dashboard/pickFocusSymbol.ts
frontend/src/features/user/dashboard/pickFocusSymbol.test.ts
frontend/src/features/user/api/userApi.ts
docs/reference/ROADMAPS_README.md
```

---

## 5. TODO (후속 STEP)

- [ ] `GET/POST/DELETE /api/v1/user/watchlist` — 관심종목
- [ ] `GET /api/v1/user/dashboard` — 회원 전용 집계 (현재 admin-summary 재사용)
- [ ] 회원↔Paper 계좌 소유권 — `account_id=1` 하드코딩 제거

---

## 6. 검증 결과 (2026-07-19)

```powershell
cd D:\Projects\stock-platform\frontend
npm run lint        # 통과 (tokenStorage unused warning 2건만)
npm run typecheck   # 통과
npm run test        # 8 files / 18 tests 통과 (STEP42 pickFocusSymbol 포함)
npm run build       # 통과 (/user/dashboard 포함)
```

---

## 7. 완료 체크리스트

- [x] README 초안
- [x] UserPageShell (AdminPageShell 동일 Breadcrumb 스타일)
- [x] User Dashboard UI (Admin 스타일 KPI/Card/Table)
- [x] KPI 4종 연결
- [x] 보유·주문·체결·전략·AI·뉴스·공시 연결
- [x] 관심종목 TODO (`UnimplementedNotice`)
- [x] lint / typecheck / build / test 통과
- [x] README 최종 업데이트

---

## 8. 구현 결과

- `/user/dashboard`를 `UserPageShell` + Admin과 동일한 Statistic KPI 그리드로 정리
- Kill Switch / Mode / Account / valuation_mode / focus symbol Tag 표시
- Paper 주문(`paper-orders`) 우선, 없으면 trading `orders` fallback
- 뉴스·공시 심볼은 `pickFocusSymbol`로 동적 선택
- 관심종목은 API 부재로 TODO 배너만 표시 (Backend 미추가)
- 신규 Backend API **없음**
