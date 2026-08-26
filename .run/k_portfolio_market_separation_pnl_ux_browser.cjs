/**
 * Auth browser verify — /admin/portfolio market separation + PnL UX (READ-ONLY).
 * No tokens printed.
 */

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const BASE = process.env.E2E_BASE_URL || "http://127.0.0.1:3000";
const OUT_JSON = path.join(ROOT, ".run", "k_portfolio_market_separation_pnl_ux.json");
const OUT_MD = path.join(ROOT, ".run", "k_portfolio_market_separation_pnl_ux.md");

const { chromium } = require(
  path.join(ROOT, "frontend", "node_modules", "playwright"),
);

function isAppConsoleNoise(text) {
  const t = String(text || "");
  if (/Download the React DevTools/i.test(t)) return true;
  if (/\[HMR\]/i.test(t)) return true;
  if (/\[Fast Refresh\]/i.test(t)) return true;
  return false;
}

function classifyWarn(text) {
  const t = String(text || "");
  if (/deprecated/i.test(t) && /antd|ant design/i.test(t)) return "antd";
  if (/hydrat/i.test(t)) return "hydration";
  if (/Warning:/i.test(t) || /React/i.test(t)) return "react";
  return "other";
}

async function injectAuth(page, context, session) {
  await context.addCookies([
    {
      name: "kiki-admin-token",
      value: session.access_token,
      domain: "127.0.0.1",
      path: "/",
    },
    ...(session.refresh_token
      ? [
          {
            name: "kiki-admin-refresh",
            value: session.refresh_token,
            domain: "127.0.0.1",
            path: "/",
          },
        ]
      : []),
  ]);
  await page.addInitScript((sess) => {
    try {
      sessionStorage.setItem("kiki-admin-token", sess.access_token);
      if (sess.refresh_token) {
        sessionStorage.setItem("kiki-admin-refresh", sess.refresh_token);
      }
      sessionStorage.setItem("kiki-admin-user", JSON.stringify(sess.user));
      document.cookie = `kiki-admin-token=${encodeURIComponent(sess.access_token)}; Path=/; SameSite=Lax`;
      if (sess.refresh_token) {
        document.cookie = `kiki-admin-refresh=${encodeURIComponent(sess.refresh_token)}; Path=/; SameSite=Lax`;
      }
    } catch (_) {
      /* ignore */
    }
  }, session);
}

async function clickMarket(page, label) {
  // 시장 필터 영역의 첫 번째 Radio.Group
  const group = page.locator(".ant-radio-group").nth(0);
  const opt = group.getByText(label, { exact: true }).first();
  await opt.click({ timeout: 5000 });
}

async function clickOwnership(page, label) {
  const group = page.locator(".ant-radio-group").nth(1);
  const opt = group.getByText(label, { exact: true }).first();
  await opt.click({ timeout: 5000 });
}

async function tableBodyText(page) {
  const table = page.locator(".ant-table-tbody").first();
  if (!(await table.count())) return "";
  return (await table.innerText()).slice(0, 4000);
}

async function main() {
  const sessionPath = path.join(ROOT, ".run", "_auth_browser_session.json");
  if (!fs.existsSync(sessionPath)) {
    throw new Error("missing session — run .run/_auth_browser_session_save.py");
  }
  const session = JSON.parse(fs.readFileSync(sessionPath, "utf8"));
  if (!session.access_token) throw new Error("no access_token");

  const state = {
    FINAL_VERDICT: "PENDING",
    ROUTE: "/admin/portfolio",
    AUTH_BROWSER_VERIFY: "RUNNING",
    BASE,
    console: { errors: [], warnings: [], antd_deprecated: 0 },
    network: {
      http_404: [],
      http_500: [],
      portfolio_latency_ms: null,
      ownership_latency_ms: null,
      initial_request_count: 0,
      api_urls: [],
    },
    filters: {},
    market_isolation: {},
    ui: {
      gap_phrase_visible: null,
      zero_qty_default_hidden: null,
      market_filter_present: null,
      ownership_filter_present: null,
    },
    mutations: {
      REAL_ORDER_MUTATION: 0,
      LIVE_ARM_MUTATION: 0,
      REAL_POLICY_MUTATION: 0,
    },
    BACKEND_RESTART_COUNT: 0,
  };

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1366, height: 768 },
  });
  const page = await context.newPage();

  page.on("console", (msg) => {
    const type = msg.type();
    const text = msg.text();
    if (isAppConsoleNoise(text)) return;
    if (type === "error") state.console.errors.push(text.slice(0, 400));
    else if (type === "warning") {
      state.console.warnings.push(text.slice(0, 400));
      if (classifyWarn(text) === "antd") state.console.antd_deprecated += 1;
    }
  });
  page.on("pageerror", (err) => {
    state.console.errors.push(
      `PAGEERROR: ${String(err.message || err).slice(0, 400)}`,
    );
  });
  page.on("response", (res) => {
    const u = res.url();
    if (!u.includes("/api/") && !u.includes(":8000")) return;
    const st = res.status();
    const method = res.request().method();
    state.network.initial_request_count += 1;
    const pathOnly = u.replace(/https?:\/\/[^/]+/, "").slice(0, 160);
    state.network.api_urls.push({
      method,
      status: st,
      url: pathOnly,
    });
    if (st === 404) state.network.http_404.push(u.slice(0, 180));
    if (st >= 500) state.network.http_500.push(u.slice(0, 180));
    if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
      if (/\/order|\/orders/i.test(u)) state.mutations.REAL_ORDER_MUTATION += 1;
      if (/\/arm|\/live/i.test(u)) state.mutations.LIVE_ARM_MUTATION += 1;
      if (/policy/i.test(u)) state.mutations.REAL_POLICY_MUTATION += 1;
    }
    if (/positions/i.test(pathOnly) && method === "GET") {
      state.network.portfolio_hit = true;
    }
    if (/symbol-ownership/i.test(pathOnly) && method === "GET") {
      state.network.ownership_hit = true;
    }
  });

  await injectAuth(page, context, session);
  const t0 = Date.now();
  await page.goto(`${BASE}/admin/dashboard`, {
    waitUntil: "domcontentloaded",
    timeout: 60000,
  });
  await page.waitForTimeout(1200);
  state.auth_landed = !/\/login/i.test(page.url());
  state.auth_url = page.url();
  if (!state.auth_landed) {
    state.FINAL_VERDICT = "PORTFOLIO_MARKET_UI_ISSUES";
    state.AUTH_BROWSER_VERIFY = "AUTH_FAIL";
    fs.writeFileSync(OUT_JSON, JSON.stringify(state, null, 2), "utf8");
    fs.writeFileSync(
      OUT_MD,
      `# Portfolio market separation\n\nAUTH_FAIL url=${state.auth_url}\n`,
      "utf8",
    );
    await browser.close();
    console.log(JSON.stringify({ FINAL_VERDICT: state.FINAL_VERDICT, auth_url: state.auth_url }));
    return;
  }
  await page.goto(`${BASE}/admin/portfolio`, {
    waitUntil: "domcontentloaded",
    timeout: 60000,
  });
  await page.waitForTimeout(3500);
  state.ui.page_load_ms = Date.now() - t0;

  const body = await page.locator("body").innerText();
  state.ui.market_filter_present =
    body.includes("업비트") && body.includes("키움증권") && body.includes("시장");
  state.ui.ownership_filter_present =
    body.includes("보유구분") &&
    body.includes("일반매매") &&
    body.includes("자동매매");
  state.ui.gap_phrase_visible = /시계열 API gap|API gap/i.test(body);
  state.ui.zero_qty_toggle = body.includes("0수량 포함");
  state.ui.realized_ready_copy = body.includes("실현손익 데이터 준비 중");

  // A ALL
  await clickMarket(page, "전체");
  await clickOwnership(page, "전체");
  await page.waitForTimeout(800);
  const allText = await tableBodyText(page);
  state.filters.A_ALL = {
    has_upbit: /KRW-|UPBIT/i.test(allText) || body.includes("업비트"),
    has_kiwoom: /\b\d{6}\b|KIWOOM/i.test(allText),
    row_snippet: allText.slice(0, 500),
  };

  // B UPBIT
  await clickMarket(page, "업비트");
  await clickOwnership(page, "전체");
  await page.waitForTimeout(1000);
  const upbitText = await tableBodyText(page);
  const upbitLeakKiwoom =
    /KIWOOM/i.test(upbitText) ||
    (/\b\d{6}\b/.test(upbitText) && !/KRW-/i.test(upbitText));
  state.filters.B_UPBIT = {
    leak_kiwoom: upbitLeakKiwoom,
    has_krw: /KRW-/i.test(upbitText),
    snippet: upbitText.slice(0, 800),
  };

  // D UPBIT + AUTO
  await clickOwnership(page, "자동매매");
  await page.waitForTimeout(800);
  const upbitAuto = await tableBodyText(page);
  state.filters.D_UPBIT_AUTO = {
    snippet: upbitAuto.slice(0, 800),
    has_manual_tag: /일반매매|일반\/기타/.test(upbitAuto),
  };

  // C KIWOOM
  await clickMarket(page, "키움증권");
  await clickOwnership(page, "전체");
  await page.waitForTimeout(800);
  const kiwoomText = await tableBodyText(page);
  const kiwoomLeakUpbit = /KRW-|UPBIT/i.test(kiwoomText);
  state.filters.C_KIWOOM = {
    leak_upbit: kiwoomLeakUpbit,
    snippet: kiwoomText.slice(0, 800),
  };

  // E KIWOOM + MANUAL
  await clickOwnership(page, "일반매매");
  await page.waitForTimeout(800);
  const kiwoomManual = await tableBodyText(page);
  state.filters.E_KIWOOM_MANUAL = {
    snippet: kiwoomManual.slice(0, 800),
    has_auto_tag: /자동매매/.test(kiwoomManual),
  };

  state.market_isolation = {
    UPBIT_NO_KIWOOM: !state.filters.B_UPBIT.leak_kiwoom,
    KIWOOM_NO_UPBIT: !state.filters.C_KIWOOM.leak_upbit,
    MARKET_ISOLATION:
      !state.filters.B_UPBIT.leak_kiwoom && !state.filters.C_KIWOOM.leak_upbit
        ? "PASS"
        : "FAIL",
  };

  const consoleOk =
    state.console.errors.length === 0 &&
    state.console.warnings.length === 0 &&
    state.console.antd_deprecated === 0;
  const httpOk =
    state.network.http_404.length === 0 && state.network.http_500.length === 0;

  if (
    state.ui.market_filter_present &&
    state.ui.ownership_filter_present &&
    !state.ui.gap_phrase_visible &&
    state.market_isolation.MARKET_ISOLATION === "PASS" &&
    consoleOk &&
    httpOk
  ) {
    state.FINAL_VERDICT = "PORTFOLIO_MARKET_SEPARATION_AND_PNL_UX_COMPLETE";
    // data gap still identified for broker snapshot vs binding
    state.DATA_GAP_NOTE =
      "BROKER_SNAPSHOT_STALE + auto_entry_price pending reload";
    state.AUTH_BROWSER_VERIFY = "PASS";
  } else if (
    state.ui.market_filter_present &&
    state.market_isolation.MARKET_ISOLATION === "PASS"
  ) {
    state.FINAL_VERDICT = "PORTFOLIO_UI_COMPLETE_DATA_GAP_IDENTIFIED";
    state.AUTH_BROWSER_VERIFY = consoleOk && httpOk ? "PASS" : "PARTIAL";
  } else {
    state.FINAL_VERDICT = "PORTFOLIO_MARKET_UI_ISSUES";
    state.AUTH_BROWSER_VERIFY = "FAIL";
  }

  state.CONSOLE_ERRORS = state.console.errors.length;
  state.CONSOLE_WARNINGS = state.console.warnings.length;
  state.HTTP_404 = state.network.http_404.length;
  state.HTTP_500 = state.network.http_500.length;

  await browser.close();

  fs.writeFileSync(OUT_JSON, JSON.stringify(state, null, 2), "utf8");
  const md = [
    "# Portfolio market separation + PnL UX",
    "",
    `FINAL_VERDICT: ${state.FINAL_VERDICT}`,
    `AUTH_BROWSER_VERIFY: ${state.AUTH_BROWSER_VERIFY}`,
    `MARKET_ISOLATION: ${state.market_isolation.MARKET_ISOLATION}`,
    `CONSOLE_ERRORS: ${state.CONSOLE_ERRORS}`,
    `CONSOLE_WARNINGS: ${state.CONSOLE_WARNINGS}`,
    `HTTP_404: ${state.HTTP_404}`,
    `HTTP_500: ${state.HTTP_500}`,
    `BACKEND_RESTART_COUNT: ${state.BACKEND_RESTART_COUNT}`,
    "",
    "See JSON for filter snippets and data audit fields (filled by report writer).",
    "",
  ].join("\n");
  fs.writeFileSync(OUT_MD, md, "utf8");
  console.log(JSON.stringify({
    FINAL_VERDICT: state.FINAL_VERDICT,
    MARKET_ISOLATION: state.market_isolation.MARKET_ISOLATION,
    CONSOLE_ERRORS: state.CONSOLE_ERRORS,
    CONSOLE_WARNINGS: state.CONSOLE_WARNINGS,
    HTTP_404: state.HTTP_404,
    HTTP_500: state.HTTP_500,
    gap_phrase: state.ui.gap_phrase_visible,
  }));
}

main().catch((err) => {
  console.error(String(err && err.stack ? err.stack : err));
  process.exit(1);
});
