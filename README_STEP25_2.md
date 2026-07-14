# STEP25-2 APScheduler 자동 실행

STEP25-1에 등록한 작업을 평일 지정 시간에 자동 실행합니다.

## 기본 실행 시간

```text
후보선정       평일 16:10
AI 분석        평일 16:30
포지션 계획    평일 17:00
```

시간대는 `Asia/Seoul`입니다.

## 설치 패키지

```powershell
python -m pip install APScheduler
```

`requirements.txt`에도 추가합니다.

```text
APScheduler
```

## 환경설정

`E:\StockTrading\secrets\stock-platform.env`에 필요 시 추가합니다.

```dotenv
SCHEDULER_ENABLED=true
SCHEDULER_TIMEZONE=Asia/Seoul

SCHEDULER_CANDIDATE_HOUR=16
SCHEDULER_CANDIDATE_MINUTE=10

SCHEDULER_AI_HOUR=16
SCHEDULER_AI_MINUTE=30

SCHEDULER_POSITION_HOUR=17
SCHEDULER_POSITION_MINUTE=0

SCHEDULER_EXCHANGE_CODE=KRX
SCHEDULER_CANDIDATE_LIMIT=30
SCHEDULER_MINIMUM_SCORE=50
SCHEDULER_AI_LIMIT=10
SCHEDULER_POSITION_LIMIT=5
SCHEDULER_POLICY_ID=1
SCHEDULER_PORTFOLIO_VALUE=10000000
SCHEDULER_AVAILABLE_CASH=5000000
SCHEDULER_MINIMUM_AI_SCORE=70
SCHEDULER_MINIMUM_CONFIDENCE=0.5
```

## 직접 실행

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1

python scripts\run_scheduler.py
```

종료는 `Ctrl + C`입니다.

## 작업 하나 즉시 실행

```powershell
python scripts\run_scheduler_job.py candidate_screening
python scripts\run_scheduler_job.py ai_orchestration
python scripts\run_scheduler_job.py position_planning
```

## Swagger 즉시 실행 API

```text
POST /api/v1/scheduler-admin/run-now/candidate_screening
POST /api/v1/scheduler-admin/run-now/ai_orchestration
POST /api/v1/scheduler-admin/run-now/position_planning
```

## Windows 시작 시 자동 실행

관리자 PowerShell에서:

```powershell
cd D:\Projects\stock-platform

powershell -ExecutionPolicy Bypass `
    -File scripts\install_scheduler_task.ps1
```

등록 확인:

```powershell
Get-ScheduledTask -TaskName StockPlatformScheduler
```

수동 시작:

```powershell
Start-ScheduledTask -TaskName StockPlatformScheduler
```

작업 삭제:

```powershell
powershell -ExecutionPolicy Bypass `
    -File scripts\uninstall_scheduler_task.ps1
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_automatic_scheduler.py `
    -q
```

## 주의

- 스케줄러 프로세스는 한 개만 실행하세요.
- FastAPI 서버와 스케줄러는 별도 프로세스로 운영합니다.
- 자동 주문이 아니라 후보선정·AI 분석·포지션 계획만 실행합니다.
- 실제 주문 전송은 아직 구현하지 않았습니다.
- `policy_id=1` 정책이 DB에 존재해야 포지션 계획이 성공합니다.
- 공휴일 여부는 아직 판단하지 않고 월요일~금요일만 실행합니다.

## Git 커밋

```powershell
git add `
    README_STEP25_2.md `
    requirements.txt `
    src\stock_platform\common\settings.py `
    src\stock_platform\scheduler\automatic.py `
    src\stock_platform\api\v1\scheduler_admin.py `
    src\stock_platform\api\router.py `
    scripts\run_scheduler.py `
    scripts\run_scheduler_job.py `
    scripts\install_scheduler_task.ps1 `
    scripts\uninstall_scheduler_task.ps1 `
    tests\test_automatic_scheduler.py

git commit -m "feat(operation): schedule daily strategy jobs"
```

다음 단계는 STEP25-3 일일 운영 파이프라인과 실패 시 재시도·의존성 제어입니다.
