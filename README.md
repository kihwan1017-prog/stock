# Kiki Trade AI

AI 기반 주식(키움)·암호화폐(Upbit)·Paper 자동매매 플랫폼.

**운영 준비: NOT READY** · **LIVE: NOT APPROVED** · Paper 무인: **NOT READY**  
근거: [docs/PROJECT_IMPLEMENTATION_STATUS.md](docs/PROJECT_IMPLEMENTATION_STATUS.md)

SoT: [AGENTS.md](AGENTS.md) · 문서 포털: [docs/README.md](docs/README.md)

---

## 주요 기능

- 시세·스크리닝·AI 분석 · 전략 수명주기 · 리스크 · 주문(Outbox) · Broker 연동
- Admin/User Next.js · FastAPI · PostgreSQL
- Upbit / Kiwoom / Paper 런타임 · Shadow 연구 · Daily Report · Observability

---

## 실행 (개발)

설정: `.env.example` · [docs/deployment/CONFIGURATION.md](docs/deployment/CONFIGURATION.md)  
시크릿 관례 경로: `E:\StockTrading\secrets\stock-platform.env` (값을 문서에 넣지 말 것)

```powershell
# Backend
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
uvicorn stock_platform.api.main:app --reload --app-dir src --host 127.0.0.1 --port 8000

# Frontend
cd frontend; npm run dev
```

- API: http://127.0.0.1:8000/docs · Health: `/health/live` · `/health/ready`
- Admin: http://localhost:3000

---

## 문서 (canonical)

| 문서 | 역할 |
|------|------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 구조 |
| [docs/AUTO_TRADING.md](docs/AUTO_TRADING.md) | 자동매매 정책 요약 |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | 기동·ops-status·재시작 |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | 개발·문서 정책 |
| [docs/DATABASE.md](docs/DATABASE.md) | DB / Alembic |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | 장애 점검 |
| [CHANGELOG.md](CHANGELOG.md) | 사용자 영향 milestone |
| [docs/CURRENT_WORK.md](docs/CURRENT_WORK.md) | 현재 작업 |
| [docs/AI_TRADING_SAFETY.md](docs/AI_TRADING_SAFETY.md) | LIVE/PAPER 안전 |

과거 root STEP/AUDIT/RUNBOOK은 [docs/archive/2026-08/root-portal/](docs/archive/2026-08/root-portal/).

---

## 운영 주의

- LIVE 기본 OFF · fail-closed · 실주문은 **명시 승인**만
- Runtime 상태 SoT = HTTP **ops-status** (CLI singleton 금지)
- 공개망 직접 노출 금지 · 시크릿을 채팅/문서에 붙이지 말 것

---

## 디렉터리

```text
src/  frontend/  tests/  database/alembic/  docs/  ops/  scripts/  .run/
```

`.run/` = runtime evidence (Git ignore). 소스 문서와 구분.

라이선스: [LICENSE](LICENSE)
