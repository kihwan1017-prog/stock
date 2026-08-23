# User-facing Korean localization — Phase 2 evidence

**FINAL_VERDICT:** `USER_FACING_KOREAN_LOCALIZATION_PARTIAL`  
**Previous commit:** `a953632`  
**Recommended commit message:** `feat(ui): complete Korean localization across trading screens`

## Why PARTIAL (not COMPLETE)

1. Authenticated browser rendering of trading screens was **login-gated** (Playwright reached Korean login shell only; session token injection not approved in this run).
2. Residual English remains on some AI/research/debug admin surfaces and intentional abbreviations.
3. USER `AccountsView` LIVE/ARM column pass was deferred to avoid unrelated WIP contamination.

## What landed

- Expanded shared `UI_LABEL_KO` / `tradingDisplayLabelsKo` (`sideLabelKo`, `tradingKindLabelKo`, risk/order keys, unknown fallback `확인 필요 (CODE)`).
- Kiwoom autotrading runtime cards aligned with Upbit terminology.
- Risk/Safety Kill Switch bilingual + live limits table Korean headers.
- Orders: shared `ADMIN_ORDER_READ_TITLES` / `USER_ORDER_READ_TITLES` Korean + side/status display formatters.
- Settlement / realtime / recovery table headers Koreanized.
- Dashboard cockpit / ops monitoring labels updated.

## Browser verify

| Route | Result |
|-------|--------|
| `/admin/upbit/autotrading` | 200 → `/login` (Korean shell, no console errors) |
| `/admin/kiwoom/autotrading` | same |
| `/admin/dashboard` | same |
| `/admin/orders` | same |
| `/admin/risk` | same |
| `/admin/operations-dashboard` | same |
| `/user/*` sampled | same |

Source markers verified on disk: portfolio slots, runtime, kill switch, 주문번호, 매수 허용.

## Mutations / contracts

- REAL/CANCEL/LIVE/ARM/24H/RISK/SLOT/UBA1381 mutations: **0**
- API / DB / enum / trading logic: **unchanged** (display-only)

## BUG_FOUND

- `OPEN_SLOT_PNL_SL_API_GAP` — recorded only, not fixed.

## Tests

- `tradingCockpitUx.test.ts`, `orderReadColumns.test.ts` — PASS

## NEXT_ACTION

`COMPLETE_REMAINING_USER_VISIBLE_LOCALIZATION`
