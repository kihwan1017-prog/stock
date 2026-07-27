# STEP 8-9C-4 — UBA Daily Loss · Equity Baseline

## Daily Loss 정의

| 필드 | 의미 |
|------|------|
| `opening_equity` | 당일 Asia/Seoul Baseline 총평가 (예수금+보유평가) |
| `closing_equity` | 현재 ACTIVE Broker Snapshot 총평가 |
| `current_daily_pnl` | `closing_equity - opening_equity` |
| `current_daily_loss` | `max(0, -current_daily_pnl)` |
| `max_daily_loss_limit` | UBA Risk 한도 |
| `remaining_daily_loss_capacity` | `max_daily_loss_limit - current_daily_loss` |

**금지:** Broker Snapshot의 `total_profit_loss`(누적 평가손익)를 일일 손실로 사용.

## UBA Scope

집계는 반드시 다음만 사용한다.

- `user_broker_account_id` (단일 UBA)
- ACTIVE Broker Account/Position Snapshot
- 당일 Asia/Seoul 거래일 Baseline
- 당일 FILLED 계열 주문 수 (진단용; 손익은 equity delta)

제외: Paper, Kiwoom, 다른 Upbit UBA, 동일 user의 다른 계좌, 취소/거부/미체결 주문, Soft-deleted 계좌.

## 계산 경로

```
Preflight DAILY_LOSS
  → AccountDailyLossEntity (uba_id + trading_date KST)
DailyLossMonitor.check_uba
  → UbaDailyLossService.ensure_baseline(FIRST_OBSERVED)
  → UbaDailyLossService.diagnose
  → equity = deposit + total_evaluation
  → pnl = equity - baseline.opening_equity
  → loss = max(0, -pnl)
  → AccountDailyLossRepository.upsert
```

## Baseline 정책

- LIVE UBA 최초 관측 시 `risk.uba_daily_equity_baseline` 생성 (`FIRST_OBSERVED`)
- 당일 체결 0건 오염 정정: `recalculate_and_persist(reset_baseline_if_no_executions=True)` → source `RECALC_NO_EXECUTIONS`
- Baseline 이전 Broker 보유 평가 변동은 일일 손익에 포함하지 않음
- Baseline 생성은 조회 전용 Snapshot만 사용 (주문 API 금지)

## 신규 계좌 초기화

신규 LIVE UBA: 주문 0 / Execution 0 / Daily Loss 0. 타 계좌 손익 상속 금지.

## 재계산 절차

```python
from decimal import Decimal
from stock_platform.database.session import get_session_factory
from stock_platform.risk_engine.uba_daily_loss_service import UbaDailyLossService

session = get_session_factory()()
UbaDailyLossService(session).recalculate_and_persist(
    user_broker_account_id=UBA_ID,
    loss_limit=Decimal("300000"),
    actor="OPERATOR",
)
```

한도 미만이면 잘못 켜진 `UBA:{id}` Kill Switch scope를 해제한다.

## 정정 Audit

| event_type | 시점 |
|------------|------|
| `UBA_DAILY_LOSS_BASELINE_CREATED` | Baseline 최초 생성 |
| `UBA_DAILY_LOSS_BASELINE_RESET` | force_replace |
| `UBA_DAILY_LOSS_RECALCULATED` | before/after breakdown |

직접 `UPDATE account_daily_loss SET current_loss=0` 금지. Risk 한도 상향 우회 금지.

## Rehearsal 시세 Fixture

- 심볼: `RH*` only (`RehearsalMarkPriceRegistry`)
- 주문 전 마크 등록 필수
- 이전 run 잔여 `RH*`는 `_cleanup_all_rehearsal_positions`로 매도 정리
- equity 평가 시 잔여 `RH*`는 `REHEARSAL_TEST_PRICE`로 마크
