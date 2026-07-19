# STEP21-3 여러 종목 일괄 평가 및 Top30

활성 종목 전체를 평가하여 점수순으로 정렬하고 상위 후보를 반환합니다.

## 주요 기능

- 거래소별 활성 종목 조회
- 종목별 CandidateService 평가
- 데이터 부족 종목 자동 제외
- 최소 점수 필터
- 모든 필수 규칙 통과 옵션
- 점수순 Top N 반환

## 적용 파일

```text
src/stock_platform/screener/batch_service.py
src/stock_platform/screener/__init__.py
src/stock_platform/api/v1/candidates.py
tests/test_candidate_batch_service.py
README_STEP21_3.md
```

ZIP을 다음 위치에 압축 해제합니다.

```text
D:\Projects\stock-platform
```

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_candidate_rule_engine.py `
    tests\test_candidate_scoring.py `
    tests\test_candidate_batch_service.py `
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

## Top30 API

```text
GET /api/v1/candidates/top/{exchange_code}
```

KRX 예:

```text
GET /api/v1/candidates/top/KRX?as_of_date=2026-07-13&limit=30&minimum_score=50&require_all_rules=false
```

업비트 예:

```text
GET /api/v1/candidates/top/UPBIT?as_of_date=2026-07-13&limit=30&minimum_score=40&require_all_rules=false
```

`require_all_rules=true`로 설정하면 6개 필수 규칙을 모두 통과한 종목만 반환합니다.

## 주의

거래소 내 모든 활성 종목을 순차 계산하므로 종목이 많으면 시간이 걸립니다.
다음 단계에서 병렬처리, 결과 캐시, 스케줄러 저장 테이블을 추가할 수 있습니다.

## Git 커밋

```powershell
git add `
    README_STEP21_3.md `
    src\stock_platform\screener\batch_service.py `
    src\stock_platform\screener\__init__.py `
    src\stock_platform\api\v1\candidates.py `
    tests\test_candidate_batch_service.py

git commit -m "feat(screener): add top candidate batch screening"
```

다음 단계는 STEP21-4 후보 선정 결과 저장 및 스케줄러 실행입니다.
