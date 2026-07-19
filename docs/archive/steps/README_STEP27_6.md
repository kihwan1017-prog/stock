# STEP27-6 실시간 뉴스·공시 기반 AI 재평가

실시간 보유 종목을 Ollama 모델로 재평가하여 다음 중 하나의
보조 판단을 생성합니다.

```text
KEEP
REDUCE
EXIT
WATCH
```

이 단계는 AI 판단을 생성할 뿐, 실제 주문을 직접 실행하지 않습니다.

## 적용 파일

```text
src/stock_platform/realtime/ai_models.py
src/stock_platform/realtime/ai_service.py
src/stock_platform/realtime/ai_runner.py
src/stock_platform/api/v1/realtime_ai.py
src/stock_platform/scheduler/realtime_ai_job.py
tests/test_realtime_ai_review_service.py
```

신규 테이블은 없어 Alembic 작업은 필요 없습니다.

## router.py 추가

```python
from stock_platform.api.v1.realtime_ai import (
    router as realtime_ai_router,
)
```

```python
api_router.include_router(realtime_ai_router)
```

## API

```text
POST /api/v1/realtime-ai/review
```

요청 예:

```json
{
  "exchange_code": "KRX",
  "symbol": "005930",
  "current_price": 72000,
  "news_limit": 10,
  "disclosure_limit": 10,
  "lookback_days": 30
}
```

응답 예:

```json
{
  "exchange_code": "KRX",
  "symbol": "005930",
  "action": "REDUCE",
  "score": 42,
  "confidence": 0.82,
  "summary": "단기 위험 증가",
  "risk_factors": [
    "변동성 확대"
  ]
}
```

## 중요

`RealtimeAiReviewService._load_context()`는 현재 최소 형태입니다.

프로젝트에 이미 구현된 뉴스·공시 Repository 구조에 맞춰
아래 데이터를 실제로 조회하도록 확장해야 합니다.

```text
최신 뉴스
최신 DART 공시
기존 AI 분석 결과
현재 포지션 손익
최근 가격 변동
```

AI 응답만으로 자동 매도하지 마세요.

권장 조건:

```text
action == EXIT
AND confidence >= 0.8
AND 기존 위험관리 조건 충족
AND PAPER 모드
```

실거래는 여전히 잠금 상태를 유지합니다.

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_realtime_ai_review_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP27_6.md `
    src\stock_platform\realtime\ai_models.py `
    src\stock_platform\realtime\ai_service.py `
    src\stock_platform\realtime\ai_runner.py `
    src\stock_platform\api\v1\realtime_ai.py `
    src\stock_platform\scheduler\realtime_ai_job.py `
    src\stock_platform\api\router.py `
    tests\test_realtime_ai_review_service.py

git commit -m "feat(realtime): add AI position reevaluation"
```

다음 단계는 STEP27-7 실시간 운영 상태 통합 조회 API입니다.
