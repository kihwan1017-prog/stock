# README_STEP48 — News & Disclosure

## 1. 목표

User Web **뉴스**·**공시** 화면을 구현·정리하고 기존 Backend API에 연결한다.

- News: 최신 뉴스 · 관심종목 뉴스 · AI 요약  
- Disclosure: 최신 공시 · 관심종목 공시 · AI 요약  

STEP48은 **신규 Backend API를 만들지 않는다.**

---

## 2. 구현 범위

| 기능 | 상태 | 데이터 소스 |
|------|------|-------------|
| 최신 뉴스 | 연결 | `GET /news/{exchange}/{symbol}` — 포커스 종목(AI 1위→보유→005930) |
| 관심종목 뉴스 | 부분 | watchlist API 없음 → TODO · **보유 종목**으로 대체 조회 |
| 뉴스 AI 요약 | 연결 | `POST /news/summarize` (+ `POST /news/sync`) |
| 최신 공시 | 연결 | `GET /dart/disclosures` — 동일 포커스 종목 · 기간 필터 |
| 관심종목 공시 | 부분 | watchlist API 없음 → TODO · **보유 종목**으로 대체 조회 |
| 공시 AI 요약 | TODO | `POST /dart/summarize` 없음 → `UnimplementedNotice` |

### 제약 (Backend 기준)

- 뉴스는 **종목 단위** API만 존재 (`/{exchange}/{symbol}`) — 전역 최신 피드 없음  
- 공시도 `stock_code` 필수 — 전역 목록 없음  
- 관심종목 CRUD API 없음 (`GET/POST/DELETE /user/watchlist`)

---

## 3. 규칙

1. 기존 Backend API만 사용한다.
2. 없는 기능은 `UnimplementedNotice` + TODO로 남긴다.
3. FastAPI에 임의 엔드포인트를 추가하지 않는다.
4. UI는 `UserPageShell` 패턴 (STEP42~47과 동일).

---

## 4. 작업 순서

```
1. README_STEP48.md 작성
2. /user/news · /user/disclosures 화면 재구성
3. 보유 종목 기반 관심종목 대체 + AI 요약(뉴스)
4. README 완료 체크리스트 업데이트
5. lint · test · build
```

---

## 5. TODO (후속)

- [ ] `GET/POST/DELETE /api/v1/user/watchlist` — 관심종목
- [ ] `GET /api/v1/news/latest` — 전역(또는 관심) 최신 피드
- [ ] `GET /api/v1/dart/disclosures` stock_code 옵션화 / latest 피드
- [ ] `POST /api/v1/dart/summarize` — 공시 AI 요약

---

## 6. 완료 체크리스트

- [x] README 초안
- [x] News: 최신 · 관심(대체) · AI 요약
- [x] Disclosure: 최신 · 관심(대체) · AI 요약 TODO
- [x] lint / test / build
- [x] README 최종 업데이트

---

## 7. 구현 결과

| 항목 | 경로 / 내용 |
|------|-------------|
| News | `frontend/src/app/(user)/user/news/page.tsx` |
| Disclosure | `frontend/src/app/(user)/user/disclosures/page.tsx` |
| 관심 심볼 헬퍼 | `frontend/src/features/user/news/pickInterestSymbols.ts` (+ test) |
| 검증 | lint 0 errors · test 32 passed · build OK |

관심종목·공시 AI 요약·전역 피드는 TODO. 다음: STEP49+
