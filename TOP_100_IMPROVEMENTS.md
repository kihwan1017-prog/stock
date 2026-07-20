# TOP_100_IMPROVEMENTS.md — STEP63

**원칙:** 기능 추가/리팩터 제안이 아니라 **배포 차단·위험 감소** 우선.  
**정렬:** Critical → High → Medium → Low (번호 = 전체 우선순위 1–100)

각 항목: **파일 · 심볼 · 원인 · 위험도 · 개선방법**

---

## Critical (1–20) — 고객/공개/Live 배포 전 필수

| # | 파일 | 심볼 | 원인 | 위험 | 개선방법 |
|---|------|------|------|------|----------|
| 1 | `api/v1/strategy_runtime_switch.py` | `switch_strategy_runtime` | 인증/권한 Dependency 없음 | 전략 런타임 탈취 | `require_admin` + 감사 로그 |
| 2 | `api/v1/pipelines.py` | `execute_daily_strategy_pipeline` | 무인증 mutate | 파이프라인·외부 API 남용 | `require_admin` |
| 3 | `api/v1/guarded_pipeline.py` | execute 핸들러 | 무인증 | 동일 | `require_admin` |
| 4 | `api/v1/candidate_runs.py` | `execute_candidate_run` | 무인증 | 데이터·AI 부하 | `require_admin` |
| 5 | `order/outbox_runtime.py` | `build_order_outbox_scheduler` | `PaperBrokerAdapter()` 하드코딩 | Live 미전송/상태 거짓 | `create_broker_adapter()` + Live 게이트 |
| 6 | `order/outbox_worker.py` | claim/PROCESSING 경로 | crash 후 재claim 이중 전송 가능 | **중복 실주문** | 브로커 idempotency + stale reclaim TTL |
| 7 | `api/v1/telegram_ops.py` | `telegram_webhook` | `expected` empty면 검증 스킵 | 위조 webhook | prod에서 secret 필수 fail-closed |
| 8 | `api/v1/sync.py` | Kiwoom sync POST | 무인증 | 브로커 쿼터·데이터 오염 | `require_admin` |
| 9 | `api/v1/upbit.py` | sync POST들 | 무인증 | 동일 | `require_admin` |
| 10 | `api/v1/kiwoom_account_sync.py` | synchronize | 무인증 | 계좌 동기화 남용 | `require_admin` |
| 11 | `api/v1/realtime_quotes.py` | start/stop | 무인증 WS 제어 | 리소스·시세 남용 | `require_admin` |
| 12 | `api/v1/ai_analysis.py` (+ 관련 AI 라우터) | run/analyze | 무인증 | GPU DoS | `require_admin` + rate limit |
| 13 | `api/v1/backtest_runs.py` | run | 무인증 | CPU DoS | `require_admin` + 큐/동시성 제한 |
| 14 | `api/v1/indicators.py` | compute/save | 무인증 | DB 쓰기·부하 | `require_admin` |
| 15 | `api/v1/step32_router.py` | executions 등 | Deprecated + 무인증 mutate | 레거시 우회 | 제거 또는 Admin + 비활성 |
| 16 | `position/exit_monitor_runtime.py` | exit 실행 | `skip_risk_checks=True` | Risk/Kill 우회 | 기본 False; 명시적 예외만 |
| 17 | `realtime/runtime.py` | 런타임 초기화 | `account_id=1` 하드코딩 | 오계좌 주문 | 설정/DB에서 계좌 주입 |
| 18 | `api/v1/broker_orders.py` | place/cancel 경로 | Kill Switch와 불균일 가능 | Kill 중 주문 | Canonical `OrderExecutionService`만 |
| 19 | `common/settings.py` + webhook | `telegram_webhook_secret` default `""` | fail-open 기본값 | 운영 실수 시 노출 | 기본 거부, 명시 설정만 허용 |
| 20 | Live E2E 부재 | tests/ | Paper만, Live matrix 없음 | 실주문 회귀 미탐지 | Paper/Live 게이트 통합 테스트 |

---

## High (21–45)

| # | 파일 | 심볼 | 원인 | 위험 | 개선방법 |
|---|------|------|------|------|----------|
| 21 | `order/cancel_replace_service.py` | replace | Kill/Risk 재검증 약함 | Kill 중 정정 | replace에도 Kill+Risk |
| 22 | `frontend/.../tokenStorage.ts` | storage | localStorage JWT | XSS 탈취 | httpOnly cookie / 짧은 TTL |
| 23 | `api/middleware/rate_limit.py` (또는 동등) | `client_ip` | XFF 신뢰 · in-memory | 우회·멀티인스턴스 무력 | 신뢰 프록시만 + Redis |
| 24 | `broker/` vs `brokers/` | 패키지 이중 | 설정/토큰 불일치 | 잘못된 브로커 호출 | 단일 패키지로 통합 |
| 25 | `broker/runtime.py` vs outbox | 이중 주문 경로 | 가드 적용 불균일 | 우회 주문 | 단일 진입점 |
| 26 | `api/lifecycle.py` | `_start_schedulers` | 다수 AsyncIOScheduler | 중복·경합 | Supervisor 1개 + 락 |
| 27 | `TradingOrderEntity.account_id` | entities | FK 부재 | orphan | FK + cascade 정책 |
| 28 | `database/alembic` vs root alembic | 이중 트리 | 잘못된 migration | 스키마 drift | 단일 경로 고정 |
| 29 | Alert 전송 | monitoring | `except: pass` | 침묵 실패 | 메트릭+재시도+로그 |
| 30 | Alert dedup | in-memory | restart 시 storm | 알림 폭주 | Redis/DB dedup |
| 31 | `ai/ollama_client.py` | call | Semaphore 없음 | GPU 폭주 | 전역 semaphore |
| 32 | `ai/candidate_ranker.py` | prompt | raw 뉴스 주입 | prompt injection | sanitize/허용 필드만 |
| 33 | Telegram poller+webhook | ops | 동시 가능 | 명령 중복 | 모드 상호배타 |
| 34 | `order/trading_guards.py` | adapter 선택 | Paper 기본 편향 | Live 오해 | 명시적 mode enum |
| 35 | FE account defaults | pages/hooks | account_id=1 | 오계좌 UI | 로그인 계좌만 |
| 36 | `SystemHealthService` | build | 동기 외부 HTTP | event loop stall | timeout+async+cache |
| 37 | `AdminDashboardSummaryService` | build | God Object | 장애 전파 | 분리·캐시 |
| 38 | Sync Session in async routes | 전역 | 블로킹 | 지연·타임아웃 | async session / to_thread |
| 39 | DR 백업 | ops docs | schema-only 습관 위험 | 데이터 손실 | full dump 검증 리허설 |
| 40 | Windows 단일 인스턴스 | 아키텍처 | SPOF | 장중 중단 | 문서화+재기동 SLA / HA 계획 |
| 41 | `live_trading_transition.py` | validate | Admin 누락 가능 | Live 전환 남용 | `require_admin` 강제 |
| 42 | Rate limit 기본값 | settings | 과도 허용 가능 | 브루트포스 | 로그인/주문 분리 한도 |
| 43 | CORS | settings | 설정 실수 시 개방 | CSRF/탈취 | prod 검증 실패 시 기동 거부 |
| 44 | Audit masking | audit | 일부 필드 누락 가능 | 비밀 로그 | 필드 화이트리스트 |
| 45 | Kiwoom disconnect | ws_manager | 재연결/주문 중단 정책 불명확 | 주문 누락 | 상태 머신+알림+재구독 |

---

## Medium (46–75)

| # | 파일 | 심볼 | 원인 | 위험 | 개선방법 |
|---|------|------|------|------|----------|
| 46 | Pagination 불균일 | 다수 list API | 페이지 규약 없음 | 대량 응답 | 공통 `page/size` |
| 47 | Filtering/Sorting | orders/jobs 외 | 일관성 없음 | UX·부하 | 표준 쿼리 스키마 |
| 48 | Error detail 과다 | 일부 핸들러 | 내부 정보 노출 | 정보 유출 | prod detail 축소 |
| 49 | `step32_router` 등록 | router.py | Legacy 생존 | 공격면 | unregister |
| 50 | `PROJECT_FINAL_AUDIT.md` | docs | DEV_OPEN 등 진부 | 잘못된 운영 | 아카이브/삭제 |
| 51 | STEP README drift | docs | 코드와 불일치 | 온보딩 오류 | STEP63 이후 정리 |
| 52 | `scheduler/automatic.py` | 기동 | lifecycle과 불명확 | 중복 job | 단일 소유권 |
| 53 | `scheduler_admin.run_job_now` | admin | 인스턴스 불일치 | 잘못된 job | scheduler registry |
| 54 | max_instances=1 | jobs | 교차 스케줄러 경합 | DB lock | 분산 락(advisory) |
| 55 | Outbox interval 1s | outbox_runtime | 공격적 폴링 | DB 부하 | 백오프 |
| 56 | Position sync race | position services | 동시 갱신 | 잔고 오류 | 행 락/버전 |
| 57 | Portfolio calc | portfolio | 가격 소스 혼재 | 잘못된 PnL | 단일 price provider |
| 58 | Daily loss / kill | risk_engine | 경로별 적용 불균일 | 손실 한도 미작동 | 전 경로 강제 |
| 59 | Idempotency keys | order API | 클라이언트 미강제 | 중복 제출 | 필수 헤더 |
| 60 | Soft delete / history | orders | 감사 추적 약함 | 분쟁 | append-only event |
| 61 | Migration overlays | docs/migration-overlays | 이중 진실 | 적용 누락 | alembic만 |
| 62 | N+1 screener | quality/screener | ORM 루프 | 지연 | eager/batch |
| 63 | Cache 부재 | dashboard | 매 요청 집계 | CPU | TTL cache |
| 64 | OpenAPI prod off | main.py | ✅ | — | 유지 |
| 65 | Signup prod 403 | auth | ✅ | — | 유지 |
| 66 | Health minimal prod | health | ✅ | — | ready는 보호 검토 |
| 67 | FE AuthGuard only | frontend | middleware 없음 | deep link 노출 | Next middleware |
| 68 | npm postcss advisory | frontend | moderate XSS class | 공급망 | 의존성 bump |
| 69 | pytest Live skip | tests | 3 skipped | 커버 공백 | 명시 skip 사유+게이트 |
| 70 | 무인증 mutate 음성 테스트 | tests | 전수 부족 | 회귀 | 라우터 스캔 테스트 |
| 71 | Chaos/kill mid-order | tests | 없음 | 복구 미검증 | fault injection |
| 72 | Load test | ops | 없음 | 용량 미지 | k6/locust 스모크 |
| 73 | Log rotation | Windows ops | 디스크 | 장애 | nssm/logrotate |
| 74 | Secret on disk | E:\StockTrading | ACL 의존 | 유출 | ACL 체크 스크립트 |
| 75 | Timezone KST | schedulers | 혼선 가능 | job 시각 오류 | 전역 TZ 고정 검증 |

---

## Low (76–100)

| # | 파일 | 심볼 | 원인 | 위험 | 개선방법 |
|---|------|------|------|------|----------|
| 76 | Naming `brokers` vs `broker` | packages | 혼란 | 유지보수 | rename |
| 77 | Long functions | dashboard services | 가독성 | 버그 | 분할 (배포 후) |
| 78 | Utility 남용 | common/ | 경계 흐림 | 결합 | 도메인 이동 |
| 79 | Static 팩토리 | 다수 | 테스트 어려움 | mock 곤란 | DI |
| 80 | Duplicate DTO | schemas | 중복 | drift | 공유 스키마 |
| 81 | Commented dead code | 일부 | 노이즈 | 오해 | 삭제 |
| 82 | TODO 소수 | codebase | 추적 약함 | 방치 | issue 링크 |
| 83 | FE unused vars | tokenStorage.ts | lint warning | 품질 | 정리 |
| 84 | Starlette TestClient warn | pytest | deprecation | 미래 깨짐 | httpx2 |
| 85 | README 길이 | root | 산만 | 온보딩 | 짧은 Quickstart |
| 86 | Manual 한글/영문 혼재 | docs/manual | 일관성 | — | 표준화 |
| 87 | Canvas/데모 페이지 | FE | 미사용 가능 | 번들 | tree-shake |
| 88 | Verbose 캐시 pyc | repo | 커밋 위험 | 오염 | gitignore 확인 |
| 89 | zip artifact | stock-platform.zip | 유출·혼선 | 삭제 | ignore |
| 90 | MCP example secrets | .cursor | 실수 커밋 | 유출 | example만 |
| 91 | Verbose __pycache__ | git status | 노이즈 | — | clean |
| 92 | Indicator recompute | API | 비용 | 캐시 키 | ETag |
| 93 | News poll interval | jobs | 과도 | 쿼터 | 설정화 |
| 94 | Telegram retry storm | notifier | 중복 알림 | 노이즈 | dedup key |
| 95 | Dashboard chart payload | FE | 과대 | 대역 | 집계 API |
| 96 | Type hints 부분 누락 | 레거시 | mypy 약함 | 회귀 | 점진 강화 |
| 97 | Docstring 불균일 | services | 문서화 | — | 핵심만 |
| 98 | Example .env drift | .env.example | 설정 누락 | 기동 실패 | STEP62/63 동기화 |
| 99 | Release note 버전 | docs | RC vs GA | 혼선 | v1.0.0 GA 게이트 |
| 100 | 재감사 자동화 | CI | 수동 STEP63 | 회귀 | auth coverage CI gate |

---

## 우선순위 로드맵 (권장)

### P0 (배포 전, 1–2주)

항목 **1–20** — 무인증 봉쇄, Outbox/Live, webhook fail-closed, account_id, exit skip_risk, Live E2E

### P1 (다음 스프린트)

항목 **21–45** — Kill 균일, rate limit Redis, 패키지 통합, 스케줄러 supervisor, FK, 알림 신뢰성

### P2

항목 **46–75** — API 일관성, 테스트 보강, DR 리허설, 성능

### P3

항목 **76–100** — 위생·문서·품질 (고객 차단과는 무관)

---

## 검증 스냅샷 (감사일)

| 검사 | 결과 |
|------|------|
| pytest | **349 passed**, 3 skipped (`.venv`) |
| FE lint | PASS (warning 2) |
| FE typecheck | PASS |
| FE test | 37 passed |
| FE build | PASS |

---

## 관련 문서

- [FINAL_AUDIT_REPORT.md](FINAL_AUDIT_REPORT.md)
- [RELEASE_RISK.md](RELEASE_RISK.md)
- [PRODUCTION_SCORECARD.md](PRODUCTION_SCORECARD.md)
