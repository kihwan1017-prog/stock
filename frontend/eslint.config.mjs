import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

/** antd 6.x 실제 deprecated / 금지 패턴 (suppress 금지 · 교체 강제) */
const antdCompatRestrictions = {
  "no-restricted-syntax": [
    "error",
    {
      selector:
        "JSXOpeningElement[name.name='Alert'] > JSXAttribute[name.name='message']",
      message:
        "antd Alert: deprecated `message` — use `title` instead (antd 6).",
    },
    {
      selector:
        "JSXMemberExpression[object.name='Tabs'][property.name='TabPane']",
      message: "antd Tabs: TabPane is deprecated — use `items` prop.",
    },
    {
      selector:
        "JSXMemberExpression[object.name='Collapse'][property.name='Panel']",
      message: "antd Collapse: Panel is deprecated — use `items` prop.",
    },
    {
      selector:
        "JSXOpeningElement[name.name='Dropdown'] > JSXAttribute[name.name='overlay']",
      message: "antd Dropdown: deprecated `overlay` — use `menu` instead.",
    },
    {
      selector:
        "JSXAttribute[name.name='destroyOnClose']",
      message:
        "antd Modal/Drawer: deprecated `destroyOnClose` — use `destroyOnHidden`.",
    },
    {
      selector: "JSXAttribute[name.name='bodyStyle']",
      message: "antd: deprecated `bodyStyle` — use `styles={{ body: ... }}`.",
    },
    {
      selector: "JSXAttribute[name.name='maskStyle']",
      message: "antd: deprecated `maskStyle` — use `styles={{ mask: ... }}`.",
    },
    {
      selector:
        "JSXOpeningElement[name.name='Statistic'] > JSXAttribute[name.name='valueStyle']",
      message:
        "antd Statistic: deprecated `valueStyle` — use `styles={{ content: ... }}` (antd 6).",
    },
    {
      selector:
        "JSXOpeningElement[name.name='Drawer'] > JSXAttribute[name.name='width']",
      message:
        "antd Drawer: deprecated `width` — use `size` instead (antd 6).",
    },
    {
      selector:
        "JSXOpeningElement[name.name='Drawer'] > JSXAttribute[name.name='height']",
      message:
        "antd Drawer: deprecated `height` — use `size` instead (antd 6).",
    },
    {
      selector:
        "ImportDeclaration[source.value='antd'] > ImportDefaultSpecifier",
      message:
        "antd: default import 금지 — named import만 사용 (예: import { Table } from 'antd').",
    },
  ],
};

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: ["src/**/*.{ts,tsx}"],
    rules: antdCompatRestrictions,
  },
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "scripts/**",
  ]),
]);

export default eslintConfig;
