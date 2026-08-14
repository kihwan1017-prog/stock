# PROJECT_IMPLEMENTATION_STATUS

**역할:** 구현 현황의 **유일한** Source of Truth.  
**근거:** PHASE 1 감사(2026-07-31) + 실행 경로 소스. 수치는 **추정치**이며 완료 판정이 아니다.  
**최종 갱신:** 2026-08-14  
**Branch / Commit baseline:** `release/v1.1.0` @ `949c0e9` + ops/news WIP commits  
**워킹트리:** Autotrading P0 package 일부 미커밋 가능 · Ops stale snapshot RETIRE 경로 추가

**Ops (2026-08-13):** Shadow cohort milestone watch (`SAMPLE_ACCUMULATING` → READY@VALID≥30/new-policy MATCH≥10/mismatch=0). 정책 변경 없음. SHADOW_ONLY · UBA1380 보호.  
**News (2026-08-14):** STEP N10 observation/coverage — natural MATCHED completed 1/20 · NO_NEWS 13/20; funnel drop 주원인 `NO_SYMBOL_OVERLAP`; Top-N Snapshot **OBSERVE_MORE** (미구현); look-ahead/threshold 유지.

---

## 1. 종합 판정

| 지표 | 값 |
|------|-----|
| 개발 구현률 | **~78%** (추정) |
| Paper 자동매매 준비도 | **~78%** (추정) |
| LIVE 자동매매 준비도 | **~52%** (추정) |
| 자동매매 운영 가능 | **NOT READY** |
| LIVE 거래 | **NOT APPROVED** |
| Paper 무인 자동매매 | **PARTIAL** (Outbox auto-fill 코드 경로 추가, E2E 미완) |

### 완료 상태 값 (영역 표용)

`COMPLETE` · `COMPLETE_WITH_LIMITATIONS` · `PARTIAL` · `DISCONNECTED` · `MOCK_ONLY` · `PAPER_ONLY` · `LIVE_UNVERIFIED` · `STUB_ONLY` · `LEGACY` · `NOT_IMPLEMENTED` · `UNKNOWN`

### 커밋 상태 값

`COMMITTED_BASELINE` · `WORKTREE_IMPLEMENTED_UNCOMMITTED` · `VERIFIED_BY_TEST` · `PARTIALLY_VERIFIED` · `DOCUMENTED_ONLY` · `NOT_IMPLEMENTED`

---

## 2. P0 Blocking (고정)

| ID | 내용 | 영향 | 상태 (2026-08-01) |
|----|------|------|-------------------|
| **P0-1** | Realtime broker hardcode | 잘못된 Outbox enqueue | **코드 수정(미커밋)** |
| **P0-2** | Kiwoom Fill → TradingOrder | LIVE 장부 불일치 | **WS bridge(미커밋)**; Position WRITE OPEN |
| **P0-3** | READY_* ↔ Runtime ACTIVE | 승인≠실행 | **명시 Promote(미커밋)**; Runner OFF |
| **P0-4** | Alembic Git/Head | 배포 스키마 | **DONE** `a7f3e91c4d28` |
| **P0-5** | Paper Outbox auto-fill | Paper E2E 단절 | **코드 수정(미커밋)** |

→ [ROADMAP.md](ROADMAP.md)

---

## 3. 환경별

| 환경 | 구현 | 연결 | 준비도 | 비고 |
|------|------|------|--------|------|
| Kiwoom MOCK | `MOCK_ONLY` | PARTIAL | 낮음 | mockapi 경로 |
| Kiwoom LIVE | `LIVE_UNVERIFIED` | `DISCONNECTED` (Fill/RT) | **~낮음** | RT 시세 없음; P0-2 |
| Upbit LIVE | `COMPLETE_WITH_LIMITATIONS` | PARTIAL | 중간 | P0-1; LIVE gate |
| Stock Paper | `PAPER_ONLY` | PARTIAL | ~72%대 | P0-5 |
| Crypto Paper | `PAPER_ONLY` | PARTIAL | ~72%대 | P0-5 |

---

## 4. 영역별 표

| 영역 | 구현 상태 | 커밋 상태 | 연결 상태 | 테스트 | Paper | LIVE | Blocking | 근거 | 다음 작업 |
|------|-----------|-----------|-----------|--------|-------|------|----------|------|-----------|
| 공통 Startup/Auth | COMPLETE_WITH_LIMITATIONS | COMMITTED_BASELINE | CONNECTED | PARTIALLY_VERIFIED | OK | fail-closed | — | `api/lifecycle.py` | — |
| 회원·UBA·Vault | COMPLETE_WITH_LIMITATIONS | WORKTREE (soft-delete/FK) | CONNECTED | PARTIALLY_VERIFIED | OK | OK | P0-4 | trading/account* | migration 커밋 경계 |
| Market Data | PARTIAL | COMMITTED_BASELINE | PARTIAL | PARTIALLY_VERIFIED | 일봉/Upbit | Kiwoom RT 없음 | — | realtime/, collectors | KRX RT 결정 |
| Candidate/AI STEP11 | COMPLETE_WITH_LIMITATIONS | COMMITTED_BASELINE | CONNECTED | VERIFIED_BY_TEST | N/A | N/A | — | ai/candidate_* | — |
| Strategy Lifecycle STEP12 | PARTIAL | WORKTREE_IMPLEMENTED_UNCOMMITTED | GATED (실행 WRITE 0) | VERIFIED_BY_TEST (워킹트리) | N/A gate | N/A | P0-3, P0-4 | ai/strategy_* | Canonical doc + 커밋 |
| Backtest | COMPLETE_WITH_LIMITATIONS | COMMITTED + WIP STEP12 | Runtime 미연동 | PARTIALLY_VERIFIED | N/A | N/A | — | backtest/ | — |
| Risk/Kill | COMPLETE_WITH_LIMITATIONS | COMMITTED_BASELINE | CONNECTED | VERIFIED_BY_TEST | OK | OK | — | risk/ | — |
| Scoped Runtime | PARTIAL | COMMITTED_BASELINE | STEP12와 분리 | PARTIALLY_VERIFIED | 수동 | 수동 | P0-3 | strategy runtime | P1 정합 |
| Order/Outbox | COMPLETE_WITH_LIMITATIONS | COMMITTED_BASELINE | CONNECTED | PARTIALLY_VERIFIED | PARTIAL | PARTIAL | P0-1 | order/, outbox | broker_code fix |
| Fill/Position | PARTIAL | COMMITTED_BASELINE | Upbit OK / Kiwoom GAP / Paper GAP | PARTIALLY_VERIFIED | P0-5 | P0-2 | P0-2,P0-5 | fill sync, paper | Fill 파이프라인 |
| Settlement/PnL | PARTIAL | WORKTREE FK | PARTIAL | PARTIALLY_VERIFIED | PARTIAL | PARTIAL | P0-4 | settlement/ | FK 커밋 |
| Recovery/Reconcile | COMPLETE_WITH_LIMITATIONS | COMMITTED_BASELINE | Upbit>Kiwoom | PARTIALLY_VERIFIED | OK | PARTIAL | P0-2 | recovery/ | Kiwoom reconcile |
| Frontend | COMPLETE_WITH_LIMITATIONS | WORKTREE + **M3/M4-A/M4-B/M4-C menu·LIVE panel committed** | PARTIAL stubs | PARTIALLY_VERIFIED | UI | UI | — | frontend/ | M4-C2 risk LIVE DEFER |
| Ops/Telegram | COMPLETE_WITH_LIMITATIONS | COMMITTED_BASELINE | RO 명령 | PARTIALLY_VERIFIED | OK | 제한 | — | telegram/ | — |
| Docs Canonical | COMPLETE (PHASE2) | NEW | — | link check | — | — | — | docs/* | PHASE3 archive |

---

## 5. 자동매매 완성 체크 (요약)

| 조건 | Paper | LIVE |
|------|-------|------|
| 시세 | 부분 | Upbit 가능 / Kiwoom RT 불가 |
| Runtime 자동 연결 | 아니오 (수동) | 아니오 |
| Risk → Order → Outbox | 경로 존재 | 경로 존재 + P0-1 |
| Fill → Position | 부분 (P0-5) | Upbit 양호 / Kiwoom 갭 (P0-2) |
| Full E2E 테스트 | 아니오 | 아니오 |

**결론:** Paper·LIVE 모두 자동매매 “완료” 미달. Paper가 LIVE보다 가깝다.

---

## 6. 유지관리

STEP/기능 완료 시 본 문서 + [CURRENT_WORK.md](CURRENT_WORK.md) + [STEP_MASTER_STATUS.md](STEP_MASTER_STATUS.md) + [ROADMAP.md](ROADMAP.md)를 함께 갱신한다.
