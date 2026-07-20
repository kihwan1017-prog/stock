# KNOWN_ISSUES.md — v1.0.0

**버전:** 1.0.0 GA  
**성격:** 운영 전 필수 인지 사항 (기능 요청 목록 아님)  
**감사 원본:** [FINAL_AUDIT_REPORT.md](FINAL_AUDIT_REPORT.md) · [TOP_100_IMPROVEMENTS.md](TOP_100_IMPROVEMENTS.md)

---

## Critical (공개망/Live 차단 사유)

| ID | 내용 | 영향 | 완화 |
|----|------|------|------|
| KI-SEC-10 | pipeline / guarded_pipeline / candidate_runs 무인증 mutate | 파이프라인·부하 남용 | VPN/ACL · 후속 `require_admin` |
| KI-SEC-11 | sync / upbit / kiwoom_account_sync / indicators 무인증 | 데이터·쿼터 오염 | 동일 |
| KI-SEC-12 | ai_* / backtest_runs 무인증 | GPU/CPU DoS | 동일 + rate limit |
| KI-SEC-13 | strategy_runtime_switch / realtime_quotes 무인증 | 런타임·WS 탈취 | 동일 |
| KI-SEC-14 | step32_router deprecated mutate 잔존 | 레거시 우회 | 제거 또는 Admin |
| KI-SEC-15 | Telegram webhook secret 빈 값 → 검증 스킵 | 위조 webhook | **운영에서 secret 필수** |
| KI-TRD-01 | Outbox가 `PaperBrokerAdapter` 고정 (`outbox_runtime`) | Live 미전송·상태 거짓 | Live OFF 전제 · 후속 factory 연결 |
| KI-TRD-02 | Outbox PROCESSING crash 재처리 레이스 | **중복 주문** | 수동 재전송 금지 · idempotency |
| KI-TRD-03 | Exit monitor `skip_risk_checks=True` | Risk 우회 | Kill Switch·감시 강화 |
| KI-TRD-04 | `account_id=1` 하드코딩 (`realtime/runtime` 등) | 오계좌 | Paper 단일 계좌 전제 |

---

## High

| ID | 내용 | 완화 |
|----|------|------|
| KI-AUTH-01 | 일부 조회 API 권한 약함 가능 | VPN |
| KI-AUTH-02 | localStorage JWT (FE) | XSS 방어 · 내부망 |
| KI-RATE-01 | Rate limit in-memory · XFF 신뢰 | 단일 인스턴스 · 공개망 금지 |
| KI-ARCH-01 | `broker/` vs `brokers/` 이중 스택 | 문서 인지 · 후속 통합 |
| KI-SCH-01 | 다수 AsyncIOScheduler | API 단일 프로세스만 |
| KI-DB-01 | 일부 order account FK 부재 | orphan 모니터링 |
| KI-DB-02 | alembic 경로 이중(root overlay) | canonical `database/alembic`만 |

---

## Medium

| ID | 내용 |
|----|------|
| KI-PERF-01 | sync ORM in async · dashboard 외부 HTTP |
| KI-PERF-02 | Screener/Quality N+1 |
| KI-AI-01 | Ollama Semaphore 없음 |
| KI-MON-01 | Alert dedup in-memory · 전송 실패 swallow |
| KI-OPS-01 | Docker/HA 없음 (의도) |
| KI-FE-01 | 일부 Admin UnimplementedNotice |
| KI-DOC-01 | `PROJECT_FINAL_AUDIT.md` 등 일부 진부 문서 |

---

## Mitigated in RC/GA (참고)

| ID | 내용 | 상태 |
|----|------|------|
| KI-SEC-01 | 다수 Broker/Realtime mutate 무인증 | STEP59/62 `require_admin` |
| KI-SEC-02 | 운영 Swagger | prod 비활성 |
| KI-SEC-03 | 공개 signup | prod 403 |
| KI-HEALTH-01 | health 상세 | prod 최소 · live/ready 분리 |

---

## Out of Scope

- OpenClaw  
- Discord 알림 UI  
- 멀티테넌시 SaaS · Docker HA  

---

## 운영 전제 (GA)

- API **공개 인터넷 직접 노출 금지**
- `KIWOOM_LIVE_ORDER_ENABLED=false`
- Known Issues 인지 후 [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md) 서명
- Critical 해소 전 고객 Live 배포 금지
