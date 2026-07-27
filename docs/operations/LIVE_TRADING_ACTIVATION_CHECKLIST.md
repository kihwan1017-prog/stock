# LIVE Trading Activation Checklist — 실행 상태

**갱신:** 2026-07-26 (STEP 8-6-1A)

| 항목 | 상태 | 근거 / 명령 |
|------|------|-------------|
| Alembic head `k8b9c0d1e2f3` | PASS | `alembic current` |
| GLOBAL_LIVE_ORDER_ENABLED=false | PASS | ops env |
| KIWOOM_USE_MOCK=true | PASS | 동일 |
| KIWOOM_LIVE_ORDER_ENABLED=false | PASS | 동일 |
| UPBIT_LIVE_ORDER_ENABLED=false | PASS | 동일 |
| Backend pytest 0 fail/skip | PASS | 전체 suite |
| Frontend vitest/tsc/lint/build | PASS | 98 / OK |
| Backup 생성·checksum | PASS | RC21/RC22 |
| 빈 DB CREATE+upgrade | **PASS** | `rc22_db_verify.py empty-upgrade` |
| Official Restore | **PASS** | `rc22_db_verify.py restore` · row count match |
| DB Release Blocker | **0** | — |
| Telegram webhook secret | PASS | Fail Closed + 운영 설정 |
| Activation expires_at | PASS | Migration + get_active |
| LIVE Dry Run API | PASS | `/dry-run` |
| KI-TRD-02 Outbox Fencing | PASS | `j3d4e5f6a7b8` |
| Operation Rehearsal | PASS | `run_operation_rehearsal.py --full` |
| Kill Switch 경로 | PASS | 기존 가드 |
| 공개망 노출 | 범위 제외 | 로컬/VPN |
| 소액 LIVE | **APPROVED** | 로컬/VPN 전제 |

## 서명

- Paper: APPROVED
- 소액 LIVE (로컬/VPN): APPROVED
- 공개망: 범위 제외
