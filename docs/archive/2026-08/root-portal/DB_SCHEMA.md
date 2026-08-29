# DB_SCHEMA.md — stock-platform v1.0.0

관련: [docs/database/README.md](docs/database/README.md) · [docs/database/ERD.md](docs/database/ERD.md) · [docs/manual/DB관리매뉴얼.md](docs/manual/DB관리매뉴얼.md)

---

## 1. 엔진 / 마이그레이션

| 항목 | 값 |
|------|-----|
| RDBMS | PostgreSQL 16/17 |
| ORM | SQLAlchemy 2.x |
| Migration | Alembic |
| Canonical path | `database/alembic/versions/` |
| Version table | `operation.alembic_version` |
| Overlay | `docs/migration-overlays/` (**실행 금지**) |

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
cd D:\Projects\stock-platform\database
..\..\.venv\Scripts\alembic.exe upgrade head
..\..\.venv\Scripts\alembic.exe current
```

(프로젝트 관례에 맞는 alembic.ini 경로를 사용하세요.)

---

## 2. 스키마(네임스페이스) 개요

| Schema | 역할 |
|--------|------|
| `auth` | 사용자 · refresh · RBAC |
| `market` / 시세 | instrument · candle · quote · trade |
| `trading` / `order` | TradingOrder · outbox · paper · execution |
| `broker` | account snapshot · pending · recovery |
| `risk` | policy · kill switch · events |
| `position` | limits · plans · exit 관련 |
| `ai` | analysis runs · candidates |
| `strategy` | deployment · performance · runtime |
| `operation` | jobs · audit · settings · alembic_version |
| `notification` | 채널·이벤트 (해당 시) |

정확한 테이블 목록은 DB `\dn` / information_schema 또는 ORM entity를 기준으로 합니다.  
개념 ERD(시세 중심): [docs/database/ERD.md](docs/database/ERD.md)

---

## 3. FK / Index / Comment

- STEP57에서 주요 FK·Index·Comment 안정화 마이그레이션 적용  
- Known Issue: 일부 `TradingOrder.account_id` 등은 논리 참조만 있는 구간 존재  
- 신규 변경은 [docs/database/DB_DEVELOPMENT_RULES.md](docs/database/DB_DEVELOPMENT_RULES.md) 준수

---

## 4. Integrity 운영 체크

1. `alembic current` == head  
2. 일간 full `pg_dump` ([BACKUP.md](BACKUP.md))  
3. Orphan 주문/포지션 점검 (운영 쿼리)  
4. Kill Switch / Daily Loss 테이블 상태  

Legacy ORM 미등록 객체: [docs/LEGACY_DB_OBJECTS.md](docs/LEGACY_DB_OBJECTS.md) (또는 database README 링크)
