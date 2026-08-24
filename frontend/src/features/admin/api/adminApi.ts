import type { AxiosRequestConfig } from "axios";

import { apiClient } from "@/lib/api/apiClient";
import { rootClient } from "@/lib/api/rootClient";

export type JsonValue = unknown;

type Params = Record<string, unknown>;

/** Admin Paper 계좌 — 호출부 하드코딩 대신 env 단일 소스. */
export function resolveAdminPaperAccountId(explicit?: number): number {
  if (typeof explicit === "number" && explicit > 0) {
    return explicit;
  }
  const fromEnv = Number(
    process.env.NEXT_PUBLIC_DEFAULT_PAPER_ACCOUNT_ID ?? "1",
  );
  return fromEnv > 0 ? fromEnv : 1;
}


async function getJson(path: string, params?: Params): Promise<JsonValue> {
  const { data } = await apiClient.get(path, { params });
  return data;
}

async function postJson(
  path: string,
  body?: unknown,
  params?: Params,
  config?: AxiosRequestConfig,
): Promise<JsonValue> {
  const { data } = await apiClient.post(path, body ?? {}, {
    params,
    ...config,
  });
  return data;
}

async function putJson(
  path: string,
  body?: unknown,
  params?: Params,
): Promise<JsonValue> {
  const { data } = await apiClient.put(path, body ?? {}, { params });
  return data;
}

async function patchJson(
  path: string,
  body?: unknown,
  params?: Params,
): Promise<JsonValue> {
  const { data } = await apiClient.patch(path, body ?? {}, { params });
  return data;
}

async function deleteJson(
  path: string,
  params?: Params,
): Promise<JsonValue> {
  const { data } = await apiClient.delete(path, { params });
  return data;
}

/** Admin — 실제 FastAPI 엔드포인트만 호출 (추측 금지) */

export async function getHealth(): Promise<JsonValue> {
  const { data } = await rootClient.get("/health");
  return data as JsonValue;
}

export async function getHealthLive(): Promise<JsonValue> {
  const { data } = await rootClient.get("/health/live");
  return data as JsonValue;
}

export async function getHealthReady(): Promise<JsonValue> {
  const { data } = await rootClient.get("/health/ready");
  return data as JsonValue;
}

export async function getVersion(): Promise<JsonValue> {
  const { data } = await rootClient.get("/version");
  return data as JsonValue;
}

export async function getMonitoringOverview(params?: {
  evaluate_alerts?: boolean;
  refresh?: boolean;
}): Promise<JsonValue> {
  return getJson("/monitoring/overview", params);
}

export async function getMonitoringAlerts(params?: {
  limit?: number;
}): Promise<JsonValue> {
  return getJson("/monitoring/alerts", params);
}

export async function getSystemDashboard(params?: {
  account_id?: number;
  exchange_code?: string;
  recent_limit?: number;
}): Promise<JsonValue> {
  return getJson("/system/dashboard", params);
}

export async function getRiskDashboard(params?: {
  user_broker_account_id?: number;
  recent_limit?: number;
}): Promise<JsonValue> {
  return getJson("/dashboard/risk", {
    user_broker_account_id: params?.user_broker_account_id,
    recent_limit: params?.recent_limit,
  });
}

export async function getStrategyOpsDashboard(): Promise<JsonValue> {
  return getJson("/dashboard/strategy-operations");
}

export async function getDashboardSummary(params?: {
  account_id?: number;
  market_code?: string;
  mode_code?: string;
  recent_limit?: number;
}): Promise<JsonValue> {
  return getJson("/dashboard/admin-summary", {
    account_id: resolveAdminPaperAccountId(params?.account_id),
    market_code: params?.market_code ?? "KRX",
    mode_code: params?.mode_code ?? "PAPER",
    recent_limit: params?.recent_limit ?? 10,
  });
}

export async function getBrokerAccount(): Promise<JsonValue> {
  return getJson("/broker/account");
}

export async function getKiwoomConfiguration(): Promise<JsonValue> {
  return getJson("/kiwoom/configuration");
}

export async function testKiwoomToken(): Promise<JsonValue> {
  return postJson("/kiwoom/token/test");
}

export async function syncKiwoomAccount(
  userBrokerAccountId: number,
): Promise<JsonValue> {
  return postJson("/broker/kiwoom/account/sync", {}, {
    user_broker_account_id: userBrokerAccountId,
  });
}

export async function createPaperAccount(body: {
  account_name: string;
  initial_cash: number;
}): Promise<JsonValue> {
  return postJson("/paper-accounts", body);
}

export async function listPaperAccounts(params?: {
  limit?: number;
  offset?: number;
}): Promise<JsonValue> {
  return getJson("/paper-accounts", params);
}

export async function getPaperAccount(accountId: number): Promise<JsonValue> {
  return getJson(`/paper-accounts/${accountId}`);
}

export interface PaperAccountUpdateBody {
  account_name?: string;
  is_active?: boolean;
  is_default?: boolean;
  initial_cash?: number;
}

/** PATCH 부분 수정 — Soft-deleted 제외, 소유권 검증은 Backend */
export async function updatePaperAccount(
  accountId: number,
  body: PaperAccountUpdateBody,
): Promise<JsonValue> {
  const { data } = await apiClient.patch(`/paper-accounts/${accountId}`, body);
  return data as JsonValue;
}

export async function getPaperPositions(accountId: number): Promise<JsonValue> {
  return getJson(`/paper-accounts/${accountId}/positions`);
}

/** Soft Delete — 관리자 전용. Hard Delete 없음. */
export async function deletePaperAccount(accountId: number): Promise<{
  deleted: boolean;
  account_id: number;
  mode: string;
  has_trading_history?: boolean;
  hard_delete_allowed?: boolean;
  deleted_at?: string | null;
}> {
  const { data } = await apiClient.delete(`/paper-accounts/${accountId}`);
  return data as {
    deleted: boolean;
    account_id: number;
    mode: string;
    has_trading_history?: boolean;
    hard_delete_allowed?: boolean;
    deleted_at?: string | null;
  };
}

export async function getRealtimeStrategyStatus(): Promise<JsonValue> {
  return getJson("/realtime-strategy/status");
}

export async function startRealtimeStrategy(): Promise<JsonValue> {
  return postJson("/realtime-strategy/start");
}

export async function stopRealtimeStrategy(): Promise<JsonValue> {
  return postJson("/realtime-strategy/stop");
}

export async function getRealtimeExecutionStatus(): Promise<JsonValue> {
  return getJson("/realtime-execution/status");
}

export async function startRealtimeExecution(): Promise<JsonValue> {
  return postJson("/realtime-execution/start");
}

export async function stopRealtimeExecution(): Promise<JsonValue> {
  return postJson("/realtime-execution/stop");
}

export async function getRealtimeSessionsStatus(): Promise<JsonValue> {
  return getJson("/realtime-sessions/status");
}

/** STEP 8-5-9 — Realtime Hub / Scope */
export async function getRealtimeHubConnections(): Promise<JsonValue> {
  return getJson("/admin/realtime/connections");
}

export async function getRealtimeHubSubscriptions(): Promise<JsonValue> {
  return getJson("/admin/realtime/subscriptions");
}

export async function getRealtimeHubScopes(): Promise<JsonValue> {
  return getJson("/admin/realtime/scopes");
}

export async function getRealtimeHubScope(
  scopeKey: string,
): Promise<JsonValue> {
  return getJson(`/admin/realtime/scopes/${encodeURIComponent(scopeKey)}`);
}

export async function reconnectRealtimeHubScope(
  scopeKey: string,
): Promise<JsonValue> {
  return postJson(
    `/admin/realtime/scopes/${encodeURIComponent(scopeKey)}/reconnect`,
  );
}

export async function rewarmRealtimeHubScope(
  scopeKey: string,
): Promise<JsonValue> {
  return postJson(
    `/admin/realtime/scopes/${encodeURIComponent(scopeKey)}/rewarm`,
  );
}

export async function getKillSwitch(): Promise<JsonValue> {
  return getJson("/risk/kill-switch");
}

export type AdminRiskSettingsPayload = {
  max_order_amount?: number | null;
  daily_max_order_amount?: number | null;
  max_total_investment_amount?: number | null;
  max_position_amount?: number | null;
  max_position_count?: number | null;
  max_position_weight?: number | null;
  allow_duplicate_buy?: boolean | null;
  daily_max_loss_amount?: number | null;
  daily_max_loss_rate?: number | null;
  stop_loss_rate?: number | null;
  take_profit_rate?: number | null;
  trailing_stop_rate?: number | null;
  auto_trading_enabled?: boolean | null;
  buy_enabled?: boolean | null;
  sell_enabled?: boolean | null;
  sell_only?: boolean | null;
  account_paused?: boolean | null;
  max_order_quantity?: number | null;
  daily_order_limit?: number | null;
  daily_submit_limit?: number | null;
  daily_filled_entry_limit?: number | null;
  duplicate_order_window_seconds?: number | null;
};

export async function getSystemRiskSettings(): Promise<JsonValue> {
  return getJson("/admin/risk-settings/system");
}

export async function updateSystemRiskSettings(
  body: AdminRiskSettingsPayload,
): Promise<JsonValue> {
  return putJson("/admin/risk-settings/system", body);
}

export async function getAdminUserRiskSettings(
  userId: number,
): Promise<JsonValue> {
  return getJson(`/admin/risk-settings/users/${userId}`);
}

export async function updateAdminUserRiskSettings(
  userId: number,
  body: AdminRiskSettingsPayload,
): Promise<JsonValue> {
  return putJson(`/admin/risk-settings/users/${userId}`, body);
}

/** STEP 8-7 — LIVE 주문 승인 */
export async function listAdminLiveOrderAccounts(
  userId: number,
): Promise<JsonValue> {
  return getJson(`/admin/live-order/users/${userId}/accounts`);
}

export async function getAdminLiveOrderAccount(
  userBrokerAccountId: number,
): Promise<JsonValue> {
  return getJson(`/admin/live-order/accounts/${userBrokerAccountId}`);
}

export async function setAdminLiveOrderEnabled(
  userBrokerAccountId: number,
  liveOrderEnabled: boolean,
  options?: { reason?: string; correlation_id?: string },
): Promise<JsonValue> {
  return putJson(`/admin/live-order/accounts/${userBrokerAccountId}`, {
    live_order_enabled: liveOrderEnabled,
    reason: options?.reason ?? null,
    correlation_id: options?.correlation_id ?? null,
  });
}

export async function updateAdminLiveRiskLimits(
  userBrokerAccountId: number,
  body: {
    max_order_amount?: number | null;
    max_order_quantity?: number | null;
    daily_order_limit?: number | null;
    daily_submit_limit?: number | null;
    daily_filled_entry_limit?: number | null;
    daily_max_loss_amount?: number | null;
    duplicate_order_window_seconds?: number | null;
    max_open_orders?: number | null;
    max_slippage_rate?: number | null;
    anomaly_orders_per_minute?: number | null;
    arm_ttl_seconds?: number | null;
  },
): Promise<JsonValue> {
  return putJson(
    `/admin/live-order/accounts/${userBrokerAccountId}/risk-limits`,
    body,
  );
}

/** STEP 8-8 — ARM / Dashboard */
export async function armAdminLiveOrder(
  userBrokerAccountId: number,
  options?: {
    ttl_seconds?: number | null;
    reason?: string;
    correlation_id?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/live-order/accounts/${userBrokerAccountId}/arm`, {
    ttl_seconds: options?.ttl_seconds ?? null,
    reason: options?.reason ?? null,
    correlation_id: options?.correlation_id ?? null,
  });
}

export async function disarmAdminLiveOrder(
  userBrokerAccountId: number,
  body?: {
    turn_live_off?: boolean;
    reason?: string;
    correlation_id?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/live-order/accounts/${userBrokerAccountId}/disarm`, {
    turn_live_off: body?.turn_live_off ?? false,
    reason: body?.reason ?? "MANUAL",
    correlation_id: body?.correlation_id ?? null,
  });
}

export async function getAdminLiveArmStatus(
  userBrokerAccountId: number,
): Promise<JsonValue> {
  return getJson(`/admin/live-order/accounts/${userBrokerAccountId}/arm`);
}

export async function getAdminLiveOpsDashboard(): Promise<JsonValue> {
  return getJson("/admin/live-order/dashboard");
}

/** STEP 8-9 — Upbit 소액 LIVE 검증 */
export async function getUpbitLiveValidationMeta(): Promise<JsonValue> {
  return getJson("/admin/live-validation/upbit/meta");
}

export async function preflightUpbitLiveValidation(body: {
  user_broker_account_id: number;
  market: string;
  side: string;
  amount: number;
  limit_price: number;
  arm_token?: string | null;
}): Promise<JsonValue> {
  return postJson("/admin/live-validation/upbit/preflight", body);
}

export async function executeUpbitLiveValidation(body: {
  user_broker_account_id: number;
  market: string;
  side: string;
  amount: number;
  limit_price: number;
  /** challenge용 선택 토큰 — 없으면 서버가 UBA ARM 상태 검증 */
  arm_token?: string | null;
  execute_live: boolean;
  confirmation_text: string;
  preflight_id: string;
}): Promise<JsonValue> {
  return postJson("/admin/live-validation/upbit/execute", body);
}

export async function listUpbitLiveValidationRuns(
  limit = 50,
): Promise<JsonValue> {
  return getJson(`/admin/live-validation/upbit/runs?limit=${limit}`);
}

export async function cancelUpbitLiveValidationRun(
  runId: string,
): Promise<JsonValue> {
  return postJson(`/admin/live-validation/upbit/runs/${runId}/cancel`, {});
}

export async function refreshUpbitLiveValidationRun(
  runId: string,
): Promise<JsonValue> {
  return postJson(`/admin/live-validation/upbit/runs/${runId}/refresh`, {});
}

export async function manualReviewUpbitLiveValidationRun(
  runId: string,
  body: { evidence: string; broker_status?: string | null },
): Promise<JsonValue> {
  return postJson(
    `/admin/live-validation/upbit/runs/${runId}/manual-review`,
    body,
  );
}

export async function getUpbitLiveValidationDashboard(): Promise<JsonValue> {
  return getJson("/admin/live-validation/upbit/dashboard");
}

/** STEP 8-3 — ADMIN 전략 소유권 */
export async function listAdminStrategies(params?: {
  owner_type?: string;
  user_id?: number;
  visibility?: string;
  limit?: number;
  offset?: number;
}): Promise<JsonValue> {
  return getJson("/admin/strategies", params);
}

export async function createAdminStrategy(body: {
  strategy_code: string;
  name: string;
  description?: string | null;
  market_type?: string;
  visibility?: string;
  parameter_payload?: Record<string, unknown>;
  is_active?: boolean;
}): Promise<JsonValue> {
  return postJson("/admin/strategies", body);
}

export async function updateAdminStrategy(
  strategyId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return putJson(`/admin/strategies/${strategyId}`, body);
}

export async function approveAdminStrategy(
  strategyId: number,
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyId}/approve`, {});
}

export async function rejectAdminStrategy(
  strategyId: number,
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyId}/reject`, {});
}

export async function publishAdminStrategy(
  strategyId: number,
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyId}/publish`, {});
}

export async function unpublishAdminStrategy(
  strategyId: number,
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyId}/unpublish`, {});
}

export async function activateAdminStrategy(
  strategyId: number,
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyId}/activate`, {});
}

export async function deactivateAdminStrategy(
  strategyId: number,
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyId}/deactivate`, {});
}

export async function setAdminUserTradingFlags(
  userId: number,
  body: {
    buy_enabled?: boolean;
    sell_only?: boolean;
    auto_trading_enabled?: boolean;
    account_paused?: boolean;
  },
): Promise<JsonValue> {
  return postJson(
    `/admin/risk-settings/users/${userId}/trading-flags`,
    body,
  );
}

/** STEP 8-5-2 — ADMIN Credential 상태 (원문 조회 API 없음) */
export interface AdminBrokerCredentialStatus {
  user_broker_account_id: number;
  broker_code: string;
  connected: boolean;
  is_active: boolean;
  verification_status: string | null;
  masked_identifier: string | null;
  key_version: number | null;
  last_verified_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  vault_available: boolean;
  owner_user_id?: number;
  uba_connection_status?: string;
  uba_is_active?: boolean;
  account_paused?: boolean;
  verification_message?: string | null;
}

export async function getAdminBrokerCredentialStatus(
  ubaId: number,
): Promise<AdminBrokerCredentialStatus> {
  const { data } = await apiClient.get(
    `/admin/accounts/${ubaId}/credentials/status`,
  );
  return data as AdminBrokerCredentialStatus;
}

export async function verifyAdminBrokerCredential(
  ubaId: number,
): Promise<AdminBrokerCredentialStatus> {
  const { data } = await apiClient.post(
    `/admin/accounts/${ubaId}/credentials/verify`,
    {},
  );
  return data as AdminBrokerCredentialStatus;
}

export async function revokeAdminBrokerCredential(
  ubaId: number,
): Promise<AdminBrokerCredentialStatus> {
  const { data } = await apiClient.post(
    `/admin/accounts/${ubaId}/credentials/revoke`,
    {},
  );
  return data as AdminBrokerCredentialStatus;
}

export async function registerAdminBrokerCredential(
  ubaId: number,
  body: {
    access_key?: string;
    secret_key?: string;
    app_key?: string;
    account_number?: string;
    account_product_code?: string;
    is_mock?: boolean;
  },
): Promise<AdminBrokerCredentialStatus> {
  const { data } = await apiClient.post(
    `/admin/accounts/${ubaId}/credentials`,
    body,
  );
  return data as AdminBrokerCredentialStatus;
}

export async function replaceAdminBrokerCredential(
  ubaId: number,
  body: {
    access_key?: string;
    secret_key?: string;
    app_key?: string;
    account_number?: string;
    account_product_code?: string;
    is_mock?: boolean;
  },
): Promise<AdminBrokerCredentialStatus> {
  const { data } = await apiClient.put(
    `/admin/accounts/${ubaId}/credentials`,
    body,
  );
  return data as AdminBrokerCredentialStatus;
}

/** STEP 8-9C — Admin UBA CRUD */
export async function listAdminBrokerAccounts(params?: {
  broker_code?: string;
  owner_user_id?: number;
  include_inactive?: boolean;
  include_deleted?: boolean;
  /** 기본 false — REAL_OPERATION만 */
  include_test_accounts?: boolean;
  /** false면 risk/vault/recovery N+1 생략 */
  enrich?: boolean;
  limit?: number;
  offset?: number;
}): Promise<JsonValue> {
  return getJson("/admin/broker-accounts", params);
}

export async function createAdminBrokerAccount(body: {
  owner_user_id: number;
  broker_code?: string;
  account_alias?: string | null;
  account_number: string;
  currency_code?: string;
  is_default?: boolean;
  apply_recommended_risk?: boolean;
}): Promise<JsonValue> {
  return postJson("/admin/broker-accounts", body);
}

export async function getAdminBrokerAccount(
  ubaId: number,
): Promise<JsonValue> {
  return getJson(`/admin/broker-accounts/${ubaId}`);
}

export async function updateAdminBrokerAccount(
  ubaId: number,
  body: { account_alias?: string; is_active?: boolean },
): Promise<JsonValue> {
  return patchJson(`/admin/broker-accounts/${ubaId}`, body);
}

export async function deleteAdminBrokerAccount(
  ubaId: number,
): Promise<JsonValue> {
  return deleteJson(`/admin/broker-accounts/${ubaId}`);
}

export async function applyAdminBrokerRecommendedRisk(
  ubaId: number,
): Promise<JsonValue> {
  return postJson(`/admin/broker-accounts/${ubaId}/apply-recommended-risk`, {});
}

export async function getAdminLiveOpsReadiness(): Promise<JsonValue> {
  return getJson("/admin/live-ops/readiness");
}

export async function getAdminUbaAutotradingReadiness(
  ubaId: number,
): Promise<JsonValue> {
  return getJson(`/admin/autotrading/uba/${ubaId}/readiness`);
}

/** 연구 데이터 수집 현황 — READ ONLY (REAL/LIVE/주문 무관) */
export async function getAdminUbaResearchCollectionStatus(
  ubaId: number,
): Promise<JsonValue> {
  return getJson(
    `/admin/autotrading/uba/${ubaId}/research/collection-status`,
  );
}

export async function getAdminUpbitResearchCleanForward(
  params?: Params,
): Promise<JsonValue> {
  return getJson("/admin/upbit/research/clean-forward", params);
}

export async function getAdminUpbitResearchCleanForwardDetail(
  shadowId: number,
): Promise<JsonValue> {
  return getJson(`/admin/upbit/research/clean-forward/${shadowId}`);
}

export async function getAdminUpbitResearchMarketContext(
  params?: Params,
): Promise<JsonValue> {
  return getJson("/admin/upbit/research/market-context", params);
}

export async function getAdminUpbitResearchAssetContext(
  params?: Params,
): Promise<JsonValue> {
  return getJson("/admin/upbit/research/asset-context", params);
}

export async function getAdminUpbitResearchNews(
  params?: Params,
): Promise<JsonValue> {
  return getJson("/admin/upbit/research/news", params);
}

export async function getAdminUpbitResearchLlmAnalysis(
  params?: Params,
): Promise<JsonValue> {
  return getJson("/admin/upbit/research/llm-analysis", params);
}

export async function getAdminUpbitResearchLlmAnalysisDetail(
  analysisId: number,
): Promise<JsonValue> {
  return getJson(`/admin/upbit/research/llm-analysis/${analysisId}`);
}

export async function getAdminUpbitResearchExperiments(): Promise<JsonValue> {
  return getJson("/admin/upbit/research/experiments");
}

/** Dual LLM role status — READ ONLY (ANALYSIS + TRADING SHADOW) */
export async function getAdminUpbitDualLlmStatus(): Promise<JsonValue> {
  return getJson("/admin/upbit/dual-llm/status");
}

export async function getAdminUpbitDualLlmRecent(
  params?: Params,
): Promise<JsonValue> {
  return getJson("/admin/upbit/dual-llm/recent", params);
}

export async function getAdminUpbitDualLlmComparison(): Promise<JsonValue> {
  return getJson("/admin/upbit/dual-llm/comparison");
}

export async function getAdminUpbitDualLlmRagFeedback(
  params?: Params,
): Promise<JsonValue> {
  return getJson("/admin/upbit/dual-llm/rag-feedback", params);
}

export async function getAdminUpbitDualLlmRagFeedbackDetail(
  analysisId: number,
): Promise<JsonValue> {
  return getJson(`/admin/upbit/dual-llm/rag-feedback/${analysisId}`);
}

/** Kiwoom Dual LLM — READ ONLY SHADOW research */
export async function getAdminKiwoomDualLlmStatus(): Promise<JsonValue> {
  return getJson("/admin/kiwoom/dual-llm/status");
}

export async function getAdminKiwoomDualLlmRecent(
  params?: Params,
): Promise<JsonValue> {
  return getJson("/admin/kiwoom/dual-llm/recent", params);
}

export async function getAdminKiwoomDualLlmRagFeedback(
  params?: Params,
): Promise<JsonValue> {
  return getJson("/admin/kiwoom/dual-llm/rag-feedback", params);
}

export async function getAdminKiwoomDualLlmRagFeedbackDetail(
  analysisId: number,
): Promise<JsonValue> {
  return getJson(`/admin/kiwoom/dual-llm/rag-feedback/${analysisId}`);
}

/** Canonical orchestrator status / start / stop */
export async function getAdminUbaOrchestratorStatus(
  ubaId: number,
): Promise<JsonValue> {
  return getJson(`/admin/autotrading/uba/${ubaId}/status`);
}

export async function startAdminUbaAutotrading(
  ubaId: number,
  body: {
    reauthorize_unattended?: boolean;
    strategy_id?: number;
    correlation_id?: string;
  } = {},
): Promise<JsonValue> {
  return postJson(`/admin/autotrading/uba/${ubaId}/start`, body);
}

export async function stopAdminUbaAutotrading(
  ubaId: number,
  body: {
    mode?: "ENTRY_ONLY" | "FULL";
    strategy_id?: number;
  } = {},
): Promise<JsonValue> {
  return postJson(`/admin/autotrading/uba/${ubaId}/stop`, {
    mode: body.mode ?? "ENTRY_ONLY",
    strategy_id: body.strategy_id,
  });
}

/** Symbol ownership list — READ only (주문·Risk mutate 없음) */
export async function listAdminSymbolOwnership(
  ubaId: number,
  brokerCode = "UPBIT",
): Promise<JsonValue> {
  return getJson(`/admin/symbol-ownership/${ubaId}`, {
    broker_code: brokerCode,
  });
}

export async function getAdminSymbolOwnership(
  ubaId: number,
  symbol: string,
  brokerCode = "UPBIT",
): Promise<JsonValue> {
  return getJson(
    `/admin/symbol-ownership/${ubaId}/${encodeURIComponent(symbol)}`,
    { broker_code: brokerCode },
  );
}

export async function getAdminUbaOpsStatus(
  ubaId: number,
  strategyId?: number,
): Promise<JsonValue> {
  const qs =
    strategyId != null ? `?strategy_id=${encodeURIComponent(strategyId)}` : "";
  return getJson(`/admin/autotrading/uba/${ubaId}/ops-status${qs}`);
}

export async function getAdminUbaFullMarketStatus(
  ubaId: number,
): Promise<JsonValue> {
  return getJson(`/admin/autotrading/uba/${ubaId}/full-market`);
}

export async function enableAdminUbaFullMarket(
  ubaId: number,
  body: {
    confirmation_text: string;
    strategy_id?: number;
    deployment_id?: number;
    template_symbol?: string;
    ai_live_gate_mode?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/autotrading/uba/${ubaId}/full-market/enable`, body);
}

export async function disableAdminUbaFullMarket(
  ubaId: number,
  body: { confirmation_text: string },
): Promise<JsonValue> {
  return postJson(`/admin/autotrading/uba/${ubaId}/full-market/disable`, body);
}

export async function drySelectAdminUbaFullMarket(
  ubaId: number,
  body?: { candidates?: Record<string, unknown>[]; scanner_run_id?: string },
): Promise<JsonValue> {
  return postJson(
    `/admin/autotrading/uba/${ubaId}/full-market/dry-select`,
    body ?? {},
  );
}

export async function getAdminUbaPortfolioStatus(
  ubaId: number,
): Promise<JsonValue> {
  return getJson(`/admin/autotrading/uba/${ubaId}/portfolio`);
}

export async function enableAdminUbaPortfolio(
  ubaId: number,
  body: {
    confirmation_text: string;
    strategy_id?: number;
    deployment_id?: number;
    template_symbol?: string;
    portfolio_capital_limit_krw?: number;
    max_positions?: number;
  },
): Promise<JsonValue> {
  return postJson(`/admin/autotrading/uba/${ubaId}/portfolio/enable`, body);
}

export async function disableAdminUbaPortfolio(
  ubaId: number,
  body: { confirmation_text: string; fallback_mode?: string },
): Promise<JsonValue> {
  return postJson(`/admin/autotrading/uba/${ubaId}/portfolio/disable`, body);
}

export async function getAdminUbaPortfolioPolicy(
  ubaId: number,
): Promise<JsonValue> {
  return getJson(`/admin/autotrading/uba/${ubaId}/portfolio/policy`);
}

export async function patchAdminUbaPortfolioPolicy(
  ubaId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return patchJson(`/admin/autotrading/uba/${ubaId}/portfolio/policy`, body);
}

export async function previewAdminUbaPortfolioSizing(
  ubaId: number,
  body?: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/autotrading/uba/${ubaId}/portfolio/preview-sizing`,
    body ?? {},
  );
}

export async function dryTopKAdminUbaPortfolio(
  ubaId: number,
  body?: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/autotrading/uba/${ubaId}/portfolio/dry-topk`,
    body ?? {},
  );
}

export async function getAdminUbaUnattendedStatus(
  ubaId: number,
): Promise<JsonValue> {
  return getJson(`/admin/autotrading/uba/${ubaId}/unattended`);
}

/** alias — Kiwoom panel 등에서 짧은 이름 사용 */
export const getAdminUbaUnattended = getAdminUbaUnattendedStatus;

export async function enableAdminUbaUnattended(
  ubaId: number,
  body: {
    confirmation_text: string;
    reason: string;
    horizon_hours?: number;
    correlation_id?: string;
    source?: "ADMIN_UI" | "ADMIN_API";
    authorization_mode?: string | null;
    next_trading_day_auto_start?: boolean;
  },
): Promise<JsonValue> {
  return postJson(`/admin/autotrading/uba/${ubaId}/unattended/enable`, body);
}

export async function reauthorizeAdminUbaUnattended(
  ubaId: number,
  body: {
    confirmation_text: string;
    reason: string;
    horizon_hours?: number;
    correlation_id?: string;
    source?: "ADMIN_UI" | "ADMIN_API";
  },
): Promise<JsonValue> {
  return postJson(
    `/admin/autotrading/uba/${ubaId}/unattended/reauthorize`,
    body,
  );
}

export async function disableAdminUbaUnattended(
  ubaId: number,
  body: { confirmation_text: string; reason: string },
): Promise<JsonValue> {
  return postJson(`/admin/autotrading/uba/${ubaId}/unattended/disable`, body);
}

/** 24H lease 자동 갱신 opt-in/out — ACTIVE lease 필수 */
export async function setAdminUbaUnattendedAutoRenew(
  ubaId: number,
  body: { enabled: boolean },
): Promise<JsonValue> {
  return postJson(
    `/admin/autotrading/uba/${ubaId}/unattended/auto-renew`,
    body,
  );
}

/** READ-ONLY — would_renew / projected expiry (시간 조작 없음) */
export async function getAdminUbaHorizonAutoRenewPreview(
  ubaId: number,
): Promise<JsonValue> {
  return getJson(
    `/admin/autotrading/uba/${ubaId}/unattended/horizon-auto-renew/preview`,
  );
}

export async function getAdminUbaKiwoomLifecycle(
  ubaId: number,
): Promise<JsonValue> {
  return getJson(`/admin/autotrading/uba/${ubaId}/kiwoom-lifecycle`);
}

export async function getAdminUbaKiwoomLifecyclePrecheck(
  ubaId: number,
): Promise<JsonValue> {
  return getJson(`/admin/autotrading/uba/${ubaId}/kiwoom-lifecycle/precheck`);
}

export async function getAdminUbaKiwoomLifecyclePreview(
  ubaId: number,
): Promise<JsonValue> {
  return getJson(`/admin/autotrading/uba/${ubaId}/kiwoom-lifecycle/preview`);
}

export async function setAdminUbaKiwoomNextDayAutoStart(
  ubaId: number,
  body: {
    enabled: boolean;
    confirmation_text: string;
    reason?: string;
  },
): Promise<JsonValue> {
  return postJson(
    `/admin/autotrading/uba/${ubaId}/kiwoom-lifecycle/next-day-auto-start`,
    body,
  );
}

export async function getAdminLiveOutboxWorkerStatus(): Promise<JsonValue> {
  return getJson("/admin/autotrading/live-outbox-worker/status");
}

export async function startAdminLiveOutboxWorker(
  confirmationText: string,
): Promise<JsonValue> {
  return postJson("/admin/autotrading/live-outbox-worker/start", {
    confirmation_text: confirmationText,
  });
}

export async function stopAdminLiveOutboxWorker(
  confirmationText: string,
): Promise<JsonValue> {
  return postJson("/admin/autotrading/live-outbox-worker/stop", {
    confirmation_text: confirmationText,
  });
}

export async function startAdminUbaStrategyRuntime(
  ubaId: number,
  strategyId: number,
  confirmationText: string,
): Promise<JsonValue> {
  return postJson(
    `/admin/autotrading/uba/${ubaId}/strategy-runtime/start`,
    {
      strategy_id: strategyId,
      confirmation_text: confirmationText,
    },
  );
}

export async function stopAdminUbaStrategyRuntime(
  ubaId: number,
  strategyId: number,
  confirmationText: string,
): Promise<JsonValue> {
  return postJson(
    `/admin/autotrading/uba/${ubaId}/strategy-runtime/stop`,
    {
      strategy_id: strategyId,
      confirmation_text: confirmationText,
    },
  );
}

export async function getAdminExitMonitorStatus(): Promise<JsonValue> {
  return getJson("/admin/autotrading/exit-monitor/status");
}

export async function startAdminExitMonitor(
  confirmationText: string,
): Promise<JsonValue> {
  return postJson("/admin/autotrading/exit-monitor/start", {
    confirmation_text: confirmationText,
  });
}

export async function stopAdminExitMonitor(
  confirmationText: string,
): Promise<JsonValue> {
  return postJson("/admin/autotrading/exit-monitor/stop", {
    confirmation_text: confirmationText,
  });
}

/** STEP 9-7 — LIVE ON 전 Runtime Pre-flight */
export const PREFLIGHT_TTL_SECONDS = 60;

export interface RuntimePreflightCheck {
  code: string;
  name: string;
  status: "PASS" | "WARN" | "FAIL" | "NOT_APPLICABLE" | string;
  blocking?: boolean;
  message: string;
  detail?: Record<string, unknown>;
  checked_at?: string;
  remediation?: string | null;
}

export interface RuntimePreflightResponse {
  mode?: "LIVE_ON" | "SCHEDULER_RUN" | string;
  overall?: string;
  overall_status: "READY_FOR_LIVE" | "BLOCKED" | string;
  /** "NOW" | null — 근거 없는 시각 추측 금지 */
  estimated_ready: "NOW" | null | string;
  live_on_allowed?: boolean;
  checked_at?: string;
  expires_at?: string;
  freshness?: {
    ttl_seconds?: number;
    checked_at?: string;
    expires_at?: string;
    status?: "FRESH" | "STALE" | string;
  };
  checks: RuntimePreflightCheck[];
  warnings: Array<{
    code?: string;
    message?: string;
    status?: string;
    remediation?: string | null;
  }>;
  blockers: Array<{
    code?: string;
    message?: string;
    status?: string;
    remediation?: string | null;
  }>;
  summary?: {
    pass?: number;
    warn?: number;
    fail?: number;
    not_applicable?: number;
    total?: number;
  };
}

const PREFLIGHT_SENSITIVE_KEY_RE =
  /^(access_key|secret_key|api_key|api_secret|arm_token|access_token|refresh_token|authorization|ciphertext|encrypted|private_key|password|secret|token|traceback|stack|exc_info)$|_secret$|_token$|_password$|_ciphertext$|_key$|traceback|stack_trace/i;

/** JSON/PDF 내보내기용 클라이언트 살균 (서버 살균 이중 안전) */
export function sanitizePreflightExport(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => sanitizePreflightExport(item));
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
      if (PREFLIGHT_SENSITIVE_KEY_RE.test(key)) continue;
      out[key] = sanitizePreflightExport(raw);
    }
    return out;
  }
  return value;
}

/** 검사 결과 최신성 (기본 TTL 60초) */
export function evaluatePreflightFreshness(
  checkedAtIso: string | null | undefined,
  ttlSeconds: number = PREFLIGHT_TTL_SECONDS,
  nowMs: number = Date.now(),
): { status: "FRESH" | "STALE"; fresh: boolean; ageSeconds: number | null } {
  if (!checkedAtIso) {
    return { status: "STALE", fresh: false, ageSeconds: null };
  }
  const checkedMs = Date.parse(checkedAtIso);
  if (Number.isNaN(checkedMs)) {
    return { status: "STALE", fresh: false, ageSeconds: null };
  }
  const ageSeconds = (nowMs - checkedMs) / 1000;
  const fresh = ageSeconds <= ttlSeconds;
  return {
    status: fresh ? "FRESH" : "STALE",
    fresh,
    ageSeconds: Math.round(ageSeconds * 1000) / 1000,
  };
}

export function isPreflightLiveOnAllowed(
  report: RuntimePreflightResponse | null | undefined,
  nowMs: number = Date.now(),
): boolean {
  if (!report) return false;
  if (String(report.overall_status).toUpperCase() !== "READY_FOR_LIVE") {
    return false;
  }
  const ttl =
    Number(report.freshness?.ttl_seconds) || PREFLIGHT_TTL_SECONDS;
  const freshness = evaluatePreflightFreshness(
    report.checked_at ?? report.freshness?.checked_at,
    ttl,
    nowMs,
  );
  return freshness.fresh;
}

export async function getRuntimePreflight(params?: {
  mode?: "LIVE_ON" | "SCHEDULER_RUN" | "ARM_ON" | "ORDER";
  user_broker_account_id?: number;
}): Promise<RuntimePreflightResponse> {
  const data = await getJson("/admin/runtime/preflight", params);
  return data as RuntimePreflightResponse;
}

/** STEP 10-3 — Operations Center 통합 Summary (Read-only) */
export async function getOperationsCenterSummary(params?: {
  cache_ttl_sec?: number;
}): Promise<JsonValue> {
  return getJson("/admin/dashboard/summary", params);
}

/** AUTO trading performance aggregate (strategy-owned only) */
export async function getAdminAutotradingPerformance(params?: {
  broker?: "ALL" | "UPBIT" | "KIWOOM";
  period?: "TODAY" | "7D" | "30D" | "90D" | "ALL";
  include_ops?: boolean;
}): Promise<JsonValue> {
  return getJson("/admin/dashboard/autotrading-performance", params);
}

/** STEP 11-3 — AI Provider Configuration / Vault */
export async function listAiProviderConfigurations(): Promise<JsonValue> {
  return getJson("/admin/ai/provider-configurations");
}

export async function getAiProviderConfiguration(
  configId: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/provider-configurations/${configId}`);
}

export async function upsertAiProviderConfiguration(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/provider-configurations", body);
}

export async function storeAiProviderCredential(
  configId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/provider-configurations/${configId}/credentials`,
    body,
  );
}

export async function verifyAiProviderCredential(
  configId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/provider-configurations/${configId}/credentials/verify`,
    body,
  );
}

export async function rotateAiProviderCredential(
  configId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/provider-configurations/${configId}/credentials/rotate`,
    body,
  );
}

export async function revokeAiProviderCredential(
  configId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/provider-configurations/${configId}/credentials/revoke`,
    body,
  );
}

export async function enableAiProvider(
  configId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/provider-configurations/${configId}/enable`,
    body,
  );
}

export async function disableAiProvider(
  configId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/provider-configurations/${configId}/disable`,
    body,
  );
}

export async function setDefaultAiProvider(
  configId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/provider-configurations/${configId}/set-default`,
    body,
  );
}

export async function reloadAiProviderRegistry(
  configId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/provider-configurations/${configId}/reload`,
    body,
  );
}

export async function testAiProvider(
  providerId: string,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/providers/${providerId}/test`, body);
}

/** STEP 11-4 — Prompt / Schema / Policy (외부 AI 호출 없음) */
export async function listAiPromptTemplates(): Promise<JsonValue> {
  return getJson("/admin/ai/prompt-templates");
}

export async function getAiPromptTemplate(id: number): Promise<JsonValue> {
  return getJson(`/admin/ai/prompt-templates/${id}`);
}

export async function createAiPromptTemplate(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/prompt-templates", body);
}

export async function createAiPromptVersion(
  templateId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/prompt-templates/${templateId}/versions`, body);
}

export async function activateAiPromptVersion(
  versionId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/prompt-versions/${versionId}/activate`, body);
}

export async function previewAiPromptRender(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/prompt-preview/render", body);
}

export async function previewAiValidateResponse(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/prompt-preview/validate-response", body);
}

export async function listAiOutputSchemas(): Promise<JsonValue> {
  return getJson("/admin/ai/output-schemas");
}

export async function getAiOutputSchema(id: number): Promise<JsonValue> {
  return getJson(`/admin/ai/output-schemas/${id}`);
}

export async function createAiOutputSchema(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/output-schemas", body);
}

export async function listAiPolicies(): Promise<JsonValue> {
  return getJson("/admin/ai/policies");
}

export async function getAiPolicy(id: number): Promise<JsonValue> {
  return getJson(`/admin/ai/policies/${id}`);
}

export async function createAiPolicy(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/policies", body);
}

export async function activateAiPolicy(
  policyId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/policies/${policyId}/activate`, body);
}

/** STEP 11-5 — AI Execution */
export async function listAiExecutions(): Promise<JsonValue> {
  return getJson("/admin/ai/executions");
}

export async function getAiExecution(id: number): Promise<JsonValue> {
  return getJson(`/admin/ai/executions/${id}`);
}

export async function createAiExecution(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/executions", body);
}

export async function dryRunAiExecution(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/executions/${id}/dry-run`, body);
}

export async function executeAiExecution(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/executions/${id}/execute`, body);
}

export async function cancelAiExecution(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/executions/${id}/cancel`, body);
}

/** STEP 11-6 — 문서 분석 (참고용, 매매 신호 아님) */
export async function listAiDocumentAnalyses(params?: {
  document_type?: string;
}): Promise<JsonValue> {
  return getJson("/admin/ai/document-analyses", params);
}

export async function getAiDocumentAnalysis(id: number): Promise<JsonValue> {
  return getJson(`/admin/ai/document-analyses/${id}`);
}

export async function createAiDocumentAnalysis(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/document-analyses", body);
}

export async function dryRunAiDocumentAnalysis(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/document-analyses/${id}/dry-run`, body);
}

export async function executeAiDocumentAnalysis(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/document-analyses/${id}/execute`, body);
}

export async function reanalyzeAiDocumentAnalysis(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/document-analyses/${id}/reanalyze`, body);
}

export async function compareAiDocumentAnalyses(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/document-analyses/compare", body);
}

export async function getAiDocumentAnalysisDashboard(): Promise<JsonValue> {
  return getJson("/admin/ai/document-analyses/dashboard");
}

/** STEP 11-7 — 시장·차트 분석 (참고용, 매매 신호 아님) */
export async function listAiMarketAnalyses(params?: {
  analysis_type?: string;
}): Promise<JsonValue> {
  return getJson("/admin/ai/market-analyses", params);
}

export async function getAiMarketAnalysis(id: number): Promise<JsonValue> {
  return getJson(`/admin/ai/market-analyses/${id}`);
}

export async function createAiMarketAnalysis(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/market-analyses", body);
}

export async function dryRunAiMarketAnalysis(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/market-analyses/${id}/dry-run`, body);
}

export async function executeAiMarketAnalysis(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/market-analyses/${id}/execute`, body);
}

export async function reanalyzeAiMarketAnalysis(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/market-analyses/${id}/reanalyze`, body);
}

export async function compareAiMarketAnalyses(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/market-analyses/compare", body);
}

export async function getAiMarketAnalysisDashboard(): Promise<JsonValue> {
  return getJson("/admin/ai/market-analyses/dashboard");
}

/** STEP 11-9 — AI 후보 평가 초안 (참고용, 매매 후보·주문 아님) */
export async function listAiCandidateAssessments(params?: {
  market_type?: string;
  assessment_type?: string;
}): Promise<JsonValue> {
  return getJson("/admin/ai/candidate-assessments", params);
}

export async function getAiCandidateAssessment(id: number): Promise<JsonValue> {
  return getJson(`/admin/ai/candidate-assessments/${id}`);
}

export async function getAiCandidateAssessmentDashboard(): Promise<JsonValue> {
  return getJson("/admin/ai/candidate-assessments/dashboard");
}

export async function getAiCandidateAssessmentHistory(
  id: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidate-assessments/${id}/history`);
}

export async function getAiCandidateAssessmentEvidence(
  id: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidate-assessments/${id}/evidence`);
}

export async function createAiCandidateAssessment(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/candidate-assessments", body);
}

export async function createAiCandidateAssessmentBatch(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/candidate-assessments/batches", body);
}

export async function dryRunAiCandidateAssessment(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-assessments/${id}/dry-run`, body);
}

export async function executeAiCandidateAssessment(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-assessments/${id}/execute`, body);
}

export async function cancelAiCandidateAssessment(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-assessments/${id}/cancel`, body);
}

export async function reassessAiCandidateAssessment(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-assessments/${id}/reassess`, body);
}

export async function requestReviewAiCandidateAssessment(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-assessments/${id}/request-review`, body);
}

export async function compareAiCandidateAssessments(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/candidate-assessments/compare", body);
}

/** STEP 11-10 — Multi-AI Candidate Consensus (참고용, 매매·후보등록 아님) */
export async function listAiCandidateConsensuses(params?: {
  market_type?: string;
  consensus_type?: string;
  limit?: number;
}): Promise<JsonValue> {
  return getJson("/admin/ai/candidate-consensuses", params);
}

export async function getAiCandidateConsensus(id: number): Promise<JsonValue> {
  return getJson(`/admin/ai/candidate-consensuses/${id}`);
}

export async function getAiCandidateConsensusDashboard(): Promise<JsonValue> {
  return getJson("/admin/ai/candidate-consensuses/dashboard");
}

export async function getAiCandidateConsensusMembers(
  id: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidate-consensuses/${id}/members`);
}

export async function getAiCandidateConsensusWeights(
  id: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidate-consensuses/${id}/weights`);
}

export async function getAiCandidateConsensusConflicts(
  id: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidate-consensuses/${id}/conflicts`);
}

export async function getAiCandidateConsensusHistory(
  id: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidate-consensuses/${id}/history`);
}

export async function createAiCandidateConsensus(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/candidate-consensuses", body);
}

export async function createAiCandidateConsensusBatch(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/candidate-consensuses/batches", body);
}

export async function dryRunAiCandidateConsensus(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-consensuses/${id}/dry-run`, body);
}

export async function calculateAiCandidateConsensus(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-consensuses/${id}/calculate`, body);
}

export async function synthesizeAiCandidateConsensus(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-consensuses/${id}/synthesize`, body);
}

export async function cancelAiCandidateConsensus(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-consensuses/${id}/cancel`, body);
}

export async function recalculateAiCandidateConsensus(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-consensuses/${id}/recalculate`, body);
}

export async function resynthesizeAiCandidateConsensus(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-consensuses/${id}/resynthesize`, body);
}

export async function requestReviewAiCandidateConsensus(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-consensuses/${id}/request-review`, body);
}

export async function compareAiCandidateConsensuses(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/candidate-consensuses/compare", body);
}

/** STEP 11-11 — 후보 추천 검토 큐 (기존 후보 등록 검토 가능, 매매·주문 아님) */
export async function listAiCandidateRecommendationQueues(params?: {
  queue_status?: string;
  market_type?: string;
  symbol?: string;
  assigned_to?: string;
  limit?: number;
  offset?: number;
}): Promise<JsonValue> {
  return getJson("/admin/ai/candidate-recommendation-queues", params);
}

export async function getAiCandidateRecommendationQueue(
  id: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidate-recommendation-queues/${id}`);
}

export async function getAiCandidateRecommendationQueueDashboard(): Promise<JsonValue> {
  return getJson("/admin/ai/candidate-recommendation-queues/dashboard");
}

export async function validateAiCandidateRecommendationQueue(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/candidate-recommendation-queues/validate", body);
}

export async function createAiCandidateRecommendationQueue(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/candidate-recommendation-queues", body);
}

export async function createAiCandidateRecommendationQueueBatch(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/candidate-recommendation-queues/batches", body);
}

export async function compareAiCandidateRecommendationQueues(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/candidate-recommendation-queues/compare", body);
}

export async function getAiCandidateRecommendationQueueReviews(
  id: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidate-recommendation-queues/${id}/reviews`);
}

export async function getAiCandidateRecommendationQueueFindings(
  id: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidate-recommendation-queues/${id}/findings`);
}

export async function getAiCandidateRecommendationQueueDecisions(
  id: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidate-recommendation-queues/${id}/decisions`);
}

export async function getAiCandidateRecommendationQueueHistory(
  id: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidate-recommendation-queues/${id}/history`);
}

export async function getAiCandidateRecommendationQueueSource(
  id: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidate-recommendation-queues/${id}/source`);
}

export async function getAiCandidateRecommendationQueuePromotionEligibility(
  id: number,
): Promise<JsonValue> {
  return getJson(
    `/admin/ai/candidate-recommendation-queues/${id}/promotion-eligibility`,
  );
}

export async function enqueueAiCandidateRecommendationQueue(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-recommendation-queues/${id}/queue`, body);
}

export async function assignAiCandidateRecommendationQueue(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-recommendation-queues/${id}/assign`, body);
}

export async function reassignAiCandidateRecommendationQueue(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/candidate-recommendation-queues/${id}/reassign`,
    body,
  );
}

export async function startReviewAiCandidateRecommendationQueue(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/candidate-recommendation-queues/${id}/start-review`,
    body,
  );
}

export async function submitAiCandidateRecommendationQueueReview(
  reviewId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/candidate-recommendation-queues/reviews/${reviewId}/submit`,
    body,
  );
}

export async function amendAiCandidateRecommendationQueueReview(
  reviewId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/candidate-recommendation-queues/reviews/${reviewId}/amend`,
    body,
  );
}

export async function withdrawAiCandidateRecommendationQueueReview(
  reviewId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/candidate-recommendation-queues/reviews/${reviewId}/withdraw`,
    body,
  );
}

export async function decideAiCandidateRecommendationQueue(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-recommendation-queues/${id}/decide`, body);
}

export async function holdAiCandidateRecommendationQueue(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-recommendation-queues/${id}/hold`, body);
}

export async function resumeAiCandidateRecommendationQueue(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-recommendation-queues/${id}/resume`, body);
}

export async function requestMoreInfoAiCandidateRecommendationQueue(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/candidate-recommendation-queues/${id}/request-more-information`,
    body,
  );
}

export async function withdrawAiCandidateRecommendationQueue(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/candidate-recommendation-queues/${id}/withdraw`,
    body,
  );
}

export async function expireAiCandidateRecommendationQueue(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-recommendation-queues/${id}/expire`, body);
}

export async function revalidateAiCandidateRecommendationQueue(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/candidate-recommendation-queues/${id}/revalidate`,
    body,
  );
}

export async function requeueAiCandidateRecommendationQueue(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-recommendation-queues/${id}/requeue`, body);
}

/** STEP 11-12 — Candidate Promotion Gateway (Commit 시에만 Candidate 등록) */
export async function listAiCandidatePromotions(params?: {
  status_filter?: string;
  exchange_code?: string;
  symbol?: string;
  limit?: number;
  offset?: number;
}): Promise<JsonValue> {
  return getJson("/admin/ai/candidate-promotions", params);
}

export async function getAiCandidatePromotion(id: number): Promise<JsonValue> {
  return getJson(`/admin/ai/candidate-promotions/${id}`);
}

export async function getAiCandidatePromotionDashboard(): Promise<JsonValue> {
  return getJson("/admin/ai/candidate-promotions/dashboard");
}

export async function createAiCandidatePromotion(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/candidate-promotions", body);
}

export async function validateAiCandidatePromotion(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-promotions/${id}/validate`, body);
}

export async function dryRunAiCandidatePromotion(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-promotions/${id}/dry-run`, body);
}

export async function submitFirstApprovalAiCandidatePromotion(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/candidate-promotions/${id}/submit-first-approval`,
    body,
  );
}

export async function approveFirstAiCandidatePromotion(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-promotions/${id}/approve-first`, body);
}

export async function submitFinalApprovalAiCandidatePromotion(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/candidate-promotions/${id}/submit-final-approval`,
    body,
  );
}

export async function approveFinalAiCandidatePromotion(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-promotions/${id}/approve-final`, body);
}

export async function commitAiCandidatePromotion(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-promotions/${id}/commit`, body);
}

export async function cancelAiCandidatePromotion(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-promotions/${id}/cancel`, body);
}

export async function rollbackAiCandidatePromotion(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidate-promotions/${id}/rollback`, body);
}

export async function getAiCandidatePromotionHistory(
  id: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidate-promotions/${id}/history`);
}

export async function getAiCandidatePromotionCandidate(
  id: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidate-promotions/${id}/candidate`);
}

/** STEP 11-13 — Candidate Lifecycle (참조·검증·만료·철회, 매매 아님) */
export async function listAiCandidateLifecycles(params?: {
  lifecycle_status?: string;
  health_status?: string;
  revalidation_required?: boolean;
  limit?: number;
  offset?: number;
}): Promise<JsonValue> {
  return getJson("/admin/ai/candidate-lifecycle", params);
}

export async function getAiCandidateLifecycleDashboard(): Promise<JsonValue> {
  return getJson("/admin/ai/candidate-lifecycle/dashboard");
}

export async function getAiCandidateLifecycle(
  candidateId: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidates/${candidateId}/lifecycle`);
}

export async function getAiCandidateLifecycleProvenance(
  candidateId: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidates/${candidateId}/provenance`);
}

export async function getAiCandidateLifecycleHistory(
  candidateId: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidates/${candidateId}/history`);
}

export async function getAiCandidateLifecycleRevalidations(
  candidateId: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidates/${candidateId}/revalidations`);
}

export async function getAiCandidateLifecycleRevocations(
  candidateId: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/candidates/${candidateId}/revocations`);
}

export async function activateReviewAiCandidateLifecycle(
  candidateId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/candidates/${candidateId}/activate-review`,
    body,
  );
}

export async function validateAiCandidateLifecycle(
  candidateId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidates/${candidateId}/validate`, body);
}

export async function revalidateAiCandidateLifecycle(
  candidateId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidates/${candidateId}/revalidate`, body);
}

export async function expireAiCandidateLifecycle(
  candidateId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidates/${candidateId}/expire`, body);
}

export async function archiveAiCandidateLifecycle(
  candidateId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidates/${candidateId}/archive`, body);
}

export async function supersedeAiCandidateLifecycle(
  candidateId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidates/${candidateId}/supersede`, body);
}

export async function requestRevocationAiCandidateLifecycle(
  candidateId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/candidates/${candidateId}/revocations`, body);
}

export async function approveRevocationAiCandidateLifecycle(
  candidateId: number,
  revocationId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/candidates/${candidateId}/revocations/${revocationId}/approve`,
    body,
  );
}

export async function cancelRevocationAiCandidateLifecycle(
  candidateId: number,
  revocationId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/candidates/${candidateId}/revocations/${revocationId}/cancel`,
    body,
  );
}

/** STEP 12-1 — AI Candidate -> Strategy Request 승인 게이트 (관리자 심사) */
export async function listStrategyRequests(params?: {
  status?: string;
  candidate_id?: number;
  user_id?: number;
  limit?: number;
  offset?: number;
}): Promise<JsonValue> {
  return getJson("/admin/strategy-requests", params);
}

export async function getStrategyRequest(
  strategyRequestId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategy-requests/${strategyRequestId}`);
}

export async function getStrategyRequestHistory(
  strategyRequestId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategy-requests/${strategyRequestId}/history`);
}

export async function approveStrategyRequest(
  strategyRequestId: number,
  body: { review_note?: string; correlation_id?: string },
): Promise<JsonValue> {
  return postJson(
    `/admin/strategy-requests/${strategyRequestId}/approve`,
    body,
  );
}

export async function rejectStrategyRequest(
  strategyRequestId: number,
  body: { review_note: string; correlation_id?: string },
): Promise<JsonValue> {
  return postJson(
    `/admin/strategy-requests/${strategyRequestId}/reject`,
    body,
  );
}

/** STEP 12-2-1 — 승인된 Strategy Request 위의 Strategy Draft 저장/버전관리 */
export interface StrategyDraftContentFields {
  title?: string;
  summary?: string;
  entry_rule?: string;
  exit_rule?: string;
  stop_loss_rule?: string;
  take_profit_rule?: string;
  position_sizing_rule?: string;
  timeframe?: string;
  market_type?: string;
  risk_parameters?: Record<string, unknown>;
  indicator_configuration?: Record<string, unknown>;
  llm_provider?: string;
  llm_model?: string;
  prompt_version?: string;
}

export async function listStrategyDrafts(params?: {
  strategy_request_id?: number;
  version?: number;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<JsonValue> {
  return getJson("/admin/strategy-drafts", params);
}

export async function getStrategyDraft(draftId: number): Promise<JsonValue> {
  return getJson(`/admin/strategy-drafts/${draftId}`);
}

export async function getStrategyDraftHistory(
  draftId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategy-drafts/${draftId}/history`);
}

/** 새 Draft(새 Version) 생성 — strategy_request_id 기준 */
export async function createStrategyDraft(
  body: StrategyDraftContentFields & {
    strategy_request_id: number;
    correlation_id?: string;
  },
): Promise<JsonValue> {
  return postJson("/admin/strategy-drafts", body);
}

/** 같은 Version 안에서 새 Revision 생성 — source_draft_id 기준 */
export async function createStrategyDraftRevision(
  body: StrategyDraftContentFields & {
    strategy_request_id: number;
    source_draft_id: number;
    reason?: string;
    correlation_id?: string;
  },
): Promise<JsonValue> {
  return postJson("/admin/strategy-drafts", body);
}

export async function updateStrategyDraft(
  draftId: number,
  body: StrategyDraftContentFields & {
    reason?: string;
    correlation_id?: string;
  },
): Promise<JsonValue> {
  return patchJson(`/admin/strategy-drafts/${draftId}`, body);
}

export async function archiveStrategyDraft(
  draftId: number,
  body?: { reason?: string; correlation_id?: string },
): Promise<JsonValue> {
  return postJson(`/admin/strategy-drafts/${draftId}/archive`, body ?? {});
}

/** Version 조회 — 해당 Version의 전체 Revision 목록 */
export async function getStrategyDraftVersion(
  strategyRequestId: number,
  version: number,
): Promise<JsonValue> {
  return getJson("/admin/strategy-drafts", {
    strategy_request_id: strategyRequestId,
    version,
  });
}

/** STEP 12-2-2 — AI Strategy Draft Generator(관리자 전용, 검토 전 초안 생성) */
export async function createStrategyDraftGeneration(body: {
  strategy_request_id: number;
  provider_id?: string;
  model?: string;
  idempotency_key?: string;
}): Promise<JsonValue> {
  return postJson("/admin/strategy-draft-generations", body);
}

export async function listStrategyDraftGenerations(params?: {
  strategy_request_id?: number;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<JsonValue> {
  return getJson("/admin/strategy-draft-generations", params);
}

export async function getStrategyDraftGeneration(
  runId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategy-draft-generations/${runId}`);
}

export async function retryStrategyDraftGeneration(
  runId: number,
): Promise<JsonValue> {
  return postJson(`/admin/strategy-draft-generations/${runId}/retry`, {});
}

/** STEP 12-2-3 — Generation Attempt 목록 */
export async function listStrategyDraftGenerationAttempts(
  runId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategy-draft-generations/${runId}/attempts`);
}

/** STEP 12-2-3 — Version/Revision 비교(동일 Strategy Request 내에서만 허용) */
export async function getStrategyDraftComparison(
  draftId: number,
  compareDraftId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategy-drafts/${draftId}/comparison`, {
    compare_draft_id: compareDraftId,
  });
}

/** STEP 12-2-3 — Draft History + Generation Run 병합 Timeline */
export async function getDraftTimeline(
  strategyRequestId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategy-requests/${strategyRequestId}/draft-timeline`);
}

/** STEP 12-3 — Strategy Draft 관리자 최종 승인/반려/취소 */
export async function approveStrategyDraft(
  draftId: number,
  body: { reason: string; idempotency_key?: string },
): Promise<JsonValue> {
  return postJson(`/admin/strategy-drafts/${draftId}/approve`, body);
}

export async function rejectStrategyDraft(
  draftId: number,
  body: { reason: string; idempotency_key?: string },
): Promise<JsonValue> {
  return postJson(`/admin/strategy-drafts/${draftId}/reject`, body);
}

export async function revokeStrategyDraftApproval(
  approvalId: number,
  body: { reason: string },
): Promise<JsonValue> {
  return postJson(`/admin/strategy-draft-approvals/${approvalId}/revoke`, body);
}

export async function listStrategyDraftApprovals(params?: {
  draft_id?: number;
  strategy_request_id?: number;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<JsonValue> {
  return getJson("/admin/strategy-draft-approvals", params);
}

export async function getStrategyDraftApproval(
  approvalId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategy-draft-approvals/${approvalId}`);
}

export async function getStrategyDraftApprovalForDraft(
  draftId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategy-drafts/${draftId}/approval`);
}

export async function getStrategyDraftApprovalHistory(
  approvalId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategy-draft-approvals/${approvalId}/history`);
}

/** STEP 12-4 — Strategy Snapshot(승인으로 생성된 불변 Definition) 조회/이력/Export */
export async function getStrategySnapshot(
  strategyDefinitionId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/snapshot`);
}

export async function getStrategySnapshotHistory(
  strategyDefinitionId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/snapshot/history`);
}

export async function exportStrategySnapshot(
  strategyDefinitionId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/snapshot/export`);
}

/** STEP 12-5 — Backtest Readiness / Provenance Chain 검증 */
export async function getStrategyReadiness(
  strategyDefinitionId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/readiness`);
}

export async function getStrategyProvenance(
  strategyDefinitionId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/provenance`);
}

/** STEP 12-6 — Backtest Executable Specification 컴파일(실행 아님) */
export async function getStrategyBacktestSpecification(
  strategyDefinitionId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/backtest-specification`);
}

/** STEP 12-8 — Backtest 결과 기반 Performance Analytics(Admin 전용, 조회) */
export async function getBacktestRunPerformance(
  backtestRunId: number,
): Promise<JsonValue> {
  return getJson(`/backtest-runs/${backtestRunId}/performance`);
}

export async function getBacktestRunScore(
  backtestRunId: number,
): Promise<JsonValue> {
  return getJson(`/backtest-runs/${backtestRunId}/score`);
}

/** STEP 12-9 — 승인 Strategy Definition의 Walk-Forward Analysis(Admin 전용) */
export async function runStrategyWalkForward(
  strategyDefinitionId: number,
  body: {
    symbol: string;
    exchange_code: string;
    start_date: string;
    end_date: string;
    train_days: number;
    test_days: number;
    window_scheme: "ROLLING" | "EXPANDING";
    initial_capital: string;
    fee_ratio?: string;
    sell_tax_ratio?: string;
    slippage_ratio?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/walk-forward`, body);
}

export async function getStrategyWalkForward(
  strategyDefinitionId: number,
  runId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/walk-forward/${runId}`);
}

export async function getStrategyWalkForwardOverfitting(
  strategyDefinitionId: number,
  runId: number,
): Promise<JsonValue> {
  return getJson(
    `/admin/strategies/${strategyDefinitionId}/walk-forward/${runId}/overfitting`,
  );
}

/** STEP 12-10 — Strategy Quality Gate(Admin 전용) */
export async function runStrategyQualityGate(
  strategyDefinitionId: number,
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/quality-gate`, {});
}

export async function getStrategyQualityGate(
  strategyDefinitionId: number,
  reportId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/quality-gate/${reportId}`);
}

export async function getStrategyQualityGateRecommendation(
  strategyDefinitionId: number,
  reportId: number,
): Promise<JsonValue> {
  return getJson(
    `/admin/strategies/${strategyDefinitionId}/quality-gate/${reportId}/recommendation`,
  );
}

/** STEP 12-11 — Parameter Sensitivity Analysis(Admin 전용) */
export async function runStrategyParameterSensitivity(
  strategyDefinitionId: number,
  body: {
    symbol: string;
    exchange_code: string;
    start_date: string;
    end_date: string;
    initial_capital: string;
    parameter_names: string[];
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(
    `/admin/strategies/${strategyDefinitionId}/parameter-sensitivity`,
    body,
  );
}

export async function getStrategyParameterSensitivity(
  strategyDefinitionId: number,
  reportId: number,
): Promise<JsonValue> {
  return getJson(
    `/admin/strategies/${strategyDefinitionId}/parameter-sensitivity/${reportId}`,
  );
}

export async function getStrategyParameterSensitivitySummary(
  strategyDefinitionId: number,
  reportId: number,
): Promise<JsonValue> {
  return getJson(
    `/admin/strategies/${strategyDefinitionId}/parameter-sensitivity/${reportId}/summary`,
  );
}

export async function getStrategyParameterSensitivityVariations(
  strategyDefinitionId: number,
  reportId: number,
): Promise<JsonValue> {
  return getJson(
    `/admin/strategies/${strategyDefinitionId}/parameter-sensitivity/${reportId}/variations`,
  );
}

/** STEP 12-12 — Monte Carlo Simulation(Admin 전용, 기존 Backtest Trade 재사용) */
export async function runStrategyMonteCarlo(
  strategyDefinitionId: number,
  body: {
    backtest_run_id: number;
    simulation_method: "TRADE_ORDER_SHUFFLE" | "BOOTSTRAP_WITH_REPLACEMENT" | "BLOCK_BOOTSTRAP";
    simulation_count?: number;
    random_seed?: number;
    confidence_level?: string;
    ruin_threshold_percent?: string;
    block_size?: number;
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/monte-carlo`, body);
}

export async function getStrategyMonteCarlo(
  strategyDefinitionId: number,
  reportId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/monte-carlo/${reportId}`);
}

export async function getStrategyMonteCarloSummary(
  strategyDefinitionId: number,
  reportId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/monte-carlo/${reportId}/summary`);
}

export async function getStrategyMonteCarloDistribution(
  strategyDefinitionId: number,
  reportId: number,
): Promise<JsonValue> {
  return getJson(
    `/admin/strategies/${strategyDefinitionId}/monte-carlo/${reportId}/distribution`,
  );
}

export async function getStrategyMonteCarloRepresentatives(
  strategyDefinitionId: number,
  reportId: number,
): Promise<JsonValue> {
  return getJson(
    `/admin/strategies/${strategyDefinitionId}/monte-carlo/${reportId}/representatives`,
  );
}

/**
 * STEP 12-14 — Strategy Explainability & Decision Evidence Layer(Admin 전용).
 * 이미 승인된 Strategy Definition과 이미 완료된 검증 Report만 읽어 사람이
 * 이해할 수 있는 설명 + Evidence Reference로 재구성한다. 새 Backtest나
 * 검증 계산을 수행하지 않고, 자동 승인·반려·Promotion을 수행하지 않는다.
 */
export async function runStrategyExplainability(
  strategyDefinitionId: number,
  body: {
    backtest_run_id?: number;
    walk_forward_run_id?: number;
    quality_gate_report_id?: number;
    parameter_sensitivity_report_id?: number;
    monte_carlo_report_id?: number;
    portfolio_validation_report_id?: number;
    explanation_language?: string;
    explanation_mode?: string;
    use_latest_when_missing?: boolean;
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/explainability`, body);
}

export async function getStrategyExplainability(
  strategyDefinitionId: number,
  reportId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/explainability/${reportId}`);
}

export async function getStrategyExplainabilitySummary(
  strategyDefinitionId: number,
  reportId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/explainability/${reportId}/summary`);
}

export async function getStrategyExplainabilityEvidence(
  strategyDefinitionId: number,
  reportId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/explainability/${reportId}/evidence`);
}

export async function getStrategyExplainabilityChecklist(
  strategyDefinitionId: number,
  reportId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/explainability/${reportId}/checklist`);
}

export async function getStrategyExplainabilityMissing(
  strategyDefinitionId: number,
  reportId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/explainability/${reportId}/missing`);
}

/**
 * STEP 12-15 — Decision Package & Human Decision(Admin 전용).
 * 이미 생성된 Explainability/Quality Gate/Sensitivity/Monte Carlo/
 * Portfolio Validation 결과를 하나의 동결된 Decision Package로 묶고,
 * 관리자가 APPROVE_FOR_PROMOTION/REQUEST_CHANGES/REJECT 중 하나를
 * 불변으로 기록한다. 실제 Promotion Commit은 수행하지 않는다.
 */
export async function createDecisionPackage(
  strategyDefinitionId: number,
  body: {
    explainability_report_id: number;
    quality_gate_report_id?: number;
    parameter_sensitivity_report_id?: number;
    monte_carlo_report_id?: number;
    portfolio_validation_report_id?: number;
    package_note?: string;
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/decision-packages`, body);
}

export async function getDecisionPackage(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/decision-packages/${packageId}`);
}

export async function getDecisionPackageSummary(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/decision-packages/${packageId}/summary`);
}

export async function getDecisionPackageChecklist(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/decision-packages/${packageId}/checklist`);
}

export async function getDecisionPackageStaleness(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/decision-packages/${packageId}/staleness`);
}

export async function recordHumanDecision(
  strategyDefinitionId: number,
  packageId: number,
  body: {
    decision_type: "APPROVE_FOR_PROMOTION" | "REQUEST_CHANGES" | "REJECT";
    reason_code: string;
    reason_text: string;
    checklist_confirmations?: Record<string, boolean>;
    acknowledged_warnings?: string[];
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/decision-packages/${packageId}/decisions`, body);
}

export async function getHumanDecision(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/decision-packages/${packageId}/decision`);
}

export async function getPromotionReadiness(strategyDefinitionId: number): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/promotion-readiness`);
}

/**
 * STEP 12-16 — Promotion Commit(Admin 전용).
 * Decision Package/Human Decision(APPROVE_FOR_PROMOTION)을 최종
 * 재검증한 뒤 관리자의 명시적 요청으로만 생성되는 불변 기록. Activation/
 * Deployment/Runtime 등록은 수행하지 않는다.
 */
export async function createPromotionCommit(
  strategyDefinitionId: number,
  body: {
    decision_package_id: number;
    human_decision_id: number;
    promotion_readiness_hash: string;
    commit_reason: string;
    confirmation_text: string;
    acknowledge_same_actor_warning?: boolean;
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/promotion-commits`, body);
}

export async function listPromotionCommits(strategyDefinitionId: number): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/promotion-commits`);
}

export async function getPromotionCommit(
  strategyDefinitionId: number,
  commitId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/promotion-commits/${commitId}`);
}

export async function getPromotionStatus(strategyDefinitionId: number): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/promotion-status`);
}

export async function getPromotionCommitProvenance(
  strategyDefinitionId: number,
  commitId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/promotion-commits/${commitId}/provenance`);
}

export async function getPromotionCommitHistory(
  strategyDefinitionId: number,
  commitId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/promotion-commits/${commitId}/history`);
}

/**
 * STEP 12-17 — Activation Review & Activation Commit(Admin 전용).
 * PROMOTION_COMMITTED Strategy를 대상으로 계좌/시장/브로커/리스크/운영
 * 준비 상태를 검증하고 관리자의 명시적 Activation Commit으로 Strategy
 * Promotion Status를 ACTIVATED로 전환한다. Runtime 등록/시작, Scheduler
 * 등록, Broker 연결, 주문 실행은 수행하지 않는다.
 */
export async function createActivationReviewPackage(
  strategyDefinitionId: number,
  body: {
    promotion_commit_id: number;
    target_market_type: string;
    target_broker_code: string;
    target_account_kind: string;
    target_user_broker_account_id?: number | null;
    target_paper_account_id?: number | null;
    requested_execution_mode: string;
    requested_runtime_scope?: Record<string, unknown> | null;
    requested_capital_limit?: string | null;
    review_note?: string | null;
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/activation-review-packages`, body);
}

export async function listActivationReviewPackages(strategyDefinitionId: number): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/activation-review-packages`);
}

export async function getActivationReviewPackage(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/activation-review-packages/${packageId}`);
}

export async function getActivationReviewPackageChecklist(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/activation-review-packages/${packageId}/checklist`);
}

export async function getActivationReviewPackageStaleness(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/activation-review-packages/${packageId}/staleness`);
}

export async function recordActivationDecision(
  strategyDefinitionId: number,
  packageId: number,
  body: {
    decision_type: string;
    reason_code: string;
    reason_text: string;
    checklist_confirmations?: Record<string, boolean>;
    acknowledged_warnings?: string[];
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/activation-review-packages/${packageId}/decisions`, body);
}

export async function getActivationDecision(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/activation-review-packages/${packageId}/decision`);
}

export async function createActivationCommit(
  strategyDefinitionId: number,
  body: {
    activation_review_package_id: number;
    activation_decision_id: number;
    activation_readiness_hash: string;
    commit_reason: string;
    confirmation_text: string;
    acknowledge_same_actor_warning?: boolean;
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/activation-commits`, body);
}

export async function getActivationStatus(strategyDefinitionId: number): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/activation-status`);
}

export async function getActivationCommit(
  strategyDefinitionId: number,
  commitId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/activation-commits/${commitId}`);
}

export async function getActivationCommitHistory(
  strategyDefinitionId: number,
  commitId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/activation-commits/${commitId}/history`);
}

/**
 * STEP 12-18 — Runtime Registration Review Package & Commit(Admin 전용).
 * ACTIVATED Strategy를 대상으로 계좌/시장/브로커/리스크/운영 준비 상태를
 * 재검증하고, 관리자의 명시적 Commit으로 Runtime Registry에 비실행
 * (enabled=false, running=false) 상태로만 등록한다. Runtime 시작,
 * Scheduler 등록, Broker 연결/로그인, 실시간 시세 구독, Signal 계산,
 * 주문 생성/전송은 수행하지 않는다.
 */
export async function createRuntimeRegistrationPackage(
  strategyDefinitionId: number,
  body: {
    activation_commit_id: number;
    activation_decision_id: number;
    target_account_kind: string;
    target_user_broker_account_id?: number | null;
    target_paper_account_id?: number | null;
    target_market_type: string;
    target_broker_code: string;
    execution_mode: string;
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/runtime-registration-packages`, body);
}

export async function getRuntimeRegistrationPackage(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/runtime-registration-packages/${packageId}`);
}

export async function getRuntimeRegistrationPackageChecklist(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/runtime-registration-packages/${packageId}/checklist`);
}

export async function recordRuntimeRegistrationDecision(
  strategyDefinitionId: number,
  packageId: number,
  body: {
    decision_type: string;
    reason_code: string;
    reason_text: string;
    checklist_confirmations?: Record<string, boolean>;
    acknowledged_warnings?: string[];
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/runtime-registration-packages/${packageId}/decisions`, body);
}

export async function getRuntimeRegistrationDecision(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/runtime-registration-packages/${packageId}/decision`);
}

export async function createRuntimeRegistrationCommit(
  strategyDefinitionId: number,
  body: {
    runtime_registration_package_id: number;
    runtime_registration_decision_id: number;
    registration_input_hash: string;
    decision_input_hash: string;
    commit_reason: string;
    confirmation_text: string;
    acknowledge_same_actor_warning?: boolean;
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/runtime-registration-commits`, body);
}

export async function getRuntimeRegistrationStatus(strategyDefinitionId: number): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/runtime-registration-status`);
}

export async function getRuntimeRegistrationHistory(
  strategyDefinitionId: number,
  params?: { runtime_scope_hash?: string },
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/runtime-registration-history`, params);
}

/** STEP 12-19 Carry-forward — 다중 Runtime Scope 목록(단일 최신 Status로는
 * 표현할 수 없는, Strategy당 여러 등록 상태를 개별 행으로 보여준다). */
export async function getRuntimeRegistrationScopes(strategyDefinitionId: number): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/runtime-registration-scopes`);
}

/**
 * STEP 12-19 — Runtime Deployment Readiness & Disabled Scheduler Plan
 * (Admin 전용). REGISTERED(비실행) Runtime Scope를 대상으로 계좌/시장/
 * 브로커/리스크/운영 준비 상태를 재검증하고, 관리자의 명시적 Deployment
 * Commit으로 StrategyDeployment를 READY_TO_START 상태로만 확정한다.
 * Scheduler Plan은 enabled=false/registered_to_scheduler=false로만
 * 저장되며, Runtime 시작, 실제 Scheduler 등록, Broker 연결/로그인, 실시간
 * 시세 구독, Signal 계산, 주문 생성/전송은 수행하지 않는다.
 */
export async function createDeploymentReadinessPackage(
  strategyDefinitionId: number,
  body: {
    runtime_registration_commit_id: number;
    runtime_registry_id: number;
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/deployment-readiness-packages`, body);
}

export async function getDeploymentReadinessPackage(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/deployment-readiness-packages/${packageId}`);
}

export async function getDeploymentReadinessPackageChecklist(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/deployment-readiness-packages/${packageId}/checklist`);
}

export async function recordDeploymentReadinessDecision(
  strategyDefinitionId: number,
  packageId: number,
  body: {
    decision_type: string;
    reason_code: string;
    reason_text: string;
    checklist_confirmations?: Record<string, boolean>;
    acknowledged_warnings?: string[];
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/deployment-readiness-packages/${packageId}/decisions`, body);
}

export async function getDeploymentReadinessDecision(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/deployment-readiness-packages/${packageId}/decision`);
}

export async function createDeploymentReadinessCommit(
  strategyDefinitionId: number,
  body: {
    deployment_readiness_package_id: number;
    deployment_readiness_decision_id: number;
    runtime_registration_commit_id: number;
    runtime_scope_hash: string;
    deployment_input_hash: string;
    decision_input_hash: string;
    commit_reason: string;
    confirmation_text: string;
    acknowledge_same_actor_warning?: boolean;
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/deployment-readiness-commits`, body);
}

export async function getDeploymentReadinessStatus(strategyDefinitionId: number): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/deployment-readiness-status`);
}

export async function getDeploymentReadinessHistory(
  strategyDefinitionId: number,
  params?: { runtime_scope_hash?: string },
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/deployment-readiness-history`, params);
}

export async function getDeploymentReadinessScopes(strategyDefinitionId: number): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/deployment-readiness-scopes`);
}

export async function listSchedulerPlans(strategyDefinitionId: number): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/scheduler-plans`);
}

/**
 * STEP 12-20 — Operation Readiness Certification(Admin 전용, STEP12
 * 마지막 단계). READY_TO_START Deployment를 대상으로 Strategy/Promotion/
 * Activation/Runtime Registration/Deployment/Scheduler Plan/Credential/
 * Risk/Trading Flag/Kill Switch/Recovery/Account/Runtime Scope/Deployment
 * Scope/History/Audit 15개 영역을 재검증하고, 관리자의 명시적 Operation
 * Commit으로 같은 Deployment 행을 READY_TO_OPERATE로 전진시킨다. Runtime
 * 시작, 실제 Scheduler 등록, Broker 연결/로그인, 실시간 시세 구독, 주문
 * 생성/전송은 수행하지 않는다.
 */
export async function createOperationReadinessPackage(
  strategyDefinitionId: number,
  body: { deployment_readiness_commit_id: number; idempotency_key?: string },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/operation-readiness-packages`, body);
}

export async function getOperationReadinessPackage(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/operation-readiness-packages/${packageId}`);
}

export async function getOperationReadinessPackageChecklist(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/operation-readiness-packages/${packageId}/checklist`);
}

export async function getOperationReadinessCertification(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/operation-readiness-packages/${packageId}/certification`);
}

export async function recordOperationReadinessDecision(
  strategyDefinitionId: number,
  packageId: number,
  body: {
    decision_type: string;
    reason_code: string;
    reason_text: string;
    checklist_confirmations?: Record<string, boolean>;
    acknowledged_warnings?: string[];
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/operation-readiness-packages/${packageId}/decisions`, body);
}

export async function getOperationReadinessDecision(
  strategyDefinitionId: number,
  packageId: number,
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/operation-readiness-packages/${packageId}/decision`);
}

export async function createOperationReadinessCommit(
  strategyDefinitionId: number,
  body: {
    operation_readiness_package_id: number;
    operation_readiness_decision_id: number;
    deployment_readiness_commit_id: number;
    runtime_scope_hash: string;
    operation_input_hash: string;
    decision_input_hash: string;
    commit_reason: string;
    confirmation_text: string;
    acknowledge_same_actor_warning?: boolean;
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/operation-readiness-commits`, body);
}

export async function getOperationReadinessStatus(strategyDefinitionId: number): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/operation-readiness-status`);
}

export async function listOperationReadinessCommits(strategyDefinitionId: number): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/operation-readiness-commits`);
}

export async function getOperationReadinessHistory(
  strategyDefinitionId: number,
  params?: { runtime_scope_hash?: string },
): Promise<JsonValue> {
  return getJson(`/admin/strategies/${strategyDefinitionId}/operation-readiness-history`, params);
}

/**
 * STEP 12-13 — Portfolio Validation(Admin 전용).
 * 이미 승인된 복수 Strategy Definition의 기존 Backtest 결과만 조합해
 * 상관관계/집중도/분산효과/위험기여도/중복노출을 검증한다. 새 Backtest를
 * 실행하거나 실제 Portfolio/자금을 배분하지 않는다.
 */
export async function runPortfolioValidation(body: {
  strategy_definition_ids: number[];
  backtest_run_ids: number[];
  weighting_method?: "EQUAL_WEIGHT" | "CUSTOM_WEIGHT";
  strategy_weights?: Record<number, string>;
  alignment_policy?: "INTERSECTION" | "UNION_FORWARD_FILL";
  minimum_overlap_days?: number;
  initial_capital?: string;
  correlation_threshold?: string;
  concentration_threshold?: string;
  idempotency_key?: string;
}): Promise<JsonValue> {
  return postJson("/admin/portfolio-validations", body);
}

export async function getPortfolioValidation(reportId: number): Promise<JsonValue> {
  return getJson(`/admin/portfolio-validations/${reportId}`);
}

export async function getPortfolioValidationSummary(
  reportId: number,
): Promise<JsonValue> {
  return getJson(`/admin/portfolio-validations/${reportId}/summary`);
}

export async function getPortfolioValidationCorrelations(
  reportId: number,
): Promise<JsonValue> {
  return getJson(`/admin/portfolio-validations/${reportId}/correlations`);
}

export async function getPortfolioValidationRiskContributions(
  reportId: number,
): Promise<JsonValue> {
  return getJson(`/admin/portfolio-validations/${reportId}/risk-contributions`);
}

export async function getPortfolioValidationExposures(
  reportId: number,
): Promise<JsonValue> {
  return getJson(`/admin/portfolio-validations/${reportId}/exposures`);
}

/** STEP 12-7 — 승인 Strategy Definition 기반 과거 데이터 Backtest 실행(Admin 전용) */
export async function runStrategyBacktest(
  strategyDefinitionId: number,
  body: {
    symbol: string;
    exchange_code: string;
    start_date: string;
    end_date: string;
    initial_capital: string;
    fee_ratio?: string;
    sell_tax_ratio?: string;
    slippage_ratio?: string;
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  return postJson(`/admin/strategies/${strategyDefinitionId}/backtests`, body);
}

/** STEP 11-8 — AI 분석 품질 검토 (매매 승인 아님) */
export async function listAiReviewAssignments(params?: {
  status?: string;
}): Promise<JsonValue> {
  return getJson("/admin/ai/review-assignments", params);
}

export async function getAiReviewAssignment(id: number): Promise<JsonValue> {
  return getJson(`/admin/ai/review-assignments/${id}`);
}

export async function createAiReviewAssignment(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/review-assignments", body);
}

export async function assignAiReviewAssignment(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/review-assignments/${id}/assign`, body);
}

export async function cancelAiReviewAssignment(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/review-assignments/${id}/cancel`, body);
}

export async function createAiReviewDraft(
  assignmentId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/review-assignments/${assignmentId}/reviews`, body);
}

export async function listAiReviewsForAssignment(
  assignmentId: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/review-assignments/${assignmentId}/reviews`);
}

export async function getAiReview(id: number): Promise<JsonValue> {
  return getJson(`/admin/ai/reviews/${id}`);
}

export async function submitAiReview(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/reviews/${id}/submit`, body);
}

export async function amendAiReview(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/reviews/${id}/amend`, body);
}

export async function withdrawAiReview(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/reviews/${id}/withdraw`, body);
}

export async function getAiReviewDashboard(): Promise<JsonValue> {
  return getJson("/admin/ai/reviews/dashboard");
}

export async function getAiReviewDecision(
  sourceType: string,
  sourceId: number,
): Promise<JsonValue> {
  return getJson(`/admin/ai/review-decisions/${sourceType}/${sourceId}`);
}

export async function overrideAiReviewDecision(
  sourceType: string,
  sourceId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/review-decisions/${sourceType}/${sourceId}/override`,
    body,
  );
}

export async function recalculateAiReviewDecision(
  sourceType: string,
  sourceId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/review-decisions/${sourceType}/${sourceId}/recalculate`,
    body,
  );
}

export async function listAiEvaluationDatasets(params?: {
  limit?: number;
}): Promise<JsonValue> {
  return getJson("/admin/ai/evaluation-datasets", params);
}

export async function getAiEvaluationDataset(id: number): Promise<JsonValue> {
  return getJson(`/admin/ai/evaluation-datasets/${id}`);
}

export async function createAiEvaluationDataset(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/evaluation-datasets", body);
}

export async function addAiEvaluationDatasetItem(
  datasetId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/evaluation-datasets/${datasetId}/items`, body);
}

export async function validateAiEvaluationDataset(
  datasetId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/evaluation-datasets/${datasetId}/validate`,
    body,
  );
}

export async function activateAiEvaluationDataset(
  datasetId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/evaluation-datasets/${datasetId}/activate`,
    body,
  );
}

export async function archiveAiEvaluationDataset(
  datasetId: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(
    `/admin/ai/evaluation-datasets/${datasetId}/archive`,
    body,
  );
}

export async function listAiBenchmarks(params?: {
  limit?: number;
}): Promise<JsonValue> {
  return getJson("/admin/ai/benchmarks", params);
}

export async function getAiBenchmark(id: number): Promise<JsonValue> {
  return getJson(`/admin/ai/benchmarks/${id}`);
}

export async function createAiBenchmark(
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson("/admin/ai/benchmarks", body);
}

export async function dryRunAiBenchmark(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/benchmarks/${id}/dry-run`, body);
}

export async function executeAiBenchmark(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/benchmarks/${id}/execute`, body);
}

export async function cancelAiBenchmark(
  id: number,
  body: Record<string, unknown>,
): Promise<JsonValue> {
  return postJson(`/admin/ai/benchmarks/${id}/cancel`, body);
}

export async function getAiBenchmarkDashboard(): Promise<JsonValue> {
  return getJson("/admin/ai/benchmarks/dashboard");
}

export async function getAiScorecards(params?: {
  dataset_id?: number;
}): Promise<JsonValue> {
  return getJson("/admin/ai/scorecards", params);
}

export async function compareAiScorecards(params: {
  left_benchmark_id: number;
  right_benchmark_id: number;
}): Promise<JsonValue> {
  return getJson("/admin/ai/scorecards/compare", params);
}

export async function getAiCalibration(): Promise<JsonValue> {
  return getJson("/admin/ai/scorecards/calibration");
}

/** STEP 8-11 — 통합 운영 모니터링 (Read-only) */
export async function getOpsDashboardOverview(): Promise<JsonValue> {
  return getJson("/admin/operations-dashboard/overview");
}

export async function getOpsDashboardAccounts(params?: {
  include_broker_balances?: boolean;
}): Promise<JsonValue> {
  return getJson("/admin/operations-dashboard/accounts", params);
}

export async function getOpsDashboardSchedulers(): Promise<JsonValue> {
  return getJson("/admin/operations-dashboard/schedulers");
}

export async function getOpsDashboardRuntimes(): Promise<JsonValue> {
  return getJson("/admin/operations-dashboard/runtimes");
}

export async function getOpsDashboardRisk(): Promise<JsonValue> {
  return getJson("/admin/operations-dashboard/risk");
}

export async function getOpsDashboardOrders(
  params?: Params,
): Promise<JsonValue> {
  return getJson("/admin/operations-dashboard/orders", params);
}

export async function getOpsDashboardPositions(): Promise<JsonValue> {
  return getJson("/admin/operations-dashboard/positions");
}

export async function getOpsDashboardAlerts(params?: {
  limit?: number;
}): Promise<JsonValue> {
  return getJson("/admin/operations-dashboard/alerts", params);
}

export async function getOpsDashboardAudits(params?: Params): Promise<JsonValue> {
  return getJson("/admin/operations-dashboard/audits", params);
}

export async function getOpsDashboardNotifications(params?: {
  limit?: number;
}): Promise<JsonValue> {
  return getJson("/admin/operations-dashboard/notifications", params);
}

export async function getRealtimeTradingSchedulerStatus(): Promise<JsonValue> {
  return getJson("/realtime-sessions/status");
}

export async function stopRealtimeTradingScheduler(): Promise<JsonValue> {
  return postJson("/realtime-sessions/stop-scheduler", {});
}

export async function startRealtimeTradingScheduler(): Promise<JsonValue> {
  return postJson("/realtime-sessions/start-scheduler", {});
}

/** STEP 9-5 — Trading Scheduler Start/Pause (LIVE/ARM gate) */
export async function getTradingSchedulerStatus(): Promise<JsonValue> {
  return getJson("/admin/trading-scheduler/status");
}

export async function startTradingScheduler(body: {
  reason: string;
  correlation_id: string;
  user_broker_account_id: number;
  min_arm_remaining_seconds?: number;
}): Promise<JsonValue> {
  return postJson("/admin/trading-scheduler/start", body);
}

export async function pauseTradingScheduler(body: {
  reason: string;
  correlation_id: string;
  user_broker_account_id?: number | null;
}): Promise<JsonValue> {
  return postJson("/admin/trading-scheduler/pause", body);
}

export interface BrokerRecoveryStatus {
  running: boolean;
  last_result: {
    success?: boolean;
    started_at?: string;
    finished_at?: string;
    steps?: Array<{
      component?: string;
      status?: string;
      message?: string;
      detail?: unknown;
    }>;
  } | null;
  last_error: string | null;
}

export async function getBrokerRecoveryStatus(): Promise<BrokerRecoveryStatus> {
  const { data } = await apiClient.get<BrokerRecoveryStatus>(
    "/broker/recovery/status",
  );
  return data;
}

export async function runBrokerRecovery(): Promise<{
  success: boolean;
  started_at?: string;
  finished_at?: string;
  steps?: Array<{
    component?: string;
    status?: string;
    message?: string;
    detail?: unknown;
  }>;
  accounts?: unknown[];
  account_count?: number;
}> {
  const { data } = await apiClient.post<{
    success: boolean;
    started_at?: string;
    finished_at?: string;
    steps?: Array<{
      component?: string;
      status?: string;
      message?: string;
      detail?: unknown;
    }>;
    accounts?: unknown[];
    account_count?: number;
  }>("/broker/recovery/run");
  return data;
}

/** STEP 8-4 — 통합 Recovery Admin API */
export async function getAdminRecoveryStatus(): Promise<JsonValue> {
  return getJson("/admin/recovery/status");
}

export async function listAdminRecoveryRuns(params?: {
  broker_code?: string;
  status_code?: string;
  limit?: number;
  offset?: number;
}): Promise<JsonValue> {
  return getJson("/admin/recovery/runs", params);
}

export async function getAdminRecoveryRun(
  recoveryId: number,
): Promise<JsonValue> {
  return getJson(`/admin/recovery/runs/${recoveryId}`);
}

export async function runAdminRecovery(body?: {
  broker_code?: string;
  paper_account_id?: number;
  user_broker_account_id?: number;
  concurrency?: number;
}): Promise<JsonValue> {
  return postJson("/admin/recovery/run", body ?? {});
}

export async function runAdminBrokerRecovery(
  brokerCode: string,
): Promise<JsonValue> {
  return postJson(`/admin/recovery/brokers/${brokerCode}/run`, {});
}

export async function runAdminAccountRecovery(
  accountId: number,
  accountType = "PAPER",
): Promise<JsonValue> {
  return postJson(
    `/admin/recovery/accounts/${accountId}/run`,
    {},
    { account_type: accountType },
  );
}

/** STEP 8-5-6 — Distributed Recovery Lock */
export async function listAdminRecoveryLocks(params?: {
  status?: string;
  limit?: number;
}): Promise<JsonValue> {
  return getJson("/admin/recovery/locks", params);
}

export async function getAdminRecoveryLock(
  scopeKey: string,
): Promise<JsonValue> {
  return getJson(
    `/admin/recovery/locks/${encodeURIComponent(scopeKey)}`,
  );
}

/** STEP 8-5-7/8-5-11 — KRX Market Calendar */
export async function listAdminMarketCalendar(params: {
  exchange_code?: string;
  start_date: string;
  end_date: string;
  verified_status?: string;
}): Promise<JsonValue> {
  return getJson("/admin/market-calendar", params);
}

export async function getAdminMarketCalendarCoverage(): Promise<JsonValue> {
  return getJson("/admin/market-calendar/coverage");
}

export async function getAdminMarketCalendarChangeHealth(): Promise<JsonValue> {
  return getJson("/admin/market-calendar/change-health");
}

export async function syncAdminMarketCalendar(body?: {
  from_date?: string;
  to_date?: string;
  mark_verified?: boolean;
  past_years?: number;
}): Promise<JsonValue> {
  return postJson("/admin/market-calendar/sync", body ?? {});
}

export async function listAdminCalendarChangeRequests(params?: {
  status?: string;
  exchange_code?: string;
  limit?: number;
}): Promise<JsonValue> {
  return getJson("/admin/market-calendar/change-requests", params ?? {});
}

export async function createAdminCalendarChangeRequest(body: {
  exchange_code?: string;
  market_date: string;
  change_type: string;
  requested_values: Record<string, unknown>;
  reason: string;
  source_type?: string;
  source_reference?: string | null;
  emergency?: boolean;
  expected_revision?: number | null;
}): Promise<JsonValue> {
  return postJson("/admin/market-calendar/change-requests", body);
}

export async function submitAdminCalendarChangeRequest(
  requestId: number,
): Promise<JsonValue> {
  return postJson(
    `/admin/market-calendar/change-requests/${requestId}/submit`,
    {},
  );
}

export async function approveAdminCalendarChangeRequest(
  requestId: number,
  comment?: string,
): Promise<JsonValue> {
  return postJson(
    `/admin/market-calendar/change-requests/${requestId}/approve`,
    { comment: comment ?? null },
  );
}

export async function rejectAdminCalendarChangeRequest(
  requestId: number,
  reason: string,
): Promise<JsonValue> {
  return postJson(
    `/admin/market-calendar/change-requests/${requestId}/reject`,
    { reason },
  );
}

export async function applyAdminCalendarChangeRequest(
  requestId: number,
): Promise<JsonValue> {
  return postJson(
    `/admin/market-calendar/change-requests/${requestId}/apply`,
    {},
  );
}

export async function cancelAdminCalendarChangeRequest(
  requestId: number,
): Promise<JsonValue> {
  return postJson(
    `/admin/market-calendar/change-requests/${requestId}/cancel`,
    {},
  );
}

export async function getAdminCalendarDayHistory(
  exchangeCode: string,
  calendarDate: string,
): Promise<JsonValue> {
  return getJson(
    `/admin/market-calendar/${encodeURIComponent(exchangeCode)}/${calendarDate}/history`,
  );
}

export async function rollbackAdminCalendarDay(
  exchangeCode: string,
  calendarDate: string,
  body: { target_revision: number; reason: string },
): Promise<JsonValue> {
  return postJson(
    `/admin/market-calendar/${encodeURIComponent(exchangeCode)}/${calendarDate}/rollback`,
    body,
  );
}

export async function updateAdminMarketCalendarDay(
  exchangeCode: string,
  calendarDate: string,
  body: {
    is_trading_day: boolean;
    session_type: string;
    holiday_name?: string | null;
    closure_reason?: string | null;
    regular_open_at?: string | null;
    regular_close_at?: string | null;
    reason: string;
    source_reference?: string | null;
    emergency?: boolean;
    apply_now?: boolean;
    expected_revision?: number | null;
  },
): Promise<JsonValue> {
  return putJson(
    `/admin/market-calendar/${encodeURIComponent(exchangeCode)}/${calendarDate}`,
    body,
  );
}

export async function verifyAdminMarketCalendarDay(
  exchangeCode: string,
  calendarDate: string,
  status = "VERIFIED",
): Promise<JsonValue> {
  return postJson(
    `/admin/market-calendar/${encodeURIComponent(exchangeCode)}/${calendarDate}/verify`,
    { status, reason: `verify ${status}`, apply_now: true },
  );
}

export async function getUserMarketCalendarStatus(
  exchangeCode = "KRX",
): Promise<JsonValue> {
  return getJson("/user/market-calendar/status", {
    exchange_code: exchangeCode,
  });
}

/** STEP 8-5-13 — KRX Session Timeline / Dynamic Job */
export interface AdminMarketCalendarTimeline {
  exchange_code: string;
  market_date: string;
  revision: number;
  timezone: string;
  session_type: string | null;
  is_trading_day: boolean;
  live_allowed: boolean;
  reason_code: string;
  preopen_start_at: string | null;
  order_entry_start_at: string | null;
  regular_open_at: string | null;
  new_entry_cutoff_at: string | null;
  regular_close_at: string | null;
  post_close_start_at: string | null;
  recovery_preopen_at: string | null;
  recovery_postclose_at: string | null;
  snapshot_at: string | null;
  settlement_at: string | null;
  analysis_at: string | null;
  current_phase: string;
  next_transition_at: string | null;
  next_transition_phase: string | null;
}

export async function getAdminMarketCalendarTimeline(
  exchangeCode: string,
  calendarDate: string,
): Promise<AdminMarketCalendarTimeline> {
  const { data } = await apiClient.get<AdminMarketCalendarTimeline>(
    `/admin/market-calendar/${encodeURIComponent(exchangeCode)}/${calendarDate}/timeline`,
  );
  return data;
}

export interface AdminMarketCalendarJob {
  job_id: string;
  job_type: string;
  status: string;
  run_at: string;
  revision: number;
  exchange_code: string;
  market_date: string;
  error?: string;
}

export async function getAdminMarketCalendarJobs(
  exchangeCode: string,
  calendarDate: string,
): Promise<{ items: AdminMarketCalendarJob[]; count: number }> {
  const data = await getJson(
    `/admin/market-calendar/${encodeURIComponent(exchangeCode)}/${calendarDate}/jobs`,
  );
  const row = data as { items?: AdminMarketCalendarJob[]; count?: number };
  return {
    items: Array.isArray(row.items) ? row.items : [],
    count: row.count ?? 0,
  };
}

export async function recomputeAdminMarketCalendarJobs(
  exchangeCode: string,
  calendarDate: string,
): Promise<JsonValue> {
  return postJson(
    `/admin/market-calendar/${encodeURIComponent(exchangeCode)}/${calendarDate}/recompute-jobs`,
    {},
  );
}

/** STEP 8-5-3 — Recovery Scheduler */
export interface RecoverySchedulerJob {
  job_id: string;
  display_name: string;
  broker_code: string;
  trigger_type: string;
  is_enabled: boolean;
  cron_expression: string | null;
  interval_minutes: number | null;
  timezone: string;
  timeout_seconds: number;
  max_retries: number;
  concurrency: number;
  last_run_at: string | null;
  next_run_at: string | null;
  last_status: string | null;
  last_error_summary: string | null;
  last_result_summary?: Record<string, unknown>;
}

export async function getRecoverySchedulerStatus(): Promise<JsonValue> {
  return getJson("/admin/recovery/scheduler/status");
}

export async function listRecoverySchedulerJobs(): Promise<{
  items: RecoverySchedulerJob[];
  total: number;
}> {
  const data = await getJson("/admin/recovery/scheduler/jobs");
  const row = data as { items?: RecoverySchedulerJob[]; total?: number };
  return {
    items: Array.isArray(row.items) ? row.items : [],
    total: row.total ?? 0,
  };
}

export async function updateRecoverySchedulerJob(
  jobId: string,
  body: {
    is_enabled?: boolean;
    cron_expression?: string | null;
    interval_minutes?: number | null;
    timeout_seconds?: number;
    max_retries?: number;
    concurrency?: number;
  },
): Promise<RecoverySchedulerJob> {
  const data = await putJson(
    `/admin/recovery/scheduler/jobs/${jobId}`,
    body,
  );
  return data as RecoverySchedulerJob;
}

export async function enableRecoverySchedulerJob(
  jobId: string,
): Promise<RecoverySchedulerJob> {
  const data = await postJson(
    `/admin/recovery/scheduler/jobs/${jobId}/enable`,
    {},
  );
  return data as RecoverySchedulerJob;
}

export async function disableRecoverySchedulerJob(
  jobId: string,
): Promise<RecoverySchedulerJob> {
  const data = await postJson(
    `/admin/recovery/scheduler/jobs/${jobId}/disable`,
    {},
  );
  return data as RecoverySchedulerJob;
}

export async function runRecoverySchedulerJobNow(
  jobId: string,
): Promise<JsonValue> {
  return postJson(`/admin/recovery/scheduler/jobs/${jobId}/run`, {});
}

export async function listRecoverySchedulerRuns(params?: {
  limit?: number;
  offset?: number;
}): Promise<JsonValue> {
  return getJson("/admin/recovery/scheduler/runs", params);
}

/** STEP 8-5-4 — Recovery Conflict */
export interface RecoveryConflictItem {
  conflict_id: number;
  user_id: number | null;
  user_broker_account_id: number | null;
  masked_account: string | null;
  broker_code: string;
  conflict_type: string;
  external_order_id_masked: string | null;
  market_code: string | null;
  side_code: string | null;
  order_type_code: string | null;
  requested_quantity: string | null;
  executed_quantity: string | null;
  remaining_quantity: string | null;
  order_price: string | null;
  average_execution_price: string | null;
  paid_fee: string | null;
  external_status: string | null;
  detected_at: string | null;
  last_remote_checked_at: string | null;
  review_status: string;
  risk_level: string;
  account_paused: boolean;
  linked_internal_order_id?: number | null;
  resolution_type?: string | null;
  resolution_note?: string | null;
  remote_snapshot?: Record<string, unknown>;
  pause_reason?: string | null;
}

export async function listRecoveryConflicts(params?: {
  broker_code?: string;
  user_id?: number;
  user_broker_account_id?: number;
  review_status?: string;
  conflict_type?: string;
  market_code?: string;
  resolved?: boolean;
  limit?: number;
  offset?: number;
}): Promise<JsonValue> {
  return getJson("/admin/recovery/conflicts", params);
}

export async function getRecoveryConflict(
  conflictId: number,
): Promise<JsonValue> {
  return getJson(`/admin/recovery/conflicts/${conflictId}`);
}

export async function refreshRecoveryConflict(
  conflictId: number,
): Promise<JsonValue> {
  return postJson(`/admin/recovery/conflicts/${conflictId}/refresh`, {});
}

export async function approveImportRecoveryConflict(
  conflictId: number,
  body?: { note?: string | null },
): Promise<JsonValue> {
  return postJson(
    `/admin/recovery/conflicts/${conflictId}/approve-import`,
    body ?? {},
  );
}

export async function ignoreRecoveryConflict(
  conflictId: number,
  body: { note: string },
): Promise<JsonValue> {
  return postJson(`/admin/recovery/conflicts/${conflictId}/ignore`, body);
}

/** STEP 8-14 — History Preserve (Import/Ignore 아님) */
export async function preserveHistoryRecoveryConflict(
  conflictId: number,
  body: { note: string },
): Promise<JsonValue> {
  return postJson(
    `/admin/recovery/conflicts/${conflictId}/preserve-history`,
    body,
  );
}

export async function holdRecoveryConflict(
  conflictId: number,
  body: { note: string },
): Promise<JsonValue> {
  return postJson(`/admin/recovery/conflicts/${conflictId}/hold`, body);
}

export async function resumeRecoveryAccount(
  ubaId: number,
  body: { reason: string; correlation_id: string },
): Promise<JsonValue> {
  return postJson(`/admin/recovery/accounts/${ubaId}/resume`, body);
}

export async function clearRecoveryAccountConflicts(
  ubaId: number,
  body: { note: string },
): Promise<JsonValue> {
  // Deprecated — 서버에서 bulk_clear_disabled 반환
  return postJson(
    `/admin/recovery/accounts/${ubaId}/clear-conflicts`,
    body,
  );
}

export async function getRecoveryResumeCheck(
  ubaId: number,
): Promise<JsonValue> {
  return getJson(`/admin/recovery/accounts/${ubaId}/resume-check`);
}

export async function getRecoveryConflictSummary(
  ubaId: number,
): Promise<JsonValue> {
  return getJson(`/admin/recovery/accounts/${ubaId}/conflict-summary`);
}

export async function dryRunResolveRecoveryConflicts(
  ubaId: number,
  body: {
    conflict_ids: number[];
    resolution: string;
    reason: string;
    expected_status?: string | null;
  },
): Promise<JsonValue> {
  return postJson(
    `/admin/recovery/accounts/${ubaId}/conflicts/resolve-dry-run`,
    body,
  );
}

/** feature flag OFF 시 서버가 execute_disabled 반환 — UI는 dry-run only */
export async function resolveSelectedRecoveryConflicts(
  ubaId: number,
  body: {
    conflict_ids: number[];
    resolution: string;
    reason: string;
    expected_status?: string | null;
  },
): Promise<JsonValue> {
  return postJson(
    `/admin/recovery/accounts/${ubaId}/conflicts/resolve-selected`,
    body,
  );
}

export async function unlockRecoveryAccount(
  ubaId: number,
  body: { note: string },
): Promise<JsonValue> {
  return postJson(`/admin/recovery/accounts/${ubaId}/unlock`, body);
}

export async function getAdminBrokerAccountOpsStatus(
  ubaId: number,
): Promise<JsonValue> {
  return getJson(`/admin/broker-accounts/${ubaId}/ops-status`);
}

export async function activateKillSwitch(body?: {
  actor?: string;
  reason?: string;
}): Promise<JsonValue> {
  return postJson("/risk/kill-switch/activate", {
    actor: body?.actor ?? "admin-web",
    reason: body?.reason ?? "Activated from Admin Web",
  });
}

export async function deactivateKillSwitch(body?: {
  actor?: string;
  reason?: string;
}): Promise<JsonValue> {
  return postJson("/risk/kill-switch/deactivate", {
    actor: body?.actor ?? "admin-web",
    reason: body?.reason ?? "Deactivated from Admin Web",
  });
}

export async function getDailyLossStatus(): Promise<JsonValue> {
  return getJson("/risk/daily-loss/status");
}

export async function listRiskPolicies(): Promise<JsonValue> {
  return getJson("/risk-policies");
}

export async function getStrategyRuntimeStatus(): Promise<JsonValue> {
  return getJson("/strategy-runtime/status");
}

/** STEP 8-5-5 — Scope Runtime Admin */
export interface StrategyRuntimeItem {
  scope_key: string;
  status: string;
  pause_reason?: string | null;
  last_error?: string | null;
  user_id: number;
  account_kind: string;
  account_id: number;
  paper_account_id?: number | null;
  user_broker_account_id?: number | null;
  strategy_id: number;
  strategy_code?: string;
  strategy_version: string;
  market_type: string;
  broker_code: string;
  deployment_id?: number;
  last_started_at?: string | null;
  last_paused_at?: string | null;
}

export async function listAdminRuntimes(params?: {
  user_id?: number;
  strategy_id?: number;
}): Promise<JsonValue> {
  return getJson("/admin/runtimes", params);
}

export async function getAdminRuntime(
  scopeKey: string,
): Promise<JsonValue> {
  return getJson(`/admin/runtimes/${encodeURIComponent(scopeKey)}`);
}

export async function pauseAdminRuntime(
  scopeKey: string,
  body?: { reason?: string },
): Promise<JsonValue> {
  return postJson(
    `/admin/runtimes/${encodeURIComponent(scopeKey)}/pause`,
    body ?? { reason: "admin_pause" },
  );
}

export async function resumeAdminRuntime(
  scopeKey: string,
): Promise<JsonValue> {
  return postJson(
    `/admin/runtimes/${encodeURIComponent(scopeKey)}/resume`,
    {},
  );
}

export async function reloadAdminRuntime(
  scopeKey: string,
  force = true,
): Promise<JsonValue> {
  return postJson(
    `/admin/runtimes/${encodeURIComponent(scopeKey)}/reload`,
    {},
    { force },
  );
}

export async function stopAdminRuntime(
  scopeKey: string,
): Promise<JsonValue> {
  return postJson(
    `/admin/runtimes/${encodeURIComponent(scopeKey)}/stop`,
    {},
  );
}

export async function getActiveDeployments(params?: {
  market_code?: string;
  mode?: string;
}): Promise<JsonValue> {
  return getJson("/strategy-deployments/active", {
    market_code: params?.market_code ?? "KRX",
    mode: params?.mode ?? "PAPER",
  });
}

export async function deployStrategy(body: {
  strategy_code: string;
  strategy_performance_run_id: number;
  market_code: string;
  symbol?: string | null;
  mode?: string;
  parameter_payload?: Record<string, unknown>;
  requested_by: string;
}): Promise<JsonValue> {
  return postJson("/strategy-deployments", {
    mode: "PAPER",
    parameter_payload: {},
    ...body,
  });
}

export async function updateStrategyDeployment(
  deploymentId: number,
  body: {
    parameter_payload: Record<string, unknown>;
    requested_by: string;
  },
): Promise<JsonValue> {
  return postJson(`/strategy-deployments/${deploymentId}/update`, body);
}

export async function stopStrategyDeployment(
  deploymentId: number,
  body?: { actor?: string; reason?: string },
): Promise<JsonValue> {
  return postJson(`/strategy-deployments/${deploymentId}/stop`, {
    actor: body?.actor ?? "admin-web",
    reason: body?.reason ?? "Stopped from Admin Web",
  });
}

export async function reloadStrategyRuntime(params?: {
  market_code?: string;
  symbol?: string;
  force?: boolean;
}): Promise<JsonValue> {
  return postJson("/strategy-runtime/reload", undefined, {
    market_code: params?.market_code ?? "KRX",
    symbol: params?.symbol,
    force: params?.force ?? false,
  });
}

export async function createStrategyPerformanceRun(body: {
  strategy_code: string;
  run_type: string;
  market_code: string;
  symbol?: string | null;
  period_start_date: string;
  period_end_date: string;
  parameter_payload?: Record<string, unknown>;
}): Promise<JsonValue> {
  return postJson("/strategy-performance/runs", {
    parameter_payload: {},
    ...body,
  });
}

export async function completeStrategyPerformanceRun(
  runId: number,
  body?: Partial<{
    initial_capital: number;
    final_capital: number;
    total_return_rate: number;
    maximum_drawdown_rate: number;
    win_rate: number;
    total_trade_count: number;
    winning_trade_count: number;
    losing_trade_count: number;
    average_profit_amount: number;
    average_loss_amount: number;
    gross_profit_amount: number;
    gross_loss_amount: number;
    net_profit_amount: number;
  }>,
): Promise<JsonValue> {
  // Admin 등록용 기본 메트릭 (실백테스트가 아닌 배포 게이트 통과용)
  return postJson(`/strategy-performance/runs/${runId}/complete`, {
    initial_capital: 10_000_000,
    final_capital: 10_500_000,
    total_return_rate: 0.05,
    maximum_drawdown_rate: 0.02,
    win_rate: 0.55,
    total_trade_count: 10,
    winning_trade_count: 6,
    losing_trade_count: 4,
    average_profit_amount: 100000,
    average_loss_amount: 50000,
    gross_profit_amount: 600000,
    gross_loss_amount: 200000,
    net_profit_amount: 400000,
    result_payload: { source: "admin-web-register" },
    ...body,
  });
}

export async function getStrategyRanking(): Promise<JsonValue> {
  return getJson("/strategy-ranking");
}

export async function getStrategySelectorLatest(): Promise<JsonValue> {
  return getJson("/strategy-selector/latest");
}

export async function listBacktestRuns(params?: Params): Promise<JsonValue> {
  return getJson("/backtest-runs", params);
}

export async function getPortfolioSummary(accountId?: number): Promise<JsonValue> {
  const id = resolveAdminPaperAccountId(accountId);
  // STEP56: Paper 기반 (step32 /portfolio/summary 대체)
  const account = await getJson(`/paper-accounts/${id}`);
  const positions = await getJson(
    `/paper-accounts/${id}/positions`,
  );
  return { account, positions };
}

export async function listPositions(accountId?: number): Promise<JsonValue> {
  const id = resolveAdminPaperAccountId(accountId);
  // STEP56: Paper 포지션
  return getJson(`/paper-accounts/${id}/positions`);
}

export async function listOrders(params?: {
  account_id?: number;
  status_code?: string;
  broker_code?: string;
  exchange_code?: string;
  symbol?: string;
  limit?: number;
  offset?: number;
}): Promise<JsonValue> {
  return getJson("/orders", params);
}

export async function getOrder(orderId: number): Promise<JsonValue> {
  return getJson(`/orders/${orderId}`);
}

export async function submitOrder(body: {
  account_id: number;
  user_broker_account_id?: number;
  broker_code?: string;
  exchange_code: string;
  environment?: string;
  symbol: string;
  side: "BUY" | "SELL";
  order_type?: string;
  quantity?: number;
  order_amount?: number;
  price?: number;
  account_number?: string;
  strategy_code?: string;
  actor?: string;
}): Promise<JsonValue> {
  return postJson("/order-execution/submit", {
    broker_code: "KIWOOM",
    environment: "PAPER",
    order_type: "LIMIT",
    actor: "admin-web",
    ...body,
  });
}

export async function cancelTradingOrder(
  orderId: number,
  body?: { quantity?: number; actor?: string },
): Promise<JsonValue> {
  return postJson(`/orders/${orderId}/cancel`, {
    actor: body?.actor ?? "admin-web",
    quantity: body?.quantity,
  });
}

/** Preview retire for unsubmitted LIVE order (no state change) */
export async function previewRetireUnsubmittedOrder(
  orderId: number,
): Promise<JsonValue> {
  return getJson(`/admin/orders/${orderId}/retire-unsubmitted/preview`);
}

/** Retire unsubmitted LIVE order — no Upbit API call */
export async function retireUnsubmittedOrder(
  orderId: number,
  reason: string,
): Promise<JsonValue> {
  return postJson(`/admin/orders/${orderId}/retire-unsubmitted`, { reason });
}

/** Preview CONFIRMED_NOT_SUBMITTED resolution (AMBIGUOUS only) */
export async function previewResolveNotSubmittedOrder(
  orderId: number,
): Promise<JsonValue> {
  return getJson(
    `/admin/orders/${orderId}/resolve-not-submitted/preview`,
  );
}

/** Resolve AMBIGUOUS as not-submitted then retire — Upbit READ-ONLY lookup only */
export async function resolveNotSubmittedOrder(
  orderId: number,
  reason: string,
): Promise<JsonValue> {
  return postJson(`/admin/orders/${orderId}/resolve-not-submitted`, {
    reason,
  });
}

export async function listExecutions(params?: Params): Promise<JsonValue> {
  return getJson("/executions", params);
}

export async function listPaperOrders(params?: {
  exchange_code?: string;
  limit?: number;
}): Promise<JsonValue> {
  return getJson("/paper-orders", params);
}

export async function createPaperOrder(body: {
  exchange_code: string;
  symbol: string;
  side: "BUY" | "SELL";
  order_type: "LIMIT" | "MARKET";
  quantity: number;
  price?: number;
  account_id?: number;
  account_number?: string;
  auto_accept?: boolean;
}): Promise<JsonValue> {
  return postJson("/paper-orders", {
    auto_accept: true,
    ...body,
  });
}

export async function cancelPaperOrder(orderId: number): Promise<JsonValue> {
  return postJson(`/paper-orders/${orderId}/cancel`);
}

export async function getTopCandidates(
  exchangeCode: string,
  asOfDate: string,
  limit = 20,
): Promise<JsonValue> {
  return getJson(`/candidates/top/${exchangeCode}`, {
    as_of_date: asOfDate,
    limit,
  });
}

export async function listAiAnalysisRuns(params?: Params): Promise<JsonValue> {
  return getJson("/ai-analysis/runs", params);
}

export async function getLatestAiAnalysis(exchangeCode: string): Promise<JsonValue> {
  return getJson(`/ai-analysis/latest/${exchangeCode}`);
}

export async function getNews(
  exchangeCode: string,
  symbol: string,
): Promise<JsonValue> {
  return getJson(`/news/${exchangeCode}/${symbol}`);
}

export async function syncNews(body: {
  exchange_code: string;
  symbol: string;
  query: string;
  display?: number;
}): Promise<JsonValue> {
  return postJson("/news/sync", body);
}

export async function listNewsFailures(): Promise<JsonValue> {
  return getJson("/news/failures");
}

export async function syncDartDisclosures(body: {
  stock_code?: string;
  corp_code?: string;
  start_date: string;
  end_date: string;
  resume?: boolean;
}): Promise<JsonValue> {
  // 공시 페이지 수집 — 기본 15s 타임아웃 부족할 수 있음
  return postJson("/dart/sync", body, undefined, { timeout: 120_000 });
}

export async function syncDartCorps(body?: Params): Promise<JsonValue> {
  // corpCode.zip 다운로드 + 전체 법인 upsert — 수분 소요 가능
  return postJson("/dart/corps/sync", body ?? {}, undefined, {
    timeout: 180_000,
  });
}

export async function listDartDisclosures(params: {
  stock_code: string;
  start_date?: string;
  end_date?: string;
  limit?: number;
}): Promise<JsonValue> {
  return getJson("/dart/disclosures", params);
}

export async function listJobs(): Promise<JsonValue> {
  return getJson("/jobs");
}

export async function listJobHistory(params?: Params): Promise<JsonValue> {
  return getJson("/jobs/history", params);
}

export async function executeJob(
  jobName: string,
  payload?: Params,
): Promise<JsonValue> {
  // Ollama AI 잡은 수분 소요 — axios 기본 15s로는 부족
  return postJson(
    `/jobs/${encodeURIComponent(jobName)}/execute`,
    {
      payload: payload ?? {},
      trigger_type: "MANUAL",
    },
    undefined,
    { timeout: 180_000 },
  );
}

export async function runSchedulerNow(jobName: string): Promise<JsonValue> {
  return postJson(
    `/scheduler-admin/run-now/${encodeURIComponent(jobName)}`,
    {},
    undefined,
    { timeout: 180_000 },
  );
}

export async function getLatestPipeline(): Promise<JsonValue> {
  return getJson("/pipelines/latest");
}

export async function listDailyReports(params?: Params): Promise<JsonValue> {
  return getJson("/daily-reports", params);
}

export async function getNotificationStatus(): Promise<JsonValue> {
  return getJson("/notification/status");
}

export async function testNotification(body?: {
  title?: string;
  message?: string;
  detail?: Record<string, unknown>;
  event_type?: string;
}): Promise<JsonValue> {
  return postJson("/notification/test", {
    title: body?.title ?? "🧪 알림 전송 테스트",
    message:
      body?.message ??
      "이 메시지는 테스트용입니다. 실주문이 아닙니다.",
    detail: body?.detail ?? {},
    event_type: body?.event_type ?? "TEST_NOTIFICATION",
  });
}

export async function listNotificationTemplates(params?: {
  channel?: string;
  event_type?: string;
  locale?: string;
}): Promise<JsonValue> {
  return getJson("/admin/notification-templates", params);
}

export async function previewNotificationTemplate(body: {
  event_type?: string;
  title_template: string;
  body_template: string;
  sample_detail?: Record<string, unknown>;
}): Promise<JsonValue> {
  return postJson("/admin/notification-templates/preview", body);
}

export async function seedNotificationTemplates(): Promise<JsonValue> {
  return postJson("/admin/notification-templates/seed", {});
}

export async function upsertNotificationTemplate(body: {
  event_type: string;
  channel?: string;
  locale?: string;
  severity?: string;
  category?: string;
  audience?: string;
  title_template: string;
  body_template: string;
  short_body_template?: string;
  enabled?: boolean;
  version?: number;
}): Promise<JsonValue> {
  return postJson("/admin/notification-templates", body);
}

export async function setNotificationTemplateEnabled(
  templateId: number,
  enabled: boolean,
): Promise<JsonValue> {
  return patchJson(
    `/admin/notification-templates/${templateId}/enabled?enabled=${enabled}`,
    {},
  );
}

export async function listNotificationDeliveryLogs(params?: {
  limit?: number;
  event_type?: string;
}): Promise<JsonValue> {
  return getJson("/admin/notification-templates/delivery-logs", params);
}

export async function listAuditEvents(params?: {
  limit?: number;
  event_type?: string;
}): Promise<JsonValue> {
  return getJson("/audit/events", params);
}

export async function listDocs(): Promise<JsonValue> {
  return getJson("/docs");
}

export async function getDoc(slug: string): Promise<JsonValue> {
  return getJson(`/docs/${slug}`);
}

export async function getOpsDbStatus(): Promise<JsonValue> {
  return getJson("/ops/db/status");
}

export async function getOpsMigrationStatus(): Promise<JsonValue> {
  return getJson("/ops/db/migration-status");
}

export async function listOpsDbTables(schema = "trading"): Promise<JsonValue> {
  return getJson("/ops/db/tables", { schema });
}

export async function getOpsBackupStatus(): Promise<JsonValue> {
  return getJson("/ops/backup/status");
}

export async function getOllamaStatus(): Promise<JsonValue> {
  return getJson("/ollama/status");
}

export async function getUpbitMarkets(): Promise<JsonValue> {
  return getJson("/upbit/markets");
}

export async function syncUpbitInstruments(): Promise<JsonValue> {
  return postJson("/upbit/instruments/sync");
}

export async function getUpbitAccountStatus(): Promise<JsonValue> {
  return getJson("/broker/upbit/account/status");
}

export async function testUpbitAccountConnection(): Promise<JsonValue> {
  return postJson("/broker/upbit/account/connection-test");
}

export async function syncUpbitAccount(
  userBrokerAccountId: number,
): Promise<JsonValue> {
  return postJson("/broker/upbit/account/sync", {}, {
    user_broker_account_id: userBrokerAccountId,
  });
}

export async function getUpbitAccountSnapshot(
  userBrokerAccountId: number,
): Promise<JsonValue> {
  return getJson("/broker/upbit/account/snapshot", {
    user_broker_account_id: userBrokerAccountId,
  });
}

export async function reconcileUpbitOrders(): Promise<JsonValue> {
  return postJson("/broker/upbit/account/reconcile-orders");
}

/** STEP 8-5-8 — Upbit Rate Limit 상태 */
export async function getUpbitRateLimits(params?: {
  limit?: number;
}): Promise<JsonValue> {
  return getJson("/admin/upbit/rate-limits", params);
}

export async function getUpbitRateLimitsForAccount(
  ubaId: number,
): Promise<JsonValue> {
  return getJson(`/admin/upbit/rate-limits/${ubaId}`);
}

export async function recheckUpbitRateLimits(
  ubaId: number,
): Promise<JsonValue> {
  return postJson(`/admin/upbit/rate-limits/${ubaId}/recheck`);
}

/** UPBIT Opportunity Scanner v0 — Alert-only */
export async function getUpbitOpportunityScannerStatus(): Promise<JsonValue> {
  return getJson("/admin/upbit/opportunity-scanner/status");
}

export async function runUpbitOpportunityScanner(body?: {
  notify?: boolean;
  force_ai?: boolean;
}): Promise<JsonValue> {
  return postJson("/admin/upbit/opportunity-scanner/run", {
    notify: body?.notify ?? true,
    force_ai: body?.force_ai ?? false,
  });
}

export async function listUpbitOpportunityShadows(params?: {
  status?: string;
  limit?: number;
}): Promise<JsonValue> {
  return getJson("/admin/upbit/opportunity-scanner/shadows", params);
}

export async function evaluateUpbitOpportunityShadows(): Promise<JsonValue> {
  return postJson("/admin/upbit/opportunity-scanner/shadows/evaluate", {});
}

/** 시장·뉴스·LLM 컨텍스트 research (REAL 미적용) */
export async function getUpbitMarketContextResearch(): Promise<JsonValue> {
  return getJson("/admin/upbit/opportunity-scanner/market-context/research");
}

export async function collectUpbitMarketContextOnce(): Promise<JsonValue> {
  return postJson("/admin/upbit/opportunity-scanner/market-context/collect-once", {});
}

/** STEP N2 — UPBIT News/Notice Collector (COLLECT only) */
export async function getUpbitNewsCollectorStatus(): Promise<JsonValue> {
  return getJson("/admin/upbit/news-collector/status");
}

export async function getUpbitNewsCollectorRecent(params?: {
  limit?: number;
  source?: string;
}): Promise<JsonValue> {
  return getJson("/admin/upbit/news-collector/recent", params);
}

export async function runUpbitNewsCollector(body?: {
  include_notice?: boolean;
  include_crypto?: boolean;
}): Promise<JsonValue> {
  return postJson("/admin/upbit/news-collector/run", {
    include_notice: body?.include_notice ?? true,
    include_crypto: body?.include_crypto ?? true,
  });
}

/** STEP N3 — Symbol Mapping (AI/Scanner 미연동) */
export async function getUpbitNewsSymbolMappingStatus(): Promise<JsonValue> {
  return getJson("/admin/upbit/news-collector/symbol-mapping/status");
}

export async function runUpbitNewsSymbolMapping(body?: {
  include_notice?: boolean;
  include_crypto?: boolean;
  limit?: number | null;
}): Promise<JsonValue> {
  return postJson("/admin/upbit/news-collector/symbol-mapping/run", {
    include_notice: body?.include_notice ?? true,
    include_crypto: body?.include_crypto ?? true,
    limit: body?.limit ?? null,
  });
}

/** STEP N4 — AI News Analysis (INFORMATIONAL ONLY) */
export async function getUpbitNewsAnalysisStatus(): Promise<JsonValue> {
  return getJson("/admin/upbit/news-analysis/status");
}

export async function getUpbitNewsAnalysisRecent(params?: {
  limit?: number;
}): Promise<JsonValue> {
  return getJson("/admin/upbit/news-analysis/recent", params);
}

export async function runUpbitNewsAnalysis(body?: {
  limit?: number;
  article_ids?: number[] | null;
  force?: boolean;
}): Promise<JsonValue> {
  return postJson("/admin/upbit/news-analysis/run", {
    limit: body?.limit ?? 5,
    article_ids: body?.article_ids ?? null,
    force: body?.force ?? false,
  });
}

/** STEP N5 — News Signal Standardization (INFORMATIONAL ONLY, no LLM) */
export async function getUpbitNewsSignalsStatus(): Promise<JsonValue> {
  return getJson("/admin/upbit/news-signals/status");
}

export async function getUpbitNewsSignalsRecent(params?: {
  limit?: number;
}): Promise<JsonValue> {
  return getJson("/admin/upbit/news-signals/recent", params);
}

export async function getUpbitNewsSignalsStats(): Promise<JsonValue> {
  return getJson("/admin/upbit/news-signals/stats");
}

export async function runUpbitNewsSignals(body?: {
  limit?: number;
  analysis_ids?: number[] | null;
  force?: boolean;
}): Promise<JsonValue> {
  return postJson("/admin/upbit/news-signals/run", {
    limit: body?.limit ?? 50,
    analysis_ids: body?.analysis_ids ?? null,
    force: body?.force ?? false,
  });
}

/** STEP N6 — News Combined Shadow Experiment (CONTROL 비수정) */
export async function getUpbitCombinedShadowStatus(): Promise<JsonValue> {
  return getJson("/admin/upbit/combined-shadow/status");
}

export async function getUpbitCombinedShadowRecent(params?: {
  limit?: number;
}): Promise<JsonValue> {
  return getJson("/admin/upbit/combined-shadow/recent", params);
}

export async function getUpbitCombinedShadowStats(): Promise<JsonValue> {
  return getJson("/admin/upbit/combined-shadow/stats");
}

export async function getUpbitCombinedShadowDiagnostics(): Promise<JsonValue> {
  return getJson("/admin/upbit/combined-shadow/diagnostics");
}

export async function runUpbitCombinedShadow(body?: {
  limit_runs?: number;
  scanner_run_ids?: string[] | null;
  force?: boolean;
}): Promise<JsonValue> {
  return postJson("/admin/upbit/combined-shadow/run", {
    limit_runs: body?.limit_runs ?? 5,
    scanner_run_ids: body?.scanner_run_ids ?? null,
    force: body?.force ?? false,
  });
}

export async function evaluateUpbitCombinedShadow(body?: {
  limit?: number;
}): Promise<JsonValue> {
  return postJson("/admin/upbit/combined-shadow/evaluate", {
    limit: body?.limit ?? 50,
  });
}

/** STEP 8-5-12 — Ambiguous Orders */
export async function listUpbitAmbiguousOrders(params?: {
  limit?: number;
}): Promise<JsonValue> {
  return getJson("/admin/upbit/ambiguous-orders", params);
}

export async function getUpbitAmbiguousHealth(): Promise<JsonValue> {
  return getJson("/admin/upbit/ambiguous-orders/health");
}

export async function lookupUpbitAmbiguousOrder(
  orderId: number,
): Promise<JsonValue> {
  return postJson(`/admin/upbit/ambiguous-orders/${orderId}/lookup`, {});
}

export async function markUpbitAmbiguousManualReview(
  orderId: number,
  reason: string,
): Promise<JsonValue> {
  return postJson(
    `/admin/upbit/ambiguous-orders/${orderId}/mark-manual-review`,
    { reason },
  );
}

export async function approveUpbitAmbiguousResubmit(
  orderId: number,
  reason: string,
): Promise<JsonValue> {
  return postJson(
    `/admin/upbit/ambiguous-orders/${orderId}/approve-resubmit`,
    { reason },
  );
}

export async function rejectUpbitAmbiguousResubmit(
  orderId: number,
  reason: string,
): Promise<JsonValue> {
  return postJson(
    `/admin/upbit/ambiguous-orders/${orderId}/reject-resubmit`,
    { reason },
  );
}

/** STEP 8-5-14 — Ambiguous Resolver Scheduler */
export async function retryUpbitAmbiguousLookup(
  orderId: number,
): Promise<JsonValue> {
  return postJson(`/admin/upbit/ambiguous-orders/${orderId}/retry-lookup`, {});
}

export async function releaseUpbitAmbiguousStaleClaim(
  orderId: number,
): Promise<JsonValue> {
  return postJson(
    `/admin/upbit/ambiguous-orders/${orderId}/release-stale-claim`,
    {},
  );
}

export async function getUpbitAmbiguousResolverStatus(): Promise<JsonValue> {
  return getJson("/admin/upbit/ambiguous-resolver/status");
}

export async function listUpbitAmbiguousResolverRuns(params?: {
  limit?: number;
  offset?: number;
}): Promise<JsonValue> {
  return getJson("/admin/upbit/ambiguous-resolver/runs", params);
}

export async function getUpbitAmbiguousResolverRun(
  runId: number,
): Promise<JsonValue> {
  return getJson(`/admin/upbit/ambiguous-resolver/runs/${runId}`);
}

export async function runUpbitAmbiguousResolverNow(): Promise<JsonValue> {
  return postJson("/admin/upbit/ambiguous-resolver/run-now", {});
}

export async function getMarketQualityDashboard(): Promise<JsonValue> {
  return getJson("/market-quality/dashboard");
}

export async function getOrderOutbox(): Promise<JsonValue> {
  return getJson("/order-outbox");
}

export async function getLiveTransitionHistory(): Promise<JsonValue> {
  return getJson("/broker/live-transition/history");
}

export async function getLiveTransitionActive(): Promise<JsonValue> {
  return getJson("/broker/live-transition/active");
}

/** ACCOUNT scope Live Transition — BROKER scope는 wrapper에서 받지 않는다. */
export type LiveTransitionAccountBody = {
  max_order_amount: number;
  max_daily_loss: number;
  paper_validation_approved?: boolean;
  scope: "ACCOUNT";
  broker_code: string;
  user_broker_account_id: number;
};

export async function validateLiveTransition(
  body: LiveTransitionAccountBody,
): Promise<JsonValue> {
  return postJson("/broker/live-transition/validate", body);
}

export async function requestLiveTransition(
  body: LiveTransitionAccountBody & { requested_by: string },
): Promise<JsonValue> {
  return postJson("/broker/live-transition/request", body);
}

export async function approveLiveTransition(
  transitionId: number,
  body: {
    approved_by: string;
    approval_phrase: string;
    reason?: string | null;
    ttl_hours?: number;
    scope: "ACCOUNT";
    broker_code: string;
    user_broker_account_id: number;
  },
): Promise<JsonValue> {
  return postJson(`/broker/live-transition/${transitionId}/approve`, body);
}

export interface MemberRecord {
  id: string;
  username: string;
  display_name?: string | null;
  email?: string | null;
  roles: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
  password_changed_at: string;
  deleted_at?: string | null;
  user_status?: string;
  password_change_required?: boolean;
  failed_login_count?: number;
  locked_until?: string | null;
  last_login_at?: string | null;
  last_login_ip?: string | null;
  onboarding_completed?: boolean;
}

export interface MemberListResult {
  items: MemberRecord[];
  total: number;
  limit: number;
  offset: number;
}

export async function listMembers(params?: {
  q?: string;
  is_active?: boolean;
  role?: string;
  include_deleted?: boolean;
  sort_by?: string;
  sort_order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}): Promise<MemberListResult> {
  const { data } = await apiClient.get<MemberListResult>("/users", { params });
  return data;
}

export async function getMember(
  userId: string,
  includeDeleted = false,
): Promise<MemberRecord> {
  const { data } = await apiClient.get<MemberRecord>(`/users/${userId}`, {
    params: { include_deleted: includeDeleted },
  });
  return data;
}

export async function createMember(body: {
  username: string;
  password: string;
  display_name?: string;
  roles: string[];
  is_active?: boolean;
}): Promise<MemberRecord> {
  const { data } = await apiClient.post<MemberRecord>("/users", body);
  return data;
}

export async function updateMember(
  userId: string,
  body: {
    display_name?: string | null;
    roles?: string[];
    is_active?: boolean;
  },
): Promise<MemberRecord> {
  const { data } = await apiClient.put<MemberRecord>(`/users/${userId}`, body);
  return data;
}

export async function softDeleteMember(userId: string): Promise<MemberRecord> {
  const { data } = await apiClient.delete<MemberRecord>(`/users/${userId}`);
  return data;
}

export async function activateMember(userId: string): Promise<MemberRecord> {
  const { data } = await apiClient.post<MemberRecord>(
    `/users/${userId}/activate`,
  );
  return data;
}

export async function deactivateMember(userId: string): Promise<MemberRecord> {
  const { data } = await apiClient.post<MemberRecord>(
    `/users/${userId}/deactivate`,
  );
  return data;
}

export async function resetMemberPassword(
  userId: string,
  newPassword?: string,
): Promise<{ user: MemberRecord; temporary_password: string }> {
  const { data } = await apiClient.post<{
    user: MemberRecord;
    temporary_password: string;
  }>(`/users/${userId}/reset-password`, {
    new_password: newPassword ?? null,
  });
  return data;
}

export async function unlockMember(userId: string): Promise<MemberRecord> {
  const { data } = await apiClient.post<MemberRecord>(
    `/users/${userId}/unlock`,
  );
  return data;
}

export async function forceLogoutMember(
  userId: string,
): Promise<{ user_id: number; revoked_sessions: number }> {
  const { data } = await apiClient.post<{
    user_id: number;
    revoked_sessions: number;
  }>(`/users/${userId}/force-logout`);
  return data;
}

export async function listMemberSessions(
  userId: string,
): Promise<{ items: Record<string, unknown>[]; total: number }> {
  const { data } = await apiClient.get<{
    items: Record<string, unknown>[];
    total: number;
  }>(`/users/${userId}/sessions`);
  return data;
}

export async function listMemberAccounts(
  userId: string,
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.get<Record<string, unknown>>(
    `/users/${userId}/accounts`,
  );
  return data;
}

export interface RoleRecord {
  id: number;
  code: string;
  name: string;
  description?: string | null;
  is_system: boolean;
  permissions: string[];
}

export interface PermissionRecord {
  id: number;
  code: string;
  name: string;
  category: string;
  description?: string | null;
}

export async function listRoles(): Promise<RoleRecord[]> {
  const { data } = await apiClient.get<RoleRecord[]>("/roles");
  return data;
}

export async function listPermissions(
  category?: string,
): Promise<PermissionRecord[]> {
  const { data } = await apiClient.get<PermissionRecord[]>("/roles/permissions", {
    params: category ? { category } : undefined,
  });
  return data;
}

export async function getRole(roleId: number): Promise<RoleRecord> {
  const { data } = await apiClient.get<RoleRecord>(`/roles/${roleId}`);
  return data;
}

export async function updateRolePermissions(
  roleId: number,
  permissions: string[],
): Promise<RoleRecord> {
  const { data } = await apiClient.put<RoleRecord>(
    `/roles/${roleId}/permissions`,
    { permissions },
  );
  return data;
}

export async function updateUserRoles(
  userId: string,
  roles: string[],
): Promise<{ user_id: number; roles: string[] }> {
  const { data } = await apiClient.put<{ user_id: number; roles: string[] }>(
    `/roles/users/${userId}`,
    { roles },
  );
  return data;
}

export interface SettingItem {
  key: string;
  category: string;
  value: string;
  typed_value?: unknown;
  value_type: "string" | "int" | "float" | "bool";
  is_secret: boolean;
  description?: string | null;
  updated_by?: string | null;
  updated_at?: string | null;
  version: number;
  min_value?: number | null;
  max_value?: number | null;
  allowed_values?: string[] | null;
}

export interface SettingCategory {
  code: string;
  name: string;
  count: number;
}

export interface SettingHistoryItem {
  history_id: number;
  key: string;
  old_value?: string | null;
  new_value?: string | null;
  actor: string;
  change_reason?: string | null;
  created_at: string;
}

export async function listSettingCategories(): Promise<SettingCategory[]> {
  const { data } = await apiClient.get<SettingCategory[]>(
    "/settings/categories",
  );
  return data;
}

export async function listSettings(
  category?: string,
): Promise<SettingItem[]> {
  const { data } = await apiClient.get<SettingItem[]>("/settings", {
    params: category ? { category } : undefined,
  });
  return data;
}

export async function updateSettings(
  items: Array<{ key: string; value: unknown }>,
  changeReason?: string,
): Promise<SettingItem[]> {
  const { data } = await apiClient.put<SettingItem[]>("/settings", {
    items,
    change_reason: changeReason ?? null,
  });
  return data;
}

export async function listSettingHistory(params?: {
  setting_key?: string;
  limit?: number;
}): Promise<SettingHistoryItem[]> {
  const { data } = await apiClient.get<SettingHistoryItem[]>(
    "/settings/history",
    { params },
  );
  return data;
}

export async function listOllamaModels(): Promise<{
  base_url: string;
  models: Array<{ name?: string; size?: number; modified_at?: string }>;
}> {
  const { data } = await apiClient.get<{
    base_url: string;
    models: Array<{ name?: string; size?: number; modified_at?: string }>;
  }>("/ollama/models");
  return data;
}

/** STEP 8-5-15 — 영속 Market Session Job (DB Claim 기반 Dispatcher/Reconcile) */
export interface AdminMarketSessionJob {
  job_id: number;
  exchange_code: string;
  market_date: string;
  calendar_revision: number;
  job_type: string;
  job_key: string;
  scheduled_for: string;
  status_code: string;
  attempt_count: number;
  max_attempts: number;
  next_retry_at: string | null;
  claimed_by: string | null;
  claimed_at: string | null;
  claim_expires_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  last_error_code: string | null;
  last_error_summary: string | null;
  superseded_by_job_id: number | null;
  depends_on_job_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface AdminMarketSessionJobHealth {
  counts_by_status: Record<string, number>;
  due_count: number;
  running_count: number;
  failed_count: number;
  superseded_count: number;
  average_lag_seconds: number | null;
  dispatcher?: { instance_id: string };
  scheduler?: {
    running: boolean;
    dispatch_job_registered: boolean;
    reconcile_job_registered: boolean;
    dispatch_next_run_at: string | null;
    reconcile_next_run_at: string | null;
  } | null;
}

export async function listAdminMarketSessionJobs(params?: {
  exchange_code?: string;
  market_date?: string;
  status_code?: string;
  job_type?: string;
  limit?: number;
  offset?: number;
}): Promise<{ items: AdminMarketSessionJob[]; count: number }> {
  const data = await getJson("/admin/market-session-jobs", params);
  const row = data as { items?: AdminMarketSessionJob[]; count?: number };
  return {
    items: Array.isArray(row.items) ? row.items : [],
    count: row.count ?? 0,
  };
}

export async function getAdminMarketSessionJobHealth(): Promise<AdminMarketSessionJobHealth> {
  const data = await getJson("/admin/market-session-jobs/health");
  return data as AdminMarketSessionJobHealth;
}

export async function getAdminMarketSessionJob(
  jobId: number,
): Promise<AdminMarketSessionJob> {
  const data = await getJson(`/admin/market-session-jobs/${jobId}`);
  return data as AdminMarketSessionJob;
}

export async function getAdminMarketSessionJobRuns(
  jobId: number,
): Promise<{ items: Record<string, unknown>[]; count: number }> {
  const data = await getJson(`/admin/market-session-jobs/${jobId}/runs`);
  const row = data as { items?: Record<string, unknown>[]; count?: number };
  return {
    items: Array.isArray(row.items) ? row.items : [],
    count: row.count ?? 0,
  };
}

export async function reconcileAdminMarketSessionJobs(payload: {
  reason: string;
  exchange_code?: string;
  days_ahead?: number;
}): Promise<JsonValue> {
  return postJson("/admin/market-session-jobs/reconcile", payload);
}

export async function runNowAdminMarketSessionJob(
  jobId: number,
  reason: string,
): Promise<JsonValue> {
  return postJson(`/admin/market-session-jobs/${jobId}/run-now`, { reason });
}

export async function retryAdminMarketSessionJob(
  jobId: number,
  reason: string,
): Promise<JsonValue> {
  return postJson(`/admin/market-session-jobs/${jobId}/retry`, { reason });
}

export async function cancelAdminMarketSessionJob(
  jobId: number,
  reason: string,
): Promise<JsonValue> {
  return postJson(`/admin/market-session-jobs/${jobId}/cancel`, { reason });
}

export async function releaseStaleClaimAdminMarketSessionJob(
  jobId: number,
  reason: string,
): Promise<JsonValue> {
  return postJson(
    `/admin/market-session-jobs/${jobId}/release-stale-claim`,
    { reason },
  );
}

/** STEP 8-5-16 — Account Daily Settlement */
export interface AdminSettlement {
  settlement_id: number;
  user_broker_account_id: number | null;
  paper_account_id: number | null;
  broker_code: string;
  market_date: string;
  calendar_revision: number | null;
  settlement_type: string;
  status_code: string;
  started_at: string | null;
  completed_at: string | null;
  open_order_count: number;
  unresolved_order_count: number;
  position_mismatch_count: number;
  cash_mismatch_amount: string;
  realized_pnl: string;
  unrealized_pnl: string;
  fees: string;
  taxes: string;
  net_pnl: string;
  opening_equity: string | null;
  closing_equity: string | null;
  internal_equity: string | null;
  external_equity: string | null;
  equity_difference: string | null;
  result_code: string | null;
  result_summary: string | null;
  external_snapshot_meta: Record<string, unknown>;
}

export interface AdminSettlementHealth {
  market_date: string;
  total: number;
  by_status: Record<string, number>;
  position_mismatch_total: number;
  cash_mismatch_count: number;
  unresolved_ambiguous_total: number;
  manual_review: number;
  failed: number;
  warnings: number;
  succeeded: number;
  oldest_incomplete: Record<string, unknown> | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  enabled: boolean;
}

export interface AdminSettlementIssue {
  issue_id: number;
  settlement_id: number;
  issue_type: string;
  severity: string;
  symbol: string | null;
  local_value: string | null;
  external_value: string | null;
  difference: string | null;
  tolerance: string | null;
  description: string | null;
  resolved: boolean;
  resolved_by: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
}

export async function listAdminSettlements(params?: {
  market_date?: string;
  status_code?: string;
  limit?: number;
}): Promise<{ items: AdminSettlement[]; count: number }> {
  const data = await getJson("/admin/settlements", params);
  const row = data as { items?: AdminSettlement[]; count?: number };
  return {
    items: Array.isArray(row.items) ? row.items : [],
    count: row.count ?? 0,
  };
}

export async function getAdminSettlementHealth(): Promise<AdminSettlementHealth> {
  const data = await getJson("/admin/settlements/health");
  return data as AdminSettlementHealth;
}

export async function getAdminSettlement(
  settlementId: number,
): Promise<AdminSettlement> {
  const data = await getJson(`/admin/settlements/${settlementId}`);
  return data as AdminSettlement;
}

export async function listAdminSettlementIssues(
  settlementId: number,
): Promise<{ items: AdminSettlementIssue[]; count: number }> {
  const data = await getJson(`/admin/settlements/${settlementId}/issues`);
  const row = data as { items?: AdminSettlementIssue[]; count?: number };
  return {
    items: Array.isArray(row.items) ? row.items : [],
    count: row.count ?? 0,
  };
}

export async function retryAdminSettlement(
  settlementId: number,
  reason: string,
): Promise<JsonValue> {
  return postJson(`/admin/settlements/${settlementId}/retry`, { reason });
}

export async function reconcileAdminSettlement(
  settlementId: number,
  reason: string,
): Promise<JsonValue> {
  return postJson(`/admin/settlements/${settlementId}/reconcile`, { reason });
}

export async function resolveAdminSettlementIssue(
  settlementId: number,
  issueId: number,
  payload: { reason: string; note: string },
): Promise<JsonValue> {
  return postJson(
    `/admin/settlements/${settlementId}/issues/${issueId}/resolve`,
    payload,
  );
}

export async function runAdminUbaSettlement(
  ubaId: number,
  payload: { reason: string; market_date: string },
): Promise<JsonValue> {
  return postJson(
    `/admin/settlements/accounts/${ubaId}/settlements/run`,
    payload,
  );
}

export async function runAdminPaperSettlement(
  paperId: number,
  payload: { reason: string; market_date: string },
): Promise<JsonValue> {
  return postJson(
    `/admin/settlements/paper-accounts/${paperId}/settlements/run`,
    payload,
  );
}

/** STEP 8-5-17 — Broker Snapshot Binding */
export interface AdminBrokerSnapshot {
  broker_account_snapshot_id: number;
  user_broker_account_id: number | null;
  paper_account_id: number | null;
  broker_code: string;
  masked_account_number: string | null;
  snapshot_status: string;
  snapshot_generation: number;
  snapshot_version: number;
  snapshot_hash: string | null;
  snapshot_time: string | null;
  synchronized_at: string | null;
  age_seconds: number | null;
  deposit_amount: string;
  available_order_amount: string;
  total_evaluation_amount: string;
}

export async function listAdminBrokerSnapshots(params?: {
  status_code?: string;
  broker_code?: string;
  limit?: number;
}): Promise<{ items: AdminBrokerSnapshot[]; count: number }> {
  const data = await getJson("/admin/broker-snapshots", params);
  const row = data as { items?: AdminBrokerSnapshot[]; count?: number };
  return {
    items: Array.isArray(row.items) ? row.items : [],
    count: row.count ?? 0,
  };
}

export async function getAdminBrokerSnapshotHealth(): Promise<
  Record<string, unknown>
> {
  return (await getJson("/admin/broker-snapshots/health")) as Record<
    string,
    unknown
  >;
}

export async function verifyAdminBrokerSnapshot(
  snapshotId: number,
  reason: string,
): Promise<JsonValue> {
  return postJson(`/admin/broker-snapshots/${snapshotId}/verify`, { reason });
}

export async function refreshAdminUbaSnapshot(
  ubaId: number,
  reason: string,
): Promise<JsonValue> {
  return postJson(
    `/admin/user-broker-accounts/${ubaId}/refresh-snapshot`,
    { reason },
  );
}

export async function releaseAdminUbaStaleSnapshot(
  ubaId: number,
  reason: string,
): Promise<JsonValue> {
  return postJson(
    `/admin/user-broker-accounts/${ubaId}/release-stale`,
    { reason },
  );
}

export async function listAdminOrphanBrokerSnapshots(params?: {
  limit?: number;
}): Promise<{ items: AdminBrokerSnapshot[]; count: number }> {
  const data = await getJson("/admin/broker-snapshots/orphans", params);
  const row = data as { items?: AdminBrokerSnapshot[]; count?: number };
  return {
    items: Array.isArray(row.items) ? row.items : [],
    count: row.count ?? 0,
  };
}

export async function rebindAdminOrphanBrokerSnapshot(
  snapshotId: number,
  payload: { target_user_broker_account_id: number; reason: string },
): Promise<JsonValue> {
  return postJson(`/admin/broker-snapshots/${snapshotId}/rebind`, payload);
}

export async function retireAdminOrphanBrokerSnapshot(
  snapshotId: number,
  reason: string,
): Promise<JsonValue> {
  return postJson(`/admin/broker-snapshots/${snapshotId}/retire`, {
    reason,
  });
}

export function todayKst(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Seoul" });
}

export function openApiDocsUrl(): string {
  // apiClient baseURL = {API_BASE_URL}{API_PREFIX}
  const base = (apiClient.defaults.baseURL ?? "").replace(/\/api\/v1\/?$/, "");
  if (base) return `${base}/docs`;
  return "/docs";
}

// --- Admin Indicator Parameters ---

export interface IndicatorParameterRecord {
  indicator_parameter_config_id: number;
  indicator_code: string;
  market_type: string;
  exchange_code?: string | null;
  timeframe: string;
  parameter_payload: Record<string, unknown>;
  version: number;
  is_active: boolean;
  effective_from?: string | null;
  created_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface IndicatorParameterListResponse {
  items: IndicatorParameterRecord[];
  system_defaults?: Record<string, unknown>;
  resolved_engine_params?: Record<string, unknown>;
}

export async function listIndicatorParameters(params?: {
  indicator_code?: string;
  active_only?: boolean;
}): Promise<IndicatorParameterListResponse> {
  const { data } = await apiClient.get<IndicatorParameterListResponse>(
    "/admin/indicator-parameters",
    { params },
  );
  return data;
}

export async function createIndicatorParameter(body: {
  indicator_code: string;
  market_type?: string;
  exchange_code?: string | null;
  timeframe?: string;
  parameter_payload: Record<string, unknown>;
  activate?: boolean;
}): Promise<IndicatorParameterRecord> {
  const { data } = await apiClient.post<IndicatorParameterRecord>(
    "/admin/indicator-parameters",
    body,
  );
  return data;
}

export async function updateIndicatorParameter(
  configId: number,
  body: {
    parameter_payload?: Record<string, unknown>;
    is_active?: boolean;
  },
): Promise<IndicatorParameterRecord> {
  const { data } = await apiClient.put<IndicatorParameterRecord>(
    `/admin/indicator-parameters/${configId}`,
    body,
  );
  return data;
}

export async function previewIndicatorParameter(body: {
  indicator_code: string;
  market_type?: string;
  exchange_code?: string | null;
  timeframe?: string;
  parameter_payload: Record<string, unknown>;
}): Promise<JsonValue> {
  return postJson("/admin/indicator-parameters/preview", body);
}

export async function restoreIndicatorParameterDefaults(body?: {
  indicator_code?: string | null;
  market_type?: string | null;
  timeframe?: string | null;
}): Promise<JsonValue> {
  return postJson("/admin/indicator-parameters/restore-defaults", body ?? {});
}

// --- Admin Member Cleanup ---

export interface MemberCleanupCandidate {
  user_id: number;
  username: string;
  email?: string | null;
  display_name?: string | null;
  is_active: boolean;
  deleted_at?: string | null;
  roles?: string[];
  protected: boolean;
  is_self: boolean;
  ref_counts: Record<string, number>;
  can_deactivate: boolean;
  can_soft_delete: boolean;
  hard_delete_allowed: boolean;
  recommended_action: string;
}

export interface MemberCleanupCandidatesResponse {
  protected_usernames: string[];
  policy: Record<string, unknown>;
  items: MemberCleanupCandidate[];
  candidate_count: number;
}

export async function listMemberCleanupCandidates(params?: {
  include_deleted?: boolean;
}): Promise<MemberCleanupCandidatesResponse> {
  const { data } = await apiClient.get<MemberCleanupCandidatesResponse>(
    "/admin/member-cleanup/candidates",
    { params },
  );
  return data;
}

export async function previewMemberCleanup(body: {
  user_ids: number[];
  mode?: "deactivate" | "soft_delete";
  confirm_phrase: string;
  backup_confirmed?: boolean;
}): Promise<JsonValue> {
  return postJson("/admin/member-cleanup/preview", body);
}

export async function executeMemberCleanup(body: {
  user_ids: number[];
  mode?: "deactivate" | "soft_delete";
  confirm_phrase: string;
  backup_confirmed: boolean;
}): Promise<JsonValue> {
  return postJson("/admin/member-cleanup/execute", body);
}
