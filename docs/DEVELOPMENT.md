# Development

개발 Gate·규칙 진입점. 상세는 AI_* 문서와 AGENTS.md.

## 읽기 순서

1. [../AGENTS.md](../AGENTS.md)
2. [CURRENT_WORK.md](CURRENT_WORK.md)
3. [PROJECT_IMPLEMENTATION_STATUS.md](PROJECT_IMPLEMENTATION_STATUS.md)
4. [STEP_MASTER_STATUS.md](STEP_MASTER_STATUS.md)
5. [AI_DEVELOPMENT_WORKFLOW.md](AI_DEVELOPMENT_WORKFLOW.md)

## Work History SoT

상세 WRK 이력의 canonical SoT는 DB:

`operation.ai_development_work_history`

WRK마다 root Markdown 완료보고를 만들지 않는다. Evidence는 `.run/` JSON(필요 시 md 1개).

## DOCUMENTATION POLICY

1. WRK마다 root `.md` 생성 금지.
2. 상세 개발 이력 → `operation.ai_development_work_history`.
3. runtime/evidence → `.run/` (소스 문서와 구분).
4. 영구 문서는 기존 `docs/*.md` / domain folder를 **우선 수정**.
5. 새 docs 파일은 기존 canonical로 표현 불가할 때만 생성.
6. 일회성 AUDIT/VERIFY/RESULT/REPORT는 root에 영구 보관하지 않음 → `docs/archive/`.
7. CHANGELOG에는 사용자 영향 milestone만.
8. 소스 설명을 별도 md로 반복 생성하지 않음.
9. Cursor 작업 완료보고를 repository root md로 자동 생성하지 않음.
10. Evidence JSON/MD ≠ product documentation.
11. Git history가 보존되면 historical duplication을 root에 유지하지 않음.
12. Before creating a new Markdown file: existing canonical 갱신 가능 여부 확인.

## 기타 규칙

- Migration: `database/alembic/` only · multi-head 주의 · rewrite 금지
- Test: `pytest -m "not external and not live and not live_ai"` 기본
- REAL BUY/SELL/CANCEL · LIVE/ARM 무단 변경 금지
- Restart: [OPERATIONS.md](OPERATIONS.md)

상세: [AI_CODING_RULE.md](AI_CODING_RULE.md) · [AI_TEST_RULE.md](AI_TEST_RULE.md) · [AI_DB_RULE.md](AI_DB_RULE.md) · [AI_TRADING_SAFETY.md](AI_TRADING_SAFETY.md)
