# Changelog

모든 주목할 만한 변경은 이 파일에 기록합니다.  
형식은 [Keep a Changelog](https://keepachangelog.com/) 스타일을 따릅니다.

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
