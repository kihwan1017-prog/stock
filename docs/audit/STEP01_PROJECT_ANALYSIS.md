# STEP 01 — 프로젝트 전체 현황 분석

> 작성일: 2026-07-22  
> 범위: 코드·문서·DB 스키마·테스트 수집만 (대규모 코드 수정 없음)  
> 환경: Python 3.12.10 · Node v24.18.0 · PostgreSQL 17.10 (Windows)  
> 안전 상태 확인: Live 주문 게이트는 기본 `false` / mock 기본 `true`

---

## 1. 현재 프로젝트 구조

### 1.1 저장소 개요

| 영역 | 경로 | 규모(점검 시점) |
|------|------|-----------------|
| Backend | `src/stock_platform/` | ≈569 `.py` |
| API v1 | `src/stock_platform/api/v1/` | 100 모듈 |
| Frontend | `frontend/` | Next.js 16 · React 19 · Ant Design 6 |
| Tests | `tests/` | `test_*.py` 164파일 · collect **501** cases |
| FE unit | `frontend/src/**/*.test.ts(x)` | 26 |
| Alembic | `database/alembic/versions/` | 64 revisions |
| Ops | `ops/` | NSSM·backup/restore·start/stop |
| Docs | `docs/` | domain folders + 루트에 구형 감사 MD 다수 |

### 1.2 백엔드 패키지 맵

| 패키지 | 역할 |
|--------|------|
| `api` | FastAPI 앱, lifecycle, ≈97 라우터 등록 |
| `auth` | JWT·Refresh·RBAC·계좌 소유권·프로필 |
| `broker` | **주문·계좌·WS 본선** (Kiwoom/Upbit/Paper) |
| `brokers` | **시세 REST** (Kiwoom/Upbit quotation) |
| `order` | 주문 생성·상태머신·Outbox·execution·guards |
| `trading` | Paper 계좌/주문/체결·시뮬레이션 |
| `risk` | 포지션 사이징·exit·정책 |
| `risk_engine` | Kill Switch·일손실·order guard·limits |
| `realtime` | 실시간 시세/전략/실행 러너 |
| `scheduler` | JobRegistry + AutomaticScheduler(cron) |
| `markets` / `collectors` / `indicators` | 시세 저장·수집·지표 |
| `screener` / `ai` / `news` / `disclosure` | 후보·LLM·뉴스·공시 |
| `strategy_deployment` / `performance` / `backtest` | 배포·성과·백테스트 |
| `notification` / `operation` | 알림·모니터링·감사·설정 |
| `strategy` / `portfolio` | **스텁 패키지**(로직 이관 완료) |

### 1.3 프런트엔드 구조

- Route groups: `(admin)` / `(user)` / `(auth)`
- 도메인 로직: `features/admin|user|auth`
- 인증: `middleware.ts` + `AuthGuard` + sessionStorage↔쿠키 동기화
- API: axios + React Query (`apiClient` → `/api/v1`)
- E2E: Playwright 스모크 스캐폴드 (`frontend/e2e`, CI 미연결)

### 1.4 PostgreSQL 스키마 (실DB 조회)

| Schema | Tables |
|--------|--------|
| trading | 25 |
| operation | 18 |
| auth | 8 |
| market | 7 |
| ai | 6 |
| news | 5 |
| disclosure | 4 |
| strategy | 4 |
| notification | 3 |
| backtest | 3 |

합계 ≈ **83 tables** (시스템 카탈로그 제외). Alembic head 계열 마이그레이션이 적용된 운영/개발 DB로 판단.

### 1.5 이중 구조 (의도적 vs 정리 대상)

| 쌍 | 판정 | 비고 |
|----|------|------|
| `broker` / `brokers` | **의도적 역할 분리**이나 이름 혼동 | 주문 vs 시세. STEP6에서 통합 설계 필요 |
| `risk` / `risk_engine` | **의도적 분리** | sizing vs kill/guard |
| 루트 `alembic/` vs `database/alembic/` | 정리 후보 | 실제 버전은 `database/alembic/versions` |
| 루트 `*.md` 감사본 vs `docs/` | 문서 부채 | STEP19 정리 대상 |

---

## 2. 주요 실행 흐름

### 2.1 애플리케이션 기동

```text
api/main.py
  → Settings 로드 (STOCK_PLATFORM_ENV_FILE → cwd → E:\StockTrading\secrets\…)
  → lifecycle: DB/스케줄러/outbox/킬스위치 관련 런타임 기동
  → router: /api/v1/* 마운트
```

Lifecycle에서 기동되는 대표 스케줄러:

- `daily_loss_monitor_scheduler`
- `position_exit_monitor_scheduler`
- `telegram_ops_scheduler`
- strategy reload / approval / deployment pipeline / performance monitor
- `order_outbox_scheduler`

참고: `scheduler/automatic.py`(장후 cron)는 API lifecycle에 **미연결**. 별도 `scripts/run_scheduler.py` 경로.

### 2.2 인증·권한

```text
Login → AuthService → JWT access + refresh
Refresh → jti 조회 / reuse 시 전세션 revoke / 회전
Deps → DB에서 user·RBAC 재검증 (JWT role claim만 신뢰하지 않음)
Ownership → paper / trading / broker account assert
```

`require_admin`은 DB `admin` 역할 또는 `ops:execute` 권한, 또는 `X-Admin-API-Key`를 허용.

### 2.3 주문 (본선)

```text
API 주문
 → 인증·권한·계좌 소유권
 → Risk sizing (risk) + KillSwitch/OrderGuard (risk_engine)
 → TradingOrder 생성
 → Outbox enqueue
 → OutboxWorker → BrokerAdapterFactory
 → Paper / Kiwoom / Upbit adapter.submit_order
 → ACCEPTED
 → Fill: Paper 시뮬 / Kiwoom WS sync (경로 분리)
```

### 2.4 Live 주문 안전 게이트

AND 조건:

1. `GLOBAL_LIVE_ORDER_ENABLED`
2. `KIWOOM_LIVE_ORDER_ENABLED` 또는 `UPBIT_LIVE_ORDER_ENABLED`
3. `LiveTradingTransitionGuard` (DB 승인)
4. Adapter mock/live 상호 배타 검증

기본값: Live **off**, mock **on**.

### 2.5 시장·AI 파이프라인 (개념)

```text
Collectors(brokers.*) → market tables
 → indicators → screener candidates
 → news/DART → Ollama AI
 → strategy_deployment / position planning
 → (선택) 주문 경로
```

---

## 3. 실제 구현 기능

### 구현됨 (코드·라우터·테스트 근거)

- 통합 로그인 / Refresh / 잠금 / 온보딩·비밀번호 변경 화면
- RBAC + Admin JWT DB 재검증
- Paper 계좌 CRUD(soft delete 포함) · Paper 주문/체결
- Order Outbox + Worker/Dispatcher
- Kiwoom REST 주문 어댑터 + WS 실행 동기화 골격
- Upbit private/account/order 어댑터 + mock
- Kill Switch 영속화 + 주문 가드 연동
- Daily loss monitor / position exit monitor
- 시세 수집(키움·업비트), 지표, 스크리너, 백테스트 다수 API
- 뉴스·공시·사용자 AI 요약/추천
- Telegram/Slack/Discord 송신 골격 + Telegram Ops(폴링/웹훅)
- Ops backup dump/status, NSSM 스크립트, CI(backend+frontend)
- Docker Compose / Dockerfile (문서상 Windows 서비스 중심과 병존)

### 부분 구현

- Live Kiwoom/Upbit: 가드·어댑터는 있으나 **실계좌 운영 검증 전**
- AutomaticScheduler(cron) vs Lifecycle 스케줄러 **이중화**
- FE 일부 화면: UI는 있으나 Backend API 공백 → `UnimplementedNotice`
- Playwright E2E: 스모크만, CI 게이트 미포함
- Telegram: 토큰/chat_id는 설정 가능하나 **`TELEGRAM_ENABLED=false` 기본**

---

## 4. 미구현·명시적 공백

### Backend

| 항목 | 근거 |
|------|------|
| Kiwoom `get_order()` | `broker/kiwoom/adapter.py` → `NotImplementedError` (별도 InquiryClient 안내) |
| `strategy` / `portfolio` 패키지 | 스텁 (`strategy_deployment` 등으로 이관) |
| step32 무인증 paper fill | **의도적 언마운트**(tombstone) |
| Broker별 공통 인터페이스 완전 통일 | STEP6 대상 |
| 외부 API 오류 코드 세분화 | 카탈로그에 `KIWOOM_/UPBIT_/DART_/OLLAMA_` 미분리 (STEP5) |

### Frontend (명시 TODO)

| 화면 | 공백 |
|------|------|
| `/user/auto-trading` | schedules CRUD, kill-switch(user) |
| `/user/strategies` | deployment DELETE, portfolio-optimize |
| `/user/trading` | realtime SSE/WS 구독 UI |
| `/admin/operations` | backup restore, logs tail |
| `/admin/notifications` | 채널 CRUD API |

---

## 5. 키워드 검색 결과

검색어: `TODO` `FIXME` `HACK` `XXX` `pass` `NotImplementedError` `stub` `mock` `temporary` `deprecated` `_repository._session`

| 패턴 | 결과 요약 |
|------|-----------|
| `TODO/FIXME/HACK/XXX` (src `*.py`) | **매치 없음** (백엔드 주석 TODO는 거의 정리됨) |
| FE TODO | auto-trading / strategies / trading / operations 등 **명시적 미구현 패널** |
| `NotImplementedError` | ABC/base 정상 + Kiwoom `get_order` 실질 미구현 1건 |
| `_repository._session` | `auth/service.py`(4), `auth/user_admin_service.py`(3) — **STEP4 우선** |
| `pass` | Exception 빈 body, except swallow, ABC 등 — 대부분 정상. swallow 다수는 realtime/ws |
| `deprecated` | `step32_router`, `indicator_router`, `risk/legacy_gate` |
| `stub` | `strategy/__init__.py` 이관 안내 |

---

## 6. 중복 코드 · Dead Code 후보

### 중복/이중화

1. **`broker` vs `brokers`** — 시세 클라이언트와 주문 어댑터 분리. Upbit 예외/rate limiter 교차 import 존재.
2. **Scheduler 이중 경로** — JobRegistry/API jobs vs AutomaticScheduler cron vs lifecycle 내장 스케줄러.
3. **루트 문서 부채** — `README_AUDIT_*.md`, `PROJECT_FINAL_AUDIT.md`, `FINAL_*` 등 루트 50+ MD와 `docs/` 병존.
4. **루트 `alembic/`** — 소량 파일; 본선은 `database/alembic`.
5. **env 예시 다중** — `.env.example--`, `stock-platform.env.example`, `requirements_step*.txt`.

### Dead / 저사용 후보

- `api/v1/step32_router.py` (미마운트 tombstone — 유지 권장)
- `ComingSoon.tsx` (app에서 import 흔적 약함)
- `strategy/`, `portfolio/` 빈 패키지
- `openclaw-workspace-state.json`, `.coverage` (STEP19)
- `PROJECT_STATUS.md` 인코딩 깨짐 표기

---

## 7. 보안 위험

| 등급 | 이슈 | 상태 |
|------|------|------|
| Critical | 과거 무인증 mutate / step32 | README_ISSUES상 **완화·해결**. STEP17에서 전수 재검증 필요 |
| High | `_repository._session` 캡슐화 우회 | Auth 경로 유지보수·테스트 Fake 계약 위험 |
| High | Telegram 웹훅 secret / enabled 운영 설정 | 토큰 존재해도 `TELEGRAM_ENABLED=false`면 알람 미발송 |
| Medium | Rate limit 편중 잔여 | 완화됨, 전 API 균등 여부 재확인 |
| Medium | Swagger/Health 정보 노출 범위 | STEP17 |
| Medium | Windows 경로 `E:\StockTrading\secrets\...` 기본 탐색 | 이식성·실수 위험 (완화: `STOCK_PLATFORM_ENV_FILE`) |
| Low | `JWT_DEV_AUTO_SECRET` local 자동생성 | prod에서는 필수 검증 있음 — 테스트 환경과 혼동 주의 |
| Info | error_catalog에 브로커/외부 API 세분화 부족 | STEP5 |

긍정 요소: Admin deps의 **DB RBAC 재검증**, Live 삼중 게이트, refresh reuse revoke, soft-delete paper account.

---

## 8. 운영 위험

| 등급 | 이슈 |
|------|------|
| High | AutomaticScheduler가 API 프로세스와 분리 — 장후 잡 누락 가능 |
| High | Outbox ACCEPTED와 Fill 경로 분리 — 재시작/복구 시나리오 STEP7 필수 |
| Medium | 멀티 인스턴스 시 스케줄러 중복 실행 방지 계약 불명확 |
| Medium | Telegram/Slack/Discord 기본 비활성 → 장애 알람 공백 |
| Medium | Backup restore 웹 UI 미구현 (스크립트/ops는 존재) |
| Medium | 루트 감사 문서와 코드 상태 불일치 가능 |
| Low | FE middleware는 쿠키 없으면 soft-pass → AuthGuard 의존 |

Ops 자산: `ops/*.bat|ps1`, NSSM, `scripts/run_scheduler.py`, CI alembic+pytest+frontend.

---

## 9. 테스트 위험

| 항목 | 현황 |
|------|------|
| Collect | **501** tests (marker 기본: `not external and not live`) |
| compileall `src` | **성공** (exit 0) |
| FE unit | 26 files |
| Coverage gate (CI) | `--cov-fail-under=25` — **낮음** |
| PG integration | `tests/test_postgres_integration.py` 존재 |
| E2E | Playwright 스모크만, CI 미포함 |
| 위험 | MagicMock 비중 높은 파일 존재(과거 감사), 실Broker 계약 약화 가능 |
| 미실행(본 STEP) | 전체 `pytest -q` / FE build — **STEP2 기준선** |

본 STEP에서는 실패 수정 없이 수집만 수행. 통과/실패 수는 STEP2에서 확정.

---

## 10. 우선순위 (후속 STEP 정렬)

| 우선순위 | 주제 | 대응 STEP |
|----------|------|-----------|
| P0 | 테스트 기준선 확립 | STEP2 |
| P0 | 설정/import-time 부작용 정리 | STEP3 |
| P0 | Auth Repository 계약 (`_session` 제거) | STEP4 |
| P0 | 예외·오류 코드 매핑 | STEP5 |
| P1 | Broker 패키지 통합 설계 | STEP6 |
| P0–P1 | 주문·체결·복구 검증 | STEP7 |
| P0 | Kill Switch / Risk | STEP8 |
| P1 | Scheduler/Runtime 일치 | STEP9 |
| P1 | Kiwoom / Upbit / Paper 상세 | STEP10–12 |
| P1 | Market·AI 파이프라인 | STEP13–14 |
| P1 | FE 빌드·미구현 기능 | STEP15–16 |
| P0 | 보안 전수 감사 | STEP17 |
| P1 | Ops·백업 | STEP18 |
| P2 | 루트 파일/문서 정리 | STEP19 |
| P0 | 통합 테스트·운영 판정 | STEP20–21 |

---

## 11. 후속 단계 계획 (변경 없음 — 명령서 준수)

1. **STEP2** — `pytest -q` + FE typecheck/lint/test/build 기준선 문서화  
2. **STEP3** — Settings·env 이름·import 안전성  
3. **STEP4** — Auth Repository 인터페이스 정렬  
4. **STEP5~8** — 예외 → Broker → 주문 → Risk  
5. **STEP9~14** — Runtime·브로커별·시장·AI  
6. **STEP15~16** — FE  
7. **STEP17~21** — 보안·운영·정리·통합·최종 판정  

각 단계는 사용자 `"다음 단계 진행"` / `"승인"` 후에만 진입.

---

## 12. 검사 명령 기록 (STEP1 실행분)

```powershell
# 구조/수집
python --version          # 3.12.10
node --version            # v24.18.0
python -m compileall -q src   # exit 0
python -m pytest --collect-only -q
# → files≈168, tests=501

# DB (MCP)
# schemas: auth/trading/market/operation/ai/news/disclosure/strategy/notification/backtest
```

코드 대규모 수정: **없음**.  
문서 추가: 본 파일 + `docs/audit/README.md` + `docs/README.md` 링크.

---

## 13. 한 줄 종합

플랫폼은 **Paper + Mock 중심의 통합 자동매매 골격이 넓게 구현**되어 있고, Live는 삼중 게이트로 기본 차단되어 있다. 다만 **Auth Repository 캡슐화 위반, Broker 이중 패키지, Scheduler 이중 경로, FE/알람/복구 UI 공백, 테스트 기준선 미측정**이 남아 있어, 명령서 STEP2부터 순서대로 기준선·계약·안전장치를 고정해야 한다.
