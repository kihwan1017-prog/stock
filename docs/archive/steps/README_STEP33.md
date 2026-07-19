# README_STEP33

STEP33 Market Data Engine 1차 통합 패키지입니다.

## 포함 범위

- PostgreSQL `market` 스키마 핵심 테이블
- Kiwoom REST 시세 클라이언트 기본 구조
- Upbit REST 시세 클라이언트 기본 구조
- Symbol / Quote / Trade / Daily Candle repository
- FastAPI 조회 API
- 일봉 동기화 서비스 기본 구조
- pytest
- ERD / API / 적용 문서

> 이 패키지는 기존 `D:\Projects\stock-platform`에 병합하는 overlay입니다.
> 적용 전 Git 커밋 또는 백업을 권장합니다.

## 설치

```powershell
cd D:\Projects\stock-platform
pip install -r requirements_step33.txt
```

## 환경변수

`.env.example.step33` 파일을 기존 `.env`에 반영합니다.

## Alembic

`alembic/versions/20260717_02_step33_market_data.py`의 `down_revision`을
현재 프로젝트의 최신 revision으로 변경합니다.

```powershell
alembic upgrade head
```

## FastAPI router 등록

```python
from stock_platform.api.v1.market_data_router import router as market_data_router
app.include_router(market_data_router)
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
pytest -q tests\step33
```

## API

- `GET /api/v1/market/symbols`
- `GET /api/v1/market/quotes/{market}/{symbol}`
- `GET /api/v1/market/candles/day/{market}/{symbol}`
- `GET /api/v1/market/trades/{market}/{symbol}`
- `POST /api/v1/market/sync/upbit/day/{symbol}`
- `POST /api/v1/market/sync/kiwoom/day/{symbol}`

## 제한 사항

- Kiwoom 요청/응답 필드명은 실제 공식 REST 명세와 프로젝트의 기존 인증 모듈에 맞춰 mapper를 조정해야 합니다.
- 현재 repository 기본 구현은 메모리 기반입니다.
- PostgreSQL SQLAlchemy repository는 다음 STEP33 보강 패키지에서 연결하도록 인터페이스를 분리했습니다.
- 실시간 WebSocket, 분봉, 지표 엔진, 캐시는 다음 보강 범위입니다.
