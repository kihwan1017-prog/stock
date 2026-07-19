# README_STEP44 — Trading

## 1. 목표

User Web **Trading(매매)** 화면을 구현·정리하고 기존 Backend API에 연결한다.

실시간 시세는 `GET /realtime-quotes/{exchange}/{symbol}` 을 사용하고,  
캐시 미스 시 `GET /prices/latest` 로 폴백한다.  
SSE 구독 UI는 TODO로 남긴다.

STEP44는 **신규 Backend API를 만들지 않는다.**

---

## 2. 구현 범위

| 기능 | 상태 | 데이터 소스 |
|------|------|-------------|
| 종목 검색 | ✅ 연결 | `GET /api/v1/market/symbols?market=` + 직접 입력 |
| 현재가 | ✅ 연결 | `GET /realtime-quotes/{ex}/{symbol}` → 폴백 `GET /prices/latest/{ex}/{symbol}` |
| 매수 | ✅ 연결 | Paper `POST /paper-orders` · Live `POST /order-execution/submit` |
| 매도 | ✅ 연결 | 동일 (side=SELL) |
| 주문 취소 | ✅ 연결 | Paper `POST /paper-orders/{id}/cancel` · Live cancel API |
| 미체결 조회 | ✅ 연결 | `GET /paper-orders` · `GET /orders` + OPEN류 필터 |
| 체결 조회 | ✅ 연결 | `GET /api/v1/executions` |
| 실시간 SSE UI | ⏳ TODO | `GET /realtime-quotes/stream/sse` 존재 · User UI 미연결 |

### 기본 컨텍스트

- Paper `account_id = 1` (회원 스코프 API 전)
- 기본 모드 `PAPER`, 거래소 `KRX`

---

## 3. 규칙

1. 기존 Backend API만 사용한다.
2. 없는 기능은 `UnimplementedNotice` + TODO로 남긴다.
3. FastAPI에 임의 엔드포인트를 추가하지 않는다.
4. UI는 STEP42/43과 동일하게 `UserPageShell` 패턴을 사용한다.

---

## 4. 주요 파일

```text
README_STEP44.md
frontend/src/app/(user)/user/trading/page.tsx
frontend/src/features/user/api/userApi.ts          # listMarketSymbols
frontend/src/features/user/trading/openOrders.ts
frontend/src/features/user/trading/openOrders.test.ts
frontend/src/lib/query/queryKeys.ts
docs/reference/ROADMAPS_README.md
```

---

## 5. TODO (후속)

- [ ] User Trading에 SSE(` /realtime-quotes/stream/sse`) 구독 UI
- [ ] 회원↔계좌 소유권 — `account_id=1` 제거
- [ ] 종목명 서버 검색 API (현재는 symbols 목록 클라이언트 필터)

---

## 6. 검증 결과 (2026-07-19)

```powershell
cd D:\Projects\stock-platform\frontend
npm run lint   # 통과 (warning 2건)
npm run test   # 10 files / 23 tests 통과
npm run build  # 통과 (/user/trading 포함)
```

---

## 7. 완료 체크리스트

- [x] README 초안
- [x] 종목 검색 · 현재가 · 매수/매도 · 취소 · 미체결 · 체결
- [x] 실시간 SSE UI TODO
- [x] lint / test / build 통과
- [x] README 최종 업데이트

---

## 8. 구현 결과

- `/user/trading`을 `UserPageShell`로 통일
- 종목 검색: `/market/symbols` Select(코드·종목명 필터) + 직접 입력
- 현재가: realtime-quotes 폴링, 404 시 prices/latest 폴백
- 매수/매도: Paper / Live 모드 전환, Kill Switch 시 주문 차단
- 미체결·취소·체결 테이블 연결
- SSE 스트림 UI만 TODO (`UnimplementedNotice`)
- **신규 Backend API 없음**
