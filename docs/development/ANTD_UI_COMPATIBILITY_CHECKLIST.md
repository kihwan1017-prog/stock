# Ant Design / Admin UI 호환성 체크리스트

Next 16 + antd 6 기준. 패키지 임의 업그레이드 금지 — **현재 설치 버전**에 맞춘다.

## 규칙

1. **Alert**: `title` 사용. `message` 금지 (antd 6 deprecated).
2. **Table**: `import { Table } from "antd"` named import만. default import 금지.
3. **query.data / asRecord**: nullable. `asRecord(x).foo` 직접 접근 금지 → `asRecord(x)?.foo` 또는 `asRecordOrEmpty` (LOADING/EMPTY/ERROR 분기 후).
4. **loading / empty / error** UI를 구분. 빈 `{}`로 의미를 숨기지 말 것.
5. **deprecated antd API** 금지: `Tabs.TabPane`, `Collapse.Panel`, `Dropdown overlay`, `bodyStyle`, `maskStyle`, `destroyOnClose`.
6. 신규 Admin 컴포넌트는 console smoke (`src/test/consoleSmoke.ts`) 포함.
7. UI commit 전:
   - `npm run check:antd-compat`
   - `npm run lint:antd-compat` (또는 전체 `npm run lint`)
   - `npm run typecheck` (unrelated known error는 분리 보고)
   - `npm run test:ui:focused`
   - `npm run check:frontend` (통합 게이트)

## 참고

- 설치 SoT: `frontend/package.json` / lockfile
- ESLint: `frontend/eslint.config.mjs` (antd compat restrictions)
