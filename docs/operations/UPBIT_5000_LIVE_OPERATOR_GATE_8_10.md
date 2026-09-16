# STEP 8-10 — 업비트 5,000원 LIVE 1건 운영자 승인 실행 절차

운영자가 **명시 승인**하기 전까지 실주문·LIVE ON·ARM을 수행하지 않는다.  
Cursor AI는 사전점검·명령 생성·실행 후 확인 절차 준비만 한다.

## 절대 금지

- 승인 전 `--execute-live` / LIVE ON / ARM
- Market 주문, 5,000원 초과, 2건 이상, 재전송
- Risk·Daily Loss 한도 변경, Trading Scheduler Resume
- Credential / `arm_token` 평문 로그·보고서 출력
- 종목·지정가 AI 자동 확정

## 1. 조회 전용 Preflight

```powershell
.venv\Scripts\python scripts\step8_10_preflight_readonly.py
```

또는 기존 운영 점검:

```powershell
.venv\Scripts\python scripts\run_upbit_live_ops_preflight.py --amount 5000 --uba-id 58 --actor STEP8_10_OPS
```

실패(조회 불가·Kill Switch·미체결·Credential 비정상·**KRW 주문가능잔고 < 5,000**) 시 **즉시 중단**.

참고: Upbit `balance − locked`가 주문가능 금액이다. Snapshot 예수금과 다를 수 있으므로 **Broker private `/accounts`를 우선**한다.

## 2. 종목·가격 (운영자 확정)

- 기본 **후보**만 표시 가능: `KRW-XRP` (자동 확정 금지)
- 운영자가 확정: `Market`, `Limit Price`, 실행 여부
- 요청가와 Broker tick **유효가**를 함께 확인
- 가격이 자동 조정되면 운영자 **재확인** 필수

## 3. 최종 Dry-run (운영자 선택가)

```powershell
.venv\Scripts\python scripts\run_upbit_live_smoke_test.py `
  --uba-id 58 `
  --market <운영자_확정_MARKET> `
  --side BUY `
  --amount 5000 `
  --limit-price <운영자_확정가격> `
  --dry-run
```

목표: `dry_run_ready=true`, `blockers=[]`, Adapter `create_order=0`, TICKER/ORDERBOOK/SLIPPAGE PASS.

## 4. 운영자 승인 게이트

다음 **문구가 운영자 채팅에 그대로** 입력된 경우에만 5단계 명령을 생성한다.

```text
UPBIT 5000원 LIVE 1건 실행 승인
```

- AI가 이 문구를 대신 입력·생성하지 않는다.
- 문구 없거나 다르면 **중단**.

## 5. LIVE ON → ARM (Admin API만)

승인 + Dry-run PASS 후, Admin UI 또는 API:

1. `PUT /api/v1/admin/live-order/accounts/58`  
   body: `{ "live_order_enabled": true }`
2. `POST /api/v1/admin/live-order/accounts/58/arm`  
   body: `{ "ttl_seconds": <정책값> }`
3. 응답의 `arm_token`은 **화면 1회만** 표시 (로그/Telegram/완료보고 금지)
4. ARM TTL·만료시각 확인

LIVE ON 또는 ARM 실패 시 실주문 명령을 **생성하지 않음**.

## 6. 실주문 명령 (AI 미실행 — 운영자만 실행)

```powershell
.venv\Scripts\python scripts\run_upbit_live_smoke_test.py `
  --uba-id 58 `
  --market <운영자_확정_MARKET> `
  --side BUY `
  --amount 5000 `
  --limit-price <운영자_확정가격> `
  --execute-live `
  --confirmation-text "UPBIT-LIVE-ONE-ORDER" `
  --arm-token <ONE_TIME_TOKEN>
```

## 7. 실행 후 자동 안전 경로 (기존 스모크)

주문 최대 1회 → Broker UUID → 조회 → 관찰 만료/부분체결 시 잔량 취소 → Post-fill →  
UNKNOWN/취소실패 시 Kill Switch → **finally DISARM + LIVE OFF** → Runtime/Trading Pause 유지.

## 8. 실행 직후 확인

```powershell
.venv\Scripts\python scripts\step8_10_post_execution_verify.py --uba-id 58 --run-id <RUN_ID>
```

확인 항목: run_id, internal/broker 상태, UUID 마스킹, 체결·수수료·잔량·취소, Post-fill,  
daily loss, Kill Switch, LIVE OFF, DISARM, Scheduler, Audit, Telegram, Manual Review.

## 9. 실패 시

`SUBMISSION_UNKNOWN` / `UNKNOWN` / 취소 실패 / Post-fill MISMATCH·EXPIRED·FAILED 등 →  
성공 처리 금지. Kill Switch + LIVE OFF + DISARM + 추가 주문 금지 + Manual Review + Telegram 긴급.
