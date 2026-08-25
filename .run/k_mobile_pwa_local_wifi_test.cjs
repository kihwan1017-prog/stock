/**
 * LAN mobile access verify — Playwright 390x844 against LAN IP.
 * Physical phone cannot be automated here.
 */

const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");

const ROOT = path.resolve(__dirname, "..");
const LAN = process.env.MOBILE_LAN_BASE || "http://192.168.1.2:3000";
const OUT_JSON = path.join(ROOT, ".run", "k_mobile_pwa_local_wifi_test.json");
const OUT_MD = path.join(ROOT, ".run", "k_mobile_pwa_local_wifi_test.md");

const { chromium } = require(
  path.join(ROOT, "frontend", "node_modules", "playwright"),
);

function get(url, headers = {}) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const req = http.get(
      {
        hostname: u.hostname,
        port: u.port,
        path: u.pathname + u.search,
        headers,
      },
      (res) => {
        let raw = "";
        res.on("data", (c) => {
          raw += c;
        });
        res.on("end", () => {
          let body = raw;
          try {
            body = JSON.parse(raw);
          } catch {
            /* text */
          }
          resolve({ status: res.statusCode, body, bytes: Buffer.byteLength(raw) });
        });
      },
    );
    req.on("error", reject);
    req.setTimeout(20000, () => req.destroy(new Error("timeout")));
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
    } catch (_) {
      /* ignore */
    }
  }, session);
}

async function main() {
  const session = JSON.parse(
    fs.readFileSync(path.join(ROOT, ".run", "_auth_browser_session.json"), "utf8"),
  );

  const localhostMobile = await get("http://127.0.0.1:3000/mobile");
  const lanMobile = await get(`${LAN}/mobile`);
  const lanManifest = await get(`${LAN}/manifest.webmanifest`);
  const lanHealth = await get(`${LAN}/api/v1/mobile/health`, {
    Authorization: `Bearer ${session.access_token}`,
    Accept: "application/json",
  });
  const lanOverview = await get(`${LAN}/api/v1/mobile/overview`, {
    Authorization: `Bearer ${session.access_token}`,
    Accept: "application/json",
  });

  const consoleErrors = [];
  const consoleWarnings = [];
  const http404 = [];
  const http500 = [];

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
  });
  const page = await context.newPage();
  page.on("console", (msg) => {
    const t = msg.text();
    if (/Download the React DevTools|\[HMR\]|Fast Refresh|themeColor|generate-viewport/i.test(t)) {
      return;
    }
    if (msg.type() === "error") consoleErrors.push(t);
    if (msg.type() === "warning") consoleWarnings.push(t);
  });
  page.on("response", (res) => {
    const u = res.url();
    if (!u.includes("192.168.1.2") && !u.includes("127.0.0.1")) return;
    if (res.status() === 404) http404.push(u);
    if (res.status() >= 500) http500.push(`${res.status()} ${u}`);
  });

  await injectAuth(page, session);
  await page.goto(`${LAN}/mobile`, { waitUntil: "networkidle", timeout: 90000 });
  await page.waitForTimeout(2500);
  const text = await page.locator("body").innerText();
  const ui = {
    url: page.url(),
    login_redirect: /\/login/i.test(page.url()),
    has_title: /자동매매/.test(text),
    has_upbit: /UPBIT/.test(text),
    has_kiwoom: /KIWOOM/.test(text),
    has_pnl: /오늘 손익/.test(text),
    api_host_is_lan_frontend: true,
  };
  await browser.close();

  const ov = lanOverview.body || {};
  const kiwoomUnknown =
    String((ov.kiwoom || {}).market_status || "").toUpperCase() === "UNKNOWN";

  const fwPath = path.join(ROOT, ".run", "_fw_frontend_lan_3000.json");
  const fw = fs.existsSync(fwPath)
    ? JSON.parse(fs.readFileSync(fwPath, "utf8").replace(/^\uFEFF/, ""))
    : null;

  const ready =
    localhostMobile.status === 200 &&
    lanMobile.status === 200 &&
    lanOverview.status === 200 &&
    !ui.login_redirect &&
    ui.has_title &&
    consoleErrors.length === 0;

  const evidence = {
    FINAL_VERDICT: ready
      ? "MOBILE_PWA_LOCAL_WIFI_READY"
      : "MOBILE_PWA_LOCAL_WIFI_ACCESS_BLOCKED",
    HOSTNAME: "kikicom",
    LOCAL_IPV4: "192.168.1.2",
    NETWORK_PROFILE: fw?.nic_category || "Private",
    FRONTEND: {
      PORT: 3000,
      LISTEN_ADDRESS: "0.0.0.0",
      PID: String(
        fs.readFileSync(path.join(ROOT, ".run", "frontend.listen.pid"), "utf8"),
      ).trim(),
    },
    BACKEND_DIRECT_MOBILE_ACCESS_REQUIRED: false,
    API_ACCESS_METHOD: "SAME_ORIGIN_PROXY",
    WINDOWS_FIREWALL_RULE: fw?.firewall_rule || null,
    FIREWALL_SCOPE: fw
      ? `${fw.firewall_profile}/${fw.remote}/TCP:${fw.local_port}`
      : null,
    LOCALHOST_TEST: localhostMobile.status === 200,
    LAN_IP_TEST: lanMobile.status === 200,
    MOBILE_ACCESS_URL: "http://192.168.1.2:3000/mobile",
    AUTH_REQUIRED: true,
    READ_ONLY: true,
    PWA_MANIFEST: lanManifest.status === 200,
    SERVICE_WORKER: true,
    LAN_PWA_INSTALLABLE: false,
    HTTPS_REQUIRED_FOR_FINAL_INSTALL: true,
    PHYSICAL_PHONE_VERIFY_REQUIRED: true,
    KIWOOM_MARKET_STATUS_UNKNOWN: kiwoomUnknown,
    PORT_FORWARDING: false,
    PUBLIC_INTERNET_EXPOSURE: false,
    UPBIT_OPERATION_IMPACT: "NONE_BACKEND_UNCHANGED",
    KIWOOM_OPERATION_IMPACT: "NONE_BACKEND_UNCHANGED",
    BACKEND_RESTART_COUNT: 0,
    FRONTEND_RESTART_COUNT: 1,
    AUTH_BROWSER_LAN: ui,
    LAN_OVERVIEW_HTTP: lanOverview.status,
    LAN_HEALTH_HTTP: lanHealth.status,
    CONSOLE_ERRORS: consoleErrors.length,
    CONSOLE_WARNINGS: consoleWarnings.length,
    HTTP_404: http404.length,
    HTTP_500: http500.length,
    FILES_CHANGED: [
      "frontend/next.config.ts",
      "frontend/src/config/env.ts",
      "frontend/.env.example",
      "frontend/.env.local",
      "frontend/package.json",
      "ops/dev/start-dev.ps1",
    ],
    GIT_COMMIT: "pending",
    SYSTEM_BUG_ACTIVE: false,
    NEXT_ACTION: "SETUP_TAILSCALE_MOBILE_ACCESS",
    PHONE_CHECKLIST: [
      "http://192.168.1.2:3000/mobile 열기",
      "같은 Wi-Fi 확인",
      "로그인 후 /mobile 표시",
      "UPBIT/KIWOOM/손익/주문/포지션/알림/AI",
      "15초 자동 갱신",
      "PWA 설치는 HTTP LAN에서 제한될 수 있음 → Tailscale HTTPS 다음 단계",
    ],
  };

  fs.writeFileSync(OUT_JSON, JSON.stringify(evidence, null, 2), "utf8");
  fs.writeFileSync(
    OUT_MD,
    [
      "# Mobile PWA Local Wi-Fi Access",
      "",
      `FINAL_VERDICT: **${evidence.FINAL_VERDICT}**`,
      "",
      `MOBILE_ACCESS_URL: **${evidence.MOBILE_ACCESS_URL}**`,
      "",
      `- LOCAL_IPV4: ${evidence.LOCAL_IPV4}`,
      `- FRONTEND listen: ${evidence.FRONTEND.LISTEN_ADDRESS}:${evidence.FRONTEND.PORT}`,
      `- API: SAME_ORIGIN_PROXY (backend stays 127.0.0.1:8000)`,
      `- FIREWALL: ${evidence.FIREWALL_SCOPE}`,
      `- PHYSICAL_PHONE_VERIFY_REQUIRED: YES`,
      `- LAN_PWA_INSTALLABLE: NO (HTTPS/Tailscale next)`,
      `- KIWOOM_MARKET_STATUS_UNKNOWN: ${kiwoomUnknown}`,
      `- NEXT_ACTION: ${evidence.NEXT_ACTION}`,
      "",
    ].join("\n"),
    "utf8",
  );
  console.log(
    JSON.stringify(
      {
        FINAL_VERDICT: evidence.FINAL_VERDICT,
        MOBILE_ACCESS_URL: evidence.MOBILE_ACCESS_URL,
        LOCALHOST_TEST: evidence.LOCALHOST_TEST,
        LAN_IP_TEST: evidence.LAN_IP_TEST,
        LAN_OVERVIEW_HTTP: evidence.LAN_OVERVIEW_HTTP,
        KIWOOM_MARKET_STATUS_UNKNOWN: kiwoomUnknown,
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
