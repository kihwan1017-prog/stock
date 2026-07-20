# Kiki Trade AI

> AI 기반 주식·암호화폐 자동매매 플랫폼  
> **Current release: v1.0.0** · Live 주문 기본 차단 (`KIWOOM_LIVE_ORDER_ENABLED=false`)

문서 포털: **[docs/README.md](docs/README.md)**

---

## 한줄 소개

Kiki Trade AI는 국내 주식(키움 REST)과 암호화폐(Upbit)를 대상으로 시세·지표·스크리닝·AI 분석을 결합한 자동매매 플랫폼입니다.  
주문은 Risk Engine·Kill Switch를 거친 뒤 Broker(Outbox)로만 전달됩니다.

---

## 아키텍처

상세: [ARCHITECTURE.md](ARCHITECTURE.md) · [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md)

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

## 스택

| 구성 | 버전 |
|------|------|
| OS | Windows 10/11 |
| Backend | Python 3.12, FastAPI |
| Frontend | Node.js 20+, Next.js 16 |
| Database | PostgreSQL 16/17 (Windows Service, **Docker 없음**) |
| AI | Ollama + Qwen (로컬) |
| 버전 | **1.0.0** (`APP_VERSION` / `GET /version`) |

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

## 인증

시크릿 기본 경로:

```text
E:\StockTrading\secrets\stock-platform.env
```

| 환경 | `JWT_SECRET` 미설정 시 |
|------|------------------------|
| `APP_ENV=local` + `JWT_DEV_AUTO_SECRET=true` | 임시 시크릿 자동 생성 (경고 로그) |
| `production` / `staging` | 기동 실패 |

상세: [SECURITY.md](SECURITY.md) · [docs/deployment/CONFIGURATION.md](docs/deployment/CONFIGURATION.md)

---

## 문서 인덱스 (v1.0.0)

| 문서 | 용도 |
|------|------|
| [CHANGELOG.md](CHANGELOG.md) | 변경 이력 |
| [RELEASE_NOTE_v1.0.0.md](RELEASE_NOTE_v1.0.0.md) | 릴리즈 노트 |
| [API.md](API.md) | API 개요 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 아키텍처 |
| [DB_SCHEMA.md](DB_SCHEMA.md) | DB 스키마 |
| [SECURITY.md](SECURITY.md) | 보안 |
| [BACKUP.md](BACKUP.md) / [RECOVERY.md](RECOVERY.md) | 백업·복구 |
| [RUNBOOK.md](RUNBOOK.md) | 일상 운영 |
| [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) | 장애 대응 |
| [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md) | Go-Live |
| [KNOWN_ISSUES.md](KNOWN_ISSUES.md) | 알려진 이슈 |
| [FINAL_PRODUCT_REPORT.md](FINAL_PRODUCT_REPORT.md) | 제품 최종 보고서 |
| [LICENSE](LICENSE) | 라이선스 |

한글 매뉴얼: [docs/manual/README.md](docs/manual/README.md)

---

## 배포 전제 (중요)

v1.0.0은 다음을 전제로 **RELEASE WITH KNOWN ISSUES** 입니다.

- **공개 인터넷 직접 노출 금지** (VPN / 사설망 / 역프록시)
- **Live 주문 기본 OFF** — 고객 SaaS Live는 STEP63 감사상 차단
- 단일 운영자 · Windows 단일 인스턴스 · Paper 중심

---

## 디렉터리

```text
stock-platform/
├── src/                 # FastAPI
├── frontend/            # Admin (Next.js)
├── tests/
├── database/alembic/    # Canonical migrations
├── ops/                 # Windows 운영 스크립트
├── docs/                # 도메인 문서
├── scripts/
├── LICENSE
├── README.md
└── CHANGELOG.md
```

---

## 라이선스

Private Project · Copyright © 2026 Kiki Trade AI — 자세한 내용 [LICENSE](LICENSE)
