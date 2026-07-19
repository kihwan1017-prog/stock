# README_STEP43 — Portfolio

## 1. 목표

User Web **Portfolio** 화면을 Admin과 동일한 스타일로 정리하고,  
기존 Backend API로 보유·수익률·평가·비중·거래내역을 연결한다.

**자산 변화 차트**용 시계열 API가 없으면 TODO로 남긴다.  
STEP43은 **신규 Backend API를 만들지 않는다.**

---

## 2. 구현 범위

| 기능 | 상태 | 데이터 소스 |
|------|------|-------------|
| 보유 종목 | ✅ 연결 | `GET /api/v1/paper-accounts/{id}/positions` |
| 종목별 수익률 | ✅ 연결 | positions + `GET /api/v1/prices/latest/{ex}/{symbol}` |
| 평가 금액 | ✅ 연결 | 시가×수량 (가격 없으면 평단) · KPI `position_market_value` |
| 보유 비중 | ✅ 연결 | `computeHoldingWeights` + 도넛/Progress |
| 거래 내역 | ✅ 연결 | `GET /api/v1/paper-orders` 우선 · fallback `orders` / `executions` |
| 자산 변화 차트 | ⏳ TODO | 일별 equity/NAV 히스토리 API 없음 → `UnimplementedNotice` |

### 보조 KPI

- 총자산 / 예수금 / 실현손익: `GET /api/v1/dashboard/admin-summary`
- 계좌 현금: `GET /api/v1/paper-accounts/{id}`

### 기본 컨텍스트

- Paper `account_id = 1` (회원 스코프 API 전)
- `mode = PAPER`, `market = KRX`

---

## 3. 규칙

1. 기존 Backend API만 사용한다.
2. 없는 API는 `UnimplementedNotice` + TODO로 남긴다.
3. FastAPI에 임의 엔드포인트를 추가하지 않는다.
4. UI는 STEP42와 동일하게 `UserPageShell` + Card / Statistic / Table 패턴을 사용한다.

---

## 4. 주요 파일

```text
README_STEP43.md
frontend/src/app/(user)/user/portfolio/page.tsx
frontend/src/features/user/components/UserPageShell.tsx
frontend/src/features/user/portfolio/holdingMetrics.ts
frontend/src/features/user/portfolio/holdingMetrics.test.ts
docs/reference/ROADMAPS_README.md
```

---

## 5. TODO (후속)

- [ ] `GET /api/v1/paper-accounts/{id}/equity-history` — 자산 변화 차트
- [ ] 회원↔Paper 계좌 소유권 — `account_id=1` 제거
- [ ] Paper executions **목록** API (현재는 `POST /paper-executions/fills`만 존재)

---

## 6. 검증 결과 (2026-07-19)

```powershell
cd D:\Projects\stock-platform\frontend
npm run lint   # 통과 (warning 2건)
npm run test   # 9 files / 21 tests 통과
npm run build  # 통과 (/user/portfolio 포함)
```

---

## 7. 완료 체크리스트

- [x] README 초안
- [x] 보유·수익률·평가·비중·거래내역 연결
- [x] 자산 변화 차트 TODO
- [x] lint / build / test 통과
- [x] README 최종 업데이트

---

## 8. 구현 결과

- `/user/portfolio`를 `UserPageShell`로 통일 (STEP42 Dashboard와 동일 스타일)
- 보유 종목 테이블에 평가 금액·종목별 수익률·비중 컬럼 유지
- 보유 비중: SVG 도넛 + Progress
- 거래 내역: paper-orders 우선
- 자산 변화 차트: Backend equity-history API 부재로 TODO 배너만 표시
- 비중/수익률 계산 유틸 + vitest 추가
- **신규 Backend API 없음**
