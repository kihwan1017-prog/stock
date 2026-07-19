# Documentation Refactoring Report

## 기존 문서 수

129 (refactor 시작 시점 Markdown, node_modules 등 제외)

## 최종 문서 수

139 (도메인 README·인벤토리·obsolete 안내·migration-overlays stub README 추가; **삭제 0**)

## 이동한 문서

| From | To |
|------|-----|
| `docs/ARCHITECTURE.md` | `docs/architecture/ARCHITECTURE.md` |
| `docs/development/DOMAIN_PACKAGE_MAP.md` | `docs/architecture/DOMAIN_PACKAGE_MAP.md` |
| `docs/API.md` | `docs/backend/API.md` |
| `docs/INSTALL.md`, `CONFIGURATION.md`, `RELEASE_CHECKLIST.md` | `docs/deployment/` |
| Ops/trading set | `docs/trading/` |
| ERD + DB rules + Alembic + Legacy | `docs/database/` |
| `docs/migration-overlays/README.md` | `docs/database/MIGRATION_OVERLAYS.md` |
| `docs/roadmaps/*` | `docs/reference/` |
| `docs/archive/step34-apply/*` | `docs/archive/obsolete/step34-apply/` |

## 새로 만든 README

- `docs/README.md` (재작성)
- `docs/architecture/README.md`
- `docs/backend/README.md`
- `docs/frontend/README.md`
- `docs/database/README.md`
- `docs/deployment/README.md`
- `docs/development/README.md` (갱신)
- `docs/trading/README.md`
- `docs/ai/README.md`
- `docs/reference/README.md`
- `docs/archive/README.md` (갱신)
- `docs/archive/obsolete/README.md`
- `docs/archive/steps/README.md` (STEP01–99 catalog)
- `docs/archive/obsolete/step34-apply/README.md` (갱신)
- `docs/migration-overlays/README.md` (포인터 stub)
- `docs/reference/DOCUMENT_INVENTORY.md`

## 수정한 링크

- Root `README.md` → deployment/trading/database/architecture/reference paths
- `frontend/README.md` → `docs/reference/STEP41_*`
- `docs/database/DB_DEVELOPMENT_RULES.md`, `MIGRATION_OVERLAYS.md`
- `docs/reference/STEP35_TO_STEP40_DEVELOPMENT_ROADMAP.md`
- `docs/development/STEP35_TEST_SUMMARY.md`
- Obsolete apply guide banners
- Relative link scan: **0 broken** after fixes

## Archive한 문서

- 기존 `docs/archive/steps/README_STEP*` (유지)
- `docs/archive/notes/*` (유지)
- `docs/archive/obsolete/step34-apply/*` (STEP34 번호형 가이드)

## 삭제한 문서

없음 (승인된 삭제 없음). 빈 `docs/roadmaps/` 디렉터리만 제거(파일 없음).

## 남은 개선사항

- `DOCUMENT_INVENTORY.md` Refs out/in 컬럼은 요약값 — 필요 시 링크 그래프 자동 생성
- AI 전용 심화 문서 본문(STEP42+)
- Agent 문서(`AGENTS.md` 등)는 의도적으로 docs 밖 유지
- Uncommitted: `frontend/.../LoginForm.tsx` (Alert 제거, 문서 리팩터와 무관)

## 현재 문서 구조

```text
docs/
├── README.md
├── architecture/
├── backend/
├── frontend/
├── database/
├── deployment/
├── development/
├── trading/
├── ai/
├── reference/          # inventory + roadmaps
├── migration-overlays/ # .py drafts + stub README
└── archive/
    ├── README.md
    ├── steps/          # README_STEP* only + STEP01-99 catalog
    ├── notes/
    └── obsolete/
        └── step34-apply/
```

## Git commits (this refactor)

1. `6d1c7c6` docs: add DOCUMENT_INVENTORY…
2. `00f4fab` docs: move current docs into domain folders
3. `ca03bce` docs: add domain folder README indexes
4. `b8d0c05` docs: reorganize archive with obsolete and STEP01-99 catalog
5. `cea0810` docs: fix markdown links…
6. `31bff41` docs: turn root README into documentation portal
7. `55d3a5b` docs: refresh CHANGELOG…
8. (this) docs: add refactoring report and overlay stub README
