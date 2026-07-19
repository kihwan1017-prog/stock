# STEP22-1 Ollama 후보 재평가

저장된 규칙 기반 후보선정 결과를 로컬 Ollama로 재평가해
최대 Top10을 반환합니다.

## 주요 원칙

- 수익 보장 또는 자동 매수 지시 금지
- 입력에 없는 뉴스·공시·재무정보 생성 금지
- Ollama Structured Output(JSON Schema) 사용
- 토큰 및 비밀정보를 로그에 출력하지 않음

## Ollama API

- URL: `POST /api/chat`
- `stream: false`
- `think: false`
- `format`: JSON Schema
- 기본 모델: `qwen3.5:4b`

## 적용 파일

```text
src/stock_platform/common/settings.py
src/stock_platform/ai/__init__.py
src/stock_platform/ai/ollama_client.py
src/stock_platform/ai/candidate_ranker.py
src/stock_platform/api/v1/ai_candidates.py
src/stock_platform/api/router.py
tests/test_ollama_candidate_ranker.py
```

ZIP을 다음 프로젝트 루트에 압축 해제합니다.

```text
D:\Projects\stock-platform
```

## 환경설정

다음 외부 비밀파일에 필요 시 추가합니다.

```text
E:\StockTrading\secrets\stock-platform.env
```

```dotenv
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3.5:4b
OLLAMA_TIMEOUT_SECONDS=120
OLLAMA_TEMPERATURE=0.2
OLLAMA_KEEP_ALIVE=10m
```

## 사전 조건

STEP21-4에서 후보선정 실행 결과가 저장되어 있어야 합니다.

```text
strategy.candidate_run
strategy.candidate_result
```

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_ollama_candidate_ranker.py `
    -q
```

## 서버 실행

```powershell
uvicorn stock_platform.api.main:app --reload --app-dir src
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

## API

```text
POST /api/v1/ai/candidates/rank/{exchange_code}
```

예:

```text
POST /api/v1/ai/candidates/rank/KRX?limit=10
```

이 단계의 결과는 아직 DB에 저장하지 않습니다.
다음 STEP22-2에서 뉴스·공시 컨텍스트와 AI 평가 결과 저장 테이블을 추가합니다.

## Git 커밋

```powershell
git add `
    README_STEP22_1.md `
    src\stock_platform\common\settings.py `
    src\stock_platform\ai `
    src\stock_platform\api\v1\ai_candidates.py `
    src\stock_platform\api\router.py `
    tests\test_ollama_candidate_ranker.py

git commit -m "feat(ai): add Ollama candidate ranking"
```
