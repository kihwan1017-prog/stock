# Kiki Trade AI

> AI ?? ??·???? ?? ???  
> **Current release: v1.0.0** · Live orders blocked by default (`KIWOOM_LIVE_ORDER_ENABLED=false`)

?? ?? ??: **[docs/README.md](docs/README.md)**

---

## ???? ??

Kiki Trade AI? ?? ??(?? REST)? ????(Upbit)? ??? ????? ??·?????? AI ?? ???????.

AI? ??·??·?? ???? ????, ?? ??? Risk Engine ?? ??? Broker? ?????.

---

## ????

??: [docs/architecture/README.md](docs/architecture/README.md) · [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md)

```text
Admin (Next.js) ??? FastAPI
                      ?
         ???????????????????????????
      Market/AI    Orders/Risk   Ops/Jobs
         ???????????????????????????
                      ?
              PostgreSQL (+ pgvector)
                      ?
              Kiwoom / Upbit
```

---

## ????

| ?? | ?? |
|------|------|
| OS | Windows 11 |
| Backend | Python 3.12, FastAPI |
| Frontend | Node.js 20+, Next.js 16 |
| Database | PostgreSQL 17 (Windows ???, **Docker ??**) |
| AI | Ollama + Qwen |
| IDE | Cursor |

---

## ?? ??

1. [??](docs/deployment/INSTALL.md)
2. [??](docs/deployment/CONFIGURATION.md)
3. Backend:
   ```powershell
   $env:PYTHONPATH = "D:\Projects\stock-platform\src"
   uvicorn stock_platform.api.main:app --reload --app-dir src --host 127.0.0.1 --port 8000
   ```
4. Admin (??): [frontend/README.md](frontend/README.md) ? `npm run dev`
5. [?? ??](docs/trading/PAPER_DAY1_CHECKLIST.md) · [?? Runbook](docs/trading/OPERATIONS_RUNBOOK.md)
6. ??? ??: `.\scripts\verify_release.ps1`

- API Docs: http://127.0.0.1:8000/docs  
- Admin: http://localhost:3000  

---

## Backend

- ???: `stock_platform.api.main:app`
- ??: [docs/backend/README.md](docs/backend/README.md) · [docs/backend/API.md](docs/backend/API.md)
- OpenAPI: `/docs`, `/openapi.json`
- Health: `GET /health`

---

## Frontend

- ??: `frontend/` (STEP41 Admin)
- ??: [docs/frontend/README.md](docs/frontend/README.md) · [frontend/README.md](frontend/README.md)
- ??: [docs/reference/STEP41_ADMIN_FOUNDATION.md](docs/reference/STEP41_ADMIN_FOUNDATION.md)
- ?? ?? ??: `NEXT_PUBLIC_AUTH_MODE=disabled`

---

## Database

- ??: [docs/database/README.md](docs/database/README.md)
- ??: [docs/database/DB_DEVELOPMENT_RULES.md](docs/database/DB_DEVELOPMENT_RULES.md)
- Canonical Alembic: `database/alembic/versions/`
- Overlay ?? ??: [docs/database/MIGRATION_OVERLAYS.md](docs/database/MIGRATION_OVERLAYS.md)

---

## API

- ??: [docs/backend/API.md](docs/backend/API.md)
- ??: http://127.0.0.1:8000/docs
- ?? API: ?? `X-Admin-API-Key` (`ADMIN_API_KEY`)

---

## AI

- ???: [docs/ai/README.md](docs/ai/README.md)
- ??·?? API? OpenAPI? `/api/v1/ai-*`, `/api/v1/candidates` ??
- ???: Ollama (??)

---

## Trading

- ??: [docs/trading/README.md](docs/trading/README.md)
- ??: [OPERATIONS_RUNBOOK](docs/trading/OPERATIONS_RUNBOOK.md)
- ??: [LIVE_TRADING_CHECKLIST](docs/trading/LIVE_TRADING_CHECKLIST.md)
- ??? `OrderExecutionService` ? Outbox ? Broker

---

## Deployment

- ??: [docs/deployment/README.md](docs/deployment/README.md)
- [INSTALL](docs/deployment/INSTALL.md) · [CONFIGURATION](docs/deployment/CONFIGURATION.md) · [RELEASE_CHECKLIST](docs/deployment/RELEASE_CHECKLIST.md)

---

## Documentation

?? ??: **[docs/README.md](docs/README.md)**  
?? ???: **[docs/manual/README.md](docs/manual/README.md)**

??: [docs/development/README.md](docs/development/README.md)  
??: [docs/reference/README.md](docs/reference/README.md)

---

## Archive

?? STEP ?? ??·obsolete ???: [docs/archive/README.md](docs/archive/README.md)

- Steps catalog: [docs/archive/steps/README.md](docs/archive/steps/README.md)
- Obsolete: [docs/archive/obsolete/README.md](docs/archive/obsolete/README.md)

?? ?? SoT? ????.

---

## ChangeLog

?? ??: **[CHANGELOG.md](CHANGELOG.md)** · ??: [PROJECT_STATUS.md](PROJECT_STATUS.md)

---

## ???? ??

```text
stock-platform
??? src/                 # FastAPI
??? frontend/            # Admin (Next.js)
??? tests/
??? database/alembic/    # Canonical migrations
??? docs/                # Domain documentation
??? scripts/
??? README.md
??? CHANGELOG.md
??? AGENTS.md            # Agent workspace (not product docs)
```

---

## ????

Private Project · Copyright © 2026 Kiki Trade AI
