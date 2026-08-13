# STEP_MASTER_STATUS

**역할:** STEP 관리의 **유일한** Source of Truth.  
**규칙:** 같은 숫자라도 네임스페이스가 다르면 **합치지 않는다.** 과거 번호를 삭제·재부여하지 않고 Mapping만 제공한다.  
**최종 갱신:** 2026-08-13  
**상세 Mapping 원본:** [audit/STEP_NUMBER_MAPPING_20260731.md](audit/STEP_NUMBER_MAPPING_20260731.md)

**Ops note:** Shadow cohort milestone watch — accumulating until READY gate. SHADOW_ONLY · UBA1380 보호.  
**News note:** STEP N9 latency alignment — N4→N5 event-driven; `NEWS_AB_SAMPLE_ACCUMULATING`.

---

## 1. 네임스페이스

| Namespace | ID 접두 | 의미 | 위치 |
|-----------|---------|------|------|
| MAIN-STEP | `HIST-*` / archive STEP16–75 | 제품 연대기 | `docs/archive/steps/` |
| AUDIT-STEP | `AUDIT21-*` | 21단계 코드 감사 | `docs/audit/STEP01–21` |
| STRATEGY-STEP | `STRAT-12.*` | Strategy Lifecycle (현재) | 코드/tests + [architecture/STRATEGY_LIFECYCLE_STEP12.md](architecture/STRATEGY_LIFECYCLE_STEP12.md) |
| NEWS-STEP | `NEWS-N*` | UPBIT News/Notice 병렬 트랙 | `src/stock_platform/news/` |
| LEGACY-STEP / SUBSTEP | `DEV-8.*`, `AI-11.*`, `OPS-10.*` | 활성 서브시리즈 | development/ai/operations |
| REL | `REL-*` | 루트 릴리스 서술 | 루트 README_STEP* |

### 충돌 경고 (동일 숫자 ≠ 동일 기능)

| Label | AUDIT21 | MAIN/Archive | Canonical SUB |
|-------|---------|--------------|---------------|
| STEP8 | Risk/Kill 감사 | — | **DEV-8.*** 브로커/계좌/LIVE |
| STEP10 | Kiwoom 감사 | — | **OPS-10.*** Runtime/Ops |
| STEP11 | Upbit 감사 | — | **AI-11.*** Provider→Lifecycle (**커밋됨**) |
| **STEP12** | **Paper Trading 감사** (`AUDIT21-12`) | — | **STRAT-12.*** Strategy Request→Readiness (**워킹트리**) |

⚠️ **과거 Paper Audit STEP12** 와 **현재 Strategy Lifecycle STEP12** 를 절대 혼동하지 말 것.

---

## 2. 활성 시리즈 요약

| Canonical ID | Historical | 제목 | 상태 | 커밋 | Migration | Tests | 다음 Gate | 관련 문서 |
|--------------|------------|------|------|------|-----------|-------|-----------|-----------|
| AI-11.13 | STEP11-13 | Candidate Lifecycle | COMPLETE_WITH_LIMITATIONS | YES (`3554ef8`) | ae5f6a7b8c9d 계열 | test_step11_13 | 유지보수 | `docs/ai/` |
| STRAT-12.1 … 12.20 | STEP12-1…20 | Strategy Lifecycle | PARTIAL / GATED | **NO** (워킹트리) | 다수 → head `a7f3e91c4d28` (WT) | test_step12_* | 커밋 경계 + P0-3 | [STRATEGY_LIFECYCLE_STEP12.md](architecture/STRATEGY_LIFECYCLE_STEP12.md) |
| DEV-8.* | STEP8-5-* | 계좌·LIVE 안전 | COMPLETE_WITH_LIMITATIONS | YES | 포함 | 다수 | P0 보강 | `docs/development/` |
| AUDIT21-* | STEP01–21 | 코드 감사 | HISTORICAL | N/A | N/A | baseline | 수정 최소화 | `docs/audit/` |
| HIST-74/75 | STEP74/75 | v1.1 감사·패키징 | HISTORICAL | YES | N/A | — | CONDITIONAL | archive/steps |
| NEWS-N2 | STEP N2 | UPBIT News/Notice Collector | COMPLETE_WITH_LIMITATIONS | YES | none (reuse news.news_article) | test_step_n2_* | N3 Symbol Mapping | `src/stock_platform/news/` |
| NEWS-N3 | STEP N3 | News Symbol Mapping | READY_WITH_LIMITATIONS | YES | none (reuse news_article_symbol) | test_step_n3_* | N3.1 Quality | `symbol_resolver/mapper` |
| NEWS-N3.1 | STEP N3.1 | Mapping Quality Guard | NEWS_SYMBOL_MAPPING_QUALITY_READY | YES | none | test_step_n3_1_* | N4 AI News | `symbol_mapping_quality*` |
| NEWS-N4 | STEP N4 | AI News Analysis | READY_WITH_LIMITATIONS | YES (`e76ab57`) | m4n5o6p7q8r9 | test_step_n4_* | N5 Signal | `news_ai_analysis*` |
| NEWS-N5 | STEP N5 | News Signal Standardization | UPBIT_NEWS_SIGNAL_READY | YES (`f4d9549`) | n5o6p7q8r9s0 | test_step_n5_* | N6 Combined | `news_signal*` |
| NEWS-N6 | STEP N6 | News Combined Shadow A/B | READY_WITH_LIMITATIONS | YES (`eac2b66`) | o6p7q8r9s0t1 | test_step_n6_* | N7 누적 | `upbit_news_combined_shadow*` |
| NEWS-N7 | STEP N7 | News A/B Sample Accumulation | NEWS_AB_SAMPLE_ACCUMULATING | YES (`60a9969`) | none (reuse N6 table) | test_step_n7_* | N8 observation | diagnostics/scheduler/UI |
| NEWS-N8 | STEP N8 | News Pipeline Continuous Observation | NEWS_PIPELINE_OBSERVATION_RUNNING | YES (`74102ad`) | none | test_step_n8_* | N9 latency | pipeline_observation* |
| NEWS-N9 | STEP N9 | News Pipeline Latency Alignment | NEWS_PIPELINE_LATENCY_ALIGNED | YES (`622eb8d`) | none | test_step_n9_* | N10 (승인 후) | N4→N5 event trigger |

---

## 3. STRATEGY-STEP (STRAT-12) 상세

| Canonical | Historical | 제목 | 상태 | 커밋 | Notes |
|-----------|------------|------|------|------|-------|
| STRAT-12.1 | STEP12-1 | Strategy Request | WORKTREE | NO | 실행 WRITE 금지 |
| STRAT-12.1a | STEP12-1a | Request review gate | WORKTREE | NO | |
| STRAT-12.2.1 | STEP12-2-1 | Draft domain | WORKTREE | NO | |
| STRAT-12.2.2 | STEP12-2-2 | Draft generation | WORKTREE | NO | |
| STRAT-12.2.3 | STEP12-2-3 | Draft review | WORKTREE | NO | |
| STRAT-12.3 | STEP12-3 | Draft approval | WORKTREE | NO | |
| STRAT-12.4…12.15 | … | Snapshot…Decision package | WORKTREE | NO | QG/MC/Explain 등 |
| STRAT-12.16 / 12.16r | … | Promotion commit/state | WORKTREE | NO | |
| STRAT-12.17 | STEP12-17 | Activation | WORKTREE | NO | Runtime 자동 start 없음 |
| STRAT-12.18 | STEP12-18 | Runtime registration | WORKTREE | NO | `running=false`, inactive links |
| STRAT-12.19 | STEP12-19 | Deployment readiness | WORKTREE | NO | READY_TO_START ≠ loader ACTIVE |
| STRAT-12.20 | STEP12-20 | Operation readiness | WORKTREE | NO | WT alembic head |

**대체 관계:** Audit `AUDIT21-12`(Paper) ≠ `STRAT-12.*`. 서로 대체하지 않음.

**Blocking:** P0-3 (Registry↔Runtime), P0-4 (Migration head).

---

## 4. 번호 배정 규칙

1. 신규는 활성 시리즈에만 붙인다 (`DEV-8` / `AI-11` / `STRAT-12` 또는 **새 시리즈 이름**).
2. 시리즈 종료 후 숫자만 재사용하지 않는다.
3. `AUDIT21-*` 번호는 신규 개발에 재사용 금지.
4. 이슈·커밋·폴더에 Canonical ID 병기.

---

## 5. STEP 완료 시

본 문서 + IMPLEMENTATION_STATUS + ROADMAP + CURRENT_WORK 갱신.  
완료보고는 SoT가 아니다 → 향후 `docs/archive/completion-reports/`.
