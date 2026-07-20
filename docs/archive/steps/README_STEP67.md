# README_STEP67 — User Watchlist (관심종목)

## 목적

회원별 관심종목 CRUD를 구현한다.  
STEP68 뉴스 · STEP69 공시 · STEP70 AI 개인화의 공통 기반이다.

---

## DB

테이블: `trading.watchlist`

| 컬럼 | 설명 |
|------|------|
| watchlist_id | PK |
| user_id | 소유자 FK |
| market | KRX / UPBIT 등 |
| symbol | 종목코드 |
| symbol_name | 종목명 |
| display_order | 정렬 |
| memo / color | 메모·색상 |
| alarm_enabled / news_enabled / disclosure_enabled / ai_enabled | 채널 플래그 |
| created_at / updated_at | 시각 |

Unique: `(user_id, market, symbol)`  
최대 개수: **50**

Migration: `a7b8c9d0e1f2` (revises `f6a7b8c9d0e1`)

```powershell
.\.venv\Scripts\alembic.exe upgrade head
```

---

## API

모두 JWT + `trading:read`. `user_id`는 JWT에서만 결정.

| Method | Path |
|--------|------|
| GET | `/api/v1/user/watchlist` |
| GET | `/api/v1/user/watchlist/search?q=` |
| POST | `/api/v1/user/watchlist` |
| PATCH | `/api/v1/user/watchlist/{id}` |
| DELETE | `/api/v1/user/watchlist/{id}` |
| PUT | `/api/v1/user/watchlist/reorder` |

종목 검색 보강: `GET /api/v1/market/symbols?q=`

---

## Frontend

- `/user/watchlist` — 검색 추가, 삭제(+Undo), 메모/색상, 드래그 정렬
- Dashboard 관심종목 미리보기
- 메뉴: 관심종목 (`StarOutlined`)

---

## 보안

- 본인 `user_id` 행만 조회·수정·삭제
- 타 사용자 ID reorder 시 거부
- 중복 등록 409

---

## 테스트

- Backend: `pytest tests/test_step67_watchlist.py`
- Frontend: `vitest watchlistHelpers.test.ts`

---

## 남은 사용자 기능

- STEP68: 관심종목 뉴스
- STEP69: 관심종목 공시
- STEP70: 관심종목 AI
- 알림 인박스 / 사용자 개인 설정
