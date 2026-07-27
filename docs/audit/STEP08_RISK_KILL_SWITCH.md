# STEP 08 — Risk Engine과 Kill Switch 검증

> 작성일: 2026-07-22  
> 목표: Kill Switch·Risk 가드를 안전하게 통합하고, fail-closed·스코프·감사 이력을 보강한다.

---

## 1. 분석 결과

### 1.1 구조

| 계층 | 역할 |
|------|------|
| `risk_engine.KillSwitchService` | GLOBAL DB 상태·이력·exchange reason 파싱 |
| `PersistentKillSwitchGuard` | 주문 허용 검사 (SELL 예외, exchange 스코프) |
| `DatabaseBackedRiskOrderGuard` | RealtimeRiskEngine + PositionLimit |
| `DailyLossMonitor` | 한도 초과 시 GLOBAL Kill Switch 자동 활성화 |
| API `/api/v1/risk/kill-switch` | 조회·activate/deactivate (admin) + **history** |

### 1.2 스코프 매트릭스

| Scope | 상태 |
|-------|------|
| GLOBAL | ✅ 구현·주문 경로 연결 |
| Exchange | ✅ reason `EXCHANGES=` + activate `exchange_codes` + 주문 경로 `exchange_code` 전달 |
| Account | ❌ 미구현 (일손실 reason에 ACCOUNT 메타만) |
| User | ❌ 미구현 |

### 1.3 Fail-closed

| 상황 | BUY | SELL(allow_sell) |
|------|-----|------------------|
| KS ACTIVE | 차단 | 허용 |
| KS DB 조회 실패 | **차단** (`KILL_SWITCH_UNAVAILABLE`) | 허용 |
| `skip_risk_checks=True` | 우회 (내부 경로) | — |

---

## 2. 수정한 파일

| 파일 | 내용 |
|------|------|
| `risk_engine/kill_switch_guard.py` | fail-closed, `KillSwitchUnavailableError` |
| `risk_engine/kill_switch_service.py` | `exchange_codes`, `list_history`, state.exchange_scope |
| `risk_engine/kill_switch_models.py` | `exchange_scope` 필드 |
| `api/v1/kill_switch.py` | history GET, activate exchange_codes |
| `order/execution_service.py` | exchange_code 전달, UNAVAILABLE 코드 |
| `realtime/risk_integrated_order_executor.py` | 동일 |
| `order/trading_guards.py` | Unavailable → TradingGuardError |
| `risk_engine/daily_loss_monitor.py` | BROKER/ACCOUNT reason 메타 |
| `operation/setting_catalog.py` | `risk_max_order_amount` 기본 100000 정렬 |
| `risk_engine/runtime.py` | 정책 단일 소스 주석 |
| 테스트 Fake·서비스·가드 보강 | |
| `docs/audit/STEP08_RISK_KILL_SWITCH.md` | 본 문서 |

---

## 3. 주요 수정 내용

1. **테스트 회귀 수정:** Fake에 `active_exchange_scope` 추가 → STEP2부터 잔존하던 실패 제거  
2. **Fail-closed:** DB 예외 시 BUY 차단, reason code `KILL_SWITCH_UNAVAILABLE`  
3. **Exchange 스코프 경로 통일:** submit/realtime에 `exchange_code` 전달  
4. **Activate API:** optional `exchange_codes` → reason에 `EXCHANGES=`  
5. **History API:** `GET /api/v1/risk/kill-switch/history` (admin)  
6. **정책 정렬:** catalog 기본 주문한도를 runtime(10만)과 맞춤 (보수적)  
7. **일손실:** 자동 KS reason에 계좌 메타 포함 (여전히 GLOBAL 정지 — Account 스코프는 후속)

Live 주문 플래그는 변경하지 않음. 해제는 admin + audit 유지.

---

## 4. 테스트 결과

```powershell
pytest tests/test_persistent_kill_switch_guard.py tests/test_kill_switch_service.py ... -q
# → 통과

pytest -q
# → 2 failed, 534 passed, 3 skipped
```

| 실패 | 후속 |
|------|------|
| `test_automatic_scheduler` | STEP9 |
| `test_unauthenticated_order_mutate_rejected` | 환경(PG password) / STEP17 |

**Kill Switch 관련 실패: 0**

---

## 5. 남아 있는 문제

- Account/User Kill Switch 스코프 DB·API 미구현  
- 일손실 모니터는 KIWOOM 단일 계좌·GLOBAL KS  
- Admin setting DB 값을 runtime policy에 실시간 오버레이하지 않음 (코드 정책이 단일 소스)  
- Cancel/Replace Outbox화는 STEP7에서 연기한 항목 유지

---

## 6. 다음 단계

명령서 순서상 **STEP9 Scheduler와 자동매매 Runtime**.

---

## 7. 권장 커밋 메시지

```text
fix(step08): harden kill switch fail-closed, exchange scope, and history API
```
