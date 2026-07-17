# STEP34 사용자 작업 체크리스트

아래 항목을 위에서부터 순서대로 실행하십시오.

## 1. 프로젝트 폴더로 이동

```powershell
cd D:\Projects\stock-platform
```

## 2. 현재 작업 백업

```powershell
git status
git add .
git commit -m "backup before step34"
```

변경 사항이 없어 커밋되지 않는 경우 그대로 다음 단계로 진행합니다.

## 3. 가상환경 활성화

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

확인:

```powershell
python --version
where.exe python
```

`D:\Projects\stock-platform\.venv\Scripts\python.exe`가 표시되어야 합니다.

## 4. STEP34 파일 복사

ZIP을 예를 들어 `D:\Temp\README_STEP34_REVISED`에 해제한 뒤 실행합니다.

```powershell
$source = "D:\Temp\README_STEP34_REVISED"
$target = "D:\Projects\stock-platform"

Copy-Item "$source\src\*" "$target\src" -Recurse -Force
Copy-Item "$source\alembic\*" "$target\alembic" -Recurse -Force
Copy-Item "$source\tests\*" "$target\tests" -Recurse -Force
Copy-Item "$source\requirements_step34.txt" "$target\requirements_step34.txt" -Force
```

복사 확인:

```powershell
Test-Path D:\Projects\stock-platform\src\stock_platform\indicator\calculator.py
Test-Path D:\Projects\stock-platform\src\stock_platform\api\v1\indicator_router.py
Test-Path D:\Projects\stock-platform\alembic\versions\20260717_03_indicator.py
Test-Path D:\Projects\stock-platform\tests\step34\test_indicator.py
```

모두 `True`가 나와야 합니다.

## 5. 패키지 설치

```powershell
cd D:\Projects\stock-platform
pip install -r requirements_step34.txt
```

## 6. Alembic 최신 Revision 확인

```powershell
alembic heads
alembic current
alembic history
```

## 7. Migration 파일 수정

수정 파일:

```text
D:\Projects\stock-platform\alembic\versions\20260717_03_indicator.py
```

수정 전:

```python
down_revision = "REPLACE_WITH_CURRENT_REVISION"
```

수정 후 예시:

```python
down_revision = "20260717_02"
```

위 값은 예시입니다. 반드시 `alembic heads` 결과를 사용하십시오.

## 8. Migration 실행

```powershell
alembic upgrade head
alembic current
```

DB 확인:

```powershell
psql -U stock_app -d stock_platform
```

```sql
SELECT table_schema, table_name
  FROM information_schema.tables
 WHERE table_schema = 'market'
   AND table_name = 'indicator';

\d market.indicator
```

## 9. Router 등록

수정 파일:

```text
D:\Projects\stock-platform\src\stock_platform\api\main.py
```

추가:

```python
from stock_platform.api.v1.indicator_router import router as indicator_router
app.include_router(indicator_router)
```

기존 프로젝트가 `api/v1/router.py`에서 하위 Router를 모으는 구조라면 그 파일에 등록하고 `main.py`에는 중복 등록하지 않습니다.

## 10. 테스트 실행

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
pytest -q tests\step34
```

## 11. 서버 실행

```powershell
uvicorn stock_platform.api.main:app --reload --app-dir src
```

## 12. API 확인

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/indicator/health
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

## 13. 완료 커밋

```powershell
git add .
git commit -m "feat(step34): add indicator engine and screening foundation"
```

# 완료 기준

- [ ] 파일 복사 완료
- [ ] requirements 설치 완료
- [ ] `down_revision` 수정 완료
- [ ] Migration 성공
- [ ] `market.indicator` 생성 확인
- [ ] Router 등록 완료
- [ ] STEP34 테스트 성공
- [ ] 서버 실행 성공
- [ ] Swagger/API 확인
- [ ] Git 커밋 완료
