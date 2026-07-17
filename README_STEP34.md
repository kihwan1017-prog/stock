# STEP34 목적

이번 STEP에서는 아래 기능을 추가합니다.

- SMA
- EMA
- RSI
- Indicator 모델
- Screening Service
- Indicator API
- indicator 테이블
- pytest

---

# 작업 순서

반드시 아래 순서대로 진행하세요.

```
1. 프로젝트 백업
2. STEP34 파일 복사
3. Python 패키지 설치
4. Alembic 수정
5. Migration 실행
6. main.py 수정
7. 테스트
8. 서버 실행
9. Swagger 확인
10. Git Commit
```

---

# 1. 프로젝트 백업

```powershell
cd D:\Projects\stock-platform

git status

git add .

git commit -m "backup before step34"
```

---

# 2. STEP34 파일 복사

압축을 풀면 아래 구조가 있습니다.

```
README_STEP34

src/
alembic/
tests/
requirements_step34.txt
```

복사합니다.

```
README_STEP34/src
↓

D:\Projects\stock-platform\src
```

```
README_STEP34/alembic
↓

D:\Projects\stock-platform\alembic
```

```
README_STEP34/tests
↓

D:\Projects\stock-platform\tests
```

```
README_STEP34/requirements_step34.txt
↓

D:\Projects\stock-platform
```

복사가 끝나면 아래 파일이 존재해야 합니다.

```
src/stock_platform/indicator/models.py

src/stock_platform/indicator/calculator.py

src/stock_platform/screener/service.py

src/stock_platform/api/v1/indicator_router.py

alembic/versions/20260717_03_indicator.py
```

---

# 3. 패키지 설치

```powershell
cd D:\Projects\stock-platform

.\.venv\Scripts\Activate.ps1

pip install -r requirements_step34.txt
```

설치 확인

```powershell
pip show fastapi

pip show sqlalchemy

pip show alembic
```

---

# 4. Alembic 수정

파일

```
alembic/versions/20260717_03_indicator.py
```

현재

```python
down_revision = "REPLACE_WITH_CURRENT_REVISION"
```

현재 프로젝트 마지막 Revision으로 변경

예)

```python
down_revision = "20260717_02"
```

Revision 확인

```powershell
alembic heads
```

---

# 5. Migration 실행

```powershell
alembic upgrade head
```

정상 확인

```powershell
alembic current
```

---

# 6. main.py 수정

파일

```
src/stock_platform/api/main.py
```

Import 추가

```python
from stock_platform.api.v1.indicator_router import router as indicator_router
```

Router 등록

```python
app.include_router(indicator_router)
```

---

# 7. 테스트

```powershell
$env:PYTHONPATH="D:\Projects\stock-platform\src"

pytest -q tests\step34
```

성공 결과

```
2 passed
```

---

# 8. 서버 실행

```powershell
uvicorn stock_platform.api.main:app --reload --app-dir src
```

---

# 9. Swagger 확인

브라우저

```
http://127.0.0.1:8000/docs
```

아래 API가 보여야 합니다.

```
GET

/api/v1/indicator/health

GET

/api/v1/indicator/screen
```

---

# 10. API 테스트

PowerShell

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/indicator/health
```

정상 결과

```
status
------
ok
```

---

# 11. 완료 확인

아래 항목이 모두 완료되어야 STEP34가 끝난 것입니다.

```
☑ 파일 복사 완료

☑ requirements 설치

☑ Alembic 수정

☑ Migration 성공

☑ indicator 테이블 생성

☑ main.py 수정

☑ 테스트 성공

☑ 서버 실행

☑ Swagger 확인

☑ API 확인
```

---

# 12. Git Commit

```powershell
git add .

git commit -m "feat(step34): indicator engine"
```

---

# STEP34 완료

다음 STEP35부터 진행합니다.