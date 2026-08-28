# UPBIT Entry Execution Provenance Hardening

- REVISION: `ue1a2b3c4d5e`
- TABLE: `operation.upbit_entry_execution_trace`
- API: `GET /api/v1/admin/autotrading/uba/{uba_id}/why-no-trade`
- TESTS: 9 passed
- TRADING_POLICY_CHANGED: **false**
- HISTORICAL 15 cases: **UNPROVEN** (no backfill)

Deploy: `alembic upgrade head` + backend restart (unattended restore).