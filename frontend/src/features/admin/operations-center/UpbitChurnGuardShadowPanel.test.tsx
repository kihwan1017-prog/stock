/**
 * AntD 6 compat + panel contract smoke for Churn Guard Shadow UI.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("UpbitChurnGuardShadowPanel antd6 compat", () => {
  const src = readFileSync(
    resolve(
      process.cwd(),
      "src/features/admin/operations-center/UpbitChurnGuardShadowPanel.tsx",
    ),
    "utf8",
  );

  it("uses Drawer size= and never width=", () => {
    expect(src).toMatch(/<Drawer[\s\S]*?\bsize=\{/);
    expect(src).not.toMatch(/<Drawer[\s\S]*?\bwidth=/);
  });

  it("declares shadow-only notice and no REAL block", () => {
    expect(src).toContain("감시/경고 전용");
    expect(src).toContain("자동 매매를 차단하지 않습니다");
    expect(src).toContain("REAL 차단 없음");
  });
});
