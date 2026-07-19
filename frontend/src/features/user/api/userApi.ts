import { apiClient } from "@/lib/api/apiClient";
import { rootClient } from "@/lib/api/rootClient";

/** 응답 스키마는 OpenAPI 기준 — 프론트에서 필드를 추측하지 않고 표시용으로 전달 */
export type JsonValue = unknown;

export async function getHealth(): Promise<JsonValue> {
  const { data } = await rootClient.get("/health");
  return data;
}

export async function getSystemDashboard(params?: {
  account_id?: number;
  exchange_code?: string;
}): Promise<JsonValue> {
  const { data } = await apiClient.get("/system/dashboard", { params });
  return data;
}

export async function getDashboardSummary(): Promise<JsonValue> {
  const { data } = await apiClient.get("/dashboard/summary");
  return data;
}

export async function getBrokerAccount(): Promise<JsonValue> {
  const { data } = await apiClient.get("/broker/account");
  return data;
}

export async function getKiwoomConfiguration(): Promise<JsonValue> {
  const { data } = await apiClient.get("/kiwoom/configuration");
  return data;
}

export async function syncKiwoomAccount(): Promise<JsonValue> {
  const { data } = await apiClient.post("/broker/kiwoom/account/sync");
  return data;
}

export async function createPaperAccount(body: {
  account_name: string;
  initial_cash: number;
  currency_code?: string;
}): Promise<JsonValue> {
  const { data } = await apiClient.post("/paper-accounts", body);
  return data;
}

export async function getPaperPositions(accountId: number): Promise<JsonValue> {
  const { data } = await apiClient.get(`/paper-accounts/${accountId}/positions`);
  return data;
}

export async function getRealtimeStrategyStatus(): Promise<JsonValue> {
  const { data } = await apiClient.get("/realtime-strategy/status");
  return data;
}

export async function startRealtimeStrategy(): Promise<JsonValue> {
  const { data } = await apiClient.post("/realtime-strategy/start");
  return data;
}

export async function stopRealtimeStrategy(): Promise<JsonValue> {
  const { data } = await apiClient.post("/realtime-strategy/stop");
  return data;
}

export async function getRealtimeExecutionStatus(): Promise<JsonValue> {
  const { data } = await apiClient.get("/realtime-execution/status");
  return data;
}

export async function startRealtimeExecution(): Promise<JsonValue> {
  const { data } = await apiClient.post("/realtime-execution/start");
  return data;
}

export async function stopRealtimeExecution(): Promise<JsonValue> {
  const { data } = await apiClient.post("/realtime-execution/stop");
  return data;
}

export async function getKillSwitch(): Promise<JsonValue> {
  const { data } = await apiClient.get("/risk/kill-switch");
  return data;
}

export async function getStrategyRuntimeStatus(): Promise<JsonValue> {
  const { data } = await apiClient.get("/strategy-runtime/status");
  return data;
}

export async function getActiveStrategyDeployment(): Promise<JsonValue> {
  const { data } = await apiClient.get("/strategy-deployments/active");
  return data;
}

export async function getStrategyRanking(): Promise<JsonValue> {
  const { data } = await apiClient.get("/strategy-ranking");
  return data;
}

export async function getLatestStrategySelection(): Promise<JsonValue> {
  const { data } = await apiClient.get("/strategy-selector/latest");
  return data;
}

export async function listBacktestRuns(): Promise<JsonValue> {
  const { data } = await apiClient.get("/backtest-runs");
  return data;
}

export async function runMovingAverageBacktest(body: Record<string, unknown>): Promise<JsonValue> {
  const { data } = await apiClient.post("/backtests/moving-average", body);
  return data;
}

export async function getPortfolioSummary(): Promise<JsonValue> {
  const { data } = await apiClient.get("/portfolio/summary");
  return data;
}

export async function listPositions(): Promise<JsonValue> {
  const { data } = await apiClient.get("/positions");
  return data;
}

export async function listOrders(params?: Record<string, unknown>): Promise<JsonValue> {
  const { data } = await apiClient.get("/orders", { params });
  return data;
}

export async function listExecutions(params?: Record<string, unknown>): Promise<JsonValue> {
  const { data } = await apiClient.get("/executions", { params });
  return data;
}

export async function listPaperOrders(): Promise<JsonValue> {
  const { data } = await apiClient.get("/paper-orders");
  return data;
}

export async function getTopCandidates(exchangeCode: string): Promise<JsonValue> {
  const { data } = await apiClient.get(`/candidates/top/${exchangeCode}`);
  return data;
}

export async function getLatestAiAnalysis(exchangeCode: string): Promise<JsonValue> {
  const { data } = await apiClient.get(`/ai-analysis/latest/${exchangeCode}`);
  return data;
}

export async function listAiAnalysisRuns(): Promise<JsonValue> {
  const { data } = await apiClient.get("/ai-analysis/runs");
  return data;
}

export async function getNewsContext(
  exchangeCode: string,
  symbol: string,
): Promise<JsonValue> {
  const { data } = await apiClient.get(`/news/${exchangeCode}/${symbol}`);
  return data;
}

export async function getNotificationStatus(): Promise<JsonValue> {
  const { data } = await apiClient.get("/notification/status");
  return data;
}
