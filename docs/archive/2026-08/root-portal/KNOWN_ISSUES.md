# KNOWN_ISSUES.md

**현재 릴리즈:** v1.0 RC (GO — Paper / 소액 LIVE 로컬·VPN)  
**최종 갱신:** STEP 8-6-1A (2026-07-26)

### v1.1.0 추가 (User Self)

| ID | 등급 | 내용 | 완화 |
|----|------|------|------|
| KI-U11-01 | Medium | Telegram QUEUED→SENT/DLQ 미구현 | Web Inbox |
| KI-U11-02 | Medium | Watchlist 그룹 없음 | flat 목록 |
| KI-U11-03 | Medium | Trading/Strategies/Auto-trading UI·admin API 혼재 | 메뉴 제한 |
| KI-U11-04 | Low | Playwright E2E 미자동화 | 수동 UAT |

---

# KNOWN_ISSUES — v1.0.0 (누적)

상세: [docs/security/KI_SEC_KNOWN_ISSUES.md](docs/security/KI_SEC_KNOWN_ISSUES.md) · [docs/trading/KI_TRD_KNOWN_ISSUES.md](docs/trading/KI_TRD_KNOWN_ISSUES.md)

## Critical (공개망/고객 Live)

| ID | 내용 | 영향 | 완화 / 상태 |
|----|------|------|-------------|
| ~~KI-TRD-02~~ | Outbox reclaim 레이스 | 중복 주문 | **FIXED 8-5-22** Fencing |
| KI-SEC-15 | Telegram webhook | 위조 webhook | **FIXED** Fail Closed + 운영 secret 설정 |

## High (소액 LIVE)

| ID | 내용 | 완화 |
|----|------|------|
| ~~KI-OPS-RC22-01~~ | 빈 DB / Restore DBA | **FIXED** Official Restore PASS · DB Release Blocker 0 |

## Medium

| ID | 내용 |
|----|------|
| KI-PERF-01 | sync ORM in async · dashboard 외부 HTTP |
| KI-PERF-02 | Screener/Quality N+1 |
| KI-AI-01 | Ollama Semaphore 없음 |
| KI-MON-01 | Alert dedup in-memory |
| KI-OPS-01 | Docker/HA 없음 (의도) |
| KI-FE-01 | 일부 Admin UnimplementedNotice |
| KI-SNAP-01 | Snapshot 레거시 account Unique |
| KI-FE-PL-01 | Position Limit Admin UI 부재 |

## 운영 전제

- API **공개 인터넷 직접 노출 금지** (공개망 범위 제외)
- 소액 LIVE는 로컬/VPN 전제
- [docs/release/V1_0_RC_FINAL_APPROVAL.md](docs/release/V1_0_RC_FINAL_APPROVAL.md)
- 리허설: [docs/operations/README_OPERATION_REHEARSAL.md](docs/operations/README_OPERATION_REHEARSAL.md)
