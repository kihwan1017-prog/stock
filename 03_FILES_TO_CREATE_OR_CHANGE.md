# STEP34 파일 변경 목록

## 새로 생성되는 파일

| 구분 | 파일 | 설명 |
|---|---|---|
| 신규 | `src/stock_platform/indicator/__init__.py` | Indicator 패키지 |
| 신규 | `src/stock_platform/indicator/models.py` | 지표 결과 모델 |
| 신규 | `src/stock_platform/indicator/calculator.py` | SMA, EMA, RSI 계산 |
| 신규 | `src/stock_platform/screener/__init__.py` | Screener 패키지 |
| 신규 | `src/stock_platform/screener/service.py` | 기본 종목 선별 규칙 |
| 신규 | `src/stock_platform/api/v1/indicator_router.py` | Indicator API |
| 신규 | `alembic/versions/20260717_03_indicator.py` | DB Migration |
| 신규 | `tests/step34/test_indicator.py` | 지표 테스트 |
| 신규 | `tests/step34/test_screener.py` | 선별 테스트 |
| 신규 | `requirements_step34.txt` | STEP34 의존성 |

## 사용자가 직접 수정해야 하는 기존 파일

| 구분 | 파일 | 직접 해야 하는 작업 |
|---|---|---|
| 수정 | `src/stock_platform/api/main.py` | `indicator_router` import 및 등록 |
| 또는 수정 | `src/stock_platform/api/v1/router.py` | 프로젝트가 통합 Router 구조일 때 하위 Router 등록 |
| 수정 | `alembic/versions/20260717_03_indicator.py` | `down_revision`을 최신 revision으로 변경 |
| 선택 수정 | 기존 `requirements.txt` | 의존성을 한 파일로 통합할 경우 추가 |

## 자동으로 수정되지 않는 파일

```text
src/stock_platform/api/main.py
src/stock_platform/api/v1/router.py
requirements.txt
.env
alembic.ini
```
