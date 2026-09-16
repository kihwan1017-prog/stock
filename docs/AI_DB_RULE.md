# AI_DB_RULE

**최종 갱신:** 2026-07-31 · Cursor `30-database.mdc`

---

## Schema / Alembic

- **Canonical 체인:** `database/alembic/` only  
- 루트 `alembic/versions` — DEPRECATED, 적용 금지  
- **단일 Head** 필수  
- **P0-4:** 커밋 Head(`3554ef8` baseline)와 워킹트리 Head(예: `a7f3e91c4d28`) 불일치를 인지하고, 배포 전 동기화

## 제약

- PK/FK/UNIQUE/CHECK/Index를 근거 없이 제거하지 않음  
- UBA · `user_id` Scope  
- Soft delete · Status/History · Audit 패턴 존중  
- Lock: SKIP LOCKED / distributed recovery lock 관례

## 변경 원칙

- 적용된 migration **rewrite 금지** → 새 revision  
- Entity와 Migration 동시 일치  
- PostgreSQL integration 테스트 없이 “DB 완료” 금지 (SQLite만 불가)

## 워킹트리

미커밋 STEP12/UBA migration은 `WORKTREE_IMPLEMENTED_UNCOMMITTED`. 운영 DB에 무단 upgrade 금지.
