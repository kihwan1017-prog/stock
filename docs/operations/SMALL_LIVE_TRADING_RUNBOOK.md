# Small LIVE Trading Runbook

**전제:** Official Restore PASS · DB Release Blocker 0 · 소액 LIVE **APPROVED** (로컬/VPN). 공개망은 범위 제외.

## DBA (완료됨 — 재검증 시)

1. 필요 시에만 `PGPASSWORD_ADMIN` 설정 후 `python scripts/rc22_db_verify.py empty-upgrade`
2. `python scripts/rc22_db_verify.py restore`
3. 결과 JSON이 `E:\StockTrading\backups\verification` 에 PASS
4. 검증 후 `Remove-Item Env:PGPASSWORD_ADMIN` (상시 보관 금지)

## 운영 리허설

```powershell
python scripts/run_operation_rehearsal.py --full --telegram=dry-run
```

## 그 다음

1. Paper 스모크 / Operation Rehearsal PASS
2. Activation Gate (TTL 필수)
3. Dry Run
4. 소액 1건 (로컬/VPN)
