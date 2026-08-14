# MENU M4-B — Admin Operations Menu Regroup

**Mode:** APPLY (menu IA only)  
**Verdict:** `MENU_M4B_READY_WITH_LIMITATIONS`  
**Date:** 2026-08-15  
**Baseline:** M4-A `62bd783`  
**Input:** [MENU_M4_OPERATIONS_PRECHECK.md](./MENU_M4_OPERATIONS_PRECHECK.md) · [MENU_M4A_OPERATIONS_READONLY_CONSOLIDATION.md](./MENU_M4A_OPERATIONS_READONLY_CONSOLIDATION.md)

> 메뉴 regroup ≠ 기능 통합. route/page/CONTROL/API 불변.  
> commit/push 하지 않음. M4-C 자동 진행 금지.

---

## BEFORE → TARGET (최소 변경)

| href | before group | after group | label before | label after | 조치 |
|------|--------------|-------------|--------------|-------------|------|
| `/admin/operations-dashboard` | 리스크·운영 | **자동매매 운영** | 거래 운영 현황 | 동일 | MOVE |
| `/admin/trading` | 거래 | **자동매매 운영** | 자동매매 Runtime | 동일 | MOVE |
| `/admin/operations/preflight` | 리스크·운영 | **자동매매 운영** | Pre-flight Check | 동일 | MOVE |
| `/admin/operations` | 리스크·운영 | **시스템 운영** | 시스템 운영 | 동일 | MOVE |
| `/admin/monitoring` | 운영관리 | **시스템 운영** | 시스템 모니터링 | 동일 | MOVE (group rename) |
| `/admin/scheduler` | 리스크·운영 | **시스템 운영** | 스케줄러 관리 | **시스템 스케줄러** | MOVE + label |
| `/admin/recovery` | 리스크·운영 | **시스템 운영** | 장애 복구 | 동일 | MOVE |
| `/admin/batch` | 리스크·운영 | **시스템 운영** | 배치 관리 | 동일 | MOVE |
| `/admin/risk` | 리스크·운영 | **리스크·안전** | 리스크 관리 | 동일 | KEEP (group rename) |
| `/admin/live-validation/upbit` | 리스크·운영 | **리스크·안전** | 업비트 소액 LIVE 검증 | 동일 | KEEP |
| `/admin/orders` | 거래 | **거래** | 주문관리 | 동일 | KEEP (이동 안 함) |
| `/admin/accounts` · `/admin/upbit` | 계좌 | **계좌** | 업비트 계좌 등 | 동일 | KEEP — LIVE leaf 추가 안 함 |

---

## BEFORE tree (Admin top-level = 10)

```text
운영 대시보드
회원·권한
계좌
시장 데이터
전략·후보
거래
  자동매매 Runtime
  주문관리
  거래내역
  잔고·손익
리스크·운영
  리스크 관리
  업비트 소액 LIVE 검증
  시스템 운영
  Pre-flight Check
  거래 운영 현황
  스케줄러 관리
  배치 관리
  장애 복구
알림
운영관리
  시스템 모니터링
  시스템 설정 · 환경설정 · 로그 · DB · API · Ollama · 문서
내 정보
```

Leaf = 55

---

## AFTER tree (Admin top-level = 11)

```text
운영 대시보드
회원·권한
계좌
시장 데이터
전략·후보
자동매매 운영          ← NEW
  거래 운영 현황
  자동매매 Runtime
  Pre-flight Check
거래
  주문관리
  거래내역
  잔고·손익
리스크·안전            ← rename from 리스크·운영
  리스크 관리
  업비트 소액 LIVE 검증
알림
시스템 운영            ← rename from 운영관리 + ops 흡수
  시스템 운영
  시스템 모니터링
  시스템 스케줄러
  장애 복구
  배치 관리
  시스템 설정 · 환경설정 · 로그 · DB · API · Ollama · 문서
내 정보
```

Leaf = 55 (add/delete leaf = 0)

---

## Canonical ownership (불변)

| Domain | Route | Menu after |
|--------|-------|------------|
| SYSTEM_OPS_LAUNCHPAD | `/admin/operations` | 시스템 운영 |
| Runtime CONTROL | `/admin/trading` | 자동매매 운영 |
| Trading RO dashboard | `/admin/operations-dashboard` | 자동매매 운영 |
| Infra monitoring | `/admin/monitoring` | 시스템 운영 (occurrence=1) |
| Recovery CONTROL | `/admin/recovery` | 시스템 운영 |
| Risk/Kill | `/admin/risk` | 리스크·안전 |
| Scheduler | `/admin/scheduler` | 시스템 운영 |
| Preflight | `/admin/operations/preflight` | 자동매매 운영 |
| Orders/Outbox | `/admin/orders` | 거래 (유지) |
| LIVE/ARM | UBA on accounts/upbit | 계좌 (신규 leaf 없음) |

---

## M2 target 비교

| | value |
|--|-------|
| M2 target top-level | 9 |
| M4-B actual | **11** |
| before | 10 |

이유: 자동매매 운영을 분리하면서도 거래(주문)·리스크·시스템 설정을 억지 병합하지 않음. domain clarity > 숫자.

---

## Safety

| 항목 | 결과 |
|------|------|
| route add/delete/rename | 0 |
| permission | 0 |
| AuthGuard | 0 |
| API/backend | 0 |
| CONTROL mount 증가 | 0 (menu only) |
| monitoring occurrence | 1 |
| duplicate href | 0 |
| User menu | unchanged |
| /admin/upbit | unchanged |
| Strategy workflow | 위치 유지 |

---

## DEFER

- M4-C LIVE/ARM single mount
- Admin top-level 11→9 강제 병합
- `/admin/risk` M4-A heading WIP 분리 커밋
- 주문·Outbox를 자동매매 운영으로 이중 노출
