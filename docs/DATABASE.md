# Database

- Canonical migrations: **`database/alembic/` only**
- Deprecated: repo root `alembic/versions` 적용 금지
- Rules: [AI_DB_RULE.md](AI_DB_RULE.md)
- Domain notes: [database/](database/)
- Archived schema notes: [archive/2026-08/root-portal/DB_SCHEMA.md](archive/2026-08/root-portal/DB_SCHEMA.md)

Upgrade/downgrade는 사용자 승인 후에만. Production data DELETE·revision rewrite 금지.
