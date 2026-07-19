# PROJECT_STATUS

> 최종 갱신: 2026-07-19 · Release **v1.0.0**

## 현재 상태

| 영역 | 상태 |
|------|------|
| Backend API | v1.0.0 (`stock_platform.api.main:app`) |
| Alembic head | `a2b3c4d5e6f7` (운영 시 `alembic current`로 확인) |
| Live trading | 기본 차단 (`KIWOOM_LIVE_ORDER_ENABLED=false`) |
| Admin frontend | STEP41 골격 (`frontend/`) |
| 문서 체계 | `docs/README.md` 목차 · 과거 STEP는 `docs/archive/` |

## 완료된 주요 구간

- **STEP16~34**: 브로커·주문·리스크·시장·전략 등 기능 단위 (아카이브: `docs/archive/steps/`)
- **STEP35~40**: 운영 통합, health/dashboard, 주문 파이프라인, 릴리스 문서
- **STEP41**: Next.js Admin 기초 (레이아웃·테마·API client·AUTH disabled)

## 진행 중 / 다음

- **STEP42**: Admin Dashboard 실데이터 (`/health`, `/api/v1/system/dashboard` 등)
- 계좌번호 설정과 키움 스냅샷 번호 정합 (`KIWOOM_ACCOUNT_NUMBER`)
- `TODO(STEP50)`: 실인증(JWT/`/me`)

## 문서 진입점

- [docs/README.md](docs/README.md)
- [CHANGELOG.md](CHANGELOG.md)
- [frontend/README.md](frontend/README.md)
