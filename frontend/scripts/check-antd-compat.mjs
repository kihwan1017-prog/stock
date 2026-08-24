#!/usr/bin/env node
/**
 * Static antd-compat gate — CI/pre-commit용 빠른 검사.
 * ESLint와 중복이지만 lockfile 없이 즉시 실패할 수 있게 유지.
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

const offenders = [];
for (const file of walk(root)) {
  const text = fs.readFileSync(file, "utf8");
  const rel = path.relative(path.join(root, ".."), file).replace(/\\/g, "/");

  for (const block of text.match(/<Alert\b[\s\S]*?>/g) || []) {
    if (/\bmessage=/.test(block)) {
      offenders.push(`${rel}: Alert deprecated message=`);
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
console.log("antd-compat OK (Alert.message / TabPane / Collapse.Panel / default import)");
