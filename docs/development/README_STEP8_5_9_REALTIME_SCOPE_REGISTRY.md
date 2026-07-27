# STEP 8-5-9 — realtime_strategy_runner Scope Registry 완전 통합

## 1. 기존 Realtime 구조

고정 MA `RealtimeStrategyRunner`가 Quote Bus를 구독해 신호를 발행하고, `RealtimeExecutionRunner`가 Paper 주문을 실행하는 **전역 싱글톤 파이프라인**이었다. Scope Registry(`DynamicStrategyRuntimeManager`)와는 분리되어 있었다.

## 2. 발견한 전역 Runner

| 심볼 | 파일 | 조치 |
|------|------|------|
| `realtime_strategy_runner` | `realtime/runtime.py` | 유지(호환) · 내부 Hub 위임 |
| `RealtimeMovingAverageStrategy` | `realtime/strategy.py` | 로직 → `MovingAverageStrategyEvaluator`로 이전 |
| `realtime_signal_bus` / `realtime_execution_runner` | 동일 | 공유 버스·실행 유지, Signal에 Scope 메타 추가 |
| `realtime_manager` | `realtime/manager.py` | Shared Hub 시세 소스로 유지 |

## 3. 공유 가능 영역

WebSocket/폴링 연결, Quote Bus, Heartbeat, 원시 파싱, 종목 최신 Cache.

## 4. Scope 격리 영역

전략 Evaluator·파라미터·가격 Buffer·마지막 신호·Cooldown·Warm-up·Pause·Recovery·Kill/Calendar 가드.

## 5. Realtime Hub

`RealtimeMarketDataHub` — Quote Bus 구독 → Event 정규화 → Scope Consumer 라우팅. 주문·Credential 장기 보관 없음.

## 6. Event 모델

`RealtimeMarketEvent` (broker/market/symbol/type/time/price/sequence…)

## 7. Consumer Registry

`ScopeConsumerRegistry` — `subscription_key → set[scope_key]`, `scope_key → consumer`. Scope 없는 등록 `ScopeRequiredError`. Paper도 CRYPTO면 UPBIT 시세 키로 Dedup.

## 8. MA Evaluator

`MovingAverageStrategyEvaluator` — Scope별 State, Warm-up 전 신호 금지, Golden/Dead Cross·손절익절.

## 9. Scope State

`ScopeStrategyState` per symbol — 타 Scope와 객체 공유 금지.

## 10. Event 순서·중복

`raw_sequence` 단조, 역순 무시, `REALTIME_EVENT_MAX_AGE_SECONDS` 초과 무시, fingerprint 중복 차단.

## 11. Warm-up

`long_window+1` 확보 전 `WARMING_UP`, 신호 없음. Rewarm API로 Buffer 초기화.

## 12. Strategy Definition 연계

Runtime bootstrap 시 `parameter_payload`의 short/long/cooldown 사용. Entry symbol로 구독.

## 13. Startup

Recovery → Hub dispatch start → Scoped Runtime bootstrap(Consumer sync) → Scheduler.

## 14. Runtime Lifecycle

put/reload/pause/resume/stop/pause_account → `sync_realtime_consumer_for_entry`. Pause 중 State 갱신 가능·신호 차단.

## 15. Recovery

`pause_account_runtimes` → Consumer `signals_allowed=False`. 다른 계좌 유지.

## 16. Calendar

KIWOOM/STOCK 신호 발행 시 `TradingCalendarService.evaluate` — `live_allowed` 아니면 차단. Upbit/Paper CRYPTO 영향 없음.

## 17. Upbit Rate Limit

UBA 주문 Group cooldown/418 시 신호 publish 차단. Paper CRYPTO는 제외.

## 18. Signal 모델

`StrategySignal` + `RealtimeSignal` Scope 메타 확장 (`signal_id`, `fingerprint`, `scope_key`, …).

## 19. Signal 중복 방지

Evaluator fingerprint + 프로세스 메모리 Dedup(5분).

## 20. 주문 실행

`RiskIntegratedRealtimeOrderExecutor` — Signal Scope의 `account_id` 우선. Scope 있는데 account 없으면 SKIP.

## 21. Paper

Paper Scope도 동일 Registry. LIVE State 공유 금지. 시세 키만 UPBIT/KIWOOM 공유.

## 22. 연결 상태

`HubConnectionStatus` vs Runtime `PAUSED` 분리 가능.

## 23. 관리자 API

`/api/v1/admin/realtime/connections|subscriptions|scopes|{scope}/reconnect|rewarm`

## 24. USER API

`/api/v1/user/realtime/scopes[/{scope_key}]` — 본인만.

## 25. Frontend

`/admin/trading` — `AdminRealtimeHubPanel`. USER 전략 화면 Warm-up/상태/마지막 신호 Tag.

## 26. 운영 Health

monitoring overview `realtime` 요약 (상세 계좌·종목 비노출).

## 27. Audit

`ADMIN_REALTIME_SCOPE_RECONNECT`, `ADMIN_REALTIME_SCOPE_REWARM`. Tick마다 Audit 없음.

## 28. 레거시 제거

전역 MA 루프 제거. `RealtimeStrategyRunner`는 Deprecated 파사드(Hub start/stop/status). `/realtime-strategy/*` 호환 유지.

## 29. DB 변경·Migration

**Migration 없음** — 메모리 Hub/Registry. Head 유지: `y2c3d4e5f6a7`.

## 30. 설정

`REALTIME_HUB_*`, reconnect, event age, cooldown, warmup, max scopes — Settings validation 포함.

## 31. 변경 파일 (요약)

- `realtime/hub_constants.py`, `market_event.py`, `strategy_signal.py`, `ma_evaluator.py`
- `consumer_registry.py`, `market_data_hub.py`, `scoped_signal_pipeline.py`, `runtime_bridge.py`
- `strategy_runner.py`(파사드), `strategy_models.py`, `risk_integrated_order_executor.py`
- `runtime_manager.py`, `lifecycle.py`, `admin_realtime_hub.py`, `router.py`
- `monitoring_snapshot.py`, `settings.py`, `.env.example`
- Frontend admin/user trading·strategies
- `tests/test_step8_5_9_realtime_scope_registry.py`

## 32. 테스트 결과

- Backend pytest: **691 passed / 0 failed / 3 skipped**
- Frontend Vitest: **83/83**
- TypeScript: 통과
- Lint: **0 errors / Warning 6**
- Production Build: 성공
- Alembic Head: **y2c3d4e5f6a7** (Migration 없음, single head)

## 33. 운영 적용

```text
# Migration 없음
# .env REALTIME_HUB_* 확인 후 API 재시작
```

## 34. 기존 Lint Warning 상태

Warning 6건 유지 목표.

## 35. 남은 문제

- Candle Backfill Warm-up(REST)은 Coordinator 연계 골격만 — 심볼별 자동 backfill은 후속
- LIVE Kiwoom Private WS 전용 연결은 본 STEP 범위 밖(시세 공유 허브 중심)
- Signal History DB 영속화 없음(메모리 Dedup)
