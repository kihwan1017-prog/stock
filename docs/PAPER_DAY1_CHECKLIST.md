# 모의 첫날 체크리스트 (15분)

목표: **실전 없이** 서버가 정상인지 확인하고, 모의 운영 루틴을 한 바퀴 도는 것.

## 0. 사전 확인 (이미 통과됨)

- Alembic head: `a2b3c4d5e6f7`
- `KIWOOM_LIVE_ORDER_ENABLED=false`
- `KIWOOM_USE_MOCK=true`
- `ADMIN_API_KEY` 비어 있음 → 로컬은 관리 API 통과(운영 전 반드시 설정)

## 1. 서버 기동

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
.\.venv\Scripts\uvicorn.exe stock_platform.api.main:app --host 127.0.0.1 --port 8000
```

## 2. 브라우저/호출 확인

1. http://127.0.0.1:8000/docs
2. http://127.0.0.1:8000/health → `status`가 `UP` 또는 `DEGRADED`(Ollama 미기동 시 DEGRADED 가능)
3. http://127.0.0.1:8000/api/v1/system/dashboard
4. http://127.0.0.1:8000/api/v1/risk/kill-switch

## 3. 모의 루틴 1회

PowerShell 예시:

```powershell
# Health
Invoke-RestMethod http://127.0.0.1:8000/health | ConvertTo-Json -Depth 5

# Dashboard
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/system/dashboard?account_id=1&exchange_code=KRX" | ConvertTo-Json -Depth 4

# 키움 계좌상태 sync (mock 가능) — 일손실 모니터가 snapshot을 쓰려면 필요
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/broker/kiwoom/account-state/sync | ConvertTo-Json -Depth 4
```

로그에 `strategy_runtime_reload_skipped` / `daily_loss_monitor_skipped` 가 **한 번**만 보이면 정상입니다.
(활성 전략 배포·계좌 스냅샷이 아직 없을 때). `Active strategy deployment not found` traceback이 30초마다 반복되면 서버를 재시작해 최신 코드를 반영하세요.

전략 자동매매까지는 **활성 PAPER 배포**가 DB에 있어야 합니다. Day-1에서는 배포 없이 API/헬스만 확인해도 됩니다.

## 4. 오늘 보면 되는 것

- [ ] DB = UP
- [ ] live_trading = DISABLED
- [ ] Kill Switch 상태 확인
- [ ] dashboard에 에러 폭주 없음
- [ ] (가능하면) 계좌 sync 한 번 — 이후 daily_loss skip 해소

## 5. 하지 말 것

- `KIWOOM_LIVE_ORDER_ENABLED=true` 로 바꾸지 않기
- live-transition approve 하지 않기
- 실계좌 대량 주문 테스트하지 않기

## 다음 날부터

[OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md)의 일일 점검 5단계만 반복하면 됩니다.
