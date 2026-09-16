# STRATEGY_LIFECYCLE_STEP12 (Canonical)

**Canonical series:** `STRAT-12.*` (Strategy Lifecycle)  
**최종 갱신:** 2026-07-31  
**커밋 상태:** `WORKTREE_IMPLEMENTED_UNCOMMITTED` (baseline `3554ef8`에는 미포함)

---

## ⚠️ 네임스페이스 경고

| ID | 의미 |
|----|------|
| **AUDIT21-12** | 과거 **Paper Trading** 코드 감사 (`docs/audit/STEP12_*`) |
| **STRAT-12.*** | **현재** Strategy Request → Operation Readiness 파이프라인 |

이 문서는 **STRAT-12만** 다룬다. Paper Audit STEP12와 혼동·대체 금지.  
SoT: [STEP_MASTER_STATUS.md](../STEP_MASTER_STATUS.md)

---

## 목적

Candidate/AI 이후 **전략 요청·초안·검증·승인·프로모션·활성화·레지스트리·준비도**를 상태 머신으로 관리한다.

설계상 이 파이프라인은 **주문·Runtime 기동 WRITE를 하지 않는다** (게이트/스냅샷/리포트).

---

## Canonical Mapping (12-1 … 12-20)

| Canonical | Historical | 제목 | 상태 | Entity/모듈 (요약) | Migration (예) | Tests |
|-----------|------------|------|------|-------------------|----------------|-------|
| STRAT-12.1 | STEP12-1 | Strategy Request | WT | `ai/strategy_request` | `bfc6ab7d28b2` | `test_step12_1_*` |
| STRAT-12.1a | STEP12-1a | Request review gate | WT | review snapshot | `27d47b2bb048` | `test_step12_1a_*` |
| STRAT-12.2.1 | STEP12-2-1 | Draft domain | WT | `ai/strategy_draft` | `5b999d920792` | `test_step12_2_1_*` |
| STRAT-12.2.2 | STEP12-2-2 | Draft generation | WT | `ai/strategy_draft_generation` | `89de5fa32629` | `test_step12_2_2_*` |
| STRAT-12.2.3 | STEP12-2-3 | Draft review | WT | review gate | — | `test_step12_2_3_*` / `2_1a` |
| STRAT-12.3 | STEP12-3 | Draft approval | WT | `ai/strategy_draft_approval` | `6d736aedafc9` | `test_step12_3_*` |
| STRAT-12.4 | STEP12-4 | Strategy snapshot | WT | approval snapshot | — | `test_step12_4_*` |
| STRAT-12.5–7 | … | Backtest readiness/spec/rule | WT | backtest_* | `417184ea4527` 등 | `test_step12_5..7_*` |
| STRAT-12.8 | … | Performance analytics | WT | performance | — | `test_step12_8_*` |
| STRAT-12.9 | … | Walk-forward | WT | walk_forward | — | `test_step12_9_*` |
| STRAT-12.10 | … | Quality gate | WT | quality_gate | `f5e26576a15b` | `test_step12_10_*` |
| STRAT-12.11 | … | Parameter sensitivity | WT | parameter_sensitivity | `57df8904f5bb` | `test_step12_11_*` |
| STRAT-12.12 | … | Monte Carlo | WT | monte_carlo | `6464dedec667` | `test_step12_12_*` |
| STRAT-12.13 | … | Portfolio validation | WT | portfolio_validation | `55c454c73e69` | `test_step12_13_*` |
| STRAT-12.14 | … | Explainability | WT | explainability | `339f8d3de392` | `test_step12_14_*` |
| STRAT-12.15 | … | Decision package | WT | decision_package | `d73cd201441a` | `test_step12_15_*` |
| STRAT-12.16 / 12.16r | … | Promotion commit / state | WT | promotion_* | `b2dd93b38dfb`, `eba1e5446ab3` | `test_step12_16*` |
| STRAT-12.17 | STEP12-17 | Activation | WT | activation | `a1c3f9e2b7d4` | `test_step12_17_*` |
| STRAT-12.18 | STEP12-18 | Runtime registration | WT | runtime_registration | `c7e4a2f8d915`, `e2b6d1a9f374` | `test_step12_18_*` |
| STRAT-12.19 | STEP12-19 | Deployment readiness | WT | deployment_readiness | `f4a8c2d6e103` | `test_step12_19_*` |
| STRAT-12.20 | STEP12-20 | Operation readiness | WT | operation_readiness | `a7f3e91c4d28` (WT head) | `test_step12_20_*` |

WT = 워킹트리 구현·테스트 존재 가능. **배포 완료 아님.**

---

## 파이프라인 흐름

```text
Candidate (별도 AI-11)
    → Strategy Request (+ review)
    → Draft (+ generation + review)
    → Approval
    → Backtest / Walk-forward / QG / Sensitivity / MC / Portfolio / Explainability
    → Decision package (human decision)
    → Promotion commit + state history
    → Activation (검증)
    → Runtime Registration (DB, 기본 running=false, link inactive)
    → Deployment Readiness (READY_TO_START 등)
    → Operation Readiness
         ✗ 자동 연결 없음 (P0-3)
Scoped Runtime Manager (active AccountStrategyLink + ACTIVE deployment만 bootstrap)
    → (수동) Runner → Risk → Order …
```

---

## API / Frontend

| 층 | 경로 (요약) |
|----|-------------|
| Admin API | `admin_strategy_requests`, `admin_strategy_drafts`, `admin_strategy_draft_generations`, `admin_strategy_draft_approvals` (+ portfolio validations 등) |
| User API | `user_strategy_requests`, `user_strategy_drafts` |
| Router | `api/router.py` include |
| FE Admin | `/admin/strategy-requests`, `/admin/strategy-drafts`, `/admin/portfolio-validations` (WT) |
| FE User | `/user/strategy-requests`, `/user/strategy-drafts` (WT) |

---

## Runtime 연결 상태

| 항목 | 판정 |
|------|------|
| Registration 레코드 | 생성 가능 · 기본 비실행 |
| AccountStrategyLink | 등록 시 `is_active=False` 유지(설계) |
| Deployment READY_TO_START | loader는 **ACTIVE**만 로드 → **불일치 (P0-3)** |
| 자동 Order | **없음** |
| Paper/LIVE 실행 | 본 STEP 범위 외 · P0-1/P0-5와 별개 |

---

## 현재 Blocking

- **P0-3** — Lifecycle/Registration/Deployment ↔ Scoped Runtime  
- **P0-4** — Migration head 미커밋  
- 완료보고 PASS ≠ 자동매매 연결 완료

---

## 다음 단계

1. 커밋 경계 확정 (STEP12 vs FE Form vs UBA FK) — P0-4  
2. Runtime 정합 설계·게이트 (기본 OFF) — P0-3 / P1-1 / P1-2  
3. Paper E2E — P0-5 / P1-4  
4. 본 문서·STEP_MASTER·IMPLEMENTATION_STATUS 동시 갱신

관련: [AI_ARCHITECTURE.md](../AI_ARCHITECTURE.md) · [ROADMAP.md](../ROADMAP.md) · [PROJECT_IMPLEMENTATION_STATUS.md](../PROJECT_IMPLEMENTATION_STATUS.md)
