/**
 * Auth browser verify — /admin/orders autotrading monitoring dashboard (READ-ONLY).
 * Tokens never printed.
 */

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const BASE = process.env.E2E_BASE_URL || "http://127.0.0.1:3000";
const OUT_JSON = path.join(ROOT, ".run", "k_order_fill_autotrading_dashboard.json");
const OUT_MD = path.join(ROOT, ".run", "k_order_fill_autotrading_dashboard.md");

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
    throw new Error("missing session — run .run/_auth_browser_session_save.py");
  }
  const session = JSON.parse(fs.readFileSync(sessionPath, "utf8"));
  if (!session.access_token) throw new Error("no access_token");

  const state = {
    FINAL_VERDICT: "PENDING",
    ROUTE: "/admin/orders",
    AUTH_BROWSER_VERIFY: "RUNNING",
    BASE,
    SUMMARY_IMPLEMENTED: false,
    TIMELINE_CHART: false,
    SYMBOL_PNL_CHART: false,
    EXIT_REASON_CHART: false,
    PIPELINE_SUMMARY: false,
    MANUAL_ORDER_MOVED_TO_OPERATIONS_TOOL: false,
    PAPER_ORDER_MOVED_TO_OPERATIONS_TOOL: false,
    TABLE_USER_FRIENDLY: false,
    TRACE_LINK: false,
    PROCESS_VERSION_LINK: false,
    DATA_SOT: {
      orders: "GET /orders",
      pnl_exit: "GET /admin/dashboard/autotrading-performance",
      pipeline: "GET /admin/autotrading/uba/{id}/pipeline-liveness",
      traces: "GET /admin/autotrading/traces",
    },
    console: {
      errors: [],
      warnings: [],
      antd_deprecated: 0,
      react: 0,
      hydration: 0,
    },
    network: { http_404: [], http_500: [], auth_failures: [], mutating: [], reads: [] },
    mutations: {
      REAL_ORDER_MUTATION: 0,
      REAL_POLICY_MUTATION: 0,
      LIVE_ARM_MUTATION: 0,
      DB_BUSINESS_MUTATION: 0,
    },
    ui: {},
    GIT_COMMIT: null,
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
    if (type === "error") {
      state.console.errors.push(text.slice(0, 400));
    } else if (type === "warning") {
      state.console.warnings.push(text.slice(0, 400));
      const kind = classifyWarn(text);
      if (kind === "antd") state.console.antd_deprecated += 1;
      if (kind === "react") state.console.react += 1;
      if (kind === "hydration") state.console.hydration += 1;
    }
  });
  page.on("pageerror", (err) => {
    state.console.errors.push(
      `PAGEERROR: ${String(err.message || err).slice(0, 400)}`,
    );
  });
  page.on("response", (res) => {
    const u = res.url();
    if (!u.includes("/api/") && !u.includes("127.0.0.1:8000")) return;
    const st = res.status();
    const method = res.request().method();
    if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
      state.network.mutating.push({ method, url: u.slice(0, 180), status: st });
      if (/order-execution|\/orders|\/paper-orders/i.test(u)) {
        state.mutations.REAL_ORDER_MUTATION += 1;
      }
      if (/policy/i.test(u)) state.mutations.REAL_POLICY_MUTATION += 1;
      if (/\/arm|\/live/i.test(u)) state.mutations.LIVE_ARM_MUTATION += 1;
    } else {
      state.network.reads.push({ method, url: u.slice(0, 180), status: st });
    }
    if (st === 404) state.network.http_404.push({ method, url: u.slice(0, 180) });
    else if (st >= 500)
      state.network.http_500.push({ method, url: u.slice(0, 180), status: st });
    else if (st === 401 || st === 403)
      state.network.auth_failures.push({
        method,
        url: u.slice(0, 180),
        status: st,
      });
  });

  await injectAuth(page, session);
  await page.goto(`${BASE}/admin/dashboard`, {
    waitUntil: "domcontentloaded",
    timeout: 45000,
  });
  await page.waitForTimeout(1200);

  const resp = await page.goto(`${BASE}/admin/orders`, {
    waitUntil: "domcontentloaded",
    timeout: 45000,
  });
  await page.waitForTimeout(5000);
  state.auth_landed = !/\/login/i.test(page.url());

  const body = await page.locator("body").innerText().catch(() => "");

  state.SUMMARY_IMPLEMENTED =
    /오늘 매수/.test(body) &&
    /오늘 매도/.test(body) &&
    /실현손익/.test(body) &&
    /승\/패|승률/.test(body);
  state.TIMELINE_CHART = /오늘 체결 흐름/.test(body);
  state.SYMBOL_PNL_CHART = /종목별 실현손익/.test(body);
  state.EXIT_REASON_CHART = /매도 사유별 성과/.test(body);
  state.PIPELINE_SUMMARY = /파이프라인/.test(body);
  state.TABLE_USER_FRIENDLY =
    /오늘 주문 목록/.test(body) &&
    /자동\/수동/.test(body) &&
    !/POST \/order-execution\/submit/.test(body);
  state.PROCESS_VERSION_LINK = /프로세스·버전/.test(body);

  // 운영 도구 Collapse — 기본 화면에서 수동 주문 폼 숨김
  const opsHeader = page.locator(".ant-collapse-header").filter({
    hasText: "운영 도구",
  });
  const opsCount = await opsHeader.count();
  const warningVisibleBefore = await page
    .getByText("수동 주문은 자동매매 외 운영 작업입니다.")
    .isVisible()
    .catch(() => false);
  if (opsCount > 0) {
    await opsHeader.first().click();
    await page.waitForTimeout(1000);
  }
  const warningVisibleAfter = await page
    .getByText("수동 주문은 자동매매 외 운영 작업입니다.")
    .isVisible()
    .catch(() => false);
  const manualBtnVisible = await page
    .getByRole("button", { name: "수동 주문" })
    .first()
    .isVisible()
    .catch(() => false);
  state.MANUAL_ORDER_MOVED_TO_OPERATIONS_TOOL =
    opsCount > 0 &&
    !warningVisibleBefore &&
    warningVisibleAfter &&
    manualBtnVisible;

  const paperHeader = page.locator(".ant-collapse-header").filter({
    hasText: "Paper 주문 테스트",
  });
  if ((await paperHeader.count()) > 0) {
    await paperHeader.first().click();
    await page.waitForTimeout(800);
  }
  const paperBtnVisible = await page
    .getByRole("button", { name: "Paper 주문" })
    .first()
    .isVisible()
    .catch(() => false);
  state.PAPER_ORDER_MOVED_TO_OPERATIONS_TOOL =
    (await paperHeader.count()) > 0 && paperBtnVisible;

  // Detail drawer
  const detailBtn = page.getByText("보기", { exact: true });
  if ((await detailBtn.count()) > 0) {
    await detailBtn.first().click();
    await page.waitForTimeout(1500);
    const drawerText = await page
      .locator(".ant-drawer-body")
      .innerText()
      .catch(() => "");
    state.TRACE_LINK =
      /Decision Trace|프로세스·버전|주문 상세/.test(drawerText) ||
      /주문 상세/.test(await page.locator("body").innerText());
    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);
  } else {
    state.TRACE_LINK = state.PROCESS_VERSION_LINK;
  }

  state.ui = {
    nav_status: resp ? resp.status() : null,
    final_url: page.url(),
    login_redirect: /\/login/i.test(page.url()),
    has_market_filter: /업비트|키움증권|전체/.test(body),
    has_ops_collapse: opsCount > 0,
    no_endpoint_main_label: !/POST \/order-execution\/submit/.test(body),
    empty_state_friendly: !/\bNo data\b/i.test(body),
    body_snippet: body.slice(0, 600).replace(/\s+/g, " "),
  };

  const mutSum = Object.values(state.mutations).reduce((a, b) => a + b, 0);
  const consoleClean =
    state.console.errors.length === 0 &&
    state.console.warnings.length === 0 &&
    state.console.antd_deprecated === 0;
  const httpClean =
    state.network.http_404.length === 0 && state.network.http_500.length === 0;

  const uiOk =
    state.auth_landed &&
    !state.ui.login_redirect &&
    state.SUMMARY_IMPLEMENTED &&
    state.TIMELINE_CHART &&
    state.SYMBOL_PNL_CHART &&
    state.EXIT_REASON_CHART &&
    state.PIPELINE_SUMMARY &&
    state.MANUAL_ORDER_MOVED_TO_OPERATIONS_TOOL &&
    state.PAPER_ORDER_MOVED_TO_OPERATIONS_TOOL &&
    state.TABLE_USER_FRIENDLY &&
    state.PROCESS_VERSION_LINK &&
    mutSum === 0 &&
    httpClean;

  if (uiOk && consoleClean) {
    state.FINAL_VERDICT = "ORDER_FILL_AUTOTRADING_DASHBOARD_COMPLETE";
  } else if (!state.auth_landed || state.ui.login_redirect) {
    state.FINAL_VERDICT = "ORDER_FILL_DASHBOARD_AUTH_VERIFY_PENDING";
  } else {
    state.FINAL_VERDICT = "ORDER_FILL_DASHBOARD_ISSUES_FOUND";
  }

  state.AUTH_BROWSER_VERIFY = state.auth_landed ? "PASS" : "FAIL";
  state.CONSOLE_ERRORS = state.console.errors.length;
  state.CONSOLE_WARNINGS = state.console.warnings.length;
  state.REAL_ORDER_MUTATION = state.mutations.REAL_ORDER_MUTATION;
  state.REAL_POLICY_MUTATION = state.mutations.REAL_POLICY_MUTATION;

  await browser.close();

  // trim large arrays in evidence
  state.network.reads = state.network.reads.slice(0, 40);
  state.console.errors = state.console.errors.slice(0, 20);
  state.console.warnings = state.console.warnings.slice(0, 20);

  fs.writeFileSync(OUT_JSON, JSON.stringify(state, null, 2), "utf8");

  const md = [
    "# Order/Fill Autotrading Dashboard — Evidence",
    "",
    `- FINAL_VERDICT: **${state.FINAL_VERDICT}**`,
    `- ROUTE: ${state.ROUTE}`,
    `- AUTH_BROWSER_VERIFY: ${state.AUTH_BROWSER_VERIFY}`,
    `- SUMMARY_IMPLEMENTED: ${state.SUMMARY_IMPLEMENTED}`,
    `- TIMELINE_CHART: ${state.TIMELINE_CHART}`,
    `- SYMBOL_PNL_CHART: ${state.SYMBOL_PNL_CHART}`,
    `- EXIT_REASON_CHART: ${state.EXIT_REASON_CHART}`,
    `- PIPELINE_SUMMARY: ${state.PIPELINE_SUMMARY}`,
    `- MANUAL_ORDER_MOVED_TO_OPERATIONS_TOOL: ${state.MANUAL_ORDER_MOVED_TO_OPERATIONS_TOOL}`,
    `- PAPER_ORDER_MOVED_TO_OPERATIONS_TOOL: ${state.PAPER_ORDER_MOVED_TO_OPERATIONS_TOOL}`,
    `- TABLE_USER_FRIENDLY: ${state.TABLE_USER_FRIENDLY}`,
    `- TRACE_LINK: ${state.TRACE_LINK}`,
    `- PROCESS_VERSION_LINK: ${state.PROCESS_VERSION_LINK}`,
    `- CONSOLE_ERRORS: ${state.CONSOLE_ERRORS}`,
    `- CONSOLE_WARNINGS: ${state.CONSOLE_WARNINGS}`,
    `- REAL_ORDER_MUTATION: ${state.REAL_ORDER_MUTATION}`,
    `- REAL_POLICY_MUTATION: ${state.REAL_POLICY_MUTATION}`,
    `- http_404: ${state.network.http_404.length}`,
    `- http_500: ${state.network.http_500.length}`,
    "",
    "## DATA_SOT",
    "```json",
    JSON.stringify(state.DATA_SOT, null, 2),
    "```",
    "",
    "## UI",
    "```json",
    JSON.stringify(state.ui, null, 2),
    "```",
    "",
  ].join("\n");
  fs.writeFileSync(OUT_MD, md, "utf8");
  console.log(state.FINAL_VERDICT);
}

main().catch((err) => {
  const fail = {
    FINAL_VERDICT: "ORDER_FILL_DASHBOARD_AUTH_VERIFY_PENDING",
    error: String(err && err.message ? err.message : err).slice(0, 500),
  };
  fs.writeFileSync(OUT_JSON, JSON.stringify(fail, null, 2), "utf8");
  fs.writeFileSync(
    OUT_MD,
    `# Pending\n\n${fail.FINAL_VERDICT}\n\n${fail.error}\n`,
    "utf8",
  );
  console.error(fail.FINAL_VERDICT, fail.error);
  process.exitCode = 1;
});
