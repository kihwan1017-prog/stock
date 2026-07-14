# STEP22-3 OpenDART 공시 수집기

금융감독원 OpenDART 공시검색 API를 사용해 기업 공시 목록을 수집하고
PostgreSQL에 저장합니다.

## 공식 API 기준

- 공시검색: `GET https://opendart.fss.or.kr/api/list.json`
- 인증키 파라미터: `crtfc_key`
- 기업 고유번호: `corp_code` 8자리
- 조회 시작일: `bgn_de` (YYYYMMDD)
- 조회 종료일: `end_de` (YYYYMMDD)
- 정상 상태 코드: `000`
- 조회 결과 없음: `013`

## 신규 테이블

```text
disclosure.dart_disclosure
```

## 환경설정

외부 비밀파일에 추가:

```dotenv
DART_API_KEY=발급받은_40자리_인증키
DART_BASE_URL=https://opendart.fss.or.kr/api
DART_TIMEOUT_SECONDS=20
```

파일:

```text
E:\StockTrading\secrets\stock-platform.env
```

## Alembic 모델 등록

`database/alembic/env.py`에 추가:

```python
from stock_platform.disclosure import models as disclosure_models  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create dart disclosure table"

alembic upgrade head --sql
alembic upgrade head
```

생성 파일에는 `disclosure.dart_disclosure` 생성만 있어야 합니다.

## API

```text
POST /api/v1/dart/sync
```

요청 예:

```json
{
  "corp_code": "00126380",
  "start_date": "2026-01-01",
  "end_date": "2026-07-13"
}
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
python -m pytest tests\test_dart_client.py -q
```

## Git 커밋

```powershell
git add .
git commit -m "feat(disclosure): add OpenDART collector"
```

다음 단계에서는 수집된 DART 공시를 종목별로 요약해
STEP22-2 AI 컨텍스트에 자동 연결할 수 있습니다.
