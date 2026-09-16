# UPBIT UBA1380 24x7 — Activation/ARM 세션 갱신 Runbook

**대상:** UPBIT UBA1380 controlled 24x7 운영 세션  
**성격:** 운영([B] OPERATIONS). 구현 완료를 되돌리지 않는다.  
**금지:** AUTO RE-ARM · 자동 실행 · 강제 주문 · Scheduler RUN · KIWOOM 변경

현재 구축 상태: **COMPLETED** (`UPBIT_24X7_AUTO_TRADING_GO_LIVE_SUCCESS_WITH_LIMITATIONS`).

만료 시각 예 (Activation #15): **2026-08-19 07:25:04 KST**, TTL 8h. ARM expiry ≤ Activation expiry.

만료 시 기대(fail-closed cascade, `live_session_expiry`):  
Activation EXPIRED → ARM OFF → LIVE OFF → Scheduler PAUSE.

---

## 만료 전 운영자 절차 (수동, 순서 고정)

자동으로 수행하지 않는다. 한 단계가 실패하면 다음 단계로 가지 않는다.

1. **health 확인** — `GET /health/live`, `/health/ready`. `/health/ops`가 DEGRADED이고 Trading Scheduler가 PAUSE이면 UPBIT 24x7에서 **EXPECTED**.
2. **Recovery / Conflict / Kill 확인** — recovery SUCCESS, trading_paused=false, blocking/HIGH conflict=0, Kill OFF, account_paused=false, CONNECTED, credential VERIFIED.
3. **Activation validate** — scope=ACCOUNT, broker=UPBIT, UBA=1380. ready=true, FAIL=[]. Risk 값은 기존 resolved contract 유지.
4. **ACCOUNT Activation approve** — 승인 phrase와 TTL은 기존 세션 정책(최대 72h, 무제한 금지). 새 transition_id 확보. timeout/unknown이면 재POST 금지.
5. **LIVE 상태 확인** — 이미 ON이면 유지. 만료 cascade로 OFF가 된 뒤에만 명시적 LIVE ON.
6. **ARM 갱신** — 명시적 ARM POST. TTL은 잔여 Activation을 넘지 않음. AUTO RE-ARM 없음. 원문 token 저장 금지.
7. **Worker RUNNING 확인** — START는 중지된 경우에만 operator API. RUNNING ≠ broker CREATE 허용.
8. **Exit Monitor 확인** — RUNNING + `position_exit_monitor_live_upbit_enabled=true`.
9. **Runtime RUNNING 확인** — strategy 17483. ERROR/STOPPED여도 이 문서만으로 자동 재시작하지 않음.

Trading Scheduler는 **PAUSE 유지**. Scanner는 **SHADOW_ONLY**. 강제 BUY/SELL 금지.

---

관련: [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md) · [CURRENT_WORK.md](../CURRENT_WORK.md)
