# database

## 목적

PostgreSQL 스키마, Alembic, Legacy 객체 규칙을 모아 둔다.

## 포함 문서

| 문서 | 설명 |
|------|------|
| [ERD.md](ERD.md) | ERD 개요 |
| [DB_DEVELOPMENT_RULES.md](DB_DEVELOPMENT_RULES.md) | DB 개발 규칙 (필수) |
| [ALEMBIC_VERIFY.md](ALEMBIC_VERIFY.md) | Alembic 검증 |
| [LEGACY_DB_OBJECTS.md](LEGACY_DB_OBJECTS.md) | ORM 미등록 객체 |
| [MIGRATION_OVERLAYS.md](MIGRATION_OVERLAYS.md) | overlay 참고·적용 금지 |
| [../manual/DB관리매뉴얼.md](../manual/DB관리매뉴얼.md) | 스키마·백업 연계 운영 매뉴얼 |

Canonical migrations: `database/alembic/versions/`  
Overlay files (code): `docs/migration-overlays/*.py` (실행 대상 아님)

상위 목차: [../README.md](../README.md)
