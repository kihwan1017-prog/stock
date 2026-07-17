# Domain Package Map (STEP35)

> 기준일: 2026-07-18  
> 원칙: **삭제부터 하지 않는다.** 표준 패키지만 신규 코드에 사용한다.

---

## 1. 표준 패키지 요약

| 도메인 | 표준 패키지 | Legacy / Overlay | 신규 코드 위치 |
|--------|-------------|------------------|----------------|
| 시장 DB (종목/일봉) | `markets` | `market` (in-memory STEP33) | `markets/` |
| 지표 API/서비스 | `indicators` | `indicator` (순수 계산) | `indicators/` |
| Broker 주문·계좌·WS | `broker` | `brokers` (레거시 HTTP 클라이언트) | `broker/` |
| 운영 리스크 | `risk_engine` | `risk` (STEP32 정책/사이징) | `risk_engine/` |
| 전략 배포·런타임 | `strategy_deployment` | `strategy` (시그널 스텁), `strategies` (빈 셸) | `strategy_deployment/` |
| 주문/체결 | `order`, `trading` | — | `order/`, `trading/` |
| 후보 스크리너 | `screener` | — | `screener/` |
| AI | `ai` | — | `ai/` |
| 운영 Job/Pipeline | `operation` | — | `operation/` |
| 실시간 런타임 | `realtime` | — | `realtime/` |

---

## 2. 중복 그룹 상세

### 2.1 market / markets

| | `markets` (표준) | `market` (overlay) |
|--|------------------|---------------------|
| 역할 | ORM `Instrument`, `PriceDaily` + DB Repository/Service | dataclass + InMemory repo + STEP33 sync stub |
| API | `/api/v1/prices`, `/api/v1/indicators`, sync | `/api/v1/market/*` (`market_data_router`) |
| DB | `market.instrument`, `market.price_daily` | 없음 |

**규칙:** PostgreSQL 연동은 `markets`만 사용. `market.symbol`/`candle_day` 재생성 금지.

### 2.2 indicator / indicators

| | `indicators` (표준) | `indicator` (유틸) |
|--|---------------------|---------------------|
| 역할 | IndicatorEngine/Service, API | sma/ema/rsi 계산기 + dataclass |
| API | `/api/v1/indicators` | deprecated `/api/v1/indicator` |

**규칙:** API/서비스는 `indicators`. 순수 계산은 `indicator.calculator` 재사용 가능.

### 2.3 broker / brokers

| | `broker` (표준) | `brokers` (레거시) |
|--|-----------------|---------------------|
| 역할 | Adapter, Dispatcher, Kiwoom REST/WS, ORM, recovery | 초기 시세 HTTP 클라이언트 (kiwoom/upbit) |
| API | `/api/v1/broker/*`, order dispatch | `kiwoom.py`, `sync.py`, `upbit.py`, collectors |

**규칙:** 주문·계좌·체결·WS는 `broker`. 시세 sync 레거시 클라이언트는 `brokers` 유지하되 신규 주문 로직 금지.  
(이전 문서의 “`brokers` 없음” 서술은 오류 — 패키지 존재함.)

### 2.4 risk / risk_engine

| | `risk_engine` (표준) | `risk` (STEP32) |
|--|----------------------|-----------------|
| 역할 | Kill switch, 일손실, position limit, realtime guard | Risk policy / position plan / 사이징 demo |
| API | `/api/v1/risk/kill-switch`, daily-loss, dashboard | `/api/v1/risk`, risk-policies |

**규칙:** 실시간 가드·킬스위치·일손실은 `risk_engine`. 정책/사이징 API는 당분간 `risk` 유지.

### 2.5 strategy / strategies / strategy_deployment

| | `strategy_deployment` (표준) | `strategy` | `strategies` |
|--|------------------------------|------------|--------------|
| 역할 | 배포 ORM, runtime, pipeline, policy | 시그널 Protocol/스텁 | **빈 패키지** |
| API | `/api/v1/strategy-*` | 거의 없음 | 없음 |

**규칙:** 배포·런타임·정책은 `strategy_deployment`. 알고리즘 스텁만 `strategy`에 추가 가능. `strategies`에 신규 코드 금지.

---

## 3. Compatibility

| 경로 | 상태 |
|------|------|
| `/api/v1/indicator` | deprecated alias → `/api/v1/indicators` |
| `/api/v1/market` | STEP36에서 `markets` Repository 연결 예정 |
| `brokers.kiwoom` / `brokers.upbit` | collectors/sync용 유지, 주문 로직 이전 금지 |

---

## 4. 신규 개발 체크리스트

1. 이 문서의 **표준 패키지**에만 Entity/Repository/Service를 추가한다.
2. Overlay(`market`)에 DB 테이블을 만들지 않는다.
3. import 경로를 바꿀 때는 즉시 삭제하지 말고, 테스트 통과 후 단계적으로 이전한다.
4. Router는 `api/router.py`의 `register_api_routers`에만 등록한다.
