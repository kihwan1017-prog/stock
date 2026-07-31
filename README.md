# Kiki Trade AI

> AI 기반 주식·암호화폐 자동매매 플랫폼  
> **Current release packaging: v1.1.0** · Branch `release/v1.1.0` · Commit baseline `3554ef8`

**⚠️ 운영 준비 상태가 아닙니다.**  
자동매매 운영: **NOT READY** · LIVE 거래: **NOT APPROVED** · Paper 무인 자동매매: **NOT READY**  
(수치·근거: [docs/PROJECT_IMPLEMENTATION_STATUS.md](docs/PROJECT_IMPLEMENTATION_STATUS.md) — 추정치)

문서 포털: **[docs/README.md](docs/README.md)** · AI/개발 SoT: **[AGENTS.md](AGENTS.md)** · Claude: **[CLAUDE.md](CLAUDE.md)**

---

## 한줄 소개

Kiki Trade AI는 국내 주식(키움 REST)과 암호화폐(Upbit), Paper 계좌를 대상으로  
시세·지표·스크리닝·AI 분석·전략 수명주기·리스크·주문을 다루는 플랫폼입니다.  
주문은 Risk Engine·Kill Switch를 거친 뒤 Broker(Outbox)로만 전달되는 것이 설계 목표입니다.

---

## 현재 상태 경고

| 항목 | 상태 (2026-07-31 추정치) |
|------|--------------------------|
| 개발 구현률 | ~76% |
| Paper 자동매매 준비도 | ~72% |
| LIVE 자동매매 준비도 | ~48% |
| LIVE 주문 기본 | OFF (`KIWOOM_LIVE_ORDER_ENABLED` 등 fail-closed) |

**P0 Blocking:** P0-1 Realtime `broker_code` 하드코딩 · P0-2 Kiwoom Fill→Position 단절 · P0-3 STEP12↔Runtime 불일치 · P0-4 Alembic Head 불일치 · P0-5 Paper Outbox 자동 Fill 부재  
→ [docs/ROADMAP.md](docs/ROADMAP.md)

워킹트리에 미커밋 STEP12·FE·Migration이 있을 수 있습니다. 배포 완료로 오해하지 마세요.

---

## Canonical 문서 (Source of Truth)

| 문서 | 역할 |
|------|------|
| [AGENTS.md](AGENTS.md) | AI/개발 공통 최상위 규칙 |
| [CLAUDE.md](CLAUDE.md) | Claude Code Bootstrap |
| [docs/CURRENT_WORK.md](docs/CURRENT_WORK.md) | 현재 작업만 |
| [docs/PROJECT_IMPLEMENTATION_STATUS.md](docs/PROJECT_IMPLEMENTATION_STATUS.md) | 구현 현황 SoT |
| [docs/STEP_MASTER_STATUS.md](docs/STEP_MASTER_STATUS.md) | STEP 상태 SoT |
| [docs/ROADMAP.md](docs/ROADMAP.md) | P0–P5 잔여 작업 |
| [docs/DECISION_LOG.md](docs/DECISION_LOG.md) | 장기 설계 결정 |
| [docs/architecture/STRATEGY_LIFECYCLE_STEP12.md](docs/architecture/STRATEGY_LIFECYCLE_STEP12.md) | Strategy Lifecycle STEP12 |

과거 릴리즈·감사 문서와 수치가 충돌하면 **Canonical + 실제 소스**를 우선합니다.

---

## 아키텍처

상세: [ARCHITECTURE.md](ARCHITECTURE.md) · [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) · [docs/AI_ARCHITECTURE.md](docs/AI_ARCHITECTURE.md)

```text
Admin/User (Next.js) ──► FastAPI
                            │
               Market/AI · Risk · Orders · Ops
                            ▼
                    PostgreSQL (+ pgvector)
                            │
                    Kiwoom / Upbit / Paper
```

---

## 스택

| 구성 | 버전 |
|------|------|
| OS | Windows 10/11 |
| Backend | Python 3.12, FastAPI (`src/stock_platform/`) |
| Frontend | Node.js 20+, Next.js (`frontend/`) |
| Database | PostgreSQL 16/17 (Windows Service, **Docker 없음**) |
| AI | Ollama + Qwen (로컬) · Mock Provider 기본 |
| 버전 | **1.1.0** (`APP_VERSION` / `GET /version`) |

---

## 빠른 시작

1. [INSTALL.md](INSTALL.md) · [docs/deployment/INSTALL.md](docs/deployment/INSTALL.md)
2. 설정: [docs/deployment/CONFIGURATION.md](docs/deployment/CONFIGURATION.md) · `.env.example`
3. Backend:
   ```powershell
   $env:PYTHONPATH = "D:\Projects\stock-platform\src"
   uvicorn stock_platform.api.main:app --reload --app-dir src --host 127.0.0.1 --port 8000
   ```
4. Admin: [frontend/README.md](frontend/README.md) → `npm run dev`
5. 운영: [OPERATIONS.md](OPERATIONS.md) · [RUNBOOK.md](RUNBOOK.md) · [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md)

- API Docs (local): http://127.0.0.1:8000/docs  
- Admin: http://localhost:3000  
- Health: `GET /health/live` · `GET /health/ready` · `GET /version`

---

## 안전 주의사항

- **LIVE 주문 기본 OFF** — 명시 승인 없이 실주문·Broker 로그인·Runtime 무단 기동 금지
- 공개 인터넷 직접 노출 금지 (VPN / 사설망 / 역프록시)
- 시크릿·API 키를 문서·로그·채팅에 붙이지 말 것
- 상세: [docs/AI_TRADING_SAFETY.md](docs/AI_TRADING_SAFETY.md) · [SECURITY.md](SECURITY.md)

시크릿 기본 경로(로컬 운영 관례):

```text
E:\StockTrading\secrets\stock-platform.env
```

| 환경 | `JWT_SECRET` 미설정 시 |
|------|------------------------|
| `APP_ENV=local` + `JWT_DEV_AUTO_SECRET=true` | 임시 시크릿 자동 생성 (경고 로그) |
| `production` / `staging` | 기동 실패 |

---

## 문서 인덱스 (v1.1.0 Historical)

| 문서 | 용도 |
|------|------|
| [CHANGELOG.md](CHANGELOG.md) | 변경 이력 |
| [RELEASE_NOTE_v1.1.0.md](docs/archive/completion-reports/RELEASE_NOTE_v1.1.0.md) | v1.1.0 릴리즈 노트 (Historical) |
| [FINAL_RELEASE_REPORT_v1.1.0.md](docs/archive/completion-reports/FINAL_RELEASE_REPORT_v1.1.0.md) | 최종 릴리즈 보고 (Historical) |
| [docs/deployment/DEPLOY_v1.1.0.md](docs/deployment/DEPLOY_v1.1.0.md) | 배포 가이드 |
| [API.md](API.md) | API 개요 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 아키텍처 |
| [docs/archive/steps/README_STEP74.md](docs/archive/steps/README_STEP74.md) | 사용자 통합 감사 |
| [docs/archive/steps/README_STEP75.md](docs/archive/steps/README_STEP75.md) | v1.1.0 Release |
| [LICENSE](LICENSE) | 라이선스 |

한글 매뉴얼: [docs/manual/README.md](docs/manual/README.md)

v1.1.0 STEP74 **CONDITIONAL APPROVAL** 전제(사설망·Live OFF·단일 운영자)는 유효하나,  
**자동매매 완료·LIVE 승인으로 해석하지 마세요.**

---

## 디렉터리

```text
stock-platform/
├── src/                 # FastAPI
├── frontend/            # Admin/User (Next.js)
├── tests/
├── database/alembic/    # Canonical migrations
├── ops/                 # Windows 운영 스크립트
├── docs/                # Canonical + 도메인 문서
├── scripts/
├── AGENTS.md / CLAUDE.md
├── README.md
└── CHANGELOG.md
```

---

## 라이선스

Private Project · Copyright © 2026 Kiki Trade AI — 자세한 내용 [LICENSE](LICENSE)
