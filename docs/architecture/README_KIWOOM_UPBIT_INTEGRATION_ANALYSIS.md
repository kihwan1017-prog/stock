# README_KIWOOM_UPBIT_INTEGRATION_ANALYSIS

> **문서 위치:** `docs/architecture/` (레포 루트 산출물 금지 규칙 준수)  
> **작성일:** 2026-07-21  
> **범위:** 분석 전용 — 본 문서 작성 시점에 **코드 구현·스키마 변경 없음**  
> **원칙:** 추측 배제. 파일·클래스·API·테이블 경로를 근거로 기재.

---

## 1. 현재 구조 요약

Stock Platform은 FastAPI + PostgreSQL + Next.js(Admin/User) 기반이다.  
브로커/시세 계층은 **의도적으로 이원화**되어 있다 (STEP56 주석: 병합하지 않음).

| 패키지 | 경로 | 역할 |
|--------|------|------|
| 주문·계좌·WS 본선 | `src/stock_platform/broker/` | `BrokerAdapter`, Kiwoom 주문/계좌/체결 WS, Paper, live transition, recovery |
| 시세 REST 클라이언트 | `src/stock_platform/brokers/` | `KiwoomRestClient`, `UpbitQuotationClient` (공개 API) |
| 수집기 | `src/stock_platform/collectors/kiwoom/`, `.../upbit/` | 일봉·분봉·instruments sync |
| 주문 엔진 | `src/stock_platform/order/` | `OrderExecutionService` → outbox → `BrokerAdapter` |
| Paper 도메인 | `src/stock_platform/trading/` | `paper_account` / `paper_order` / positions |
| 실시간 | `src/stock_platform/realtime/` | KRX poller + `UpbitRealtimeClient`(공개 시세) |
| 리스크 | `src/stock_platform/risk_engine/` | Kill Switch, daily loss, order guard (기본 KIWOOM/KRX) |

**한 줄:** 키움은 **주문+계좌+시세**까지 연결돼 있고, 업비트는 **시세·종목 메타**까지이며 **실주문 어댑터가 없다**.

---

## 2. 키움 구현 상태

### 2.1 완료·가동 중

| 영역 | 근거 |
|------|------|
| 공통 어댑터 | `broker/adapter.py` — `BrokerAdapter.submit_order/cancel_order/replace_order/get_order` |
| 팩토리 | `broker/factory.py` — `PAPER` → `PaperBrokerAdapter`, `LIVE`+`KIWOOM` → `KiwoomBrokerAdapter` + `LiveTradingTransitionGuard` |
| 주문 | `broker/kiwoom/adapter.py` — `/api/dostk/ordr`, API ID `kt10000`~`kt10003` |
| 토큰 | `broker/kiwoom/token_*.py`, `broker/kiwoom/auth.py` |
| 계좌 sync | `KiwoomAccountSyncService` → `trading.broker_account_snapshot` / positions |
| 미체결 | `broker_pending_order` + `KiwoomPendingOrderService` |
| 체결 WS | `kiwoom/execution_ws_*.py`, API `/api/v1/broker/kiwoom/order-websocket` |
| Live 이중 게이트 | `LiveTradingTransitionService` + `KIWOOM_LIVE_ORDER_ENABLED` + mock 교차 금지 |
| Recovery | `broker_recovery_*`, `/api/v1/broker/recovery` |
| 시세 수집 | `collectors/kiwoom/*`, `POST /api/v1/sync/kiwoom/daily` |
| Admin UI | `/admin/kiwoom`, `/admin/orders`, `/admin/accounts`, `/admin/trading` |
| Outbox 경로 | `order/execution_service.py` → `order_outbox` → `OrderOutboxDispatcher` |

### 2.2 키움에 강하게 결합된 부분 (공통화 시 주의)

| 결합점 | 근거 |
|--------|------|
| Factory LIVE는 KIWOOM만 | `BrokerAdapterFactory` — UPBIT 분기 없음 |
| Outbox runtime 기본 Paper | `order/outbox_runtime.py` — 기본 `PaperBrokerAdapter()` |
| Risk 기본 broker | `risk_engine/order_guard.py`, `daily_loss_runtime.py` — default `"KIWOOM"` |
| 장시간 규칙 | `risk_engine/rules.py` — `exchange_code != "KRX"` 시 장시간 스킵 |
| Realtime 세션 | `realtime/session_*.py` — KRX 장시간; settings `realtime_strategy_market_code="KRX"` |
| Live transition 문구 | `"ENABLE KIWOOM LIVE TRADING"` |
| Admin 주문 폼 기본 | `frontend/.../admin/orders/page.tsx` — `exchange_code: "KRX"` |
| 모니터링 Broker | `operation/monitoring_snapshot.py` — 키움 WS connected 기준 |

---

## 3. 업비트 구현 상태

### 3.1 있음 (시세·메타)

| 영역 | 근거 |
|------|------|
| 공개 REST | `brokers/upbit/client.py` — `list_markets`, day/minute candles |
| Instruments | `UpbitInstrumentSyncService` → `market.instrument` (`asset_type=CRYPTO`, `exchange_code=UPBIT`) |
| 일봉/분봉 | `collectors/upbit/*` → `price_daily`, `candle_minute` |
| 공개 WS | `realtime/upbit_client.py` — ticker/trade/orderbook |
| Admin API | `/api/v1/upbit/markets`, `/instruments/sync`, `/daily/sync`, `/minute/sync` |
| Admin UI | `/admin/upbit` |
| User 계좌 타입 | `UserAccountType`에 `"UPBIT"` (`userApi.ts`); `user_broker_account.broker_code` |
| User 매매 Select | `user/trading/page.tsx` — KRX / UPBIT 선택 가능 (실행은 Paper/키움 경로 중심) |
| Env (공개만) | `UPBIT_BASE_URL`, `UPBIT_TIMEOUT_SECONDS`, `UPBIT_MAX_REQUESTS_PER_SECOND` |

### 3.2 없음 (암호화폐 자동매매 갭)

| 갭 | 설명 |
|----|------|
| `UpbitBrokerAdapter` | 클래스/디렉터리 `broker/upbit/` 부재 |
| Private API | Access Key / Secret / JWT·Query Hash 미구현 |
| Env | `UPBIT_ACCESS_KEY`, `UPBIT_SECRET_KEY`, `UPBIT_LIVE_ORDER_ENABLED`, `UPBIT_USE_MOCK` 없음 |
| 잔고·주문 sync | Kiwoom 전용 account/pending 서비스만 존재 |
| Outbox → Upbit | Factory/runtime이 UPBIT를 모름 |
| Private 체결 WS | 공개 시세만 |
| Live transition | 키움 전용 |
| 공식 Paper | 없음 → 내부 Paper 필요 (요구사항과 일치) |

**판정:** 업비트는 **데이터 레이어 준비 단계**, 주문·자동매매·리스크 통합은 **미착수**.

---

## 4. 공통화 가능 기능

기존 코드에 이미 “시장 중립에 가까운” 축이 있다. **복사본을 만들지 말고 확장**한다.

| 기능 | 현재 근거 | 통합 방향 |
|------|-----------|-----------|
| 주문 제출 파이프라인 | `OrderExecutionService` + `trading.trading_order` (`broker_code`, `exchange_code`) | 어댑터만 분기 |
| Outbox / idempotency | `order_outbox`, `client_order_id` | 브로커별 어댑터 선택 |
| Paper 엔진 | `PaperBrokerAdapter`, `paper_*` | 시장 정책(호가·수수료·시간) 주입 |
| Instrument 마스터 | `market.instrument` — `STOCK`/`CRYPTO`/`ETF`/`INDEX` + `exchange_code` | `market_type` 별칭 또는 문서 표준화 |
| 캔들 | `candle_minute`, `price_daily` (`source`) | 공통 OHLCV 유지 |
| User 계좌 UI | `/user/account` — PAPER/KIWOOM/UPBIT 한 목록 | 인증 폼만 조건부 |
| User 매매 UI | `/user/trading` — exchange Select | LIVE Upbit 연결만 추가 |
| 관심종목/뉴스/AI | watchlist·user APIs | Scoring Provider만 시장별 |
| 전략 배포 | `strategy_deployment.market_code` | `broker_scope`/`market_scope` 확장 |
| Kill Switch | 시스템 단위 존재 | 거래소별 플래그 추가 |
| 알림 | Telegram ops | 메시지 prefix `[KIWOOM]`/`[UPBIT]` |
| 모니터링 overview | broker/db/ai 섹션 | Upbit private health 섹션 추가 |

---

## 5. 거래소별 분리 기능 (Adapter / Provider)

공통 메뉴·서비스·테이블을 쓰되, **아래만** 거래소 전용으로 둔다.

### 키움 전용

- REST/OAuth 토큰 (`broker/kiwoom/token_*`, `auth.py`)
- 주문 API ID·정정 (`kt10000`~`kt10003`)
- 계좌 TR (`ka00001`, `kt00001`, `kt00018`)
- 체결 WS 및 pending 반영
- 장시간·휴장·상하한가·호가단위
- Live transition 승인 문구·설정
- Recovery WS/trading 플래그
- Admin `/admin/kiwoom` 연결·토큰 테스트

### 업비트 전용 (신규 구현 대상)

- JWT + Query Hash 인증
- 주문/취소/조회 private REST
- 시장가 매수(금액) vs 매도(수량) 파라미터
- 정정 없음 → cancel+new + `original_order_id`/`replaced_order_id` 연계 (`trading_order`에 이미 자기참조 FK 존재)
- 최소 주문금액·코인 호가단위
- 24시간 캘린더 / 점검 감지
- Private WS(선택) 또는 REST 폴링 체결 동기화
- Admin 업비트 인증·연결 테스트 UI (기존 `/admin/upbit` 확장)

### 권장 공통 인터페이스 (기존 재사용 우선)

이미 있는 것:

- `BrokerAdapter` (`broker/adapter.py`)
- `BrokerAdapterFactory` (`broker/factory.py`)
- `BrokerOrderRequest` / `BrokerOrderResult` (`broker/models.py`)

검토 후 **필요 시만** 추가 (신규 ABC 남발 금지):

| 후보 | 도입 조건 |
|------|-----------|
| `AccountProvider` / `BalanceProvider` | Kiwoom account sync와 Upbit balances를 동일 스냅샷 테이블에 쓸 때 |
| `MarketDataProvider` | collectors 공통화 시 (지금은 collectors 분리로 충분할 수 있음) |
| `TradingCalendarProvider` | KRX 세션 vs 24h 정책을 전략/리스크에서 주입할 때 |
| `FeePolicy` / `TickSizePolicy` | Paper·백테스트·주문 validate 공통화 시 |
| `RealtimeMarketDataProvider` | KRX poller + Upbit WS 추상화 시 |

---

## 6. 통합 메뉴 설계

### 6.1 원칙

- **키움 주문 / 업비트 주문**처럼 메뉴를 복제하지 않는다.
- Admin의 `/admin/kiwoom`, `/admin/upbit`는 **연결·인증·수집 운영**용으로 유지하되, 거래·자산·전략은 통합 화면으로 이전한다.
- User는 이미 통합에 가깝다 (`menu.tsx` `userMenuItems`).

### 6.2 목표 메뉴 맵

| 통합 메뉴 | 현재 | 변경 |
|-----------|------|------|
| 대시보드 | User `/user/dashboard`, Admin dashboard | 전체/키움/업비트 필터 + 연결 상태 |
| 내 계좌 | `/user/account`, `/admin/accounts` | `broker_code`+`account_type` 공통 목록, 인증 폼 조건부 |
| 보유자산 | portfolio / paper positions | exchange·broker 컬럼, 주식/코인 상세 분기 |
| 주문 관리 | `/user/trading`, `/admin/orders`, trades | 필터: broker/account/side/status/strategy |
| 전략 | `/user/strategies`, `/admin/strategies` | `market_scope` / `broker_scope` |
| 자동매매 | `/user/auto-trading`, `/admin/trading` | 거래소별 Kill Switch·스케줄 |
| 리스크 | `/admin/risk` | 계층 정책 UI |
| 시장 데이터 | Admin upbit+sync, monitoring | 시장 필터 통합 허브 |
| 후보 | candidates / AI | Scoring Provider 분기 |
| 백테스트 | `/user/backtests` | 시장·수수료 정책 선택 |
| 모니터링·알림 | `/admin/monitoring`, notifications | broker 태그 |

필터 표준: `전체 | KIWOOM | UPBIT | account_id | market | strategy | 기간`.

---

## 7. Backend 통합 설계

```text
                    ┌─────────────────────┐
  API / Jobs / UI ─▶│ OrderExecutionService│
                    └──────────┬──────────┘
                               ▼
                         order_outbox
                               ▼
                    BrokerAdapterFactory
                     ├── PAPER
                     ├── KIWOOM (기존)
                     └── UPBIT (신규)
```

### 단계별 백엔드 축

1. **모델 확정:** `broker_code` + `exchange_code`(+ 선택 `market_type`/`asset_type`) 용어 통일  
2. **Factory 확장:** `UPBIT` + `UPBIT_LIVE_ORDER_ENABLED` + mock 가드  
3. **Outbox runtime:** 주문行의 `broker_code`로 어댑터 선택 (Paper 고정 해제)  
4. **Account sync:** 공통 snapshot 테이블에 Upbit balances 매핑  
5. **Calendar/Risk:** Provider 주입으로 KRX 하드코딩 완화  
6. **Secrets:** Upbit key는 평문 금지 — 기존 secrets/암호화 정책 준수 (`user_broker_account`는 이미 시크릿 미저장 설계)

하위 호환: 기존 `/api/v1/broker/kiwoom/*`, `/api/v1/upbit/*` sync API는 **유지**. 신규 통합 API는 추가 또는 얇은 facade.

---

## 8. Frontend 통합 설계

| 화면 | 통합 방식 |
|------|-----------|
| User 계좌/매매/포트폴리오 | 기존 유지 + LIVE Upbit·필터 강화 |
| Admin 주문/자동매매 | KRX 기본값 제거 → 선택 필수 또는 최근 계좌 |
| Admin 키움/업비트 | “거래소 연결” 허브로 묶고 하위 탭 유지 (즉시 삭제 금지) |
| 대시보드 | broker별 KPI 카드 + Overall |
| 권한 | 기존 `menu:kiwoom` / `menu:upbit` + 통합 메뉴 permission 재매핑 |

회귀: User Paper 주문·Admin Kiwoom sync 스모크를 매 PR에 유지.

---

## 9. DB 통합 설계

### 9.1 이미 공통에 가까운 테이블

| 테이블 | 비고 |
|--------|------|
| `market.instrument` | `asset_type` + `exchange_code` |
| `market.candle_minute`, `price_daily` | instrument FK / source |
| `trading.trading_order` | `broker_code`, `exchange_code`, `broker_order_id`, status, replace FK |
| `trading.order_outbox` | 브로커 중립 큐 |
| `trading.broker_*_snapshot`, `broker_pending_order` | `broker_code` 있음 — Upbit 적재만 추가 |
| `trading.user_broker_account` | `broker_code` — 시크릿 미저장 |
| `trading.strategy_deployment` | `market_code` — broker_scope 확장 검토 |

### 9.2 갭·마이그레이션 후보

| 대상 | 갭 | 제안 |
|------|-----|------|
| `paper_account` | broker/market 컬럼 없음 | `broker_code`, `exchange_code` 또는 `market_type` nullable 추가 (기본 KIWOOM/KRX로 백필) |
| `paper_order` | `broker_code` 없음 | `exchange_code` 유지 + `broker_code` 추가 검토 |
| 용어 | `market_code` vs `exchange_code` vs 요구 `market_type` | 문서 매핑표 고정; 물리 컬럼은 점진 추가 |
| `live_trading_transition` | environment 기본 KIWOOM | broker 중립 또는 Upbit row 허용 |
| risk 테이블 | default `'KIWOOM'` | 정책 row에 UPBIT 허용 |
| 신규 | Upbit secrets vault | 별도 encrypted store / env — **평문 컬럼 금지** |

업비트 전용 테이블을 새로 대량 만들지 말고, **기존 `broker_*` + `trading_order` + `instrument`** 에 적재하는 방향을 우선한다.

### 9.3 마이그레이션 원칙

- Alembic만 사용 (`database/alembic/versions/`)
- 기존 키움 데이터 NOT NULL 깨지지 않게 백필 기본값
- Downgrade 가능 여부 명시
- `trading_order.account_id` FK는 paper/broker 다형 — 단일 FK 강제는 보류 (기존 감사 이슈와 동일)

---

## 10. API 통합 설계

### 유지 (하위 호환)

- `/api/v1/broker/kiwoom/**`
- `/api/v1/upbit/**` (시세 sync)
- `/api/v1/order-execution/submit`
- `/api/v1/paper-orders/**`
- `/api/v1/sync/kiwoom/daily`

### 확장·추가 후보

| API | 목적 |
|-----|------|
| Factory/outbox 내부 | `broker_code=UPBIT` 주문 송신 |
| `POST /api/v1/broker/upbit/account/sync` (또는 공통 `/broker/{code}/account/sync`) | 잔고 동기화 |
| `POST /api/v1/broker/upbit/connection/test` | 키 검증 |
| 주문 조회 필터 | `broker_code`, `exchange_code` 쿼리 강화 |
| Kill Switch | 선택적 `broker_code` 스코프 |
| Health/monitoring | Upbit private ping 섹션 |

OpenAPI `securitySchemes`·`require_admin` 패턴은 기존 P0 보안 게이트를 유지한다.

---

## 11. 자동매매 통합 설계

| 항목 | 키움 | 업비트 |
|------|------|--------|
| 스케줄 | KRX 장시간 (`realtime/session_*`, safety_guard) | 24h + 점검/지연 가드 |
| 신호→주문 | realtime execution → Paper/KIWOOM | 동일 버스 + Upbit adapter |
| 중복 주문 | outbox idempotency + safety_guard | 동일 + 심볼 쿨다운 |
| 복구 | broker recovery + WS | REST open-order reconcile (우선) |
| Kill Switch | 전역 | 전역 + `broker_code=UPBIT` |

`RealtimeExecutionConfig.account_id`는 이미 설정 주입 (`REALTIME_PAPER_ACCOUNT_ID`). 계좌별 브로커 매핑 테이블/설정이 필요하다.

---

## 12. 리스크 통합 설계

계층 (요구사항 정렬):

1. Global (`GLOBAL_LIVE_ORDER_ENABLED`, Kill Switch)  
2. Exchange (`KIWOOM_*` / `UPBIT_*`)  
3. User / Account / Strategy / Symbol / Order  

현재:

- 전역 Kill Switch·daily loss·position limit 존재
- 기본값·대시보드가 KIWOOM/KRX에 치우침

필요 작업:

- 정책 row에 `broker_code`/`exchange_code` 필터
- 전체 자산 대비 암호화폐 비중 한도 (포트폴리오 평가 합산)
- 업비트 급등락·데이터 지연 차단
- 거래소별 Kill Switch 상태 필드

기존 `RiskManagementEngine` / `RealtimeOrderSafetyGuard`를 **교체하지 말고 규칙 확장**.

---

## 13. 예상 수정 파일 목록 (우선순위)

### Backend (핵심)

- `src/stock_platform/broker/factory.py`
- `src/stock_platform/broker/upbit/` **(신규)** — adapter, auth(jwt), client, mappers
- `src/stock_platform/broker/models.py` — 요청 필드 확장(금액 시장가 등)
- `src/stock_platform/order/outbox_runtime.py`, `outbox_dispatcher.py`
- `src/stock_platform/order/execution_service.py` — validate 분기
- `src/stock_platform/common/settings.py` — `UPBIT_*` live/mock/keys
- `src/stock_platform/risk_engine/*` — broker 스코프
- `src/stock_platform/realtime/session_*.py`, `safety_guard.py` — calendar provider
- `src/stock_platform/operation/monitoring_snapshot.py` — Upbit health
- `src/stock_platform/api/v1/order_execution.py`, `user_accounts.py`, (신규 upbit broker routes)
- Alembic: paper_account 메타, risk/live_transition 확장

### Frontend

- `frontend/src/config/menu.tsx`, `routes.ts`
- `frontend/src/app/(user)/user/{account,trading,dashboard,portfolio,auto-trading}/**`
- `frontend/src/app/(admin)/admin/{orders,trading,accounts,upbit,kiwoom,risk,monitoring}/**`
- `frontend/src/features/{user,admin}/api/*.ts`

### Tests

- 기존 Kiwoom/Paper 회귀 + 신규 Upbit JWT/hash/order mapping/unit
- `tests/test_security_step62.py` — 신규 mutate 경로 401 매트릭스

---

## 14. 데이터 마이그레이션 계획

| Step | 내용 |
|------|------|
| M1 | `paper_account`에 `broker_code`/`exchange_code`(또는 `market_type`) nullable 추가 → 기존 row `KIWOOM`/`KRX` 백필 → 정책에 따라 NOT NULL |
| M2 | risk/live_transition 기본값·체크 제약에 `UPBIT` 허용 |
| M3 | (선택) `trading_order.metadata_payload`에 upbit 원본 필드 보존 가이드 |
| M4 | secrets: DB 컬럼 추가 금지; vault/env 문서화 |
| M5 | RBAC: 통합 메뉴 permission과 `menu:upbit` 공존 |

롤백: 각 revision downgrade + 백필 역방향.

---

## 15. 테스트 계획

| 구분 | 항목 |
|------|------|
| 회귀 | Paper 주문, Kiwoom adapter mock, outbox, kill switch, live transition guard |
| Upbit unit | JWT, query hash, 시장가 매수/매도 파라미터, tick/min notional |
| 통합 | account sync mapping, cancel+replace 관계, rate limit |
| 리스크 | 거래소별 한도, 전체 비중, Kill Switch 스코프 |
| FE | 통합 필터, 계좌 폼 조건부, typecheck/lint |
| 보안 | 키 로그 마스킹, live 기본 false, mutate 401 |
| 운영 | WS/재시작 복구(키움 기존 + 업비트 reconcile), 장시간(24h) 스모크 |
| 게이트 | `pytest`, `alembic upgrade`, `npm test`, `npm run typecheck`, `npm run build` |

---

## 16. 우선순위별 작업 단계 (STEP 1–10)

요청하신 단계와 현재 갭을 맞춘 **실행 순서**다. **이번 작업은 STEP 1(본 문서)까지.**

| STEP | 내용 | 의존 | 키움 회귀 |
|------|------|------|-----------|
| **1** | 분석·공통 모델·메뉴/DB/API 계획 (본 문서) | — | N/A |
| **2** | 업비트 인증·계좌 연결·잔고·키 보안·rate limit | 1 | 무영향 목표 |
| **3** | 업비트 주문/취소/조회 (live 기본 OFF) | 2 | Factory 격리 |
| **4** | 공통 주문 엔진에 Upbit adapter 연결, 상태·감사 | 3 | Outbox 회귀 필수 |
| **5** | 업비트 실시간(공개 WS 강화 + 체결 동기화) | 2–4 | KRX poller 분리 유지 |
| **6** | 전략 StrategyContext·캘린더·24h 스케줄 | 4–5 | KRX 세션 테스트 |
| **7** | 리스크 계층·비중·급등락·거래소 Kill | 4 | 기존 KS 테스트 |
| **8** | 통합 FE 대시보드/계좌/주문/전략/모니터링 | 4–7 | Admin 키움 페이지 유지 |
| **9** | Upbit Paper + 백테스트 비용정책 | 4,6 | Paper 주식 회귀 |
| **10** | 복구·알림·부하·체크리스트·GO/NO-GO | 전부 | Full suite |

권장 env (구현 시):

```env
UPBIT_USE_MOCK=true
UPBIT_LIVE_ORDER_ENABLED=false
UPBIT_ACCESS_KEY=
UPBIT_SECRET_KEY=
UPBIT_ALLOWED_MARKETS=KRW-BTC,KRW-ETH
KIWOOM_USE_MOCK=true
KIWOOM_LIVE_ORDER_ENABLED=false
GLOBAL_LIVE_ORDER_ENABLED=false
```

---

## 17. 기존 기능 회귀 위험

| 위험 | 영향 | 완화 |
|------|------|------|
| Outbox runtime을 브로커 선택으로 바꿀 때 | 키움/Paper 주문 경로 장애 | 기본 동작 동등성 테스트 + feature flag |
| `trading_order` 스키마/상태 enum 변경 | 기존 주문·FE | 상태 매핑 레이어, 기존 코드 유지 |
| Risk 기본값 제거 | KRX 장시간 미적용 | 캘린더 Provider 기본 KRX |
| Admin 키움 페이지 조기 삭제 | 운영 중단 | 허브로 이전 후 deprecate |
| `broker`/`brokers` 성급한 병합 | 시세+주문 회귀 | STEP56 방침 유지, 어댑터만 확장 |
| Upbit live 조기 활성화 | 자금 사고 | mock·allowlist·이중 게이트 |
| paper_account 강제 NOT NULL | 기존 모의 계좌 | 백필 후 제약 |
| 24h 스케줄러 부하 | CPU/API | 심볼 화이트리스트·RPS |
| Secret 로그 | 유출 | 기존 `security_mask` 확장 |

**NO-GO 조건 (실거래):** Upbit adapter + Paper E2E + 회귀 스위트 + live 이중 게이트 문서화 전 `UPBIT_LIVE_ORDER_ENABLED=true` 금지.

---

## 부록 A. 공통화 대상 목록 (체크리스트)

- [ ] `BrokerAdapterFactory` UPBIT
- [ ] Outbox 어댑터 라우팅
- [ ] `trading_order` 필터/API 문서
- [ ] `broker_*_snapshot` Upbit 적재
- [ ] Paper 계좌 메타 (`broker_code`/`exchange_code`)
- [ ] Risk/Kill 스코프
- [ ] TradingCalendarProvider
- [ ] User/Admin 통합 필터
- [ ] Monitoring Upbit 섹션
- [ ] 알림 broker 태그
- [ ] 백테스트 FeePolicy
- [ ] 후보 Scoring Provider (CRYPTO)

## 부록 B. 거래소별 분리 대상 목록

- [ ] Kiwoom token/order/account/WS/recovery/live-transition (유지)
- [ ] Upbit JWT/hash/private order/cancel/min-notional/tick
- [ ] KRX session hours vs Upbit 24h
- [ ] Admin 연결 페이지(키움·업비트) 인증 UI
- [ ] 오류코드 매퍼 (키움/업비트 각각)

## 부록 C. 핵심 경로 인덱스

```text
broker/adapter.py
broker/factory.py
broker/kiwoom/adapter.py
broker/paper/adapter.py
order/execution_service.py
order/outbox_runtime.py
brokers/upbit/client.py
collectors/upbit/
realtime/upbit_client.py
markets/models.py          # Instrument asset_type
order/entities.py          # TradingOrderEntity
trading/account_models.py  # UserBrokerAccount, PaperAccount
frontend/src/config/menu.tsx
```

---

## 다음 액션

본 문서로 **STEP 1 완료**로 본다.  
승인 후 **STEP 2–10** 구현을 진행한다. (체크리스트: [LIVE_KIWOOM_UPBIT_CHECKLIST.md](../trading/LIVE_KIWOOM_UPBIT_CHECKLIST.md))

### STEP 구현 메모

| STEP | 상태 | 요약 |
|------|------|------|
| 2 | 완료 | JWT·잔고·Admin 연결/스냅샷 |
| 3 | 완료 | `UpbitBrokerAdapter` 주문/취소/cancel+new, mock 기본 |
| 4 | 완료 | Outbox `broker_code`/`environment` 라우팅 + Factory UPBIT |
| 5 | 완료 | REST `reconcile-orders` 폴링 |
| 6 | 완료 | UPBIT 장시간 스킵(기존), 호가/수량 `lot_rounding` 분기 |
| 7 | 완료 | Kill `EXCHANGES=` 스코프, 모니터링 kiwoom/upbit |
| 8 | 완료 | Admin 주문 broker/exchange, paper_account 메타 컬럼 |
| 9 | 완료 | `broker/fee_policy.py` Upbit/KRX |
| 10 | 완료 | Live GO/NO-GO 체크리스트 |

결정 항목(유지):

1. `market_type` 컬럼 신설 vs `asset_type`+`exchange_code` 문서 표준만 사용 → **후자 채택**
2. Upbit secrets → **env only**
3. Admin `/admin/kiwoom`·`/admin/upbit` → **유지·확장** (삭제 없음)

---

## 18. 통합 로그인·권한 분석 (STEP 1-A / §12)

### 18.1 현재 로그인 화면 구조

| 경로 | 파일 | 비고 |
|------|------|------|
| `/` | `frontend/src/app/page.tsx` | 단일 진입 → `/login` (User/Admin 분리 버튼 제거) |
| `/login` | `frontend/src/app/(auth)/login/page.tsx` | **유일 로그인** |
| `/signup` | `(auth)/signup` | 공개 가입 (prod 차단) |
| `/change-password` | `(auth)/change-password` | 강제 변경 |
| `/onboarding` | `(auth)/onboarding` | 최초 설정 안내 |
| `/forbidden` | `(auth)/forbidden` | 권한 부족 |

**없음:** `/admin/login`, `/user/login`, 키움/업비트 로그인 페이지.  
브로커 API 인증은 플랫폼 로그인과 분리 — `내 계좌` / Admin 키움·업비트 연결.

### 18.2 인증 API

| API | 구현 |
|-----|------|
| `POST /api/v1/auth/login` | `api/v1/auth.py` → `AuthService.login` |
| `POST /api/v1/auth/refresh` | rotation + reuse → revoke-all |
| `POST /api/v1/auth/logout` | refresh revoke + audit |
| `GET /api/v1/auth/me` | **DB 재조회** `default_route` 포함 |
| `POST /api/v1/auth/change-password` | 세션 폐기 + audit |
| `POST /api/v1/auth/onboarding/complete` | 온보딩 완료 |

로그인 응답: `access_token`, `refresh_token`, `expires_in`, `user`(roles/permissions/**user_status**/password_change_required/**default_route**).

### 18.3 사용자·역할·권한 DB

| 테이블 | 용도 |
|--------|------|
| `auth.user` | 로그인 계정 (+ `password_change_required`, `failed_login_count`, `locked_until`, `onboarding_completed_at`) |
| `auth.role` / `auth.permission` | RBAC |
| `auth.user_role` / `auth.role_permission` | 매핑 |
| `auth.refresh_token` | 세션·rotation |

역할 시드: `admin`, `operator`, `viewer` (불필요 역할 추가 없음).

### 18.4 화면 분리

- 동일 Next.js 앱: `(admin)` / `(user)` 레이아웃 + 공통 `AuthGuard`
- Admin: `requiredRoles=["admin","operator"]` + menu permission
- User: path별 trader 역할

### 18.5 관리자 판정 / JWT

- JWT access claim에 `roles` 스냅샷 존재하나 **인가에 미사용**
- `require_admin` / `get_current_user`: `sub` 검증 → **DB user + RBAC 재조회**
- 비활성·삭제·잠금 시 기존 JWT로도 401

### 18.6 소유권

- `assert_paper_account_access` / `assert_trading_account_access` 사용 중
- `assert_broker_account_access` 정의됨 — 계좌 연결 API에 점진 배선

### 18.7 토큰 저장

- FE: sessionStorage (+ 미들웨어용 session cookie 동기화)
- BE: `AUTH_REFRESH_COOKIE_ENABLED=true` 시 login/refresh에 HttpOnly `kiki_refresh_token` 설정 (`auth/refresh_cookie.py`)
- 기본값은 `false` (크로스 Origin SPA 호환). 활성화 시 `credentials` + CORS allow_credentials 필요
- 비밀번호 변경 / Admin force-logout 시 `revoke_all_for_user`

### 18.8 로그인 보안

| 항목 | 상태 |
|------|------|
| bcrypt 해시 | 있음 |
| Rate limit login | 20/60s |
| 실패 잠금 | `AUTH_MAX_FAILED_LOGINS` / `AUTH_LOCKOUT_MINUTES` |
| 로그인 감사 | SUCCESS/FAILURE |
| 로그아웃·비밀번호 변경 감사 | 추가됨 |
| 아이디 존재 노출 방지 | 동일 오류 메시지 |

### 18.9 권한별 초기 이동

`auth/user_status.py` `resolve_default_route`:

1. LOCKED/INACTIVE → 로그인 차단  
2. PASSWORD_CHANGE_REQUIRED → `/change-password`  
3. 온보딩 미완료(비관리자) → `/onboarding`  
4. admin/operator → `/admin/dashboard`  
5. 그 외 → `/user/dashboard`

### 18.10 예상 수정·마이그레이션

- Migration `l8a9b0c1d2e3` — auth.user 상태/잠금/온보딩  
- BE: `auth/service.py`, `deps.py`, `schemas.py`, `api/v1/auth.py`  
- Admin: `POST /users/{id}/unlock`, `force-logout`, `GET .../sessions`, `GET .../accounts`  
- 소유권: `user_accounts`에 `assert_account_access` 배선  
- FE: 단일 로그인, AuthGuard, `/forbidden`, Admin 회원 잠금해제/세션/계좌  
- 테스트: `test_auth_user_status.py`, `test_admin_user_unlock.py`, `test_refresh_cookie.py`

### 18.11 회귀 위험

- 기존 사용자 온보딩: migration 백필로 완료 처리  
- portal 쿼리 제거 — 북마크 `?portal=admin`은 무시되고 DB 권한으로 이동  
- Admin URL을 viewer가 next로 넣으면 `/forbidden`
