# API

## Symbols
`GET /api/v1/market/symbols?market=KRX`

## Quote
`GET /api/v1/market/quotes/KRX/005930`

## Daily candles
`GET /api/v1/market/candles/day/KRX/005930?limit=200`

## Trades
`GET /api/v1/market/trades/KRX/005930?limit=100`

## Manual sync
- `POST /api/v1/market/sync/upbit/day/KRW-BTC?count=200`
- `POST /api/v1/market/sync/kiwoom/day/005930`
