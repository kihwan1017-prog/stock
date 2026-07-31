# DATABASE / MIGRATION AUDIT — 2026-07-31

읽기 전용. DB 쓰기·upgrade/downgrade 미실행. `alembic heads` / 파일 분석만.

---

## 1. Alembic 구성

| 항목 | 값 |
|------|-----|
| script_location | `database/alembic` (`alembic.ini`) |
| Versions (working tree) | **130** `.py` |
| Head (working tree) | **단일** `a7f3e91c4d28` — `operation_readiness` |
| Git HEAD `3554ef8` | STEP11 `ae5f6a7b8c9d`까지 커밋; **STEP12+ 다수 미커밋** |
| Deprecated | 루트 `alembic/versions/` (5) — README에 적용 금지 |

**위험:** 배포 환경이 커밋만 따라가면 head가 워킹트리와 다름. P0-4로 커밋 경계 필요.

---

## 2. Schema 개요 (코드/마이그레이션 기준)

주요 스키마: `auth`, `market`, `trading`, `strategy`, `operation`, `news`, `disclosure`, `ai`, `backtest`, `broker`, `common`, `notification`, `screener` 등.

---

## 3. 소유권 컬럼 혼용

| 개념 | 컬럼 | 용도 |
|------|------|------|
| 사용자 | `user_id` | 소유자 |
| LIVE 계좌 | `user_broker_account_id` | UBA |
| Paper 계좌 | `account_id` / `paper_account_id` | Paper |

혼재 테이블 예:

- `trading.trading_order` — 역사적으로 `account_id`, 이후 UBA 추가 (`p3d4…`, `2fab1d…`)
- Settlement/ledger — UBA + paper dual FK (`84b4b4…`)
- Runtime registration — `target_user_id` / UBA / paper triple (`c7e4a2…`)

LIVE 경로는 UBA 강제 가드 존재. 레거시 orphan 가능성은 health/migration 주석에 명시.

---

## 4. STEP12 / 관련 미커밋 마이그레이션 (워킹트리)

예시 (전부 `??` 상태였음):

- `bfc6ab7d28b2` strategy_request
- `5b999d920792` strategy_draft_domain
- `89de5fa32629` strategy_draft_generation
- `6d736aedafc9` strategy_draft_approval
- backtest/quality/monte_carlo/explainability/decision/promotion/activation/runtime/deployment/operation readiness 일련
- `dac603609696` uba_soft_delete
- `2fab1d256681` trading_order_account_fk
- `84b4b4a8c996` settlement_ledger_account_fks

**권장:** 단일 선형 체인 유지 확인 후 커밋; 복수 head 재발 방지.

---

## 5. 테이블 상태 템플릿 (대표)

| 테이블 | 목적 | Scope | 상태 | 문제 | 조치 |
|--------|------|-------|------|------|------|
| `trading.trading_order` | 주문 | user/UBA/paper | ACTIVE | 컬럼 혼용 이력 | KEEP + FK 완성 |
| `trading.order_outbox` | 전송 큐 | order | ACTIVE | — | KEEP |
| `ai.candidate_lifecycle` | AI 후보 수명 | result_id | ACTIVE | — | KEEP |
| `ai.strategy_request` 등 | STEP12 | user | WIP | 미커밋 | MIGRATE/COMMIT |
| `trading.strategy_runtime_registry` | STEP12 등록 | scope | ACTIVE/GATED | running=false 기본 | ADAPT |
| `account_strategy_link` | Runtime bootstrap | account/strategy | ACTIVE | STEP12가 inactive 생성 | ADAPT |
| `broker_pending_order` | Kiwoom pending | UBA | ACTIVE | TradingOrder 미연결 | ADAPT |
| deprecated overlay tables | step32/33 | — | LEGACY | 적용 금지 | ARCHIVE |

전체 테이블 전수는 PHASE 2에서 ERD 문서와 대조 권장.

---

## 6. 제약 / 패턴

- Soft delete: paper/UBA 일부 (`deleted_at`)
- Idempotency: outbox, AI executions, promotion keys
- Evidence 불변: AI analysis/review 패턴
- Unique: DAILY candidate run partial unique 등
- Check: lifecycle/promotion status CHECKs

---

## 7. 판정

- Migration **체인 단절(복수 head):** 워킹트리에서 `alembic heads` = 단일 (양호)
- Entity↔Migration: 대체로 일치; STEP12 미커밋으로 **배포 불일치 위험 HIGH**
- 고아 데이터: legacy account orphan 가능성 (기존 migration/health)
- 미사용/중복: overlay alembic, 일부 legacy risk tables — ARCHIVE/DEPRECATE 후보
