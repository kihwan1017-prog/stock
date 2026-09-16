# STEP 8-5-22-DBA-RESTORE-AUTH-TABLE-FINAL-FIX

## 원인

Restore 행 수 비교가 `auth.user`(실제 테이블)를 SQL 키워드 충돌 없이 조회하지 못하거나, 과거 잘못된 `auth.users` 대상으로 `NA`/`RESTORE_PARTIAL`이 발생했다.

## 수정

- 비교 대상: `auth.user` (`COMPARE_TABLES`)
- `psycopg.sql.Identifier` 로 `"auth"."user"` COUNT
- 오류 구분: `table_not_found` / `permission_denied` / `query_failed` / `connection_failed` / `count_mismatch`
- 불일치·오류 시 Fail Closed (`RESTORE_PARTIAL` + exit 8)
- 보고서 필드: `source_exists`, `restored_exists`, `source_count`, `restored_count`, `match`, `error`

## 재실행

```powershell
$env:PGPASSWORD_ADMIN = '<admin password>'
python scripts/rc22_db_verify.py restore
Remove-Item Env:PGPASSWORD_ADMIN
```
