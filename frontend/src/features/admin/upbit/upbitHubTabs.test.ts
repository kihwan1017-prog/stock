import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { adminMenuItems, flattenMenuItems } from "@/config/menu";
import { adminRoutes } from "@/config/routes";
import {
  UPBIT_HUB_TAB_KEYS,
  UPBIT_HUB_TAB_LABELS,
  UPBIT_HUB_TAB_ORDER,
} from "@/features/admin/upbit/upbitHubTabConfig";

/** vitest cwd = frontend/ */
const srcRoot = join(process.cwd(), "src");

function readRel(pathFromSrc: string): string {
  return readFileSync(join(srcRoot, pathFromSrc), "utf8");
}

describe("M5-A Upbit Hub Tab shell", () => {
  const page = () => readRel("app/(admin)/admin/upbit/page.tsx");
  const tabs = () => readRel("features/admin/upbit/UpbitHubTabs.tsx");
  const ops = () => readRel("features/admin/upbit/UpbitHubOpsSection.tsx");
  const config = () => readRel("features/admin/upbit/upbitHubTabConfig.ts");

  it("Tabs·5개 라벨·키가 존재한다", () => {
    expect(tabs()).toMatch(/<Tabs\b/);
    expect(UPBIT_HUB_TAB_ORDER).toHaveLength(5);
    expect(UPBIT_HUB_TAB_LABELS.overview).toBe("개요");
    expect(UPBIT_HUB_TAB_LABELS.technical).toBe("Technical");
    expect(UPBIT_HUB_TAB_LABELS.news).toBe("뉴스 파이프라인");
    expect(UPBIT_HUB_TAB_LABELS.ab).toBe("A/B 실험");
    expect(UPBIT_HUB_TAB_LABELS.ops).toBe("운영·정합");
    const cfg = config();
    const shell = tabs();
    for (const key of UPBIT_HUB_TAB_ORDER) {
      expect(cfg).toContain(`"${key}"`);
      expect(cfg).toContain(UPBIT_HUB_TAB_LABELS[key]);
      // shell은 UPBIT_HUB_TAB_LABELS.* 참조
      expect(shell).toContain(`UPBIT_HUB_TAB_LABELS.${key}`);
    }
  });

  it("Overview에 LiveSummary, Technical에 Scanner", () => {
    const p = page();
    expect(p).toMatch(/liveSummary=\{<\s*UpbitLiveStatusReadSummary/);
    expect(p).toMatch(/technical=\{<\s*UpbitOpportunityScannerPanel/);
  });

  it("News에 Collector, A/B에 Combined — N6가 N2–N5보다 탭 순서상 뒤", () => {
    const p = page();
    expect(p).toMatch(/news=\{<\s*UpbitNewsNoticeCollectorPanel/);
    expect(p).toMatch(/ab=\{<\s*UpbitNewsCombinedShadowPanel/);

    const newsIdx = UPBIT_HUB_TAB_ORDER.indexOf(UPBIT_HUB_TAB_KEYS.news);
    const abIdx = UPBIT_HUB_TAB_ORDER.indexOf(UPBIT_HUB_TAB_KEYS.ab);
    expect(newsIdx).toBeGreaterThan(-1);
    expect(abIdx).toBeGreaterThan(newsIdx);

    // keepAlive 렌더 순서도 news → ab
    const t = tabs();
    const newsPane = t.indexOf(
      `keepAlivePane(UPBIT_HUB_TAB_KEYS.news`,
    );
    const abPane = t.indexOf(`keepAlivePane(UPBIT_HUB_TAB_KEYS.ab`);
    expect(newsPane).toBeGreaterThan(-1);
    expect(abPane).toBeGreaterThan(newsPane);
  });

  it("Ambiguous·page ops는 Ops section 단일 mount", () => {
    const p = page();
    const o = ops();
    expect(p).toMatch(/ops=\{<\s*UpbitHubOpsSection/);
    expect(p).not.toMatch(/<UpbitAmbiguousOrdersPanel/);
    expect(o).toMatch(/<UpbitAmbiguousOrdersPanel\s*\/>/);
    expect(o).toMatch(/testUpbitAccountConnection/);
    expect(o).toMatch(/syncUpbitAccount/);
    expect(o).toMatch(/reconcileUpbitOrders/);
    expect(o).toMatch(/recheckUpbitRateLimits/);

    // duplicate JSX mount 방지
    const scannerMounts = (
      p.match(/<UpbitOpportunityScannerPanel\b/g) ?? []
    ).length;
    const collectorMounts = (
      p.match(/<UpbitNewsNoticeCollectorPanel\b/g) ?? []
    ).length;
    const combinedMounts = (
      p.match(/<UpbitNewsCombinedShadowPanel\b/g) ?? []
    ).length;
    expect(scannerMounts).toBe(1);
    expect(collectorMounts).toBe(1);
    expect(combinedMounts).toBe(1);
  });

  it("LIVE panel은 upbit에 없고 accounts link·mutation 문자열 0", () => {
    const p = page();
    const t = tabs();
    const o = ops();
    for (const src of [p, t, o]) {
      expect(src).not.toMatch(/AdminUpbitLiveUbaPanel/);
      expect(src).not.toMatch(/setAdminLiveOrderEnabled/);
      expect(src).not.toMatch(/armAdminLiveOrder/);
      expect(src).not.toMatch(/disarmAdminLiveOrder/);
      expect(src).not.toMatch(/startTradingScheduler/);
      expect(src).not.toMatch(/pauseTradingScheduler/);
    }
    expect(p).toMatch(/adminRoutes\.accounts/);
    expect(p).toMatch(/계좌 관리 \(LIVE\/ARM 제어\)/);
  });

  it("keep-alive: 방문 전 unmount · Tab switch mutation 없음", () => {
    const t = tabs();
    expect(t).toMatch(/visited/);
    expect(t).toMatch(/display: activeKey === key \? "block" : "none"/);
    expect(t).not.toMatch(/destroyInactiveTabPane\s*=\s*\{?\s*true/);
    // Tab onChange는 selectTab만 — mutate/run 호출 없음
    expect(t).toMatch(/onChange=\{selectTab\}/);
    expect(t).not.toMatch(/\.mutate\(/);
    expect(t).not.toMatch(/runUpbit/);
    expect(t).not.toMatch(/evaluateUpbit/);
  });

  it("route·permission·menu leaf 유지", () => {
    expect(adminRoutes.upbit).toBe("/admin/upbit");
    const flat = flattenMenuItems(adminMenuItems);
    const accounts = flat.find((item) => item.key === "accounts");
    expect(accounts?.matchPaths).toContain(adminRoutes.upbit);
    expect(accounts?.permission).toBe("menu:accounts");
    expect(flat.filter((item) => item.path === adminRoutes.upbit)).toHaveLength(
      0,
    );
  });
});
