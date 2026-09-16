# Upbit 소액 LIVE 검증 Runbook

업비트 실계좌에서 **지정가 소액 1건**만 수동 검증하기 위한 운영 절차입니다.  
키움 실계좌·자동 전략·Scheduler 자동주문은 범위 밖입니다.

## 절대 원칙

- 기본은 DRY-RUN
- 실주문은 `--execute-live` + `--confirmation-text UPBIT-LIVE-ONE-ORDER` + `--arm-token` 모두 있을 때만
- 시장가 금지 / 다중 주문 금지 / 최대 10,000원
- 실행 후 즉시 DISARM + LIVE OFF (자동 Resume 금지)
- Outbox Pending ≠ Broker Accepted / Cancel Requested ≠ Canceled
- Fail Closed · 기존 Safety Pipeline 우회 금지

## 사전 준비

0. **STEP 8-9B 운영 점검** — 실주문 전 조회 전용 점검

```powershell
.venv\Scripts\python scripts\run_upbit_live_ops_preflight.py --amount 5000
```

보고서: `docs/operations/reports/UPBIT_LIVE_PREFLIGHT_<timestamp>.md`

1. **사전 백업** — DB dump, 설정 스냅샷
2. **운영 DB 확인** — Alembic head `o4e5f6a7b8c9` (`live_validation_run` tracking columns)
3. **대상 UBA 확인** — `broker_code=UPBIT`, active, 본인 소유 1개만
4. **Credential Verify** — Vault 복호화·인증 API 성공
5. **모든 계좌 LIVE OFF 확인** — 대상 외 LIVE ON 금지
6. **대상 UBA만 LIVE ON**
7. **Risk Limit ≤ 10,000원** — 계좌/사용자/시스템 effective min
8. **Scheduler Pause** — 해당 UBA 자동주문 OFF (거래 Scheduler)
9. **Runtime Pause** — 해당 UBA Strategy Runtime Pause
10. **Open Order 0 확인**
11. **Kill Switch OFF 확인**
12. **Telegram 확인** — dry-run 또는 live publisher
13. **ARM** — Admin ARM + one-time `arm_token` (로그/저장 금지)
14. **Broker Tracker** — `upbit_live_track` Scheduler 기동 (거래 Scheduler와 분리)

## Dry-run (Windows PowerShell)

```powershell
python scripts/run_upbit_live_smoke_test.py `
  --uba-id <UBA_ID> `
  --market KRW-XRP `
  --side BUY `
  --amount 5000 `
  --limit-price <PRICE> `
  --dry-run
```

15. Dry-run 실행
16. Preflight 결과 `ready=true`, Blocker 0 확인

Admin UI: `/admin/live-validation/upbit`

## 실주문 (별도 승인 후, PowerShell)

```powershell
python scripts/run_upbit_live_smoke_test.py `
  --uba-id <UBA_ID> `
  --market KRW-XRP `
  --side BUY `
  --amount 5000 `
  --limit-price <PRICE> `
  --execute-live `
  --confirmation-text "UPBIT-LIVE-ONE-ORDER" `
  --arm-token <ONE_TIME_TOKEN>
```

17. CLI에서 `internal_status` / `broker_order_status` 구분 확인  
    (`OUTBOX_PENDING`을 Accepted로 보지 말 것)
18. Broker UUID 확보 및 조회 확정 (ACCEPTED/OPEN/FILLED/…)
19. 미체결 시 자동 취소 → `CANCEL_PENDING` → Broker 재조회로 `CANCELED` 확정
20. 체결 시 Post-fill `VERIFIED` (WAITING_SNAPSHOT은 성공 아님)
21. **DISARM** / **LIVE OFF** 확인
22. 거래 Scheduler / Runtime Pause **유지** (Tracker는 미확정 주문 계속 조회 가능)
23. Audit / Telegram (Outbox 생성만으로 접수 알림 없음)
24. DB 백업

## Linux / macOS (참고)

```bash
python scripts/run_upbit_live_smoke_test.py \
  --uba-id <UBA_ID> \
  --market KRW-XRP \
  --side BUY \
  --amount 5000 \
  --limit-price <PRICE> \
  --dry-run
```

## 장애 대응

25. **UNKNOWN** — Broker 수동 조회, 추가 주문 금지, Manual Review
26. **취소 실패** — Kill Switch + LIVE OFF + Pause 유지
27. **수동 Kill Switch** — Admin Risk API

## 설정

| Key | 기본 |
|-----|------|
| `UPBIT_LIVE_PREFLIGHT_TTL_SECONDS` | 30 |
| `UPBIT_LIVE_SMOKE_ALLOWLIST` | KRW-BTC,KRW-ETH,KRW-XRP |
| `UPBIT_LIVE_SMOKE_ORDER_WATCH_SECONDS` | 60 |
| `UPBIT_LIVE_SMOKE_AUTO_CANCEL` | true |
| `UPBIT_LIVE_TRACK_ENABLED` | true |
| `UPBIT_LIVE_TRACK_POLL_SECONDS` | 2 |
| `UPBIT_LIVE_TRACK_RETRY_DELAYS_SECONDS` | 1,2,5,10,20 |
| `UPBIT_LIVE_TRACK_MAX_ATTEMPTS` | 8 |

## 관련

- Tracking: `trading/upbit_live_tracking_service.py`
- Scheduler: `trading/upbit_live_tracking_scheduler.py`
- CLI: `scripts/run_upbit_live_smoke_test.py`
- STEP: `docs/development/README_STEP8_9_UPBIT_LIVE_SMOKE.md`
