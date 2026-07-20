# FINAL_AUDIT_REPORT.md — STEP63 Final Production Audit

**감사일:** 2026-07-20  
**질문:** 오늘 실제 고객에게 배포 가능한가?  
**판정:** **BLOCK RELEASE** (공개망 · Live · 다고객)  
**조건부:** 단일 운영자 · 사설망/VPN · Paper 전용은 **APPROVED WITH CONSTRAINTS** (아래 전제 충족 시)

본 감사는 코드를 **수정하지 않고** 문제만 기록합니다.  
근거는 `src/`, `frontend/`, `tests/`, 운영 문서의 실제 심볼입니다.

---

## 1. Executive Verdict

| 배포 시나리오 | 판정 |
|---------------|------|
| 공개 인터넷 + 실고객 + Live 주문 | **BLOCK RELEASE** |
| 사설망 + 단일 운영자 + Paper + Live OFF | **APPROVED WITH CONSTRAINTS** |
| 스테이징 (동일 보안 전제) | **APPROVED WITH MINOR ISSUES** |

**핵심 차단 사유 (요약)**

1. **무인증 mutate API가 여전히 다수** — pipeline, AI, sync, backtest, strategy switch, realtime quotes 등  
2. **Order Outbox가 `PaperBrokerAdapter`에 고정** — Live outbox 경로가 실질적으로 비활성/오해 소지  
3. **Telegram webhook secret 미설정 시 검증 스킵** — fail-open  
4. **단일 프로세스 Rate Limit · XFF 신뢰** — 다중 인스턴스/프록시에서 무력화  
5. **`account_id=1` 하드코딩 잔존** — 멀티유저 격리 실패  

STEP59–62로 봉쇄된 영역(Broker mutate, kill-switch GET, jobs, paper-fill 등)은 **개선**되었으나,  
“고객 배포” 기준의 Critical 표면은 **닫히지 않았습니다.**

---

## 2. Architecture Audit

### 문제

| ID | 파일 / 심볼 | 원인 | 위험 |
|----|-------------|------|------|
| A-01 | `broker/` vs `brokers/` (이중 Kiwoom 스택) | 패키지 이원화 | 토큰·rate·mock 불일치 |
| A-02 | `broker/runtime.py` vs `order/outbox_runtime.py` | 주문 경로 이중화 | Kill Switch 적용 불균일 |
| A-03 | `operation/admin_dashboard_summary_service.py` `AdminDashboardSummaryService` | God Aggregator | 테스트·확장 어려움 |
| A-04 | 다수 `api/v1/*` 가 Session+Repo 직결 | 레이어 얇음/위반 | 트랜잭션 경계 흐림 |
| A-05 | `api/lifecycle.py` 스케줄러 8개 분리 | Supervisor 부재 | 중복·관측 파편화 |

### 양호 (짧게)

- 도메인 패키지 분리 방향은 존재 (`order`, `risk_engine`, `position`)  
- Canonical `OrderExecutionService.submit` 경로에 Risk/Kill Switch 존재  

**Architecture 점수: 58/100**

---

## 3. Code Quality Audit

| ID | 근거 | 문제 |
|----|------|------|
| Q-01 | `AdminDashboardSummaryService.build` | 과도한 책임 |
| Q-02 | `SystemHealthService.build` | 외부 HTTP 동기 호출 집약 |
| Q-03 | `step32_router.py` | Deprecated이나 등록·mutate 잔존 |
| Q-04 | archive STEP 문서 vs 코드 | 문서 drift |
| Q-05 | `TODO`/`FIXME` 검색은 적음 | Legacy는 라우터·이중 패키지에 존재 |

**Maintainability 점수: 68/100**

---

## 4. API Audit

| ID | 문제 | 예시 |
|----|------|------|
| API-01 | REST mutate에 인증 누락 | `POST /api/v1/pipelines/daily-strategy` |
| API-02 | Error 포맷은 STEP59로 통일됨 | `{code,message,detail,request_id}` ✅ |
| API-03 | Pagination/Filtering 불균일 | jobs/orders 일부만 |
| API-04 | Deprecated step32 엔드포인트 생존 | `step32_router` |
| API-05 | 운영 `/health` 축소 ✅ | 로컬은 상세 유지 |

대략 **APIRouter ~89** vs **auth dependency 흔적 ~41** — 권한 적용 비율이 낮음.

---

## 5. Security Audit (재검사)

### Critical (미봉쇄)

| ID | 파일 | 함수 | 문제 |
|----|------|------|------|
| S-01 | `api/v1/pipelines.py` | `execute_daily_strategy_pipeline` | 무인증 파이프라인 |
| S-02 | `api/v1/guarded_pipeline.py` | execute | 무인증 |
| S-03 | `api/v1/candidate_runs.py` | `execute_candidate_run` | 무인증 |
| S-04 | `api/v1/sync.py` | Kiwoom daily sync | 무인증 |
| S-05 | `api/v1/upbit.py` | sync POST들 | 무인증 |
| S-06 | `api/v1/indicators.py` | compute/save | 무인증 |
| S-07 | `api/v1/ai_analysis.py` 등 | AI 실행 | 무인증 |
| S-08 | `api/v1/backtest_runs.py` | run | 무인증 CPU |
| S-09 | `api/v1/strategy_runtime_switch.py` | `switch_strategy_runtime` | 무인증 런타임 전환 |
| S-10 | `api/v1/realtime_quotes.py` | start/stop | 무인증 WS |
| S-11 | `api/v1/kiwoom_account_sync.py` | synchronize | 무인증 |
| S-12 | `api/v1/step32_router.py` | executions 등 | 무인증 mutate |
| S-13 | `api/v1/telegram_ops.py` | `telegram_webhook` | secret 빈 값이면 검증 스킵 |
| S-14 | `api/v1/live_trading_transition.py` | `validate` | Admin 누락 가능 |

### 개선됨 (STEP62)

- Broker/paper-fill/kill-switch GET/jobs/dashboard 등 `require_admin`  
- JWT DB RBAC 재검증, Refresh reuse revoke-all  
- Rate limit · security headers · CORS 축소  

### Frontend

| ID | 파일 | 문제 |
|----|------|------|
| S-FE-01 | `frontend/src/lib/storage/tokenStorage.ts` | localStorage 토큰 |
| S-FE-02 | AuthGuard만 존재 | 서버 middleware 부재 |

**Security 점수: 52/100**

---

## 6. Database Audit

| ID | 근거 | 문제 | 위험 |
|----|------|------|------|
| D-01 | `order/entities.py` `TradingOrderEntity.account_id` | FK 없음(논리 참조) | orphan / 잘못된 조인 |
| D-02 | STEP57 FK/Index 작업은 존재 | 완전성 미검증 구간 잔존 | 무결성 |
| D-03 | root `alembic/versions` vs `database/alembic` | 이중 트리 혼선 | 잘못된 migration |
| D-04 | sync Session 전역 | async 라우트에서 블로킹 | 지연 |
| D-05 | Dashboard N+1 가격 조회 | 성능 | Admin 지연 |

**DB 운영 성숙도: 중간 (스키마 안정화는 진행, 경로·FK 완전성은 미완)**

---

## 7. Trading Audit

| ID | 파일 / 심볼 | 문제 | 운영 위험 |
|----|-------------|------|-----------|
| T-01 | `order/outbox_runtime.py` `build_order_outbox_scheduler` | **PaperBrokerAdapter 하드코딩** | Live outbox 오해·미전송 |
| T-02 | `order/outbox_worker.py` PROCESSING 중 crash | 재처리/이중전송 레이스 | **중복 실주문** |
| T-03 | `position/exit_monitor_runtime.py` | `skip_risk_checks=True` | 정상 SL/TP도 Risk 우회 가능 |
| T-04 | `api/v1/broker_orders.py` | Admin 직접 place, Kill Switch 불균일 | Kill 중에도 경로 존재 가능 |
| T-05 | `order/cancel_replace_service.py` | replace에 Kill/Risk 재검증 약함 | Kill 중 정정 |
| T-06 | `realtime/runtime.py` | `account_id=1` 기본 | 잘못된 계좌 |
| T-07 | Live 가드 (settings/factory) | mock+live 교차 금지는 ✅ | 설정 실수 시 오동작 |

**Live 자동매매를 “고객 서비스”로 열기엔 불가.**

---

## 8. Scheduler Audit

| ID | 근거 | 문제 |
|----|------|------|
| SCH-01 | `api/lifecycle.py` `_start_schedulers` | 다수 AsyncIOScheduler |
| SCH-02 | `scheduler/automatic.py` | API lifecycle에 자동 기동 불명확 |
| SCH-03 | `scheduler_admin.run_job_now` | 인스턴스 불일치 가능 |
| SCH-04 | max_instances=1 있으나 스케줄러 간 교차 | DB/Broker 경합 |

---

## 9. AI Audit

| ID | 파일 | 문제 |
|----|------|------|
| AI-01 | `ai/ollama_client.py` | Timeout 있으나 Semaphore 없음 |
| AI-02 | `ai/candidate_ranker.py` | 뉴스/공시 raw prompt 주입 |
| AI-03 | 무인증 AI API | GPU/CPU DoS |
| AI-04 | AI → 주문 직접 실행은 없음 ✅ | 단, 우회 API가 열리면 무의미 |

---

## 10. Telegram Audit

| ID | 파일 | 문제 |
|----|------|------|
| TG-01 | `telegram_webhook` | secret empty → fail-open |
| TG-02 | poller + webhook 동시 가능 | 명령 중복 |
| TG-03 | Chat allowlist fail-closed ✅ | secret과 별개 |
| TG-04 | Retry 시 중복 알림 가능 | 노이즈 |

---

## 11. Monitoring Audit

| ID | 평가 |
|----|------|
| M-01 | `/health/live|ready` ✅ |
| M-02 | monitoring overview + alert rules ✅ |
| M-03 | Alert dedup in-memory only — restart 시 폭주 |
| M-04 | Alert 전송 실패 swallow (`except: pass`) |
| M-05 | 운영 health 최소 공개 ✅ |

**Monitoring 점수: 70/100**

---

## 12. Performance Audit

| ID | 문제 |
|----|------|
| P-01 | Sync ORM in async FastAPI |
| P-02 | Health/dashboard 외부 HTTP |
| P-03 | Screener/품질 N+1 (KNOWN) |
| P-04 | Exit monitor to_thread (STEP58) ✅ 부분 개선 |
| P-05 | Ollama 동시성 제한 없음 |

**Performance 점수: 55/100**

---

## 13. Documentation Audit

| 문서 | 평가 |
|------|------|
| INSTALL / OPERATIONS / RELEASE_CHECKLIST | 양호 |
| SECURITY_AUDIT_STEP62 | 양호, 잔여 Critical 명시 |
| PROJECT_FINAL_AUDIT.md | **일부 진부** (DEV_OPEN 등) |
| STEP README 다수 | 유용하나 drift |
| Docker 없음 | 의도적이나 고객 SaaS 기준 미달 |

**Documentation 점수: 78/100**

---

## 14. Testing Audit

| 항목 | 결과 |
|------|------|
| pytest (2026-07-20) | **349 passed**, 3 skipped |
| FE test | 37 passed |
| FE build | PASS |
| lint | warnings only (tokenStorage unused) |
| Live broker E2E | **없음** |
| 무인증 mutate 음성 테스트 전수 | **부족** (STEP62는 일부만) |
| 부하/카오스 | **없음** |

**Testing 점수: 62/100**

---

## 15. Production Risks (데이터/주문)

1. **중복 실주문** — Outbox PROCESSING crash + Paper/Live 혼선  
2. **주문 누락** — Outbox Paper 고정으로 Live 기대 시 미전송  
3. **무인증 파이프라인/동기화** — 데이터 오염·API 키 소진  
4. **전략 런타임 탈취** — `strategy_runtime_switch` 무인증  
5. **Kill Switch 우회 경로** — broker_orders / skip_risk exit  
6. **Memory/Event-loop stall** — 무인증 backtest/AI  
7. **Telegram 위조 명령** — webhook secret 미설정  
8. **Recovery 실패** — 다중 스케줄러·단일 인스턴스 전제  

---

## 16. Final Scores

| 항목 | 점수 | 한줄 근거 |
|------|------|-----------|
| Architecture | **58** | 이중 broker/주문 경로, God service |
| Security | **52** | STEP62 봉쇄 + 대형 무인증 잔존 |
| Performance | **55** | sync ORM, AI 동시성, N+1 |
| Maintainability | **68** | 문서·패키지 있으나 Legacy 라우터 |
| Documentation | **78** | 운영 문서 충실, 일부 진부 |
| Monitoring | **70** | live/ready/overview 있음, dedup 약함 |
| Testing | **62** | 단위 풍부, Live/보안 전수 부족 |
| Release Readiness | **45** | 고객 Live 배포 불가 |

**종합: 56 / 100**

---

## 17. Production Decision

### **BLOCK RELEASE**

**대상:** 실제 고객 · 공개망 · Live 자동매매 · 멀티테넌시

**이유:**

1. Critical 무인증 mutate API가 다수 남아 있음 (증거: `pipelines.py`, `strategy_runtime_switch.py`, `ai_*`, `sync.py` 등)  
2. Outbox가 Paper에 고정되어 Live 주문 신뢰성이 없음 (`outbox_runtime.py`)  
3. Telegram webhook이 secret 없이 fail-open (`telegram_ops.py`)  
4. Live E2E·카오스 테스트 부재  

### 조건부 허용 (고객 배포 아님)

**사설망 + 단일 운영자 + `KIWOOM_LIVE_ORDER_ENABLED=false` + Paper만**  
→ `APPROVED WITH CONSTRAINTS` (TOP Critical 중 무인증 API를 방화벽/네트워크로 격리한다는 전제)

---

## 18. Verification Snapshot

| 검사 | 결과 |
|------|------|
| pytest | 349 passed, 3 skipped |
| frontend lint | PASS (warning 2) |
| frontend typecheck | PASS |
| frontend test | 37 passed |
| frontend build | PASS |

---

## 19. Related Artifacts

- [RELEASE_RISK.md](RELEASE_RISK.md)  
- [PRODUCTION_SCORECARD.md](PRODUCTION_SCORECARD.md)  
- [TOP_100_IMPROVEMENTS.md](TOP_100_IMPROVEMENTS.md)  
- [SECURITY_AUDIT_STEP62.md](SECURITY_AUDIT_STEP62.md)  
- [KNOWN_ISSUES.md](KNOWN_ISSUES.md)
