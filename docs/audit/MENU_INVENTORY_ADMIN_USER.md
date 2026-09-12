# MENU INVENTORY — Admin / User (STEP M1)

**Mode:** READ ONLY · **Verdict:** `MENU_INVENTORY_READY`

Source: `frontend/src/config/menu.tsx`, `routes.ts`, `app/(admin|user)/**/page.tsx`.

## Counts

| Metric | Value |
|--------|-------|
| admin_top_level | 10 |
| admin_menu_leaves | 53 |
| admin_pages | 60 |
| user_top_level | 12 |
| user_menu_leaves | 27 |
| user_pages | 36 |
| hidden_routes | 17 |
| broken_entries | 0 |
| embedded_features | 9 |
| duplicate_candidates | 16 |

## Admin menu tree

```text
Admin
├─ Dashboard                          /admin/dashboard
├─ 회원관리
│  ├─ 회원관리                         /admin/members
│  └─ 권한관리                         /admin/roles
├─ 계좌
│  ├─ 전체 계좌                        /admin/accounts
│  ├─ 키움 계좌                        /admin/kiwoom
│  └─ 업비트 계좌                      /admin/upbit  ★ embedded hub
├─ 시장 데이터
│  ├─ 시스템 모니터링                  /admin/monitoring
│  ├─ 뉴스관리                         /admin/news
│  ├─ 공시관리                         /admin/disclosures
│  ├─ 업비트 시세                      /admin/upbit/markets
│  └─ 기술지표 관리                    /admin/indicators
├─ 전략·후보
│  ├─ 후보·LLM 관리 + AI subpages (providers…lifecycle)
│  ├─ 전략관리                         /admin/strategies
│  └─ 백테스트                         /admin/backtests
├─ 거래
│  ├─ 자동매매관리                     /admin/trading
│  ├─ 주문관리                         /admin/orders
│  ├─ 거래내역                         /admin/trades
│  └─ 잔고·손익                        /admin/portfolio
├─ 리스크·운영
│  ├─ 리스크 / LIVE검증 / 운영센터 / Preflight / 통합모니터
│  └─ 스케줄러 / 배치 / 장애복구
├─ 알림 (알림관리, Telegram)
├─ 운영관리 (모니터 중복, 설정, 로그, DB, API, Ollama, 문서)
└─ 내 정보                             /admin/profile
```

## User menu tree

```text
User
├─ 대시보드
├─ 내 계좌 (전체/키움/업비트/Paper)
├─ 시장 정보 (주식/암호화폐/관심/뉴스/공시)
├─ 매매 후보 (주식/업비트/LLM→/user/ai)
├─ 내 전략 (전략/자동매매/백테스트)
├─ 내 주문·체결 (매매/주문/키움/업비트)
├─ 내 잔고·손익
├─ 내 리스크
├─ 업비트 LIVE 검증
├─ 내 리포트
├─ 알림
└─ 내 정보 (프로필/설정)
```

## Hidden / legacy routes

- `/admin/data` · LEGACY_ROUTE · adminRoutes.monitoring · hidden admin route
- `/admin/market` · LEGACY_ROUTE · adminRoutes.monitoring · hidden admin route
- `/admin/portfolio-validations` · HIDDEN_OPERATION_ROUTE · no redirect · Portfolio Validation(사이드바 미노출)
- `/admin/positions` · LEGACY_ROUTE · adminRoutes.portfolio · hidden admin route
- `/admin/settings` · LEGACY_ROUTE · adminRoutes.envSettings · hidden admin route
- `/admin/strategy-drafts` · HIDDEN_OPERATION_ROUTE · no redirect · Strategy Draft 관리(사이드바 미노출)
- `/admin/strategy-requests` · HIDDEN_OPERATION_ROUTE · no redirect · Strategy Request 승인 게이트(사이드바 미노출)
- `/user/account` · LEGACY_ROUTE · userRoutes.accounts · hidden user route
- `/user/ai` · DETAIL_ROUTE · no redirect · AI 추천·LLM 분석(메뉴 미노출, 리다이렉트 타깃)
- `/user/market` · LEGACY_ROUTE · userRoutes.marketsStocks · hidden user route
- `/user/orders/paper` · LEGACY_ROUTE · userRoutes.orders · Paper 주문 → /user/orders 리다이렉트
- `/user/strategies/auto` · LEGACY_ROUTE · userRoutes.autoTrading · hidden user route
- `/user/strategy-drafts` · HIDDEN_OPERATION_ROUTE · no redirect · 내 Strategy Draft(사이드바 미노출)
- `/user/strategy-requests` · HIDDEN_OPERATION_ROUTE · no redirect · 내 Strategy Request(사이드바 미노출)
- `/user/trades` · LEGACY_ROUTE · userRoutes.orders · hidden user route
- `/admin` · LEGACY_ROUTE · adminRoutes.dashboard · admin root redirect to dashboard
- `/user` · LEGACY_ROUTE · userRoutes.dashboard · user root redirect to dashboard

## Embedded features (selected)

- `/admin/upbit` → **UBA Live / Auto Trading readiness** (`AdminUpbitLiveUbaPanel`) — UBA binding·readiness·LIVE 안전 상태
- `/admin/upbit` → **Opportunity Scanner + Technical Shadow** (`UpbitOpportunityScannerPanel`) — Scanner run/status + Shadow evaluate/cohort
- `/admin/upbit` → **News Combined Shadow A/B** (`UpbitNewsCombinedShadowPanel`) — N6/N7/N10 experiment observation
- `/admin/upbit` → **News Collector / N4 / N5** (`UpbitNewsNoticeCollectorPanel`) — Notice/Crypto collect, mapping, AI analysis, signals
- `/admin/upbit` → **Ambiguous Orders** (`UpbitAmbiguousOrdersPanel`) — Upbit ambiguous order resolver ops
- `/admin/trading` → **Strategy Runtime** (`AdminRuntimePanel`) — Scoped runtime status/control
- `/admin/trading` → **Realtime Hub** (`AdminRealtimeHubPanel`) — Realtime hub connections/subscriptions
- `/admin/recovery` → **Recovery Conflict / Scheduler** (`RecoveryConflictPanel,RecoverySchedulerPanel`) — Recovery conflict resolution UI
- `/admin/operations` → **Operation Center tiles** (`OPERATION_CENTER_TILES`) — Ops hub linking to specialized screens

## Duplicate candidates

- `DUP_ACCOUNTS` [ADMIN_USER] ['/admin/accounts|/admin/kiwoom|/admin/upbit', '/user/accounts*'] — 계좌 조회/자격증명 — Admin 전역 vs User 소유 scope
- `DUP_STRATEGIES` [ADMIN_USER] ['/admin/strategies', '/user/strategies'] — 전략 관리 vs 내 전략
- `DUP_ORDERS` [ADMIN_USER] ['/admin/orders|/admin/trades', '/user/orders*|/user/trading'] — 주문/체결 운영 vs 사용자 주문
- `DUP_PORTFOLIO` [ADMIN_USER] ['/admin/portfolio', '/user/portfolio'] — 잔고·손익
- `DUP_RISK` [ADMIN_USER] ['/admin/risk', '/user/risk'] — 리스크 화면
- `DUP_LIVE_VALIDATION` [ADMIN_USER] ['/admin/live-validation/upbit', '/user/live-validation/upbit'] — 업비트 LIVE 검증 Admin 운영 vs User 읽기
- `DUP_NEWS` [ADMIN_USER] ['/admin/news', '/user/news'] — 뉴스 관리 vs 사용자 뉴스 (+ Upbit embedded news ops)
- `DUP_BACKTESTS` [ADMIN_USER] ['/admin/backtests', '/user/backtests'] — 백테스트
- `DUP_NOTIFICATIONS` [ADMIN_USER] ['/admin/notifications|/admin/telegram', '/user/notifications'] — 알림 운영 vs 수신
- `DUP_AUTO_TRADING` [ADMIN_USER] ['/admin/trading', '/user/auto-trading'] — 자동매매 Runtime 제어 vs 사용자 자동매매
- `DUP_ADMIN_MONITORING` [ADMIN_INTERNAL] ['/admin/monitoring (시장 데이터)', '/admin/monitoring (운영관리)'] — 동일 route가 사이드바에 2회 노출
- `DUP_ADMIN_OPS_SURFACES` [ADMIN_INTERNAL] ['/admin/operations', '/admin/operations-dashboard', '/admin/monitoring', '/admin/scheduler'] — 운영/모니터링/스케줄러 표면 분산
- `DUP_ADMIN_NEWS_SURFACES` [ADMIN_INTERNAL] ['/admin/news', '/admin/upbit#NewsPanels'] — 일반 뉴스관리 vs Upbit News pipeline embedded
- `DUP_ADMIN_AI_CLUSTER` [ADMIN_INTERNAL] ['/admin/ai', '/admin/ai/*', '/admin/ollama'] — AI 후보/LLM 세분화 메뉴 다수 + Ollama
- `DUP_USER_CANDIDATES_AI` [USER_INTERNAL] ['/user/candidates/llm', '/user/ai'] — 메뉴 LLM 분석이 /user/ai로 리다이렉트
- `DUP_USER_ORDERS` [USER_INTERNAL] ['/user/orders', '/user/orders/kiwoom|/upbit|/paper'] — 주문 허브 vs 브로커별 주문 화면

## Permission notes

- Admin layout AuthGuard requiredRoles=['admin'] + enforceMenuPermission → ADMIN_ONLY portal
- filterMenuByPermissions: admin role bypasses menu permission checks → admin sees all enabled menus regardless of menu:* grants
- indicators/recovery/profile menu entries lack permission field → permission mismatch candidate vs other menu:* gated items
- User layout redirects admin-role users to /admin/dashboard → USER portal is USER_ONLY in practice for admin accounts
- User menus use minAccess=user only; no menu permission strings → USER_OWNER / role-tier gating

## Broken menu entries

None detected (all sidebar leaf paths resolve to existing `page.tsx`).

## Safety

- frontend/backend production mutation: 0
- DB/route/env/commit: 0 / no
- Scanner/News/Shadow/LIVE paths untouched

Machine-readable: [MENU_INVENTORY_ADMIN_USER.json](./MENU_INVENTORY_ADMIN_USER.json)

