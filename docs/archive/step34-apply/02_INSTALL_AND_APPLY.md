# STEP34 설치 및 적용 명령어

> **아카이브** — 현재 설치 절차는 [../../INSTALL.md](../../INSTALL.md) 를 사용하세요.  
> 목차: [../../README.md](../../README.md)

## 전체 명령 흐름

```powershell
cd D:\Projects\stock-platform
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1

pip install -r requirements_step34.txt
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

alembic heads
alembic current
```

이 시점에서 `alembic\versions\20260717_03_indicator.py`의 `down_revision`을 수정합니다.

그 다음:

```powershell
alembic upgrade head
pytest -q tests\step34
uvicorn stock_platform.api.main:app --reload --app-dir src
```

## 실패 시 되돌리기

Migration만 되돌리기:

```powershell
alembic downgrade -1
```

아직 커밋하지 않은 파일 변경 되돌리기:

```powershell
git status
git restore .
git clean -fd
```

`git clean -fd`는 신규 파일을 삭제하므로 `git status`를 먼저 확인하십시오.
