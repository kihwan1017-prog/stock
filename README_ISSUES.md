# 문제 이슈사항 정리 (증권사 납품 기준)

**종합 판정(감사 시점):** 51/100 · NO-GO  
**근거:** `README_FINAL_AUDIT.md`, `README_AUDIT_API.md`, `README_AUDIT_DB.md`, `README_AUDIT_TEST.md`, `README_AUDIT_01.md`  
**현행 조치:** 아래 상태열. 감사 스냅샷 동기화는 `PROJECT_FINAL_AUDIT.md` §0.

## P0 — 납품 차단

| ID | 이슈 | 상태 | 조치 |
|----|------|------|------|
| P0-1 | 무인증 mutate POST 다수 | **완화** | 핵심 라우터 `require_admin` + policy/live-transition 라우터 게이트 |
| P0-2 | deprecated `step32` 무인증 paper fill | **해결** | `router.py` 언마운트 + `step32_router.py` tombstone |
| P0-3 | `paper_order.account_id` 부재 | **해결** | 마이그레이션 `h4c5d6e7f8a9` + ORM/서비스 |
| P0-4 | 핵심 FK 누락 | **완화** | `h4` + `j6e7f8a9b0c1`(leaderboard/pipeline/metric/selection) |
| P0-5 | CI/CD 부재 | **해결** | `.github/workflows/ci.yml` + Docker Compose |
| P0-6 | coverage/보안 테스트 공백 | **완화** | `pytest-cov` 게이트 + `test_security_step62` 확장 |
| P0-7 | Live 이중 게이트 증적 | **완화** | `docs/trading/LIVE_TRADING_CHECKLIST.md` 이중 게이트 섹션 |

## P1 — 인수 전

| ID | 이슈 | 상태 | 조치 |
|----|------|------|------|
| P1-1 | Rate limit 편중 | **완화** | 주문/sync/pipeline/backtest/AI 고비용 POST 적용 |
| P1-2 | FE localStorage + middleware 없음 | **완화** | sessionStorage + 쿠키 동기화 + `middleware.ts` |
| P1-3 | `account_id=1` 하드코딩 | **완화** | `REALTIME_PAPER_ACCOUNT_ID` / Query None→설정 |
| P1-4 | instrument CASCADE | **완화** | `i5`+`j6` RESTRICT (일별·분봉·틱·호가) |
| P1-5 | 진짜 PG integration | **완화** | `tests/test_postgres_integration.py` |
| P1-6 | Outbox race 테스트 | **완화** | `tests/test_outbox_race.py` |
| P1-7 | Backup/RTO | **완화** | `/ops/backup/status` RTO·RPO + `/ops/backup/dump` |
| P1-8 | broker/markets 이중 스택 | 잔여 | 점진 통합 |
| P1-9 | User mutate RBAC 왜곡 | **완화** | mutate → `trading:write` |
| P1-10 | Docker 산출물 | **해결** | `Dockerfile` / `docker-compose.yml` |
| P1-11 | ENV 경로 머신 고정 | **완화** | `STOCK_PLATFORM_ENV_FILE` 탐색 + `BACKUP_DIR` |

## P2–P3

| ID | 이슈 | 상태 |
|----|------|------|
| P2-1~3 | 에러/Envelope/OpenAPI | **완화** (`error_catalog` 핸들러 적용, OpenAPI securitySchemes) |
| P2-4 | 진짜 E2E | **완화** (Playwright 스캐폴드 `frontend/e2e`, CI 미연결) |
| P2-5~11 | runner/로그/부하 등 | 잔여 |
| P3-* | dead code/코멘트/레거시 alembic | **완화** (indicator/step32 tombstone 유지) |

## 권장 검증

```bash
python -m alembic upgrade head
python -m pytest --cov=stock_platform --cov-fail-under=25
cd frontend && npm test && npm run typecheck
```
