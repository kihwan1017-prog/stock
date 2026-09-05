# Ant Design / Admin UI 호환성 체크리스트

Next 16 + antd 6 기준. 패키지 임의 업그레이드 금지 — **현재 설치 버전**에 맞춘다.

## 규칙

1. **Alert**: `title` 사용. `message` 금지 (antd 6 deprecated).
2. **Statistic**: `styles.content` 사용. `valueStyle` 금지 (antd 6 deprecated).
3. **Drawer**: `size` 사용. `width` / `height` 금지 (antd 6 deprecated). Recharts `width`와 혼동 금지.
4. **Table**: `import { Table } from "antd"` named import만. default import 금지.
5. **query.data / asRecord**: nullable. `asRecord(x).foo` 직접 접근 금지 → `asRecord(x)?.foo` 또는 `asRecordOrEmpty` (LOADING/EMPTY/ERROR 분기 후).
6. **loading / empty / error** UI를 구분. 빈 `{}`로 의미를 숨기지 말 것.
7. **deprecated antd API** 금지: `Tabs.TabPane`, `Collapse.Panel`, `Dropdown overlay`, `bodyStyle`, `maskStyle`, `destroyOnClose`.
8. **Tooltip collision**: Ant Design `Tooltip`과 Recharts `Tooltip`을 같은 파일에서 쓰면 Recharts는 `Tooltip as ChartTooltip`로 alias.
9. 신규 Admin 컴포넌트는 console smoke (`src/test/consoleSmoke.ts`) 포함.
10. UI 변경 완료 Gate (PASS 전 보고 금지):
    - `npm run check:frontend:gate`
      (= `check:antd-compat` + `typecheck` + focused vitest + **production `build`**)
    - 개발 중 빠른 검사: `npm run check:frontend` (lint 포함, build 제외)
    - PASS 기준: NEW TS error=0 · NEW AntD deprecation warning=0 · related vitest PASS · production build PASS
    - 변경 화면(`/admin/dashboard`, `/admin/autotrading/upbit` 등) console error/warn = 0

## 참고

- 설치 SoT: `frontend/package.json` / lockfile
- ESLint: `frontend/eslint.config.mjs` (antd compat restrictions)
- Static gate: `frontend/scripts/check-antd-compat.mjs` (Drawer는 `<Drawer>` 블록만 검사)
