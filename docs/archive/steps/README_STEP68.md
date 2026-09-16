# README_STEP68 — User Watchlist News

## 목적

STEP67 관심종목을 기반으로 로그인 사용자의 관심종목 뉴스만 조회·읽음·북마크할 수 있게 한다.  
공시·AI 뉴스 요약은 본 STEP 범위 밖이다.

---

## 기존 문제

- 사용자 뉴스 화면이 보유 포지션/관리자 뉴스 컨텍스트에 의존
- `UnimplementedNotice`로 관심종목 뉴스 미구현
- 사용자별 읽음·북마크 상태 없음
- 동일 `content_hash` 재수집 시 종목 덮어쓰기 위험

---

## 뉴스 데이터 구조

| 테이블 | 역할 |
|--------|------|
| `news.news_article` | 공용 원문(제목·요약·링크·hash) — **user_id 없음** |
| `news.news_article_symbol` | 기사–종목 다대다 링크 |
| `news.user_news_state` | 사용자별 읽음·북마크·숨김 |

중복 키: `news_article.content_hash` Unique.  
재수집 시 메타만 갱신하고 종목은 링크 테이블에 upsert.

---

## 뉴스와 종목 연결

1. 수집 시 `PROVIDER` match_type으로 `(market, symbol)` 링크 저장
2. 조회는 `news_article_symbol` ∪ legacy `news_article.exchange_code/symbol`
3. 사용자 화면에는 **본인 watchlist + news_enabled** 종목만 노출

---

## 사용자 뉴스 API

JWT `user_id`만 사용. 권한: `trading:read` (관리자 권한 불필요).

| Method | Path |
|--------|------|
| GET | `/api/v1/user/news` |
| GET | `/api/v1/user/news/unread-count` |
| GET | `/api/v1/user/news/{news_id}` |
| POST/DELETE | `/api/v1/user/news/{news_id}/read` |
| POST/DELETE | `/api/v1/user/news/{news_id}/bookmark` |
| POST | `/api/v1/user/news/read-all` |

Query: `market_code`, `symbol`, `watchlist_id`, `keyword`, `source_code`, `from_date`, `to_date`, `read_status`, `bookmarked`, `page`, `page_size`

정책:

- 기본 = 관심종목(news_enabled) 전체 뉴스
- `symbol`이 watchlist에 없으면 거부
- GET 상세는 상태 변경 없음 (FE가 read API 호출)
- `read-all` 범위 = 현재 관심종목(+선택 필터) 미읽음

---

## 읽음 및 북마크

- `user_news_state` Unique `(user_id, article_id)`
- Idempotent POST/DELETE
- 북마크 삭제해도 원문 유지
- 타 사용자 상태 비노출

---

## 중복 제거

- Unique: `content_hash`
- 동일 기사 재수집 시 종목 링크만 추가 (원문 1건)

---

## 뉴스 수집 Scheduler

Job: `watchlist_news_sync` (group NEWS)

- 활성 `news_enabled` 관심종목의 **distinct (market, symbol)** 만 수집
- 공용 저장 — 사용자별 중복 저장 없음
- 종목 단위 실패 격리

운영 cron은 과도하게 변경하지 않음. 수동/스케줄러 UI에서 실행 가능.

---

## Frontend 화면

`/user/news`

- UnimplementedNotice 제거
- 관심종목/시장/읽음/기간/키워드 필터
- 카드 목록 + Drawer 상세
- 원문 `rel="noopener noreferrer"`
- HTML 직접 렌더링 없음
- 관심종목 없으면 안내 + watchlist 이동
- AI 요약은 “준비 중” 안내만

---

## 권한 및 보안

- 일반 사용자: `trading:read`로 본인 뉴스만
- Admin `settings:*` / `system:*` 로 우회하지 않음
- Naver Secret은 Backend만 사용
- 클라이언트 `user_id` 미수신

---

## Database 변경

Migration: `b8c9d0e1f2a3` (revises `a7b8c9d0e1f2`)

- index `ix_news_article_symbol_published`
- table `news.news_article_symbol` + backfill
- table `news.user_news_state` + indexes

```powershell
.\.venv\Scripts\alembic.exe upgrade head
```

운영 DB 자동 적용 금지.

---

## 성능 및 Index

- `news_article (exchange_code, symbol, published_at)`
- `news_article_symbol (market_code, symbol, article_id)`
- `user_news_state (user_id, article_id)` Unique
- `user_news_state (user_id, is_read)` / `(user_id, is_bookmarked)`
- 목록 시 상태·링크 batch 조회 (N+1 방지)

---

## 테스트 결과

- Backend: `pytest tests/test_step68_user_news.py`
- OpenAPI 경로·401·서비스 필터·읽음/북마크·Job 등록

---

## 운영 설정

- `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` (기존)
- Secret 누락 시 수집 Job만 실패 — 조회 API는 DB 데이터로 동작

---

## 수동 검증 방법

1. 로그인 후 관심종목 등록 (`news_enabled` on)
2. (선택) 스케줄러에서 `watchlist_news_sync` 실행 또는 관리자 뉴스 sync
3. `/user/news`에서 목록·필터·읽음·북마크·원문 링크 확인
4. 다른 계정으로 상태 비노출 확인
5. 관심종목 비우면 Empty 안내 확인

---

## 남은 사용자 기능

- 관심종목 공시
- 공시 AI 요약
- 사용자용 AI 추천
- 알림 인박스
- 사용자 개인 설정
- 내정보 최종 보완
