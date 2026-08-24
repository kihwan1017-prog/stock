# Frontend Ant Design Compatibility Hardening

**FINAL_VERDICT:** `FRONTEND_ANTD_COMPATIBILITY_HARDENED`

## CURRENT DEPENDENCIES (installed)

| Package | Version |
|---------|---------|
| next | 16.2.10 |
| react / react-dom | 19.2.4 |
| antd | 6.5.1 |
| @ant-design/icons | 6.3.2 |
| typescript | 5.9.3 |
| eslint | 9.39.5 |

Package upgrade: **NONE**

## CURRENT WARNING ROOT CAUSE

| Field | Value |
|-------|-------|
| ROOT_CAUSE_FILE | `frontend/src/features/admin/upbit/UpbitResearchCollectionStatusPanel.tsx` |
| ROOT_CAUSE_LINES | 190, 197, 298, 322 |
| OLD_PROP | `message` |
| NEW_PROP | `title` |
| FIXED | **YES** |

Workspace `~1319`는 부모 stack 위치일 뿐 원인 아님.

## PROJECT AUDIT

| Item | Before | After |
|------|--------|-------|
| Alert `message` | 19 | **0** |
| Tabs.TabPane | 0 | 0 |
| Collapse.Panel | 0 | 0 |
| Dropdown overlay | 0 | 0 |
| Table default import | 0 | 0 |
| Null-unsafe asRecord. | found | fixed (`asRecordOrEmpty`) |

## PREVENTION

- ESLint `no-restricted-syntax` (Alert.message, TabPane, Collapse.Panel, overlay, bodyStyle, maskStyle, destroyOnClose, antd default import)
- `npm run check:antd-compat`
- `npm run lint:antd-compat`
- `npm run test:ui:focused` + `src/test/consoleSmoke.ts`
- `npm run check:frontend`
- Checklist: `docs/development/ANTD_UI_COMPATIBILITY_CHECKLIST.md`

## VALIDATION

- check:frontend **PASS**
- typecheck (changed files) **PASS**
- typecheck/lint full: **pre-existing unrelated FAIL** (documented)
- browser smoke: **LIMITED** (no auth E2E)

## SAFETY

All trading/backend mutations **0**. BACKEND_RESTART_COUNT **0**.

## NEXT_ACTION

`CONTINUE_NORMAL_UI_DEVELOPMENT_WITH_COMPATIBILITY_GATE`
