# RC22 Database Restore Verification

## 실행 방법 (DBA)

```powershell
$env:PGPASSWORD_ADMIN = "<superuser password>"  # 출력·커밋 금지
$env:PGUSER_ADMIN = "postgres"
python scripts/rc22_db_verify.py empty-upgrade
python scripts/rc22_db_verify.py restore
```

검증 DB 접두사만 허용:

- `stock_platform_rc_verify_*`
- `stock_platform_restore_verify_*`

운영 DB(`stock_platform` 등) 삭제/초기화 **Fail Closed**.

## Backup 재검증 (실행됨)

| 항목 | 값 |
|------|-----|
| file | `stock_rc21_20260726_092023.dump` |
| sha256 | `739271404934a5eac23feb0238c48e6d45a8e01d52ab2b57b92d701efdbe9674` |
| match | **True** |
| size | 17711041 |

## 2026-07-26 실행 상태

| 단계 | 결과 |
|------|------|
| Checksum | **PASS** |
| empty-upgrade | **PASS** (Head `j3d4e5f6a7b8`) |
| Official Restore | **PASS** (`pg_restore_exit=0`, row count match) |
| Restore Row Compare | `auth.user` 2/2, `paper_account` 7/7 등 |
| DB Release Blocker | **0** |

행 수 비교: `scripts/rc22_db_verify.py` (`auth.user` + Identifier quoting)  
문서: [../development/README_STEP8_5_22_DBA_RESTORE_AUTH_TABLE_FIX.md](../development/README_STEP8_5_22_DBA_RESTORE_AUTH_TABLE_FIX.md)

결과 디렉터리: `E:\StockTrading\backups\verification`

> `PGPASSWORD_ADMIN`은 검증 실행 시에만 사용하며 상시 보관하지 않는다.
