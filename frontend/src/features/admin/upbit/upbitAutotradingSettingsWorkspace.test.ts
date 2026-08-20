import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { adminMenuItems, flattenMenuItems } from "@/config/menu";
import { adminRoutes } from "@/config/routes";
import {
  CONSERVATIVE_PORTFOLIO_DEFAULTS,
  CONFIRM_ENABLE_PORTFOLIO,
  formatUpbitAutotradingModeLabel,
  isFullMarketSingleMode,
  isPortfolioMode,
  resolvePortfolioEnableControl,
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

  it("drawer는 요약+링크이며 설정 상세는 워크스페이스", () => {
    const d = drawer();
    expect(d).toMatch(/adminRoutes\.upbitAutotrading/);
    expect(d).toMatch(/업비트 자동매매 설정 열기/);
    expect(d).not.toMatch(/Save Policy/);
    expect(d).not.toMatch(/previewAdminUbaPortfolioSizing/);
  });

  it("settings workspace에 Portfolio Enable UI·API wiring이 있다", () => {
    const ws = workspace();
    expect(ws).toMatch(/enableAdminUbaPortfolio/);
    expect(ws).toMatch(/disableAdminUbaPortfolio/);
    expect(ws).toContain("FULL MARKET PORTFOLIO 시작");
    expect(ws).toContain("FULL MARKET PORTFOLIO 중지");
    expect(ws).toContain("CONFIRM_ENABLE_PORTFOLIO");
    expect(ws).toContain("confirmation_text: CONFIRM_ENABLE_PORTFOLIO");
    expect(CONFIRM_ENABLE_PORTFOLIO).toBe("전체시장 포트폴리오 모드 시작");
    expect(ws).toMatch(/previewAdminUbaPortfolioSizing/);
    expect(ws).toMatch(/Dry Select/);
    expect(ws).toMatch(/resolvePortfolioEnableControl/);
  });

  it("SINGLE + Portfolio OFF → Enable visible; blocked면 disabled reason", () => {
    const ok = resolvePortfolioEnableControl({
      portfolioOn: false,
      live: "ON",
      arm: "ON",
      unattendedEnabled: true,
      unattendedRemainingSeconds: 3600,
      primaryBlocker: null,
      killActive: false,
      conflictHighCritical: 0,
    });
    expect(ok.showEnable).toBe(true);
    expect(ok.enableDisabled).toBe(false);

    const blocked = resolvePortfolioEnableControl({
      portfolioOn: false,
      live: "OFF",
      arm: "OFF",
      unattendedEnabled: false,
      primaryBlocker: "LIVE_OFF",
      killActive: false,
      conflictHighCritical: 0,
    });
    expect(blocked.showEnable).toBe(true);
    expect(blocked.enableDisabled).toBe(true);
    expect(blocked.disableReasons).toEqual(
      expect.arrayContaining(["LIVE_OFF", "ARM_OFF", "UNATTENDED_OFF"]),
    );
  });

  it("Portfolio ON → Disable visible", () => {
    const on = resolvePortfolioEnableControl({
      portfolioOn: true,
      live: "ON",
      arm: "ON",
      unattendedEnabled: true,
    });
    expect(on.showDisable).toBe(true);
    expect(on.showEnable).toBe(false);
  });

  it("탭 키 상수가 안정적이다", () => {
    expect(UPBIT_AUTOTRADING_TAB_KEYS.market).toBe("market");
    expect(UPBIT_AUTOTRADING_TAB_KEYS.safety).toBe("safety");
  });

  it("쿼리 로딩 시 asRecord null 중첩 접근을 asObj로 방어한다", () => {
    const ws = workspace();
    expect(ws).toContain("function asObj");
    expect(ws).toContain("asRecord(value) ?? {}");
    expect(ws).toContain("const portfolio = asObj(portfolioQuery.data)");
    expect(ws).toContain("const policy = asObj(portfolio.policy)");
  });

  it("탭 Form은 forceRender/destroyOnHidden=false로 useForm 연결을 유지한다", () => {
    const ws = workspace();
    expect(ws).toContain("destroyOnHidden={false}");
    expect(ws).toContain("forceRender");
    expect(ws).toMatch(/formsReady/);
  });
});
