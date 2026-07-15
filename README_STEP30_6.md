# STEP30-6 LLM 기반 전략 선택기

STEP30-2의 전략 순위 후보를 Ollama에 전달해 현재 시장·위험
컨텍스트에 적합한 전략 1개를 선택합니다.

LLM이 실패하거나 잘못된 후보를 선택하면 결정론적 순위 1위를
자동 선택하는 Fallback을 사용합니다.

## 처리 흐름

```text
전략 성과 Ranking
  ↓
상위 후보 5개
  ↓
시장 컨텍스트 + 위험 컨텍스트
  ↓
Ollama 전략 선택
  ↓
후보 검증
  ↓
선택 결과 DB 저장
```

## 신규 테이블

```text
ai.strategy_selection_run
```

저장 항목:

```text
시장
종목
성과 실행 유형
Ollama 모델
선택 상태
선택 전략
성과 Run ID
신뢰도
선택 이유
위험 메모
대안 전략
후보 목록
LLM 원본 응답
```

## 선택 상태

```text
SELECTED
FALLBACK
FAILED
```

현재 구현은 LLM 오류 시 `FALLBACK`으로 Ranking 1위를 선택합니다.

## Alembic 등록

`database/alembic/env.py`:

```python
from stock_platform.performance import selector_entities as selector_entities  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create strategy selection run table"

alembic upgrade head --sql
alembic upgrade head
```

예상하지 않은 삭제 작업이 있으면 적용하지 마세요.

## Ollama 설정

기존 환경변수를 사용합니다.

```dotenv
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3.5:4b
```

설정 클래스의 실제 필드명이 다르면
`selector_runtime.py`에서 맞춰 주세요.

## API

전략 선택:

```text
POST /api/v1/strategy-selector/select
```

요청 예:

```json
{
  "market_code": "KRX",
  "symbol": "005930",
  "run_type": "WALK_FORWARD",
  "minimum_trade_count": 20,
  "candidate_limit": 5,
  "market_context": {
    "market_trend": "SIDEWAYS",
    "volatility": "MEDIUM",
    "rsi": 48.2,
    "news_sentiment": 0.15
  },
  "risk_context": {
    "kill_switch": "INACTIVE",
    "daily_loss_ratio": 0.10,
    "max_position_weight": 0.20
  }
}
```

최근 선택 조회:

```text
GET /api/v1/strategy-selector/latest
```

조건:

```text
market_code
symbol
```

## LLM 응답 검증

LLM은 후보 목록에 있는 다음 두 값을 정확히 반환해야 합니다.

```text
selected_strategy_code
selected_performance_run_id
```

후보 밖 전략, 잘못된 Run ID, 0~1 범위를 벗어난 신뢰도는
모두 거부하고 Fallback을 사용합니다.

## 자동매매 연결 주의

이번 단계는 전략을 선택하고 기록할 뿐, 실시간 전략을 자동 교체하지
않습니다.

운영 적용 순서:

```text
1. Strategy Selector 실행
2. 선택 결과 검토
3. 모의투자 Strategy Runner에 수동 반영
4. 하루 이상 모니터링
5. 성과 비교
6. 자동 교체 기능은 다음 단계에서 연결
```

## router.py 추가

```python
from stock_platform.api.v1.strategy_selector import (
    router as strategy_selector_router,
)

api_router.include_router(
    strategy_selector_router
)
```

## 적용 파일

```text
src/stock_platform/performance/selector_models.py
src/stock_platform/performance/selector_entities.py
src/stock_platform/performance/selector_prompt.py
src/stock_platform/performance/selector_llm.py
src/stock_platform/performance/selector_repository.py
src/stock_platform/performance/selector_service.py
src/stock_platform/performance/selector_runtime.py
src/stock_platform/api/v1/strategy_selector.py
tests/test_strategy_selector_service.py
tests/test_strategy_selector_llm.py
README_STEP30_6.md
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_strategy_selector_service.py `
    tests\test_strategy_selector_llm.py `
    tests\test_strategy_ranking_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP30_6.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\performance\selector_models.py `
    src\stock_platform\performance\selector_entities.py `
    src\stock_platform\performance\selector_prompt.py `
    src\stock_platform\performance\selector_llm.py `
    src\stock_platform\performance\selector_repository.py `
    src\stock_platform\performance\selector_service.py `
    src\stock_platform\performance\selector_runtime.py `
    src\stock_platform\api\v1\strategy_selector.py `
    src\stock_platform\api\router.py `
    tests\test_strategy_selector_service.py `
    tests\test_strategy_selector_llm.py

git commit -m "feat(ai): add LLM strategy selector"
```

다음 단계는 STEP30-7 전략 성과·순위·선택 결과 통합 대시보드입니다.
