# DECISION_LOG

장기적으로 유지할 설계·프로세스 결정만 기록한다.  
**최종 갱신:** 2026-07-31

---

## DEC-20260731-01 — AGENTS.md as AI Source of Truth

| | |
|--|--|
| **Date** | 2026-07-31 |
| **Context** | Cursor / Claude / 완료보고가 규칙을 각각 복제·충돌 |
| **Decision** | [AGENTS.md](../AGENTS.md)를 모든 AI 공통 최상위 SoT로 사용. CLAUDE.md·Cursor Rules는 포인터·짧은 게이트만 |
| **Consequence** | 공통 규칙 장문 복제 금지; 충돌 시 AGENTS 우선 |
| **Related** | CLAUDE.md, `.cursor/rules/00-project-core.mdc` |

---

## DEC-20260731-02 — STEP_MASTER_STATUS as STEP SoT

| | |
|--|--|
| **Date** | 2026-07-31 |
| **Context** | STEP8/10/11/12 숫자 네임스페이스 충돌 |
| **Decision** | [STEP_MASTER_STATUS.md](STEP_MASTER_STATUS.md)가 STEP 상태 SoT. 과거 번호는 Mapping만, 삭제·재부여 금지 |
| **Consequence** | Audit STEP12(Paper) ≠ Strategy STEP12. Canonical ID 병기 |
| **Related** | audit/STEP_NUMBER_MAPPING_20260731.md |

---

## DEC-20260731-03 — PROJECT_IMPLEMENTATION_STATUS as implementation SoT

| | |
|--|--|
| **Date** | 2026-07-31 |
| **Context** | 릴리즈 문서·감사·완료보고의 준비도 주장 불일치 |
| **Decision** | [PROJECT_IMPLEMENTATION_STATUS.md](PROJECT_IMPLEMENTATION_STATUS.md)가 구현 현황 SoT. 완료 ≠ Paper/LIVE 준비도 |
| **Consequence** | 추정치는 추정치로 표기. NOT READY / NOT APPROVED 유지까지 명시 |
| **Related** | ROADMAP.md, PHASE1 draft |

---

## DEC-20260731-04 — CURRENT_WORK is present-tense only

| | |
|--|--|
| **Date** | 2026-07-31 |
| **Context** | “현재 작업” 문서에 이력 누적 |
| **Decision** | [CURRENT_WORK.md](CURRENT_WORK.md)에는 **현재 작업·Gate·금지·P0**만 |
| **Consequence** | 이력은 CHANGELOG·완료보고·archive |
| **Related** | AGENTS.md §문서 |

---

## DEC-20260731-05 — Completion reports are Historical

| | |
|--|--|
| **Date** | 2026-07-31 |
| **Context** | PASS 완료보고가 실행 단절을 가림 |
| **Decision** | 완료보고는 SoT가 아님. 향후 `docs/archive/completion-reports/` |
| **Consequence** | PASS여도 소스 단절 시 자동매매 미완료 |
| **Related** | AGENTS.md Source of Truth 순서 |

---

## DEC-20260731-06 — User / Account / Strategy / Runtime Scope

| | |
|--|--|
| **Date** | 2026-07-31 (재확인) |
| **Context** | 다중 계좌·브로커 |
| **Decision** | `user_id` · UBA · Paper account · strategy ownership · scoped runtime 유지 유지 |
| **Consequence** | 전역 runtime/단일 계좌 가정 코드 금지 |
| **Related** | AI_CODING_RULE, DEV-8 docs |

---

## DEC-20260731-07 — LIVE default OFF and fail-closed

| | |
|--|--|
| **Date** | 2026-07-31 (재확인) |
| **Context** | 실거래 위험 |
| **Decision** | LIVE 기본 OFF; startup fail-closed; 실주문·Broker는 명시 승인 |
| **Consequence** | AI 자동 LIVE/주문 금지; P0 해소 전 NOT APPROVED |
| **Related** | AI_TRADING_SAFETY.md, 90-trading-safety.mdc |

---

## DEC-20260731-08 — Archive before delete

| | |
|--|--|
| **Date** | 2026-07-31 |
| **Context** | 문서 중복·루트 난립 |
| **Decision** | 삭제 전 Archive. PHASE 3에서 이동 계획; 무단 삭제 금지 |
| **Consequence** | Historical 링크 보존 |
| **Related** | documentation-structure.mdc |

---

## DEC-20260731-09 — STEP numbers mapped, not rewritten

| | |
|--|--|
| **Date** | 2026-07-31 |
| **Context** | 번호 충돌 |
| **Decision** | Historical ID 보존 + Canonical Mapping |
| **Consequence** | 문서·커밋에 Canonical ID 병기 |
| **Related** | STEP_MASTER_STATUS.md |

---

## DEC-20260731-10 — Source and tests over documents

| | |
|--|--|
| **Date** | 2026-07-31 |
| **Context** | 문서 드리프트 |
| **Decision** | SoT 우선순위: 소스 → Migration/Entity → 테스트 → 설정 → PHASE1 → Canonical → Historical |
| **Consequence** | 문서만으로 완료 금지 |
| **Related** | AGENTS.md |

---

## DEC-20260731-11 — PHASE 2 P0 ID freeze

| | |
|--|--|
| **Date** | 2026-07-31 |
| **Context** | PHASE1 remaining-work와 사용자 PHASE2 지시의 P0 번호 상이 |
| **Decision** | Canonical P0-1…P0-5는 PHASE2 지시(하드코딩/Fill/STEP12-Runtime/Alembic/Paper fill)로 고정 |
| **Consequence** | ROADMAP·모든 Canonical이 동일 ID 사용. PHASE1 remaining은 Historical |
| **Related** | ROADMAP.md |
