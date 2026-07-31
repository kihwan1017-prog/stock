# AI_PROJECT_CONTEXT

AI 작업용 프로젝트 컨텍스트. 장문 규칙은 [AGENTS.md](../AGENTS.md)를 본다.  
**최종 갱신:** 2026-07-31

---

## 목표

KRX(키움)·Upbit·Paper를 아우르는 시세·후보·전략 수명주기·리스크·주문·정산 플랫폼 (Kiki Trade AI).

## 통합 범위

- **KRX:** 일봉/캘린더/주문·Recovery — 실시간 시세는 제한(갭)
- **Upbit:** WS 시세·주문·Fill sync 상대적 강함
- **Paper:** Stock/Crypto 모의 — Outbox 후 자동 Fill 갭(P0-5)

## 역할

- **USER:** 본인 계좌·전략·요청 범위
- **ADMIN:** 플랫폼 운영·승인·UBA 관리

## 계좌 종류

- Live UBA (`user_broker_account_id`) — Kiwoom / Upbit
- Paper account — LIVE와 분리

## 주요 기술

Python 3.12 · FastAPI · Next.js · PostgreSQL · Alembic(`database/alembic`) · Outbox · Scoped Runtime · Kill Switch

## 주요 경로

| 영역 | 경로 |
|------|------|
| API entry | `src/stock_platform/api/main.py` → `lifecycle.py` |
| Router | `src/stock_platform/api/` |
| Domains | `src/stock_platform/{ai,order,risk,trading,backtest,…}/` |
| Frontend | `frontend/src/app/(admin|user)/` |
| Migrations | `database/alembic/versions/` |
| Tests | `tests/test_step*.py` |

## 현재 개발 상태 (추정)

- 구현률 ~**76%** · Paper ~**72%** · LIVE ~**48%**
- Commit baseline: `3554ef8` (STEP11). STEP12는 워킹트리 미커밋 가능.

## 운영 준비 경고

**NOT READY** · LIVE **NOT APPROVED** · Paper 무인 **NOT READY**  
P0: [ROADMAP.md](ROADMAP.md) · 현황: [PROJECT_IMPLEMENTATION_STATUS.md](PROJECT_IMPLEMENTATION_STATUS.md)
