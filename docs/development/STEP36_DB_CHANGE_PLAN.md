# STEP36 DB 변경 계획

> 작성일: 2026-07-18  
> 상태: STEP36-01~07 완료 (head `d5b1c82e4a01`)  
> 원칙: 기존 `market.instrument` / `market.price_daily` 재사용.  
> `market.symbol` / `market.candle_day` 재생성 금지.

## 현재 DB

| 테이블 | 역할 | 상태 |
|--------|------|------|
| `market.instrument` | 종목 마스터 | 사용 중 |
| `market.price_daily` | 일봉 | 사용 중 |
| `market.candle_minute` | 분봉 (1/3/5/15) | 신규 |
| `market.quote_snapshot` | 최신 호가 | 신규 |
| `market.trade_tick` | 체결 틱 | 신규 |
| `market.orderbook_snapshot` | 호가창 | 신규 |
| `market.indicator_daily` | 일봉 지표 | 신규 |

## Unique 키

| 테이블 | Unique / PK |
|--------|-------------|
| candle_minute | instrument_id + timeframe + candle_at |
| quote_snapshot | instrument_id |
| trade_tick | instrument_id + trade_id |
| orderbook_snapshot | instrument_id + captured_at |
| indicator_daily | instrument_id + trade_date |

## STEP36-06/07

- 지표: MA5/20/60, EMA12/26, RSI14, volume_ma20, 52주 고저 + status(READY/PARTIAL/INSUFFICIENT)
- Job: `indicator_daily_batch`
- 품질: OHLC/음수/갭/중복 + `/api/v1/market-quality/dashboard`

## 금지

- overlay `docs/migration-overlays/` 의 symbol/candle_day/indicator 적용
- Docker 기반 DB
