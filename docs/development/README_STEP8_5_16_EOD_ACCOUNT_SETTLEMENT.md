# STEP 8-5-16 — EOD Account Settlement

EOD 실정산 자동화 및 포지션·체결·잔고 일관성 검증.

## 1. 기존 정산 구조

- `KRX_SETTLEMENT` Market Session Job Handler가 `SETTLEMENT_NOOP`만 반환
- Scheduler Job 정의·Claim·Run History는 존재하나 일일 정산 로직 없음
- Equity Snapshot / Daily Report는 시점 가치·리포트용으로 별도 존재

## 2. 기존 Snapshot 구조

- `BrokerAccountSnapshotEntity` / `BrokerPositionSnapshotEntity`: LIVE 잔고·포지션
- Portfolio Equity Snapshot: 빠른 조회·리포트
- Settlement는 Snapshot을 **검증·확정** 용도로 참조 (동일 계산식 중복 저장 금지)

## 3. Settlement 범위

| 유형 | Settlement Type | 실행 |
|------|-----------------|------|
| Kiwoom LIVE | `KRX_EOD` | `KRX_SETTLEMENT` Job |
| Stock Paper | `PAPER_STOCK_EOD` | `KRX_SETTLEMENT` Job |
| Upbit LIVE | `UPBIT_DAILY` | Upbit Daily Cron (KRX 비연동) |
| Crypto Paper | `PAPER_CRYPTO_DAILY` | Upbit Daily Cron |

## 4. Broker별 차이

- **Kiwoom**: 예수금·주문가능·보유·수수료·세금·미체결 (Snapshot 기반 Fail Closed)
- **Upbit**: KRW/Locked·코인 보유·평균매수가·수수료 (Snapshot 기반, 00:10 KST)
- **Paper**: 내부 Ledger = 진실, 외부 API 없음

## 5. Settlement 모델

`trading.account_daily_settlement` — 계좌 XOR (UBA | Paper) + 날짜 + type Unique

상태: `PENDING` `RUNNING` `SUCCEEDED` `SUCCEEDED_WITH_WARNINGS` `RETRY_PENDING` `FAILED` `MANUAL_REVIEW_REQUIRED` `SKIPPED` `SUPERSEDED`

## 6. Issue 모델

`trading.account_daily_settlement_issue` — 주문/체결/포지션/현금/AMBIGUOUS 등

## 7. 실행 단위

`market_session_job` → `KRX_SETTLEMENT` → 계좌별 독립 commit → 집계

## 8. 계좌 Lock

`RecoveryLockScope(market_type=ACCOUNT_SETTLEMENT:{market_date})` + account_kind/id  
Commit 전 `assert_owns` — Ownership Lost 시 성공 Commit 금지

## 9. Broker Adapter

- `PaperSettlementAdapter`
- `KiwoomSettlementAdapter` / `UpbitSettlementAdapter` (`adapters_live.py`, 기존 Snapshot 재사용)

## 10–18. Reconcile / PnL / 가격

- 주문: AMBIGUOUS·REMOTE_LOOKUP_PENDING → LIVE는 Manual Review
- 체결: Broker Fill ID 중복 탐지
- 포지션: 수량(tol=0)·평균가(Decimal)
- 현금: Paper available_cash vs bundle
- PnL: `net = realized - fees - taxes`; 입출금 없으면 `DEPOSITS_UNKNOWN`(INFO)
- 평가가: Broker → 종가 → 최근 검증 종가 → 체결가 (Realtime Tick 단독 종가 금지)
- SUCCEEDED: 핵심 불일치 0 + AMBIGUOUS 0 + Sync OK
- Warning: 평균가 경미 차이 등 비핵심만

## 19–25. Pause / Adjustment / Jobs

- Critical mismatch → UBA `trading_paused` (일괄 Broker Pause 금지)
- `ledger_adjustment`: 요청·승인 구조만 (자동 적용 UI 없음)
- KRX Handler: NOOP 제거 → `run_krx_eod_settlement`
- Upbit: Cron `UPBIT_DAILY_SETTLEMENT_HOUR/MINUTE` (기본 00:10 Asia/Seoul)

## 26–33. API / FE / Health / Audit / Settings

- Admin: `/api/v1/admin/settlements` (+ health/retry/reconcile/resolve/run)
- USER: `/api/v1/user/settlements` (본인 계좌·안전 필드만)
- FE: Admin Batch 패널 + User Reports 정산 상태
- Health: `account_settlements` 컴포넌트 (Public에는 계좌 상세 미노출)
- Settings: `SETTLEMENT_*`, `UPBIT_DAILY_SETTLEMENT_*`

## 34–35. Migration / Tests

- Revision: `d7e8f9a0b1c2` (revises `c6d7e8f9a0b1`)
- Backfill: **없음** (과거 가짜 Settlement 금지)
- Tables: `account_daily_settlement`, `account_daily_settlement_issue`, `ledger_adjustment`

## 36. 변경 파일 (요약)

- `src/stock_platform/settlement/*`
- `api/v1/admin_settlements.py`, `user_settlements.py`
- `operation/market_session_job_handlers.py`, `health_service.py`, `lifecycle.py`
- `database/alembic/versions/d7e8f9a0b1c2_*.py`
- Frontend Admin/User Settlement UI
- `tests/test_step8_5_16_eod_account_settlement.py`

## 37. 테스트 결과

```text
Backend pytest: 793 passed / 0 failed / 3 skipped
STEP 8-5-16 tests: 9 passed
Frontend Vitest: 96/96
TypeScript: 통과
Lint: 0 errors / 0 warnings
Production Build: 성공
Alembic down/up (c6d7e8f9a0b1 ↔ d7e8f9a0b1c2): 성공
Alembic Head: d7e8f9a0b1c2 (single head)
Backfill: none
```

## 38. 운영 적용

```bash
alembic upgrade head
# SETTLEMENT_ENABLED=true, UPBIT_DAILY_SETTLEMENT_ENABLED=true
```

## 39. 남은 문제

- LIVE UBA ↔ Broker Snapshot 계좌 바인딩이 최신 broker snapshot 휴리스틱 (평문 계좌번호 미저장)
- Paper 주문은 `TradingOrderEntity.paper_account_id` 부재로 주문 reconcile 제한
- Ledger Adjustment 자동 적용·승인 워크플로는 후속 STEP
- Upbit/Kiwoom 실시간 Sync를 Settlement 직전 강제 호출은 Fail Closed Snapshot 선행에 의존
