# COMMIT BOUNDARY PLAN — 2026-07-31

**실제 commit 금지.** 승인 후 실행용 Manifest.  
근거: [WORKTREE_CHANGE_MANIFEST_20260731.md](WORKTREE_CHANGE_MANIFEST_20260731.md) · [MIGRATION_COMMIT_ORDER_AUDIT_20260731.md](MIGRATION_COMMIT_ORDER_AUDIT_20260731.md)

---

## 원칙

1. 한 커밋 = 한 목적  
2. Migration과 Entity/Service/Test 정합  
3. 문서-only ↔ 소스 분리  
4. Archive 이동 + 링크 수정 = **동일 패키지**  
5. 중간 깨진 head/테스트 상태 만들지 않기  
6. 민감·cache 제외 · staged 없이 계획만  

---

## CP-01 — Foundation Audit Documents

| 필드 | 내용 |
|------|------|
| Title | `docs(audit): add PHASE1 foundation audit reports (2026-07-31)` |
| Include | `docs/audit/*_20260731.md` foundation set (STATUS_DRAFT, REMAINING, inventories, etc.) · optional README_AUDIT_CODE_20260728 **HOLD** |
| Exclude | Canonical SoT · Archive moves · source |
| Deps | none |
| Order | **1** |
| Tests | none (docs) |
| Migration | none |
| Rollback | delete files / revert commit |
| Risk | Low |
| Ready | **YES** |

---

## CP-02 — Canonical AI Documentation

| 필드 | 내용 |
|------|------|
| Title | `docs: standardize AGENTS/CLAUDE/Cursor rules and canonical status docs` |
| Include | AGENTS.md · CLAUDE.md · `.cursor/rules/*` · docs SoT (IMPLEMENTATION_STATUS, STEP_MASTER, ROADMAP, DECISION_LOG, AI_*) · STRATEGY_LIFECYCLE_STEP12 · PHASE2 report · docs/README·architecture/README·audit/README (Canonical 인덱스) |
| Exclude | CURRENT_WORK(권장 CP-03) · Archive deletes · README Archive 링크만 남기면 CP-03과 **병합 가능** |
| Deps | CP-01 optional |
| Order | **2** |
| Tests | none |
| Risk | Low |
| Ready | **YES** (README를 CP-03에 두면 더 깔끔) |

---

## CP-03 — Archive Completion Reports Batch 1

| 필드 | 내용 |
|------|------|
| Title | `docs(archive): move completion reports to docs/archive/completion-reports` |
| Include | 16 root deletes + `docs/archive/completion-reports/**` · CHANGELOG/OPERATIONS/SECURITY/TOP_100/README_ISSUES link fixes · README Historical links · CURRENT_WORK · PHASE3A/3B reports |
| Exclude | Batch 2–5 targets · source |
| Deps | CP-02 (또는 README 동봉) |
| Order | **3** |
| Tests | link check script |
| Risk | Med |
| Ready | **YES** |

---

## CP-04 — UBA Ownership / FK Migrations

| 필드 | 내용 |
|------|------|
| Title | `fix(uba): soft-delete and trading/settlement account FKs` |
| Include | `dac603609696`, `2fab1d256681`, `84b4b4a8c996` · order/settlement/trading account entities·services · admin_broker/settlements · `test_step_2_5_*` · `migration_helpers` (head 동적) · 관련 step8/11 테스트 ±4줄이 helpers만이면 포함 |
| Exclude | STRAT-12 domain · step12 tests · FE |
| Deps | CP-03 완료 권장 |
| Order | **4** |
| Tests | `pytest tests/test_step_2_5_*.py` · migration head assert · PG integration if available |
| Migration | head becomes **`84b4b4a8c996`** |
| Rollback | downgrade 3 revisions (운영 승인 후) |
| Risk | **High** |
| Ready | **YES** (DB backup 권장) |

---

## CP-05 — Strategy Lifecycle STEP12 Backend + remaining migrations

| 필드 | 내용 |
|------|------|
| Title | `feat(strategy): STEP12 request→readiness lifecycle backend` |
| Include | migrations `bfc6…`→`a7f3…` · `ai/strategy_*` packages · admin/user strategy APIs · admin_strategies.py · router/deps · backtest/performance/strategy_deployment hooks · `test_step12_*` · STRATEGY doc already in CP-02 |
| Exclude | FE pages · Form-only FE |
| Deps | **CP-04 필수** (down_revision chain) |
| Order | **5** |
| Tests | `pytest tests/test_step12_*.py -m "not live"` · collect first |
| Migration | head **`a7f3e91c4d28`** |
| Rollback | reverse mig + revert |
| Risk | **High** |
| Ready | **YES with review** (admin_strategies size) |
| Split by substep? | **NO** — shared router + linear mig |

---

## CP-06 — Strategy Lifecycle STEP12 Frontend

| 필드 | 내용 |
|------|------|
| Title | `feat(frontend): strategy request/draft admin and user pages` |
| Include | strategy-* · portfolio-validations pages · routes/queryKeys/adminApi/userApi **STRAT12 부분** |
| Exclude | Form/message-only pages |
| Deps | CP-05 (API 존재) |
| Order | **6** |
| Tests | `npm test` / vitest 관련 · `npm run build` 권장 |
| Risk | Med |
| Ready | **YES** (API client SPLIT 주의) |

---

## CP-07 — Frontend Form / App.useApp unrelated

| 필드 | 내용 |
|------|------|
| Title | `fix(frontend): Ant Design Form mount and App.useApp message usage` |
| Include | accounts/risk/settings/ai pages Form·message · SettingsEditor · Recovery · MarketCalendar · Profile · BrokerCredential 등 |
| Exclude | strategy-* pages |
| Deps | none (CP-06과 순서 교환 가능하나 충돌 파일 주의) |
| Order | **7** (또는 CP-06 전 — routes 미겹치면) |
| Tests | vitest · 수동 Form 경고 확인 |
| Risk | Low |
| Ready | **YES** |

---

## CP-08 (optional) — Reconciliation audits

| Title | `docs(audit): worktree reconciliation and commit boundary plans` |
| Include | WORKTREE_* · COMMIT_BOUNDARY · MIGRATION_COMMIT_ORDER · STRATEGY_STEP12_CHANGE_MAPPING · P0_BASELINE |
| Order | after CP-07 or with CP-03 |
| Ready | YES |

---

## 통합이 필요한 경우

| 상황 | 권장 |
|------|------|
| API client에 Form+STRAT12 동일 hunk | **하나의 FE 커밋** 또는 interactive staging (승인 후) |
| seed_data가 draft prompt 포함 | CP-05에 포함 |
| migration_helpers만 먼저 | CP-04 |

**CP-04+CP-05 단일 메가 커밋:** 가능하나 리뷰 부담↑ — 분리가 안전 (순서만 지키면 중간 head `84b4b4`에서 2.5 tests green 목표).

---

## 제외 / Hold

| Item | Action |
|------|--------|
| README_AUDIT_CODE_20260728 | HOLD 육안 |
| routes.ts secret pattern | HOLD 육안 |
| Batch 2–5 archive | EXCLUDE |
| P0 source fixes | EXCLUDE (별도) |
| .env / secrets | EXCLUDE (없음) |

---

## 커밋 전 검증 명령 (제안)

```powershell
# Docs packages
# (링크 스크립트)

# CP-04
pytest tests/test_step_2_5_1_uba_soft_delete.py tests/test_step_2_5_2_trading_order_account_fk.py tests/test_step_2_5_3_settlement_ledger_fk.py -q

# CP-05
pytest tests/test_step12_*.py -m "not external and not live and not live_ai" -q --collect-only
pytest tests/test_step12_*.py -m "not external and not live and not live_ai" -q

# CP-06/07
cd frontend; npm test -- --run
```

**LIVE / Broker 테스트: 제안하지 않음 (격리).**
