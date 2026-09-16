# AI_DEVELOPMENT_WORKFLOW

**최종 갱신:** 2026-07-31 · SoT 규칙: [AGENTS.md](../AGENTS.md)

---

## 순서

1. **Audit** — 소스·Migration·테스트·CURRENT_WORK 확인  
2. **Plan** — 범위·금지·P0·커밋 vs 워킹트리  
3. **Implementation** — 승인 범위만  
4. **Migration** — 필요 시 새 revision, 단일 head (`database/alembic`)  
5. **Backend Test** — pytest (non-live)  
6. **Frontend Test** — vitest / 수동 RBAC  
7. **Integration Test** — PostgreSQL 필요 시 명시  
8. **Documentation Update** — CURRENT_WORK · IMPLEMENTATION_STATUS · STEP_MASTER · ROADMAP (+ DECISION_LOG)  
9. **Completion Report** — Historical  
10. **User Approval Gate** — 이후 commit/push · LIVE · Archive

Gate를 건너뛰지 않는다. Broker/Runtime/주문은 [AI_TRADING_SAFETY.md](AI_TRADING_SAFETY.md).

---

## 큰 작업

단계별로 사용자 확인. PHASE 문서 작업과 소스 P0 수정을 한 세션에 섞지 말 것(지시된 경우만).
