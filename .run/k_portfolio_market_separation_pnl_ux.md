# Portfolio market separation + PnL UX

**FINAL_VERDICT:** `PORTFOLIO_UI_COMPLETE_DATA_GAP_IDENTIFIED`

## Data accuracy audit

| Item | Finding |
|------|---------|
| UPBIT_ZERO_AVG_PRICE_ROOT_CAUSE | AUTO 수량(ownership/binding) + broker snapshot `average_purchase_price=0` 혼합 표시. Snapshot 자체도 OPEN binding 대비 qty=0 stale. |
| UPBIT_ZERO_VALUATION_ROOT_CAUSE | 동일 — `evaluation_amount`/`profit_loss`를 stale snapshot(0)에서 가져와 qty>0인데 평가/손익 0원 표시. |
| FIRST_DATA_GAP_STAGE | `UI_MIXED_SOURCE_MAPPING` |
| UNDERLYING | `BROKER_POSITION_SNAPSHOT_STALE_VS_OPEN_BINDING` |
| BROKER_ASSET_VS_STRATEGY_POSITION | CLEAR |

### SUI / GRVT provenance

- quantity ← `operation.strategy_position_binding` OPEN `owned_quantity`
- avg_price ← binding `entry_price` → ownership `auto_entry_price` (UI)
- current_price ← broker snapshot
- valuation ← UI `qty × current` (broker eval=0 무시)
- unrealized ← valuation − cost (entry≈mark → 0은 정상)

0수량(STX/WLD 등): CLOSED binding + ACTIVE qty=0 snapshot → 기본 숨김.

## UI

- Route: `/admin/portfolio`
- Market filter: 전체 / 업비트 / 키움증권 (`broker_code`)
- Ownership filter: 전체 / 일반매매 / 자동매매
- Summary: 시장별 카드 분리, `시계열 API gap` 제거 → `실현손익 데이터 준비 중`
- Zero qty: 기본 OFF + `[0수량 포함]`
- MARKET_ISOLATION: **PASS**

## Verify

- AUTH_BROWSER_VERIFY: PASS (A–E)
- CONSOLE_ERRORS/WARNINGS: 0 / 0
- HTTP 404/500: 0 / 0
- antd-compat / portfolio eslint / typecheck / vitest(21): PASS
- full `check:frontend`: unrelated lint in `LlmLearningCenterView.tsx`

## Safety

- BACKEND_RESTART_COUNT=0
- REAL_ORDER_MUTATION=0 / LIVE_ARM_MUTATION=0 / REAL_POLICY_MUTATION=0

## Residual

1. Upbit broker snapshot sync lag (qty=0 while OPEN binding)
2. Realized PnL timeseries not wired

## Commit

`feat(admin): separate portfolio views by market`
