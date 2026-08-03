import { apiClient } from "@/lib/api/apiClient";
import { rootClient } from "@/lib/api/rootClient";
import { getRefreshToken } from "@/lib/storage/tokenStorage";

/** 응답 스키마는 OpenAPI 기준 — 프론트에서 필드를 추측하지 않고 표시용으로 전달 */
export type JsonValue = unknown;

/** STEP65 — 회원 계좌 (Backend UserAccountView와 일치) */
export type UserAccountType = "PAPER" | "KIWOOM" | "UPBIT" | string;

export interface UserAccount {
  account_id: number;
  user_id: number;
  account_type: UserAccountType;
  broker_code: string;
  account_name: string;
  masked_account_number: string | null;
  currency_code: string;
  is_default: boolean;
  is_active: boolean;
  connection_status: string;
  created_at?: string | null;
  updated_at?: string | null;
  last_synced_at?: string | null;
  sync_note?: string;
  /** STEP 8-5-4 — Recovery 검토/일시중지 (상세 Conflict 없음) */
  trading_paused?: boolean;
  recovery_review_required?: boolean;
  recovery_status?: string | null;
  recovery_user_message?: string | null;
  /** 사용자용 친절한 일시중지 원인 목록 (내부 코드 비노출) */
  pause_reasons?: string[];
  /** STEP 8-5-8 — Upbit Rate Limit 요약 */
  upbit_api_status?: string | null;
  upbit_rate_limit_message?: string | null;
  upbit_retry_scheduled_at?: string | null;
  /** STEP 8-7 — LIVE 실주문 승인 (읽기 전용) */
  live_order_enabled?: boolean;
  /** LIVE ARM 상태 (읽기 전용) */
  live_armed?: boolean;
  /** LIVE+ARM 모두 켜져 실주문 가능 여부 */
  live_trading_ready?: boolean;
  /** Trading Scheduler 상태 (읽기 전용) */
  trading_scheduler_state?: string | null;
  trading_scheduler_desired?: string | null;
  trading_scheduler_actual?: string | null;
}

export interface UserAccountListResponse {
  items: UserAccount[];
  total: number;
}

export interface CreateUserAccountRequest {
  account_type: UserAccountType;
  account_name?: string | null;
  initial_cash?: number | null;
  currency_code?: string;
  account_number?: string | null;
  is_default?: boolean;
}

export interface UpdateUserAccountRequest {
  account_name?: string | null;
  is_active?: boolean | null;
  account_type?: UserAccountType | null;
}

export interface TradeOrder {
  order_id?: number;
  account_id?: number;
  symbol?: string;
  exchange_code?: string;
  side_code?: string;
  status_code?: string;
  order_quantity?: number | string;
  order_price?: number | string | null;
  filled_quantity?: number | string;
  created_at?: string;
  // STEP 8-5-14 — Resolver Scheduler 원격 재조회 안전 필드 (Claim 토큰 등은 노출 안 함)
  next_remote_lookup_at?: string | null;
  last_remote_lookup_at?: string | null;
  remote_lookup_attempt_count?: number;
  manual_review_required?: boolean;
  remote_order_found?: boolean;
  [key: string]: unknown;
}

export interface TradeExecution {
  execution_id?: number;
  order_id?: number;
  symbol?: string;
  side_code?: string | null;
  execution_price?: number | string;
  execution_quantity?: number | string;
  executed_at?: string;
  [key: string]: unknown;
}

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

export async function syncKiwoomAccount(
  userBrokerAccountId: number,
): Promise<JsonValue> {
  const { data } = await apiClient.post(
    "/broker/kiwoom/account/sync",
    {},
    { params: { user_broker_account_id: userBrokerAccountId } },
  );
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
  const { data } = await apiClient.get("/user/strategies/realtime/status");
  return data;
}

/** STEP 8-5-9 — 본인 Realtime Scope 상태 */
export async function listMyRealtimeScopes(): Promise<JsonValue> {
  const { data } = await apiClient.get("/user/realtime/scopes");
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

export type RiskSettingsPayload = {
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
  duplicate_order_window_seconds?: number | null;
};

export async function getMyRiskSettings(): Promise<JsonValue> {
  const { data } = await apiClient.get("/user/risk-settings");
  return data;
}

export async function updateMyRiskSettings(
  body: RiskSettingsPayload,
): Promise<JsonValue> {
  const { data } = await apiClient.put("/user/risk-settings", body);
  return data;
}

export async function getAccountRiskSettings(
  userBrokerAccountId: number,
): Promise<JsonValue> {
  const { data } = await apiClient.get(
    `/user/accounts/${userBrokerAccountId}/risk-settings`,
  );
  return data;
}

export async function updateAccountRiskSettings(
  userBrokerAccountId: number,
  body: RiskSettingsPayload,
): Promise<JsonValue> {
  const { data } = await apiClient.put(
    `/user/accounts/${userBrokerAccountId}/risk-settings`,
    body,
  );
  return data;
}

/** STEP 8-7 — 계좌 LIVE 상태 (읽기 전용) */
export async function listMyLiveOrderStatus(): Promise<JsonValue> {
  const { data } = await apiClient.get("/user/live-order/accounts");
  return data;
}

export async function getMyLiveOrderStatus(
  userBrokerAccountId: number,
): Promise<JsonValue> {
  const { data } = await apiClient.get(
    `/user/live-order/accounts/${userBrokerAccountId}`,
  );
  return data;
}

/** STEP 8-8 — LIVE/ARM 읽기 전용 대시보드 */
export async function getMyLiveOpsDashboard(): Promise<JsonValue> {
  const { data } = await apiClient.get("/user/live-order/dashboard");
  return data;
}

/** STEP 8-9 — Upbit LIVE 검증 읽기 전용 */
export async function listUpbitLiveValidationRuns(
  limit = 20,
): Promise<JsonValue> {
  const { data } = await apiClient.get("/user/live-validation/upbit/runs", {
    params: { limit },
  });
  return data;
}

export async function getUpbitLiveValidationRun(
  runId: string,
): Promise<JsonValue> {
  const { data } = await apiClient.get(
    `/user/live-validation/upbit/runs/${runId}`,
  );
  return data;
}

/** Controlled Live Order Smoke — 계좌 단위 Pre-flight / Preview / Confirm */
export async function getLiveOrderPreflight(
  ubaId: number,
): Promise<JsonValue> {
  const { data } = await apiClient.get(
    `/user/accounts/${ubaId}/live-order-preflight`,
  );
  return data;
}

export async function postLiveOrderPreview(
  ubaId: number,
  body: {
    market: string;
    side: string;
    amount?: number;
    limit_price?: number;
    idempotency_key?: string;
  },
): Promise<JsonValue> {
  const { data } = await apiClient.post(
    `/user/accounts/${ubaId}/live-order-preview`,
    body,
  );
  return data;
}

export async function postLiveOrderConfirm(
  ubaId: number,
  body: {
    market: string;
    side: string;
    amount: number;
    limit_price: number;
    confirmation_text: string;
    arm_token?: string;
    execute_live?: boolean;
    idempotency_key?: string;
    preview_id?: string;
  },
): Promise<JsonValue> {
  const { data } = await apiClient.post(
    `/user/accounts/${ubaId}/live-order-confirm`,
    body,
  );
  return data;
}

export async function getLiveOrderSmokeRun(
  ubaId: number,
  runId: string,
): Promise<JsonValue> {
  const { data } = await apiClient.get(
    `/user/accounts/${ubaId}/live-order-smoke/${runId}`,
  );
  return data;
}

export async function getLiveOrderSmokeMeta(): Promise<JsonValue> {
  const { data } = await apiClient.get("/user/accounts/live-order-smoke/meta");
  return data;
}

/** STEP 8-3 — 전략 소유권 정의 */
export type StrategyDefinitionPayload = {
  strategy_code: string;
  name: string;
  description?: string | null;
  market_type?: string;
  parameter_payload?: Record<string, unknown>;
};

export async function listOwnedStrategies(params?: {
  scope?: "MINE" | "PUBLIC";
  limit?: number;
  offset?: number;
}): Promise<JsonValue> {
  const { data } = await apiClient.get("/user/strategies", { params });
  return data;
}

export async function getOwnedStrategy(
  strategyId: number,
): Promise<JsonValue> {
  const { data } = await apiClient.get(`/user/strategies/${strategyId}`);
  return data;
}

export async function createOwnedStrategy(
  body: StrategyDefinitionPayload,
): Promise<JsonValue> {
  const { data } = await apiClient.post("/user/strategies", body);
  return data;
}

export async function updateOwnedStrategy(
  strategyId: number,
  body: Partial<StrategyDefinitionPayload> & { is_active?: boolean },
): Promise<JsonValue> {
  const { data } = await apiClient.put(`/user/strategies/${strategyId}`, body);
  return data;
}

export async function deleteOwnedStrategy(
  strategyId: number,
): Promise<JsonValue> {
  const { data } = await apiClient.delete(`/user/strategies/${strategyId}`);
  return data;
}

export async function cloneOwnedStrategy(
  strategyId: number,
  body?: { name?: string },
): Promise<JsonValue> {
  const { data } = await apiClient.post(
    `/user/strategies/${strategyId}/clone`,
    body ?? {},
  );
  return data;
}

export async function checkStrategyBacktestAllowed(
  strategyId: number,
): Promise<JsonValue> {
  const { data } = await apiClient.post(
    `/user/strategies/${strategyId}/backtest`,
    {},
  );
  return data;
}

export async function listAccountStrategies(
  accountId: number,
  accountType = "PAPER",
): Promise<JsonValue> {
  const { data } = await apiClient.get(
    `/user/accounts/${accountId}/strategies`,
    { params: { account_type: accountType } },
  );
  return data;
}

export async function linkAccountStrategy(
  accountId: number,
  strategyId: number,
  body?: { account_type?: string; account_broker?: string },
): Promise<JsonValue> {
  const { data } = await apiClient.post(
    `/user/accounts/${accountId}/strategies/${strategyId}`,
    body ?? { account_type: "PAPER", account_broker: "PAPER" },
  );
  return data;
}

export async function unlinkAccountStrategy(
  accountId: number,
  strategyId: number,
  accountType = "PAPER",
): Promise<JsonValue> {
  const { data } = await apiClient.delete(
    `/user/accounts/${accountId}/strategies/${strategyId}`,
    { params: { account_type: accountType } },
  );
  return data;
}

export async function getStrategyRuntimeStatus(): Promise<JsonValue> {
  const { data } = await apiClient.get("/user/strategies/runtime/status");
  return data;
}

/** STEP 8-5-5 — 본인 Scope Runtime */
export async function listMyRuntimes(): Promise<{
  items: Array<Record<string, unknown>>;
  total: number;
}> {
  const { data } = await apiClient.get("/user/runtimes");
  const row = data as {
    items?: Array<Record<string, unknown>>;
    total?: number;
  };
  return {
    items: Array.isArray(row.items) ? row.items : [],
    total: row.total ?? 0,
  };
}

export async function listAccountRuntimes(
  accountId: number,
  accountType?: string,
): Promise<{
  items: Array<Record<string, unknown>>;
  total: number;
}> {
  const { data } = await apiClient.get(
    `/user/accounts/${accountId}/runtimes`,
    { params: accountType ? { account_type: accountType } : undefined },
  );
  const row = data as {
    items?: Array<Record<string, unknown>>;
    total?: number;
  };
  return {
    items: Array.isArray(row.items) ? row.items : [],
    total: row.total ?? 0,
  };
}

export async function getActiveStrategyDeployment(params: {
  market_code: string;
  mode?: string;
  symbol?: string;
}): Promise<JsonValue> {
  // market_code 쿼리 필수 — require_authenticated라 회원도 조회 가능
  const { data } = await apiClient.get("/strategy-deployments/active", {
    params,
  });
  return data;
}

export async function getStrategyRanking(): Promise<JsonValue> {
  const { data } = await apiClient.get("/user/strategies/ranking");
  return data;
}

export async function getLatestStrategySelection(): Promise<JsonValue> {
  const { data } = await apiClient.get("/user/strategies/selection/latest");
  return data;
}

export async function listBacktestRuns(
  params?: Record<string, unknown>,
): Promise<JsonValue> {
  const { data } = await apiClient.get("/user/backtests/runs", { params });
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
  const { data } = await apiClient.post("/user/backtests/moving-average", {
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
  const { data } = await apiClient.post("/user/backtests/walk-forward", {
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
  const { data } = await apiClient.post("/user/backtests/portfolio", {
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

export async function listOrders(params?: {
  account_id?: number;
  user_broker_account_id?: number;
  status_code?: string;
  broker_code?: string;
  exchange_code?: string;
  symbol?: string;
  limit?: number;
  offset?: number;
}): Promise<TradeOrder[]> {
  const { data } = await apiClient.get("/orders", { params });
  return (Array.isArray(data) ? data : []) as TradeOrder[];
}

export async function listExecutions(params?: {
  account_id?: number;
  user_broker_account_id?: number;
  limit?: number;
}): Promise<TradeExecution[]> {
  const { data } = await apiClient.get("/executions", { params });
  return (Array.isArray(data) ? data : []) as TradeExecution[];
}

/** 계좌 원장 기준 전략별 성과 (백테스트와 분리) */
export interface AccountStrategyPerformanceItem {
  strategy_id?: number | null;
  strategy_name?: string | null;
  strategy_code?: string | null;
  strategy_version?: string | null;
  attribution?: string;
  order_count?: number;
  fill_count?: number;
  buy_quantity?: string;
  sell_quantity?: string;
  realized_pnl?: string;
  unrealized_pnl?: string;
  fee_tax?: string;
  net_pnl?: string;
  win_count?: number;
  loss_count?: number;
  win_rate?: number | null;
  period_return_rate?: number | null;
  last_trade_at?: string | null;
  source?: string;
}

export interface AccountStrategyPerformanceResponse {
  account_id: number;
  account_type: string;
  source: string;
  unattributed_label?: string;
  items: AccountStrategyPerformanceItem[];
}

export interface AccountStrategyTradeItem {
  order_id?: number;
  execution_id?: number;
  trade_id?: number;
  symbol?: string;
  side_code?: string;
  quantity?: string | number;
  price?: string | number;
  realized_pnl?: string | number;
  traded_at?: string | null;
  strategy_key?: string;
  source?: string;
  [key: string]: unknown;
}

export interface AccountStrategyTradesResponse {
  account_id: number;
  strategy_key: string;
  source: string;
  items: AccountStrategyTradeItem[];
}

export async function getAccountStrategyPerformance(
  accountId: number,
  opts?: {
    account_type?: string;
    date_from?: string;
    date_to?: string;
  },
): Promise<AccountStrategyPerformanceResponse> {
  const { data } = await apiClient.get<AccountStrategyPerformanceResponse>(
    `/user/accounts/${accountId}/strategy-performance`,
    {
      params: {
        account_type: opts?.account_type ?? "PAPER",
        date_from: opts?.date_from,
        date_to: opts?.date_to,
      },
    },
  );
  return data;
}

export async function getAccountStrategyTrades(
  accountId: number,
  strategyKey: string,
  opts?: {
    account_type?: string;
    date_from?: string;
    date_to?: string;
    limit?: number;
  },
): Promise<AccountStrategyTradesResponse> {
  const { data } = await apiClient.get<AccountStrategyTradesResponse>(
    `/user/accounts/${accountId}/strategy-performance/${encodeURIComponent(strategyKey)}/trades`,
    {
      params: {
        account_type: opts?.account_type ?? "PAPER",
        date_from: opts?.date_from,
        date_to: opts?.date_to,
        limit: opts?.limit ?? 100,
      },
    },
  );
  return data;
}

export async function listPaperOrders(params?: {
  account_id?: number;
  exchange_code?: string;
  limit?: number;
}): Promise<JsonValue> {
  const { data } = await apiClient.get("/paper-orders", { params });
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
  const { data } = await apiClient.get(`/user/candidates/top/${exchangeCode}`, {
    params: { as_of_date: resolvedDate },
  });
  return data;
}

/** 최신 매매 후보 스코어링 — 별도 as_of_date 지정 없이 최신 배치 결과 조회 (없으면 404) */
export async function getLatestCandidates(
  exchangeCode: string,
): Promise<JsonValue> {
  const { data } = await apiClient.get(
    `/user/candidates/latest/${exchangeCode}`,
  );
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

/** STEP71 — Notification Center */
export interface UserNotificationItem {
  notification_id: number;
  user_notification_id: number;
  event_type: string;
  category: string;
  title: string;
  message: string;
  severity: string;
  created_at: string;
  expires_at: string | null;
  is_read: boolean;
  is_archived: boolean;
  is_starred: boolean;
  read_at: string | null;
  delivery_status: string;
  payload?: Record<string, unknown>;
}

export interface UserNotificationListResponse {
  items: UserNotificationItem[];
  page: number;
  page_size: number;
  total_count: number;
  has_next: boolean;
}

export interface UserNotificationFilter {
  event_type?: string;
  severity?: string;
  unread_only?: boolean;
  archived?: boolean | null;
  starred?: boolean | null;
  keyword?: string;
  page?: number;
  page_size?: number;
}

export interface NotificationSubscriptionItem {
  event_type: string;
  enabled: boolean;
  telegram_enabled: boolean;
  web_enabled: boolean;
  email_enabled: boolean;
  quiet_time_start: string | null;
  quiet_time_end: string | null;
}

export async function listUserNotifications(
  params?: UserNotificationFilter,
): Promise<UserNotificationListResponse> {
  const { data } = await apiClient.get("/user/notifications", { params });
  return data as UserNotificationListResponse;
}

export async function getUserNotificationDetail(
  notificationId: number,
): Promise<UserNotificationItem> {
  const { data } = await apiClient.get(
    `/user/notifications/${notificationId}`,
  );
  return data as UserNotificationItem;
}

export async function getNotificationUnreadCount(): Promise<{
  unread_count: number;
  total: number;
}> {
  const { data } = await apiClient.get("/user/notifications/unread-count");
  return data as { unread_count: number; total: number };
}

export async function markNotificationRead(
  notificationId: number,
): Promise<{ notification_id: number; is_read: boolean }> {
  const { data } = await apiClient.post(
    `/user/notifications/${notificationId}/read`,
  );
  return data as { notification_id: number; is_read: boolean };
}

export async function markNotificationUnread(
  notificationId: number,
): Promise<{ notification_id: number; is_read: boolean }> {
  const { data } = await apiClient.delete(
    `/user/notifications/${notificationId}/read`,
  );
  return data as { notification_id: number; is_read: boolean };
}

export async function readAllNotifications(): Promise<{
  updated_count: number;
}> {
  const { data } = await apiClient.post("/user/notifications/read-all");
  return data as { updated_count: number };
}

export async function archiveNotification(
  notificationId: number,
): Promise<{ notification_id: number; is_archived: boolean }> {
  const { data } = await apiClient.post(
    `/user/notifications/${notificationId}/archive`,
  );
  return data as { notification_id: number; is_archived: boolean };
}

export async function unarchiveNotification(
  notificationId: number,
): Promise<{ notification_id: number; is_archived: boolean }> {
  const { data } = await apiClient.delete(
    `/user/notifications/${notificationId}/archive`,
  );
  return data as { notification_id: number; is_archived: boolean };
}

export async function starNotification(
  notificationId: number,
): Promise<{ notification_id: number; is_starred: boolean }> {
  const { data } = await apiClient.post(
    `/user/notifications/${notificationId}/star`,
  );
  return data as { notification_id: number; is_starred: boolean };
}

export async function unstarNotification(
  notificationId: number,
): Promise<{ notification_id: number; is_starred: boolean }> {
  const { data } = await apiClient.delete(
    `/user/notifications/${notificationId}/star`,
  );
  return data as { notification_id: number; is_starred: boolean };
}

export async function deleteUserNotification(
  notificationId: number,
): Promise<{ notification_id: number; is_deleted: boolean }> {
  const { data } = await apiClient.delete(
    `/user/notifications/${notificationId}`,
  );
  return data as { notification_id: number; is_deleted: boolean };
}

export async function listNotificationSubscriptions(): Promise<{
  items: NotificationSubscriptionItem[];
}> {
  const { data } = await apiClient.get("/user/notifications/subscriptions");
  return data as { items: NotificationSubscriptionItem[] };
}

export async function updateNotificationSubscription(
  body: NotificationSubscriptionItem,
): Promise<NotificationSubscriptionItem> {
  const { data } = await apiClient.put(
    "/user/notifications/subscriptions",
    body,
  );
  return data as NotificationSubscriptionItem;
}

/** STEP72 — User Preferences / Settings */
export interface UserSettings {
  user_id: number;
  theme: "light" | "dark" | "system" | string;
  language: "KO" | "EN" | string;
  timezone: string;
  date_format: string;
  number_format: string;
  currency: "KRW" | "USD" | string;
  default_market: string;
  default_account_id: number | null;
  default_watchlist_id: number | null;
  default_dashboard: string;
  items_per_page: number;
  ai_enabled: boolean;
  ai_auto_summary: boolean;
  ai_recommendation_enabled: boolean;
  notification_enabled: boolean;
  telegram_enabled: boolean;
  email_enabled: boolean;
  web_enabled: boolean;
  created_at?: string;
  updated_at?: string;
}

export type UserSettingsPatch = Partial<
  Omit<UserSettings, "user_id" | "created_at" | "updated_at">
>;

export async function getUserSettings(): Promise<UserSettings> {
  const { data } = await apiClient.get("/user/settings");
  return data as UserSettings;
}

export async function putUserSettings(
  body: UserSettingsPatch,
): Promise<UserSettings> {
  const { data } = await apiClient.put("/user/settings", body);
  return data as UserSettings;
}

export async function patchUserSettings(
  body: UserSettingsPatch,
): Promise<UserSettings> {
  const { data } = await apiClient.patch("/user/settings", body);
  return data as UserSettings;
}

export async function resetUserSettings(): Promise<UserSettings> {
  const { data } = await apiClient.post("/user/settings/reset");
  return data as UserSettings;
}

/** STEP73 — My Profile / Security / Connections */
export interface UserProfile {
  user_id: number;
  username: string;
  email: string | null;
  email_full: string | null;
  display_name: string | null;
  nickname: string | null;
  profile_image_url: string | null;
  bio: string | null;
  locale: string;
  status: string;
  email_verified: boolean;
  last_login_at: string | null;
  last_password_changed_at: string | null;
  created_at: string;
  updated_at?: string;
  two_factor_enabled: boolean;
  two_factor_method: string | null;
  two_factor_enrolled_at: string | null;
}

export type UpdateUserProfileRequest = Partial<
  Pick<
    UserProfile,
    "display_name" | "nickname" | "profile_image_url" | "bio" | "locale"
  >
>;

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
  new_password_confirmation: string;
}

export interface UserSession {
  session_id: string;
  device_name: string;
  browser_name: string | null;
  operating_system: string | null;
  ip_address_masked: string;
  created_at: string;
  last_used_at: string;
  expires_at: string;
  is_current: boolean;
}

export interface UserSessionListResponse {
  items: UserSession[];
  total: number;
}

export type ConnectedServiceStatus =
  | "CONNECTED"
  | "NOT_CONNECTED"
  | "VERIFYING"
  | "ERROR"
  | "EXPIRED"
  | "DISABLED"
  | string;

export interface ConnectedService {
  connection_type: string;
  status: ConnectedServiceStatus;
  display_name: string;
  account_masked: string | null;
  mode?: string | null;
  last_verified_at: string | null;
  last_success_at: string | null;
  last_error_code: string | null;
  can_disconnect: boolean;
  manage_path?: string;
  note?: string;
}

export interface UserAccountSummary {
  paper_accounts: {
    count: number;
    default_account_id: number | null;
  };
  kiwoom_accounts: { count: number; connected: boolean };
  upbit_accounts: { count: number; connected: boolean };
  total_accounts: number;
  default_account_id: number | null;
}

function refreshTokenHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = getRefreshToken();
  return token ? { "X-Refresh-Token": token } : {};
}

export async function getUserProfile(): Promise<UserProfile> {
  const { data } = await apiClient.get("/user/profile");
  return data as UserProfile;
}

export async function updateUserProfile(
  body: UpdateUserProfileRequest,
): Promise<UserProfile> {
  const { data } = await apiClient.patch("/user/profile", body);
  return data as UserProfile;
}

export async function changeUserPassword(
  body: ChangePasswordRequest,
): Promise<{
  changed: boolean;
  revoked_session_count: number;
  current_session_kept: boolean;
  last_password_changed_at: string;
}> {
  const { data } = await apiClient.post("/user/profile/change-password", body, {
    headers: refreshTokenHeaders(),
  });
  return data as {
    changed: boolean;
    revoked_session_count: number;
    current_session_kept: boolean;
    last_password_changed_at: string;
  };
}

export async function listUserSessions(): Promise<UserSessionListResponse> {
  const { data } = await apiClient.get("/user/profile/sessions", {
    headers: refreshTokenHeaders(),
  });
  return data as UserSessionListResponse;
}

export async function revokeUserSession(
  sessionId: string,
): Promise<{ revoked: boolean; session_id: string; was_current: boolean }> {
  const { data } = await apiClient.delete(
    `/user/profile/sessions/${sessionId}`,
    { headers: refreshTokenHeaders() },
  );
  return data as {
    revoked: boolean;
    session_id: string;
    was_current: boolean;
  };
}

export async function revokeUserSessions(params?: {
  exclude_current?: boolean;
}): Promise<{
  revoked_count: number;
  exclude_current: boolean;
  current_session_kept: boolean;
}> {
  const { data } = await apiClient.delete("/user/profile/sessions", {
    params: { exclude_current: params?.exclude_current ?? true },
    headers: refreshTokenHeaders(),
  });
  return data as {
    revoked_count: number;
    exclude_current: boolean;
    current_session_kept: boolean;
  };
}

export async function getProfileAccountsSummary(): Promise<UserAccountSummary> {
  const { data } = await apiClient.get("/user/profile/accounts-summary");
  return data as UserAccountSummary;
}

export async function getProfileConnections(): Promise<{
  connections: ConnectedService[];
  accounts_summary: UserAccountSummary;
}> {
  const { data } = await apiClient.get("/user/profile/connections");
  return data as {
    connections: ConnectedService[];
    accounts_summary: UserAccountSummary;
  };
}

export async function disconnectTelegramConnection(): Promise<{
  disconnected: boolean;
  connection_type: string;
}> {
  const { data } = await apiClient.delete(
    "/user/profile/connections/telegram",
  );
  return data as { disconnected: boolean; connection_type: string };
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

/** STEP66 — 포트폴리오 자산 이력 */
export type PortfolioHistoryPeriod = "7d" | "30d" | "90d" | "1y" | "all";

export interface PortfolioHistoryItem {
  snapshot_id?: number;
  account_id: number;
  snapshot_date: string;
  snapshot_time?: string | null;
  cash: string;
  market_value: string;
  total_asset: string;
  invested_amount?: string;
  realized_profit?: string;
  unrealized_profit?: string;
  daily_profit: string;
  daily_profit_rate: string;
  total_return_rate: string;
  position_count?: number;
  mode_code?: string;
  valuation_mode?: string;
}

export interface PortfolioHistoryResponse {
  account_id: number;
  period: string;
  from: string | null;
  to: string | null;
  items: PortfolioHistoryItem[];
  total: number;
}

export interface PortfolioAssetSummaryResponse {
  account_id: number;
  period: string;
  from: string | null;
  to: string | null;
  current_total_asset: string | null;
  current_cash: string | null;
  current_market_value: string | null;
  today_profit: string;
  cumulative_profit: string;
  peak_asset: string;
  trough_asset: string;
  max_drawdown: string;
  max_drawdown_pct: string;
  period_return_rate: string;
  daily_return_rate: string;
  weekly_return_rate: string;
  monthly_return_rate: string;
  total_return_rate: string;
  realized_profit: string | null;
  unrealized_profit: string | null;
  position_count: number;
  snapshot_count: number;
  valuation_mode: string | null;
}

export async function getPortfolioHistory(params: {
  account_id: number;
  period?: PortfolioHistoryPeriod | string;
  from?: string;
  to?: string;
}): Promise<PortfolioHistoryResponse> {
  const { data } = await apiClient.get("/user/portfolio/history", {
    params,
  });
  return data as PortfolioHistoryResponse;
}

export async function getPortfolioAssetSummary(params: {
  account_id: number;
  period?: PortfolioHistoryPeriod | string;
  from?: string;
  to?: string;
}): Promise<PortfolioAssetSummaryResponse> {
  const { data } = await apiClient.get("/user/portfolio/summary", {
    params,
  });
  return data as PortfolioAssetSummaryResponse;
}

export async function createPortfolioSnapshot(body: {
  account_id: number;
  snapshot_date?: string;
  mode_code?: string;
}): Promise<PortfolioHistoryItem> {
  const { data } = await apiClient.post("/user/portfolio/snapshot", body);
  return data as PortfolioHistoryItem;
}

/** STEP67 — 관심종목 */
export interface WatchlistItem {
  watchlist_id: number;
  user_id: number;
  market: string;
  symbol: string;
  symbol_name: string;
  display_order: number;
  memo: string | null;
  color: string | null;
  alarm_enabled: boolean;
  news_enabled: boolean;
  disclosure_enabled: boolean;
  ai_enabled: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface WatchlistListResponse {
  items: WatchlistItem[];
  total: number;
  max_items: number;
}

export interface WatchlistSearchHit {
  market: string;
  symbol: string;
  symbol_name: string;
  name?: string;
  asset_type?: string;
  currency?: string;
}

export async function listWatchlist(): Promise<WatchlistListResponse> {
  const { data } = await apiClient.get("/user/watchlist");
  return data as WatchlistListResponse;
}

export async function searchWatchlistSymbols(params: {
  q: string;
  market?: string;
  limit?: number;
}): Promise<{ items: WatchlistSearchHit[]; query: string }> {
  const { data } = await apiClient.get("/user/watchlist/search", { params });
  return data as { items: WatchlistSearchHit[]; query: string };
}

export async function addWatchlistItem(body: {
  market: string;
  symbol: string;
  symbol_name?: string;
  memo?: string;
  color?: string;
  alarm_enabled?: boolean;
  news_enabled?: boolean;
  disclosure_enabled?: boolean;
  ai_enabled?: boolean;
}): Promise<WatchlistItem> {
  const { data } = await apiClient.post("/user/watchlist", body);
  return data as WatchlistItem;
}

export async function updateWatchlistItem(
  watchlistId: number,
  body: {
    memo?: string | null;
    color?: string | null;
    symbol_name?: string;
    alarm_enabled?: boolean;
    news_enabled?: boolean;
    disclosure_enabled?: boolean;
    ai_enabled?: boolean;
    display_order?: number;
    clear_memo?: boolean;
    clear_color?: boolean;
  },
): Promise<WatchlistItem> {
  const { data } = await apiClient.patch(`/user/watchlist/${watchlistId}`, body);
  return data as WatchlistItem;
}

export async function deleteWatchlistItem(
  watchlistId: number,
): Promise<{ deleted: boolean; item: WatchlistItem }> {
  const { data } = await apiClient.delete(`/user/watchlist/${watchlistId}`);
  return data as { deleted: boolean; item: WatchlistItem };
}

export async function reorderWatchlist(
  orderedIds: number[],
): Promise<WatchlistListResponse> {
  const { data } = await apiClient.put("/user/watchlist/reorder", {
    ordered_ids: orderedIds,
  });
  return data as WatchlistListResponse;
}

/** STEP68 — 관심종목 뉴스 */
export interface UserNewsSymbol {
  market_code: string;
  symbol: string;
  symbol_name: string;
  relevance_score: number;
  match_type?: string;
}

export interface UserNewsItem {
  news_id: number;
  title: string;
  summary: string | null;
  source_code: string;
  source_name: string;
  original_url: string | null;
  published_at: string | null;
  matched_symbols: UserNewsSymbol[];
  is_read: boolean;
  is_bookmarked: boolean;
  collected_at?: string;
}

export interface UserNewsListResponse {
  items: UserNewsItem[];
  page: number;
  page_size: number;
  total_count: number;
  has_next: boolean;
  watchlist_empty?: boolean;
  message?: string;
}

export interface UserNewsFilter {
  market_code?: string;
  symbol?: string;
  watchlist_id?: number;
  keyword?: string;
  source_code?: string;
  from_date?: string;
  to_date?: string;
  read_status?: "read" | "unread" | "";
  bookmarked?: boolean;
  page?: number;
  page_size?: number;
}

export interface UnreadNewsCountResponse {
  unread_count: number;
  total: number;
  by_symbol: Array<{
    market_code: string;
    symbol: string;
    count: number;
  }>;
}

export interface UserNewsStateResponse {
  news_id: number;
  is_read?: boolean;
  is_bookmarked?: boolean;
  read_at?: string | null;
  bookmarked_at?: string | null;
}

export async function listUserNews(
  params?: UserNewsFilter,
): Promise<UserNewsListResponse> {
  const { data } = await apiClient.get("/user/news", { params });
  return data as UserNewsListResponse;
}

export async function getUserNewsDetail(
  newsId: number,
): Promise<UserNewsItem> {
  const { data } = await apiClient.get(`/user/news/${newsId}`);
  return data as UserNewsItem;
}

export async function getUnreadNewsCount(): Promise<UnreadNewsCountResponse> {
  const { data } = await apiClient.get("/user/news/unread-count");
  return data as UnreadNewsCountResponse;
}

export async function markUserNewsRead(
  newsId: number,
): Promise<UserNewsStateResponse> {
  const { data } = await apiClient.post(`/user/news/${newsId}/read`);
  return data as UserNewsStateResponse;
}

export async function unmarkUserNewsRead(
  newsId: number,
): Promise<UserNewsStateResponse> {
  const { data } = await apiClient.delete(`/user/news/${newsId}/read`);
  return data as UserNewsStateResponse;
}

export async function bookmarkUserNews(
  newsId: number,
): Promise<UserNewsStateResponse> {
  const { data } = await apiClient.post(`/user/news/${newsId}/bookmark`);
  return data as UserNewsStateResponse;
}

export async function unbookmarkUserNews(
  newsId: number,
): Promise<UserNewsStateResponse> {
  const { data } = await apiClient.delete(`/user/news/${newsId}/bookmark`);
  return data as UserNewsStateResponse;
}

export async function readAllUserNews(params?: {
  market_code?: string;
  symbol?: string;
}): Promise<{ updated_count: number; scope: string }> {
  const { data } = await apiClient.post("/user/news/read-all", null, {
    params,
  });
  return data as { updated_count: number; scope: string };
}

/** STEP69 — 관심종목 공시 */
export interface UserDisclosureItem {
  disclosure_id: number;
  receipt_no: string;
  corp_code: string;
  market_code: string;
  symbol: string;
  symbol_name: string;
  corp_name: string;
  report_name: string;
  disclosure_type: string;
  submitted_at: string | null;
  original_url: string | null;
  is_correction: boolean;
  related_receipt_no: string | null;
  is_read: boolean;
  is_bookmarked: boolean;
  ai_summary_status: string;
  has_ai_summary: boolean;
  filer_name?: string | null;
  remark?: string | null;
  importance_score?: number;
  body_text?: string;
  body_note?: string;
  ai_summary?: DisclosureAiSummary;
}

export interface UserDisclosureListResponse {
  items: UserDisclosureItem[];
  page: number;
  page_size: number;
  total_count: number;
  has_next: boolean;
  watchlist_empty?: boolean;
  message?: string;
}

export interface UserDisclosureFilter {
  market_code?: string;
  symbol?: string;
  watchlist_id?: number;
  disclosure_type?: string;
  report_name?: string;
  keyword?: string;
  from_date?: string;
  to_date?: string;
  read_status?: "read" | "unread" | "";
  bookmarked?: boolean;
  has_ai_summary?: boolean;
  page?: number;
  page_size?: number;
}

export type DisclosureAiSummaryStatus =
  | "NOT_REQUESTED"
  | "QUEUED"
  | "PROCESSING"
  | "COMPLETED"
  | "FAILED"
  | "STALE";

export interface DisclosureAiSummary {
  disclosure_id: number;
  status: DisclosureAiSummaryStatus | string;
  summary?: string | null;
  key_points?: string[];
  risk_factors?: string[];
  financial_impacts?: string[];
  important_numbers?: string[];
  uncertainty_notes?: string[];
  model_name?: string;
  prompt_version?: string;
  generated_at?: string | null;
  is_stale?: boolean;
  error_code?: string | null;
  disclaimer?: string;
  message?: string;
  regenerate_failed?: boolean;
}

export interface UnreadDisclosureCountResponse {
  unread_count: number;
  total: number;
  by_symbol: Array<{ symbol: string; count: number }>;
}

export interface UserAiStatusResponse {
  available: boolean;
  status: string;
  message: string | null;
  active_model_display_name?: string | null;
  last_success_at?: string | null;
  retry_after_seconds?: number | null;
  disclosure_summary_available?: boolean;
  recommendation_available?: boolean;
  model_configured?: boolean;
  prompt_version?: string;
}

/** STEP70 — 사용자 AI 추천 */
export type AiRecommendationRequestStatus =
  | "QUEUED"
  | "PROCESSING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "EXPIRED";

export type AiRecommendationAction =
  | "WATCH"
  | "POSITIVE"
  | "NEUTRAL"
  | "CAUTION"
  | "AVOID";

export interface CreateAiRecommendationRequest {
  market_code?: string;
  account_id?: number | null;
  source_type?:
    | "WATCHLIST"
    | "PORTFOLIO"
    | "MARKET_CANDIDATES"
    | "WATCHLIST_AND_PORTFOLIO";
  recommendation_count?: number;
  investment_horizon?: "SHORT_TERM" | "MEDIUM_TERM" | "LONG_TERM";
  risk_level?: "CONSERVATIVE" | "MODERATE" | "AGGRESSIVE";
}

export interface CreateAiRecommendationResponse {
  request_id: number;
  status: AiRecommendationRequestStatus | string;
  message: string;
  reused?: boolean;
}

export interface AiRecommendationSymbolResult {
  rank: number;
  market_code: string;
  symbol: string;
  symbol_name: string;
  action: AiRecommendationAction | string;
  confidence_score: number;
  total_score: number;
  summary: string | null;
  reasons: string[];
  risk_factors: string[];
  data_as_of?: string | null;
  in_watchlist?: boolean;
  in_portfolio?: boolean;
}

export interface AiRecommendationDetail {
  request_id: number;
  status: AiRecommendationRequestStatus | string;
  market_code: string;
  account_id: number | null;
  source_type: string;
  investment_horizon: string;
  risk_level: string;
  recommendation_count: number;
  generated_at: string | null;
  expires_at: string | null;
  is_expired: boolean;
  model_display_name?: string;
  prompt_version?: string;
  error_code?: string | null;
  is_bookmarked: boolean;
  is_hidden: boolean;
  candidate_count: number;
  disclaimer: string;
  items: AiRecommendationSymbolResult[];
}

export interface AiRecommendationListItem {
  request_id: number;
  status: string;
  market_code: string;
  source_type: string;
  investment_horizon: string;
  risk_level: string;
  recommendation_count: number;
  created_at: string;
  completed_at: string | null;
  expires_at: string | null;
  is_expired: boolean;
  is_bookmarked: boolean;
  top_symbol: string | null;
  top_symbol_name: string | null;
  top_action: string | null;
  has_results?: boolean;
}

export interface AiRecommendationFilter {
  market_code?: string;
  status?: string;
  bookmarked?: boolean;
  page?: number;
  page_size?: number;
}

export interface PaginatedAiRecommendationResponse {
  items: AiRecommendationListItem[];
  page: number;
  page_size: number;
  total_count: number;
  has_next: boolean;
}

export async function listUserDisclosures(
  params?: UserDisclosureFilter,
): Promise<UserDisclosureListResponse> {
  const { data } = await apiClient.get("/user/disclosures", { params });
  return data as UserDisclosureListResponse;
}

export async function getUserDisclosureDetail(
  disclosureId: number,
): Promise<UserDisclosureItem> {
  const { data } = await apiClient.get(`/user/disclosures/${disclosureId}`);
  return data as UserDisclosureItem;
}

export async function getUnreadDisclosureCount(): Promise<UnreadDisclosureCountResponse> {
  const { data } = await apiClient.get("/user/disclosures/unread-count");
  return data as UnreadDisclosureCountResponse;
}

export async function markUserDisclosureRead(
  disclosureId: number,
): Promise<{ disclosure_id: number; is_read: boolean }> {
  const { data } = await apiClient.post(
    `/user/disclosures/${disclosureId}/read`,
  );
  return data as { disclosure_id: number; is_read: boolean };
}

export async function unmarkUserDisclosureRead(
  disclosureId: number,
): Promise<{ disclosure_id: number; is_read: boolean }> {
  const { data } = await apiClient.delete(
    `/user/disclosures/${disclosureId}/read`,
  );
  return data as { disclosure_id: number; is_read: boolean };
}

export async function bookmarkUserDisclosure(
  disclosureId: number,
): Promise<{ disclosure_id: number; is_bookmarked: boolean }> {
  const { data } = await apiClient.post(
    `/user/disclosures/${disclosureId}/bookmark`,
  );
  return data as { disclosure_id: number; is_bookmarked: boolean };
}

export async function unbookmarkUserDisclosure(
  disclosureId: number,
): Promise<{ disclosure_id: number; is_bookmarked: boolean }> {
  const { data } = await apiClient.delete(
    `/user/disclosures/${disclosureId}/bookmark`,
  );
  return data as { disclosure_id: number; is_bookmarked: boolean };
}

export async function readAllUserDisclosures(params?: {
  market_code?: string;
  symbol?: string;
}): Promise<{ updated_count: number; scope: string }> {
  const { data } = await apiClient.post(
    "/user/disclosures/read-all",
    null,
    { params },
  );
  return data as { updated_count: number; scope: string };
}

export async function getDisclosureAiSummary(
  disclosureId: number,
): Promise<DisclosureAiSummary> {
  const { data } = await apiClient.get(
    `/user/disclosures/${disclosureId}/ai-summary`,
  );
  return data as DisclosureAiSummary;
}

export async function requestDisclosureAiSummary(
  disclosureId: number,
): Promise<DisclosureAiSummary> {
  const { data } = await apiClient.post(
    `/user/disclosures/${disclosureId}/ai-summary`,
  );
  return data as DisclosureAiSummary;
}

export async function regenerateDisclosureAiSummary(
  disclosureId: number,
): Promise<DisclosureAiSummary> {
  const { data } = await apiClient.post(
    `/user/disclosures/${disclosureId}/ai-summary/regenerate`,
  );
  return data as DisclosureAiSummary;
}

export async function getUserAiStatus(): Promise<UserAiStatusResponse> {
  const { data } = await apiClient.get("/user/ai/status");
  return data as UserAiStatusResponse;
}

export async function createAiRecommendation(
  body: CreateAiRecommendationRequest,
): Promise<CreateAiRecommendationResponse> {
  const { data } = await apiClient.post("/user/ai/recommendations", body);
  return data as CreateAiRecommendationResponse;
}

export async function listAiRecommendations(
  params?: AiRecommendationFilter,
): Promise<PaginatedAiRecommendationResponse> {
  const { data } = await apiClient.get("/user/ai/recommendations", {
    params,
  });
  return data as PaginatedAiRecommendationResponse;
}

export async function getLatestAiRecommendation(params?: {
  market_code?: string;
}): Promise<AiRecommendationDetail> {
  const { data } = await apiClient.get("/user/ai/recommendations/latest", {
    params,
  });
  return data as AiRecommendationDetail;
}

export async function getAiRecommendationDetail(
  requestId: number,
): Promise<AiRecommendationDetail> {
  const { data } = await apiClient.get(
    `/user/ai/recommendations/${requestId}`,
  );
  return data as AiRecommendationDetail;
}

export async function bookmarkAiRecommendation(
  requestId: number,
): Promise<{ request_id: number; is_bookmarked: boolean }> {
  const { data } = await apiClient.post(
    `/user/ai/recommendations/${requestId}/bookmark`,
  );
  return data as { request_id: number; is_bookmarked: boolean };
}

export async function unbookmarkAiRecommendation(
  requestId: number,
): Promise<{ request_id: number; is_bookmarked: boolean }> {
  const { data } = await apiClient.delete(
    `/user/ai/recommendations/${requestId}/bookmark`,
  );
  return data as { request_id: number; is_bookmarked: boolean };
}

export async function hideAiRecommendation(
  requestId: number,
): Promise<{ request_id: number; is_hidden: boolean }> {
  const { data } = await apiClient.post(
    `/user/ai/recommendations/${requestId}/hide`,
  );
  return data as { request_id: number; is_hidden: boolean };
}

export async function feedbackAiRecommendation(
  requestId: number,
  body: { feedback_type: string; comment?: string },
): Promise<{ request_id: number; feedback_type: string }> {
  const { data } = await apiClient.post(
    `/user/ai/recommendations/${requestId}/feedback`,
    body,
  );
  return data as { request_id: number; feedback_type: string };
}

export async function getRecentDisclosureAiSummaries(
  limit = 10,
): Promise<{
  items: Array<{
    disclosure_id: number;
    receipt_no: string;
    symbol: string;
    symbol_name: string;
    report_name: string;
    status: string;
    summary: string | null;
    generated_at: string | null;
    model_name: string;
  }>;
  total: number;
}> {
  const { data } = await apiClient.get(
    "/user/ai/disclosure-summaries/recent",
    { params: { limit } },
  );
  return data as {
    items: Array<{
      disclosure_id: number;
      receipt_no: string;
      symbol: string;
      symbol_name: string;
      report_name: string;
      status: string;
      summary: string | null;
      generated_at: string | null;
      model_name: string;
    }>;
    total: number;
  };
}

/** STEP 12-1 — AI Candidate -> Strategy Request 승인 게이트 */
export interface StrategyRequestItem {
  strategy_request_id: number;
  candidate_id: number;
  user_id: number;
  reviewer_user_id: number | null;
  status: string;
  candidate_lifecycle_status_snapshot: string;
  request_note: string | null;
  review_note: string | null;
  version: number;
  requested_at: string;
  reviewed_at: string | null;
  cancelled_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface StrategyRequestListResponse {
  items: StrategyRequestItem[];
  total: number;
}

/** 후보(Candidate)의 참조·검증·만료·철회 상태 — 매매 승인을 의미하지 않음 */
export async function getUserAiCandidateLifecycle(
  candidateId: number,
): Promise<JsonValue> {
  const { data } = await apiClient.get(
    `/user/ai-candidates/${candidateId}/lifecycle`,
  );
  return data;
}

export async function createStrategyRequest(body: {
  candidate_id: number;
  request_note?: string;
  correlation_id?: string;
}): Promise<StrategyRequestItem> {
  const { data } = await apiClient.post("/user/strategy-requests", body);
  return data as StrategyRequestItem;
}

export async function listStrategyRequests(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<StrategyRequestListResponse> {
  const { data } = await apiClient.get("/user/strategy-requests", { params });
  return data as StrategyRequestListResponse;
}

export async function getStrategyRequest(
  strategyRequestId: number,
): Promise<StrategyRequestItem> {
  const { data } = await apiClient.get(
    `/user/strategy-requests/${strategyRequestId}`,
  );
  return data as StrategyRequestItem;
}

export async function cancelStrategyRequest(
  strategyRequestId: number,
  body?: { reason?: string; correlation_id?: string },
): Promise<StrategyRequestItem> {
  const { data } = await apiClient.post(
    `/user/strategy-requests/${strategyRequestId}/cancel`,
    body ?? {},
  );
  return data as StrategyRequestItem;
}

/** STEP 12-2-1 — 내 Strategy Request 위의 Strategy Draft 조회(읽기 전용) */
export interface StrategyDraftItem {
  draft_id: number;
  strategy_request_id: number;
  version: number;
  revision: number;
  label: string;
  status: string;
  title: string;
  summary: string | null;
  entry_rule: string | null;
  exit_rule: string | null;
  stop_loss_rule: string | null;
  take_profit_rule: string | null;
  position_sizing_rule: string | null;
  timeframe: string;
  market_type: string;
  risk_parameters: Record<string, unknown> | null;
  indicator_configuration: Record<string, unknown> | null;
  llm_provider: string | null;
  llm_model: string | null;
  prompt_version: string | null;
  candidate_fingerprint: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface StrategyDraftListResponse {
  items: StrategyDraftItem[];
  total: number;
}

export async function listStrategyDrafts(params?: {
  strategy_request_id?: number;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<StrategyDraftListResponse> {
  const { data } = await apiClient.get("/user/strategy-drafts", { params });
  return data as StrategyDraftListResponse;
}

export async function getStrategyDraft(
  draftId: number,
): Promise<StrategyDraftItem> {
  const { data } = await apiClient.get(`/user/strategy-drafts/${draftId}`);
  return data as StrategyDraftItem;
}

/** STEP52 — 로그인 사용자 기본 Paper 계좌 */
export async function getMyPaperAccount(): Promise<JsonValue> {
  const { data } = await apiClient.get("/paper-accounts/me");
  return data;
}

/** STEP65 — 회원 계좌 목록 */
export async function listUserAccounts(params?: {
  default?: boolean;
  include_inactive?: boolean;
}): Promise<UserAccountListResponse> {
  const { data } = await apiClient.get("/user/accounts", { params });
  const payload = data as Partial<UserAccountListResponse> | UserAccount[];
  if (Array.isArray(payload)) {
    return { items: payload, total: payload.length };
  }
  const items = Array.isArray(payload.items) ? payload.items : [];
  return { items, total: payload.total ?? items.length };
}

export async function createUserAccount(
  body: CreateUserAccountRequest,
): Promise<UserAccount> {
  const { data } = await apiClient.post("/user/accounts", body);
  return data as UserAccount;
}

/** STEP 8-5-2 — UBA Credential Vault (원문 Secret 응답 없음) */
export interface BrokerCredentialStatus {
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
  expires_at: string | null;
  verification_message: string | null;
  vault_available: boolean;
}

export interface KiwoomCredentialPayload {
  app_key: string;
  secret_key: string;
  account_number: string;
  account_product_code?: string;
  is_mock?: boolean;
}

export interface UpbitCredentialPayload {
  access_key: string;
  secret_key: string;
}

export async function getUserBrokerCredentialStatus(
  ubaId: number,
): Promise<BrokerCredentialStatus> {
  const { data } = await apiClient.get(
    `/user/accounts/${ubaId}/credentials/status`,
  );
  return data as BrokerCredentialStatus;
}

export async function registerUserBrokerCredential(
  ubaId: number,
  body: KiwoomCredentialPayload | UpbitCredentialPayload,
): Promise<BrokerCredentialStatus> {
  const { data } = await apiClient.post(
    `/user/accounts/${ubaId}/credentials`,
    body,
  );
  return data as BrokerCredentialStatus;
}

export async function replaceUserBrokerCredential(
  ubaId: number,
  body: KiwoomCredentialPayload | UpbitCredentialPayload,
): Promise<BrokerCredentialStatus> {
  const { data } = await apiClient.put(
    `/user/accounts/${ubaId}/credentials`,
    body,
  );
  return data as BrokerCredentialStatus;
}

export async function revokeUserBrokerCredential(
  ubaId: number,
): Promise<BrokerCredentialStatus> {
  const { data } = await apiClient.delete(
    `/user/accounts/${ubaId}/credentials`,
  );
  return data as BrokerCredentialStatus;
}

export async function verifyUserBrokerCredential(
  ubaId: number,
): Promise<BrokerCredentialStatus> {
  const { data } = await apiClient.post(
    `/user/accounts/${ubaId}/credentials/verify`,
    {},
  );
  return data as BrokerCredentialStatus;
}

export async function getUserAccount(
  accountId: number,
  params?: { account_type?: string },
): Promise<UserAccount> {
  const { data } = await apiClient.get(`/user/accounts/${accountId}`, {
    params,
  });
  return data as UserAccount;
}

export async function updateUserAccount(
  accountId: number,
  body: UpdateUserAccountRequest,
): Promise<UserAccount> {
  const { data } = await apiClient.patch(`/user/accounts/${accountId}`, body);
  return data as UserAccount;
}

export async function deleteUserAccount(
  accountId: number,
  params?: { account_type?: string },
): Promise<JsonValue> {
  const { data } = await apiClient.delete(`/user/accounts/${accountId}`, {
    params,
  });
  return data;
}

export async function setDefaultUserAccount(
  accountId: number,
  params?: { account_type?: string },
): Promise<UserAccount> {
  const { data } = await apiClient.post(
    `/user/accounts/${accountId}/set-default`,
    null,
    { params },
  );
  return data as UserAccount;
}

export async function connectUserAccount(
  accountId: number,
  params?: { account_type?: string },
): Promise<UserAccount> {
  const { data } = await apiClient.post(
    `/user/accounts/${accountId}/connect`,
    null,
    { params },
  );
  return data as UserAccount;
}

export async function disconnectUserAccount(
  accountId: number,
  params?: { account_type?: string },
): Promise<UserAccount> {
  const { data } = await apiClient.post(
    `/user/accounts/${accountId}/disconnect`,
    null,
    { params },
  );
  return data as UserAccount;
}

export async function syncUserAccount(
  accountId: number,
  params?: { account_type?: string },
): Promise<UserAccount> {
  const { data } = await apiClient.post(
    `/user/accounts/${accountId}/sync`,
    null,
    { params },
  );
  return data as UserAccount;
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

/** 최신 종가 — 포트폴리오·매매 폴백용 (주식·업비트 공통) */
export async function getLatestPrice(
  exchangeCode: string,
  symbol: string,
): Promise<JsonValue> {
  const { data } = await apiClient.get(
    `/user/market/prices/latest/${exchangeCode}/${symbol}`,
  );
  return data;
}

/** 종목 목록 — 매매·시장정보 화면 검색용 (주식·업비트 공통) */
export async function listMarketSymbols(params?: {
  market?: string;
  active_only?: boolean;
}): Promise<JsonValue> {
  const { data } = await apiClient.get("/user/market/symbols", {
    params: {
      market: params?.market,
      active_only: params?.active_only ?? true,
    },
  });
  return data;
}

/** 일봉 캔들 — 시장정보 화면용 (주식·업비트 공통) */
export async function getDailyCandles(
  exchangeCode: string,
  symbol: string,
  params?: { limit?: number },
): Promise<JsonValue> {
  const { data } = await apiClient.get(
    `/user/market/candles/day/${exchangeCode}/${symbol}`,
    { params },
  );
  return data;
}

/** 일봉 기술지표 — 시장정보 화면용 (주식·업비트 공통) */
export async function getDailyIndicators(
  exchangeCode: string,
  symbol: string,
  params: { start_date: string; end_date: string },
): Promise<JsonValue> {
  const { data } = await apiClient.get(
    `/user/market/indicators/daily/${exchangeCode}/${symbol}`,
    { params },
  );
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

/** 실시간 시세 캐시 조회 (없으면 404, 주식·업비트 공통) */
export async function getRealtimeQuote(
  exchangeCode: string,
  symbol: string,
): Promise<JsonValue> {
  const { data } = await apiClient.get(
    `/user/market/realtime-quotes/${exchangeCode}/${symbol}`,
  );
  return data;
}

export async function getRealtimeQuotesStatus(): Promise<JsonValue> {
  const { data } = await apiClient.get("/realtime-quotes/status");
  return data;
}

export async function getStrategyOpsDashboard(): Promise<JsonValue> {
  const { data } = await apiClient.get(
    "/user/strategies/operations-dashboard",
  );
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

/** STEP 8-5-16 — 본인 계좌 정산 조회 (Backend 계산값만 표시) */
export interface UserSettlement {
  settlement_id: number;
  market_date: string;
  broker_code: string;
  settlement_type: string;
  status_code: string;
  status_label: string;
  needs_manual_review: boolean;
  has_mismatch: boolean;
  realized_pnl: string;
  unrealized_pnl: string;
  fees: string;
  taxes: string;
  net_pnl: string;
  closing_equity: string | null;
  completed_at: string | null;
}

export async function listMySettlements(params?: {
  market_date?: string;
  limit?: number;
}): Promise<{ items: UserSettlement[]; count: number }> {
  const { data } = await apiClient.get("/user/settlements", { params });
  const row = data as { items?: UserSettlement[]; count?: number };
  return {
    items: Array.isArray(row.items) ? row.items : [],
    count: row.count ?? 0,
  };
}

export async function getMySettlement(
  settlementId: number,
): Promise<UserSettlement> {
  const { data } = await apiClient.get(`/user/settlements/${settlementId}`);
  return data as UserSettlement;
}

/** STEP 8-5-17 — Snapshot 상태 (정상/동기화 중/오래됨) */
export interface UserBrokerSnapshotStatus {
  broker_code: string;
  status_label: string;
  is_fresh: boolean;
}

export async function listMyBrokerSnapshotStatus(): Promise<{
  items: UserBrokerSnapshotStatus[];
  count: number;
}> {
  const { data } = await apiClient.get("/user/broker-snapshots");
  const row = data as { items?: UserBrokerSnapshotStatus[]; count?: number };
  return {
    items: Array.isArray(row.items) ? row.items : [],
    count: row.count ?? 0,
  };
}
