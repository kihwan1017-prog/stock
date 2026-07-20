# Changelog

모든 주목할 만한 변경은 이 파일에 기록합니다.  
형식은 [Keep a Changelog](https://keepachangelog.com/) 스타일을 따릅니다.

---

## [1.1.0] — 2026-07-21

### Added — User Platform (STEP65–STEP73)

- **STEP65** User Account Ownership — Paper/Broker 계좌 Self API, 마스킹, 기본 계좌
- **STEP66** Portfolio Asset History — Snapshot, 기간 수익률, MDD
- **STEP67** User Watchlist — 관심종목 CRUD (flat), 시장·중복 방지
- **STEP68** Watchlist News — 공용 뉴스 + 사용자 읽음/북마크 상태
- **STEP69** Watchlist Disclosures & AI Summary — 공시·사용자용 요약 (admin settings 불필요)
- **STEP70** User AI Recommendation — 후보 검증·Ollama 분리·주문 비연결
- **STEP71** Notification Center — Inbox, 읽음/보관/중요, 구독, Dispatcher→Telegram 큐
- **STEP72** User Preferences — Theme/Language/Timezone/기본 계좌·시장 (admin Settings 분리)
- **STEP73** My Profile / Security / Sessions / Connections — 프로필·비밀번호·세션·연결 요약
- **STEP74** User Integration Audit — Quiet Time 적용, admin 래퍼 제거, UAT/Security 문서

### Security

- 사용자 Self API와 Admin Settings/Ollama/Users API 경계 강화
- JWT `user_id` 기반 소유권 (Body user_id 미신뢰)
- 세션 public id, IP/계좌/이메일/Chat ID 마스킹
- 비밀번호 변경 Rate Limit · 타 세션 revoke
- Notification Quiet Time (Telegram 억제, CRITICAL 예외)

### Changed

- `APP_VERSION` / Frontend `package.json` → **1.1.0**
- Alembic head: `g3b4c5d6e7f8` (STEP65–73 migrations)
- Release 판정 기반: STEP74 **CONDITIONAL APPROVAL**

### Migration

운영 DB는 **수동** `alembic upgrade head` (자동 적용 금지).  
체인: `e5f6a7b8c9d0` … `g3b4c5d6e7f8`

### Breaking Changes

- 없음 (기존 Admin/Paper/Ops API 계약 유지). 신규는 `/api/v1/user/*` 추가.

### Known Issues

- Telegram QUEUED→SENT/DLQ worker 미구현
- Watchlist 그룹 테이블 없음
- `/user/trading|strategies|auto-trading` 일부 Unimplemented / admin realtime 혼재
- Playwright E2E 미자동화
- npm `postcss` moderate (next 종속)
- 상세: `docs/archive/steps/RELEASE_RISK_STEP74.md`

### Freeze (STEP75)

- Migration Freeze · Prompt Version Freeze · API 계약 변경 금지

---

## [1.0.0] — 2026-07-20

### Added
- Auth / JWT / RBAC / Admin·User Web (Next.js)
- Paper 주문·포지션 · Order Outbox · Kill Switch · Daily Loss Monitor
- Position Exit Monitor · Telegram Ops · Notification Publisher
- Ollama AI 분석 · News/Disclosure · Strategy Deployment
- Operations Center · Settings Catalog · Monitoring overview/alerts (STEP61)
- Windows 운영 패키지 `ops/` + NSSM 가이드 (STEP60)
- Health: `/health/live`, `/health/ready` · 강화된 `/version`
- 제품 매뉴얼 (`docs/manual/`) · 운영 Runbook / Incident / Go-Live 체크리스트

### Security
- Live 주문 기본 차단 (`KIWOOM_LIVE_ORDER_ENABLED=false`)
- LIVE adapter는 DB transition 승인 필요
- STEP59/62: 다수 민감 mutate → `require_admin` (DB RBAC)
- 운영 Swagger/OpenAPI 비활성 · 공개 Signup 403
- JWT HS256 only · Refresh reuse 시 세션 일괄 폐기
- Rate limit · Security headers · CORS 축소 · 로그/감사 마스킹
- Order account ownership 검사 (IDOR 완화)
- Telegram webhook Secret-Token 검증 (설정 시)

### Performance
- STEP58: DB pool 명시 · Exit Monitor `to_thread` · Ollama tags TTL · lifecycle 알림 timeout

### Changed / Refactor
- STEP56 Technical Debt Cleanup
- STEP57 DB FK/Index/Comment 안정화
- 에러 응답 통일 `{code,message,detail,request_id}`
- OpenAPI / root `/` 버전 문자열을 `APP_VERSION`(=1.0.0)과 동기화
- Frontend `package.json` version → `1.0.0`

### Removed
- OpenClaw 연동 (범위 제외)
- DEV_OPEN (미설정 Admin Key로 Admin 개방) 제거

### Breaking Changes
| 변경 | 영향 |
|------|------|
| 민감 Broker/Realtime mutate → Admin 필수 | 스크립트에 `ADMIN_API_KEY` 또는 Admin JWT 필요 |
| 운영 `/docs` 비활성 | OpenAPI는 local/staging에서만 |
| 운영 Signup 403 | 사용자는 Admin Users API로 생성 |
| 운영 CORS localhost 단독 거부 | 실제 Origin 필수 |

### Known Issues
상세: [KNOWN_ISSUES.md](KNOWN_ISSUES.md) · [FINAL_AUDIT_REPORT.md](FINAL_AUDIT_REPORT.md)

- 일부 mutate API(pipeline/AI/sync/strategy-runtime 등) 무인증 잔존 → **공개망 배포 금지**
- Order Outbox 기본 `PaperBrokerAdapter` 고정
- Telegram webhook secret 미설정 시 검증 스킵 (fail-open)
- `account_id=1` 하드코딩 경로 잔존
- Live broker E2E 테스트 부재
- Docker/HA 없음 (의도: Windows 단일 인스턴스)

### Notes
- PostgreSQL Windows Service only (no Docker)
- Canonical Alembic: `database/alembic/versions/`
- 릴리즈 결정: **RELEASE WITH KNOWN ISSUES** (사설망 · Paper · Live OFF)

---

## [1.0.0-RC1] — 2026-07-20

Release Candidate. 내용 요약은 [RELEASE_NOTE_v1.0.0_RC1.md](RELEASE_NOTE_v1.0.0_RC1.md).

### Docs (pre-GA)
- Domain documentation refactor under `docs/`
- Product manuals under `docs/manual/`
- STEP59–63 감사·보안·모니터링 문서

---

## Unreleased

(다음 마이너/패치용 — 현재 비움)
