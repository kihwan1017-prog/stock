# MENU IA Consolidation Design — STEP M2

**Mode:** DESIGN ONLY · **Verdict:** `MENU_IA_DESIGN_READY`  
**Input SoT:** [MENU_INVENTORY_ADMIN_USER.md](./MENU_INVENTORY_ADMIN_USER.md) · [MENU_INVENTORY_ADMIN_USER.json](./MENU_INVENTORY_ADMIN_USER.json)  
**Date:** 2026-08-14

> Production menu/route/component/API/permission **변경 없음**.  
> REMOVE_CANDIDATE도 **실제 삭제 금지** — 후속 Wave + 사용자 승인 후.

---

## 0. M1 기준값 (재확인)

| Metric | M1 |
|--------|-----|
| Admin top / leaf / pages | 10 / 53 / 60 |
| User top / leaf / pages | 12 / 27 / 36 |
| Hidden / Broken / Embedded | 17 / 0 / 9 |

코드와 M1 충돌: **없음** (본 설계는 M1 inventory를 SoT로 사용).

---

## 1. Domain 재분류 (20)

| Domain | 의미 |
|--------|------|
| DASHBOARD | 포털 요약 |
| MEMBER_ACCESS | 회원·역할·권한 |
| ACCOUNT | 계좌·Credential·UBA |
| MARKET_DATA | 시세·관심·공시·지표 |
| SCANNER_CANDIDATE | Opportunity Scanner / 매매 후보 |
| AI_ANALYSIS | Market AI / LLM 분석 결과 |
| AI_PLATFORM | Provider/Prompt/Schema/Policy/Ollama |
| NEWS_NOTICE | 일반 뉴스 + UPBIT News pipeline |
| STRATEGY | Strategy / Request / Draft / Lifecycle |
| BACKTEST | 백테스트·Portfolio Validation |
| PAPER_SHADOW | Paper Shadow / Cohort / Combined A/B |
| ORDER_EXECUTION | 주문·체결·Ambiguous |
| POSITION_PNL | 잔고·포지션·손익 |
| RISK | 리스크·Kill Switch·한도 |
| LIVE_CONTROL | LIVE 검증·Preflight·ARM 관련 운영 UI |
| RUNTIME_SCHEDULER | Runtime / Scheduler / Batch / Realtime Hub |
| RECOVERY_SYNC | Recovery / Conflict / Sync |
| NOTIFICATION | 알림·Telegram |
| OPERATIONS_HEALTH | Health / Monitoring / Ops hub |
| SYSTEM_SETTINGS | env/system/DB/API/docs |
| PROFILE | 내 정보·설정 |

---

## 2. 판정 Enum 요약 (Current → Decision)

집계 (메뉴 leaf + 주요 hidden/embedded 단위; 상세는 JSON):

| Decision | 대략 n | 의미 |
|----------|--------|------|
| KEEP | 28 | 위치·역할 유지 |
| MERGE | 18 | 허브/탭으로 통합 |
| MOVE | 14 | 도메인 이동 |
| HIDE | 8 | 메뉴 비노출·상세/탭 |
| DEPRECATE | 11 | legacy redirect 유지 |
| DETAIL_ONLY | 6 | 리스트→상세 |
| REDIRECT_ONLY | 11 | 호환 redirect만 |
| REMOVE_CANDIDATE | 0 | **증거 부족 → 0** |

---

## 3. Admin ↔ User 공용 기능 전략

| 기능 | 전략 | 설명 |
|------|------|------|
| 계좌 | **B** 공용 Component + Scope 분리 | Admin=전역/복구 · User=owner self-service. route 통합 금지 |
| 전략 | **B** | Admin=승인·배포 · User=내 전략/요청. Request/Draft는 STRATEGY workflow |
| 주문 | **B** | Admin=운영/Outbox · User=실행·내역. broker 탭은 User 내부 MERGE |
| 포트폴리오 | **B** | 동일 요약 컴포넌트 가능, scope 분리 |
| 리스크 | **C** 별도 유지 + 일부 SHARE | Admin=정책/Kill · User=내 한도 조회 |
| LIVE 검증 | **C** | Admin=운영 실행 · User=읽기 전용 유지 |
| 뉴스 | **C/D 혼합** | User 뉴스 읽기 유지 · Admin 일반뉴스 KEEP · UPBIT pipeline은 자동매매 허브 |
| 백테스트 | **B** | 결과 뷰 공용 가능, 실행 권한 분리 |
| 알림 | **B** | User=수신 · Admin=운영/Telegram |
| 자동매매 | **C** | Admin=Runtime/Scanner/Shadow · User=내 자동매매 상태. **route 통합 금지** |

억지 단일 route 통합: **하지 않음**.

---

## 4. `/admin/upbit` 과밀 처리안

현재 embedded ≥5 운영 패널 → **과밀**.

| Feature | 추천 |
|---------|------|
| UBA Account / Credential / readiness | **KEEP_EMBEDDED** (계좌 허브 핵심) + 탭 `계좌` |
| Auto Trading Status (UBA) | **SEPARATE_TAB** `상태` |
| Opportunity Scanner | **SEPARATE_TAB** `Scanner` → Domain SCANNER_CANDIDATE |
| Technical Shadow / Cohort | **SEPARATE_TAB** `Shadow` → PAPER_SHADOW |
| News Collector / Mapping / N4 / N5 | **SEPARATE_TAB** `News Pipeline` → NEWS_NOTICE |
| Combined A/B Experiment | **SEPARATE_TAB** (News Pipeline 하위 또는 동일 탭 섹션) |
| Ambiguous Orders | **MOVE_TO_OTHER_DOMAIN** → ORDER_EXECUTION / Recovery 인접 탭 `Ambiguous` |
| (향후) 전용 leaf menu 폭증 | **금지** — **허브 + 탭** 우선 |

목표 route 후보 (구현 시):

```text
/admin/upbit                      # hub shell
  ?tab=account|status|scanner|shadow|news|ambiguous
```

기능 삭제 없음 · 패널만 탭 분리.

---

## 5. Operations 중복 Matrix → 목표 그룹

| Capability | operations | ops-dashboard | monitoring | recovery | trading | risk |
|------------|:---:|:---:|:---:|:---:|:---:|:---:|
| Health/Monitor | △ | ● | ● | | | |
| Scheduler/Batch | △ | △ | | △ | | |
| Runtime/Hub | | | | | ● | |
| Preflight | △(link) | | | | | ●(path) |
| Recovery/Conflict | | | | ● | | |
| Outbox/Orders | | | | | △ | △ |
| Risk/Kill | | | | | | ● |
| Live Control | △ | | | | △ | ● |

**목표 그룹**

1. **자동매매 운영** (`/admin/autotrading` 후보 hub)  
   상태 · Runtime · Scheduler · Preflight · (링크) Recovery  
   ← MERGE: trading + operations 타일 중 자동매매 관련 + preflight + scheduler
2. **리스크/안전**  
   Risk · LIVE 검증 · (Outbox fencing 링크)  
   ← KEEP risk, MOVE live-validation 여기
3. **장애 복구**  
   Recovery hub (Conflict/Scheduler panels)  
   ← KEEP recovery, HIDE 중복 ops 진입점
4. **시스템 Health**  
   monitoring 단일 진입 (sidebar 이중 노출 MERGE→1)  
   ← operations-dashboard는 monitoring/ops hub의 탭 또는 DETAIL

`/admin/monitoring` 사이드바 2회 → **MERGE** (한 메뉴만 유지).

---

## 6. AI 메뉴 처리안

기술명 "AI" 단일 덤프 지양 → **업무 분리**:

| 버킷 | 포함 | 메뉴 위치 |
|------|------|-----------|
| AI Platform | providers, prompts, schemas, policies, executions, ollama, eval/benchmark | **시스템 운영 → AI Platform** |
| Trading / Market AI | market-analyses, reviews | **자동매매 → 분석** 또는 시장 데이터 |
| Candidate / Strategy gen | candidate-* , ai hub | **전략 → 후보/게이트웨이** |
| News AI | N4 analysis (Upbit hub) | **자동매매/Upbit → News Pipeline** (AI 메뉴에 넣지 않음) |

`/admin/ai` leaf 과밀 → **MERGE** into 3 hubs + DETAIL_ONLY children.

---

## 7. News 메뉴 처리안

| Surface | 역할 | 판정 |
|---------|------|------|
| `/admin/news` | General News Management | **KEEP** (MARKET_DATA/NEWS) |
| `/user/news` | 사용자 읽기 | **KEEP** |
| `/admin/upbit` News panels | UPBIT News Pipeline (N2–N10) | **SEPARATE_TAB** under Upbit/Autotrading hub — **통합 단일 메뉴로 강제 병합 금지** |

같은 article repo를 써도 **운영 목적(파이프라인 vs CMS)** 이 다르면 분리 유지.  
교차 링크만 권장.

---

## 8–9. Target User / Admin top-level

### User: 12 → **8**

```text
User
├─ 대시보드
├─ 내 계좌          (키움/업비트/Paper 탭)
├─ 시장             (주식/암호화폐/관심/뉴스/공시)
├─ 자동매매         (후보 · 전략 · 요청/Draft · 백테스트 · 자동매매 상태 · LIVE검증)
├─ 거래             (매매 실행 · 주문/체결 · 브로커 탭)
├─ 자산·손익
├─ 리스크·알림      (리스크 · 리포트 · 알림)  ※ 또는 리스크/알림 분리 유지 가능
└─ 내 정보          (프로필 · 설정)
```

흐름: 계좌 → 후보/전략 → Paper/자동매매 → LIVE검증 → 주문 → 손익 → 리스크/리포트.

### Admin: 10 → **9**

```text
Admin
├─ 운영 대시보드
├─ 회원·권한
├─ 계좌             (전체 · 키움 · 업비트[hub+tabs])
├─ 시장 데이터      (시세 · 공시 · 지표 · 일반뉴스)  ※ monitoring 여기 아님
├─ 자동매매         (Scanner/Shadow · Upbit News Pipeline · Runtime · Scheduler · Preflight)
├─ 거래·주문        (주문 · 체결 · Ambiguous)
├─ 리스크·안전      (Risk · LIVE 검증)
├─ 전략             (Strategies · Request · Draft · Portfolio Validation · Backtest · Candidate gateway)
├─ 시스템 운영      (Health/Monitoring · Recovery · 알림/Telegram · AI Platform · Settings · Logs · DB · API · Docs)
└─ (내 정보는 시스템 또는 하단 KEEP)
```

내 정보는 top 유지(10번째) 가능 → **target top-level = 9~10** (프로필 독립 시 10).  
본 설계 **권장: 9 + 프로필 = 10** 이되 업무 top은 9로 체감 단순화.

확정 카운트 보고용: **Admin target top-level = 9** (프로필을 시스템 하단 링크로 둘 경우) / 문서 트리에는 프로필 KEEP.

JSON에서는 `admin_target_top_level: 9`, `user_target_top_level: 8`.

---

## 10. Hidden Route 정책

| Route | Policy | 상위 workflow |
|-------|--------|----------------|
| `/admin/strategy-requests` | **PROMOTE_TO_MENU** (전략 하위) | 전략 → 요청 심사 |
| `/admin/strategy-drafts` | **PROMOTE_TO_MENU** | 전략 → Draft |
| `/admin/portfolio-validations` | **PROMOTE_TO_MENU** 또는 DETAIL | 전략 → Validation |
| `/user/strategy-requests` | **PROMOTE_TO_MENU** (자동매매/전략 하위) | 내 전략 → 요청 |
| `/user/strategy-drafts` | **PROMOTE_TO_MENU** | 내 전략 → Draft |
| `/user/ai` | **DETAIL_ONLY** / KEEP_HIDDEN menu | 후보 LLM → detail |
| Legacy redirects (아래) | DEPRECATE_REDIRECT | — |
| `/admin` `/user` roots | KEEP_HIDDEN redirect | dashboard |

ACTIVE 숨김 기능을 orphan 취급하지 **않음**.

---

## 11. Legacy Route 정책

| Route | Policy |
|-------|--------|
| `/admin` → dashboard | KEEP_REDIRECT |
| `/admin/data` `/admin/market` → monitoring | DEPRECATE_REDIRECT |
| `/admin/positions` → portfolio | DEPRECATE_REDIRECT |
| `/admin/settings` → env-settings | DEPRECATE_REDIRECT |
| `/user` → dashboard | KEEP_REDIRECT |
| `/user/account` → accounts | DEPRECATE_REDIRECT |
| `/user/market` → markets/stocks | DEPRECATE_REDIRECT |
| `/user/trades` → orders | DEPRECATE_REDIRECT |
| `/user/strategies/auto` → auto-trading | DEPRECATE_REDIRECT |
| `/user/orders/paper` → orders | DEPRECATE_REDIRECT |
| `/user/candidates/llm` → ai | KEEP_REDIRECT (또는 메뉴를 ai로 직결 LOW) |

실제 redirect 제거 = 후속 Wave · **REMOVE_LATER**는 telemetry 후.

---

## 12–13. 업무 Flow 평가

**User:** 현재 12 top이 흐름을 분절(후보/전략/자동매매/LIVE/주문/리스크/리포트 산재). Target 8이 흐름에 더 가깝다.

**Admin:** monitoring 이중·ops 삼각·Upbit 과밀이 운영 흐름(계좌→Scanner→Runtime→Preflight→Order→Recovery→Health)을 방해. Target 자동매매 허브가 핵심 경로.

---

## 14. 과밀도

| Page | 현재 | 목표 |
|------|------|------|
| `/admin/upbit` | panels ≥5 | tabs ≤6, panel/탭 ≤3 |
| `/admin/ai/*` | leaf 15+ | 3 hub + detail |
| `/admin/operations*` | 3 surfaces | 1 hub + tabs |
| User orders* | 4 leaves | 1 + broker tabs |

---

## 15. Shared Component 후보

| Component | 판정 |
|-----------|------|
| AccountStatusCard | SHARE_COMPONENT |
| BrokerCredentialForm | SHARE_COMPONENT (scope props) |
| StrategyList | SHARE_COMPONENT |
| OrderList | SHARE_COMPONENT |
| PortfolioSummary | SHARE_COMPONENT |
| RiskSummary | SHARE_COMPONENT |
| NotificationList | SHARE_COMPONENT |
| BacktestResultTable | SHARE_COMPONENT |
| LiveValidationPanel | KEEP_SEPARATE (Admin write vs User read) |
| Upbit News Pipeline panels | KEEP_SEPARATE (Admin ops only) |
| Runtime/Preflight | KEEP_SEPARATE (Admin) |

---

## 16. Permission 개선 후보 (수정 금지 · 제안만)

| 대상 | 제안 key |
|------|----------|
| indicators | `menu:indicators` |
| recovery | `menu:recovery` |
| profile (admin) | `menu:profile` or open |
| strategy-requests | `menu:strategy_requests` |
| strategy-drafts | `menu:strategy_drafts` |
| portfolio-validations | `menu:portfolio_validations` |
| upbit tabs (future) | `menu:upbit` 하위 세분화는 MEDIUM+ |

Admin role bypass 현상은 문서화만 — 모델 변경은 HIGH.

---

## 17. REMOVE_CANDIDATE

**0건.**  
대체 미증명 · ACTIVE pipeline/전략 게이트 존재 · legacy는 DEPRECATE_REDIRECT만.

---

## 18–19. CURRENT → TARGET mapping (요약)

### Admin (발췌)

| Current | Decision | Target |
|---------|----------|--------|
| Dashboard | KEEP | 운영 대시보드 |
| members/roles | KEEP | 회원·권한 |
| accounts/kiwoom | KEEP | 계좌 |
| upbit | MERGE(tabs) | 계좌 + 자동매매 탭 연계 |
| monitoring ×2 | MERGE | 시스템 운영 · Health 1회 |
| news | KEEP | 시장 데이터 |
| disclosures/indicators/upbit-markets | KEEP | 시장 데이터 |
| ai/* many | MOVE/MERGE | 전략 후보 vs AI Platform |
| strategies/backtests | KEEP/MOVE | 전략 |
| strategy-requests/drafts/portfolio-validations | PROMOTE | 전략 하위 |
| trading | MERGE | 자동매매 |
| orders/trades | KEEP/MERGE | 거래·주문 |
| portfolio | KEEP | 거래 또는 자산 링크 |
| risk / live-validation | KEEP/MOVE | 리스크·안전 |
| operations / ops-dashboard / scheduler / batch | MERGE | 자동매매 + 시스템 |
| recovery | KEEP | 시스템 운영 |
| notifications/telegram | KEEP | 시스템 운영 |
| system/env/logs/db/api/ollama/docs | KEEP | 시스템 운영 |
| profile | KEEP | 내 정보 |

### User (발췌)

| Current | Decision | Target |
|---------|----------|--------|
| dashboard | KEEP | 대시보드 |
| accounts* | MERGE tabs | 내 계좌 |
| markets*/watchlist/news/disclosures | MERGE | 시장 |
| candidates* / strategies / auto-trading / backtests / live-validation / strategy-req/draft | MERGE | 자동매매 |
| trading / orders* | MERGE | 거래 |
| portfolio | KEEP | 자산·손익 |
| risk / reports / notifications | MERGE | 리스크·알림 (또는 분리) |
| profile/settings | KEEP | 내 정보 |

---

## 20. 난이도

**LOW:** 메뉴 라벨/순서, monitoring 이중 제거, User LLM 메뉴 직결, hidden strategy* 메뉴 노출  
**MEDIUM:** Upbit 탭 허브, ops 허브 통합, User top 축소, shared list components  
**HIGH:** permission 모델, Admin/User route 통합 시도(비권장), page 삭제, API ownership

---

## 21. Implementation Waves (설계만)

| Wave | 내용 | Risk |
|------|------|------|
| **M3-A** | LOW: label/order, monitoring 중복 메뉴 1개화, User candidates/llm 직결 | LOW |
| **M3-B** | Strategy Request/Draft/Validation 메뉴 노출 + legacy redirect 정책 문서화 | LOW–MED |
| **M4** | Admin operations/trading/preflight/scheduler 허브 정리 | MEDIUM |
| **M5** | `/admin/upbit` 탭 분해 (기능 보존) | MEDIUM |
| **M6** | Shared account/order/portfolio components | MEDIUM |
| **M7** | DEPRECATE redirect cleanup (telemetry 후) | MEDIUM |
| **M8** | Full FE regression + permission keys | HIGH |

---

## 22. 절대 보호

Account · Scanner · Shadow/Cohort · News pipeline · AI News · Signal · Combined A/B · Strategy Request/Draft · Backtest · Paper · Runtime · Preflight · Recovery · Orders/Outbox · Risk/Kill · Market Feed · Notification — **기능 삭제 없음** (메뉴 HIDE/MOVE만 가능).

---

## 23. 산출물

- 본 문서  
- [MENU_IA_CONSOLIDATION_DESIGN.json](./MENU_IA_CONSOLIDATION_DESIGN.json)

## 24. Safety

frontend/backend production mutation = **0** · commit = **no** · DB/env = **no**
