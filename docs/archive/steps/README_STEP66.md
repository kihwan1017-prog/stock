# README_STEP66 — Portfolio Asset History

## 목적

회원·계좌별 **일별 자산 스냅샷**을 저장하고, 총자산·손익·MDD·수익률을 차트/표로 조회한다.

---

## DB

테이블: `trading.portfolio_snapshot`

| 컬럼 | 설명 |
|------|------|
| snapshot_id | PK |
| user_id | 소유자 (JWT 스코프) |
| account_id | Paper 계좌 FK |
| snapshot_date | 일자 |
| snapshot_time | 생성 시각 |
| cash / market_value / total_asset | 자산 |
| invested_amount | 원가 합 |
| realized_profit / unrealized_profit | 손익 |
| daily_profit / daily_profit_rate | 전일 대비 |
| total_return_rate | 초기현금 대비 |
| position_count | 보유 종목 수 |
| mode_code | PAPER \| LIVE |
| valuation_mode | mark_to_market 등 |

Unique: `(account_id, snapshot_date, mode_code)` — 일별 중복 방지.

Migration: `f6a7b8c9d0e1` (revises `e5f6a7b8c9d0`)

```powershell
.\.venv\Scripts\alembic.exe upgrade head
```

---

## API

JWT + `trading:read` / `trading:write`. 본인 Paper 계좌만.

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/v1/user/portfolio/history` | 일별 시계열 |
| GET | `/api/v1/user/portfolio/summary` | 현재·MDD·기간수익률 |
| POST | `/api/v1/user/portfolio/snapshot` | 수동 스냅샷 upsert |

Query: `account_id` (필수), `period` (`7d|30d|90d|1y|all`), `from`, `to`

---

## Chart (Frontend)

- `recharts` Line / Area / Bar
- 기간 Segmented (7/30/90/1y/전체)
- Summary KPI + 테이블
- Loading / Empty / Error
- Query Key: `account_id` + `period`

파일: `PortfolioAssetHistorySection.tsx`, `portfolio/page.tsx`

---

## Scheduler

Job: `portfolio_equity_snapshot`

- Cron: mon–fri `SCHEDULER_EQUITY_SNAPSHOT_HOUR/MINUTE` (기본 15:40 KST)
- 활성·소유자 있는 Paper 계좌 전부 upsert
- `include_live=true` 시 mode_code=LIVE 행도 저장 (평가 로직 동일, 태그 구분)
- 수동: `POST /api/v1/jobs/portfolio_equity_snapshot/execute`

---

## 보안

- `assert_paper_account_access`로 타 사용자 계좌 차단
- history 조회 시 `user_id` + `account_id` 동시 필터
- 평문 시크릿/계좌번호 미포함

---

## 테스트

- Backend: `pytest tests/test_step66_portfolio_snapshot.py`
- Frontend: `vitest mdd.test.ts`
- OpenAPI 경로·401·MDD 공식

---

## 남은 포트폴리오 기능

- 브로커 Live NAV 전용 스냅샷 (현재는 Paper 평가 + LIVE 태그)
- 입출금/이체 반영 일손익 보정
- 벤치마크(KOSPI) 대비 차트
- Zoom brush / 내보내기 CSV
