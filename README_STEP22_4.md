# STEP22-4 네이버 뉴스 수집·요약

네이버 검색 Open API의 뉴스 검색 결과를 수집하고 Ollama로
요약하여 PostgreSQL에 저장합니다.

## 공식 API 기준

- 요청 URL: `https://openapi.naver.com/v1/search/news.json`
- HTTP 메서드: GET
- 인증 헤더:
  - `X-Naver-Client-Id`
  - `X-Naver-Client-Secret`
- 주요 파라미터:
  - `query`
  - `display` 1~100
  - `start` 1~1000
  - `sort`: `date` 또는 `sim`

## 신규 테이블

```text
news.news_article
news.news_summary
```

## 환경설정

`E:\StockTrading\secrets\stock-platform.env`에 추가합니다.

```dotenv
NAVER_CLIENT_ID=발급받은_클라이언트_ID
NAVER_CLIENT_SECRET=발급받은_클라이언트_SECRET
NAVER_NEWS_BASE_URL=https://openapi.naver.com/v1/search/news.json
NAVER_NEWS_TIMEOUT_SECONDS=15
```

## Alembic 모델 등록

`database/alembic/env.py`에 추가합니다.

```python
from stock_platform.news import models as news_models  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create news article and summary tables"

alembic upgrade head --sql
alembic upgrade head
```

생성 파일에는 다음 두 테이블 생성만 있어야 합니다.

```text
news.news_article
news.news_summary
```

`op.drop_table(...)`이 있으면 적용하지 마세요.

## 뉴스 수집 API

```text
POST /api/v1/news/sync
```

예:

```json
{
  "exchange_code": "KRX",
  "symbol": "005930",
  "query": "삼성전자",
  "display": 100
}
```

## 뉴스 요약 API

```text
POST /api/v1/news/summarize
```

예:

```json
{
  "exchange_code": "KRX",
  "symbol": "005930",
  "limit": 20
}
```

## AI 컨텍스트 조회

```text
GET /api/v1/news/KRX/005930?limit=20
```

반환된 `news` 배열은 STEP22-2 AI 분석 요청의 종목 컨텍스트로
사용할 수 있습니다.

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_naver_news_client.py `
    tests\test_news_service.py `
    -q
```

## Git 커밋

```powershell
git add .
git commit -m "feat(news): add Naver news collection and summary"
```

다음 단계에서는 뉴스와 DART 공시를 후보 종목별로 자동 결합해
AI 분석 요청을 한 번에 실행하는 오케스트레이션 서비스를 추가할 수 있습니다.
