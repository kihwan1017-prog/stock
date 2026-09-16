# KIWOOM LIVE/MOCK Source-of-Truth Alignment

**상태:** PATCH_READY / 운영 reload 때문에 **src 미적용**  
**일자:** 2026-08-19  
**대상:** KIWOOM UBA1381 execution SoT  
**금지:** UPBIT UBA1380 중단 · `KIWOOM_USE_MOCK` ENV 변경 · KIWOOM LIVE/ARM/주문

uvicorn은 `--reload --reload-dir src` 로 기동 중이다. `src/` 저장 시 startup fail-closed로 UBA1380 LIVE/ARM/Worker/Runtime/Runner가 내려간다. 유지창에서만 본 패치를 적용한다.

---

## Canonical SoT (적용 후)

| 구분 | SoT | ENV/필드 |
|------|-----|----------|
| 주문 실행 환경 | UBA credential `is_mock` + host | `is_mock=false` → `https://api.kiwoom.com` |
| 시장데이터/WS | process `KIWOOM_USE_MOCK` | 이번 STEP에서 **true 유지** |
| LIVE 가능 여부 | GLOBAL → KIWOOM_LIVE → UBA active → credential VERIFIED → `is_mock` → Activation → LIVE → ARM | 기존 게이트 |

UBA1381 현재: `is_mock=false` explicit → **EXECUTION REAL**. `KIWOOM_USE_MOCK=true` → **MARKET MOCK** (WARN/limitation, dispatch CRITICAL 아님).

---

## 현재 코드 SoT 맵 (적용 전)

| 함수 | GLOBAL ENV | broker ENV | UBA credential | 비고 |
|------|------------|------------|----------------|------|
| `evaluate_live_flag_consistency(broker)` | LIVE flags | `KIWOOM_USE_MOCK` | **미사용** | KIWOOM/`None` → `LIVE_MOCK_CONFLICT` CRITICAL |
| `evaluate_live_flag_consistency("UPBIT")` | GLOBAL+UPBIT | `UPBIT_USE_MOCK` | 미사용 | KIWOOM mock **무시** |
| `kiwoom_uba_has_explicit_real_execution` | — | — | explicit `is_mock=false` | Option D canonical |
| `kiwoom_global_mock_blocks_live_execution` | LIVE+mock | same | explicit REAL이면 **False** | dispatch 우회 |
| `assert_kiwoom_live_env_allows_orders` | 위 + Option D | | UBA | conflict여도 explicit REAL 통과 |
| `LiveOrderSafetyPipeline` | broker-scoped evaluate | | Option D bypass | OES 정렬됨 |
| `assert_live_outbox_dispatch_safety` | broker-scoped | | Option D bypass | dispatch 정렬됨 |
| `BrokerAdapterFactory` (LIVE KIWOOM) | unscoped evaluate | | Option D bypass | host는 vault |
| `build_kiwoom_order_config_from_vault` | fallback only if `is_mock` 없음 | | **payload is_mock** | REAL host 정상 |
| `KiwoomLiveTransitionValidator` ACCOUNT | shared mock | | explicit REAL 통과 | Option D |
| `KiwoomLivePreflightService` `KIWOOM_REAL_ENV` | 제외 | | credential is_mock | PASS |
| `KIWOOM_MARKET_ENV` | `KIWOOM_USE_MOCK` | | — | WARN 가능 |
| `evaluate_kiwoom_runtime_run_gates` | worker 등 | | credential VERIFIED | **LIVE_MOCK_CONFLICT 없음**. Activation/LIVE/ARM로 BLOCK |
| `LiveOrderDryRunService` | unscoped KIWOOM evaluate | | 미전달 | **LIVE_MOCK_CONFLICT로 BLOCK** (갭) |
| `health_service` live_flag | unscoped | | 미전달 | ops CRITICAL 힌트 (주문 경로와 분리) |
| market auth/WS | `kiwoom_use_mock` | | — | 시장 SoT |
| `KiwoomOrderConfig.from_env` | `kiwoom_use_mock` | | — | SYSTEM_SHARED/레거시만 |

**Root cause:** Option D는 dispatch/OES/factory/validator/preflight에 이미 있다. `evaluate_live_flag_consistency`가 UBA를 받지 않아 프로세스 플래그만으로 `LIVE_MOCK_CONFLICT` CRITICAL을 낸다. Dry-run 등 UBA 없는 호출이 이 코드를 그대로 차단에 쓴다.

---

## 유지창 패치 (중복 예외 로직 추가 금지 — Option D 승격)

### 1. `evaluate_live_flag_consistency` 시그니처

```python
def evaluate_live_flag_consistency(
    broker_code: str | None = None,
    *,
    session: Session | None = None,
    user_broker_account_id: int | None = None,
    uses_system_shared_credential: bool = False,
    credential_ref: str | None = None,
) -> LiveConfigGateResult:
```

`LIVE_MOCK_CONFLICT` 분기에 **기존** `kiwoom_global_mock_blocks_live_execution`만 호출한다.

- UBA explicit REAL → `allowed=True`, `code=KIWOOM_EXPLICIT_REAL_EXECUTION`, `status=DEGRADED` (market MOCK WARN), detail `execution_env=REAL`, `market_env=MOCK`
- unscoped / mock credential / SYSTEM_SHARED → 기존 `LIVE_MOCK_CONFLICT` **유지** (`test_p_live_config_gate_conflict_signal_preserved`)

### 2. 호출부 — evaluate에 session+UBA 전달 (별도 예외 분기 축소)

- `assert_kiwoom_live_env_allows_orders`
- `LiveOrderSafetyPipeline.evaluate`
- `assert_live_outbox_dispatch_safety`
- `BrokerAdapterFactory.create` (KIWOOM LIVE)
- `LiveOrderDryRunService.run`

### 3. `evaluate_kiwoom_runtime_run_gates`

동일 evaluate(UBA) 사용. explicit REAL이면 `LIVE_MOCK_CONFLICT` blocker 넣지 않음. mock credential이면 blocker 추가. Activation/LIVE/ARM OFF는 그대로 BLOCK. **UPBIT pause 호출 금지.**

### 4. 하지 말 것

- `KIWOOM_USE_MOCK` ENV rename/false
- KIWOOM Activation/LIVE/ARM/Runner START
- UPBIT 스택 mutation
- `--reload` 켠 채 `src/` 저장

적용 후: `pytest tests/test_kiwoom_live_mock_sot_alignment.py` 의 skip 1건이 PASS가 되어야 한다.

---

## 현재 운영 (2026-08-19 11:04 KST, READ-ONLY)

- UPBIT 1380: #19 ACTIVE · LIVE ON · ARM ACTIVE · Worker/Exit/Runtime/Runner RUNNING · Scheduler PAUSE · 주문 247/1696 · Outbox 58/1133
- KIWOOM 1381: credential VERIFIED · `is_mock=false` · host `api.kiwoom.com` · LIVE/ARM OFF · Activation INACTIVE · Runtime STOPPED
- backend `--reload-dir src` · 본 STEP에서 src 미저장 · reload 0
