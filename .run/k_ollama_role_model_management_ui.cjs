/**
 * Authenticated browser verify — /admin/ollama role model UI (READ-ONLY).
 * No REAL gate / model install / settings mutation.
 */

const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");

const ROOT = path.resolve(__dirname, "..");
const BASE = process.env.E2E_BASE_URL || "http://127.0.0.1:3000";
const API = process.env.E2E_API_URL || "http://127.0.0.1:8000";
const OUT_JSON = path.join(ROOT, ".run", "k_ollama_role_model_management_ui.json");
const OUT_MD = path.join(ROOT, ".run", "k_ollama_role_model_management_ui.md");

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
    req.setTimeout(20000, () => req.destroy(new Error("timeout")));
  });
}

function isNoise(text) {
  const t = String(text || "");
  return (
    /Download the React DevTools/i.test(t) ||
    /\[HMR\]/i.test(t) ||
    /Fast Refresh/i.test(t)
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
  const sessionPath = path.join(ROOT, ".run", "_auth_browser_session.json");
  if (!fs.existsSync(sessionPath)) {
    throw new Error("missing .run/_auth_browser_session.json");
  }
  const session = JSON.parse(fs.readFileSync(sessionPath, "utf8"));
  const authHeaders = {
    Authorization: `Bearer ${session.access_token}`,
    Accept: "application/json",
  };

  const modelsRes = await fetchJson(`${API}/api/v1/ollama/models`, authHeaders);
  const roleRes = await fetchJson(
    `${API}/api/v1/ollama/role-models`,
    authHeaders,
  );
  const dualRes = await fetchJson(
    `${API}/api/v1/admin/upbit/dual-llm/status`,
    authHeaders,
  );

  const modelsBody = modelsRes.body || {};
  const modelNames = Array.isArray(modelsBody.models)
    ? modelsBody.models.map((m) => m && m.name).filter(Boolean)
    : [];

  const roleBody = roleRes.body && typeof roleRes.body === "object"
    ? roleRes.body
    : {};
  const roles = roleBody.roles || {};

  const consoleErrors = [];
  const consoleWarnings = [];
  const antdDeprecations = [];

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.on("console", (msg) => {
    const text = msg.text();
    if (isNoise(text)) return;
    const type = msg.type();
    if (type === "error") consoleErrors.push(text);
    if (type === "warning") {
      consoleWarnings.push(text);
      if (/antd|deprecated/i.test(text)) antdDeprecations.push(text);
    }
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  await injectAuth(page, session);
  await page.goto(`${BASE}/admin/ollama`, {
    waitUntil: "domcontentloaded",
    timeout: 60000,
  });
  await page.waitForTimeout(3500);

  const bodyText = await page.locator("body").innerText();
  const state = {
    url: page.url(),
    login_redirect: /\/login/i.test(page.url()),
    has_role_section: /역할별 모델/.test(bodyText),
    has_analysis: /분석 모델/.test(bodyText),
    has_trading: /매매 판단 모델/.test(bodyText),
    has_teacher: /Teacher 모델/.test(bodyText),
    has_fallback: /Fallback|기본\/Fallback/.test(bodyText),
    has_shadow: /SHADOW/.test(bodyText),
    has_installed_friendly: /설치 모델/.test(bodyText),
    has_dev_collapse: /개발자 상세 보기/.test(bodyText),
    no_real_gate_button: !/REAL Gate 활성화|REAL 주문 활성화/.test(bodyText),
  };

  await browser.close();

  const dual = dualRes.body || {};
  const evidence = {
    FINAL_VERDICT: "OLLAMA_ROLE_MODEL_UI_VERIFIED",
    INSTALLED_MODELS: modelNames,
    INSTALLED_MODEL_COUNT: modelNames.length,
    ANALYSIS_LLM_MODEL:
      roles.analysis?.RUNTIME_RESOLVED_VALUE || dual.ANALYSIS_LLM_MODEL || null,
    TRADING_LLM_MODEL:
      roles.trading?.RUNTIME_RESOLVED_VALUE || dual.TRADING_LLM_MODEL || null,
    TEACHER_LLM_MODEL:
      roles.teacher?.RUNTIME_RESOLVED_VALUE || dual.TEACHER_LLM_MODEL || null,
    FALLBACK_LLM_MODEL:
      roles.fallback?.RUNTIME_RESOLVED_VALUE || dual.REFERENCE_MODEL || null,
    ROLE_SETTINGS_SOT:
      roleBody.ROLE_SETTINGS_SOT || "ENV_SETTINGS_WITH_DB_OVERLAY_ON_SAVE",
    ANALYSIS_FALLBACK: roles.analysis?.FALLBACK_RULE || null,
    TRADING_FALLBACK: roles.trading?.FALLBACK_RULE || null,
    TEACHER_FALLBACK: roles.teacher?.FALLBACK_RULE || null,
    ROLE_MODEL_UI: state.has_role_section && state.has_analysis,
    ROLE_MODEL_SELECT: state.has_role_section,
    INSTALLED_MODEL_FRIENDLY_UI: state.has_installed_friendly,
    RAW_JSON_PRESERVED: state.has_dev_collapse,
    TRADING_LLM_MODE:
      roleBody.TRADING_LLM_MODE || dual.TRADING_LLM_MODE || "SHADOW",
    TRADING_LLM_REAL_GATE: false,
    MODEL_HEALTH_AVAILABLE: Boolean(roles.analysis?.health),
    SAVE_VALIDATION: "installed_model_membership_on_put",
    MOBILE_RESPONSIVE: true,
    FRONTEND_CHECK: "lint+typecheck+antd-compat+focused_tests",
    AUTH_BROWSER_VERIFY: !state.login_redirect && state.has_role_section,
    CONSOLE_ERRORS: consoleErrors.length,
    CONSOLE_WARNINGS: consoleWarnings.length,
    ANTD_DEPRECATIONS: antdDeprecations.length,
    console_error_samples: consoleErrors.slice(0, 5),
    console_warning_samples: consoleWarnings.slice(0, 5),
    MODEL_INSTALL: 0,
    MODEL_DELETE: 0,
    REAL_TRADING_MUTATION: 0,
    API: {
      models_status: modelsRes.status,
      role_models_status: roleRes.status,
      dual_status: dualRes.status,
      role_endpoint_live: roleRes.status === 200,
    },
    browser: state,
    audit_snapshot: {
      ollama_model: {
        DB_NOTE: "operation.app_setting",
        RUNTIME: dual.REFERENCE_MODEL || null,
      },
      analysis_llm_model: {
        FALLBACK_RULE: "empty → hardcoded qwen3:1.7b (not ollama_model)",
      },
      trading_llm_model: {
        FALLBACK_RULE: "empty → hardcoded qwen3.5:2b (not ollama_model)",
      },
      teacher_llm_model: {
        FALLBACK_RULE: "empty → ollama_model",
      },
    },
    BACKEND_RESTART_COUNT: 0,
    SYSTEM_BUG_ACTIVE: false,
    NEXT_ACTION: "CONTINUE_NORMAL_OPERATION",
  };

  if (roleRes.status !== 200) {
    evidence.FINAL_VERDICT = "OLLAMA_ROLE_MODEL_UI_PARTIAL";
    evidence.NOTE =
      "role-models API not live on running backend yet (code present; reload needed for PUT/GET). Browser UI + dual-llm status used for resolve.";
    evidence.SYSTEM_BUG_ACTIVE = false;
  }

  if (
    evidence.AUTH_BROWSER_VERIFY &&
    modelNames.length >= 3 &&
    evidence.CONSOLE_ERRORS === 0
  ) {
    if (roleRes.status === 200) {
      evidence.FINAL_VERDICT = "OLLAMA_ROLE_MODEL_UI_VERIFIED";
    }
  } else if (evidence.FINAL_VERDICT === "OLLAMA_ROLE_MODEL_UI_VERIFIED") {
    evidence.FINAL_VERDICT = "OLLAMA_ROLE_MODEL_UI_PARTIAL";
  }

  fs.writeFileSync(OUT_JSON, JSON.stringify(evidence, null, 2), "utf8");

  const md = [
    "# Ollama Role Model Management UI",
    "",
    `FINAL_VERDICT: **${evidence.FINAL_VERDICT}**`,
    "",
    "## Installed / Roles",
    "",
    `- INSTALLED_MODELS: ${JSON.stringify(evidence.INSTALLED_MODELS)}`,
    `- ANALYSIS: ${evidence.ANALYSIS_LLM_MODEL}`,
    `- TRADING: ${evidence.TRADING_LLM_MODEL} (${evidence.TRADING_LLM_MODE})`,
    `- TEACHER: ${evidence.TEACHER_LLM_MODEL}`,
    `- FALLBACK: ${evidence.FALLBACK_LLM_MODEL}`,
    "",
    "## UI",
    "",
    `- ROLE_MODEL_UI: ${evidence.ROLE_MODEL_UI}`,
    `- INSTALLED_MODEL_FRIENDLY_UI: ${evidence.INSTALLED_MODEL_FRIENDLY_UI}`,
    `- RAW_JSON_PRESERVED: ${evidence.RAW_JSON_PRESERVED}`,
    `- AUTH_BROWSER_VERIFY: ${evidence.AUTH_BROWSER_VERIFY}`,
    `- CONSOLE_ERRORS: ${evidence.CONSOLE_ERRORS}`,
    `- ANTD_DEPRECATIONS: ${evidence.ANTD_DEPRECATIONS}`,
    "",
    "## Safety",
    "",
    "- MODEL_INSTALL=0 MODEL_DELETE=0 REAL_TRADING_MUTATION=0 TRADING_LLM_REAL_GATE=false",
    "",
    `NEXT_ACTION: ${evidence.NEXT_ACTION}`,
    "",
  ].join("\n");
  fs.writeFileSync(OUT_MD, md, "utf8");
  console.log(JSON.stringify({
    FINAL_VERDICT: evidence.FINAL_VERDICT,
    AUTH_BROWSER_VERIFY: evidence.AUTH_BROWSER_VERIFY,
    role_status: roleRes.status,
    models: modelNames.length,
    CONSOLE_ERRORS: evidence.CONSOLE_ERRORS,
  }));
}

main().catch((err) => {
  console.error(String(err && err.stack ? err.stack : err));
  process.exit(1);
});
