# STEP 18 — 운영 스크립트·백업·복구

## 현황
ops/ NSSM·backup/restore, scripts/run_scheduler.py, health/monitoring snapshot, lifecycle 리더 락(STEP9).

## 검증
운영 DB 파괴 테스트 미실시(안전). 복구는 별도 테스트 DB에서 수행 권장.

## 권장
AutomaticScheduler를 NSSM 별도 서비스로 등록. SCHEDULER_LEADER_LOCK_ENABLED=true (multi replica).

## 권장 커밋
docs(step18): document ops scheduler and backup posture
