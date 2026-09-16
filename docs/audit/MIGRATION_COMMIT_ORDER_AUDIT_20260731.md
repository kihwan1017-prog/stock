# MIGRATION COMMIT ORDER AUDIT — 2026-07-31

**정적 분석만.** upgrade/downgrade/DB 쓰기 **없음.**

---

## 1. 판정

**CHAIN_VALID_WITH_UNCOMMITTED_REVISIONS**

| 항목 | 값 |
|------|-----|
| Script location | `database/alembic` |
| Revision files (WT) | **130** |
| Heads (WT) | **1** — `a7f3e91c4d28` (`operation_readiness`) |
| Baseline `3554ef8` tip | `ae5f6a7b8c9d` (STEP11 candidate lifecycle) |
| Untracked revisions | **22** |
| Merge revisions in new chain | **없음** (선형) |
| Multiple head risk | **아니오** (현재 WT) |
| P0-4 | Git 미커밋 head 불일치 — **chain 붕괴 아님** |

---

## 2. 미커밋 적용 순서 (oldest → newest)

```text
ae5f6a7b8c9d                    # COMMITTED baseline (STEP11)
└─ dac603609696 uba_soft_delete           # CP-04 UBA
   └─ 2fab1d256681 trading_order_account_fk
      └─ 84b4b4a8c996 settlement_ledger_account_fks
         └─ bfc6ab7d28b2 strategy_request   # CP-05 STRAT-12 시작
            └─ 27d47b2bb048 request_review_snapshot
               └─ 5b999d920792 strategy_draft_domain
                  └─ 89de5fa32629 draft_generation
                     └─ 6d736aedafc9 draft_approval
                        └─ 417184ea4527 backtest_run_definition_provenance
                           └─ f5e26576a15b quality_gate_report
                              └─ 57df8904f5bb parameter_sensitivity
                                 └─ 6464dedec667 monte_carlo
                                    └─ 55c454c73e69 portfolio_validation
                                       └─ 339f8d3de392 explainability
                                          └─ d73cd201441a decision_package
                                             └─ b2dd93b38dfb promotion_commit
                                                └─ eba1e5446ab3 promotion_state_history
                                                   └─ a1c3f9e2b7d4 activation_review_decision
                                                      └─ c7e4a2f8d915 runtime_registration
                                                         └─ e2b6d1a9f374 runtime_registration_rework
                                                            └─ f4a8c2d6e103 deployment_readiness
                                                               └─ a7f3e91c4d28 operation_readiness  # WT HEAD
```

---

## 3. Entity ↔ Migration

| Migration | Expected entities/tables | 코드 존재 (WT) | 판정 |
|-----------|--------------------------|----------------|------|
| dac603 | UBA soft delete columns | trading/account_models · services | 일치 추정 |
| 2fab1d | trading_order account FK | order/entities | 일치 추정 |
| 84b4b4 | settlement/ledger FKs | settlement/entities | 일치 추정 |
| bfc6…a7f3 | strategy_request/draft/approval/reports/registry… | `ai/strategy_*` packages | 일치 추정 |
| Entity-only gap | — | 미커밋 도메인 ↔ mig 동반 | **의도적 쌍** |
| Mig-only gap | 미검출 (도메인 패키지 존재) | | OK |

정밀 ORM↔SQL 대조는 커밋 전 리뷰 권장 — 본 단계는 파일 존재 기준.

---

## 4. 테스트 Head 하드코딩

| 항목 | 상태 |
|------|------|
| `tests/migration_helpers.py` | `alembic_current_head()` **동적** ScriptDirectory |
| step11/8/10 소규모 diff | helper 사용 쪽으로 정렬된 듯 |
| 판정 | Head 문자열 하드코딩 **완화됨** — CP-04/05에 helpers 포함 |

---

## 5. 운영 적용 위험

| 위험 | 수준 | 비고 |
|------|------|------|
| Backfill/FK on trading_order | High | 운영 DB 백업 후 |
| Soft delete | Med | 쿼리 필터 누락 회귀 |
| Locking | Med | long transaction 주의 |
| PostgreSQL-only | 가정 | SQLite만으로 완료 금지 |
| Downgrade | 가능 여부 revision별 | 프로덕션 downgrade 비권장 |

---

## 6. 커밋 분할과 중간 Head

| After package | Expected alembic head |
|---------------|----------------------|
| CP-04 only | `84b4b4a8c996` |
| CP-04+CP-05 | `a7f3e91c4d28` |

중간 상태에서 STEP12 테스트는 **실패 정상** — CP-05 전에 step12 테스트를 CI에 넣지 말 것.

---

## 7. P0-4 세분

| 가설 | 판정 |
|------|------|
| 미커밋으로 인한 정상 head 차이 | **YES** |
| Migration chain 자체 오류 | **NO** (단일 head, ae5f 도달) |
| 배포 절차 문제 | 커밋 전 배포 시 **YES 위험** |
| Head 하드코딩 테스트 | helpers 동적 — **낮음** |
