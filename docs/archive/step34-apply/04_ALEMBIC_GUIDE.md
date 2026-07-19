# Alembic 적용 가이드

> **아카이브** — 현재 Alembic 규칙은  
> [../../development/DB_DEVELOPMENT_RULES.md](../../development/DB_DEVELOPMENT_RULES.md) ·  
> [../../development/ALEMBIC_VERIFY.md](../../development/ALEMBIC_VERIFY.md) 를 사용하세요.  
> Canonical path: `database/alembic/versions/`

## 최신 Revision 확인

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
alembic heads
```

예:

```text
20260717_02 (head)
```

## STEP34 Migration 수정

수정 전:

```python
revision = "20260717_03"
down_revision = "REPLACE_WITH_CURRENT_REVISION"
```

수정 후 예시:

```python
revision = "20260717_03"
down_revision = "20260717_02"
```

실제 `alembic heads` 결과를 넣으십시오.

## 중복 Revision 주의

이미 `20260717_03`이 존재한다면 revision과 파일명을 함께 변경합니다.

예:

```python
revision = "20260717_03_step34"
```

파일명:

```text
20260717_03_step34_indicator.py
```

## Migration 실행

```powershell
alembic upgrade head
```

## 오류 확인

```powershell
alembic history
alembic heads
alembic current
```

`market` 스키마가 없다는 오류가 나면 DB에서 확인합니다.

```sql
CREATE SCHEMA IF NOT EXISTS market AUTHORIZATION stock_app;
```
