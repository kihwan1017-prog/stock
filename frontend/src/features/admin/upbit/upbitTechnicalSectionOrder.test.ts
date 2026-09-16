import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { adminMenuItems, flattenMenuItems } from "@/config/menu";
import { adminRoutes } from "@/config/routes";
import {
  UPBIT_HUB_TAB_KEYS,
  UPBIT_HUB_TAB_ORDER,
} from "@/features/admin/upbit/upbitHubTabConfig";

/** vitest cwd = frontend/ */
const frontendRoot = process.cwd();
const srcRoot = join(frontendRoot, "src");

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
    expect(idx, `missing marker: ${marker}`).toBeGreaterThan(-1);
    expect(idx, `order fail at: ${marker}`).toBeGreaterThan(prev);
    prev = idx;
  }
}

describe("M5-B Technical SECTION_REORGANIZE", () => {
  const panel = () =>
    readRel("features/admin/upbit/UpbitOpportunityScannerPanel.tsx");
  const page = () => readRel("app/(admin)/admin/upbit/page.tsx");
  const tabs = () => readRel("features/admin/upbit/UpbitHubTabs.tsx");
  const api = () => readRel("features/admin/api/adminApi.ts");

  it("section headings·cards 존재 및 Scanner→Candidate→Shadow→Evaluate→Cohort 순서", () => {
    const src = panel();
    expect(src).toContain("Scanner 상태");
    expect(src).toContain("후보 / AI 분석");
    expect(src).toContain("Paper Shadow");
    expect(src).toContain("Shadow 평가");
    expect(src).toContain("Cohort 성과");
    expect(src).toContain('title="Scanner Status"');
    expect(src).toContain('title="Last Top Candidates"');
    expect(src).toContain('title="Active Shadows"');
    expect(src).toContain('title="Completed Shadows"');
    expect(src).toContain('title="Shadow Evaluator Scheduler"');
    expect(src).toContain('title="Shadow 통계 / 코호트"');

    const normalized = src.replace(/\r\n/g, "\n");
    assertOrder(normalized, [
      "Scanner 상태",
      "후보 / AI 분석",
      'title="Last Top Candidates"',
      'title="Active Shadows"',
      'title="Completed Shadows"',
      "Shadow 평가\n      </Typography.Title>",
      'title="Shadow Evaluator Scheduler"',
      "Cohort 성과",
      'title="Shadow 통계 / 코호트"',
    ]);
  });

  it("mutation/API/handler 계약 유지 (split·endpoint 변경 없음)", () => {
    const src = panel();
    expect(src.match(/useMutation\(/g)?.length ?? 0).toBe(3);
    expect(src.match(/useQuery\(/g)?.length ?? 0).toBe(2);
    expect(src.match(/useState\(/g)?.length ?? 0).toBe(0);
    expect(src.match(/useEffect\(/g)?.length ?? 0).toBe(0);
    expect(src).toContain("runUpbitOpportunityScanner");
    expect(src).toContain("evaluateUpbitOpportunityShadows");
    expect(src).toContain("getUpbitOpportunityScannerStatus");
    expect(src).toContain("force_ai: false");
    expect(src).toContain("notify: true");
    expect(src).toMatch(/Dry Run 1회/);
    expect(src).toMatch(/>\s*Shadow 평가\s*</);

    // 신규 split 파일 없음
    expect(
      existsSync(
        join(srcRoot, "features/admin/upbit/ScannerSection.tsx"),
      ),
    ).toBe(false);
    expect(
      existsSync(join(srcRoot, "features/admin/upbit/ShadowSection.tsx")),
    ).toBe(false);
    expect(
      existsSync(join(srcRoot, "features/admin/upbit/CohortSection.tsx")),
    ).toBe(false);

    const apiSrc = api();
    expect(apiSrc).toContain(
      'getJson("/admin/upbit/opportunity-scanner/status")',
    );
    expect(apiSrc).toContain(
      'postJson("/admin/upbit/opportunity-scanner/run"',
    );
    expect(apiSrc).toContain(
      'postJson("/admin/upbit/opportunity-scanner/shadows/evaluate"',
    );
  });

  it("panel mount=1 · Technical tab · News/A-B/Ops · LIVE mut=0", () => {
    const files = walkTsxFiles(srcRoot);
    const mounts: string[] = [];
    for (const file of files) {
      if (file.includes(".test.") || file.includes(".spec.")) continue;
      const text = readFileSync(file, "utf8");
      if (/<UpbitOpportunityScannerPanel\b/.test(text)) {
        mounts.push(file.replace(/\\/g, "/"));
      }
    }
    expect(mounts).toHaveLength(1);
    expect(mounts[0]).toContain("app/(admin)/admin/upbit/page.tsx");

    const p = page();
    expect(p).toMatch(/technical=\{<\s*UpbitOpportunityScannerPanel/);
    expect(p).toMatch(/news=\{<\s*UpbitNewsNoticeCollectorPanel/);
    expect(p).toMatch(/ab=\{<\s*UpbitNewsCombinedShadowPanel/);
    expect(p).toMatch(/ops=\{<\s*UpbitHubOpsSection/);
    expect(UPBIT_HUB_TAB_ORDER).toEqual([
      UPBIT_HUB_TAB_KEYS.overview,
      UPBIT_HUB_TAB_KEYS.technical,
      UPBIT_HUB_TAB_KEYS.news,
      UPBIT_HUB_TAB_KEYS.ab,
      UPBIT_HUB_TAB_KEYS.ops,
    ]);
    expect(tabs()).toMatch(/UPBIT_HUB_TAB_KEYS\.technical/);

    for (const src of [p, panel(), tabs()]) {
      expect(src).not.toMatch(/setAdminLiveOrderEnabled/);
      expect(src).not.toMatch(/armAdminLiveOrder/);
      expect(src).not.toMatch(/disarmAdminLiveOrder/);
      expect(src).not.toMatch(/startTradingScheduler/);
      expect(src).not.toMatch(/pauseTradingScheduler/);
      expect(src).not.toMatch(/AdminUpbitLiveUbaPanel/);
    }

    const risk = readRel("app/(admin)/admin/risk/page.tsx");
    expect(risk).not.toMatch(/setAdminLiveOrderEnabled/);
    expect(risk).not.toMatch(/armAdminLiveOrder/);
    expect(risk).not.toMatch(/startTradingScheduler/);

    const flat = flattenMenuItems(adminMenuItems);
    expect(adminRoutes.upbit).toBe("/admin/upbit");
    const accounts = flat.find((i) => i.key === "accounts");
    expect(accounts?.matchPaths).toContain(adminRoutes.upbit);
    expect(flat.filter((i) => i.path === adminRoutes.upbit)).toHaveLength(0);
  });
});
