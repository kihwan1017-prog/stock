import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { adminMenuItems, flattenMenuItems } from "@/config/menu";
import { adminRoutes } from "@/config/routes";

const frontendRoot = process.cwd();
const srcRoot = join(frontendRoot, "src");

function readSrc(rel: string): string {
  return readFileSync(join(srcRoot, rel), "utf8");
}

function walkMountFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const full = join(dir, name);
      if (statSync(full).isDirectory()) {
        if (name === "node_modules" || name === ".next") continue;
        walk(full);
      } else if (
        (name.endsWith(".tsx") || name.endsWith(".ts")) &&
        !name.includes(".test.")
      ) {
        out.push(full);
      }
    }
  };
  walk(srcRoot);
  return out;
}

describe("M4-C2-APPLY Risk LIVE/ARM single-surface", () => {
  it("Risk page: LIVE/ARM/Scheduler mutation 없음 · Kill·accounts 링크 있음", () => {
    const risk = readSrc("app/(admin)/admin/risk/page.tsx");
    expect(risk).not.toMatch(/setAdminLiveOrderEnabled/);
    expect(risk).not.toMatch(/armAdminLiveOrder/);
    expect(risk).not.toMatch(/disarmAdminLiveOrder/);
    expect(risk).not.toMatch(/startTradingScheduler/);
    expect(risk).not.toMatch(/pauseTradingScheduler/);
    expect(risk).toMatch(/activateKillSwitch/);
    expect(risk).toMatch(/deactivateKillSwitch/);
    expect(risk).toMatch(/Kill Switch ON/);
    expect(risk).toMatch(/adminRoutes\.accounts/);
    expect(risk).toMatch(/계좌 LIVE 제어/);
    expect(risk).toMatch(/live_order_enabled/);
    expect(risk).toMatch(/live_armed/);
    expect(risk).toMatch(/updateAdminLiveRiskLimits/);
  });

  it("Accounts panel: LIVE/ARM/Scheduler control 유지", () => {
    const panel = readSrc("features/admin/accounts/AdminUpbitLiveUbaPanel.tsx");
    expect(panel).toMatch(/setAdminLiveOrderEnabled/);
    expect(panel).toMatch(/armAdminLiveOrder/);
    expect(panel).toMatch(/disarmAdminLiveOrder/);
    expect(panel).toMatch(/startTradingScheduler/);
    expect(panel).toMatch(/pauseTradingScheduler/);
  });

  it("Upbit page: LIVE/ARM/Scheduler mutation 없음", () => {
    const upbit = readSrc("app/(admin)/admin/upbit/page.tsx");
    const summary = readSrc("features/admin/upbit/UpbitLiveStatusReadSummary.tsx");
    for (const text of [upbit, summary]) {
      expect(text).not.toMatch(/setAdminLiveOrderEnabled/);
      expect(text).not.toMatch(/armAdminLiveOrder/);
      expect(text).not.toMatch(/disarmAdminLiveOrder/);
      expect(text).not.toMatch(/startTradingScheduler/);
      expect(text).not.toMatch(/pauseTradingScheduler/);
    }
  });

  it("AdminUpbitLiveUbaPanel mount = 1 (accounts only)", () => {
    const mounts = walkMountFiles().filter((file) => {
      const text = readFileSync(file, "utf8");
      return /<AdminUpbitLiveUbaPanel\b/.test(text);
    });
    expect(mounts).toHaveLength(1);
    expect(mounts[0]?.replace(/\\/g, "/")).toContain(
      "app/(admin)/admin/accounts/page.tsx",
    );
  });

  it("menu regression: duplicate=0 · strategy visible", () => {
    const flat = flattenMenuItems(adminMenuItems);
    const paths = flat.map((i) => i.path).filter(Boolean) as string[];
    const seen = new Set<string>();
    const dup: string[] = [];
    for (const p of paths) {
      if (seen.has(p)) dup.push(p);
      seen.add(p);
    }
    expect(dup).toEqual([]);
    expect(flat.some((i) => i.path === adminRoutes.strategyRequests)).toBe(true);
    expect(flat.some((i) => i.path === adminRoutes.strategyDrafts)).toBe(true);
    expect(flat.some((i) => i.path === adminRoutes.portfolioValidations)).toBe(
      true,
    );
    expect(existsSync(join(srcRoot, "app/(admin)/admin/risk/page.tsx"))).toBe(
      true,
    );
  });
});
