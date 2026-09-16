# AUTOTRADING EXECUTION FLOW AUDIT — 2026-07-31

읽기 전용. 클래스 존재 ≠ 연결. 근거는 실제 call chain.

**시스템 진입:** `src/stock_platform/api/lifecycle.py` `ApplicationLifecycle.startup()`  
Recovery → Runtime bootstrap → Schedulers → (조건부) realtime hub.

---

## 1. Hop 판정표

| # | Hop | 판정 | 근거 (요약) |
|---|-----|------|-------------|
| 1 | Market Data | CONNECTED_WITH_LIMITATIONS | Upbit WS `realtime/manager.py`; Kiwoom 실시간 **없음**; KRX 일봉 collector |
| 2 | Indicator | PARTIALLY_CONNECTED | `indicators/pipeline_service` vs screener 인라인 재계산 — 자동 연결 약함 |
| 3 | Candidate | VERIFIED_CONNECTED | `scheduler/handlers` → screener `execute_and_save` |
| 4 | Candidate → AI Lifecycle | CONNECTED_WITH_LIMITATIONS | Promotion Gateway 경유만 lifecycle 보장 |
| 5 | Strategy Request | VERIFIED_CONNECTED | `ai/strategy_request` — 주문/Runtime WRITE 0 |
| 6 | Strategy Draft | VERIFIED_CONNECTED | Draft/Generation — 실행 연결 0 |
| 7 | Backtest | VERIFIED_CONNECTED | Approval path → `BacktestEngine` — Runtime 미연동 |
| 8 | Promotion | VERIFIED_CONNECTED | 상태만 — Activation 자동 시작 0 |
| 9 | Activation | VERIFIED_CONNECTED | 검증만 — Runtime 등록 자동 0 |
| 10 | Runtime Registration | CONNECTED_WITH_LIMITATIONS | DB registry `running=false`, link `is_active=False` |
| 11 | Deployment Readiness | PARTIALLY_CONNECTED | `READY_TO_START` vs loader **`ACTIVE`만** |
| 12 | Runtime Start | CONNECTED_WITH_LIMITATIONS | bootstrap은 **active link**만; STEP12와 분리 |
| 13 | Scheduler | CONNECTED_WITH_LIMITATIONS | Session OPEN ≠ runner 자동 기동 |
| 14 | Signal | VERIFIED_CONNECTED | Hub → MA evaluator → scoped signal (Upbit quote 전제) |
| 15 | Risk Guard | VERIFIED_CONNECTED | KillSwitch + DB RiskOrderGuard |
| 16 | Order Intent | VERIFIED_CONNECTED | `OrderExecutionService.submit` — realtime **broker=KIWOOM 하드코딩** |
| 17 | Order Creation | VERIFIED_CONNECTED | TradingOrder + Outbox enqueue |
| 18 | Broker Submit | VERIFIED_CONNECTED | Outbox worker → Factory adapters |
| 19 | Fill | PARTIALLY_CONNECTED | Upbit FillSync **강**; Kiwoom pending만; Paper outbox auto-fill **약** |
| 20 | Position | PARTIALLY_CONNECTED | Paper `apply_fill`; Live Kiwoom 갭 |
| 21 | Balance/PnL | PARTIALLY_CONNECTED | Settlement 배치; intraday 약함 |
| 22 | SL/TP/Trailing | VERIFIED_CONNECTED | Exit monitor 폴링 |
| 23 | Kill Switch | VERIFIED_CONNECTED | Persistent, fail-closed |
| 24 | Recovery | VERIFIED_CONNECTED | Startup + periodic — 주문 생성 없음 |
| 25 | Reconciliation | CONNECTED_WITH_LIMITATIONS | Upbit 양호; Kiwoom TradingOrder 통합 미완 |
| 26 | Audit/Notification | VERIFIED_CONNECTED | live safety audit, telegram RO |

---

## 2. 실행 Call Chain (검증된 운영 경로)

```
lifecycle.startup
  → broker_recovery_manager.recover()
  → dynamic_strategy_runtime_manager.initialize()
       → bootstrap_scoped_runtimes (active account_strategy_link)
       → realtime consumer register
  → order_outbox_scheduler.start()

[Market→Signal] Upbit WS → RealtimeMarketDataHub → ScopeConsumerRegistry → signal bus
[Signal→Order] realtime_execution_runner (명시적 API start) → RiskIntegratedRealtimeOrderExecutor
             → OrderExecutionService → outbox
[Order→Broker] OutboxWorker → Dispatcher → Kiwoom/Upbit/Paper adapter
[Fill] UPBIT: UpbitFillSyncService | PAPER: 별도 PaperExecutionService | KIWOOM: pending only
```

---

## 3. STEP12 AI 승인 파이프라인 (실행과 분리)

```
Lifecycle → Request → Draft → Approval/Backtest/QG/… → Promotion → Activation
  → RuntimeRegistration (disabled) → DeploymentReadiness (READY_TO_START)
```

**자동 Runtime Start / Order 없음.** 수동: link activate + ACTIVE deployment + runner API.

---

## 4. Broker별 요약

| 환경 | 종합 | 핵심 갭 |
|------|------|---------|
| Kiwoom LIVE | 실API미검증 / 안전상 기본 차단 | 실시간 시세 없음, Fill→Position 단절 |
| Kiwoom MOCK | Mock만 | mockapi 경로 |
| Upbit LIVE | 코드 연결 양호 / 실검증 제한 | realtime broker 하드코딩, LIVE gate 다단계 |
| Stock/Crypto PAPER | Paper만 | Outbox≠auto-fill; runner 수동 |

---

## 5. Critical Gaps

1. STEP12 ↔ Scoped Runtime **3-way 상태 불일치**  
2. Realtime executor `broker_code="KIWOOM"`  
3. Kiwoom realtime market data missing  
4. Kiwoom fill loop gap  
5. PAPER outbox no auto-fill  
6. Runner start decoupled from session OPEN / Trading Scheduler Start  

상세 파일 경로는 PHASE 1 탐색 보고서 및 `SOURCE_COMPONENT_INVENTORY_20260731.md` 참조.
