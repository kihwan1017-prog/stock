# STEP 8-11 — 통합 운영 모니터링 Dashboard

## 1. 목적

관리자가 자동매매 운영 전 상태를 **한 화면**에서 조회한다.  
**Read-only** — 실주문, LIVE ON, ARM, Scheduler Resume, Kill Switch 변경 없음.

## 2. 접근 경로

- URL: `/admin/operations-dashboard`
- 메뉴: 운영 → **통합 모니터링**
- 권한: Admin (`require_admin` + `menu:scheduler`)

## 3. Backend API

Prefix: `/api/v1/admin/operations-dashboard`

| Method | Path | 설명 |
|--------|------|------|
| GET | `/overview` | Overall / DB / Broker / Scheduler / Runtime / Kill / Alerts |
| GET | `/accounts` | 계좌별 Readiness |
| GET | `/schedulers` | Scheduler Desired/Actual |
| GET | `/runtimes` | Strategy Runtime Registry |
| GET | `/risk` | Daily Loss·Risk Limits |
| GET | `/orders` | 주문·체결 (filter/pagination) |
| GET | `/positions` | Broker Position Snapshot |
| GET | `/alerts` | 통합 경고·Manual Review |
| GET | `/audits` | Audit (민감정보 제거) |
| GET | `/notifications` | Inbox·Telegram 상태 |

## 4. Overall 판정

Backend `compute_overall_status` 단일 기준:

- **ERROR**: DB Unhealthy, Kill Switch, Broker ERROR, Trading Scheduler 의도치 않은 RUNNING, Manual Review, Critical Alerts
- **WARNING**: Broker stale/unhealthy, Runtime errors 등
- **HEALTHY**: 그 외

Frontend는 표시만 한다.

## 5. Readiness

계좌별 `dry_run_ready` / `live_execution_ready` / `blockers`.  
Credential 값·ARM Token·Broker UUID 원문 미반환. 계좌번호 마스킹.

## 6. Daily Loss

`UbaDailyLossService.diagnose` 재사용 (baseline 쓰기 금지).  
사용률: 0–69 NORMAL / 70–89 WARNING / 90–99 DANGER / ≥100 BLOCKED.

## 7. Scheduler Desired vs Actual

- Trading/Tracking/Post-fill: `collect_scheduler_readiness`
- **Recovery**: `broker_recovery_scheduler.status()` + `recovery_scheduler_enabled`
  - Desired: enabled면 RUNNING, 아니면 STOPPED
  - Actual: DISABLED / COOLDOWN / RUNNING / STOPPED / UNKNOWN
  - Startup Cooldown은 STOPPED 경고로 취급하지 않음
  - Recovery는 lifecycle cron 게이트와 무관하게 기동 (STEP 8-11A)

## 8. Stale (설정)

`ops_dashboard_*_stale_seconds`, `ops_dashboard_broker_balance_ttl_seconds`  
하드코딩 금지.

## 9. Fail Closed

Broker 잔고 조회 실패 시 `0` 위장 금지 → `status=ERROR|UNKNOWN`, `reason_code` 반환.  
전체 Dashboard 500 방지.

## 10. 자동 새로고침

기본 10초. UI에서 끔/5/10/30/60초. 백그라운드 탭은 호출 중단.  
서버 설정 변경 없음.

## 11. 장애 시 확인 순서

1. Overview Overall / Critical Alerts  
2. Kill Switch  
3. 계좌 Blockers (Credential, Open Orders, KRW, Daily Loss)  
4. Scheduler Desired≠Actual  
5. Alerts Manual Review  
6. Audit correlation_id  

## 12. 실주문 절차와 분리

실주문은 STEP 8-10 운영자 승인 게이트·STEP 8-12 검증에서만.  
본 Dashboard에서는 상태 변경 API를 호출하지 않는다.

## 13. STEP 8-12 전 확인

- Dry-run Ready  
- Orderable KRW ≥ 주문금액  
- Daily Loss Remaining  
- Trading Scheduler PAUSED  
- Tracking/Post-fill RUNNING  
- Kill Switch OFF  
- Manual Review 0  
