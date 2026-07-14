# STEP27-7 실시간 운영 상태 통합 대시보드 API

자동매매 플랫폼의 주요 운영 상태를 하나의 API에서 조회합니다.

## API

```text
GET /api/v1/system/dashboard
```

선택 파라미터:

```text
account_id
recent_limit
```

예:

```text
GET /api/v1/system/dashboard?account_id=1&recent_limit=20
```

## 조회 항목

### 애플리케이션

```text
앱 이름
실행 환경
시간대
조회 시각
```

### 인프라

```text
PostgreSQL 연결 상태
Ollama URL
Ollama 모델
실시간 세션 스케줄러 상태
등록 작업과 다음 실행 시각
```

### 실시간 엔진

```text
실시간 시세 클라이언트
최신 시세 캐시
시세 구독자 수
전략 실행기 상태
신호 처리 수
주문 실행기 상태
실행·차단·실패 주문 수
일일 손실 누적값
```

### 모의 계좌

```text
현금 잔액
실현손익
보유 종목 수
포지션 원가 합계
```

포지션 원가 합계는 현재가 평가금액이 아니라
`수량 × 평균매입가`입니다.

### 주문·체결

```text
금일 주문 수
금일 체결 수
최근 주문
최근 체결
```

### AI

```text
Ollama 모델
최근 AI 관련 작업 상태
최근 AI 오류
```

### 오류

```text
최근 FAILED 작업
실시간 전략 최근 오류
실시간 주문 최근 오류
```

## 적용 파일

```text
src/stock_platform/realtime/dashboard_models.py
src/stock_platform/realtime/dashboard_service.py
src/stock_platform/realtime/__init__.py
src/stock_platform/api/v1/system_dashboard.py
tests/test_realtime_dashboard_service.py
README_STEP27_7.md
```

신규 테이블은 없어 Alembic 작업은 필요 없습니다.

## router.py 추가

```python
from stock_platform.api.v1.system_dashboard import (
    router as system_dashboard_router,
)
```

```python
api_router.include_router(
    system_dashboard_router
)
```

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_realtime_dashboard_service.py `
    -q
```

## Swagger 확인

```powershell
uvicorn stock_platform.api.main:app `
    --app-dir src `
    --reload
```

브라우저:

```text
http://127.0.0.1:8000/docs
```

## Git 커밋

```powershell
git add `
    README_STEP27_7.md `
    src\stock_platform\realtime\dashboard_models.py `
    src\stock_platform\realtime\dashboard_service.py `
    src\stock_platform\realtime\__init__.py `
    src\stock_platform\api\v1\system_dashboard.py `
    src\stock_platform\api\router.py `
    tests\test_realtime_dashboard_service.py

git commit -m "feat(realtime): add operations dashboard API"
```

STEP27 실시간 자동매매 기반 구축은 여기까지입니다.

다음 단계는 STEP28에서 키움·업비트 주문 어댑터,
실거래 승인 절차, 계좌 동기화 구조를 구현합니다.
