# 아키텍처 — stock-platform v1.0

```text
FastAPI (lifespan)
  ├─ Health / Dashboard / Audit
  ├─ Market collectors (Kiwoom/Upbit)
  ├─ Indicators / Screener / AI
  ├─ OrderExecutionService
  │    → Risk/KillSwitch/Sizing
  │    → TradingOrder + Outbox
  │    → OutboxWorker → BrokerAdapter
  ├─ ExecutionSync / Recovery / Timeout
  ├─ Risk Engine / Exit Monitor
  └─ Notifications (Telegram/Slack/Discord)
           │
      PostgreSQL 17
```

## 핵심 원칙

1. 주문은 `OrderExecutionService` 단일 진입점만 사용한다.
2. Broker 직접 호출 금지(Outbox Worker만 송신).
3. 실전 주문은 환경 플래그 + DB 승인 모두 필요.
4. 민감 API는 `X-Admin-API-Key`로 보호.
5. Docker 없이 Windows 서비스형 PostgreSQL 사용.

## 도메인 패키지

- `markets`, `indicators`, `screener`, `ai`
- `order`, `broker`, `trading`, `position`
- `risk`, `risk_engine`, `realtime`
- `operation`, `notification`, `scheduler`
