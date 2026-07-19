# Kiki Trade AI

> AI 기반 주식 및 가상자산 투자 플랫폼  
> **Current release: v1.0.0**

---

## 문서 목차 (시작점)

**전체 문서 인덱스:** [docs/README.md](docs/README.md)

| 구분 | 링크 |
|------|------|
| 설치·설정 | [docs/INSTALL.md](docs/INSTALL.md) · [docs/CONFIGURATION.md](docs/CONFIGURATION.md) |
| 운영 | [docs/OPERATIONS_RUNBOOK.md](docs/OPERATIONS_RUNBOOK.md) · [docs/PAPER_DAY1_CHECKLIST.md](docs/PAPER_DAY1_CHECKLIST.md) |
| 실전 | [docs/LIVE_TRADING_CHECKLIST.md](docs/LIVE_TRADING_CHECKLIST.md) |
| DB 규칙 | [docs/development/DB_DEVELOPMENT_RULES.md](docs/development/DB_DEVELOPMENT_RULES.md) |
| Admin 웹 | [frontend/README.md](frontend/README.md) |
| 로드맵 | [docs/roadmaps/](docs/roadmaps/) |
| 과거 STEP 로그 | [docs/archive/](docs/archive/) (아카이브) |
| 변경 이력 | [CHANGELOG.md](CHANGELOG.md) · [PROJECT_STATUS.md](PROJECT_STATUS.md) |

실전 주문은 기본 차단입니다 (`KIWOOM_LIVE_ORDER_ENABLED=false`).

---

## 프로젝트 소개

Kiki Trade AI는 국내 주식(키움증권 REST API)과 가상자산(Upbit API)을 하나의 플랫폼에서 분석하고 자동매매할 수 있는 AI 투자 플랫폼입니다.

단순한 자동매매 프로그램이 아니라 AI 기반 투자 운영체제(AI Investment Platform)를 목표로 합니다.

### v1.0 빠른 시작

1. [설치](docs/INSTALL.md)
2. [설정](docs/CONFIGURATION.md)
3. Backend: `uvicorn stock_platform.api.main:app --reload --app-dir src --host 127.0.0.1 --port 8000`
4. (선택) Admin: [frontend/README.md](frontend/README.md) → `npm run dev`
5. [운영 Runbook](docs/OPERATIONS_RUNBOOK.md)
6. 릴리스 검증: `.\scripts\verify_release.ps1`

- FastAPI Docs: http://127.0.0.1:8000/docs  
- Admin: http://localhost:3000  

---

## 프로젝트 목표

- AI 기반 뉴스·공시 분석
- AI Memory
- 전략 기반 자동매매
- 위험관리(Risk Engine)
- 백테스트
- 운영·투자 Dashboard (Admin: STEP41 골격, STEP42에서 실데이터)

---

## 시스템 아키텍처

상세: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

```text
Admin (Next.js) ──► FastAPI
                      │
         ┌────────────┼────────────┐
      Market/AI    Orders/Risk   Ops/Jobs
         └────────────┼────────────┘
                      ▼
              PostgreSQL (+ pgvector)
                      │
              Kiwoom / Upbit
```

---

## 기술 스택

| 분야 | 기술 |
|------|------|
| Language | Python 3.12 · TypeScript (Admin) |
| API | FastAPI |
| Admin UI | Next.js 16 · Ant Design |
| Database | PostgreSQL 17 · pgvector |
| AI Runtime | Ollama · Qwen |
| Stock / Crypto | Kiwoom REST · Upbit |
| IDE / VCS | Cursor · Git |

---

## 프로젝트 구조

```text
stock-platform
├── src/                 # FastAPI 백엔드
├── frontend/            # Admin 웹 (STEP41+)
├── tests/
├── database/alembic/    # Canonical migrations
├── docs/                # 문서 (목차: docs/README.md)
│   ├── development/     # DB·도메인 규칙
│   ├── roadmaps/        # STEP 로드맵
│   └── archive/         # 과거 README_STEPxx 등
├── scripts/
├── README.md
├── CHANGELOG.md
├── PROJECT_STATUS.md
└── AGENTS.md            # Agent 워크스페이스 규칙
```

---

## 개발 원칙

1. **문서 우선** — [docs/README.md](docs/README.md) → 설계 → 개발 → 테스트 → Commit  
2. **AI는 주문하지 않는다** — 분석·요약·제안만; 주문은 Risk Engine 승인 후 Broker  
3. **PostgreSQL 중심** — 거래·전략·로그·AI Memory  
4. **기능 하나 완료 → Commit 하나**  
5. **테스트 후 Commit**  
6. **Docker 사용 금지** (Windows PostgreSQL 서비스)

---

## 로드맵 상태

| Phase | 내용 | 상태 |
|-------|------|------|
| STEP16~34 | 기능 단위 구축 | 완료 (문서: [docs/archive/steps/](docs/archive/steps/)) |
| STEP35~40 | 통합·운영·v1.0 | 완료 ([로드맵](docs/roadmaps/STEP35_TO_STEP40_DEVELOPMENT_ROADMAP.md)) |
| STEP41 | Admin 기초 | 완료 ([스펙](docs/roadmaps/STEP41_ADMIN_FOUNDATION.md)) |
| STEP42 | Admin Dashboard 실데이터 | 예정 |

---

## 개발 환경

- Windows 11 · Python 3.12 · PostgreSQL 17 · Node.js 20+  
- Ollama · Cursor · Git  

---

## 라이선스

Private Project · Copyright © 2026 Kiki Trade AI
