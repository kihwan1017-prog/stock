# STEP22-2 뉴스·공시 컨텍스트 및 AI 결과 저장

사용자가 제공하거나 이후 수집기가 생성할 뉴스·공시 요약을
종목별 컨텍스트로 Ollama에 전달하고 평가 결과를 PostgreSQL에
저장합니다.

## 신규 테이블

```text
ai.candidate_analysis_run
ai.candidate_analysis_result
```

## Alembic 모델 등록

`database/alembic/env.py`의 모델 import 영역에 추가합니다.

```python
from stock_platform.ai import analysis_models as ai_analysis_models  # noqa: F401
```

기존 import 예:

```python
from stock_platform.markets import models as market_models  # noqa: F401
from stock_platform.screener import persistence_models as screener_models  # noqa: F401
from stock_platform.ai import analysis_models as ai_analysis_models  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create ai candidate analysis tables"

alembic upgrade head --sql
alembic upgrade head
```

생성 파일에는 아래 두 테이블 생성만 있어야 합니다.

```text
ai.candidate_analysis_run
ai.candidate_analysis_result
```

`op.drop_table(...)`이 있으면 적용하지 마세요.

## AI 분석 실행

```text
POST /api/v1/ai-analysis/KRX
```

요청 예:

```json
{
  "limit": 10,
  "contexts": {
    "005930": {
      "news": [
        "최근 실적 관련 기사 요약"
      ],
      "disclosures": [
        "최근 공시 요약"
      ],
      "notes": [
        "출처와 작성 시각을 별도로 확인할 것"
      ]
    }
  }
}
```

뉴스·공시가 없으면 빈 객체로 실행할 수 있습니다.

```json
{
  "limit": 10,
  "contexts": {}
}
```

## 최신 결과 조회

```text
GET /api/v1/ai-analysis/latest/KRX
```

## 주의

이번 단계는 뉴스·공시 원문을 자동 수집하지 않습니다.
컨텍스트 입력과 AI 결과 저장 기반을 먼저 제공합니다.

다음 STEP22-3에서 DART 공시 수집과 뉴스 수집 인터페이스를
연결할 수 있습니다.

## Git 커밋

```powershell
git add `
    README_STEP22_2.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\ai `
    src\stock_platform\api\v1\ai_analysis.py `
    src\stock_platform\api\router.py `
    tests\test_candidate_analysis_repository.py

git commit -m "feat(ai): persist candidate analysis results"
```
