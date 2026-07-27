# STEP 9-2 — UPBIT 5,000원 주문 Dry Run

## 1. 목적

실제 Broker 주문·DB trading_order 없이 5,000원 Market BUY 요청이 생성 직전까지 검증되는지 확인한다.

## 2. 실제 주문과 차이

| | Dry Run | Live |
|--|---------|------|
| LIVE/ARM | OFF 유지 | 별도 승인 |
| Adapter submit | 0 | 1 |
| trading_order | 0 | 생성 |
| Audit | ORDER_DRY_RUN_VALIDATED | 실주문 Audit |

## 3. 사전 조건

Pause OFF, Recovery RUNNING, ACTIVE_REVIEW=0, Open=0, Kill INACTIVE, Credential VERIFIED, Trading Scheduler PAUSED, LIVE/ARM OFF.

## 4. 마켓 Allowlist

`--market` 필수. 기본 후보 `KRW-BTC`. Allowlist 외·자동 대체 금지.

## 5. 금액 입력

`requested_order_amount=5000` KRW.

## 6. 수수료 계산 (코드 증명)

- **Adapter A**: Market BUY `ord_type=price`, `price=KRW 금액`. 수수료는 거래소 별도. (`order_mapper.py`)
- **B 미사용**
- **C**: 가용 KRW 여유 버퍼 `amount*(1+fee)`는 운영 Preflight 추정용 — Broker body 미포함

## 7. 최소 주문금액

`UPBIT_MIN_NOTIONAL_KRW=5000`

## 8. Decimal·반올림

수량/가격 ROUND_DOWN. 수수료 `quantize(0.0001)`.

## 9. Daily Loss

raw `16888.04` / remaining `283111.96`. 정수 표시 ROUND_DOWN 시 1원 차이 → **ROUND_DOWN** (계산 오류 아님).

## 10–12. Risk / Broker / DB

Preflight `purpose=dry_run` → LIVE/ARM EXPECTED_OFF. create_order/submit/order insert=0.

## 13. Audit

`ORDER_DRY_RUN_VALIDATED` (실주문 Audit와 분리).

## 14. 민감정보

Access/Secret/서명/전체 UUID 금지. identifier 마스킹.

## 15. 실패 시

BLOCKED_DEFECT/ERROR면 STEP 9-3 금지. 원인 코드 확인 후 재검증.

## 16. STEP 9-3 인계

Dry Run PASS + LIVE OFF + Scheduler PAUSED + Open=0 유지. LIVE/ARM/실주문은 별도 승인.

스크립트: `scripts/step9_2_upbit_5000_dry_run.py --market KRW-BTC`
