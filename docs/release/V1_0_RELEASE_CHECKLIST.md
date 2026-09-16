# v1.0 Release Checklist

운영 배포 직전 체크리스트. 항목을 모두 확인한 뒤 서명한다.

## A. 코드·스키마

- [ ] Alembic single head = `h1b2c3d4e5f6` (`alembic heads` / `alembic current`)
- [ ] 운영 DB `alembic upgrade head` 완료
- [ ] Backend pytest 0 failed / 0 skipped
- [ ] Frontend vitest + typecheck + lint + build PASS
- [ ] 신규 Release Blocker 없음

## B. 환경

- [x] 운영 env RC 안전값 (STEP 8-5-21)
- [ ] `TELEGRAM_WEBHOOK_SECRET` 비어 있지 않음
- [ ] 빈 DB Migration (DBA)
- [ ] Restore 검증 (DBA)
- [x] Backend/Frontend 테스트 PASS
- [x] Alembic head `i2c3d4e5f6a7`

## C. 안전장치

- [ ] Kill Switch 동작 확인
- [ ] Health CRITICAL 시 LIVE 주문 차단 확인
- [ ] 계좌 격리(UBA/Paper) 스모크
- [ ] Telegram webhook secret 비어 있지 않음 (사용 시)

## D. 운영

- [ ] `ops/health_check.bat` PASS
- [ ] 서비스 시작/중지/재시작
- [ ] NSSM 등록·재부팅 자동시작 (해당 시)
- [ ] 최근 DB 백업 존재·파일 크기 정상

## E. LIVE (해당 시에만)

- [ ] `docs/operations/LIVE_TRADING_ACTIVATION_CHECKLIST.md` 전부 완료
- [ ] 관리자 명시 승인 기록

## 서명

| 역할 | 이름 | 일자 | 결과 |
|------|------|------|------|
| 개발 | | | |
| 운영 | | | |
| 승인 | | | GO / GO CONDITIONAL / NO-GO |
