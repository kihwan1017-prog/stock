# v1.0 Release Candidate Validation Report

**STEP:** 8-5-20  
**일자:** 2026-07-26  
**프로젝트:** `D:\Projects\stock-platform`  
**운영 데이터:** `E:\StockTrading`  
**Alembic Head:** `h1b2c3d4e5f6`

---

## 1. 시스템 개요

주식(키움)·업비트·Paper 자동매매를 단일 FastAPI + PostgreSQL + Next.js 스택으로 운영한다.  
내부 계좌 식별은 LIVE=`user_broker_account_id`(UBA), Paper=`paper_account_id`이다.  
실주문은 기본 비활성(Fail Closed)이며, Health CRITICAL 시 LIVE 신규 주문을 차단한다.

---

## 2. 검증 범위

| 영역 | 결과 |
|------|------|
| 키움 / 업비트 / Paper 흐름 (코드·테스트 연결) | PASS (통합 자동화 중심) |
| 계좌 격리 | PASS |
| broker_pending_order UBA 전환 | PASS (Migration `h1b2c3d4e5f6`) |
| Snapshot UBA ACTIVE Partial Unique | PASS (변경 없음·안전) |
| 주문 상태 머신 | PASS (테스트·코드) |
| Risk / Kill Switch Fail Closed | PASS |
| Settlement / Recovery / Scheduler | PASS (기존 STEP 회귀) |
| Health CRITICAL → LIVE 차단 | PASS |
| 보안 (소유권·마스킹·LIVE 기본값) | PASS (Critical 신규 0, Known Critical 잔존은 VPN 전제) |
| 운영 경로·env 분리 | PASS (경로 존재·프로젝트 `.env` 없음) |
| 백업/복구 스크립트 | PASS (스크립트·경로) / 실복구는 권한·파괴 위험으로 절차 문서화 |
| 빈 DB 전체 upgrade | **PARTIAL** (CREATE DATABASE 권한 없음) |
| Backend / Frontend 테스트 | PASS |

---

## 3. 테스트 결과

### Backend

- `pytest` 전체: **832 passed / 0 failed / 0 skipped**
- Warning: Starlette `httpx` TestClient deprecation 1건 (의존성)
- 핵심 스위트 3회 반복: account identity / settlement / snapshot / recovery lock / upbit idempotency / RC smoke — **ALL_OK**

### Frontend

- Vitest: **98 passed** (39 files)
- TypeScript (`tsc --noEmit`): PASS
- ESLint (`--max-warnings=0`): PASS
- Production Build: PASS

---

## 4. 보안 결과

- LIVE 기본: `KIWOOM_USE_MOCK=true`(설정 기본), `KIWOOM_LIVE_ORDER_ENABLED=false`, `UPBIT_LIVE_ORDER_ENABLED=false`, `GLOBAL_LIVE_ORDER_ENABLED=false`
- UBA/Paper/Order 소유권 검사 및 account masking 유지
- pending 저장: `account_number` 내부 토큰 `UBA:{id}`, `masked_account_ref` 사용
- Known Critical (`KI-SEC-10`~`15`, Outbox Live 등): **공개망·고객 Live 전 Blocker**로 유지. VPN/LIVE-OFF 전제 RC와 분리

---

## 5. 성능 결과

운영을 막는 성능 결함은 본 STEP에서 발견하지 않았다.  
과도한 최적화는 수행하지 않았다. (KI-PERF-*는 Medium Technical Debt)

---

## 6. 장애 복구 결과

- Unified Recovery + Kiwoom adapter: pending sync **UBA 필수**
- Claim/Lease/Fencing·Ambiguous Resolver·EOD Settlement 회귀 테스트 PASS
- 레거시 `BrokerRecoveryService` account_number-only pending sync는 Fail Closed

---

## 7. 백업/복구 결과

| 항목 | 결과 |
|------|------|
| `ops/backup_db.*` / `ops/restore_db.*` | 존재·문서화 |
| `E:\StockTrading\backups` | 경로 존재 |
| 운영 DB `upgrade`/`downgrade g0`/`upgrade` | PASS → Head `h1b2c3d4e5f6` |
| 빈 DB CREATE + 전체 upgrade | **미완** (DB 역할에 CREATE DATABASE 권한 없음) |
| 실서비스 파괴적 restore | 미실행 (운영 보호) — 절차는 `docs/operations/BACKUP_RESTORE_VERIFICATION.md` |

---

## 8. Migration 결과

- Single head: `h1b2c3d4e5f6`
- Revises: `g0a1b2c3d4e5`
- 내용: `broker_pending_order.user_broker_account_id` NOT NULL + FK RESTRICT, Unique `(broker_code, uba, broker_order_id)`, `masked_account_ref`
- 운영 DB down/up 검증 PASS

---

## 9. Known Issues (본 STEP 확정)

| 항목 | 등급 |
|------|------|
| 공개망 무인증 mutate·Telegram secret·Outbox Live (`KI-SEC-*`, `KI-TRD-*`) | Release Blocker (**고객 Live/공개망**) / VPN+LIVE-OFF 시 운영 허용 |
| 빈 DB 전체 Migration / 실 Restore 권한 검증 미완 | High |
| Snapshot 레거시 `(broker, account_number)` Unique 잔존 | Medium (v1.1) |
| Position Limit Admin UI 부재 | Medium (v1.1) — API만으로 RC 충분 |
| broker_pending_order account_number 내부식별 | **해소** (`h1b2c3d4e5f6`) |
| Dual alembic overlay (`KI-DB-02`) | Medium |
| Playwright E2E 미자동화 | Low |

---

## 10. Technical Debt (v1.1+)

- Position Limit 관리 UI
- Snapshot 레거시 Unique 정리
- Outbox → Live Broker factory
- 무인증 mutate 엔드포인트 Admin 강제
- FE Admin Health 전용 화면 (현재 Monitoring/Operations)

---

## 11. 운영 승인 여부

| 모드 | 판정 |
|------|------|
| Paper / LIVE-OFF / VPN·내부망 | **조건부 RC 승인 (GO CONDITIONAL)** — **단, 현재 로드된 운영 env는 LIVE 안전 모드 위반** |
| 공개망 고객 Live | **NO-GO** (Known Critical 잔존) |
| 소액 LIVE 테스트 | **조건부** — Kill Switch·LIVE 체크리스트·Vault 확인 후 Admin 명시 활성화만 |

**코드 기본값:** LIVE OFF / Mock ON — PASS  
**Broker factory:** `GLOBAL_LIVE_ORDER_ENABLED=false` 이면 실주문 어댑터 차단 — 현재 운영 env에서도 전역 게이트는 OFF  
**현재 운영 env 로드 (2026-07-26):** `KIWOOM_USE_MOCK=false`, `KIWOOM_LIVE_ORDER_ENABLED=true`, `GLOBAL_LIVE_ORDER_ENABLED=false`  
→ 체크리스트상 `KIWOOM_LIVE_ORDER_ENABLED=false` 미충족(High). 전역 게이트로 실전송은 막혀 있으나 RC 운영 승인 전 env를 안전 기본값으로 정렬할 것.

**STEP 8-5-21 갱신:** 운영 env 안전값 정렬·Activation 만료·Telegram Fail Closed·Backup 실측 완료.  
소액 LIVE는 Official Restore PASS·DB Release Blocker 0 기준으로 **APPROVED** (로컬/VPN). 공개망은 범위 제외. 상세: [V1_0_RC_FINAL_APPROVAL.md](V1_0_RC_FINAL_APPROVAL.md)
