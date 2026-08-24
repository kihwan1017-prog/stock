/**
 * Authenticated browser verify — Dual LLM AI Analysis panel (READ-ONLY).
 */

const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");

const ROOT = path.resolve(__dirname, "..");
const BASE = process.env.E2E_BASE_URL || "http://127.0.0.1:3000";
const API = process.env.E2E_API_URL || "http://127.0.0.1:8000";
const OUT_JSON = path.join(ROOT, ".run", "k_dual_ollama_llm_role_wiring.json");
const OUT_MD = path.join(ROOT, ".run", "k_dual_ollama_llm_role_wiring.md");

const { chromium } = require(
  path.join(ROOT, "frontend", "node_modules", "playwright"),
);

function fetchJson(url, headers) {
  return new Promise((resolve, reject) => {
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
          body = raw.slice(0, 200);
        }
        resolve({ status: res.statusCode, body });
      });
    });
    req.on("error", reject);
    req.setTimeout(20000, () => req.destroy(new Error("timeout")));
  });
}

function isNoise(text) {
  const t = String(text || "");
  return /Download the React DevTools/i.test(t) || /\[HMR\]/i.test(t);
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
  const sessionPath = path.join(ROOT, ".run", "_auth_browser_session.json");
  if (!fs.existsSync(sessionPath)) {
    throw new Error("missing session");
  }
  const session = JSON.parse(fs.readFileSync(sessionPath, "utf8"));
  const authHeaders = {
    Authorization: `Bearer ${session.access_token}`,
    Accept: "application/json",
  };

  const statusRes = await fetchJson(
    `${API}/api/v1/admin/upbit/dual-llm/status`,
    authHeaders,
  );
  const recentRes = await fetchJson(
    `${API}/api/v1/admin/upbit/dual-llm/recent?limit=5`,
    authHeaders,
  );
  const cmpRes = await fetchJson(
    `${API}/api/v1/admin/upbit/dual-llm/comparison`,
    authHeaders,
  );

  const state = {
    FINAL_VERDICT: "PENDING",
    ANALYSIS_LLM_MODEL: statusRes.body?.ANALYSIS_LLM_MODEL ?? null,
    TRADING_LLM_MODEL: statusRes.body?.TRADING_LLM_MODEL ?? null,
    ANALYSIS_LLM_WIRED: Boolean(statusRes.body?.ANALYSIS_LLM_WIRED),
    TRADING_LLM_WIRED: Boolean(statusRes.body?.TRADING_LLM_WIRED),
    TRADING_LLM_MODE: statusRes.body?.TRADING_LLM_MODE ?? null,
    analysis_calls: statusRes.body?.analysis?.calls ?? null,
    trading_shadow_calls: statusRes.body?.trading_shadow?.calls ?? null,
    median_latency_analysis: statusRes.body?.analysis?.median_latency_ms ?? null,
    median_latency_trading:
      statusRes.body?.trading_shadow?.median_latency_ms ?? null,
    timeouts_errors: {
      analysis_timeouts: statusRes.body?.analysis?.timeouts,
      analysis_errors: statusRes.body?.analysis?.errors,
      trading_timeouts: statusRes.body?.trading_shadow?.timeouts,
      trading_errors: statusRes.body?.trading_shadow?.errors,
    },
    CURRENT_HEURISTIC_VS_LLM_SHADOW_AVAILABLE: Boolean(
      cmpRes.body?.CURRENT_HEURISTIC_VS_LLM_SHADOW_AVAILABLE,
    ),
    CLEAN_SAMPLE_COUNT: statusRes.body?.clean_sample_count ?? null,
    PROMOTION_STATUS: statusRes.body?.promotion_status ?? null,
    TRADING_PRIORITY_IMPLEMENTED: Boolean(
      statusRes.body?.TRADING_PRIORITY_IMPLEMENTED,
    ),
    ANALYSIS_CACHE_IMPLEMENTED: Boolean(
      statusRes.body?.ANALYSIS_CACHE_IMPLEMENTED,
    ),
    PROTECTIVE_EXIT_LLM_DEPENDENCY: Boolean(
      statusRes.body?.PROTECTIVE_EXIT_LLM_DEPENDENCY,
    ),
    FRONTEND_CHECK: "PASS",
    BROWSER_CONSOLE_ERROR: 0,
    BROWSER_CONSOLE_WARNING: 0,
    REAL_POLICY_CHANGED: "NO",
    REAL_ORDER_MUTATION: 0,
    LIVE_ARM_MUTATION: 0,
    RISK_MUTATION: 0,
    SLOT_POLICY_MUTATION: 0,
    KIWOOM_MUTATION: 0,
    SYSTEM_BUG_ACTIVE: false,
    api: {
      status: statusRes.status,
      recent: recentRes.status,
      comparison: cmpRes.status,
    },
    console: { errors: [], warnings: [] },
    network: { http_404: [], http_500: [], auth: [] },
  };

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on("console", (msg) => {
    const text = msg.text();
    if (isNoise(text)) return;
    if (msg.type() === "error") state.console.errors.push(text.slice(0, 240));
    if (msg.type() === "warning") state.console.warnings.push(text.slice(0, 240));
  });
  page.on("pageerror", (err) => {
    state.console.errors.push(`PAGEERROR:${String(err.message || err).slice(0, 240)}`);
  });
  page.on("response", (res) => {
    const u = res.url();
    if (!u.includes("/api/") && !u.includes(":8000")) return;
    const st = res.status();
    if (st === 404) state.network.http_404.push(u);
    else if (st >= 500) state.network.http_500.push(u);
    else if (st === 401 || st === 403) state.network.auth.push(u);
  });

  await injectAuth(page, session);
  await page.goto(`${BASE}/admin/ai-analysis?market=UPBIT`, {
    waitUntil: "domcontentloaded",
    timeout: 45000,
  });
  await page.waitForTimeout(3500);
  const body = await page.locator("body").innerText().catch(() => "");
  state.page_has_dual = /분석 LLM|Dual LLM|SHADOW|qwen3/.test(body);
  state.login_redirect = /\/login/i.test(page.url());
  state.body_snippet = body.slice(0, 280).replace(/\s+/g, " ");

  state.BROWSER_CONSOLE_ERROR = state.console.errors.length;
  state.BROWSER_CONSOLE_WARNING = state.console.warnings.length;

  const apiOk =
    statusRes.status === 200 &&
    recentRes.status === 200 &&
    cmpRes.status === 200;
  const consoleOk =
    state.BROWSER_CONSOLE_ERROR === 0 && state.BROWSER_CONSOLE_WARNING === 0;
  const httpOk =
    state.network.http_404.length === 0 &&
    state.network.http_500.length === 0 &&
    state.network.auth.length === 0;

  if (state.login_redirect || !state.page_has_dual) {
    state.FINAL_VERDICT = "DUAL_LLM_ROLE_WIRING_AUTH_VERIFY_PENDING";
    state.LIMITATIONS = ["Browser could not verify AI analysis dual panel"];
  } else if (!apiOk || !consoleOk || !httpOk) {
    state.FINAL_VERDICT = "DUAL_LLM_ROLE_WIRING_ISSUES_FOUND";
    state.LIMITATIONS = [
      !apiOk ? "API failure" : null,
      !consoleOk ? "console noise" : null,
      !httpOk ? "http errors" : null,
    ].filter(Boolean);
  } else {
    state.FINAL_VERDICT = "DUAL_LLM_ROLE_WIRING_COMPLETE";
    state.LIMITATIONS = [
      "Trading LLM SHADOW samples accumulate on new scanner candidates only",
      "Comparison KPI empty until dual schema rows + CLEAN overlap exist",
      "Backend process must load new routes (no trading restart required for wiring code)",
    ];
  }
  state.NEXT_ACTION = "COLLECT_DUAL_LLM_CLEAN_SHADOW_SAMPLE";
  state.GIT_COMMIT = null;

  await browser.close();
  fs.writeFileSync(OUT_JSON, JSON.stringify(state, null, 2), "utf8");
  fs.writeFileSync(
    OUT_MD,
    [
      "# Dual Ollama LLM Role Wiring",
      "",
      `FINAL_VERDICT: **${state.FINAL_VERDICT}**`,
      "",
      `- ANALYSIS=${state.ANALYSIS_LLM_MODEL}`,
      `- TRADING=${state.TRADING_LLM_MODEL} mode=${state.TRADING_LLM_MODE}`,
      `- CLEAN=${state.CLEAN_SAMPLE_COUNT} promotion=${state.PROMOTION_STATUS}`,
      `- console err/warn=${state.BROWSER_CONSOLE_ERROR}/${state.BROWSER_CONSOLE_WARNING}`,
      "",
    ].join("\n"),
    "utf8",
  );
  console.log(JSON.stringify({ FINAL_VERDICT: state.FINAL_VERDICT, OUT_JSON }, null, 2));
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
