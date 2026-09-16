# README_AUDIT_01.md — Stock Platform 전체 감사 보고서

| 항목 | 내용 |
|------|------|
| **감사일** | 2026-07-21 |
| **범위** | Backend (`src/stock_platform`) · Frontend (`frontend`) · Database · Scheduler · Broker · Auth · Ops |
| **원칙** | 코드/DB/설정 **근거만** 사용. **코드 수정·신규 기능 구현 없음.** |
| **Alembic head** | `g3b4c5d6e7f8` (STEP73) |
| **DB 스키마(라이브)** | ai(6) · auth(8) · backtest(3) · disclosure(4) · market(7) · news(5) · notification(3) · operation(18) · strategy(4) · trading(25) |
| **비교 기준** | `PROJECT_FINAL_AUDIT.md` (2026-07-19) — STEP65–75 이후 다수 항목이 **해소됨** |

### 한 줄 요약

User 플랫폼(STEP65–75)·주문 실행 인증·DEV_OPEN 제거·ExitMonitor lifecycle 연결은 **이전 대비 크게 개선**됐다.  
잔여 **Critical**은 레거시/운영 mutate API의 **무인증 노출**과 `step32` 런타임 버그, Admin/Realtime의 **`account_id=1` 하드코딩**이다.

### 영향도 범례

| 등급 | 의미 |
|------|------|
| **Critical** | 즉시 악용·데이터 훼손·자금/계좌 위험 |
| **High** | 출시 전 필수 조치 |
| **Medium** | 운영 안정성·유지보수 리스크 |
| **Low** | 정리/문서화 수준 |

---

## 1. 미구현 기능

### 1.1 User 뉴스 AI 요약

| 항목 | 내용 |
|------|------|
| **위치** | `frontend/src/app/(user)/user/news/page.tsx` (배너·상세 Alert) |
| **문제** | 뉴스 목록/상세는 동작하나 AI 요약 UI가 “준비 중”으로 고정. 공시 AI 요약(STEP69)과 비대칭. |
| **영향도** | Medium |
| **수정방법** | 뉴스 전용 AI 요약 API 구현 후 UI 연결, 또는 배너/문구 제거하고 “미제공”으로 제품 스펙을 고정. |

### 1.2 User 매매 SSE/WS 시세 UI

| 항목 | 내용 |
|------|------|
| **위치** | `frontend/src/app/(user)/user/trading/page.tsx` (~863, TODO 주석) |
| **문제** | `GET /api/v1/realtime-quotes/stream/sse` 등 BE 존재 가능 구간과 User UI 미연결. 폴링 위주. |
| **영향도** | Medium |
| **수정방법** | SSE/WS 구독 컴포넌트 연결 또는 TODO·배너 제거 후 폴링-only를 공식 스펙으로 문서화. |

### 1.3 User 전략 배포 삭제 / 포트폴리오 최적화

| 항목 | 내용 |
|------|------|
| **위치** | `frontend/src/app/(user)/user/strategies/page.tsx` (~592, ~866) |
| **문제** | `DELETE /strategy-deployments/{id}`, `POST /portfolio-optimize` UI는 있으나 Backend 미연결(UnimplementedNotice). |
| **영향도** | Medium |
| **수정방법** | API 추가 후 연결, 또는 섹션/CTA를 메뉴·화면에서 숨김. |

### 1.4 User Kill Switch 조작 · 자동매매 스케줄 CRUD

| 항목 | 내용 |
|------|------|
| **위치** | `frontend/src/app/(user)/user/auto-trading/page.tsx` (~363, ~528) |
| **문제** | Kill Switch activate/deactivate·스케줄 CRUD가 User 권한으로 미구현(Admin 전용/미존재). |
| **영향도** | High (제품 기대치 vs 실제 권한 불일치) |
| **수정방법** | User용 제한 API 설계(읽기 전용 상태만 등) 또는 조작 UI 제거·Admin 딥링크만 제공. |

### 1.5 웹 Backup dump / Restore / 앱 로그 테일

| 항목 | 내용 |
|------|------|
| **위치** | `src/stock_platform/api/v1/ops_db.py` (`GET /backup/status`만) · `frontend/.../admin/operations/page.tsx` · `operationCenterTiles.ts` |
| **문제** | pg_dump/pg_restore **가용성 점검만** 존재. 실행·복구·로그 테일 POST API 없음. |
| **영향도** | High (운영 사고 시 웹에서 복구 불가) |
| **수정방법** | CLI 전용으로 명시하거나, Admin+감사로그 보호된 dump/restore/log-tail API 추가. |

### 1.6 Upbit 주문

| 항목 | 내용 |
|------|------|
| **위치** | `src/stock_platform/api/v1/upbit.py` (시세/sync POST만) |
| **문제** | 시세·캔들 sync는 있으나 **주문/체결 API 없음**. |
| **영향도** | Medium (의도적 범위 제외 가능) |
| **수정방법** | 제품 범위에서 “시세만” 명시하거나, 주문 어댑터·가드·API를 Kiwoom 경로와 동일 수준으로 설계. |

### 1.7 2FA (Two-Factor Auth)

| 항목 | 내용 |
|------|------|
| **위치** | `src/stock_platform/auth/profile_service.py` (~66–69) |
| **문제** | `two_factor_enabled` 등 필드를 **항상 False/None**으로 반환하는 확장 자리만 존재. |
| **영향도** | Medium |
| **수정방법** | TOTP/이메일 2FA 구현 또는 API 응답에서 필드 제거해 미지원을 명확화. |

### 1.8 Admin 알림 채널 CRUD

| 항목 | 내용 |
|------|------|
| **위치** | `frontend/src/app/(admin)/admin/notifications/page.tsx` |
| **문제** | 상태/테스트 위주. 채널 CRUD 미구현. |
| **영향도** | Low–Medium |
| **수정방법** | CRUD API+UI 또는 메뉴 라벨을 “상태/테스트”로 축소. |

### 1.9 Docker / Compose 배포 산출물

| 항목 | 내용 |
|------|------|
| **위치** | 레포 루트 — `Dockerfile` / `docker-compose*.yml` **0건** |
| **문제** | 설치 매뉴얼과 컨테이너 배포 경로가 코드베이스에 없음. |
| **영향도** | Medium |
| **수정방법** | 공식 배포 방식(Windows 서비스/venv)을 문서에 고정하거나 Dockerfile·compose 추가. |

### 1.10 Next.js Edge Middleware 가드

| 항목 | 내용 |
|------|------|
| **위치** | `frontend/` — `middleware.ts` 없음. `AuthGuard` 클라이언트만 |
| **문제** | `/admin/*`, `/user/*` 서버측 리다이렉트 가드 부재. |
| **영향도** | High (보안·UX) |
| **수정방법** | Next.js middleware에서 쿠키/세션 검사 후 미인증 deep-link 차단. |

### 1.11 OpenClaw

| 항목 | 내용 |
|------|------|
| **위치** | `src/stock_platform` OpenClaw 0건 (STEP57-1 범위 제외) |
| **문제** | 과거 감사의 “미구현”이나 **의도적 제외**. |
| **영향도** | Low (범위 외) |
| **수정방법** | 추가 조치 불필요. 문서에 “제외” 유지. |

---

## 2. TODO / FIXME

### 2.1 Frontend 제품 TODO (활성)

| 항목 | 내용 |
|------|------|
| **위치** | `user/trading/page.tsx`, `user/strategies/page.tsx`, `user/auto-trading/page.tsx`, `admin/operations` 관련 tiles |
| **문제** | 실제 미연결 기능을 TODO 주석·UnimplementedNotice로 표시. Backend `src/`에는 TODO/FIXME가 **거의 없음**. |
| **영향도** | Medium |
| **수정방법** | 이슈 트래커로 이관 후 코드 TODO 축소. 릴리즈 전 “미구현 CTA” 숨김 정책 수립. |

### 2.2 운영 타일 Restore TODO

| 항목 | 내용 |
|------|------|
| **위치** | `frontend/src/features/admin/operations/operationCenterTiles.ts` (~121) `TODO: POST /ops/backup/restore` |
| **문제** | planned 타일이 미완성 API를 암시. |
| **영향도** | Low |
| **수정방법** | planned 필터에서 제외하거나 CLI 문서 링크만 유지. |

---

## 3. NotImplemented

### 3.1 KiwoomAdapter.get_order

| 항목 | 내용 |
|------|------|
| **위치** | `src/stock_platform/broker/kiwoom/adapter.py` (~156–162) |
| **문제** | `get_order`가 `NotImplementedError("Use KiwoomOrderInquiryClient")`를 raise. |
| **영향도** | Medium (호출 시 런타임 실패) |
| **수정방법** | InquiryClient로 위임 구현하거나 인터페이스에서 제거·호출부 전면 교체. |

### 3.2 ABC 계약상의 NotImplementedError

| 항목 | 내용 |
|------|------|
| **위치** | `broker/adapter.py`, `broker/base.py`, `risk_engine/rules.py`, `notification/base.py` |
| **문제** | 추상 베이스의 정상 패턴. 구체 구현체는 별도 존재. |
| **영향도** | Low (정보) |
| **수정방법** | 조치 불필요. 프로덕션 어댑터 목록만 문서화. |

---

## 4. Pass 처리

### 4.1 예외 삼킴 (`except: pass` / bare pass)

| 항목 | 내용 |
|------|------|
| **위치** | `auth/deps.py` (~188, ~257), `api/exception_handlers.py` (~183), `broker/kiwoom/ws_client.py`, `realtime/*`, `order/outbox_scheduler.py` cleanup 경로, `operation/monitoring_snapshot.py` 등 |
| **문제** | 다수가 취소/정리 경로의 의도적 무시. 일부는 JWT/키 폴백 전 `pass`로 디버깅이 어려움. |
| **영향도** | Low–Medium |
| **수정방법** | shutdown-only는 유지하되, 인증·매핑 실패는 `logger.debug/exception`으로 남김. |

### 4.2 빈 예외 클래스의 `pass`

| 항목 | 내용 |
|------|------|
| **위치** | `broker/exceptions.py`, `news/user_news_service.py` 도메인 예외, `auth/preference_service.py` 등 |
| **문제** | 마커 예외 클래스 — 정상 패턴. |
| **영향도** | Low |
| **수정방법** | 불필요. |

---

## 5. Mock 코드

### 5.1 Kiwoom Mock 기본값

| 항목 | 내용 |
|------|------|
| **위치** | `src/stock_platform/common/settings.py` (`kiwoom_use_mock: bool = True`, mock API/WS URL) |
| **문제** | 기본이 mock. Live와 교차 검증(`kiwoom_live_order_enabled and kiwoom_use_mock`)은 있음. |
| **영향도** | Medium (운영 설정 실 시 잘못된 환경) |
| **수정방법** | prod 프로파일에서 mock 기본 False + 기동 체크리스트에 mock/live 명시. |

### 5.2 테스트용 unittest.mock

| 항목 | 내용 |
|------|------|
| **위치** | `tests/test_step65_*.py` ~ `test_step74_*.py` 등 |
| **문제** | 단위 테스트의 MagicMock — 정상. |
| **영향도** | Low |
| **수정방법** | 프로덕션 경로에 mock 주입이 없는지 CI에서 import 가드 유지. |

### 5.3 Paper / Realtime paper 모드

| 항목 | 내용 |
|------|------|
| **위치** | `realtime/runtime.py` — `RealtimeExecutionMode.PAPER`, `auto_fill=True` |
| **문제** | 의도된 모의 실행. 다만 `account_id=1`과 결합(§6·§15). |
| **영향도** | Medium |
| **수정방법** | 설정/DB에서 계좌·모드 주입. |

---

## 6. 임시 코드

### 6.1 JWT_DEV_AUTO_SECRET 기본 True

| 항목 | 내용 |
|------|------|
| **위치** | `common/settings.py` (`jwt_dev_auto_secret` 기본 True, local/dev 임시 Secret 생성) |
| **문제** | APP_ENV 오설정 시 개발 가정에 의존할 여지. prod는 JWT_SECRET 필수. |
| **영향도** | Medium |
| **수정방법** | 기본 False(opt-in), 기동 로그에 secret 출처 명시. |

### 6.2 하드코딩 ENV / Backup 경로

| 항목 | 내용 |
|------|------|
| **위치** | `common/settings.py` `ENV_FILE = E:\StockTrading\secrets\...` · `ops_db.py` `E:\StockTrading\backups` |
| **문제** | 머신 고정 경로. 다른 환경에서 잘못된 secrets 로드·문서 혼선. |
| **영향도** | Medium |
| **수정방법** | 환경변수/상대경로·프로젝트 `.env` 우선. 절대경로는 예시로만. |

### 6.3 Deprecated step32 호환 API (임시 성격의 장기 잔존)

| 항목 | 내용 |
|------|------|
| **위치** | `api/v1/step32_router.py` — `router.py`에 **여전히 마운트** (~281) |
| **문제** | DEPRECATED 표기에도 무인증 mutate/read 가능(§10·§15·§20). |
| **영향도** | Critical |
| **수정방법** | 마운트 제거 또는 `/dev`+`require_admin`+feature flag. |

---

## 7. 테스트용 코드

### 7.1 프로덕션에 혼입된 테스트 흔적

| 항목 | 내용 |
|------|------|
| **위치** | `tests/` (정상), `frontend/**/*.test.ts` (정상) |
| **문제** | 소스에 `__test__` 전용 엔드포인트는 주요 발견 없음. `POST /notification/test`는 **인증+rate limit** 적용됨(이전 Critical는 해소). |
| **영향도** | Low |
| **수정방법** | 현행 유지. Admin UI에서만 노출 권장. |

### 7.2 menu flatten “테스트용” 유틸

| 항목 | 내용 |
|------|------|
| **위치** | `frontend/src/config/menu.tsx` (~360 주석) |
| **문제** | 가드·테스트용 flatten — 프로덕션에서도 사용 가능. |
| **영향도** | Low |
| **수정방법** | 테스트 전용으로 분리하거나 주석만 정리. |

---

## 8. Dead Code

### 8.1 미등록 indicator_router

| 항목 | 내용 |
|------|------|
| **위치** | `src/stock_platform/api/v1/indicator_router.py` (STEP56 등록 해제, `router.py`에 없음) |
| **문제** | “gone” 응답 tombstone 파일만 잔존. |
| **영향도** | Low |
| **수정방법** | 다음 릴리스에서 파일 삭제. |

### 8.2 Frontend 미사용 컴포넌트

| 항목 | 내용 |
|------|------|
| **위치** | `ComingSoon.tsx`, `SystemStatusPlaceholder.tsx`, `FoundationChecklist.tsx`, `DashboardWelcome.tsx` (사용처 import 0) |
| **문제** | 데드 UI. |
| **영향도** | Low |
| **수정방법** | 삭제 또는 대시보드에 재연결. |

### 8.3 이중 패키지 스택

| 항목 | 내용 |
|------|------|
| **위치** | `broker/` vs `brokers/`, `market/`(스키마) vs `markets/`(패키지) |
| **문제** | 둘 다 참조됨. 인지 부하·중복 유지비. |
| **영향도** | Medium |
| **수정방법** | 통합 로드맵(신규는 `broker`/`markets`로 단일화). |

---

## 9. 사용되지 않는 파일

| 항목 | 내용 |
|------|------|
| **위치** | `indicator_router.py` · FE dead components(§8) · `docs/migration-overlays/*` (문서/오버레이) · 루트 `stock-platform.zip`(git 미추적 zip) |
| **문제** | 런타임 미사용 또는 산출물 잔존. |
| **영향도** | Low |
| **수정방법** | zip은 `.gitignore`/삭제. overlay는 archive 유지. dead 파일 삭제. |

---

## 10. 사용되지 않는 / 위험한 API

### 10.1 무인증 라우터 파일 (스캔 결과 45개)

인증 마커(`require_admin` / `require_permission` / `get_current_user` 등) **없는** `api/v1` 파일:

`ai_analysis`, `ai_candidates`, `ai_orchestration`, `backtest_*`, `backtests`, `candidate_*`, `candidates`, `daily_reports`, `dart`, `deployment_performance_monitor`, `docs_cms`, `guarded_pipeline`, `health`*, `indicators`, `indicator_router`(미등록), `market_data_router`, `market_quality`, `news`, `pipelines`, `portfolio_*backtests`, `position_candidates`, `prices`, `realtime_ai`, `realtime_quotes`, `realtime_risk_*`, `risk`, `risk_dashboard`, `step32_router`, `strategy_leaderboard`, `strategy_operations_dashboard`, `strategy_performance*`, `strategy_ranking`, `strategy_runtime_switch`, `strategy_selector`, `sync`, `trading_calendar`, `upbit`, `version`*, `walk_forward*`

\* `health`/`version`은 공개 의도가 타당.

| 항목 | 내용 |
|------|------|
| **위치** | 위 목록 + 특히 mutate: `step32_router`, `sync`, `pipelines`, `guarded_pipeline`, `strategy_runtime_switch`, `realtime_quotes` start, `upbit`/`news`/`dart`/`backtest` POST |
| **문제** | 네트워크 도달 시 DB 쓰기·파이프라인·전략 전환·외부 API 남용 가능. |
| **영향도** | **Critical** (mutate) / **High** (CPU·비용 DoS) |
| **수정방법** | 라우터 단위 `dependencies=[Depends(require_admin)]` 또는 권한 세분화. step32는 제거. |

### 10.2 이전 Critical의 해소 (참고)

| API | 현재 |
|-----|------|
| `order-execution` | `trading:write` + ownership |
| `notification/test` | `trading:write` + rate limit |
| User STEP65–73 APIs | JWT + ownership |

### 10.3 Frontend 고아 API 클라이언트

| 항목 | 내용 |
|------|------|
| **위치** | `frontend/src/features/user/api/userApi.ts` — export 대비 미사용 약 24개 (예: `getHealth`, `syncNews`, `summarizeNews`, `getRealtimeQuotesStatus` 등) |
| **문제** | User 번들에 Admin/legacy 표면 혼재. |
| **영향도** | Low–Medium |
| **수정방법** | User 전용 분리, 미사용 export 제거. |

---

## 11. 사용되지 않는 Service

### 11.1 PositionExitMonitor (이전 Dead → 현재 연결)

| 항목 | 내용 |
|------|------|
| **위치** | `api/lifecycle.py` — `position_exit_monitor_scheduler.start()` (~244) |
| **문제** | 구감사의 “미연결”은 **해소**. 다만 exit 경로 `skip_risk_checks` 설계는 재검토 여지. |
| **영향도** | Medium (리스크 설계) |
| **수정방법** | Kill Switch 적용 여부 문서화·테스트. |

### 11.2 OrderDispatcher / 레거시 Risk 게이트

| 항목 | 내용 |
|------|------|
| **위치** | `broker/dispatcher.py`, `risk/legacy_gate.py` (step32와 연동) |
| **문제** | 본선은 `order/execution_service`·`risk_engine`. 레거시는 혼란 유발. |
| **영향도** | Medium |
| **수정방법** | step32 제거와 함께 legacy gate 폐기. |

### 11.3 AutomaticScheduler vs lifecycle 스케줄러

| 항목 | 내용 |
|------|------|
| **위치** | `scheduler/automatic.py` vs `lifecycle._start_schedulers` |
| **문제** | API lifespan과 AutomaticScheduler 역할 분리. 이중 기동/미기동 혼동 가능. |
| **영향도** | Medium |
| **수정방법** | “API 내장 vs 별도 프로세스” 운영 문서로 단일 경로 고정. |

---

## 12. 중복 코드

### 12.1 Backend 이중 스택

| 항목 | 내용 |
|------|------|
| **위치** | `broker`/`brokers`, 수집기 sync 경로 다수 |
| **문제** | 동일 도메인 이중 구현·import. |
| **영향도** | Medium |
| **수정방법** | 패키지 통합 계획. |

### 12.2 Frontend 셸/알림 컴포넌트 중복

| 항목 | 내용 |
|------|------|
| **위치** | `UnimplementedNotice` vs `UnimplementedApiPanel` · `AdminPageShell` vs `UserPageShell` · `JsonPanel` vs `AdminJsonCard` · barrel `shared/components` vs `components/common` |
| **문제** | UX/스타일 드리프트. |
| **영향도** | Low |
| **수정방법** | 공통 컴포넌트로 통합. |

### 12.3 User 백테스트 UX 분산

| 항목 | 내용 |
|------|------|
| **위치** | `user/backtests/page.tsx` vs `user/strategies/page.tsx` 내 백테스트 섹션 |
| **문제** | 기능 중복·불일치. |
| **영향도** | Low |
| **수정방법** | 단일 진입점으로 통합. |

---

## 13. 순환참조

| 항목 | 내용 |
|------|------|
| **위치** | 패키지 레벨: `broker`↔`order`, `notification`↔`risk_engine`, `operation`↔`realtime`, `realtime`↔`risk_engine`, `ai`↔`disclosure`/`news` |
| **문제** | 현재는 `lifecycle` 등에서 deferred import로 완화. 신규 top-level import 추가 시 ImportError 위험. |
| **영향도** | Medium |
| **수정방법** | 공유 DTO 추출, 런타임 lazy import 유지, `broker→order` 모듈 로드 시점 의존 금지. |

---

## 14. Import 오류 가능성

### 14.1 step32 PaperAccountService 생성자 불일치

| 항목 | 내용 |
|------|------|
| **위치** | `api/v1/step32_router.py` (~81) `PaperAccountService(session)` vs `account_service.py` `__init__(repository: PaperAccountRepository)` |
| **문제** | Session을 repository로 전달 → 첫 `apply_fill`에서 AttributeError. (타입 검사 미통과 가능) |
| **영향도** | **Critical** (해당 API 호출 시) |
| **수정방법** | 엔드포인트 제거가 최선. 유지 시 `PaperAccountService(PaperAccountRepository(session))`. |

### 14.2 이중 예외 타입 import

| 항목 | 내용 |
|------|------|
| **위치** | `api/exception_handlers.py` — `broker.exceptions.BrokerError`와 `brokers.kiwoom.exceptions.KiwoomError` 병존 |
| **문제** | 핸들러 누락 시 500으로만 노출될 수 있음. |
| **영향도** | Low–Medium |
| **수정방법** | 예외 계층 통일. |

---

## 15. Runtime 오류 가능성

### 15.1 account_id=1 하드코딩

| 항목 | 내용 |
|------|------|
| **위치** | BE: `realtime/runtime.py` (~57), `realtime/execution_models.py` 기본값, Admin dashboard/operations 서비스 일부 · FE: `admin/dashboard`, `admin/portfolio`, `admin/orders` initialValues, `queryKeys.ts` default |
| **문제** | 계좌 1 부재·타 계좌 운영 시 잘못된 KPI/주문/실시간 체결. User 쪽은 `useMyPaperAccountId`로 상대적 안전. |
| **영향도** | **High** |
| **수정방법** | 기본값 제거. 설정/UI에서 명시적 계좌 선택 필수. |

### 15.2 get_db_session 비커밋 + 호출부 누락

| 항목 | 내용 |
|------|------|
| **위치** | `database/session.py` — yield 후 `close`만, auto-commit 없음 |
| **문제** | mutate 경로가 `.commit()`을 빠뜨리면 **조용히 미반영**. (관례 의존) |
| **영향도** | High |
| **수정방법** | 커밋 정책 문서화 + 미들웨어 성공 시 commit 또는 서비스 레이어 강제 감사. |

### 15.3 FE non-null 단언

| 항목 | 내용 |
|------|------|
| **위치** | 예: `user/portfolio/page.tsx` `executionsQuery.error!` 등 |
| **문제** | 가드 회귀 시 런타임 crash. |
| **영향도** | Low–Medium |
| **수정방법** | optional chaining / narrowing. |

---

## 16. Exception 누락

| 항목 | 내용 |
|------|------|
| **위치** | 무인증 POST 핸들러 다수 — `ValueError`/`LookupError`만 HTTP 변환, 그 외 500 · `lifecycle._run_optional`은 기동 실패 삼킴 |
| **문제** | 운영 가시성 저하, 감사 로그 공백. |
| **영향도** | Medium |
| **수정방법** | DomainError 통일, optional 실패를 `/monitoring`에 노출. |

---

## 17. Transaction 누락

| 항목 | 내용 |
|------|------|
| **위치** | `get_db_session` (전역) · 서비스별 수동 `commit` (예: `account_service.apply_fill` → `repository.commit`) |
| **문제** | 멀티 리포지토리 작업에서 부분 커밋·롤백 불일치 가능. Outbox/execution 경로는 상대적으로 양호. |
| **영향도** | High |
| **수정방법** | Unit-of-Work 패턴 또는 `session.begin()` 컨텍스트로 단일 트랜잭션 강제. |

---

## 18. Rollback 문제

| 항목 | 내용 |
|------|------|
| **위치** | 세션 dependency가 예외 시 **rollback 명시 없음** (close만) · 일부 서비스는 성공 경로만 commit |
| **문제** | dirty session이 다른 요청에 재사용되지 않도록 close로 완화되나, 명시적 rollback 부재로 디버깅·부분 flush 혼란 가능. |
| **영향도** | Medium |
| **수정방법** | `finally`에서 `session.rollback()` 후 `close`, 또는 context manager 표준화. |

---

## 19. 성능 문제

### 19.1 무인증 고비용 POST

| 항목 | 내용 |
|------|------|
| **위치** | backtest / walk-forward / AI / indicator / upbit·dart sync |
| **문제** | CPU·DB·외부 API DoS. |
| **영향도** | **High** |
| **수정방법** | Auth + `enforce_rate_limit` + 잡 큐화. |

### 19.2 대량 limit 기본값

| 항목 | 내용 |
|------|------|
| **위치** | `market_data_router.py` limit 기본/상한 5000급 · dart `le=5000` |
| **문제** | 대응답·DB 부하. |
| **영향도** | Medium |
| **수정방법** | 기본 100–200, 페이지네이션, 인증. |

### 19.3 Sync Session in Async

| 항목 | 내용 |
|------|------|
| **위치** | FastAPI async 라우트 + SQLAlchemy sync Session |
| **문제** | 이벤트 루프 블로킹. |
| **영향도** | Medium |
| **수정방법** | 무거운 작업은 `to_thread`/잡 워커. |

### 19.4 Rate limit 적용 범위

| 항목 | 내용 |
|------|------|
| **위치** | `common/rate_limit.py` — auth, notification test, telegram, profile, AI 일부에만 적용 |
| **문제** | 앱 전역 rate limit 아님. |
| **영향도** | Medium |
| **수정방법** | 고비용·공개 엔드포인트에 일괄 적용. |

---

## 20. Security 문제

### 20.1 무인증 mutate API (최우선)

| 항목 | 내용 |
|------|------|
| **위치** | `POST /api/v1/positions/executions` (step32), `POST /api/v1/sync/kiwoom/daily`, `POST /api/v1/pipelines/daily-strategy`, `POST /api/v1/guarded-pipelines/daily-strategy`, `POST /api/v1/strategy-runtime-switch` 등 |
| **문제** | 인증 없이 포지션/파이프라인/전략 런타임 변경 가능. |
| **영향도** | **Critical** |
| **수정방법** | 즉시 `require_admin` 또는 라우터 제거. 네트워크 ACL만으로 의존 금지. |

### 20.2 FE 토큰 localStorage / sessionStorage

| 항목 | 내용 |
|------|------|
| **위치** | `frontend/src/lib/storage/tokenStorage.ts`, `authStore.ts` |
| **문제** | XSS 시 Access/Refresh·역할 JSON 탈취·변조 UI. 서버 권한 강제에 의존. |
| **영향도** | High |
| **수정방법** | httpOnly Secure cookie + BFF, hydrate 시 `/auth/me` 재검증. |

### 20.3 Middleware 부재

| 항목 | 내용 |
|------|------|
| **위치** | Next.js `middleware.ts` 없음 |
| **문제** | 보호 라우트 순간 노출·봇 접근. |
| **영향도** | High |
| **수정방법** | Edge middleware 가드. |

### 20.4 401 portal 분기

| 항목 | 내용 |
|------|------|
| **위치** | `frontend/src/lib/api/interceptors.ts` — 401 시 `?portal=admin` 고정 경향 |
| **문제** | User 세션 만료 후 Admin 로그인 UX로 유도. |
| **영향도** | Medium |
| **수정방법** | pathname 기준 `portal=user|admin`. |

### 20.5 CORS / CSRF

| 항목 | 내용 |
|------|------|
| **위치** | `api/main.py` CORSMiddleware · CSRF 미구현 |
| **문제** | CORS는 설정 기반(개선됨). CSRF는 Bearer 전제라 쿠키 전환 시 필요. |
| **영향도** | Medium (현재 Bearer) / High (쿠키 전환 시) |
| **수정방법** | 쿠키 세션 도입 시 CSRF 토큰. CORS allowlist 운영값 점검. |

### 20.6 Live 주문 게이트 (양호·유지)

| 항목 | 내용 |
|------|------|
| **위치** | `kiwoom_live_order_enabled` + mock 교차 검증, `broker_orders` `require_admin` |
| **문제** | 게이트는 존재. 설정 실수·무인증 주변 API가 우회 경로가 될 수 있음. |
| **영향도** | — (통제됨, 주변 Critical과 연계) |
| **수정방법** | Live 전환 체크리스트 + 무인증 API 제거를 병행. |

### 20.7 ADMIN_API_KEY / DEV_OPEN

| 항목 | 내용 |
|------|------|
| **위치** | `settings.ensure_admin_api_key`, `auth/deps.require_admin` |
| **문제** | 구감사의 DEV_OPEN은 **제거됨**. prod는 키 필수. |
| **영향도** | Low (해소) — 설정 누락 시 기동 실패로 fail-closed |
| **수정방법** | 현행 유지. |

---

## 우선순위 백로그 (조치 순서 제안)

1. **P0 / Critical** — `step32_router` 제거 또는 인증 · `sync`/`pipelines`/`guarded_pipeline`/`strategy_runtime_switch`에 `require_admin` · `PaperAccountService(session)` 버그 경로 차단  
2. **P1 / High** — 나머지 무인증 mutate·고비용 POST 인증 · `account_id=1` 제거 · FE middleware + 토큰 저장 개선  
3. **P2 / Medium** — Backup/Restore·로그 테일 정책 확정 · User 미구현 CTA 정리 · 트랜잭션/rollback 표준화 · 이중 패키지 통합 계획  
4. **P3 / Low** — dead 파일/컴포넌트·고아 `userApi`·ComingSoon 삭제 · TODO 이슈화  

---

## 이전 감사 대비 델타 (요약)

| 구감사(2026-07-19) | 현재(2026-07-21) |
|--------------------|------------------|
| order-execution 무인증 | ✅ 인증+ownership |
| ADMIN_API_KEY → DEV_OPEN | ✅ 제거, prod fail-closed |
| User account_id=1 / 소유권 없음 | ✅ User API 대부분 해소 (Admin/Realtime 잔존) |
| Watchlist/Prefs/Inbox/공시AI | ✅ STEP67–73 구현 |
| ExitMonitor 미연결 | ✅ lifecycle 연결 |
| Telegram 수신 없음 | ✅ telegram_ops 존재 |
| `/admin/logs`, `/admin/data` 404 | ✅ 페이지/리다이렉트 존재 (메뉴 404 없음) |
| 무인증 notification/test | ✅ 권한+rate limit |
| step32·pipelines·sync 무인증 | ❌ **잔존 Critical** |
| Docker 없음 | ❌ 잔존 |
| 웹 Backup 실행 없음 | ❌ 잔존 |
| FE middleware 없음 | ❌ 잔존 |

---

## 감사 결론

**출시(단일 운영자 · VPN · Paper 중심)** 가정에서는 User STEP65–75와 본선 주문 경로가 실질적으로 사용 가능하다.  
**다중 사용자 · 인터넷 노출 · Live 자동매매** 가정에서는 무인증 운영 API 장막과 `account_id=1`·FE 토큰 저장이 **출시 차단 수준**이다.

본 문서는 감사 전용이다. **코드 변경은 포함하지 않았다.**
