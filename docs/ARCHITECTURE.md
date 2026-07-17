# STEP33 Architecture

```text
Kiwoom REST ------+
                  +--> Market Client --> Sync Service --> Repository --> PostgreSQL
Upbit REST -------+                                          |
                                                             +--> FastAPI
```

원칙:
- 외부 API 모델과 내부 domain model 분리
- 수집과 저장 분리
- 일봉은 `(market, symbol, candle_date)` 기준 upsert
- quote는 `(market, symbol)` 기준 최신 상태 유지
- trade는 외부 trade ID 기준 중복 방지
