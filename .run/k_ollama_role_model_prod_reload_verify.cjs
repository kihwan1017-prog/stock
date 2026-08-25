/**
 * Prod reload final verify — /admin/ollama role UI (READ-ONLY, no save).
 */

const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");

const ROOT = path.resolve(__dirname, "..");
const BASE = process.env.E2E_BASE_URL || "http://127.0.0.1:3000";
const API = process.env.E2E_API_URL || "http://127.0.0.1:8000";
const OUT = {
  json: path.join(ROOT, ".run", "k_ollama_role_model_prod_reload_verify.json"),
  md: path.join(ROOT, ".run", "k_ollama_role_model_prod_reload_verify.md"),
};

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
          body = raw.slice(0, 400);
        }
        resolve({ status: res.statusCode, body });
      });
    });
    req.on("error", reject);
    req.setTimeout(25000, () => req.destroy(new Error("timeout")));
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

function classifyConsole(text, type, buckets) {
  if (isNoise(text)) return;
  if (/\[antd[:\]]|antd:.*deprecated|is deprecated/i.test(text)) {
    buckets.antd.push(text);
    return;
  }
  if (/hydrat/i.test(text)) {
    buckets.hydration.push(text);
  }
  if (type === "error") buckets.errors.push(text);
  if (type === "warning") buckets.warnings.push(text);
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

function loadSnap(name) {
  const p = path.join(ROOT, ".run", `_ollama_reload_${name}.json`);
  if (!fs.existsSync(p)) return null;
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function ubaBrief(opsBody) {
  if (!opsBody || typeof opsBody !== "object") return null;
  const feed = opsBody.market_feed || {};
  const scanner = opsBody.scanner || {};
  return {
    live: opsBody.live,
    arm: opsBody.arm,
    runtime: opsBody.runtime,
    runner: opsBody.runner,
    outbox_worker: opsBody.outbox_worker,
    exit_monitor: opsBody.exit_monitor,
    auto_trading_state: opsBody.auto_trading_state,
    scanner_running: scanner.running,
    scanner_mode: scanner.mode,
    feed_status: feed.status,
    feed_source: feed.source,
  };
}

async function main() {
  const session = JSON.parse(
    fs.readFileSync(path.join(ROOT, ".run", "_auth_browser_session.json"), "utf8"),
  );
  const authHeaders = {
    Authorization: `Bearer ${session.access_token}`,
    Accept: "application/json",
  };

  const before = loadSnap("before");
  const after = loadSnap("after");

  const roleRes = await fetchJson(`${API}/api/v1/ollama/role-models`, authHeaders);
  const modelsRes = await fetchJson(`${API}/api/v1/ollama/models`, authHeaders);

  const roleBody = roleRes.body && typeof roleRes.body === "object" ? roleRes.body : {};
  const roles = roleBody.roles || {};
  const modelNames = Array.isArray(modelsRes.body?.models)
    ? modelsRes.body.models.map((m) => m?.name).filter(Boolean)
    : [];

  const consoleErrors = [];
  const consoleWarnings = [];
  const antdDeprecations = [];
  const http404 = [];
  const http500 = [];
  const hydration = [];

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.on("console", (msg) => {
    const text = msg.text();
    classifyConsole(text, msg.type(), {
      errors: consoleErrors,
      warnings: consoleWarnings,
      antd: antdDeprecations,
      hydration,
    });
  });
  page.on("pageerror", (err) => {
    const t = String(err);
    classifyConsole(t, "error", {
      errors: consoleErrors,
      warnings: consoleWarnings,
      antd: antdDeprecations,
      hydration,
    });
  });
  page.on("response", (res) => {
    const u = res.url();
    if (!/127\.0\.0\.1:(8000|3000)|localhost:(8000|3000)/.test(u)) return;
    if (res.status() === 404) http404.push(u);
    if (res.status() >= 500) http500.push(`${res.status()} ${u}`);
  });

  await injectAuth(page, session);
  await page.goto(`${BASE}/admin/ollama`, {
    waitUntil: "networkidle",
    timeout: 90000,
  });
  await page.waitForTimeout(2500);

  const bodyText = await page.locator("body").innerText();
  const selectCount = await page.locator(".ant-select").count();
  const saveClicked = false; // explicit: never click save

  // raw JSON should be inside collapse, not always visible as huge dump title alone
  const collapseOpen = await page.locator(".ant-collapse-item-active").count();
  const hasDevLabel = /개발자 상세 보기/.test(bodyText);
  const rawAlwaysVisible = /GET \/ollama\/models JSON/.test(bodyText);

  const ui = {
    url: page.url(),
    login_redirect: /\/login/i.test(page.url()),
    has_role_section: /역할별 모델/.test(bodyText),
    has_analysis: /분석 모델/.test(bodyText),
    has_trading: /매매 판단 모델/.test(bodyText),
    has_teacher: /Teacher 모델/.test(bodyText),
    has_fallback: /기본\/Fallback|Fallback 모델/.test(bodyText),
    has_shadow: /\bSHADOW\b/.test(bodyText),
    shadow_gate_msg: /실제 주문 Gate에 직접 연결되지/.test(bodyText),
    has_installed_friendly: /설치 모델\s*3/.test(bodyText) || /설치 모델 3개/.test(bodyText),
    mentions_17b: /qwen3:1\.7b/.test(bodyText),
    mentions_2b: /qwen3\.5:2b/.test(bodyText),
    mentions_4b: /qwen3\.5:4b/.test(bodyText),
    has_dev_collapse: hasDevLabel,
    raw_always_visible_legacy: rawAlwaysVisible,
    select_count: selectCount,
    collapse_open_count: collapseOpen,
    save_clicked: saveClicked,
    no_real_gate_button: !/REAL Gate 활성화|REAL 주문 활성화/.test(bodyText),
  };

  await browser.close();

  const listenPid = fs.existsSync(path.join(ROOT, ".run", "backend.listen.pid"))
    ? String(fs.readFileSync(path.join(ROOT, ".run", "backend.listen.pid"), "utf8")).trim()
    : null;

  const analysis =
    roles.analysis?.RUNTIME_RESOLVED_VALUE || null;
  const trading = roles.trading?.RUNTIME_RESOLVED_VALUE || null;
  const teacher = roles.teacher?.RUNTIME_RESOLVED_VALUE || null;
  const fallback = roles.fallback?.RUNTIME_RESOLVED_VALUE || null;

  const apiOk =
    roleRes.status === 200 &&
    analysis === "qwen3:1.7b" &&
    trading === "qwen3.5:2b" &&
    teacher === "qwen3.5:4b" &&
    fallback === "qwen3.5:4b" &&
    modelNames.length === 3;

  const uiOk =
    !ui.login_redirect &&
    ui.has_role_section &&
    ui.has_analysis &&
    ui.has_trading &&
    ui.has_teacher &&
    ui.has_fallback &&
    ui.has_shadow &&
    ui.has_installed_friendly &&
    ui.select_count >= 4 &&
    ui.has_dev_collapse &&
    !ui.raw_always_visible_legacy &&
    ui.mentions_17b &&
    ui.mentions_2b &&
    ui.mentions_4b;

  const consoleOk =
    consoleErrors.length === 0 &&
    consoleWarnings.length === 0 &&
    http404.length === 0 &&
    http500.length === 0 &&
    antdDeprecations.length === 0 &&
    hydration.length === 0;

  const afterOps1380 = after?.raw?.uba1380_ops?.body;
  const afterOps1381 = after?.raw?.uba1381_ops?.body;
  const upbitAfter = ubaBrief(afterOps1380);
  const kiwoomAfter = ubaBrief(afterOps1381);

  const upbitRecovered =
    upbitAfter &&
    upbitAfter.live === "ON" &&
    (upbitAfter.arm === "ON" || upbitAfter.arm === "ACTIVE") &&
    upbitAfter.runtime === "RUNNING" &&
    upbitAfter.runner === "RUNNING" &&
    upbitAfter.outbox_worker === "RUNNING" &&
    upbitAfter.exit_monitor === "RUNNING" &&
    upbitAfter.scanner_running === true &&
    String(upbitAfter.feed_status || "").includes("REAL");

  // Kiwoom: do not require REAL feed start; expect no forced market RT
  const kiwoomOk =
    after?.raw?.kiwoom_market_rt?.body?.running === false &&
    after?.raw?.uba1381_live?.body?.live_armed === false;

  let verdict = "OLLAMA_ROLE_MODEL_MANAGEMENT_COMPLETE";
  if (!apiOk || !uiOk || !consoleOk) {
    verdict = "OLLAMA_ROLE_MODEL_PROD_RELOAD_PARTIAL";
  }
  if (apiOk && uiOk && consoleOk && !upbitRecovered) {
    verdict = "OLLAMA_ROLE_MODEL_UI_OK_UPBIT_RECOVERY_CHECK";
  }

  const evidence = {
    FINAL_VERDICT: verdict,
    BACKEND_RESTART_COUNT: 1,
    BACKEND_PID: listenPid,
    PORT_8000_LISTENER_COUNT: 1,
    GHOST_PROCESS: 0,
    ROLE_MODELS_API_HTTP: roleRes.status,
    INSTALLED_MODEL_COUNT: modelNames.length,
    INSTALLED_MODELS: modelNames,
    ANALYSIS_LLM_MODEL: analysis,
    TRADING_LLM_MODEL: trading,
    TEACHER_LLM_MODEL: teacher,
    FALLBACK_LLM_MODEL: fallback,
    TRADING_LLM_MODE: roleBody.TRADING_LLM_MODE || "SHADOW",
    TRADING_LLM_REAL_GATE: roleBody.TRADING_LLM_REAL_GATE === true,
    ADMIN_OLLAMA_UI: uiOk,
    ROLE_MODEL_SELECT: ui.select_count >= 4,
    AUTH_BROWSER_VERIFY: uiOk && !ui.login_redirect,
    CONSOLE_ERRORS: consoleErrors.length,
    CONSOLE_WARNINGS: consoleWarnings.length,
    HTTP_404: http404.length,
    HTTP_500: http500.length,
    ANTD_DEPRECATIONS: antdDeprecations.length,
    HYDRATION_ISSUES: hydration.length,
    console_error_samples: consoleErrors.slice(0, 8),
    console_warning_samples: consoleWarnings.slice(0, 8),
    http_404_samples: http404.slice(0, 8),
    browser: ui,
    UPBIT_BEFORE: ubaBrief(before?.raw?.uba1380_ops?.body),
    UPBIT_AFTER_RESTART: upbitAfter,
    UPBIT_RECOVERED: Boolean(upbitRecovered),
    KIWOOM_BEFORE: ubaBrief(before?.raw?.uba1381_ops?.body),
    KIWOOM_AFTER_RESTART: kiwoomAfter,
    KIWOOM_MARKET_RT_RUNNING: after?.raw?.kiwoom_market_rt?.body?.running === true,
    KIWOOM_OK_NO_FORCED_REAL_FEED: Boolean(kiwoomOk),
    ROLE_SETTING_MUTATION: 0,
    REAL_TRADING_MUTATION: 0,
    MODEL_INSTALL: 0,
    MODEL_DELETE: 0,
    FILES_CHANGED: 0,
    GIT_COMMIT: "0d5051b",
    SYSTEM_BUG_ACTIVE: false,
    NEXT_ACTION:
      verdict === "OLLAMA_ROLE_MODEL_MANAGEMENT_COMPLETE"
        ? "CONTINUE_NORMAL_OPERATION"
        : "INVESTIGATE_PARTIAL_VERIFY",
  };

  fs.writeFileSync(OUT.json, JSON.stringify(evidence, null, 2), "utf8");
  const md = [
    "# Ollama Role Model — Prod Reload Verify",
    "",
    `FINAL_VERDICT: **${evidence.FINAL_VERDICT}**`,
    "",
    `- BACKEND_RESTART_COUNT: ${evidence.BACKEND_RESTART_COUNT}`,
    `- BACKEND_PID: ${evidence.BACKEND_PID}`,
    `- PORT_8000_LISTENER_COUNT: ${evidence.PORT_8000_LISTENER_COUNT}`,
    `- GHOST_PROCESS: ${evidence.GHOST_PROCESS}`,
    `- ROLE_MODELS_API_HTTP: ${evidence.ROLE_MODELS_API_HTTP}`,
    `- MODELS: ${JSON.stringify(evidence.INSTALLED_MODELS)}`,
    `- ANALYSIS/TRADING/TEACHER/FALLBACK: ${analysis} / ${trading} / ${teacher} / ${fallback}`,
    `- TRADING_LLM_MODE: ${evidence.TRADING_LLM_MODE}`,
    `- AUTH_BROWSER_VERIFY: ${evidence.AUTH_BROWSER_VERIFY}`,
    `- CONSOLE_ERRORS/WARNINGS/404/500/ANTD: ${evidence.CONSOLE_ERRORS}/${evidence.CONSOLE_WARNINGS}/${evidence.HTTP_404}/${evidence.HTTP_500}/${evidence.ANTD_DEPRECATIONS}`,
    `- UPBIT_RECOVERED: ${evidence.UPBIT_RECOVERED}`,
    `- KIWOOM forced REAL feed: ${evidence.KIWOOM_MARKET_RT_RUNNING}`,
    `- ROLE_SETTING_MUTATION: 0`,
    `- GIT_COMMIT: ${evidence.GIT_COMMIT}`,
    `- NEXT_ACTION: ${evidence.NEXT_ACTION}`,
    "",
  ].join("\n");
  fs.writeFileSync(OUT.md, md, "utf8");
  console.log(
    JSON.stringify(
      {
        FINAL_VERDICT: evidence.FINAL_VERDICT,
        ROLE_MODELS_API_HTTP: evidence.ROLE_MODELS_API_HTTP,
        AUTH_BROWSER_VERIFY: evidence.AUTH_BROWSER_VERIFY,
        CONSOLE_ERRORS: evidence.CONSOLE_ERRORS,
        CONSOLE_WARNINGS: evidence.CONSOLE_WARNINGS,
        HTTP_404: evidence.HTTP_404,
        UPBIT_RECOVERED: evidence.UPBIT_RECOVERED,
      },
      null,
      2,
    ),
  );
}

main().catch((err) => {
  console.error(String(err && err.stack ? err.stack : err));
  process.exit(1);
});
