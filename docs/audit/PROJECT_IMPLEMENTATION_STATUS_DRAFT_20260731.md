# PROJECT IMPLEMENTATION STATUS DRAFT — 2026-07-31

**역할:** PHASE 1 초안. Canonical `docs/PROJECT_IMPLEMENTATION_STATUS.md`는 PHASE 2에서 생성 예정.  
**기준:** 워킹트리 소스 호출 관계 (문서 주장 무시).

---

## 상태 범례

| 코드 | 의미 |
|------|------|
| DONE | 진입점·의존성·DB·권한·오류처리·테스트 증거 |
| PARTIAL | 일부만 연결 |
| GATED | 구현됐으나 수동/플래그/승인 전제 |
| MOCK | Mock/테스트 전용 |
| GAP | 단절 또는 미구현 |
| WIP | 워킹트리 미커밋 작업 |

---

## 영역별 현황

### 공통 기반 — DONE (~88%)
- Startup: `api/main.py` + `lifecycle.py` (DB ping, LIVE fail-closed, recovery, schedulers)
- Auth: JWT + refresh + RBAC DB 재검증
- Admin: `require_admin` (JWT role or API key)
- Ownership: `auth/account_ownership.py`, strategy ownership
- Audit / security headers / secret masking: 존재

### 회원·계좌 — DONE/PARTIAL (~85–90%)
- User/Admin UBA, Paper, Credential Vault, Verify/Revoke
- WIP: UBA soft-delete, trading_order/settlement FK migrations (미커밋)

### Market Data — PARTIAL (~70%)
- Upbit: WS + private REST
- KRX: 일봉/캘린더/collector
- GAP: Kiwoom realtime quotes

### Candidate / AI — DONE/GATED (~78–80%)
- Screener DAILY + AI Assessment→Consensus→Queue→Promotion→Lifecycle
- AI 실행은 Mock 기본, EXTERNAL confirm 패턴
- Candidate ≠ Strategy 자동 연결 (STEP12 Request가 별도 게이트)

### Strategy Lifecycle (STEP12) — GATED (~72%)
- Request → Draft → Generation → Approval → Backtest/QG/MC/Explainability → Decision → Promotion → Activation → Runtime Registration → Deployment/Operation Readiness
- **실행 WRITE 금지** docstring 일관
- WIP: 미커밋 migrations/tests/FE pages

### Backtest — DONE (~80%)
- Engine + repository + STEP12 approval backtest
- Runtime/주문 미연동

### Risk — DONE (~88%)
- Kill switch, daily loss, order guards, live health gate, ARM
- Realtime path에서 final submit `skip_risk_checks` 존재 (상단에서 이미 검사)

### Runtime / Scheduler — PARTIAL (~65–68%)
- Scoped in-memory runtime manager + DB registry (이중 개념)
- Trading session scheduler; outbox; recovery scheduler; market session jobs
- GAP: SESSION OPEN ≠ auto runner; STEP12 registry ≠ bootstrap active links

### Order / Execution — PARTIAL (~60–85%)
- Outbox SKIP LOCKED: DONE
- Upbit fill sync: DONE
- Kiwoom fill→position: GAP
- Paper outbox auto-fill: GAP

### Position / Balance / Settlement — PARTIAL (~60–65%)
- Paper apply_fill; EOD settlement runners
- Live Kiwoom balance sync는 주문 fill loop과 분리

### Recovery / Reconciliation — DONE/PARTIAL (~75%)
- Startup recover, periodic recovery, Upbit ambiguous resolver
- Kiwoom pending vs TradingOrder 통합 미완

### Frontend — DONE/PARTIAL (~80%)
- 99 pages; admin/user RBAC layouts
- Strategy request/draft pages (WIP untracked)
- Stubs: SSE quotes, some CRUD TODOs
- Form/message Ant Design 경고 수정 진행(미커밋)

### Security — DONE (~82%)
- LIVE fail-closed on startup
- Unauthenticated: health, version, auth login, telegram webhook (secret header)
- Gaps: `/version` info disclosure (LOW)

### Ops / Telegram — DONE (~78%)
- Dashboards, RO telegram commands, no order from telegram for AI mutate

---

## 자동매매 완성 기준 (§7) 체크

| 조건 | Paper | LIVE |
|------|-------|------|
| 시세 수집 | 부분(Upbit/일봉) | Upbit 가능 / Kiwoom RT 불가 |
| 전략 실행 | 수동 runner | 동일 + LIVE gate |
| 신호 | Hub 경로 | Hub+Upbit |
| Risk | 적용 | 적용 |
| 주문 생성/전송 | Outbox+Paper adapter | Outbox+LIVE adapter |
| 체결 반영 | 부분 | Upbit 양호 / Kiwoom 갭 |
| 잔고·포지션 동기 | Paper 부분 | Upbit 부분 / Kiwoom 갭 |
| PnL | 부분 | 부분 |
| SL/TP | Exit monitor | Exit monitor |
| Kill Switch | Yes | Yes |
| Recovery | Yes | Yes |
| Isolation | Yes | Yes |
| Full test E2E | No | No |
| Ops runbook | Yes (docs) | Yes + LIVE checklists |

**결론:** Paper/LIVE 모두 §7 “자동매매 완료” **미달**. Paper가 LIVE보다 가깝다.

---

## 다음 Canonical 승격 시 주의

이 초안은 워킹트리 WIP를 포함한다. Canonical 문서로 승격하기 전:

1. STEP12 커밋 경계 확정  
2. Alembic head를 DB와 동기화  
3. P0 하드코딩/Fill 갭을 이슈로 고정
