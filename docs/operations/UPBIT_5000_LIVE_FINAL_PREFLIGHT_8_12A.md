# STEP 8-12A — 업비트 5,000원 LIVE 최종 사전검증

UBA 58 기준 **실주문 직전** Read-only / Dry-run 게이트.  
STEP 8-12B(실주문)와 분리하며, 운영자 승인 문구·실주문 명령은 본 STEP에서 생성하지 않는다.

## 1. 목적

1. Recovery Conflict unresolved 건을 **조회 전용**으로 분류
2. 현재 실거래 영향 여부 판정
3. Allowlist Market·지정가 **후보** 제공 (자동 확정 금지)
4. 운영자 Market/Price 확정 시에만 Dry-run
5. `READY_FOR_OPERATOR_APPROVAL` 또는 `BLOCKED` 판정 후 **중단**

## 2. 절대 금지

- Upbit/Kiwoom 실주문, cancel/replace
- LIVE ON / ARM / ARM Token / `--execute-live`
- Conflict approve-import / ignore / 상태 변경 / Import
- Trading Scheduler Resume / Runtime Resume
- Kill Switch·Risk·Credential 변경
- 직접 DB UPDATE, 운영자 승인 문구 대행 생성
- Market·지정가 자동 확정

## 3. Conflict 분류 기준

| 코드 | 의미 |
|------|------|
| `CURRENT_ACTIVE_CONFLICT` | Broker/DB 미체결과 충돌 가능 → **Release Blocker** |
| `CURRENT_STATE_MISMATCH` | 스냅샷과 현재 remote 상태 불일치 (예: DB=`wait`, 조회=`cancel`) |
| `HISTORICAL_STALE_CONFLICT` | 종료 주문(done/cancel) 이력, 현재 Open=0이면 비차단 가능 |
| `TEST_OR_NON_LIVE_ARTIFACT` | Paper/테스트 데이터 |
| `DUPLICATE_OR_ORPHAN` | 중복·고아 (자동 삭제 금지) |
| `UNCLASSIFIED` | 안전 분류 불가 → **Release Blocker** |

구현: `stock_platform.trading.step8_12a_conflict_classifier`  
스크립트: `scripts/step8_12a_final_preflight.py`

## 4. Release Blocker 기준

다음이 있으면 `BLOCKED`:

- `CURRENT_ACTIVE_CONFLICT` / `UNCLASSIFIED`
- Broker 또는 DB Open Orders > 0
- Account Trading Pause ON
- Credential ≠ VERIFIED, UPBIT_USE_MOCK=true
- Global/UBA Kill Switch ON
- Dashboard에서 Recovery Actual ∉ {RUNNING, COOLDOWN}
- Broker 상태 조회 실패
- Orderable KRW < 5,100

`HISTORICAL_STALE` / (원격 종료 확정된) `STATE_MISMATCH`만 있고 Open=0·Pause OFF면 Conflict만으로는 비차단 가능.  
**자동 승인·무시·삭제는 하지 않는다.**

## 5. Market 후보 확인

Allowlist만: `KRW-BTC`, `KRW-ETH`, `KRW-XRP`.

```powershell
.venv\Scripts\python scripts\step8_12a_final_preflight.py --uba-id 58 --amount 5000
```

보고의 `market_candidates`는 **후보 비교표**이다.  
`system_suggested_market_for_pipeline_only`는 파이프라인 검증용 참고이며 **자동 확정이 아니다**.

## 6. Limit Price 확정 방법

운영자가 Market과 Limit Price를 **직접** 정한다.  
각 Market의 `limit_candidates` 라벨:

1. `best_bid`
2. `best_ask`
3. `best_ask_plus_1_tick`
4. `trade_price_normalized`

요청가 → Broker tick **effective_price**를 함께 확인한다. `price_adjusted=true`면 재확인 필수.

## 7. Tick Size 처리

`upbit_tick_size` / `round_upbit_price` / `round_upbit_volume` 사용.  
최소 주문금액: `UPBIT_MIN_NOTIONAL_KRW`.

## 8. Dry-run 실행 방법

Market/Price 미확정 시:

- `dry_run_executed=false`
- `reason=OPERATOR_MARKET_PRICE_REQUIRED`

운영자 확정 후:

```powershell
.venv\Scripts\python scripts\step8_12a_final_preflight.py `
  --uba-id 58 --amount 5000 `
  --market <운영자_MARKET> `
  --limit-price <운영자_PRICE>
```

`execute_live` 없음. Adapter `create_order` 호출 0회여야 한다.

## 9. Dry-run 결과 판정

- `dry_run_ready=true` + blockers 없음 → Dry-run PASS
- `live_execution_ready=false`(LIVE OFF/ARM OFF)는 **정상**이며 Dry-run 실패가 아님

## 10. READY_FOR_OPERATOR_APPROVAL 의미

사전검증 게이트를 통과했다는 뜻이다.  
**실주문 승인·실행 허가가 아니다.** STEP 8-12B와 운영자 승인 게이트가 별도로 필요하다.

## 11. 운영자 승인 전 중단 원칙

본 STEP 완료 보고 후 반드시 중단한다.  
승인 문구 생성·대행 입력·실주문 명령 생성 금지.

## 12. STEP 8-12B와의 분리

| STEP | 내용 |
|------|------|
| 8-12A | Conflict 분류, 후보, Dry-run(조건부), 판정 |
| 8-12B | 운영자 승인 후 LIVE/ARM/실주문 (별도 승인) |

## 13. 장애 시 확인 순서

1. `release_blockers` / Account Pause / Open Orders  
2. Credential / Broker Health / Kill Switch  
3. Recovery Scheduler (Dashboard) / Trading PAUSED  
4. Conflict 분류 샘플 (`CURRENT_ACTIVE` 우선)  
5. Market 시세 stale / Tick 조정  
6. Orderable KRW·Daily Loss  

## 14. 민감정보 처리

- Order UUID는 마스킹 (`abcd…xyz1`)
- Credential·ARM Token·API Key 원문 금지
- 보고서·로그에 Secret 미출력

## 15. 실제 주문 미실행 확인

스크립트 필드:

- `execute_live=false`
- `arm_attempted=false`
- `live_on_attempted=false`
- `adapter_create_order_calls=0`
- `conflict_mutations=0`
- `approve_import_calls=0` / `ignore_calls=0`
