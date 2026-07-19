# Documentation Index — stock-platform

> 현재 유효 문서의 목차입니다.  
> **v1.0.0** 기준 · Docker 미사용 · PostgreSQL Windows 서비스

---

## 1. 빠른 시작 (운영)

| 문서 | 설명 |
|------|------|
| [INSTALL.md](INSTALL.md) | 설치 |
| [CONFIGURATION.md](CONFIGURATION.md) | 환경변수·설정 |
| [PAPER_DAY1_CHECKLIST.md](PAPER_DAY1_CHECKLIST.md) | 모의 첫날 15분 점검 |
| [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md) | 일일 운영 Runbook |
| [LIVE_TRADING_CHECKLIST.md](LIVE_TRADING_CHECKLIST.md) | 실전 전환 체크리스트 |
| [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) | 장애 대응 |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 트러블슈팅 |
| [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) | 릴리스 체크리스트 |

루트 진입점: [../README.md](../README.md) · Changelog: [../CHANGELOG.md](../CHANGELOG.md)

---

## 2. 설계·API

| 문서 | 설명 |
|------|------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 아키텍처 개요 |
| [API.md](API.md) | API 요약 (상세는 OpenAPI `/docs`) |
| [ERD.md](ERD.md) | ERD 개요 |

OpenAPI: `http://127.0.0.1:8000/docs`

---

## 3. 개발 규칙

| 문서 | 설명 |
|------|------|
| [development/DB_DEVELOPMENT_RULES.md](development/DB_DEVELOPMENT_RULES.md) | DB/Alembic/스키마 규칙 |
| [development/DOMAIN_PACKAGE_MAP.md](development/DOMAIN_PACKAGE_MAP.md) | 도메인 패키지 맵 |
| [development/ALEMBIC_VERIFY.md](development/ALEMBIC_VERIFY.md) | Alembic 검증 |
| [development/LEGACY_DB_OBJECTS.md](development/LEGACY_DB_OBJECTS.md) | ORM 미등록 Legacy 객체 |
| [development/STEP35_TEST_SUMMARY.md](development/STEP35_TEST_SUMMARY.md) | STEP35 테스트 요약 |
| [development/STEP36_DB_CHANGE_PLAN.md](development/STEP36_DB_CHANGE_PLAN.md) | STEP36 DB 계획 |

표준 마이그레이션 경로: `database/alembic/versions/`  
참고용 overlay: [migration-overlays/README.md](migration-overlays/README.md)

---

## 4. 로드맵

| 문서 | 설명 |
|------|------|
| [roadmaps/STEP35_TO_STEP40_DEVELOPMENT_ROADMAP.md](roadmaps/STEP35_TO_STEP40_DEVELOPMENT_ROADMAP.md) | STEP35~40 통합·v1.0 (완료) |
| [roadmaps/STEP41_ADMIN_FOUNDATION.md](roadmaps/STEP41_ADMIN_FOUNDATION.md) | Admin 웹 기초 (STEP41) |

Admin 앱 실행: [../frontend/README.md](../frontend/README.md)

---

## 5. 아카이브 (과거 작업 로그)

현재 운영 SoT가 **아닙니다**. 재현·히스토리용입니다.

| 경로 | 내용 |
|------|------|
| [archive/README.md](archive/README.md) | 아카이브 안내 |
| [archive/steps/](archive/steps/) | `README_STEP16`~`34` 작업 지시서 |
| [archive/step34-apply/](archive/step34-apply/) | STEP34 번호형 적용 가이드 (`01_`~`07_`) |
| [archive/notes/](archive/notes/) | 적용 메모 |

설치·Alembic·트리는 아카이브가 아니라 위 **§1·§3** 문서를 사용하세요.

---

## 6. 문서 체계 규칙

1. **현재 유효 문서**는 이 목차(`docs/README.md`)에만 올린다.
2. 새 STEP 지시서는 `docs/roadmaps/` 또는 완료 후 `docs/archive/steps/`로 둔다.
3. 루트에는 `README.md`, `CHANGELOG.md`, `PROJECT_STATUS.md`, Agent 문서(`AGENTS.md` 등)만 유지한다.
4. API 상세는 Markdown 복제보다 OpenAPI를 우선한다.
5. Docker 관련 문서는 추가하지 않는다.
