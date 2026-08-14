import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { adminRoutes } from "@/config/routes";
import {
  UPBIT_HUB_TAB_KEYS,
  UPBIT_HUB_TAB_ORDER,
} from "@/features/admin/upbit/upbitHubTabConfig";

/** vitest cwd = frontend/ */
const srcRoot = join(process.cwd(), "src");

function readRel(pathFromSrc: string): string {
  return readFileSync(join(srcRoot, pathFromSrc), "utf8");
}

function walkTsxFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (name === "node_modules" || name === ".next") continue;
      walkTsxFiles(full, out);
    } else if (name.endsWith(".tsx") || name.endsWith(".ts")) {
      out.push(full);
    }
  }
  return out;
}

function assertOrder(src: string, markers: string[]) {
  let prev = -1;
  for (const marker of markers) {
    const idx = src.indexOf(marker);
    expect(idx, `missing: ${marker}`).toBeGreaterThan(-1);
    expect(idx, `order fail: ${marker}`).toBeGreaterThan(prev);
    prev = idx;
  }
}

describe("M5-E Ops SECTION_REORGANIZE", () => {
  const ops = () => readRel("features/admin/upbit/UpbitHubOpsSection.tsx");
  const page = () => readRel("app/(admin)/admin/upbit/page.tsx");
  const ambiguous = () =>
    readRel("features/admin/upbit/UpbitAmbiguousOrdersPanel.tsx");

  it("Status < Sync < Rate < Snapshot < Reconcile < Ambiguous 순서", () => {
    const src = ops();
    expect(src).toContain("운영 상태");
    expect(src).toContain("연결·동기화");
    expect(src).toContain("Rate 상태");
    expect(src).toContain("Snapshot");
    expect(src).toContain("주문·체결 정합");
    expect(src).toContain("Ambiguous Orders");

    // heading Title 닫힘 마커로 intro paragraph의 동일 문구와 충돌 방지
    assertOrder(src, [
      "운영 상태\n      </Typography.Title>",
      'title="GET /broker/upbit/account/status"',
      "연결·동기화\n      </Typography.Title>",
      "onClick={() => connectionTest.mutate()}",
      "onClick={() => ubaId != null && syncAccount.mutate(ubaId)}",
      "Rate 상태\n      </Typography.Title>",
      'title="Upbit Rate Limit (STEP 8-5-8)"',
      'title="Rate Limit Health"',
      "Snapshot\n      </Typography.Title>",
      'title="보유 스냅샷 (UPBIT)"',
      'title="스냅샷 원본"',
      "주문·체결 정합\n      </Typography.Title>",
      "onClick={() => reconcileOrders.mutate()}",
      "Ambiguous Orders\n      </Typography.Title>",
      "<UpbitAmbiguousOrdersPanel />",
    ]);
  });

  it("Ops mutation/GET/state/effect 계약 유지 (handler/API 변경 없음)", () => {
    const src = ops();
    expect(src.match(/useMutation\(/g)?.length ?? 0).toBe(4);
    expect(src.match(/useQuery\(/g)?.length ?? 0).toBe(3);
    expect(src.match(/useState(?:<[^>]+>)?\(/g)?.length ?? 0).toBe(1);
    expect(src.match(/useEffect\(/g)?.length ?? 0).toBe(0);

    for (const fn of [
      "getUpbitAccountStatus",
      "getUpbitAccountSnapshot",
      "getUpbitRateLimits",
      "testUpbitAccountConnection",
      "syncUpbitAccount",
      "reconcileUpbitOrders",
      "recheckUpbitRateLimits",
    ]) {
      expect(src).toContain(fn);
    }

    // split 금지
    expect(
      existsSync(join(srcRoot, "features/admin/upbit/OpsStatusSection.tsx")),
    ).toBe(false);
    expect(
      existsSync(join(srcRoot, "features/admin/upbit/OpsSyncSection.tsx")),
    ).toBe(false);
  });

  it("Ambiguous mount=1 · panel 내부 API 계약 유지 · Ops만 Ambiguous mount", () => {
    const o = ops();
    const p = page();
    const a = ambiguous();

    expect((o.match(/<UpbitAmbiguousOrdersPanel\b/g) ?? []).length).toBe(1);
    expect(p).not.toMatch(/<UpbitAmbiguousOrdersPanel/);

    expect(a.match(/useMutation\(/g)?.length ?? 0).toBe(7);
    expect(a.match(/useQuery\(/g)?.length ?? 0).toBe(4);
  });

  it("M5 tabs·LIVE/Risk mutation 0 · Ambiguous는 orders/recovery에 없음", () => {
    expect(UPBIT_HUB_TAB_ORDER).toEqual([
      UPBIT_HUB_TAB_KEYS.overview,
      UPBIT_HUB_TAB_KEYS.technical,
      UPBIT_HUB_TAB_KEYS.news,
      UPBIT_HUB_TAB_KEYS.ab,
      UPBIT_HUB_TAB_KEYS.ops,
    ]);

    const o = ops();
    for (const forbidden of [
      "AdminUpbitLiveUbaPanel",
      "setAdminLiveOrderEnabled",
      "armAdminLiveOrder",
      "disarmAdminLiveOrder",
      "startTradingScheduler",
      "pauseTradingScheduler",
      "setKillSwitch",
      "clearKillSwitch",
    ]) {
      expect(o).not.toContain(forbidden);
    }

    const risk = readRel("app/(admin)/admin/risk/page.tsx");
    expect(risk).not.toMatch(/testUpbitAccountConnection|reconcileUpbitOrders/);

    const orders = readRel("app/(admin)/admin/orders/page.tsx");
    const recovery = readRel("app/(admin)/admin/recovery/page.tsx");
    expect(orders).not.toMatch(/UpbitAmbiguousOrdersPanel/);
    expect(recovery).not.toMatch(/UpbitAmbiguousOrdersPanel/);

    expect(page()).toMatch(/adminRoutes\.accounts/);
    expect(adminRoutes.upbit).toBe("/admin/upbit");

    // Ambiguous JSX mount는 OpsSection 단일 (test·문서 문자열 제외)
    const featuresUpbit = join(srcRoot, "features", "admin", "upbit");
    const mounts: string[] = [];
    for (const file of walkTsxFiles(featuresUpbit)) {
      if (file.includes(".test.")) continue;
      const text = readFileSync(file, "utf8");
      if (/<UpbitAmbiguousOrdersPanel\s*\/>/.test(text)) {
        mounts.push(file.replace(/\\/g, "/"));
      }
    }
    expect(mounts).toHaveLength(1);
    expect(mounts[0]).toMatch(/UpbitHubOpsSection\.tsx$/);
  });
});
