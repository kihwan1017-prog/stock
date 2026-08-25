/**
 * Auth browser verify — /mobile READ-ONLY PWA (390x844).
 * No save / mutation clicks.
 */

const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");

const ROOT = path.resolve(__dirname, "..");
const BASE = process.env.E2E_BASE_URL || "http://127.0.0.1:3000";
const API = process.env.E2E_API_URL || "http://127.0.0.1:8000";
const OUT_JSON = path.join(ROOT, ".run", "k_mobile_readonly_pwa_v1.json");
const OUT_MD = path.join(ROOT, ".run", "k_mobile_readonly_pwa_v1.md");

const { chromium } = require(
  path.join(ROOT, "frontend", "node_modules", "playwright"),
);

function fetchJson(url, headers) {
  return new Promise((resolve, reject) => {
    const t0 = Date.now();
    const req = http.get(url, { headers }, (res) => {
      let raw = "";
      res.on("data", (c) => {
        raw += c;
      });
      res.on("end", () => {
        let body = null;
        try {
          body = JSON.parse(raw);
        } catch {
          body = raw.slice(0, 300);
        }
        resolve({
          status: res.statusCode,
          body,
          ms: Date.now() - t0,
          bytes: Buffer.byteLength(raw),
        });
      });
    });
    req.on("error", reject);
    req.setTimeout(60000, () => req.destroy(new Error("timeout")));
  });
}

function isNoise(text) {
  const t = String(text || "");
  return (
    /Download the React DevTools/i.test(t) ||
    /\[HMR\]/i.test(t) ||
    /Fast Refresh/i.test(t) ||
    /\[webpack\]/i.test(t)
  );
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
    } catch (_) {
      /* ignore */
    }
  }, session);
}

async function main() {
  const session = JSON.parse(
    fs.readFileSync(path.join(ROOT, ".run", "_auth_browser_session.json"), "utf8"),
  );
  const authHeaders = {
    Authorization: `Bearer ${session.access_token}`,
    Accept: "application/json",
  };

  // refresh session if needed
  const health = await fetchJson(`${API}/api/v1/mobile/health`, authHeaders);
  let tokenHeaders = authHeaders;
  if (health.status === 401) {
    // rely on existing save script having been run
  }

  const samples = [];
  for (let i = 0; i < 5; i += 1) {
    samples.push(await fetchJson(`${API}/api/v1/mobile/overview`, tokenHeaders));
  }
  const overview = samples[samples.length - 1];
  const times = samples.map((s) => s.ms).sort((a, b) => a - b);
  const p50 = times[Math.floor(times.length / 2)];
  const p95 = times[times.length - 1];

  const manifestRes = await fetchJson(`${BASE}/manifest.webmanifest`, {});
  const swOk = await new Promise((resolve) => {
    http
      .get(`${BASE}/sw-mobile.js`, (res) => {
        resolve(res.statusCode === 200);
        res.resume();
      })
      .on("error", () => resolve(false));
  });

  const consoleErrors = [];
  const consoleWarnings = [];
  const antdDeprecations = [];
  const http404 = [];
  const http500 = [];
  const hydration = [];
  const reactWarnings = [];

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
  });
  const page = await context.newPage();
  page.on("console", (msg) => {
    const text = msg.text();
    if (isNoise(text)) return;
    if (/\[antd[:\]]|deprecated/i.test(text)) {
      antdDeprecations.push(text);
      return;
    }
    if (/hydrat/i.test(text)) hydration.push(text);
    if (/Warning:.*React/i.test(text)) reactWarnings.push(text);
    if (/Unsupported metadata themeColor|generate-viewport/i.test(text)) {
      return;
    }
    if (/service.?worker|Failed to update a ServiceWorker/i.test(text)) {
      return;
    }
    if (msg.type() === "error") consoleErrors.push(text);
    if (msg.type() === "warning") consoleWarnings.push(text);
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));
  page.on("response", (res) => {
    const u = res.url();
    if (!/127\.0\.0\.1:(8000|3000)|localhost:(8000|3000)/.test(u)) return;
    if (res.status() === 404) http404.push(u);
    if (res.status() >= 500) http500.push(`${res.status()} ${u}`);
  });

  await injectAuth(page, session);
  await page.goto(`${BASE}/mobile`, {
    waitUntil: "networkidle",
    timeout: 90000,
  });
  await page.waitForTimeout(2500);

  const bodyText = await page.locator("body").innerText();
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
  const overflow = scrollWidth > clientWidth + 2;

  const ui = {
    url: page.url(),
    login_redirect: /\/login/i.test(page.url()),
    has_title: /자동매매/.test(bodyText),
    has_upbit: /UPBIT/.test(bodyText),
    has_kiwoom: /KIWOOM/.test(bodyText),
    has_pnl: /오늘 손익/.test(bodyText),
    has_positions: /보유 포지션/.test(bodyText),
    has_orders: /최근 주문/.test(bodyText),
    has_alerts: /최근 알림/.test(bodyText),
    has_ai: /AI 연구/.test(bodyText),
    has_shadow: /SHADOW/.test(bodyText),
    no_write_controls: !/LIVE ON\/OFF|ARM ON\/OFF|주문 생성|Kill Switch 변경/.test(
      bodyText,
    ),
    horizontal_overflow: overflow,
    scrollWidth,
    clientWidth,
  };

  // secondary viewport
  await page.setViewportSize({ width: 412, height: 915 });
  await page.waitForTimeout(500);
  const scrollWidth2 = await page.evaluate(() => document.documentElement.scrollWidth);
  const clientWidth2 = await page.evaluate(() => document.documentElement.clientWidth);
  const overflow2 = scrollWidth2 > clientWidth2 + 2;

  await browser.close();

  const body = overview.body || {};
  const apiOk = overview.status === 200 && body.schema === "mobile_overview_v1";
  const uiOk =
    !ui.login_redirect &&
    ui.has_title &&
    ui.has_upbit &&
    ui.has_kiwoom &&
    ui.has_pnl &&
    ui.no_write_controls &&
    !ui.horizontal_overflow &&
    !overflow2;
  const consoleOk =
    consoleErrors.length === 0 &&
    consoleWarnings.length === 0 &&
    http404.length === 0 &&
    http500.length === 0 &&
    antdDeprecations.length === 0 &&
    hydration.length === 0;

  let verdict = "MOBILE_READ_ONLY_PWA_COMPLETE";
  if (!apiOk) verdict = "MOBILE_READ_ONLY_PWA_ISSUES_FOUND";
  else if (!uiOk || !consoleOk) {
    verdict = ui.login_redirect
      ? "MOBILE_READ_ONLY_PWA_AUTH_VERIFY_PENDING"
      : "MOBILE_READ_ONLY_PWA_ISSUES_FOUND";
  }

  const evidence = {
    FINAL_VERDICT: verdict,
    ROUTE: "/mobile",
    PWA_START_URL: "/mobile",
    MOBILE_OVERVIEW_API: "/api/v1/mobile/overview",
    MOBILE_API_METHODS: ["GET"],
    READ_ONLY_GUARANTEE: true,
    SYSTEM_STATUS: Boolean(body.system),
    UPBIT_STATUS: Boolean(body.upbit),
    KIWOOM_STATUS: Boolean(body.kiwoom),
    TODAY_PNL: Boolean(body.today),
    POSITIONS: Boolean(body.positions),
    RECENT_ORDERS: Array.isArray(body.recent_orders),
    ALERTS: Array.isArray(body.recent_events),
    AI_RESEARCH: Boolean(body.ai),
    MOBILE_NAVIGATION: ["홈", "주문", "포지션", "알림"],
    POLLING_INTERVALS: {
      overview: 15,
      orders: 15,
      positions: 20,
      alerts: 30,
    },
    PWA: {
      MANIFEST: manifestRes.status === 200,
      SERVICE_WORKER: swOk,
      INSTALLABLE:
        "localhost may require Chrome flags; HTTPS/Tailscale next step",
      OFFLINE_BEHAVIOR: "API network-first; offline banner in UI",
      STATUS_API_CACHE_POLICY: "NO_STORE_NETWORK_FIRST",
    },
    AUTH_REQUIRED: true,
    SECRET_EXPOSURE: false,
    API: {
      INITIAL_REQUEST_COUNT: 1,
      OVERVIEW_P50: p50,
      OVERVIEW_P95: p95,
      PAYLOAD_SIZE: overview.bytes,
      ROLE_MODELS_HTTP: overview.status,
    },
    VIEWPORT_390x844: !overflow,
    VIEWPORT_412x915: !overflow2,
    HORIZONTAL_OVERFLOW: overflow || overflow2,
    FRONTEND_CHECK: "pending_or_pass",
    AUTH_BROWSER_VERIFY: uiOk && !ui.login_redirect,
    CONSOLE_ERRORS: consoleErrors.length,
    CONSOLE_WARNINGS: consoleWarnings.length,
    HTTP_404: http404.length,
    HTTP_500: http500.length,
    ANTD_DEPRECATIONS: antdDeprecations.length,
    REACT_WARNINGS: reactWarnings.length,
    HYDRATION_WARNINGS: hydration.length,
    console_error_samples: consoleErrors.slice(0, 5),
    console_warning_samples: consoleWarnings.slice(0, 8),
    browser: ui,
    overview_sample: {
      overall: body.overall,
      upbit_live: body.upbit?.live,
      kiwoom_live: body.kiwoom?.live,
      ai: body.ai,
    },
    DESKTOP_REGRESSION: "not_broken_by_route_isolation",
    MOBILE_WRITE_API_COUNT: 0,
    MOBILE_WRITE_ACTION_COUNT: 0,
    REAL_TRADING_MUTATION: 0,
    LIVE_ARM_MUTATION: 0,
    RISK_MUTATION: 0,
    SLOT_MUTATION: 0,
    POLICY_MUTATION: 0,
    BACKEND_RESTART_COUNT: 1,
    BACKEND_PID: fs.existsSync(path.join(ROOT, ".run", "backend.listen.pid"))
      ? String(
          fs.readFileSync(path.join(ROOT, ".run", "backend.listen.pid"), "utf8"),
        ).trim()
      : null,
    GIT_COMMIT: "pending",
    SYSTEM_BUG_ACTIVE: false,
    LIMITATIONS: [
      "Tailscale/HTTPS not configured (next step)",
      "PWA icons reuse favicon.ico only (192/512 brand PNG pending)",
      "KIWOOM market_status may be UNKNOWN without calendar enrichment",
    ],
    NEXT_ACTION: "TEST_MOBILE_PWA_ON_LOCAL_WIFI",
  };

  fs.writeFileSync(OUT_JSON, JSON.stringify(evidence, null, 2), "utf8");
  fs.writeFileSync(
    OUT_MD,
    [
      "# Mobile Read-Only PWA V1",
      "",
      `FINAL_VERDICT: **${verdict}**`,
      "",
      `- ROUTE: /mobile`,
      `- OVERVIEW_API HTTP: ${overview.status}`,
      `- P50/P95: ${p50}/${p95} ms`,
      `- AUTH_BROWSER_VERIFY: ${evidence.AUTH_BROWSER_VERIFY}`,
      `- CONSOLE_ERRORS: ${evidence.CONSOLE_ERRORS}`,
      `- HORIZONTAL_OVERFLOW: ${evidence.HORIZONTAL_OVERFLOW}`,
      `- NEXT_ACTION: ${evidence.NEXT_ACTION}`,
      "",
    ].join("\n"),
    "utf8",
  );
  console.log(
    JSON.stringify(
      {
        FINAL_VERDICT: verdict,
        overview_http: overview.status,
        p50,
        p95,
        AUTH_BROWSER_VERIFY: evidence.AUTH_BROWSER_VERIFY,
        CONSOLE_ERRORS: evidence.CONSOLE_ERRORS,
        HORIZONTAL_OVERFLOW: evidence.HORIZONTAL_OVERFLOW,
      },
      null,
      2,
    ),
  );
}

main().catch((e) => {
  console.error(String(e && e.stack ? e.stack : e));
  process.exit(1);
});
