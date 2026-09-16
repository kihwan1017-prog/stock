/**
 * SymbolPerformanceDrawer — AntD 6 size API + Drawer width 금지.
 */

import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("SymbolPerformanceDrawer antd6 compat", () => {
  it("uses Drawer size= and never width=", () => {
    const src = fs.readFileSync(
      path.join(
        process.cwd(),
        "src/features/admin/operations-center/SymbolPerformanceDrawer.tsx",
      ),
      "utf8",
    );
    expect(src).toMatch(/<Drawer[\s\S]*?\bsize=\{/);
    expect(src).not.toMatch(/<Drawer[\s\S]*?\bwidth=/);
    expect(src).toContain("destroyOnHidden");
  });
});
