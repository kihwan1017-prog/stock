# STEP 11-7 — Chart · Market AI Analysis Pipeline

## 최종 원칙

- AI 결과는 **참고 정보**이며 매수·매도·주문·전략·리스크 설정이 아니다.
- 시세/캔들 **수집과 AI 실행을 분리**한다. 수집·갱신만으로 AI 호출 0.
- 기본 Provider는 **Mock**. EXTERNAL은 `confirm=true`만.
- Vision 차트 이미지는 **기본 비활성** (`VISION_ENABLED_DEFAULT=False`).
- Trading / Order / Scheduler에서 `ai.market_analysis` import 금지.
- STEP 11-8은 본 STEP 완료 전 시작하지 않는다.

## Architecture

```
Admin Request
  → Eligibility (Prompt ACTIVE, Snapshot, Data Quality)
  → MarketSnapshotBuilder (price_daily / candle_minute + indicator_daily)
  → Candle normalize (Decimal, OHLC checks)
  → AIExecutionService.create_request (≠ execute)
  → DRY_RUN / MOCK / EXTERNAL
  → CHART_ANALYSIS_RESULT_V1 | MARKET_ANALYSIS_RESULT_V1
  → Safe Result (ai.market_analysis)
  → Admin UI / Dashboard / Telegram read-only
```

## KRX / Upbit

| 항목 | KRX | Upbit |
|------|-----|-------|
| 일봉 | `market.price_daily` | 동일 |
| 분봉 | 수집 없음 | `market.candle_minute` |
| Symbol | `005930` | `KRW-BTC` |
| Timezone | Asia/Seoul (거래일) | 일봉 KST 날짜 / 분봉 UTC |
| 수정주가 | 수집 시 adjusted (컬럼 구분 없음) | N/A |
| 휴장 | trading_calendar | ALWAYS_OPEN |

심볼은 반드시 `(exchange_code, symbol)`.

## Snapshot

- 고정 hash/version, completed_candle_only 기본
- 당일 미완성 일봉 기본 제외 (`include_incomplete_candle`로만 포함)
- 전체 Tick/호가/계좌/주문 **미포함**
- 입력 크기 초과 시 **명시적 downsampling** (무음 절단 금지)

## Candle / Decimal

- float NaN/Infinity 거부
- OHLC 불일치·음수 volume → quality flags / INVALID
- JSON은 Decimal 문자열

## Indicator

- 내부 `indicator_daily` + `INDICATOR_VERSION=indicator_engine_v1`
- AI가 지표를 새로 계산하지 않음
- AI 수치 mismatch → warning (`AI_MARKET_NUMERIC_MISMATCH`)

## Limits

- 일봉 최소 30 / 최대 250
- 분봉 최소 30 / 최대 300
- Batch Mock ≤100 / External ≤10
- Vision 기본 OFF

## Data Quality

GOOD / ACCEPTABLE / STALE / INCOMPLETE / GAP_DETECTED / DUPLICATE_DETECTED / INVALID  
INVALID → 실행 차단.

## Schemas / Prompts

- `CHART_ANALYSIS_RESULT_V1`, `MARKET_ANALYSIS_RESULT_V1` (ACTIVE)
- `CHART_ANALYSIS_BASE`, `MARKET_ANALYSIS_BASE` (**DRAFT** until operator activates)

금지 필드: buy/sell/order/target_price/entry/position_size/stop_loss_order/live/arm/scheduler/allocate/api_key 등.

## API

`/api/v1/admin/ai/market-analyses` — create/dry-run/execute/cancel/reanalyze/batches/compare/dashboard

## Frontend

Admin → AI → **시장·차트 분석**. 매수·매도·전략·손절 버튼 없음.

## Dashboard / Telegram

- Dashboard: `ai_market_analyses`
- Telegram: `/ai_charts`, `/ai_markets` (조회만)

## Migration

- **`y5f6a7b8c9d0`** (revises `x4e5f6a7b8c9`)
- Rollback: `alembic downgrade -1`

## STEP 11-8 연결 원칙

후보/전략 Task로 확장하더라도 **점수·주문·LIVE 자동 연결 금지**. 11-7 Safe Result는 참고 계층만.
