# STEP 10-3 — Operations Center Dashboard

## Architecture

```
Admin UI (/admin/dashboard)
  → GET /api/v1/admin/dashboard/summary (5s polling)
  → OperationsCenterDashboardService
       → OpsMonitoringDashboardService (STEP 8-11 재사용)
       → TradingSchedulerControlService.status (STEP 10-2)
       → resource_monitor / runtime_info
       → in-process TTL cache (3s)
```

**Read-only** — DB Mutation 없음, 주문/LIVE/ARM/Scheduler 제어 없음.

## API

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/v1/admin/dashboard/summary` | 통합 Summary (`require_admin`) |

Query: `cache_ttl_sec` (0–30, default 3)

응답 섹션: `system`, `runtime`, `scheduler`, `safety`, `broker`, `orders`, `accounts`, `positions`, `audit`

## UI

- 경로: `/admin/dashboard` (Operations Center)
- 9개 카드: System, Trading Engine, Safety, Broker, Orders, Account, Positions, Scheduler, Audit
- 5초 polling, `placeholderData`로 부분 갱신
- 탭 비가시 시 polling 중단

## Health

`HEALTHY` / `WARNING` / `ERROR` — `compute_overall_status` 재사용

## Refresh

- 기본 5초 (`refetchInterval`)
- 백엔드 3초 TTL 캐시

## Performance

- Summary 1회 호출로 초기 로딩
- N+1 방지: 기존 ops batch 집계 재사용
- 목표: 500ms 이내 (캐시 hit 시 더 빠름)

## Security

- `require_admin` RBAC
- Audit/계좌 마스킹 — ops monitoring masking 재사용
- Mutation API 없음

## 운영 방법

1. Admin 로그인 → Dashboard
2. Overall / Scheduler blocked_reason / Safety 확인
3. 상세 탭: `/admin/operations-dashboard` (STEP 8-11)

## Related

- STEP 8-11: `OPERATIONS_MONITORING_DASHBOARD_8_11.md`
- STEP 10-2: Scheduler desired/actual 영속화
