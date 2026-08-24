# AntD Statistic valueStyle deprecation fix

**FINAL_VERDICT:** `FRONTEND_ANTD_STATISTIC_DEPRECATION_FIXED_AUTH_VERIFY_PENDING`

## Root cause

| Field | Value |
|-------|-------|
| FILE | `UpbitResearchCollectionStatusPanel.tsx` |
| LINES | 338, 352, 361 |
| BEFORE count | 3 |
| AFTER count | 0 |
| OLD | `valueStyle={{ fontSize: 18 }}` |
| NEW | `styles={{ content: { fontSize: 18 } }}` |

## Gate miss

**CHECK_GATE_MISS_ROOT_CAUSE:** `CHECK_RULE_MISSING`

이전 `check:antd-compat` / ESLint가 Alert.message만 커버하고 Statistic.valueStyle 규칙이 없었음 (런타임 deprecation warning).

## After

- Alert message remaining: **0**
- Statistic valueStyle remaining: **0**
- check:antd-compat updated: **YES**
- lint / typecheck / focused vitest / check:frontend: **PASS**

## Browser

Authenticated `/admin/upbit/autotrading` console verify: **NOT RUN** → AUTH_VERIFY_PENDING

## NEXT_ACTION

`CONTINUE_UI_WITH_RUNTIME_ANTD_GATE`
