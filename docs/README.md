# Documentation Index — stock-platform

> v1.0.0 · Docker 미사용 · PostgreSQL Windows 서비스  
> 루트 포털: [../README.md](../README.md)

## Domain folders

| Folder | Purpose |
|--------|---------|
| [architecture/](architecture/) | 시스템 아키텍처·도메인 맵 |
| [backend/](backend/) | FastAPI API 개요 |
| [frontend/](frontend/) | Admin 웹 문서 포인터 |
| [database/](database/) | ERD·DB 규칙·Alembic |
| [deployment/](deployment/) | 설치·설정·릴리스 |
| [development/](development/) | STEP 테스트·DB 변경 계획 |
| [trading/](trading/) | 운영·모의·실전·장애 |
| [ai/](ai/) | AI 관련 문서 인덱스 |
| [reference/](reference/) | 로드맵·문서 인벤토리 |
| [archive/](archive/) | 과거 STEP 로그·obsolete |

## Quick links

- Install: [deployment/INSTALL.md](deployment/INSTALL.md)
- Ops: [trading/OPERATIONS_RUNBOOK.md](trading/OPERATIONS_RUNBOOK.md)
- DB rules: [database/DB_DEVELOPMENT_RULES.md](database/DB_DEVELOPMENT_RULES.md)
- Admin: [../frontend/README.md](../frontend/README.md)
- Changelog: [../CHANGELOG.md](../CHANGELOG.md)

## Rules

1. 현재 유효 문서는 이 목차에 올린다.
2. **새 Markdown은 프로젝트 루트에 만들지 않는다.** `docs/` 하위 도메인 폴더에만 생성한다.
3. 새 문서를 만들면 **해당 폴더 `README.md`에 링크·한 줄 설명**을 추가한다. (주요 문서는 이 목차에도 반영)
4. STEP 작업 로그는 `archive/steps/`에만 둔다.
5. 삭제는 하지 않고 obsolete/notes로 이동한다.
6. API 상세는 OpenAPI `http://127.0.0.1:8000/docs` 우선.

루트 예외(포털/에이전트만): `README.md`, `CHANGELOG.md`, `PROJECT_STATUS.md`, `AGENTS.md` 등.  
상세 규칙: `.cursor/rules/documentation-structure.mdc`
