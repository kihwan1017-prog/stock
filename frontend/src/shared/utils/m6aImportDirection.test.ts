import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const srcRoot = join(process.cwd(), "src");

function walk(dir: string, out: string[] = []): string[] {
  if (!existsSync(dir)) return out;
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (name === "node_modules" || name === ".next") continue;
      walk(full, out);
    } else if (name.endsWith(".ts") || name.endsWith(".tsx")) {
      out.push(full);
    }
  }
  return out;
}

describe("M6-A import direction", () => {
  it("user → admin/utils/dataHelpers import count = 0", () => {
    const hits: string[] = [];
    for (const file of [
      ...walk(join(srcRoot, "features", "user")),
      ...walk(join(srcRoot, "app", "(user)")),
    ]) {
      const text = readFileSync(file, "utf8");
      if (text.includes("@/features/admin/utils/dataHelpers")) {
        hits.push(file.replace(/\\/g, "/"));
      }
    }
    expect(hits, hits.join("\n")).toEqual([]);
  });

  it("shared utils modules exist", () => {
    expect(
      existsSync(join(srcRoot, "shared", "utils", "dataHelpers.ts")),
    ).toBe(true);
    expect(
      existsSync(join(srcRoot, "shared", "utils", "strategyStatusColors.ts")),
    ).toBe(true);
    expect(
      existsSync(join(srcRoot, "shared", "utils", "riskRatePercent.ts")),
    ).toBe(true);
  });

  it("admin dataHelpers is re-export shim only (no local body)", () => {
    const text = readFileSync(
      join(srcRoot, "features", "admin", "utils", "dataHelpers.ts"),
      "utf8",
    );
    expect(text).toContain("@/shared/utils/dataHelpers");
    expect(text).not.toMatch(/export function asRecord/);
  });
});
