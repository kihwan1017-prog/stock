# Single Admin Operator UX Consolidation

**Date:** 2026-08-22  
**Mode:** Architecture Audit + Implementation (frontend-first)  
**LIVE note:** Backend under `uvicorn --reload` → **PRODUCTION_RELOAD_RISK**. Backend orchestration endpoint deferred as **SAFE_RELOAD_REQUIRED**.

---

## 1. Inventory summary

| Area | Count / note |
|------|----------------|
| Admin sidebar (pre) | 11 top / ~40 leaves |
| User sidebar (pre) | 12 top / ~29 leaves |
| Admin pages | ~59 `page.tsx` |
| User pages | ~36 (retained as redirect targets) |
| Canonical LIVE WRITE | `/admin/accounts` + Upbit 24x7 controls (not duplicated in hubs) |
| Unattended reauth | `POST .../unattended/reauthorize` (existing) |
| Stack start FE | `runUpbit24x7StackStart` (existing) |

### Backend (READ-ONLY inventory)

- ADMIN autotrading: `admin_autotrading_readiness.py` (unattended enable/reauthorize/disable, runtime, worker, exit)
- LIVE/ARM: live services — **not mutated in this STEP**
- USER APIs: retained (FK / ownership / audit) — **LEGACY_INTERNAL_IDENTITY_REQUIRED**
- DB DROP: **not performed**

### FK / identity

`user_id` on UBA, orders, positions, audits, notifications remains. UI no longer exposes member/role product features.

---

## 2. Old → New menu mapping

| Old | New |
|-----|-----|
| 운영 대시보드 | 대시보드 |
| 회원·권한 / 내 정보 | **removed from sidebar** (routes kept, redirect optional) |
| 전체/키움/업비트 계좌 | 계좌·자산 → 계좌 현황 (`?broker=`) |
| 잔고·손익 | 계좌·자산 → 보유자산·손익 |
| 업비트 자동매매 설정 | 자동매매 → 업비트 자동매매 |
| 자동매매 Runtime / Preflight / 거래 운영 현황 | Workspace 탭·상세 (메뉴 leaf 제거, route 유지) |
| 주문관리 + 거래내역 | 자동매매 → 주문·체결 |
| 전략·후보 5 leaf | 전략·분석 (시장/뉴스/AI/검증 포함) |
| 리스크·LIVE검증 | 리스크·안전 (+ 장애·복구) |
| 알림/Telegram | 알림 센터 |
| 시스템 운영 다수 leaf | 시스템 상태 / 스케줄·배치 / 로그·감사 / 데이터·API / 환경 / AI 인프라 / 문서 |
| 전 USER portal | `/user/*` → `/admin/dashboard` (admin) or forbidden |

---

## 3. One-click architecture (this STEP)

**Frontend orchestration** (no new backend mutation endpoint):

1. Ops snapshot / readiness
2. If `needs_reauthorize` → `reauthorizeAdminUbaUnattended`
3. Else `runUpbit24x7StackStart` (Worker → Exit → Runtime; gates fail-closed)
4. Optional stack stop via `runUpbit24x7StackStop`

Backend `POST /admin/autotrading/uba/{id}/start|stop`: **SAFE_RELOAD_REQUIRED** (avoid LIVE restart under `--reload`).

---

## 4. Safety

- REAL_ORDER_MUTATION: 0 (by design this STEP)
- LIVE_ARM_MUTATION: 0 (orchestration only when operator clicks; no auto toggle in audit)
- UBA1381_MUTATION: 0
- DB DROP: 0
