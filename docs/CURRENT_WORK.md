# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-15

---

## Current Phase

**STEP M7-A — Normalize User LLM menu → `/user/ai`** — READY FOR COMMIT (`LLM_MENU_CANONICAL_ROUTE_READY_FOR_COMMIT`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` · baseline M6_CLOSE `de16a45` |
| 변경 | `menu.tsx` leaf → `userRoutes.ai` · label `LLM 분석` 유지 |
| Legacy | `/user/candidates/llm` redirect **유지** · page 삭제 **0** |
| 산출물 | [audit/MENU_M7A_LLM_CANONICAL_ROUTE_NORMALIZE.md](audit/MENU_M7A_LLM_CANONICAL_ROUTE_NORMALIZE.md) |
| Tests | `menu.test.ts` 11 PASS · eslint PASS |
| commit | **본 커밋** (M7-A only · selective) · push **금지** |

병렬: residual WIP **미수정** · 기타 DEPRECATE redirect **미수정** (M7-B)

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. **M7-B** DEPRECATE_REDIRECT documentation (승인 후 · 삭제 금지)  
2. residual WIP 별도  
3. M7-A 이후 menu churn — 필요 시만  

→ [ROADMAP.md](ROADMAP.md)
