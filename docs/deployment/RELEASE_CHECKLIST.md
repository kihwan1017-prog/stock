# stock-platform v1.0 Release Checklist

## 검증

- [ ] `alembic upgrade head` 성공
- [ ] `alembic heads` 단일 head
- [ ] `pytest -q` 전체 통과
- [ ] `GET /health` 응답 확인
- [ ] `GET /api/v1/system/dashboard` 응답 확인
- [ ] 모의 주문 Outbox 경로 확인
- [ ] 실전 주문 기본 차단 확인
- [ ] `ADMIN_API_KEY` 운영 설정

## 문서

- [x] INSTALL.md
- [x] CONFIGURATION.md
- [x] ARCHITECTURE.md
- [x] API.md
- [x] OPERATIONS_RUNBOOK.md
- [x] INCIDENT_RESPONSE.md
- [x] LIVE_TRADING_CHECKLIST.md
- [x] TROUBLESHOOTING.md
- [x] CHANGELOG.md

## 태그

```powershell
git tag v1.0.0
git push origin v1.0.0
```
