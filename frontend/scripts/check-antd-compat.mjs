#!/usr/bin/env node
/**
 * Static antd-compat gate — CI/pre-commit용 빠른 검사.
 * ESLint와 중복이지만 lockfile 없이 즉시 실패할 수 있게 유지.
 *
 * Drawer width/height 탐지는 Ant Design <Drawer ...> 블록만 대상으로 하여
 * Recharts / ResponsiveContainer 등의 width 오탐을 피한다.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "src");

function walk(dir, out = []) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ent.name === "node_modules" || ent.name === ".next") continue;
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) walk(p, out);
    else if (/\.(tsx|ts)$/.test(ent.name)) out.push(p);
  }
  return out;
}

/** JSX 시작 태그에서 매칭 닫는 '>'까지 (nested JSX 태그 제외한 속성 구간) */
function matchJsxOpenTags(text, tagName) {
  const re = new RegExp(`<${tagName}\\b`, "g");
  const blocks = [];
  let m;
  while ((m = re.exec(text)) !== null) {
    const start = m.index;
    let i = start + m[0].length;
    let quote = null;
    while (i < text.length) {
      const ch = text[i];
      if (quote) {
        if (ch === quote && text[i - 1] !== "\\") quote = null;
        i += 1;
        continue;
      }
      if (ch === '"' || ch === "'" || ch === "`") {
        quote = ch;
        i += 1;
        continue;
      }
      if (ch === ">") {
        blocks.push(text.slice(start, i + 1));
        break;
      }
      i += 1;
    }
  }
  return blocks;
}

const offenders = [];
for (const file of walk(root)) {
  const text = fs.readFileSync(file, "utf8");
  const rel = path.relative(path.join(root, ".."), file).replace(/\\/g, "/");

  for (const block of matchJsxOpenTags(text, "Alert")) {
    if (/\bmessage=/.test(block)) {
      offenders.push(`${rel}: Alert deprecated message=`);
    }
  }
  // AntD Statistic only — false positive 방지 (다른 컴포넌트 valueStyle 제외)
  for (const block of matchJsxOpenTags(text, "Statistic")) {
    if (/\bvalueStyle=/.test(block)) {
      offenders.push(`${rel}: Statistic deprecated valueStyle=`);
    }
  }
  // AntD Drawer only — Recharts width 오탐 방지
  for (const block of matchJsxOpenTags(text, "Drawer")) {
    if (/\bwidth=/.test(block)) {
      offenders.push(`${rel}: Drawer deprecated width= (use size=)`);
    }
    if (/\bheight=/.test(block)) {
      offenders.push(`${rel}: Drawer deprecated height= (use size=)`);
    }
  }
  if (/Tabs\.TabPane/.test(text)) {
    offenders.push(`${rel}: Tabs.TabPane`);
  }
  if (/Collapse\.Panel/.test(text)) {
    offenders.push(`${rel}: Collapse.Panel`);
  }
  if (/import\s+Table\s+from\s+['"]antd['"]/.test(text)) {
    offenders.push(`${rel}: default Table import`);
  }
  if (/import\s+antd\s+from\s+['"]antd['"]/.test(text)) {
    offenders.push(`${rel}: default antd import`);
  }
}

if (offenders.length) {
  console.error("antd-compat FAIL:");
  for (const o of offenders) console.error(" -", o);
  process.exit(1);
}
console.log(
  "antd-compat OK (Alert.message / Statistic.valueStyle / Drawer.width|height / TabPane / Collapse.Panel / default import)",
);
