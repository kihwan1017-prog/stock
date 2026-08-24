# Frontend Baseline Cleanup

**FINAL_VERDICT:** `FRONTEND_BASELINE_CLEAN`

## BEFORE

| Gate | Result |
|------|--------|
| lint | FAIL — 17 errors, 16 warnings |
| typecheck | FAIL — 12 errors |
| check:antd-compat | PASS |
| check:frontend (narrow) | PASS |

## FIXED (요약)

- Dashboard `PeriodFilter`에 `90D` 통일 · URL Set.has typing
- Opportunity Scanner null 비교 / filters typing / stable Tag key
- `runtimePreflight(ubaId)` query key · live-validation `arm_token` optional typing
- setState-in-effect → derive / lazy init / keyed remount
- React Compiler memo deps → query `data`
- impure `Date.now` / `Math.random` 제거
- unused imports/vars · test `require` → ESM import

## AFTER

| Gate | Result |
|------|--------|
| `npm run lint` | **PASS** (0 warnings) |
| `npm run typecheck` | **PASS** |
| `npm run check:antd-compat` | **PASS** |
| `npm run test:ui:focused` | **PASS** 7/7 |
| `npm run check:frontend` | **PASS** (full lint+tsc+antd+focused) |

## BROWSER

Upbit / Dashboard / Portfolio console smoke: **LIMITED** (인증 E2E 없음)

## SAFETY

All trading/backend mutations **0**. BACKEND_RESTART **0**.

## NEXT_ACTION

`CONTINUE_NORMAL_UI_DEVELOPMENT_WITH_CLEAN_BASELINE`
