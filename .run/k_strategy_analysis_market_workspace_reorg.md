# Strategy Analysis Market Workspace Reorganization

**Verdict:** `STRATEGY_ANALYSIS_KIWOOM_UPBIT_WORKSPACE_AUTH_VERIFY_PENDING`

## MENU_BEFORE → MENU_AFTER

| Before | After |
|--------|-------|
| 전략·후보 → `/admin/strategies` | `/admin/strategy-candidates` (+ matchPaths 유지) |
| 시장 분석 → `/admin/upbit/markets` | `/admin/market-analysis` |
| 뉴스·공시 → `/admin/news` | `/admin/news-disclosures` |
| AI 설정 only | **AI 분석** + **AI 설정** 분리 |
| 전략 검증 → `/admin/backtests` | `/admin/strategy-validation` |
| (없음) | **연구 데이터** → `/admin/research` |

자동매매 = LIVE 운영 / 전략·분석 = 후보·시장·뉴스·AI·연구·검증

## MARKET_SELECTOR

`[전체 | 키움 | 업비트]` → `ALL | KIWOOM | UPBIT`  
URL: `?market=UPBIT` (새로고침 유지)

## Per-area

| Area | KIWOOM | UPBIT |
|------|--------|-------|
| STRATEGY_CANDIDATE | lifecycle/strategies links | research + autotrading slot ops link |
| MARKET_ANALYSIS | indicators / AI market | upbit markets + research context |
| NEWS_DISCLOSURE | news + DART | research news + news admin |
| AI_ANALYSIS | market-analyses / assessments | research LLM |
| STRATEGY_VALIDATION | backtests / promotions | CLEAN / E1–E8 via research |
| RESEARCH_DATA | existing links only (no fake) | full collection-status panel reuse |

## Autotrading cleanup

- UPBIT: full research panel → **요약 카드** + link `연구 데이터?market=UPBIT`
- KIWOOM: **분석·연구** 요약 + link `?market=KIWOOM`

## Safety

REAL/LIVE/ARM/Risk/Slot/Policy mutation = **0**  
NEW_API = none · collection-status 재사용

## Gates

- check:antd-compat / lint / typecheck / test:ui:focused → PASS
- AUTH browser → LIMITED

## NEXT_ACTION

관리자 로그인 후 전략·분석 6+1 메뉴와 자동매매 요약 링크를 브라우저로 확인.
