# AGENTS.md — Stock Platform Source of Truth

이 파일은 Cursor, Claude Code, Codex 등 **모든 AI 도구가 따르는 최상위 규칙**이다.  
공통 규칙을 다른 문서에 장문 복제하지 말고, 여기서 링크한다.

**최종 갱신:** 2026-07-31 (PHASE 2 Documentation Standardization)

---

## 1. 프로젝트 목적

Kiki Trade AI (`stock-platform`)는 KRX(키움)와 Upbit(암호화폐)를 대상으로 하는  
시세·후보·전략 수명주기·리스크·주문·브로커 연동 플랫폼이다.

현재 상태 (PHASE 1 감사 추정치 — **완료 판정 아님**):

| 지표 | 추정치 |
|------|--------|
| 개발 구현률 | ~76% |
| Paper 자동매매 준비도 | ~72% |
| LIVE 자동매매 준비도 | ~48% |
| 운영 가능 | **NOT READY** |
| LIVE 거래 | **NOT APPROVED** |
| Paper 무인 자동매매 | **NOT READY** |

상세 SoT: [docs/PROJECT_IMPLEMENTATION_STATUS.md](docs/PROJECT_IMPLEMENTATION_STATUS.md)

---

## 2. 기술 스택

- Backend: Python 3.12, FastAPI (`src/stock_platform/`)
- Frontend: Next.js App Router (`frontend/`)
- DB: PostgreSQL + Alembic (`database/alembic/` — **유일한** migration 체인)
- Broker: Kiwoom REST, Upbit, Paper
- AI: Provider 추상화 (Mock 기본)

---

## 3. Source of Truth 우선순위

충돌 시 아래 순서를 따른다.

1. 실제 실행 경로의 소스 코드
2. Alembic Migration + SQLAlchemy Entity
3. 실행 가능한 테스트
4. 환경 설정·운영 스크립트
5. PHASE 1 감사 (`docs/audit/*_20260731.md`)
6. **Canonical 문서** (이 파일 + `docs/` SoT)
7. 과거 STEP 완료보고 / Historical 문서

완료보고에 PASS가 있어도 실행 흐름이 단절되면 자동매매 완료로 판정하지 않는다.

---

## 4. 작업 시작 전 읽을 문서

1. [AGENTS.md](AGENTS.md) (본 파일)
2. [docs/CURRENT_WORK.md](docs/CURRENT_WORK.md)
3. [docs/PROJECT_IMPLEMENTATION_STATUS.md](docs/PROJECT_IMPLEMENTATION_STATUS.md)
4. [docs/STEP_MASTER_STATUS.md](docs/STEP_MASTER_STATUS.md)
5. 작업 관련: [docs/ROADMAP.md](docs/ROADMAP.md), [docs/AI_TRADING_SAFETY.md](docs/AI_TRADING_SAFETY.md), 도메인 상세

Claude Code는 [CLAUDE.md](CLAUDE.md)의 읽기 순서를 따른다.  
Cursor는 `.cursor/rules/*.mdc`를 따르되 **본 파일을 우선**한다.

---

## 5. Canonical 문서 맵

| 문서 | 역할 |
|------|------|
| [docs/CURRENT_WORK.md](docs/CURRENT_WORK.md) | **현재 작업만** |
| [docs/PROJECT_IMPLEMENTATION_STATUS.md](docs/PROJECT_IMPLEMENTATION_STATUS.md) | 구현 현황 SoT |
| [docs/STEP_MASTER_STATUS.md](docs/STEP_MASTER_STATUS.md) | STEP 상태 SoT |
| [docs/ROADMAP.md](docs/ROADMAP.md) | P0–P5 잔여 작업 |
| [docs/DECISION_LOG.md](docs/DECISION_LOG.md) | 장기 설계 결정 |
| [docs/AI_*.md](docs/AI_PROJECT_CONTEXT.md) | AI 상세 규칙 |
| [docs/architecture/STRATEGY_LIFECYCLE_STEP12.md](docs/architecture/STRATEGY_LIFECYCLE_STEP12.md) | Strategy STEP12 |

완료보고는 SoT가 아니다. 보관 경로(예정): `docs/archive/completion-reports/`

---

## 6. 단계별 Gate

1. Audit / 현황 확인  
2. Plan (범위·금지·P0)  
3. Implementation  
4. Migration (필요 시, 단일 head)  
5. Backend / Frontend / Integration 테스트  
6. Documentation 갱신 (아래 §11)  
7. Completion Report  
8. **User Approval** 후에만 commit/push·LIVE·Archive

Gate를 건너뛰지 않는다.

---

## 7. 디렉터리 개요

```text
src/stock_platform/   # FastAPI domains
frontend/             # Next.js ADMIN/USER
database/alembic/     # Canonical migrations only
tests/                # pytest
docs/                 # Canonical + domain docs
ops/                  # Windows ops scripts
alembic/versions/     # DEPRECATED — 적용 금지
```

---

## 8. Backend / Frontend / DB 기본 규칙

상세: [docs/AI_CODING_RULE.md](docs/AI_CODING_RULE.md), [docs/AI_DB_RULE.md](docs/AI_DB_RULE.md), Cursor `10/20/30-*.mdc`

- Router는 HTTP, Service는 비즈니스, Session 소유권을 명확히
- USER/ADMIN·`user_id`·UBA(`user_broker_account_id`)·Paper `account_id` Scope 유지
- Frontend는 Backend 미구현 API를 완료처럼 호출하지 않음 (Stub 표시)
- Alembic **단일 Head**; Entity↔Migration 일치; 루트 `alembic/versions` 적용 금지

---

## 9. 테스트 기본 규칙

상세: [docs/AI_TEST_RULE.md](docs/AI_TEST_RULE.md)

- 기본: `pytest -m "not external and not live and not live_ai"`
- SQLite만으로 DB 완료 판단 금지
- 실제 Broker 호출·실계좌 테스트는 명시 승인 없이 금지
- 테스트 증거 없는 완료 판정 금지

---

## 10. 자동매매 안전 규칙 (요약)

상세: [docs/AI_TRADING_SAFETY.md](docs/AI_TRADING_SAFETY.md), Cursor `90-trading-safety.mdc`

- LIVE 기본 **OFF**, startup **fail-closed**
- Broker 로그인/주문/Runtime/Scheduler 자동 실행 금지 (명시 승인 필요)
- Kill Switch · Account Pause · 한도 존중
- LIVE/PAPER 데이터·설정 분리
- 민감정보(시크릿·키·토큰) 출력 금지

### P0 Blocking (2026-07-31 — 모든 Canonical에 동일)

| ID | 내용 |
|----|------|
| **P0-1** | Realtime 실행 경로 `broker_code="KIWOOM"` 하드코딩 |
| **P0-2** | Kiwoom Fill → TradingOrder → Position/Balance/P&L 단절 |
| **P0-3** | STEP12 Registry/Deployment 상태 ↔ Scoped Runtime 실행 상태 불일치·자동 연결 부재 |
| **P0-4** | Git 커밋 Alembic Head ↔ 워킹트리 Head 불일치 |
| **P0-5** | Paper Outbox ACCEPTED 이후 `PaperExecutionService` 자동 Fill 부재 |

---

## 11. 문서 관리 규칙

STEP/기능 완료 시 **필수 갱신**:

1. `docs/CURRENT_WORK.md`  
2. `docs/PROJECT_IMPLEMENTATION_STATUS.md`  
3. `docs/STEP_MASTER_STATUS.md`  
4. `docs/ROADMAP.md`  

필요 시: `DECISION_LOG.md`, Architecture/API/Operations.

- 제품 how-to는 루트에 새로 만들지 말고 `docs/<domain>/` ([documentation-structure](.cursor/rules/documentation-structure.mdc))
- 삭제 전 Archive 우선; 사용자 승인 없는 삭제 금지
- STEP 번호 네임스페이스 혼용 금지 — [STEP_MASTER_STATUS.md](docs/STEP_MASTER_STATUS.md)

### 워킹트리 상태 표기

| 상태 | 의미 |
|------|------|
| COMMITTED_BASELINE | `3554ef8` 등 커밋에 포함 |
| WORKTREE_IMPLEMENTED_UNCOMMITTED | 워킹트리만 |
| VERIFIED_BY_TEST | 테스트 증거 |
| PARTIALLY_VERIFIED / DOCUMENTED_ONLY / NOT_IMPLEMENTED | 그 외 |

워킹트리만의 기능을 배포·운영 완료로 쓰지 않는다.

---

## 12. Git 안전 규칙

- 사용자 요청 없이 commit/push/force/amend 금지
- Secret·`.env` 커밋 금지
- Migration head 확인 후 커밋
- destructive git 명령 금지

---

## 13. 금지 작업 (기본)

승인 없이:

- 실 Broker API / 실계좌 조회 / 주문 생성·전송·취소·정정
- LIVE 활성화, Runtime/Scheduler 무단 기동
- DB 데이터 파괴, Migration rewrite
- 문서/코드 대량 삭제, history rewrite

---

## 14. 완료보고 규칙

완료보고는 Historical이다. Canonical 수치·STEP 상태는 SoT 문서를 갱신한 뒤에만 “완료”를 주장한다.  
형식은 작업지시서·[CLAUDE.md](CLAUDE.md)를 따른다.

---

## 15. Agent Workspace (persona continuity)

아래는 OpenClaw/세션 연속성용이다. **프로젝트 개발 규칙과 충돌하면 §1–14가 우선한다.**

### Session Startup

런타임이 제공한 `AGENTS.md` / `SOUL.md` / `USER.md` / daily memory를 우선 사용한다.  
불필요하게 재읽지 않는다.

### Memory

- Daily: `memory/YYYY-MM-DD.md`
- Long-term: `MEMORY.md` (메인 세션만; 공유 채널에 유출 금지)
- “기억해줘” → 파일에 기록

### Red Lines (persona)

- 사적 데이터 유출 금지
- 파괴적 명령은 묻기
- `trash` > `rm`
- 그룹 채팅에서 대리 발화 금지

### Documentation structure (project)

- 신규 제품 MD: `docs/<domain>/` only (루트 예외: README/CHANGELOG/PROJECT_STATUS/AGENTS 등 portal)
- Canonical map: [docs/README.md](docs/README.md)

### Related

- [Default AGENTS.md](/reference/AGENTS.default) (upstream template)
