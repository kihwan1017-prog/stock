# STEP22-5 뉴스·공시·AI 자동 오케스트레이션

최신 규칙 기반 후보를 읽고 종목별 뉴스와 DART 공시 컨텍스트를
자동 결합한 뒤 Ollama 분석을 실행하고 결과를 저장합니다.

## 처리 흐름

```text
strategy.candidate_run
        ↓
strategy.candidate_result Top10
        ↓
news.news_article / news.news_summary
        +
disclosure.dart_disclosure
        ↓
Ollama 구조화 분석
        ↓
ai.candidate_analysis_run
ai.candidate_analysis_result
```

## 적용 파일

```text
src/stock_platform/disclosure/repository.py
src/stock_platform/ai/context_builder.py
src/stock_platform/ai/orchestration_service.py
src/stock_platform/ai/__init__.py
src/stock_platform/api/v1/ai_orchestration.py
src/stock_platform/api/router.py
tests/test_candidate_context_builder.py
```

이번 단계에는 신규 테이블이 없으므로 Alembic 작업은 필요 없습니다.

## 사전 조건

다음 단계가 DB에 적용되어 있어야 합니다.

- STEP21-4 후보선정 결과 저장
- STEP22-2 AI 분석 결과 저장
- STEP22-3 DART 공시 수집
- STEP22-4 네이버 뉴스 수집·요약

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_candidate_context_builder.py `
    -q
```

## API

```text
POST /api/v1/ai-orchestration/{exchange_code}
```

KRX 예:

```json
{
  "limit": 10,
  "news_limit": 20,
  "disclosure_limit": 20,
  "lookback_days": 90
}
```

호출 주소:

```text
POST /api/v1/ai-orchestration/KRX
```

업비트는 DART 공시 없이 뉴스만 사용합니다.

```text
POST /api/v1/ai-orchestration/UPBIT
```

## 주의

후보 종목의 뉴스와 공시가 미리 수집되어 있어야 컨텍스트에 포함됩니다.
데이터가 없는 경우 빈 배열로 전달되며, Ollama는 정보 부족을
위험요소로 기록하도록 구성되어 있습니다.

## Git 커밋

```powershell
git add `
    README_STEP22_5.md `
    src\stock_platform\disclosure\repository.py `
    src\stock_platform\ai\context_builder.py `
    src\stock_platform\ai\orchestration_service.py `
    src\stock_platform\ai\__init__.py `
    src\stock_platform\api\v1\ai_orchestration.py `
    src\stock_platform\api\router.py `
    tests\test_candidate_context_builder.py

git commit -m "feat(ai): orchestrate news disclosure candidate analysis"
```

다음 단계는 STEP23 위험관리 엔진입니다.
