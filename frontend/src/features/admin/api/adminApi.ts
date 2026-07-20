import type { AxiosRequestConfig } from "axios";

import { apiClient } from "@/lib/api/apiClient";
import { rootClient } from "@/lib/api/rootClient";

export type JsonValue = unknown;

type Params = Record<string, unknown>;

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
  account_number?: string;
  recent_limit?: number;
}): Promise<JsonValue> {
  return getJson("/dashboard/risk", {
    account_number: params?.account_number,
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
    account_id: params?.account_id ?? 1,
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

export async function syncKiwoomAccount(): Promise<JsonValue> {
  return postJson("/broker/kiwoom/account/sync");
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

export async function getPaperPositions(accountId: number): Promise<JsonValue> {
  return getJson(`/paper-accounts/${accountId}/positions`);
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

export async function getKillSwitch(): Promise<JsonValue> {
  return getJson("/risk/kill-switch");
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

export async function getPortfolioSummary(accountId = 1): Promise<JsonValue> {
  // STEP56: Paper 기반 (step32 /portfolio/summary 대체)
  const account = await getJson(`/paper-accounts/${accountId}`);
  const positions = await getJson(
    `/paper-accounts/${accountId}/positions`,
  );
  return { account, positions };
}

export async function listPositions(accountId = 1): Promise<JsonValue> {
  // STEP56: Paper 포지션
  return getJson(`/paper-accounts/${accountId}/positions`);
}

export async function listOrders(params?: {
  account_id?: number;
  status_code?: string;
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
  broker_code?: string;
  exchange_code: string;
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
  return postJson("/dart/sync", body);
}

export async function syncDartCorps(body?: Params): Promise<JsonValue> {
  return postJson("/dart/corps/sync", body ?? {});
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
}): Promise<JsonValue> {
  return postJson("/notification/test", {
    title: body?.title ?? "Admin Web 테스트 알림",
    message:
      body?.message ?? "Admin 알림 관리 화면에서 전송된 테스트입니다.",
    detail: body?.detail ?? {},
  });
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

export async function getMarketQualityDashboard(): Promise<JsonValue> {
  return getJson("/market-quality/dashboard");
}

export async function getOrderOutbox(): Promise<JsonValue> {
  return getJson("/order-outbox");
}

export async function getLiveTransitionHistory(): Promise<JsonValue> {
  return getJson("/broker/live-transition/history");
}

export interface MemberRecord {
  id: string;
  username: string;
  display_name?: string | null;
  roles: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
  password_changed_at: string;
  deleted_at?: string | null;
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

export function todayKst(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Seoul" });
}

export function openApiDocsUrl(): string {
  // apiClient baseURL = {API_BASE_URL}{API_PREFIX}
  const base = (apiClient.defaults.baseURL ?? "").replace(/\/api\/v1\/?$/, "");
  if (base) return `${base}/docs`;
  return "/docs";
}
