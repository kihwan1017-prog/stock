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

describe("M5-C News Pipeline SECTION_REORGANIZE", () => {
  const panel = () =>
    readRel("features/admin/upbit/UpbitNewsNoticeCollectorPanel.tsx");
  const page = () => readRel("app/(admin)/admin/upbit/page.tsx");
  const tech = () =>
    readRel("features/admin/upbit/UpbitOpportunityScannerPanel.tsx");

  it("N2→N3→N4→N5 section·action 순서", () => {
    const src = panel();
    expect(src).toContain("뉴스 수집");
    expect(src).toContain("심볼 매핑 · 품질");
    expect(src).toContain("AI 뉴스 분석");
    expect(src).toContain("News Signal");

    assertOrder(src, [
      "뉴스 수집",
      "수동 수집 1회",
      'title="최근 공지/뉴스 (+ Mapped Symbols)"',
      "심볼 매핑 · 품질",
      "Symbol Mapping 실행",
      'title="Collector + Mapping status"',
      "AI 뉴스 분석",
      "AI News Analysis (max 5)",
      'title="최근 AI 분석 (sentiment ≠ trade signal)"',
      'title="AI News Analysis status"',
      "News Signal\n      </Typography.Title>",
      'title="최근 News Signals"',
      'title="News Signal stats"',
    ]);
    // Signal action은 Signal section 내부 (heading 이후)
    const signalHeading = src.indexOf("News Signal\n      </Typography.Title>");
    const signalAction = src.indexOf("News Signal 표준화", signalHeading);
    expect(signalAction).toBeGreaterThan(signalHeading);
  });

  it("API/mutation/handler 계약·rowKey WIP·no split·no trade actions", () => {
    const src = panel();
    expect(src.match(/useMutation\(/g)?.length ?? 0).toBe(4);
    expect(src.match(/useQuery\(/g)?.length ?? 0).toBe(7);
    expect(src.match(/useState\(/g)?.length ?? 0).toBe(0);
    expect(src.match(/useEffect\(/g)?.length ?? 0).toBe(0);
    expect(src.match(/onClick=/g)?.length ?? 0).toBe(5);

    for (const fn of [
      "getUpbitNewsCollectorStatus",
      "getUpbitNewsCollectorRecent",
      "runUpbitNewsCollector",
      "runUpbitNewsSymbolMapping",
      "getUpbitNewsAnalysisStatus",
      "getUpbitNewsAnalysisRecent",
      "runUpbitNewsAnalysis",
      "getUpbitNewsSignalsStatus",
      "getUpbitNewsSignalsRecent",
      "getUpbitNewsSignalsStats",
      "runUpbitNewsSignals",
    ]) {
      expect(src).toContain(fn);
    }

    // M5-C commit 기준: HEAD-style key map (rowKey WIP는 WT residual, commit 제외)
    expect(src).toMatch(/dataSource=\{items\.map/);
    expect(src).toContain("key: String(row.article_id ?? idx)");
    expect(src).toContain("key: String(row.analysis_id ?? idx)");
    expect(src).toContain("key: String(row.signal_id ?? idx)");
    expect(src).not.toContain(
      "AdminDataTable 기본 rowKey=id — article에는 id 없음",
    );

    expect(existsSync(join(srcRoot, "features/admin/upbit/NewsCollectionSection.tsx"))).toBe(
      false,
    );
    expect(existsSync(join(srcRoot, "features/admin/upbit/NewsSignalSection.tsx"))).toBe(
      false,
    );

    // action buttons only — no trade verbs as UI actions
    expect(src).not.toMatch(/>(BUY|SELL|ALLOW|APPLY)</);
    expect(src).not.toMatch(/onClick=\{[^}]*ALLOW/);
  });

  it("mounts·M5-A/B·LIVE/Risk regression", () => {
    const files = walkTsxFiles(srcRoot);
    const newsMounts: string[] = [];
    const abMounts: string[] = [];
    for (const file of files) {
      if (file.includes(".test.") || file.includes(".spec.")) continue;
      const text = readFileSync(file, "utf8");
      if (/<UpbitNewsNoticeCollectorPanel\b/.test(text)) {
        newsMounts.push(file.replace(/\\/g, "/"));
      }
      if (/<UpbitNewsCombinedShadowPanel\b/.test(text)) {
        abMounts.push(file.replace(/\\/g, "/"));
      }
    }
    expect(newsMounts).toHaveLength(1);
    expect(abMounts).toHaveLength(1);
    expect(newsMounts[0]).toContain("app/(admin)/admin/upbit/page.tsx");

    const p = page();
    expect(p).toMatch(/news=\{<\s*UpbitNewsNoticeCollectorPanel/);
    expect(p).toMatch(/ab=\{<\s*UpbitNewsCombinedShadowPanel/);
    expect(p).toMatch(/technical=\{<\s*UpbitOpportunityScannerPanel/);
    expect(UPBIT_HUB_TAB_ORDER).toEqual([
      UPBIT_HUB_TAB_KEYS.overview,
      UPBIT_HUB_TAB_KEYS.technical,
      UPBIT_HUB_TAB_KEYS.news,
      UPBIT_HUB_TAB_KEYS.ab,
      UPBIT_HUB_TAB_KEYS.ops,
    ]);

    // M5-B Technical flow markers
    const t = tech();
    expect(t).toContain("Scanner 상태");
    expect(t).toContain("후보 / AI 분석");
    expect(t).toContain("Paper Shadow");
    expect(t).toContain("Shadow 평가");
    expect(t).toContain("Cohort 성과");

    for (const src of [p, panel()]) {
      expect(src).not.toMatch(/setAdminLiveOrderEnabled/);
      expect(src).not.toMatch(/armAdminLiveOrder/);
      expect(src).not.toMatch(/startTradingScheduler/);
      expect(src).not.toMatch(/AdminUpbitLiveUbaPanel/);
    }
    const risk = readRel("app/(admin)/admin/risk/page.tsx");
    expect(risk).not.toMatch(/setAdminLiveOrderEnabled/);
    expect(risk).not.toMatch(/armAdminLiveOrder/);
    expect(adminRoutes.upbit).toBe("/admin/upbit");
  });
});
