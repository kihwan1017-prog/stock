# Incident Response Checklist

## 1. 즉시 조치 (분 단위)

- [ ] Kill Switch 활성화 (시스템 / 브로커 / 해당 UBA)
- [ ] LIVE 플래그 OFF (`KIWOOM_*` / `UPBIT_*` / `GLOBAL_*`)
- [ ] 신규 주문 API 차단 확인 (Health / trading guards)
- [ ] 영향 계좌·주문 ID·correlation id 기록

## 2. 상태 파악

- [ ] `ops/health_check.bat` / Admin Monitoring
- [ ] 최근 주문: CREATED→…→AMBIGUOUS/MANUAL_REVIEW 여부
- [ ] Broker 원장 vs 로컬 Order/Fill/Position
- [ ] Scheduler claim 잔류·stuck job
- [ ] Snapshot ACTIVE / Freshness
- [ ] Settlement 진행·락

## 3. 복구

- [ ] Unified Recovery (UBA 단위) 실행
- [ ] Ambiguous Resolver / Manual Review 처리
- [ ] Reconciliation 후 Position·Balance 확인
- [ ] 필요 시 DB 백업본 복구 절차 (`BACKUP_RESTORE_VERIFICATION.md`) — **승인 후**

## 4. 사후

- [ ] Audit / 로그에서 Secret·원문 계좌번호 노출 여부 점검
- [ ] Known Issues / 변경 기록
- [ ] LIVE 재개 전 Activation Checklist 재수행

## 심각도 가이드

| 등급 | 예 | 조치 |
|------|----|------|
| CRITICAL | 중복 실주문, 타 계좌 혼합, Secret 유출 | Kill+LIVE OFF+복구 |
| HIGH | Settlement 실패, Snapshot stale | 주문 일시중지·정합 |
| MEDIUM | Scheduler misfire | Job 재처리 |
| LOW | UI 오류 | 티켓 |
