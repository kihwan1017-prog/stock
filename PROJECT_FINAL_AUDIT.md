# PROJECT_FINAL_AUDIT.md

> **감사일:** 2026-07-19  
> **범위:** Backend · Frontend · Database · Scheduler · Broker · Risk · Strategy · AI · Auth · Ops  
> **원칙:** 코드/DB 근거만 사용. **신규 기능 구현·코드 수정 없음.**  
> **상태 범례:** ✅ 완료 · 🟡 일부 · 🔴 미구현 · ⚪ 구현됐으나 미사용(Dead)  
> **UPDATE (STEP57-1):** OpenClaw 연동은 프로젝트 범위에서 제외됨. Telegram·Ollama는 유지.

---

# 1. 프로젝트 요약

Stock Platform은 **FastAPI + PostgreSQL + Next.js(Admin/User)** 기반의 주식 자동매매·운영 플랫폼이다.  
STEP35~51까지 Admin 콘솔·User Web·인증·RBAC·Paper/주문 아웃박스·Kill Switch·일손실·백테스트/WF·Ollama AI·알림 송신·운영센터 허브까지 **제품 골격은 대부분 갖춰져 있다.**

그러나 **출시(릴리즈) 관점**에서는 다음이 핵심 리스크다.

1. **매매·리스크 API 다수가 무인증** (`order-execution` 등)
2. **`ADMIN_API_KEY` 미설정 시 `require_admin` → `DEV_OPEN`**
3. **User Web `account_id = 1` 하드코딩** (멀티유저 격리 불가)
4. **실시간 청산 모니터(`PositionExitMonitor`) 미연결**
5. **~~OpenClaw Backend·Telegram 수신(슬래시) 없음~~** → Telegram 수신은 STEP54로 해소. OpenClaw는 STEP57-1에서 범위 제외
6. **Admin `/admin/logs`, `/admin/data` 페이지 부재(404)**
7. **웹 Backup/Restore 실행 API 없음**
8. **Docker 배포 산출물 없음** (레포 내 Dockerfile/compose 미발견)

**한 줄 평가:** “단일 운영자 · 내부망 · Paper 중심 데모”에는 가깝고, “다중 회원 · Live 자동매매 · 원격 Telegram 운영” 출시에는 **추가 보안·격리·청산·알림 훅이 필수**다.

---

# 2. 구현 완료 기능

| 영역 | 내용 | 근거 |
|------|------|------|
| Auth 핵심 | Signup/Login/Refresh/Logout/Me/Change-password · JWT · Refresh 해시·로테이션 · bcrypt | `api/v1/auth.py`, `auth/service.py`, `auth/jwt_service.py` |
| RBAC 코어 | roles/permissions/users Admin API · 시드 admin/operator/viewer | `api/v1/roles.py`, `users.py`, RBAC migration |
| Paper 계좌·주문 | Paper account/positions/orders · User/Admin UI | `paper_*` tables, User trading/portfolio |
| 주문 실행 경로 | `POST /order-execution/submit` · Outbox · Risk/Kill guard | `order/execution_service.py`, `lifecycle` outbox scheduler |
| Kill Switch | activate/deactivate · DB 영속 · 일손실 연동 | `api/v1/kill_switch.py`, `daily_loss_monitor` |
| Daily Loss | 모니터·스케줄러 lifecycle 기동 | `lifecycle._start_schedulers` |
| Backtest / Grid / WF | 엔진·API·Admin/User 일부 UI | `backtest/*`, walk-forward routers |
| Strategy deploy/runtime | deployment · ranking · pipeline · Admin/User 전략 화면 | strategy routers, STEP46 |
| Kiwoom (주문·시세 스택) | Adapter/WS/pending · config/token UI | `broker/kiwoom/*`, `brokers/kiwoom/*` |
| Market 데이터 | instrument/price/candle 등 | `market` schema |
| News / DART 조회·sync | 뉴스 sync/summarize · dart disclosures | `api/v1/news.py`, `dart.py` |
| Ollama / AI 분석 | status/models · analysis/candidates | `ai/*`, `/ollama/*` |
| Telegram **송신** | sender + `/notification/test|status` | `notification/telegram_sender.py` |
| Admin 다수 화면 | members/roles/risk/scheduler/db/kiwoom/upbit/… | `frontend/.../admin/*` |
| User 핵심 화면 | dashboard/portfolio/trading/auto-trading/strategies/ai/news… | STEP42~48 |
| Ops DB 점검 | `/ops/db/status`, migration, tables, backup **status** | `api/v1/ops_db.py` |
| 운영센터 허브 | `/admin/operations` live status + 딥링크 | STEP51 |
| Health | `GET /health`, `/version` | health/version routers |

---

# 3. 부분 구현 기능

| 영역 | 상태 | 설명 |
|------|------|------|
| API 보안 | 🟡 | Auth/RBAC는 일부 라우터만 적용. 매매·백테스트·전략 대다수 개방 |
| Live 포지션/포트폴리오 | 🟡 | DB 모델·Paper는 있음. step32 인메모리 API도 동시 마운트 |
| SL / TP / Trailing | 🟡 | 리스크 엔진·백테스트에 로직 존재. **실시간 청산 루프 미연결** |
| Upbit | 🟡 | 시세·캔들 sync만. **주문 API 없음** |
| Realtime Strategy | 🟡 | SL/TP 일부. Trailing·ExitMonitor와 분리 |
| AutomaticScheduler | 🟡 | 구현됨. **API lifespan 미기동** (수동/`run_job_now` 위주) |
| 알림 이벤트 | 🟡 | 송신 인프라 + 테스트. 주문/체결/손절 등 **이벤트 훅 대부분 planned** |
| Log Viewer | 🟡 | 감사 로그 API·의도. **`/admin/logs` 페이지 없음** · 앱 로그 테일 없음 |
| Backup | 🟡 | `GET /ops/backup/status` (도구 존재 여부). dump 실행 없음 |
| User 관심종목 | 🟡 | UI TODO · 보유종목 대체 |
| User RBAC | 🟡 | viewer/trader(operator)/admin FE 가드. Backend `trader` 시드 없음 |
| CORS | 🟡 | localhost:3000 고정 · credentials |
| Audit | 🟡 | kill/scheduler 등 일부만 기록 |
| SSE 시세 UI | 🟡 | BE 존재 언급되나 User Trading UI TODO |
| Discord | 🟡/의도적 제외 | 송신 스택 존재. STEP50에서 UI 제외 |

---

# 4. 미구현 기능

| 영역 | 상태 | 설명 |
|------|------|------|
| OpenClaw Backend | 🔴 | `src/stock_platform` OpenClaw **0건**. FE stub만 |
| Telegram Bot 수신 | 🔴 | webhook/getUpdates · `/status` 등 슬래시 핸들러 없음 |
| 웹 Restore / dump | 🔴 | CLI 매뉴얼 수준. POST API 없음 |
| 앱 로그 테일 API | 🔴 | |
| Watchlist CRUD | 🔴 | |
| `POST /dart/summarize` | 🔴 | |
| User preferences / inbox | 🔴 | |
| 회원↔계좌 소유권 | 🔴 | |
| Upbit 주문 | 🔴 | |
| Next.js middleware 가드 | 🔴 | 클라이언트 AuthGuard만 |
| App Rate Limit | 🔴 | 브로커 limiter만 |
| CSRF 보호 | 🔴 | Bearer 전제 |
| Docker 배포 | 🔴 | Dockerfile/compose 미발견 |
| Admin `/admin/logs`, `/admin/data` | 🔴(라우트) | 메뉴·문서만 있고 `page.tsx` 없음 → **404** |

---

# 5. 제거 가능한 코드 / Dead Code

| 항목 | 상태 | 근거 |
|------|------|------|
| `PositionExitMonitorService` | ⚪ | `position/exit_monitor.py` 정의만. **타 모듈 import 0** |
| `step32_router` 인메모리 positions/portfolio/risk | ⚪/위험 | 프로덕션과 혼동 가능한 표면 |
| `RiskService` (레거시 인메모리) | ⚪ | step32 계열과 연관. `risk_engine`와 중복 |
| OpenClaw FE stub 이벤트 | ⚪(의도) | accepted=false 고정. Backend 전 계약용 |
| `broker`/`common` 빈 스키마 | ⚪ | 테이블 0 (설치 잔존 가능) |
| `operation.system_health` | ⚪ | ORM 미매핑 · LEGACY 문서화 |
| `market`→`/admin/data` redirect | 깨진 호환 | data 페이지 없어 **404 연쇄** |
| `broker/` vs `brokers/`, `market/` vs `markets/`, indicators 이중 prefix | 구조 부채 | 둘 다 사용 중이나 유지비 큼 |

---

# 6. 개선 권장 사항

1. **모든 매매·리스크·실행 API에 JWT + permission 강제**
2. **`ADMIN_API_KEY` 미설정 시 DEV_OPEN 금지** (프로덕션 fail-closed)
3. **회원 스코프 계좌** — `account_id=1` 제거
4. **ExitMonitor를 lifecycle에 연결**하거나 제품 문서에서 “미지원” 명시
5. **step32 인메모리 라우터 제거 또는 `/dev` 격리**
6. **`/admin/logs` · `/admin/data` 페이지 복구 또는 메뉴 삭제**
7. **AutomaticScheduler를 별도 프로세스/문서화** (API와 역할 분리 명확화)
8. **알림 이벤트 publisher** (최소: 주문/체결/Kill Switch)
9. **그린필드 마이그레이션** — market/trading/operation 스키마 CREATE 명시
10. **주문·전략 계열 FK** 보강
11. Docker/compose 또는 설치 매뉴얼과 일치하는 배포 산출물
12. CORS·Rate limit·시크릿 점검 체크리스트를 릴리즈 게이트에 포함

---

# 7. 보안 점검 결과

| 항목 | 판정 | 근거 |
|------|------|------|
| JWT Access | ✅ | HS256 · 타입 클레임 · 시동 시 시크릿 검증 |
| Refresh Token | ✅ | jti + SHA-256 저장 · rotate · logout revoke |
| Password Hash | ✅ | bcrypt rounds=12 · 최소 길이 |
| Role / Permission | 🟡 | 코어 견고. **적용 범위 협소** |
| Secret / API Key | 🟡 | settings/env. Admin key 없으면 DEV_OPEN |
| CORS | 🟡 | localhost only · `allow_credentials` + `*` methods/headers |
| Rate Limit (앱) | 🔴 | 없음 |
| CSRF | 🔴 | 없음 (Bearer 전제) |
| XSS | 🟡 | React 기본 이스케이프. 운영 입력/문서 HTML 별도 점검 필요 |
| SQL Injection | ✅에 가까움 | SQLAlchemy 파라미터 바인딩 중심 |
| 무인증 주문 | 🔴 **Critical** | `order_execution.py`에 `get_current_user`/`require_permission` **없음** |
| 알림 테스트 무인증 | 🔴 | `POST /notification/test` 공개 가능 |
| FE 토큰 저장 | 🟡 | local/sessionStorage — XSS 시 탈취 가능 |

---

# 8. 성능 점검 결과

| 항목 | 판정 | 근거 |
|------|------|------|
| Connection Pool | 🟡 | `pool_pre_ping`, recycle 있음. **pool_size 명시 부족** |
| Async + Sync Session | 🟡 | lifecycle/startup에서 sync Session → 이벤트 루프 블로킹 가능 |
| Rate limiter sleep | 🟡 | Kiwoom SlidingWindow `time.sleep` — 워커 점유 |
| N+1 | 🟡 | 광범위 확증 없음. list는 repository 패턴 위주 |
| 무인증 백테스트/WF | 🔴 | CPU/DB DoS 가능 |
| Batch / Job | 🟡 | Jobs API·history 있음. AutomaticScheduler는 API와 분리 |
| Caching | 🟡/부분 | 명시적 앱 캐시 계층 약함 |
| API Response | 🟡 | Admin JsonPanel·대용량 raw JSON 화면 존재 |

---

# 9. DB 점검 결과

### 사용 스키마·테이블 (라이브 MCP 기준)

| Schema | Tables |
|--------|--------|
| ai | 3 |
| auth | 6 |
| backtest | 3 |
| disclosure | 2 |
| market | 7 |
| news | 3 |
| operation | 18 |
| strategy | 4 |
| trading | 22 |

ORM `__tablename__` **66** ↔ 마이그레이션 `create_table` **66** 이름 기준 **일치**.  
Head revision: `a1b2c3d4e5f6` (감사 시점).

### 미사용·고아

- `operation.system_health` — DB 존재, ORM/코드 미사용 (LEGACY 문서)
- 빈 `broker` / `common` 스키마 가능 (테이블 0)

### FK / Index / Unique / Cascade

- **실제 DB FK 약 24개** — 논리 `*_id` 대비 **미연결 다수**  
  (예: `trading_order_status_history.order_id`, strategy deployment/pipeline 계열, `app_setting_history.setting_key` 등)
- Unique는 instrument/auth/outbox 등 핵심에 존재
- Index는 market/auth 일부에 집중 · ops/strategy 조회성 index 부족 가능
- Cascade: market/news/candidate/backtest/paper 일부 CASCADE · execution/outbox NO ACTION · 일부 SET NULL

### Migration / Comment

- 그린필드 시 **market/trading/operation/news/… 스키마 CREATE 누락** 위험 (일부 revision no-op)
- `alembic/env.py` auth/settings/audit 모델 import 누락 → autogenerate drift 오판 가능
- 테이블/컬럼 **comment 거의 없음** (소수 market만)

### Transaction

- 주문 아웃박스·가드 경로는 서비스 단위 트랜잭션 설계.  
  step32 인메모리와 DB 경로 혼재 시 **일관성 착시** 위험.

---

# 10. Backend 점검 결과

### 계층

| 계층 | 판정 |
|------|------|
| API (Controller) | 🟡 기능 풍부 · **인증 적용 불균일** · step32 레거시 혼재 |
| Service | ✅/🟡 도메인 분리 양호 · 레거시 RiskService·ExitMonitor dead |
| Repository | ✅ 대체로 존재 |
| Entity/Model | ✅ 다수 · FK 약함 |
| DTO/Schema | 🟡 Pydantic 요청 모델 · 일부 중복 가능 |
| Scheduler | 🟡 lifecycle(일손실·아웃박스·전략 계열) vs AutomaticScheduler 분리 |
| Event | 🟡 알림은 메시지 모델만 · 도메인 이벤트 버스 약함 |
| Exception | ✅ 일부 도메인 핸들러 |
| Configuration | ✅ settings/env |
| Security/JWT/RBAC | 🟡 코어 ✅ · 표면 🔴 |
| Validation | ✅ Pydantic Field 제약 |
| Logging | ✅ structlog · Audit 부분 |
| Caching | 🟡 약함 |
| OpenClaw | 🔴 |
| Telegram | 🟡 송신만 |

### 구조 이슈

- 중복 스택: `broker`/`brokers`, `market`/`markets`, indicator 이중 라우터
- 사용되지 않는 Service: ExitMonitor, (사실상) step32 RiskService
- 사용 가능하지만 위험한 API: 무인증 submit/cancel, notification test
- 순환 참조: 본 감사에서 치명적 사이클 미확증
- 의존성: 패키지 이중화로 인지 부하

---

# 11. Frontend 점검 결과

### Admin

| 판정 | 내용 |
|------|------|
| ✅ | Dashboard, members, roles, risk(KS 조작), scheduler, batch, kiwoom, upbit, db, settings, ollama, operations, openclaw(카탈로그), AI, strategies, orders… |
| 🔴 | `/admin/logs`, `/admin/data` **page 없음** → 메뉴 클릭 시 404 |
| 🟡 | notifications 채널 CRUD Unimplemented · operations backup/restore Panel |

### User Web

| 판정 | 내용 |
|------|------|
| ✅ | Auth pages · RBAC 메뉴 필터 · trading/auto-trading/strategies 핵심 |
| 🟡 | UnimplementedNotice 다수 (watchlist, SSE, KS mutate, ownership, OpenClaw…) |
| 🟡 | backtests/trades/account JsonPanel 수준 UX |
| 🔴 | 회원 스코프 계좌 · preferences · inbox |

### 공통

- AuthGuard · apiClient refresh interceptor · PermissionButton(Admin 일부)
- User는 role tier, Admin은 menu permission
- **Broken link:** logs, data, market→data
- Dead: OpenClaw NotConfigured bridge (의도적 stub)
- 중복: Admin/User 유사 API 래퍼 (허용 가능한 분리)

---

# 12. 자동매매 기능 점검

| 기능 | 상태 | 비고 |
|------|------|------|
| 시장 데이터 | ✅/🟡 | 수집·조회 있음. 운영 품질은 데이터 적재에 의존 |
| 종목 관리 | ✅ | instrument · Admin/User 검색 |
| 전략 관리 | ✅/🟡 | deploy/update/stop. DELETE UI TODO |
| 백테스트 | ✅ | |
| Walk Forward | ✅/🟡 | API·UI. 영속 UI 일부 TODO |
| Portfolio | 🟡 | Paper/요약. Live 포트폴리오·optimize TODO |
| Risk Engine | ✅ | 이중 패키지지만 주문 경로 연결 |
| Order | ✅/🔴보안 | 경로 있음 · **인증 필수 미적용** |
| Pending Order | ✅/🟡 | Kiwoom pending 스택 · UI 일부 |
| Execution | ✅ | outbox/execution 테이블·서비스 |
| Position | 🟡 | Paper ✅ · Live DB/API 혼재·step32 |
| Profit/Loss | 🟡 | KPI·일손실. 포지션별 PnL UX 부분 |
| Kill Switch | ✅ | BE+Admin. User는 조회만 |
| Relative Loss | 🟡 | 정책/엔진 존재 여부 대비 제품 노출 제한 |
| Trailing Stop | 🟡/⚪ | 엔진 로직. **실시간 모니터 미연결** |
| Take Profit / Stop Loss | 🟡 | 동일 |
| Daily Loss | ✅ | |
| Position Size | ✅/🟡 | RiskManagementEngine sizing |
| AI Recommendation | ✅ | candidates/top · User AI |
| News | ✅/🟡 | sync/summarize. 전역 피드 없음 |
| Disclosure | 🟡 | 조회·sync. AI summarize 없음 |
| Alert | 🟡 | 카탈로그·test. 이벤트 훅 부족 |
| Telegram | 🟡 | 송신만 |
| OpenClaw | 🔴 | |

---

# 13. OpenClaw / Telegram 점검

| 항목 | 상태 | 근거 |
|------|------|------|
| OpenClaw Gateway/Agent/Workspace/Memory/Skill/Tool | 🔴 BE / 🟡 FE stub | Admin `/admin/openclaw` · User AI bridge |
| Ollama 연결 | ✅ | `/ollama/status` |
| Telegram Bot Token/Chat ID 설정 | ✅ | env/settings `telegram_*` |
| Telegram 송신 | ✅ | NotificationSender |
| Telegram 수신·슬래시 `/status`… | 🔴 | |
| 알림 이벤트 카탈로그 | 🟡 | FE `opsCatalog` — 대부분 planned, KS partial |
| Discord | 의도적 제외 | STEP50 |

**운영 명령:** REST 힌트만 문서화. Bot 실행 경로 없음.

---

# 14. Release 전에 반드시 수정해야 하는 항목

## Critical

1. **매매·취소·일손실 리셋 등 핵심 API에 인증·인가 강제** (`order-execution` 등 무인증 제거)
2. **`require_admin`의 `DEV_OPEN` fail-open 제거** (또는 프로덕션에서 `ADMIN_API_KEY` 필수 + 시동 실패)
3. **User `account_id=1` 하드코딩 제거** 또는 단일테넌트 전용임을 릴리즈 범위에서 명문화하고 외부 공개 금지
4. **Admin `/admin/logs`, `/admin/data` 404 해소** (페이지 추가 또는 메뉴/문서 삭제)
5. **Live 자동청산(SL/TP/Trailing) 범위 명확화** — ExitMonitor 연결 또는 “미지원” 고지 (오해 방지)

## High

6. step32 인메모리 `/positions`·`/portfolio/summary` 제거 또는 비활성
7. `POST /notification/test` 인증 필요
8. Kill Switch·주문 변경에 대한 Audit 강화
9. 회원↔계좌 소유권 (멀티유저 시 필수)
10. AutomaticScheduler 운영 방식 문서화·프로세스 분리
11. CORS를 배포 도메인으로 제한
12. JWT_SECRET / ADMIN_API_KEY / 브로커 시크릿 프로덕션 체크리스트

## Medium

13. 알림 이벤트 훅 (주문/체결/KS 최소)
14. SSE 시세 UI 또는 TODO 고지
15. Watchlist / dart summarize
16. 전략 DELETE · portfolio optimize
17. DB FK·스키마 CREATE·env.py 모델 등록
18. Upbit를 “시세 전용”으로 제품 문구 정리
19. Rate limiting
20. Backup CLI 런북을 릴리즈 패키지에 고정 (웹 API는 후속)

## Low

21. OpenClaw Backend (후속 로드맵)
22. Telegram 슬래시 Bot
23. Discord UI
24. trader 역할 시드
25. 앱 로그 테일 · 웹 restore
26. Comment/문서 정리 · README_STEP 아카이브
27. JsonPanel User 화면 UX 개선

---

# 15. 출시 준비도

### 추정

| 시나리오 | 준비율 | 근거 |
|----------|--------|------|
| **A. 내부 단일 운영자 · Paper · VPN/방화벽 · 수동 런북** | **약 72%** | 핵심 루프·Admin·User·KS·일손실·백테스트·Ollama는 동작 가능. 단, Critical 보안 항목 미해결 시 **외부 노출 금지** |
| **B. 소규모 Live(키움) · 단일 계정 · 강화된 시크릿** | **약 55%** | ExitMonitor 미연결 · 무인증 API · step32 혼재 · 알림 훅 부족 |
| **C. 다중 회원 SaaS · User Web 공개** | **약 38%** | account ownership·API auth 전면화·preferences·watchlist·Rate limit 필수 |
| **D. OpenClaw+Telegram 원격 운영 포함 완전체** | **약 30%** | OpenClaw BE·Bot 수신 전무 |

### 종합 (제품 로드맵 STEP51 기준 “출시”)

**출시 준비율: 약 58%**

- **가산:** 도메인 커버리지 넓음 · Paper 매매·리스크·전략·AI·Auth 코어·Ops 허브·테스트 존재  
- **감산:** Critical 보안 구멍 · 멀티테넌시 부재 · 실시간 청산 미연결 · 깨진 Admin 라우트 · OpenClaw/Telegram 운영 미완 · Docker 부재 · Backup 실행 미완

### 권장 출시 게이트 (최소)

출시 전 **Critical 1~5** 해소 또는 동등한 **네트워크 격리 + 명문화된 단일테넌트 제약**을 강제할 것.  
그 전까지는 **“개발/스테이징 데모”** 로만 취급하는 것이 안전하다.

---

## 부록 A — 기능별 현황 매트릭스 (요청 §2)

| 구분 | 상태 |
|------|------|
| Backend 코어 API | 🟡 |
| Frontend Admin | 🟡 (logs/data 🔴) |
| Frontend User | 🟡 |
| Database 스키마 | ✅/🟡 (FK·스키마 CREATE) |
| Scheduler (lifecycle) | 🟡 |
| AutomaticScheduler | 🟡/⚪(미기동) |
| Kiwoom | ✅/🟡 |
| Upbit | 🟡 (시세) / 🔴 (주문) |
| Broker 일반 | 🟡 |
| Risk Engine | ✅ |
| Strategy | ✅/🟡 |
| Portfolio | 🟡 |
| Backtest / WF | ✅ |
| AI / Ollama | ✅ |
| OpenClaw | 🔴 BE / 🟡 FE |
| Telegram | 🟡 |
| Authentication | ✅ |
| RBAC | 🟡 (적용 범위) |
| Logging / Audit | 🟡 |
| Monitoring / Health | ✅ |
| Batch / Jobs | ✅/🟡 |
| Environment / Settings | ✅ |
| Docker | 🔴 |
| Configuration | ✅ |

---

## 부록 B — 감사 방법

- 코드 탐색: `src/stock_platform`, `frontend/src`, `database/alembic`, `tests`, STEP README  
- DB: PostgreSQL MCP `pg_tables` 스키마별 카운트 · 선행 DB 감사(FK 24, head revision)  
- **본 문서는 분석 전용이며 애플리케이션 코드는 변경하지 않았다.**

---

*End of PROJECT_FINAL_AUDIT.md*
