/**
 * Authenticated browser verify — System Status user-friendly UI (READ-ONLY).
 * No tokens printed. Evidence only.
 */

const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const BASE = process.env.E2E_BASE_URL || "http://127.0.0.1:3000";
const OUT_JSON = path.join(ROOT, ".run", "k_system_status_user_friendly_ui.json");
const OUT_MD = path.join(ROOT, ".run", "k_system_status_user_friendly_ui.md");

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
    ROUTE: "/admin/monitoring",
    AUTH_BROWSER_VERIFY: "RUNNING",
    BASE,
    console: {
      errors: [],
      warnings: [],
      antd_deprecated: 0,
      react: 0,
      hydration: 0,
    },
    network: { http_404: [], http_500: [], auth_failures: [], mutating: [] },
    mutations: {
      REAL_ORDER_MUTATION: 0,
      CANCEL_AMEND_MUTATION: 0,
      LIVE_ARM_MUTATION: 0,
      POLICY_MUTATION: 0,
      RISK_MUTATION: 0,
      SLOT_POLICY_MUTATION: 0,
      UPBIT_TRADING_MUTATION: 0,
      KIWOOM_TRADING_MUTATION: 0,
      DB_MUTATION: 0,
    },
    ui: {},
  };

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1366, height: 768 } });
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
    state.console.errors.push(`PAGEERROR: ${String(err.message || err).slice(0, 400)}`);
  });
  page.on("response", (res) => {
    const u = res.url();
    if (!u.includes("/api/") && !u.includes("127.0.0.1:8000")) return;
    const st = res.status();
    const method = res.request().method();
    if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
      state.network.mutating.push({ method, url: u.slice(0, 180), status: st });
      if (/\/order|\/orders/i.test(u)) state.mutations.REAL_ORDER_MUTATION += 1;
      if (/cancel|amend/i.test(u)) state.mutations.CANCEL_AMEND_MUTATION += 1;
      if (/\/arm|\/live/i.test(u)) state.mutations.LIVE_ARM_MUTATION += 1;
      if (/policy/i.test(u)) state.mutations.POLICY_MUTATION += 1;
      if (/risk/i.test(u)) state.mutations.RISK_MUTATION += 1;
      if (/slot/i.test(u)) state.mutations.SLOT_POLICY_MUTATION += 1;
      if (/upbit/i.test(u) && /order|trade|arm|live/i.test(u))
        state.mutations.UPBIT_TRADING_MUTATION += 1;
      if (/kiwoom/i.test(u) && /order|trade|arm|live/i.test(u))
        state.mutations.KIWOOM_TRADING_MUTATION += 1;
    }
    if (st === 404) state.network.http_404.push({ method, url: u.slice(0, 180) });
    else if (st >= 500)
      state.network.http_500.push({ method, url: u.slice(0, 180), status: st });
    else if (st === 401 || st === 403)
      state.network.auth_failures.push({ method, url: u.slice(0, 180), status: st });
  });

  await injectAuth(page, session);

  await page.goto(`${BASE}/admin/dashboard`, {
    waitUntil: "domcontentloaded",
    timeout: 45000,
  });
  await page.waitForTimeout(1500);
  {
    const u = page.url();
    state.auth_landed = !/\/login/i.test(u);
    state.auth_url = u;
  }

  const resp = await page.goto(`${BASE}/admin/monitoring`, {
    waitUntil: "domcontentloaded",
    timeout: 45000,
  });
  await page.waitForTimeout(4500);

  const body = await page.locator("body").innerText().catch(() => "");
  const collapseDev = await page.getByText("개발자 상세 보기").count();
  const preLocator = page.locator("pre");
  const preCount = await preLocator.count();
  let preVisibleDefault = false;
  for (let i = 0; i < preCount; i += 1) {
    if (await preLocator.nth(i).isVisible().catch(() => false)) {
      preVisibleDefault = true;
      break;
    }
  }
  if (collapseDev > 0) {
    await page.getByText("개발자 상세 보기").first().click();
    await page.waitForTimeout(500);
  }
  let preVisibleAfterOpen = false;
  for (let i = 0; i < (await preLocator.count()); i += 1) {
    if (await preLocator.nth(i).isVisible().catch(() => false)) {
      preVisibleAfterOpen = true;
      break;
    }
  }

  state.ui = {
    nav_status: resp ? resp.status() : null,
    final_url: page.url(),
    login_redirect: /\/login/i.test(page.url()),
    has_title: /시스템 상태/.test(body),
    has_overall: /전체 상태|정상 운영|일부 확인 필요|자동매매 중지|오류/.test(body),
    has_common_tab: /공통/.test(body),
    has_upbit_tab: /업비트/.test(body),
    has_kiwoom_tab: /키움/.test(body),
    has_refresh: /새로고침|마지막 갱신/.test(body),
    has_blockers_section: /차단 원인|자동매매 가능|확인 필요/.test(body),
    has_dev_collapse: collapseDev > 0,
    raw_pre_visible_by_default: preVisibleDefault,
    raw_pre_visible_after_dev_open: preVisibleAfterOpen,
    body_snippet: body.slice(0, 500).replace(/\s+/g, " "),
    no_undefined_literal: !/\bundefined\b/.test(body),
    no_nan_literal: !/\bNaN\b/.test(body),
    no_admin_json_card_titles: !/Database \(JSON\)|Broker \(JSON\)|Resources \(JSON\)/i.test(
      body,
    ),
  };

  // Tab switch smoke
  for (const label of ["공통", "업비트", "키움", "전체"]) {
    const tab = page.getByRole("tab", { name: label });
    if (await tab.count()) {
      await tab.first().click();
      await page.waitForTimeout(600);
    }
  }
  const bodyAfterTabs = await page.locator("body").innerText().catch(() => "");
  state.ui.tabs_ok =
    /공통 시스템|업비트|키움/.test(bodyAfterTabs) &&
    !state.ui.login_redirect;

  const mutSum = Object.values(state.mutations).reduce((a, b) => a + b, 0);
  const consoleClean =
    state.console.errors.length === 0 &&
    state.console.warnings.length === 0 &&
    state.console.antd_deprecated === 0 &&
    state.console.react === 0 &&
    state.console.hydration === 0;

  const uiOk =
    state.auth_landed &&
    state.ui.has_title &&
    state.ui.has_overall &&
    state.ui.has_dev_collapse &&
    !state.ui.raw_pre_visible_by_default &&
    state.ui.raw_pre_visible_after_dev_open &&
    state.ui.has_upbit_tab &&
    state.ui.has_kiwoom_tab &&
    state.ui.no_undefined_literal &&
    state.ui.no_admin_json_card_titles &&
    mutSum === 0;

  if (uiOk && consoleClean) {
    state.FINAL_VERDICT = "SYSTEM_STATUS_USER_FRIENDLY_UI_COMPLETE";
  } else if (uiOk && !consoleClean) {
    state.FINAL_VERDICT = "SYSTEM_STATUS_UI_ISSUES_FOUND";
  } else if (!state.auth_landed || state.ui.login_redirect) {
    state.FINAL_VERDICT = "SYSTEM_STATUS_USER_FRIENDLY_UI_AUTH_VERIFY_PENDING";
  } else {
    state.FINAL_VERDICT = "SYSTEM_STATUS_UI_ISSUES_FOUND";
  }

  state.AUTH_BROWSER_VERIFY = state.auth_landed ? "PASS" : "FAIL";
  state.CONSOLE_ERRORS = state.console.errors.length;
  state.CONSOLE_WARNINGS = state.console.warnings.length;
  state.RAW_JSON_PRESERVED = state.ui.has_dev_collapse;
  state.RAW_JSON_LOCATION = "Collapse: 개발자 상세 보기";

  await browser.close();

  fs.writeFileSync(OUT_JSON, JSON.stringify(state, null, 2), "utf8");

  const md = [
    "# System Status User-Friendly UI — Evidence",
    "",
    `- FINAL_VERDICT: **${state.FINAL_VERDICT}**`,
    `- ROUTE: ${state.ROUTE}`,
    `- AUTH_BROWSER_VERIFY: ${state.AUTH_BROWSER_VERIFY}`,
    `- CONSOLE_ERRORS: ${state.CONSOLE_ERRORS}`,
    `- CONSOLE_WARNINGS: ${state.CONSOLE_WARNINGS}`,
    `- RAW_JSON_PRESERVED: ${state.RAW_JSON_PRESERVED}`,
    `- RAW_JSON_LOCATION: ${state.RAW_JSON_LOCATION}`,
    `- mutations_sum: ${mutSum}`,
    "",
    "## UI flags",
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
    FINAL_VERDICT: "SYSTEM_STATUS_USER_FRIENDLY_UI_AUTH_VERIFY_PENDING",
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
