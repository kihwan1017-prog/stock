# CLAUDE.md — Claude Code Bootstrap

**공통 개발 규칙은 [AGENTS.md](AGENTS.md)에만 둔다.** 이 파일은 Claude Code의 읽기 순서·작업 게이트·보고 형식만 정의한다.

**최종 갱신:** 2026-07-31 (PHASE 2)

> `frontend/CLAUDE.md`는 `@AGENTS.md` 포인터로 유지한다. 루트 본 파일이 Claude 진입점이다.

---

## 1. 최상위 규칙

[AGENTS.md](AGENTS.md)가 Source of Truth다.  
충돌 시 AGENTS.md → CURRENT_WORK → IMPLEMENTATION_STATUS → STEP_MASTER 순.

---

## 2. 작업 전 필수 읽기 순서

1. [AGENTS.md](AGENTS.md)  
2. [docs/CURRENT_WORK.md](docs/CURRENT_WORK.md)  
3. [docs/PROJECT_IMPLEMENTATION_STATUS.md](docs/PROJECT_IMPLEMENTATION_STATUS.md)  
4. [docs/STEP_MASTER_STATUS.md](docs/STEP_MASTER_STATUS.md)  
5. 현재 작업 관련 상세 (`docs/ROADMAP.md`, `docs/AI_TRADING_SAFETY.md`, Architecture, 해당 STEP 문서)

큰 작업은 위 문서를 건너뛰고 구현을 시작하지 않는다.

---

## 3. 작업 순서 (Gate)

```text
Audit → Plan → Implementation → Migration → Tests → Docs Update → Completion Report → User Approval
```

- Audit: 실제 소스·테스트·Migration 확인 (문서만으로 완료 금지)
- Plan: 범위·금지·P0·커밋/워킹트리 구분
- Implementation: 승인된 범위만
- Docs: CURRENT_WORK / IMPLEMENTATION_STATUS / STEP_MASTER / ROADMAP 갱신
- User Approval 전: commit/push, LIVE, Archive 이동 금지 (지시 없는 경우)

---

## 4. 백그라운드·권한

- 장시간 작업은 결과 파일을 확인한 뒤 완료를 주장한다.
- 권한 승인 프롬프트가 나와도 Broker/주문/LIVE/파괴적 git을 **임의로 확대 해석하지 않는다**.
- “dangerously skip permissions” 환경에서도 AGENTS 금지 목록을 지킨다.

---

## 5. 실행 금지 (기본)

승인 문구 없이:

- Broker 로그인·실 API·주문·취소·정정
- Runtime/Scheduler 기동으로 실거래 유발
- 실계좌 잔고/포지션 조회를 검증 목적 외로 수행
- Migration upgrade/downgrade (사용자가 명시한 경우만)
- git commit / push

---

## 6. 완료 판단

- 소스에 호출 경로가 없으면 미구현
- 워킹트리만 있으면 `WORKTREE_IMPLEMENTED_UNCOMMITTED` — 배포 완료 금지
- Paper/LIVE/Kiwoom/Upbit를 섞어 한 문장으로 “자동매매 완료” 금지
- P0가 남아 있으면 LIVE NOT APPROVED 유지

---

## 7. 완료보고 최소 양식

```text
# 완료보고
## 최종 판정
## 범위 준수 (소스/문서/Broker/Git)
## 변경 파일
## 테스트 결과 (실행한 것만)
## Canonical 문서 갱신 여부
## P0 / 잔여 리스크
## 다음 권장 작업
```

---

## 8. 관련 링크

- [docs/AI_DEVELOPMENT_WORKFLOW.md](docs/AI_DEVELOPMENT_WORKFLOW.md)
- [docs/AI_TRADING_SAFETY.md](docs/AI_TRADING_SAFETY.md)
- [docs/audit/PHASE2_DOCUMENTATION_STANDARDIZATION_REPORT_20260731.md](docs/audit/PHASE2_DOCUMENTATION_STANDARDIZATION_REPORT_20260731.md)
