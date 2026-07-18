# 설정 가이드 — stock-platform v1.0

환경파일: `E:\StockTrading\secrets\stock-platform.env`  
템플릿: `.env.example`

## 필수

| 키 | 설명 |
|----|------|
| `DB_HOST/PORT/NAME/USER/PASSWORD` | PostgreSQL |
| `APP_ENV` | local/prod |

## Broker

| 키 | 기본 | 설명 |
|----|------|------|
| `KIWOOM_USE_MOCK` | true | 모의/실서버 전환 |
| `KIWOOM_LIVE_ORDER_ENABLED` | false | 실전 주문 허용 |
| `KIWOOM_ACCOUNT_NUMBER` | | 계좌번호 |
| `KIWOOM_APP_KEY/SECRET_KEY` | | REST 인증 |

## AI / 데이터

| 키 | 설명 |
|----|------|
| `OLLAMA_BASE_URL/MODEL` | 로컬 LLM |
| `UPBIT_BASE_URL` | 업비트 REST |
| `DART_API_KEY` | 공시 |
| `NAVER_CLIENT_ID/SECRET` | 뉴스 |

## 운영

| 키 | 설명 |
|----|------|
| `ADMIN_API_KEY` | 관리 API (`X-Admin-API-Key`) |
| `TELEGRAM_*` / `SLACK_*` / `DISCORD_*` | 알림 |
| `SCHEDULER_ENABLED` | 스케줄러 |

## 보안 기본값

- 실전 주문 OFF
- Kiwoom mock ON
- 관리 API 키 미설정 시 로컬 개발만 통과(운영에서는 반드시 설정)
