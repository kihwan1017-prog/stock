# Ant Design / Admin UI 호환성 체크리스트

Next 16 + antd 6 기준. 패키지 임의 업그레이드 금지 — **현재 설치 버전**에 맞춘다.

## 규칙

1. **Alert**: `title` 사용. `message` 금지 (antd 6 deprecated).
2. **Statistic**: `styles.content` 사용. `valueStyle` 금지 (antd 6 deprecated).
3. **Table**: `import { Table } from "antd"` named import만. default import 금지.
4. **query.data / asRecord**: nullable. `asRecord(x).foo` 직접 접근 금지 → `asRecord(x)?.foo` 또는 `asRecordOrEmpty` (LOADING/EMPTY/ERROR 분기 후).
5. **loading / empty / error** UI를 구분. 빈 `{}`로 의미를 숨기지 말 것.
6. **deprecated antd API** 금지: `Tabs.TabPane`, `Collapse.Panel`, `Dropdown overlay`, `bodyStyle`, `maskStyle`, `destroyOnClose`.
7. 신규 Admin 컴포넌트는 console smoke (`src/test/consoleSmoke.ts`) 포함.
8. UI commit 전:
   - `npm run check:frontend` (= antd-compat + **full lint** + **full typecheck** + focused vitest)
   - 필요 시 개별: `check:antd-compat` / `lint` / `typecheck` / `test:ui:focused`

## 참고

- 설치 SoT: `frontend/package.json` / lockfile
- ESLint: `frontend/eslint.config.mjs` (antd compat restrictions)
