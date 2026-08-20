import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { adminMenuItems, flattenMenuItems } from "@/config/menu";
import { adminRoutes } from "@/config/routes";
import {
  CONSERVATIVE_PORTFOLIO_DEFAULTS,
  formatUpbitAutotradingModeLabel,
  isFullMarketSingleMode,
  isPortfolioMode,
  UPBIT_AUTOTRADING_TAB_KEYS,
  UPBIT_AUTOTRADING_TAB_LABELS,
  UPBIT_AUTOTRADING_TAB_ORDER,
} from "@/features/admin/upbit/upbitAutotradingSettingsConfig";

/** vitest cwd = frontend/ */
const srcRoot = join(process.cwd(), "src");

function readRel(pathFromSrc: string): string {
  return readFileSync(join(srcRoot, pathFromSrc), "utf8");
}

describe("UPBIT autotrading settings workspace", () => {
  const page = () =>
    readRel("app/(admin)/admin/upbit/autotrading/page.tsx");
  const workspace = () =>
    readRel("features/admin/upbit/UpbitAutotradingSettingsWorkspace.tsx");
  const config = () =>
    readRel("features/admin/upbit/upbitAutotradingSettingsConfig.ts");
  const drawer = () =>
    readRel("features/admin/accounts/UpbitPortfolioControls.tsx");

  it("6개 탭 키·라벨이 존재한다", () => {
    expect(UPBIT_AUTOTRADING_TAB_ORDER).toHaveLength(6);
    expect(UPBIT_AUTOTRADING_TAB_LABELS.market).toBe("전체시장 자동선정");
    expect(UPBIT_AUTOTRADING_TAB_LABELS.capital).toBe("자금 · 포지션");
    expect(UPBIT_AUTOTRADING_TAB_LABELS.entry).toBe("진입 규칙");
    expect(UPBIT_AUTOTRADING_TAB_LABELS.exit).toBe("청산 규칙");
    expect(UPBIT_AUTOTRADING_TAB_LABELS.ai).toBe("AI");
    expect(UPBIT_AUTOTRADING_TAB_LABELS.safety).toBe("안전 · 손실 제한");
    const cfg = config();
    const ws = workspace();
    for (const key of UPBIT_AUTOTRADING_TAB_ORDER) {
      expect(cfg).toContain(`"${key}"`);
      expect(cfg).toContain(UPBIT_AUTOTRADING_TAB_LABELS[key]);
      expect(ws).toContain(`UPBIT_AUTOTRADING_TAB_KEYS.${key}`);
    }
    expect(ws).toMatch(/<Tabs\b/);
  });

  it("보수적 기본값 객체가 안전 지향이다", () => {
    expect(CONSERVATIVE_PORTFOLIO_DEFAULTS.max_positions).toBe(3);
    expect(CONSERVATIVE_PORTFOLIO_DEFAULTS.min_cash_reserve_pct).toBe(0.6);
    expect(CONSERVATIVE_PORTFOLIO_DEFAULTS.allow_averaging_down).toBe(false);
    expect(CONSERVATIVE_PORTFOLIO_DEFAULTS.allow_duplicate_symbol).toBe(false);
    expect(CONSERVATIVE_PORTFOLIO_DEFAULTS.portfolio_max_pending_entries).toBe(
      1,
    );
    expect(CONSERVATIVE_PORTFOLIO_DEFAULTS.daily_loss_limit_pct).toBe(0.02);
    expect(workspace()).toContain("보수적 설정 적용");
    expect(workspace()).toContain("CONSERVATIVE_PORTFOLIO_DEFAULTS");
  });

  it("모드 렌더링 헬퍼가 FIXED/SINGLE/PORTFOLIO를 구분한다", () => {
    expect(formatUpbitAutotradingModeLabel("FIXED_SYMBOL")).toBe("FIXED");
    expect(formatUpbitAutotradingModeLabel("FULL_MARKET_SINGLE")).toBe(
      "SINGLE",
    );
    expect(formatUpbitAutotradingModeLabel("FULL_MARKET_AUTO")).toBe("SINGLE");
    expect(formatUpbitAutotradingModeLabel("FULL_MARKET_PORTFOLIO")).toBe(
      "PORTFOLIO",
    );
    expect(isPortfolioMode("FULL_MARKET_PORTFOLIO")).toBe(true);
    expect(isFullMarketSingleMode("FULL_MARKET_SINGLE")).toBe(true);
    expect(isPortfolioMode("FIXED_SYMBOL")).toBe(false);
  });

  it("page는 AdminPageShell + Workspace + ubaId 쿼리를 사용한다", () => {
    const p = page();
    expect(p).toMatch(/AdminPageShell/);
    expect(p).toMatch(/UpbitAutotradingSettingsWorkspace/);
    expect(p).toMatch(/ubaId/);
    expect(p).toMatch(/DEFAULT_UPBIT_AUTOTRADING_UBA_ID/);
  });

  it("route·menu leaf·permission", () => {
    expect(adminRoutes.upbitAutotrading).toBe("/admin/upbit/autotrading");
    const flat = flattenMenuItems(adminMenuItems);
    const item = flat.find(
      (i) => i.path === adminRoutes.upbitAutotrading,
    );
    expect(item?.label).toBe("업비트 자동매매 설정");
    expect(item?.permission).toBe("menu:upbit");
  });

  it("drawer는 요약+링크이며 자동 Enable 호출 문자열이 없다", () => {
    const d = drawer();
    expect(d).toMatch(/adminRoutes\.upbitAutotrading/);
    expect(d).toMatch(/업비트 자동매매 설정 열기/);
    expect(d).not.toMatch(/Save Policy/);
    expect(d).not.toMatch(/previewAdminUbaPortfolioSizing/);
    const ws = workspace();
    expect(ws).not.toMatch(/enableAdminUbaPortfolio/);
    expect(ws).toMatch(/previewAdminUbaPortfolioSizing/);
  });

  it("탭 키 상수가 안정적이다", () => {
    expect(UPBIT_AUTOTRADING_TAB_KEYS.market).toBe("market");
    expect(UPBIT_AUTOTRADING_TAB_KEYS.safety).toBe("safety");
  });
});
