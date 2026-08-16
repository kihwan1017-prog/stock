# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-16

---

## Parallel policy

**TRACK U** / **TRACK K** / **SHARED** — 독립 WRITE 병행 · SHARED WRITE 동시 금지 · U+K commit 혼합 금지 · LIVE 금지  

---

## Current Phase

| Track | STEP | Verdict | Next |
|-------|------|---------|------|
| **U** | TERMINATION SELECTIVE COMMIT | **`UPBIT_TERMINATION_CLOSE=YES`** (commit this STEP) | — (no auto next) |
| **K** | CREDENTIAL PROVISIONING | **`KIWOOM_CREDENTIAL_WAITING_FOR_USER_INPUT`** | User UI register+verify → then continue |

| 항목 | 값 |
|------|-----|
| Coverage | **CLOSED** |
| TP | **CLOSED_KEEP_6** · TP **6%** · SL **3%** |
| Long-active termination | **CLOSED** (52/70 CANCELLED proven) |
| News | ACCUMULATING (background) |
| push | **금지** |

K: linked credential **0** — Cursor는 secret을 받지 않음. User는 `/user/accounts/kiwoom` UI에서 등록.

---

## Next Gate

1. **K:** 사용자 UI Credential 등록 완료 통지 후 검증 READ  
2. Upbit 추가 개발 자동 시작 **금지**  

→ [ROADMAP.md](ROADMAP.md)
