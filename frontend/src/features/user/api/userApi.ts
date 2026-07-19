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

export async function getDashboardSummary(params: {
  account_id: string | number;
}): Promise<JsonValue> {
  // STEP56: step32 /dashboard/summary → admin-summary
  const { data } = await apiClient.get("/dashboard/admin-summary", {
    params: {
      account_id: Number(params.account_id),
      market_code: "KRX",
      mode_code: "PAPER",
      recent_limit: 10,
    },
  });
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

export async function getRealtimeExecutionHistory(): Promise<JsonValue> {
  const { data } = await apiClient.get("/realtime-execution/history");
  return data;
}

export async function getRealtimeSessionsStatus(): Promise<JsonValue> {
  const { data } = await apiClient.get("/realtime-sessions/status");
  return data;
}

export async function startRealtimeSessionScheduler(): Promise<JsonValue> {
  const { data } = await apiClient.post("/realtime-sessions/start-scheduler");
  return data;
}

export async function stopRealtimeSessionScheduler(): Promise<JsonValue> {
  const { data } = await apiClient.post("/realtime-sessions/stop-scheduler");
  return data;
}

export async function runRealtimeSessionPhaseNow(
  phase: string,
): Promise<JsonValue> {
  const { data } = await apiClient.post(
    `/realtime-sessions/run-now/${encodeURIComponent(phase)}`,
  );
  return data;
}

export async function getRealtimeRiskStatus(): Promise<JsonValue> {
  const { data } = await apiClient.get("/realtime-risk/status");
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

export async function getActiveStrategyDeployment(params: {
  market_code: string;
  mode?: string;
  symbol?: string;
}): Promise<JsonValue> {
  // market_code 쿼리 필수
  const { data } = await apiClient.get("/strategy-deployments/active", {
    params,
  });
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

export async function listBacktestRuns(
  params?: Record<string, unknown>,
): Promise<JsonValue> {
  const { data } = await apiClient.get("/backtest-runs", { params });
  return data;
}

export async function runMovingAverageBacktest(body: {
  exchange_code: string;
  symbol: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  short_window?: number;
  long_window?: number;
  stop_loss_ratio?: number;
  take_profit_ratio?: number;
}): Promise<JsonValue> {
  const { data } = await apiClient.post("/backtests/moving-average", {
    short_window: 5,
    long_window: 20,
    stop_loss_ratio: 0.05,
    take_profit_ratio: 0.1,
    ...body,
  });
  return data;
}

export async function runWalkForward(body: {
  exchange_code: string;
  symbol: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  train_months?: number;
  test_months?: number;
  short_windows?: number[];
  long_windows?: number[];
  stop_loss_ratios?: number[];
  take_profit_ratios?: number[];
  position_ratios?: number[];
}): Promise<JsonValue> {
  const { data } = await apiClient.post("/walk-forward", {
    train_months: 6,
    test_months: 2,
    short_windows: [5, 10],
    long_windows: [20, 40],
    stop_loss_ratios: [0.05],
    take_profit_ratios: [0.1],
    position_ratios: [1],
    ...body,
  });
  return data;
}

export async function runPortfolioBacktest(body: {
  assets: Array<{
    exchange_code: string;
    symbol: string;
    weight: number;
  }>;
  start_date: string;
  end_date: string;
  initial_capital: number;
  short_window?: number;
  long_window?: number;
}): Promise<JsonValue> {
  const { data } = await apiClient.post("/portfolio-backtests", {
    short_window: 5,
    long_window: 20,
    ...body,
  });
  return data;
}

export async function getPortfolioSummary(params: {
  account_id: string | number;
}): Promise<JsonValue> {
  // STEP56: Paper 계좌 요약 (step32 /portfolio/summary 대체)
  const accountId = Number(params.account_id);
  const { data: account } = await apiClient.get(
    `/paper-accounts/${accountId}`,
  );
  const { data: positions } = await apiClient.get(
    `/paper-accounts/${accountId}/positions`,
  );
  return { account, positions, deprecated_source: "step32-migrated" };
}

export async function listPositions(accountId: number): Promise<JsonValue> {
  // STEP56: Paper 포지션 (step32 /positions 대체)
  const { data } = await apiClient.get(
    `/paper-accounts/${accountId}/positions`,
  );
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

export async function getTopCandidates(
  exchangeCode: string,
  asOfDate?: string,
): Promise<JsonValue> {
  // API 필수 파라미터 — 미지정 시 오늘(로컬) 날짜 사용
  const resolvedDate =
    asOfDate ??
    new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Seoul" });
  const { data } = await apiClient.get(`/candidates/top/${exchangeCode}`, {
    params: { as_of_date: resolvedDate },
  });
  return data;
}

export async function getLatestAiAnalysis(exchangeCode: string): Promise<JsonValue> {
  const { data } = await apiClient.get(`/ai-analysis/latest/${exchangeCode}`);
  return data;
}

export async function listAiAnalysisRuns(
  params?: Record<string, unknown>,
): Promise<JsonValue> {
  const { data } = await apiClient.get("/ai-analysis/runs", { params });
  return data;
}

export async function getAiAnalysisRun(runId: number): Promise<JsonValue> {
  const { data } = await apiClient.get(`/ai-analysis/runs/${runId}`);
  return data;
}

export async function getAiCandidateRationale(
  runId: number,
  symbol: string,
): Promise<JsonValue> {
  const { data } = await apiClient.get(
    `/ai-analysis/runs/${runId}/candidates/${encodeURIComponent(symbol)}`,
  );
  return data;
}

export async function getOllamaStatus(): Promise<JsonValue> {
  const { data } = await apiClient.get("/ollama/status");
  return data;
}

export async function listOllamaModels(): Promise<JsonValue> {
  const { data } = await apiClient.get("/ollama/models");
  return data;
}

/** AI 설정 — ollama_model 등 (settings:write 권한 필요) */
export async function updateAppSettings(body: {
  items: Array<{ key: string; value: unknown }>;
  change_reason?: string | null;
}): Promise<JsonValue> {
  const { data } = await apiClient.put("/settings", body);
  return data;
}

export async function summarizeNews(body: {
  exchange_code: string;
  symbol: string;
  limit?: number;
}): Promise<JsonValue> {
  const { data } = await apiClient.post("/news/summarize", {
    limit: 20,
    ...body,
  });
  return data;
}

export async function syncNews(body: {
  exchange_code: string;
  symbol: string;
  query: string;
  display?: number;
}): Promise<JsonValue> {
  const { data } = await apiClient.post("/news/sync", {
    display: 50,
    ...body,
  });
  return data;
}

export async function getNewsContext(
  exchangeCode: string,
  symbol: string,
  limit = 20,
): Promise<JsonValue> {
  const { data } = await apiClient.get(`/news/${exchangeCode}/${symbol}`, {
    params: { limit },
  });
  return data;
}

export async function getNotificationStatus(): Promise<JsonValue> {
  const { data } = await apiClient.get("/notification/status");
  return data;
}

export async function testNotification(body?: {
  title?: string;
  message?: string;
  detail?: Record<string, unknown>;
}): Promise<JsonValue> {
  const { data } = await apiClient.post("/notification/test", body ?? {});
  return data;
}

/** 투자 KPI — Paper 계좌 기준 (Admin summary와 동일 소스) */
export async function getInvestmentKpis(params: {
  account_id: number;
  market_code?: string;
  mode_code?: string;
  recent_limit?: number;
}): Promise<JsonValue> {
  const { data } = await apiClient.get("/dashboard/admin-summary", {
    params: {
      account_id: params.account_id,
      market_code: params.market_code ?? "KRX",
      mode_code: params.mode_code ?? "PAPER",
      recent_limit: params.recent_limit ?? 10,
    },
  });
  return data;
}

/** STEP52 — 로그인 사용자 기본 Paper 계좌 */
export async function getMyPaperAccount(): Promise<JsonValue> {
  const { data } = await apiClient.get("/paper-accounts/me");
  return data;
}

export async function listPaperAccounts(params?: {
  limit?: number;
  offset?: number;
}): Promise<JsonValue> {
  const { data } = await apiClient.get("/paper-accounts", { params });
  return data;
}

export async function listDartDisclosures(params: {
  stock_code: string;
  start_date?: string;
  end_date?: string;
  limit?: number;
}): Promise<JsonValue> {
  const { data } = await apiClient.get("/dart/disclosures", { params });
  return data;
}

export async function syncDartDisclosures(body: {
  stock_code?: string;
  corp_code?: string;
  start_date: string;
  end_date: string;
  resume?: boolean;
}): Promise<JsonValue> {
  const { data } = await apiClient.post("/dart/sync", body);
  return data;
}

export async function getPaperAccount(accountId: number): Promise<JsonValue> {
  const { data } = await apiClient.get(`/paper-accounts/${accountId}`);
  return data;
}

/** 최신 종가 — 포트폴리오·매매 폴백용 */
export async function getLatestPrice(
  exchangeCode: string,
  symbol: string,
): Promise<JsonValue> {
  const { data } = await apiClient.get(
    `/prices/latest/${exchangeCode}/${symbol}`,
  );
  return data;
}

/** 종목 목록 — 매매 화면 검색용 */
export async function listMarketSymbols(params?: {
  market?: string;
  active_only?: boolean;
}): Promise<JsonValue> {
  const { data } = await apiClient.get("/market/symbols", {
    params: {
      market: params?.market,
      active_only: params?.active_only ?? true,
    },
  });
  return data;
}

export async function createPaperOrder(body: {
  exchange_code: string;
  symbol: string;
  side: "BUY" | "SELL";
  order_type: "LIMIT" | "MARKET";
  quantity: number;
  price?: number;
  account_id: number;
  account_number?: string;
  auto_accept?: boolean;
}): Promise<JsonValue> {
  const { data } = await apiClient.post("/paper-orders", {
    auto_accept: true,
    ...body,
  });
  return data;
}

export async function cancelPaperOrder(orderId: number): Promise<JsonValue> {
  const { data } = await apiClient.post(`/paper-orders/${orderId}/cancel`);
  return data;
}

export async function submitLiveOrder(body: {
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
  const { data } = await apiClient.post("/order-execution/submit", {
    broker_code: "KIWOOM",
    order_type: "LIMIT",
    actor: "user-web",
    ...body,
  });
  return data;
}

export async function cancelTradingOrder(
  orderId: number,
  body?: { quantity?: number; actor?: string },
): Promise<JsonValue> {
  const { data } = await apiClient.post(`/orders/${orderId}/cancel`, {
    actor: body?.actor ?? "user-web",
    quantity: body?.quantity,
  });
  return data;
}

/** 실시간 시세 캐시 조회 (없으면 404) */
export async function getRealtimeQuote(
  exchangeCode: string,
  symbol: string,
): Promise<JsonValue> {
  const { data } = await apiClient.get(
    `/realtime-quotes/${exchangeCode}/${symbol}`,
  );
  return data;
}

export async function getRealtimeQuotesStatus(): Promise<JsonValue> {
  const { data } = await apiClient.get("/realtime-quotes/status");
  return data;
}

export async function getStrategyOpsDashboard(): Promise<JsonValue> {
  const { data } = await apiClient.get("/dashboard/strategy-operations");
  return data;
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
  const { data } = await apiClient.post("/strategy-deployments", {
    mode: "PAPER",
    parameter_payload: {},
    ...body,
  });
  return data;
}

export async function updateStrategyDeployment(
  deploymentId: number,
  body: {
    parameter_payload: Record<string, unknown>;
    requested_by: string;
  },
): Promise<JsonValue> {
  const { data } = await apiClient.post(
    `/strategy-deployments/${deploymentId}/update`,
    body,
  );
  return data;
}

export async function stopStrategyDeployment(
  deploymentId: number,
  body?: { actor?: string; reason?: string },
): Promise<JsonValue> {
  const { data } = await apiClient.post(
    `/strategy-deployments/${deploymentId}/stop`,
    {
      actor: body?.actor ?? "user-web",
      reason: body?.reason ?? "Stopped from User Web",
    },
  );
  return data;
}

export async function reloadStrategyRuntime(params?: {
  market_code?: string;
  symbol?: string;
  force?: boolean;
}): Promise<JsonValue> {
  const { data } = await apiClient.post(
    "/strategy-runtime/reload",
    {},
    {
      params: {
        market_code: params?.market_code ?? "KRX",
        symbol: params?.symbol,
        force: params?.force ?? false,
      },
    },
  );
  return data;
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
  const { data } = await apiClient.post("/strategy-performance/runs", {
    parameter_payload: {},
    ...body,
  });
  return data;
}

export async function completeStrategyPerformanceRun(
  runId: number,
): Promise<JsonValue> {
  const { data } = await apiClient.post(
    `/strategy-performance/runs/${runId}/complete`,
    {
      initial_capital: 10_000_000,
      final_capital: 10_500_000,
      total_return_rate: 0.05,
      maximum_drawdown_rate: 0.02,
      win_rate: 0.55,
      total_trade_count: 10,
      winning_trade_count: 6,
      losing_trade_count: 4,
      average_profit_amount: 100_000,
      average_loss_amount: 50_000,
      gross_profit_amount: 600_000,
      gross_loss_amount: 200_000,
      net_profit_amount: 400_000,
    },
  );
  return data;
}
