# KI-TRD-02 Outbox Fencing

## 문제

`PROCESSING` Lease 만료 후 다른 Worker가 재Claim하면, Broker 전송 여부가 불명한 채 재전송될 수 있다.

## 해결 (STEP 8-5-22)

| 메커니즘 | 동작 |
|----------|------|
| `fencing_token` | Claim 시 단조 증가. 상태 변경은 토큰+owner+lease 일치 시에만 |
| `lease_expires_at` | Claim TTL (기본 2분) |
| `dispatch_intent_at` + `request_hash` | Broker **호출 전** Commit. Intent 후 Lease 만료 → **AMBIGUOUS** (자동 RETRY 금지) |
| Intent 없는 stale | RETRY 허용 |
| 늦은 응답 | 구 Token → `OUTBOX_STALE_RESPONSE_IGNORED`, 상태 덮어쓰기 불가 |
| Hash 불일치 | MANUAL_REVIEW |
| `broker_order_id` on order | 재전송 억제 |
| Admin | `/ambiguous`, `/confirm-absent`, `/approve-retry` (무조건 재전송 버튼 없음) |

Migration: `j3d4e5f6a7b8`

상태: **MITIGATED / CLOSED for KI-TRD-02 Critical** (자동 재전송 경로 제거).
