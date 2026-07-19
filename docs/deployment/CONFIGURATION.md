# 설정 가이드 — stock-platform v1.0

환경파일(비밀): `E:\StockTrading\secrets\stock-platform.env`  
템플릿: 프로젝트 `stock-platform.env.example` · `.env.example`  
프론트: `frontend/.env.local` (템플릿 `frontend/.env.example`)  
런타임 DB 설정 UI: Admin → 시스템설정 / 환경설정 (`operation.app_setting`)

> **비밀은 Git에 넣지 마세요.** `NEXT_PUBLIC_*` 에는 API Key·JWT Secret을 넣지 않습니다.

---

## 1. 비밀 env vs DB Settings

| 구분 | 저장 위치 | 예 | 비고 |
|------|-----------|----|------|
| 비밀·부팅 필수 | `stock-platform.env` | `DB_*`, `JWT_SECRET`, `ADMIN_API_KEY`, 키움 키 | 프로세스 기동 시 로드 |
| 운영 튜닝 | DB `operation.app_setting` | Ollama 모델, risk·scheduler 일부 | Admin Settings UI · 이력 보관 |
| 프론트 공개 | `frontend/.env.local` | `NEXT_PUBLIC_API_BASE_URL` | 브라우저에 노출됨 |

카탈로그 키 목록: `src/stock_platform/operation/setting_catalog.py`

---

## 2. 필수

| 키 | 설명 |
|----|------|
| `DB_HOST` / `PORT` / `NAME` / `USER` / `PASSWORD` | PostgreSQL |
| `APP_ENV` | `local` / `prod` 등 |
| `JWT_SECRET` | 로그인·토큰 서명 (비우면 HTTP 로그인 불가) |

---

## 3. 인증 / 권한 (JWT)

| 키 | 기본 | 설명 |
|----|------|------|
| `JWT_SECRET` | (운영 필수) | HS256 서명 키. Git/프론트에 넣지 말 것 |
| `JWT_ALGORITHM` | HS256 | |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | 60 (예제) | Access 토큰 수명(분). 코드 기본 30 |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | 30 (예제) | Refresh 수명(일). 코드 기본 7 |
| `JWT_DEV_AUTO_SECRET` | true | **local/dev만**: Secret 없을 때 기동 시 임시 생성 |
| `AUTH_BOOTSTRAP_ADMIN_USERNAME` | | 사용자 0명일 때만 최초 admin |
| `AUTH_BOOTSTRAP_ADMIN_PASSWORD` | | 위와 함께 설정 |
| `ADMIN_API_KEY` | (빈 값=로컬 통과) | `X-Admin-API-Key` |

### JWT_SECRET 동작

| `APP_ENV` | `JWT_SECRET` 비어 있음 | 결과 |
|-----------|------------------------|------|
| `local` / `dev` / `development` | + `JWT_DEV_AUTO_SECRET=true` | 임시 Secret 자동 생성(경고 로그) |
| `local` … | + `JWT_DEV_AUTO_SECRET=false` | 친절한 오류로 기동 중단 |
| `prod` / `production` / `staging` | (자동 생성 **불가**) | 친절한 오류로 기동 중단 |

템플릿: `stock-platform.env.example` → `E:\StockTrading\secrets\stock-platform.env`

Admin Web: **JWT 로그인** (`/login`).  
스크립트: Admin Key **또는** admin JWT.

---

## 4. Broker (키움)

| 키 | 기본 | 설명 |
|----|------|------|
| `KIWOOM_USE_MOCK` | true | 모의 API |
| `KIWOOM_LIVE_ORDER_ENABLED` | false | 실전 주문 허용 |
| `KIWOOM_ACCOUNT_NUMBER` | | 계좌번호 (Risk 가드에도 사용) |
| `KIWOOM_APP_KEY` / `KIWOOM_SECRET_KEY` | | REST 인증 |
| `KIWOOM_RECOVERY_START_WS` | false | 기동 시 주문 WS (모의는 false 권장) |
| `KIWOOM_WS_MAX_CONSECUTIVE_FAILURES` | 8 | WS 연속 실패 한도 |

**교차 규칙:** `KIWOOM_LIVE_ORDER_ENABLED=true` 와 `KIWOOM_USE_MOCK=true` 동시 설정 시 기동 실패.  
실전은 live-transition 승인 + 위 live 플래그 모두 필요.

---

## 5. AI / 데이터

| 키 | 설명 |
|----|------|
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | 로컬 LLM |
| `UPBIT_BASE_URL` | 업비트 REST |
| `DART_API_KEY` | 공시 |
| `NAVER_CLIENT_ID` / `SECRET` | 뉴스 |

일부 Ollama·risk·scheduler 값은 DB Settings로도 관리합니다.

---

## 6. 운영 / 스케줄러

| 키 | 설명 |
|----|------|
| `SCHEDULER_ENABLED` | 별도 `run_scheduler.py` 사용 여부 |
| `SCHEDULER_*` | 후보·AI·포지션 시각·한도 등 (`.env.example` 참고) |
| `TELEGRAM_*` / `SLACK_*` / `DISCORD_*` | 알림 |

---

## 7. 보안 기본값 (권장)

- 실전 주문 OFF (`KIWOOM_LIVE_ORDER_ENABLED=false`)
- Kiwoom mock ON
- `JWT_SECRET` · `ADMIN_API_KEY` 운영에서 반드시 설정
- 프론트에 서버 비밀 키 노출 금지

상세 예시: 루트 `.env.example`
