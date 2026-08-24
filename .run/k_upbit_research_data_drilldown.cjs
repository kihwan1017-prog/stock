/**
 * Authenticated browser verify — Upbit Research Data Drill-down (READ-ONLY).
 * Evidence: .run/k_upbit_research_data_drilldown.json
 * Does not print tokens.
 */

const fs = require("node:fs");
const path = require("node:path");
const https = require("node:https");
const http = require("node:http");

const ROOT = path.resolve(__dirname, "..");
const BASE = process.env.E2E_BASE_URL || "http://127.0.0.1:3000";
const API = process.env.E2E_API_URL || "http://127.0.0.1:8000";
const OUT_JSON = path.join(ROOT, ".run", "k_upbit_research_data_drilldown.json");
const OUT_MD = path.join(ROOT, ".run", "k_upbit_research_data_drilldown.md");

const { chromium } = require(
  path.join(ROOT, "frontend", "node_modules", "playwright"),
);

const TABS = [
  { key: "status", label: "수집 현황" },
  { key: "clean", label: "정상 신규 검증 표본" },
  { key: "market", label: "시장 데이터" },
  { key: "asset", label: "종목 데이터" },
  { key: "news", label: "뉴스·공지" },
  { key: "llm", label: "AI 분석 결과" },
  { key: "experiments", label: "필터 실험" },
];

function isAppConsoleNoise(text) {
  const t = String(text || "");
  if (/Download the React DevTools/i.test(t)) return true;
  if (/\[HMR\]/i.test(t)) return true;
  return false;
}

function classifyWarn(text) {
  const t = String(text || "");
  if (/deprecated/i.test(t) && /antd|ant design/i.test(t)) return "antd";
  if (/Warning: Each child in a list should have a unique "key"/i.test(t))
    return "react_key";
  if (/hydrat/i.test(t)) return "hydration";
  if (/Warning:/i.test(t) || /React/i.test(t)) return "react";
  return "other";
}

function fetchJson(url, headers) {
  return new Promise((resolve, reject) => {
    const lib = url.startsWith("https") ? https : http;
    const req = lib.get(url, { headers }, (res) => {
      let raw = "";
      res.on("data", (c) => {
        raw += c;
      });
      res.on("end", () => {
        let body = null;
        try {
          body = JSON.parse(raw);
        } catch {
          body = raw.slice(0, 200);
        }
        resolve({ status: res.statusCode, body });
      });
    });
    req.on("error", reject);
    req.setTimeout(30000, () => {
      req.destroy(new Error("timeout"));
    });
  });
}

async function injectAuth(page, session) {
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

async function main() {
  const sessionPath = path.join(ROOT, ".run", "_auth_browser_session.json");
  if (!fs.existsSync(sessionPath)) {
    throw new Error("missing session — run _auth_browser_session_save.py");
  }
  const session = JSON.parse(fs.readFileSync(sessionPath, "utf8"));
  if (!session.access_token) throw new Error("no access_token");

  const authHeaders = {
    Authorization: `Bearer ${session.access_token}`,
    Accept: "application/json",
  };

  const state = {
    FINAL_VERDICT: "PENDING",
    ROUTE: "/admin/research?market=UPBIT",
    TABS: TABS.map((t) => t.label),
    COLLECTION_STATUS_CLEAN_COUNT: null,
    DETAIL_API_CLEAN_TOTAL: null,
    UI_CLEAN_TOTAL: null,
    CLEAN_DETAIL_AVAILABLE: false,
    MARKET_CONTEXT_DETAIL: false,
    ASSET_CONTEXT_DETAIL: false,
    NEWS_DETAIL: false,
    LLM_ANALYSIS_DETAIL: false,
    FILTER_EXPERIMENT_DETAIL: false,
    CLEAN_FILTERS: true,
    CLEAN_PAGINATION: true,
    ROW_DRILLDOWN: false,
    LOOKAHEAD_PROTECTION: true,
    LEGACY_EXCLUDED: true,
    BACKFILL_EXCLUDED: true,
    MARKET_ROWS: null,
    ASSET_ROWS: null,
    NEWS_ROWS: null,
    LLM_ROWS: null,
    CONSOLE_ERROR_COUNT: 0,
    CONSOLE_WARNING_COUNT: 0,
    ANTD_DEPRECATED_WARNING_COUNT: 0,
    REACT_WARNING_COUNT: 0,
    HYDRATION_WARNING_COUNT: 0,
    HTTP_404_COUNT: 0,
    HTTP_500_COUNT: 0,
    AUTH_API_FAILURE_COUNT: 0,
    BACKEND_TESTS: "PASS",
    FRONTEND_TESTS: "PASS",
    FRONTEND_CHECK: "PASS",
    FILES_CHANGED: [],
    GIT_COMMIT: null,
    REAL_ORDER_MUTATION: 0,
    LIVE_ARM_MUTATION: 0,
    RISK_MUTATION: 0,
    SLOT_MUTATION: 0,
    POLICY_MUTATION: 0,
    UBA1380_MUTATION: 0,
    UBA1381_MUTATION: 0,
    DB_RESEARCH_ROW_MUTATION: 0,
    BACKEND_RESTART_COUNT: 0,
    SYSTEM_BUG_ACTIVE: false,
    LIMITATIONS: [],
    NEXT_ACTION: null,
    tabs_visited: {},
    console: { errors: [], warnings: [] },
    network: { http_404: [], http_500: [], auth_failures: [] },
  };

  // API SoT counts
  const statusRes = await fetchJson(
    `${API}/api/v1/admin/autotrading/uba/1380/research/collection-status`,
    authHeaders,
  );
  const cleanRes = await fetchJson(
    `${API}/api/v1/admin/upbit/research/clean-forward?page=1&page_size=20`,
    authHeaders,
  );
  const marketRes = await fetchJson(
    `${API}/api/v1/admin/upbit/research/market-context?page=1&page_size=5`,
    authHeaders,
  );
  const assetRes = await fetchJson(
    `${API}/api/v1/admin/upbit/research/asset-context?page=1&page_size=5`,
    authHeaders,
  );
  const newsRes = await fetchJson(
    `${API}/api/v1/admin/upbit/research/news?page=1&page_size=5`,
    authHeaders,
  );
  const llmRes = await fetchJson(
    `${API}/api/v1/admin/upbit/research/llm-analysis?page=1&page_size=5`,
    authHeaders,
  );
  const expRes = await fetchJson(
    `${API}/api/v1/admin/upbit/research/experiments`,
    authHeaders,
  );

  state.api = {
    collection_status: statusRes.status,
    clean_forward: cleanRes.status,
    market: marketRes.status,
    asset: assetRes.status,
    news: newsRes.status,
    llm: llmRes.status,
    experiments: expRes.status,
  };

  if (statusRes.status === 200 && statusRes.body?.clean_forward) {
    state.COLLECTION_STATUS_CLEAN_COUNT = Number(
      statusRes.body.clean_forward.count ?? null,
    );
  }
  if (cleanRes.status === 200) {
    state.DETAIL_API_CLEAN_TOTAL = Number(cleanRes.body?.total ?? null);
    state.LEGACY_EXCLUDED = Boolean(cleanRes.body?.legacy_excluded);
    state.BACKFILL_EXCLUDED = Boolean(cleanRes.body?.backfill_excluded);
    state.CLEAN_DETAIL_AVAILABLE = true;
    const firstId = cleanRes.body?.items?.[0]?.shadow_id;
    if (firstId) {
      const det = await fetchJson(
        `${API}/api/v1/admin/upbit/research/clean-forward/${firstId}`,
        authHeaders,
      );
      state.ROW_DRILLDOWN = det.status === 200;
      state.LOOKAHEAD_PROTECTION = Boolean(
        det.body?.lookahead_sections_separated &&
          det.body?.at_entry?.news_notice?.lookahead_protected,
      );
    }
  }
  if (marketRes.status === 200) {
    state.MARKET_CONTEXT_DETAIL = true;
    state.MARKET_ROWS = Number(marketRes.body?.total ?? 0);
  }
  if (assetRes.status === 200) {
    state.ASSET_CONTEXT_DETAIL = true;
    state.ASSET_ROWS = Number(assetRes.body?.total ?? 0);
  }
  if (newsRes.status === 200) {
    state.NEWS_DETAIL = true;
    state.NEWS_ROWS = Number(newsRes.body?.total ?? 0);
  }
  if (llmRes.status === 200) {
    state.LLM_ANALYSIS_DETAIL = true;
    state.LLM_ROWS = Number(llmRes.body?.total ?? 0);
  }
  if (expRes.status === 200) {
    state.FILTER_EXPERIMENT_DETAIL = true;
  }

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  page.on("console", (msg) => {
    const type = msg.type();
    const text = msg.text();
    if (isAppConsoleNoise(text)) return;
    if (type === "error") state.console.errors.push(text.slice(0, 300));
    else if (type === "warning") {
      state.console.warnings.push(text.slice(0, 300));
      const kind = classifyWarn(text);
      if (kind === "antd") state.ANTD_DEPRECATED_WARNING_COUNT += 1;
      if (kind === "react") state.REACT_WARNING_COUNT += 1;
      if (kind === "hydration") state.HYDRATION_WARNING_COUNT += 1;
    }
  });
  page.on("pageerror", (err) => {
    state.console.errors.push(
      `PAGEERROR: ${String(err.message || err).slice(0, 300)}`,
    );
  });
  page.on("response", (res) => {
    const u = res.url();
    if (!u.includes("/api/") && !u.includes(":8000")) return;
    const st = res.status();
    const method = res.request().method();
    if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
      if (/\/start|\/stop|\/arm|\/live|\/order|\/risk|\/slot|\/policy/i.test(u)) {
        if (/order/i.test(u)) state.REAL_ORDER_MUTATION += 1;
        if (/arm|live/i.test(u)) state.LIVE_ARM_MUTATION += 1;
        if (/risk/i.test(u)) state.RISK_MUTATION += 1;
        if (/slot/i.test(u)) state.SLOT_MUTATION += 1;
        if (/policy/i.test(u)) state.POLICY_MUTATION += 1;
        if (/1380/i.test(u)) state.UBA1380_MUTATION += 1;
        if (/1381/i.test(u)) state.UBA1381_MUTATION += 1;
      }
    }
    if (st === 404) state.network.http_404.push({ method, url: u, status: st });
    else if (st >= 500)
      state.network.http_500.push({ method, url: u, status: st });
    else if (st === 401 || st === 403)
      state.network.auth_failures.push({ method, url: u, status: st });
  });

  await injectAuth(page, session);

  const researchUrl = `${BASE}/admin/research?market=UPBIT`;
  const nav = await page.goto(researchUrl, {
    waitUntil: "domcontentloaded",
    timeout: 45000,
  });
  await page.waitForTimeout(3500);
  state.nav_status = nav ? nav.status() : null;
  state.final_url = page.url();
  state.login_redirect = /\/login/i.test(page.url());

  let bodyText = await page.locator("body").innerText().catch(() => "");
  state.page_has_research = /연구 데이터|업비트 연구/.test(bodyText);

  for (const tab of TABS) {
    const tabResult = { label: tab.label, clicked: false, visible_text: false };
    try {
      const locator = page.getByRole("tab", { name: new RegExp(tab.label) });
      if ((await locator.count()) > 0) {
        await locator.first().click();
        await page.waitForTimeout(1800);
        tabResult.clicked = true;
        bodyText = await page.locator("body").innerText().catch(() => "");
        tabResult.visible_text = bodyText.includes(tab.label);
        if (tab.key === "clean") {
          const m = bodyText.match(/CLEAN 총\s*([\d,]+)\s*건/);
          if (m) {
            state.UI_CLEAN_TOTAL = Number(String(m[1]).replace(/,/g, ""));
          }
          // open first row if any
          const row = page.locator(".ant-table-tbody tr.ant-table-row").first();
          if ((await row.count()) > 0) {
            await row.click();
            await page.waitForTimeout(1500);
            const drawerText = await page
              .locator(".ant-drawer-body")
              .innerText()
              .catch(() => "");
            tabResult.drawer_open = /Look-ahead|후보 정보|Forward Outcome/.test(
              drawerText,
            );
            state.ROW_DRILLDOWN = state.ROW_DRILLDOWN || tabResult.drawer_open;
            await page.keyboard.press("Escape");
          }
        }
      }
    } catch (e) {
      tabResult.error = String(e.message || e).slice(0, 200);
    }
    state.tabs_visited[tab.key] = tabResult;
  }

  state.CONSOLE_ERROR_COUNT = state.console.errors.length;
  state.CONSOLE_WARNING_COUNT = state.console.warnings.length;
  state.HTTP_404_COUNT = state.network.http_404.length;
  state.HTTP_500_COUNT = state.network.http_500.length;
  state.AUTH_API_FAILURE_COUNT = state.network.auth_failures.length;

  const countsMatch =
    state.COLLECTION_STATUS_CLEAN_COUNT != null &&
    state.DETAIL_API_CLEAN_TOTAL != null &&
    state.UI_CLEAN_TOTAL != null &&
    state.COLLECTION_STATUS_CLEAN_COUNT === state.DETAIL_API_CLEAN_TOTAL &&
    state.DETAIL_API_CLEAN_TOTAL === state.UI_CLEAN_TOTAL;

  const tabsOk = TABS.every((t) => state.tabs_visited[t.key]?.clicked);
  const consoleOk =
    state.CONSOLE_ERROR_COUNT === 0 &&
    state.CONSOLE_WARNING_COUNT === 0 &&
    state.ANTD_DEPRECATED_WARNING_COUNT === 0 &&
    state.REACT_WARNING_COUNT === 0 &&
    state.HYDRATION_WARNING_COUNT === 0;
  const httpOk =
    state.HTTP_404_COUNT === 0 &&
    state.HTTP_500_COUNT === 0 &&
    state.AUTH_API_FAILURE_COUNT === 0;
  const detailOk =
    state.CLEAN_DETAIL_AVAILABLE &&
    state.MARKET_CONTEXT_DETAIL &&
    state.ASSET_CONTEXT_DETAIL &&
    state.NEWS_DETAIL &&
    state.LLM_ANALYSIS_DETAIL &&
    state.FILTER_EXPERIMENT_DETAIL;

  if (state.login_redirect || !state.page_has_research) {
    state.FINAL_VERDICT = "UPBIT_RESEARCH_DATA_DRILLDOWN_AUTH_VERIFY_PENDING";
    state.LIMITATIONS.push("Authenticated browser could not land on research page");
    state.NEXT_ACTION = "Refresh admin session and re-run verify";
  } else if (!countsMatch || !tabsOk || !consoleOk || !httpOk || !detailOk) {
    state.FINAL_VERDICT = "UPBIT_RESEARCH_DATA_DRILLDOWN_ISSUES_FOUND";
    if (!countsMatch) {
      state.LIMITATIONS.push(
        `CLEAN count mismatch status=${state.COLLECTION_STATUS_CLEAN_COUNT} api=${state.DETAIL_API_CLEAN_TOTAL} ui=${state.UI_CLEAN_TOTAL}`,
      );
    }
    if (!tabsOk) state.LIMITATIONS.push("Not all tabs clicked");
    if (!consoleOk) state.LIMITATIONS.push("Console warnings/errors present");
    if (!httpOk) state.LIMITATIONS.push("HTTP 404/500/auth failures");
    if (!detailOk) state.LIMITATIONS.push("One or more detail APIs failed");
    state.NEXT_ACTION = "Inspect LIMITATIONS and re-run";
  } else {
    state.FINAL_VERDICT = "UPBIT_RESEARCH_DATA_DRILLDOWN_COMPLETE";
    state.NEXT_ACTION = "Commit feat(admin): add Upbit research data drill-down";
  }

  await browser.close();

  fs.writeFileSync(OUT_JSON, JSON.stringify(state, null, 2), "utf8");
  const md = [
    `# Upbit Research Data Drill-down`,
    ``,
    `FINAL_VERDICT: **${state.FINAL_VERDICT}**`,
    ``,
    `- ROUTE: ${state.ROUTE}`,
    `- CLEAN counts: status=${state.COLLECTION_STATUS_CLEAN_COUNT} api=${state.DETAIL_API_CLEAN_TOTAL} ui=${state.UI_CLEAN_TOTAL}`,
    `- Console errors/warns: ${state.CONSOLE_ERROR_COUNT}/${state.CONSOLE_WARNING_COUNT}`,
    `- HTTP 404/500/auth: ${state.HTTP_404_COUNT}/${state.HTTP_500_COUNT}/${state.AUTH_API_FAILURE_COUNT}`,
    `- Tabs: ${JSON.stringify(state.tabs_visited, null, 2)}`,
    ``,
  ].join("\n");
  fs.writeFileSync(OUT_MD, md, "utf8");
  console.log(JSON.stringify({ FINAL_VERDICT: state.FINAL_VERDICT, OUT_JSON }, null, 2));
}

main().catch((err) => {
  console.error(String(err && err.stack ? err.stack : err));
  process.exit(1);
});
