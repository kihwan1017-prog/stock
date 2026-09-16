# AI_ARCHITECTURE

실제 구현 기준 실행 흐름. **클래스 존재 ≠ 연결.**  
근거: [audit/AUTOTRADING_EXECUTION_FLOW_AUDIT_20260731.md](audit/AUTOTRADING_EXECUTION_FLOW_AUDIT_20260731.md)  
**최종 갱신:** 2026-07-31

---

## End-to-end (목표)

```text
Market → Candidate → Strategy Lifecycle → Runtime → Risk → Order → Broker
  → Execution/Fill → Position/Balance/P&L → Recovery/Reconciliation
```

---

## Hop 요약

| 구간 | 상태 | 비고 |
|------|------|------|
| Market | PARTIAL | Upbit WS OK · **GAP:** Kiwoom realtime quotes |
| Candidate | CONNECTED | Screener → AI assessment→…→lifecycle |
| Strategy Lifecycle (STEP12) | GATED | 상태/승인만 · **실행 WRITE 0** |
| Runtime | PARTIAL | Scoped in-memory + DB registry **이중** |
| Risk | CONNECTED | Kill Switch · guards |
| Order | CONNECTED | Outbox SKIP LOCKED · **GAP P0-1:** realtime `broker_code=KIWOOM` |
| Broker | CONNECTED | Factory adapters |
| Fill | PARTIAL | Upbit sync OK · **GAP P0-2** Kiwoom · **GAP P0-5** Paper |
| Position/Balance/P&L | PARTIAL | Paper apply_fill · settlement 배치 |
| Recovery/Reconcile | PARTIAL | Upbit > Kiwoom |

---

## GAP (명시)

1. **GAP-A (P0-3):** STEP12 Registration/Deployment (`READY_TO_START`, inactive links) ↔ Scoped Runtime bootstrap (`ACTIVE` links only) — 자동 연결 없음  
2. **GAP-B (P0-1):** `RiskIntegratedRealtimeOrderExecutor` 등 realtime submit의 broker 하드코딩  
3. **GAP-C (P0-2):** Kiwoom Fill → TradingOrder → Position/Balance/P&L  
4. **GAP-D (P0-5):** Paper Outbox ACCEPTED → `PaperExecutionService` 자동 Fill  
5. **GAP-E:** Session OPEN ≠ Runner 자동 start  
6. **GAP-F:** Kiwoom realtime market data 부재  

```text
[STEP12] … → Deployment READY_TO_START
                    ✗ auto
[Runtime] bootstrap(active links only) → runner (수동 API)
                    → Risk → Order ──P0-1──► Outbox → Broker
                                              │
                         Upbit Fill OK ◄──────┤
                         Kiwoom ──P0-2── GAP   │
                         Paper ──P0-5── GAP    │
```

상세 도메인 맵: [architecture/ARCHITECTURE.md](architecture/ARCHITECTURE.md) · [architecture/STRATEGY_LIFECYCLE_STEP12.md](architecture/STRATEGY_LIFECYCLE_STEP12.md)
